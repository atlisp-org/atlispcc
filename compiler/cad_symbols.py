"""CAD stub 符号槽顺序推导（AutoCAD 24.1s 实测逆向）。

CAD 紧凑 stub 格式按符号槽编址。符号槽注册顺序按文件结构分两套：

**多函数文件**（≥2 个 defun，样本 m2/m3/cross/sh/multi/f4*/f5 实测）：
1. 所有函数名逆序（最后一个函数名在前，槽 0）——模块注册域
2. 函数体符号按**字节码首次引用序**（后序：先内层调用后外层函数名，即
   USUBR 出现序）逐函数收集，源函数序拼接、先到先得去重后**整体逆序**；
   逆序后每函数引用组连续（源逆序），其唯一参数按逆序紧跟组末
3. **共享参数**（被多个函数使用）推迟到最后统一注册；递归/跨函数调用函数名
   由调用者引用组登记（模块注册域已占位，函数名重复槽；递归名不重复）

**单函数文件**（≤1 个 defun，fact/sf_cond/fun 实测）：
按"字节码引用序逆序"收集：函数体符号按字节码首次引用序的反向注册
（调用内参数先于函数名出现在字节码中：PUSH_G arg… → USUBR func，逆序后
函数名在前），参数（含共享）放最后；递归函数名产生重复槽但不提前。

逆向来源：samples/cad-compare/（m2/m3/cross/sh/multi 的 CAD 官方产物）与
tests/（fact/fun/sf_cond/mix 的 CAD 官方产物）。
"""
from compiler.ast import (
    Symbol, String, Integer, Real, ListExpr, QuotedExpr,
    Defun, Setq, IfNode, WhileNode, ForeachNode, RepeatNode, Call, Progn,
    LambdaNode, Cond,
)

CONST_MARK = '__const__'


def to_const(node):
    """把引用的字面量节点规范化为常量结构元组；不可常量化的返回 None。

    CAD 把 ``'(lambda ...)`` 等引用字面量注册为资源段常量（值在加载期由
    资源流 BUILD_LIST 构建），字节码只发一条 ``PUSH_G``。结构与资源流
    记录一一对应：('SYMBOL', name) / ('INT', v) / ('REAL', v) /
    ('STRING', s) / ('LIST', (item, ...)) / ('NIL',) / ('T',)。
    """
    if isinstance(node, Symbol):
        if node.name == 'T':
            return ('T',)
        if node.name == 'nil':
            return ('NIL',)
        return ('SYMBOL', node.name)
    if isinstance(node, Integer):
        return ('INT', node.value)
    if isinstance(node, Real):
        return ('REAL', node.value)
    if isinstance(node, String):
        return ('STRING', node.value)
    if isinstance(node, LambdaNode):
        params = ('LIST', tuple(('SYMBOL', a) for a in node.args))
        body = tuple(to_const(b) for b in node.body)
        if any(b is None for b in body):
            return None
        return ('LIST', (('SYMBOL', 'lambda'), params) + body)
    if isinstance(node, ListExpr):
        if node.dotted is not None:
            return None
        items = tuple(to_const(i) for i in node.items)
        if any(i is None for i in items):
            return None
        return ('LIST', items)
    if isinstance(node, Call):
        items = (to_const(Symbol(node.name)),) + tuple(to_const(a) for a in node.args)
        if any(i is None for i in items):
            return None
        return ('LIST', items)
    return None


def is_const_entry(item):
    return isinstance(item, tuple) and len(item) == 2 and item[0] == CONST_MARK


