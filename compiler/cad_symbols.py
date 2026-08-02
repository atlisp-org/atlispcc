"""CAD stub 符号槽顺序推导（AutoCAD 从右到左收集算法）。

CAD 紧凑 stub 格式按符号槽编址，符号槽注册顺序 = **首次字节码引用序的逆序**：

1. 所有函数名逆序（最后一个函数名在前，槽 0）
2. 函数体符号按"首次字节码引用序"逆序收集（调用内参数先于函数名
   出现在字节码中：`PUSH_G arg… → USUBR func`，故逆序后函数名在前）
3. 唯一参数（只被一个函数使用）随后，共享参数最后
4. 递归/跨函数调用产生重复函数名槽
"""
from compiler.ast import (
    Symbol, String, Integer, Real, ListExpr, QuotedExpr,
    Defun, Setq, IfNode, WhileNode, ForeachNode, RepeatNode, Call, Progn,
    LambdaNode, Cond,
)


class CadSymbolCollector:
    def __init__(self):
        self.names = []
        self.arg_names = set()
        self.forced = set()

    def add(self, name, force=False):
        if name in ('T', 'nil'):
            return
        if force or name not in self.names:
            self.names.append(name)

    @staticmethod
    def _seen(out, name=None):
        if name is None:
            return out
        return any(n == name for n, _ in out)

    def collect_program(self, program):
        defuns = [f for f in program.forms if isinstance(f, Defun)]
        others = [f for f in program.forms if not isinstance(f, Defun)]
        self.func_names = {f.name for f in defuns}
        # 参数使用统计：argname -> 使用它的函数数
        arg_usage: dict = {}
        for f in defuns:
            for a in f.args:
                arg_usage[a] = arg_usage.get(a, 0) + 1
        # 1. 函数名逆序
        for f in reversed(defuns):
            self.add(f.name)
        # 2. 顶层代码（CAD：顶层表达式符号排在函数体内建/参数之前）
        refs = []
        for form in others:
            self._collect_forward(form, refs, set())
        for name, force in reversed(refs):
            self.add(name, force=force)
        # 3. 函数体符号 + 参数：按源码函数逆序，每个函数内"字节码引用序"逆序
        #    （refs 为字节码正序，reversed 后函数名/外层调用在前），参数紧跟其后。
        for f in reversed(defuns):
            arg_names = set(f.args)
            refs = []
            for expr in f.body:
                self._collect_forward(expr, refs, arg_names)
            for name, force in reversed(refs):
                self.add(name, force=force)
            for arg in f.args:
                if arg not in self.names:
                    self.add(arg)
            for loc in reversed(f.locals):
                self.add(loc)
        # CAD 顶层表达式符号槽为源码逆序：先注册最后一个顶层表达式的符号。
        # _collect_forward 已按"值在前、变量在后"收集（如 setq a "x" → "x",a），
        # reversed 后即 a,"x"（变量在值前）。多表达式时整体逆序。
        return self.names

    def _collect_forward(self, node, out, arg_names):
        """按字节码首次引用序向前收集 (name, forced) 列表。"""
        if isinstance(node, Symbol):
            if node.name not in arg_names and not self._seen(out, node.name):
                out.append((node.name, False))
        elif isinstance(node, Call):
            for a in node.args:
                self._collect_forward(a, out, arg_names)
            if node.name in self.func_names:
                # 递归/跨函数调用：首次引用分配重复槽（CAD 行为）
                out.append((node.name, True))
            elif node.name not in arg_names and not self._seen(out, node.name):
                out.append((node.name, False))
        elif isinstance(node, Setq):
            for target, value in node.pairs:
                if value:
                    self._collect_forward(value, out, arg_names)
                if isinstance(target, Symbol):
                    if target.name not in arg_names and not self._seen(out, target.name):
                        out.append((target.name, False))
                else:
                    self._collect_forward(target, out, arg_names)
        elif isinstance(node, IfNode):
            if node.cond:
                self._collect_forward(node.cond, out, arg_names)
            if node.then:
                self._collect_forward(node.then, out, arg_names)
            if node.else_expr:
                self._collect_forward(node.else_expr, out, arg_names)
        elif isinstance(node, WhileNode):
            out.append(("while", False))
            if node.cond:
                self._collect_forward(node.cond, out, arg_names)
            for expr in node.body:
                self._collect_forward(expr, out, arg_names)
        elif isinstance(node, Progn):
            for form in node.forms:
                self._collect_forward(form, out, arg_names)
        elif isinstance(node, ForeachNode):
            out.append(("foreach", False))
            for expr in node.body:
                self._collect_forward(expr, out, arg_names)
            if node.list_expr:
                self._collect_forward(node.list_expr, out, arg_names)
            if node.var is not None:
                self._collect_forward(node.var, out, arg_names)
        elif isinstance(node, RepeatNode):
            out.append(("repeat", False))
            for expr in node.body:
                self._collect_forward(expr, out, arg_names)
            if node.count:
                self._collect_forward(node.count, out, arg_names)
        elif isinstance(node, Cond):
            for clause in node.clauses:
                for item in clause:
                    self._collect_forward(item, out, arg_names)
        elif isinstance(node, ListExpr):
            for item in node.items:
                self._collect_forward(item, out, arg_names)
        elif isinstance(node, QuotedExpr):
            if node.expr:
                if isinstance(node.expr, ListExpr) and len(node.expr.items) >= 2 and isinstance(node.expr.items[0], Symbol) and node.expr.items[0].name == 'lambda':
                    if isinstance(node.expr.items[1], ListExpr):
                        lambda_args = set()
                        for item in node.expr.items[1].items:
                            if isinstance(item, Symbol):
                                lambda_args.add(item.name)
                        self._collect_forward(node.expr, out, arg_names | lambda_args)
                        return
                self._collect_forward(node.expr, out, arg_names)
        elif isinstance(node, LambdaNode):
            out.append(("lambda", False))
            lambda_args = set(node.args)
            for expr in node.body:
                self._collect_forward(expr, out, arg_names | lambda_args)
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