class CadSymbolCollector:
    def __init__(self):
        self.names = []
        self.shared = set()
        self.deferred = []
        self.func_names = set()

    def add(self, name, force=False):
        if is_const_entry(name):
            structure = name[1]
            if force or not any(is_const_entry(n) and n[1] == structure for n in self.names):
                self.names.append(name)
            return
        if name in ('T', 'nil'):
            return
        if force or name not in self.names:
            self.names.append(name)

    @staticmethod
    def _seen(out, name=None):
        if name is None:
            return out
        if is_const_entry(name):
            structure = name[1]
            return any(is_const_entry(n) and n[1] == structure for n, _ in out)
        return any(n == name for n, _ in out)

    def collect_program(self, program):
        defuns = [f for f in program.forms if isinstance(f, Defun)]
        others = [f for f in program.forms if not isinstance(f, Defun)]
        self.func_names = {f.name for f in defuns}
        # 参数使用统计：argname -> 使用它的函数数（共享参数判定）
        arg_usage: dict = {}
        for f in defuns:
            for a in f.args:
                arg_usage[a] = arg_usage.get(a, 0) + 1
        self.shared = {a for a, c in arg_usage.items() if c > 1}
        self.deferred = []

        if len(defuns) <= 1:
            return self._collect_single(defuns, others)

        # 1. 函数名逆序（模块注册域）
        for f in reversed(defuns):
            self.add(f.name)

        # 2. 顶层代码（CAD：顶层表达式符号排在函数体内建/参数之前）
        refs = []
        for form in others:
            self._collect_forward(form, refs, set())
        for name, force in refs:
            self.add(name, force=force)

        # 3. 函数体符号：按字节码引用序收集，逆序注册；唯一参数紧跟所属函数，
        #    共享参数最后。CAD 实测（f4/f4b/f4c/f4d/f4e/f4x/f4r/f5/m3/cross/sh）：
        #    函数体内符号按"字节码首次引用序"（后序：先内层调用后外层函数名，
        #    即 USUBR 出现序）逐函数收集，源函数序拼接、先到先得去重后整体逆序；
        #    逆序后每函数引用组连续（源逆序），其唯一参数按逆序紧跟组末，
        #    跨函数共享参数推迟到最后统一注册。链式/递归交叉调用下函数名
        #    由调用者引用组登记（递归名不重复槽）。
        seen_refs = set()
        kept_refs = []
        for f in defuns:
            refs = []
            arg_names = set(f.args)
            for expr in f.body:
                self._collect_byteorder(expr, refs, arg_names)
            kept = [(n, fr) for n, fr in refs if n not in seen_refs]
            seen_refs.update(n for n, _ in refs)
            kept_refs.append(kept)

        for f, kept in zip(reversed(defuns), reversed(kept_refs)):
            for name, force in reversed(kept):
                self.add(name, force=force)
            for arg in reversed(f.args):
                if arg in self.shared:
                    if arg not in self.deferred:
                        self.deferred.append(arg)
                elif arg not in self.names:
                    self.add(arg)
            for loc in reversed(f.locals):
                self.add(loc)

        # 4. 共享参数最后（CAD：跨函数共享的局部变量槽排末尾）
        for arg in self.deferred:
            if arg not in self.names:
                self.add(arg)
        return self.names

    def _collect_single(self, defuns, others):
        """单函数文件（≤1 defun）：字节码引用序逆序收集（CAD fact/sf_cond 实测）。

        函数体符号按首次字节码引用序的逆序注册（调用内参数先于函数名出现在
        字节码中：PUSH_G arg… → USUBR func，逆序后函数名在前），参数（含共享）
        放最后；递归函数名产生重复槽但不提前。
        """
        # 1. 函数名逆序（模块注册域）
        for f in reversed(defuns):
            self.add(f.name)

        # 2. 顶层代码（CAD：顶层表达式符号排在函数体内建/参数之前，源码逆序）
        refs = []
        for form in others:
            self._collect_byteorder(form, refs, set())
        for name, force in reversed(refs):
            self.add(name, force=force)

        # 3. 函数体符号：字节码引用序正序收集，逆序注册；参数最后（共享不特殊处理）
        for f in reversed(defuns):
            arg_names = set(f.args)
            refs = []
            for expr in f.body:
                self._collect_byteorder(expr, refs, arg_names)
            for name, force in reversed(refs):
                self.add(name, force=force)
            for arg in f.args:
                if arg not in self.names:
                    self.add(arg)
            for loc in reversed(f.locals):
                self.add(loc)
        return self.names

    def _collect_byteorder(self, node, out, arg_names):
        """按字节码首次引用序向前收集 (name, forced) 列表（单函数算法）。"""
        if isinstance(node, Symbol):
            if node.name not in arg_names and not self._seen(out, node.name):
                out.append((node.name, False))
        elif isinstance(node, Call):
            for a in node.args:
                self._collect_byteorder(a, out, arg_names)
            if node.name in self.func_names:
                out.append((node.name, True))
            elif node.name not in arg_names and not self._seen(out, node.name):
                out.append((node.name, False))
        elif isinstance(node, Setq):
            for target, value in node.pairs:
                if value:
                    self._collect_byteorder(value, out, arg_names)
                if isinstance(target, Symbol):
                    if target.name not in arg_names and not self._seen(out, target.name):
                        out.append((target.name, False))
                else:
                    self._collect_byteorder(target, out, arg_names)
        elif isinstance(node, IfNode):
            if node.cond:
                self._collect_byteorder(node.cond, out, arg_names)
            if node.then:
                self._collect_byteorder(node.then, out, arg_names)
            if node.else_expr:
                self._collect_byteorder(node.else_expr, out, arg_names)
        elif isinstance(node, WhileNode):
            out.append(("while", False))
            if node.cond:
                self._collect_byteorder(node.cond, out, arg_names)
            for expr in node.body:
                self._collect_byteorder(expr, out, arg_names)
        elif isinstance(node, Progn):
            for form in node.forms:
                self._collect_byteorder(form, out, arg_names)
        elif isinstance(node, ForeachNode):
            out.append(("foreach", False))
            for expr in node.body:
                self._collect_byteorder(expr, out, arg_names)
            if node.list_expr:
                self._collect_byteorder(node.list_expr, out, arg_names)
            if node.var is not None:
                self._collect_byteorder(node.var, out, arg_names)
        elif isinstance(node, RepeatNode):
            out.append(("repeat", False))
            for expr in node.body:
                self._collect_byteorder(expr, out, arg_names)
            if node.count:
                self._collect_byteorder(node.count, out, arg_names)
        elif isinstance(node, Cond):
            for clause in node.clauses:
                for item in clause:
                    self._collect_byteorder(item, out, arg_names)
        elif isinstance(node, ListExpr):
            for item in node.items:
                self._collect_byteorder(item, out, arg_names)
        elif isinstance(node, QuotedExpr):
            if node.expr is not None:
                const = to_const(node.expr)
                if const is not None:
                    out.append(((CONST_MARK, const), False))
                else:
                    self._collect_byteorder(node.expr, out, arg_names)
        elif isinstance(node, LambdaNode):
            const = to_const(node)
            if const is not None:
                out.append(((CONST_MARK, const), False))
            else:
                out.append(("lambda", False))
                lambda_args = set(node.args)
                for expr in node.body:
                    self._collect_byteorder(expr, out, arg_names | lambda_args)
        elif isinstance(node, String):
            if not self._seen(out, '"' + node.value + '"'):
                out.append(('"' + node.value + '"', False))
        elif isinstance(node, (Integer, Real)):
            pass

    def _collect_forward(self, node, out, locals_):
        """深度优先收集符号 (name, forced) 列表。

        调用：函数名在前，参数按源码逆序展开。
        """
        if isinstance(node, Symbol):
            if node.name in self.shared or node.name in locals_:
                return
            if not self._seen(out, node.name):
                out.append((node.name, False))
        elif isinstance(node, Call):
            if node.name in self.func_names:
                out.append((node.name, True))
            elif node.name not in locals_ and not self._seen(out, node.name):
                out.append((node.name, False))
            for a in reversed(node.args):
                self._collect_forward(a, out, locals_)
        elif isinstance(node, Setq):
            for target, value in node.pairs:
                if value:
                    self._collect_forward(value, out, locals_)
                if isinstance(target, Symbol):
                    if target.name not in locals_ and not self._seen(out, target.name):
                        out.append((target.name, False))
                else:
                    self._collect_forward(target, out, locals_)
        elif isinstance(node, IfNode):
            if node.cond:
                self._collect_forward(node.cond, out, locals_)
            if node.then:
                self._collect_forward(node.then, out, locals_)
            if node.else_expr:
                self._collect_forward(node.else_expr, out, locals_)
        elif isinstance(node, WhileNode):
            out.append(("while", False))
            if node.cond:
                self._collect_forward(node.cond, out, locals_)
            for expr in node.body:
                self._collect_forward(expr, out, locals_)
        elif isinstance(node, Progn):
            for form in node.forms:
                self._collect_forward(form, out, locals_)
        elif isinstance(node, ForeachNode):
            out.append(("foreach", False))
            for expr in node.body:
                self._collect_forward(expr, out, locals_)
            if node.list_expr:
                self._collect_forward(node.list_expr, out, locals_)
            if node.var is not None:
                self._collect_forward(node.var, out, locals_)
        elif isinstance(node, RepeatNode):
            out.append(("repeat", False))
            for expr in node.body:
                self._collect_forward(expr, out, locals_)
            if node.count:
                self._collect_forward(node.count, out, locals_)
        elif isinstance(node, Cond):
            for clause in node.clauses:
                for item in clause:
                    self._collect_forward(item, out, locals_)
        elif isinstance(node, ListExpr):
            for item in node.items:
                self._collect_forward(item, out, locals_)
        elif isinstance(node, QuotedExpr):
            if node.expr is not None:
                const = to_const(node.expr)
                if const is not None:
                    out.append(((CONST_MARK, const), False))
                else:
                    self._collect_forward(node.expr, out, locals_)
        elif isinstance(node, LambdaNode):
            const = to_const(node)
            if const is not None:
                out.append(((CONST_MARK, const), False))
            else:
                out.append(("lambda", False))
                lambda_args = set(node.args)
                for expr in node.body:
                    self._collect_forward(expr, out, locals_ | lambda_args)
        elif isinstance(node, String):
            if not self._seen(out, '"' + node.value + '"'):
                out.append(('"' + node.value + '"', False))
        elif isinstance(node, (Integer, Real)):
            pass


def derive_symbol_names(program):
    """返回与 CAD 一致的符号槽顺序列表。

    字符串以 ``"value"`` 形式表示（含引号），符号为普通名字。
    """
    coll = CadSymbolCollector()
    return coll.collect_program(program)
