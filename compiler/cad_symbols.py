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
from compiler.ast_nodes import (
    Symbol, String, Integer, Real, ListExpr, QuotedExpr,
    Defun, Setq, IfNode, WhileNode, ForeachNode, RepeatNode, Call, Progn,
    LambdaNode, Cond, Defpackage, InPackage,
)

CONST_MARK = '__const__'


def strip_docstring(body):
    """CAD 忽略 defun 后第一个裸字符串（docstring）。

    `(defun f () "文档说明" ...)` 编译时丢弃该字符串（AutoLISP 惯例，
    docstr.fas CAD 实测 strings 为空）。仅当它是函数体**首个**独立字符串
    字面量时返回剥离后的列表；空体或仅 docstring 时返回原列表（保持空体）。
    """
    if len(body) > 1 and isinstance(body[0], String):
        return body[1:]
    return body


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
        # CAD 把 dotted 引用 `'(1 . 2)` 编译为普通列表常量 `(1 2)`
        # （resource 流 `INT8 1; INT8 2; BUILD_LIST 2`，t12_quote 实测）。
        items = tuple(to_const(i) for i in node.items)
        if any(i is None for i in items):
            return None
        if node.dotted is not None:
            d = to_const(node.dotted)
            if d is None:
                return None
            items = items + (d,)
            # dotted 引用 `'(a . b)`：CAD 以 `2a`(LIST_END) 收尾而非
            # `39 <count>`（t12_quote 实测），需标记以便 _emit_const 正确编码。
            return ('LIST', items, True)
        if not items:
            # 空列表 `'()` = nil：CAD 用 PUSH_NIL(01) 而非 BUILD_LIST 0
            # （i18n_v2 顶层 `'()` 实测），避免多占一个 gvar 槽。
            return ('NIL',)
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

        if len(defuns) <= 1:
            return self._collect_single(defuns, others, program)

        # 1. 模块注册域（CAD：按源码逆序逐 form 交错，defun 与顶层表达式均参与）。
        #    defun → 函数名；顶层 → 其字节码引用符号（逆序）。混合模式
        #    （i18n）下顶层表达式与 defun 按源码逆序交错，最后出现的顶层
        #    `(set '_ @::_)` 的 `_` 排在模块注册最前（i18n-cad 实测）。
        #    纯函数文件（无顶层）退化为"函数名逆序"，与多函数实测一致。
        self._register_module(program)

        # 3. 函数体符号：按字节码引用序收集，逆序注册；唯一参数紧跟所属函数，
        #    共享参数注册在其源码序最先使用的函数之后。CAD 实测
        #    （f4/f4b/f4c/f4d/f4e/f4x/f4r/f5/m3/cross/sh/multi/rt_e/t15）：
        #    函数体内符号按"字节码首次引用序"（后序：先内层调用后外层函数名，
        #    即 USUBR 出现序）逐函数收集，源函数序拼接、先到先得去重后整体逆序；
        #    逆序后每函数引用组连续（源逆序），其唯一参数按逆序紧跟组末；
        #    跨函数共享参数注册在**源码序最先使用它的函数**（逆序迭代最后一个
        #    使用者）之后——multi 中 a/b 最先被源码第 0 个函数 add 使用，槽序
        #    排末尾；t15 中 p1/p2 最先被 get-dist（源码第 1 个）使用，槽序 =
        #    …DISTANCE, P2, P1, GETPOINT, STRING。链式/递归交叉调用下函数名
        #    由调用者引用组登记（递归名不重复槽）。
        seen_refs = set()
        kept_refs = []
        for f in defuns:
            refs = []
            arg_names = set(f.args)
            for expr in strip_docstring(f.body):
                self._collect_byteorder(expr, refs, arg_names)
            # 同一函数内对函数名的多次调用共享同一个重复槽（t09 中 sum-of-squares
            # 两次调用 square 仅 1 个重复 SQUARE 槽；CAD 实测）。
            seen_forced = set()
            intra_dedup = []
            for name, fr in refs:
                if fr and name in seen_forced:
                    continue
                intra_dedup.append((name, fr))
                if fr:
                    seen_forced.add(name)
            kept = [(n, fr) for n, fr in intra_dedup if n not in seen_refs]
            seen_refs.update(n for n, _ in intra_dedup)
            kept_refs.append(kept)

        nfuncs = len(defuns)
        # 每个共享参数：记录源码序最先使用它的函数索引（逆序迭代最后处理到）。
        shared_first_user = {}
        for i, f in enumerate(defuns):
            for arg in f.args:
                if arg in self.shared and arg not in shared_first_user:
                    shared_first_user[arg] = i

        # 混合模式（defun + 顶层表达式）下，模块注册已含顶层符号；函数体符号
        # 若与模块注册符号同名，需作为重复槽**强制**再注册（t10_init 实测
        # `*VERSION* PRINC` 在模块段与函数体段各出现一次）。纯函数文件不受影响
        # （模块注册仅函数名，函数体符号本就独立）。
        module_reg_names = set(self.names)
        # `_al-bind-alist` 共享槽注册在**源码序第一个**带 `/ 局部变量` 的函数
        # （逆序迭代最后一个 local 函数 = `@::update-locale`），而非第一个遍历到
        # 的 local 函数（i18n-cad 实测 slot 121 在 @::update-locale 区）。其余
        # local 函数不重复注册 `_al-bind-alist`（共享，codegen 按符号名取回）。
        source_first_local = next((f for f in defuns if f.locals), None)
        for i, (f, kept) in enumerate(zip(reversed(defuns), reversed(kept_refs))):
            for name, force in reversed(kept):
                self.add(name, force=force or name in module_reg_names)
            # CAD `/ 局部变量`（多函数）：与单函数一致注入 `_al-bind-alist` +
            # `(quote (locals...))` 常量；`_al-bind-alist` 全文件共享一个符号槽
            # （i18n-cad 实测仅 1 个 `_al-bind-alist`），locals 常量每函数独立。
            # i18n-cad 实测槽序：`_al-bind-alist` → locals 常量 → 局部变量 →
            # 参数（@::update-locale: `_al-bind-alist (LOC-FILE) LOC-FILE PKG-NAME`）。
            if f.locals:
                if f is source_first_local:
                    self.add('_al-bind-alist')
                self.add((CONST_MARK, ('LIST', tuple(('SYMBOL', l) for l in f.locals))))
            for loc in reversed(f.locals):
                self.add(loc)
            for arg in reversed(f.args):
                if arg in self.shared:
                    # 逆序迭代索引 i 对应源码索引 nfuncs-1-i。
                    if shared_first_user.get(arg) == nfuncs - 1 - i:
                        self.add(arg)
                elif arg not in self.names:
                    self.add(arg)

        return self.names

    def _collect_single(self, defuns, others, program):
        """单函数文件（≤1 defun）：模块注册与函数体符号按 CAD 序收集。

        函数体符号按首次字节码引用序的逆序注册（调用内参数先于函数名出现在
        字节码中：PUSH_G arg… → USUBR func，逆序后函数名在前），参数（含共享）
        放最后；递归函数名产生重复槽但不提前。
        """
        # 模块注册域：有 defun 时（含纯函数与混合模式）CAD 按源码逆序逐 form
        # 交错注册（顶层符号可能穿插在 defun 名前后）。纯顶层文件（无 defun）
        # 退化为：函数名字段为空 + 顶层 refs 全局逆序（setcmp/set5/setqa 实测）。
        if program and defuns:
            self._register_module(program)
        elif others:
            # 纯顶层文件：顶层 refs 按字节码引用序收集后全局逆序注册。
            refs = []
            for form in others:
                self._collect_byteorder(form, refs, set())
            for name, force in reversed(refs):
                self.add(name, force=force)

        # 3. 函数体符号：字节码引用序正序收集，逆序注册；参数最后（共享不特殊处理）。
        #    CAD 单函数参数槽逆序（实测 simple3/t13：`+ Z Y X`、`> C B A`——
        #    最后一个声明的参数槽最小，紧跟函数体符号）。
        #    递归函数名：多次自身调用共享同一个重复槽（t03 递归两次仅 1 个重复
        #    FIB 槽；fact 递归一次 1 个重复槽）。
        for f in reversed(defuns):
            arg_names = set(f.args)
            refs = []
            for expr in strip_docstring(f.body):
                self._collect_byteorder(expr, refs, arg_names)
            seen_forced = set()
            deduped = []
            for name, force in refs:
                if force and name in seen_forced:
                    continue
                deduped.append((name, force))
                if force:
                    seen_forced.add(name)
            for name, force in reversed(deduped):
                self.add(name, force=force)
            # CAD `/ 局部变量`：注入 `_al-bind-alist` 助手符号与局部变量引用
            # 常量 `(quote (locals...))`，紧跟函数体符号之后、参数之前
            # （t11_localvars 实测：`+ <= I RESULT _al-bind-alist (RESULT I) N`）。
            if f.locals:
                self.add('_al-bind-alist')
                self.add((CONST_MARK, ('LIST', tuple(('SYMBOL', l) for l in f.locals))))
            for arg in reversed(f.args):
                if arg not in self.names:
                    self.add(arg)
            for loc in reversed(f.locals):
                self.add(loc)
        return self.names

    def _register_module(self, program):
        """模块注册域：按源码逆序逐 form 交错注册（defun 与顶层表达式均参与）。

        defun → 函数名；顶层 → _collect_byteorder 字节码引用符号（逆序注册）。
        混合模式（i18n）下顶层表达式与 defun 按源码逆序交错：位于源码尾部
        的顶层 form 其符号排在模块注册最前（i18n-cad/p03 实测：
        `(setq @::*codepage* (vl-catch-all-apply ...))` 在 defun 之后，其符号
        @::*CODEPAGE* VL-CATCH-ALL-APPLY syscodepage GETVAR 排在 @::CODEPAGE2LANG
        之前）。纯函数文件（无顶层）退化为"函数名逆序"。
        顶层 form 里的用户函数名调用（force=True）不另发槽——并入 defun
        槽（p04 实测 form4 调用 @::codepage2lang 不占顶层组）。
        """
        forms_all = [f for f in program.forms
                     if not isinstance(f, (Defpackage, InPackage))]
        n = len(forms_all)
        reads, targets = [], []
        for i, form in enumerate(forms_all):
            r, t = set(), set()
            if isinstance(form, Defun):
                t.add(form.name)
            else:
                self._form_read_target(form, r, t, set())
            reads.append(r)
            targets.append(t)
        # 符号归属：setq 目标优先 → 最早赋值的 form；否则 → 最早读取的 form。
        # CAD p05/p06/p07 实测：`@::*LANG*` 既是 form0 `(setq @::*lang* ...)`
        # 的目标，又被末尾 `(null @::*lang*)` 读取——槽归属到目标 form0
        # （排在 pre-form 组尾部），而非读取它的 post-form。
        owner_read = {}
        owner_target = {}
        for i in range(n):
            for s in targets[i]:
                if s not in owner_target:
                    owner_target[s] = i
            for s in reads[i]:
                if s not in owner_read:
                    owner_read[s] = i
        ancestor = {}

        def _owner_of(sym):
            if sym in owner_target:
                return owner_target[sym]
            if sym in owner_read:
                return owner_read[sym]
            return -1

        module_seen = set()
        for i in reversed(range(n)):
            form = forms_all[i]
            if isinstance(form, Defun):
                if _owner_of(form.name) == i and form.name not in module_seen:
                    module_seen.add(form.name)
                    self.add(form.name)
            else:
                form_refs = []
                self._collect_byteorder(form, form_refs, set())
                for name, force in reversed(form_refs):
                    # 顶层符号调用（force=True）不登记槽——并入 defun 槽
                    # （CAD p04 form4 cadr/not/codepage 组无 c2l）。
                    if force:
                        continue
                    # 符号由"归属 form"独占登记，其它 form 引用不重复发槽
                    # （CAD p04：lang 属 form0 被放尾部，codepage 属 form3）。
                    if _owner_of(name) != i:
                        continue
                    if is_const_entry(name):
                        if name[1] in (('NIL',), ('T',)):
                            # NIL/T 由 PUSH_NIL/PUSH_T 内建编码，不占常量槽
                            # （CAD i18n golden 无 NIL/T 槽）。
                            continue
                        self.add(name, force=force)
                    elif name not in module_seen:
                        module_seen.add(name)
                        self.add(name, force=force)

    def _form_read_target(self, node, reads, targets, arg_names, in_quote=False):
        """收集 form 的 读(value)/setq目标(target) 符号集合（模块归属用）。"""
        if isinstance(node, Symbol):
            if node.name not in arg_names:
                reads.add(node.name)
        elif isinstance(node, Call):
            for a in node.args:
                self._form_read_target(a, reads, targets, arg_names, in_quote)
            if node.name not in self.func_names:
                reads.add(node.name)
        elif isinstance(node, Setq):
            for target, value in node.pairs:
                if value:
                    self._form_read_target(value, reads, targets, arg_names, in_quote)
                if isinstance(target, Symbol) and target.name not in arg_names:
                    targets.add(target.name)
                else:
                    self._form_read_target(target, reads, targets, arg_names, in_quote)
        elif isinstance(node, IfNode):
            for part in (node.cond, node.then, node.else_expr):
                if part:
                    self._form_read_target(part, reads, targets, arg_names, in_quote)
        elif isinstance(node, WhileNode):
            if node.cond:
                self._form_read_target(node.cond, reads, targets, arg_names, in_quote)
            for expr in node.body:
                self._form_read_target(expr, reads, targets, arg_names, in_quote)
        elif isinstance(node, Progn):
            for form in node.forms:
                self._form_read_target(form, reads, targets, arg_names, in_quote)
        elif isinstance(node, ForeachNode):
            for expr in node.body:
                self._form_read_target(expr, reads, targets, arg_names, in_quote)
            if node.list_expr:
                self._form_read_target(node.list_expr, reads, targets, arg_names, in_quote)
            if node.var is not None:
                self._form_read_target(node.var, reads, targets, arg_names, in_quote)
        elif isinstance(node, RepeatNode):
            for expr in node.body:
                self._form_read_target(expr, reads, targets, arg_names, in_quote)
            if node.count:
                self._form_read_target(node.count, reads, targets, arg_names, in_quote)
        elif isinstance(node, Cond):
            for clause in node.clauses:
                for item in clause:
                    self._form_read_target(item, reads, targets, arg_names, in_quote)
        elif isinstance(node, ListExpr):
            for item in node.items:
                self._form_read_target(item, reads, targets, arg_names, in_quote)
        elif isinstance(node, QuotedExpr):
            if node.expr is not None:
                if isinstance(node.expr, Symbol) and node.expr.name not in ('T', 'nil'):
                    if node.expr.name not in arg_names:
                        reads.add(node.expr.name)
                elif to_const(node.expr) is not None:
                    reads.add((CONST_MARK, to_const(node.expr)))
                else:
                    self._form_read_target(node.expr, reads, targets, arg_names, True)
        elif isinstance(node, LambdaNode):
            if to_const(node) is not None:
                reads.add((CONST_MARK, to_const(node)))
            else:
                for expr in node.body:
                    self._form_read_target(expr, reads, targets, arg_names | set(node.args), in_quote)
        elif isinstance(node, String):
            reads.add('"' + node.value + '"')

    def _collect_byteorder(self, node, out, arg_names, in_quote=False):
        """按字节码首次引用序向前收集 (name, forced) 列表（单函数算法）。"""
        if isinstance(node, Symbol):
            if node.name not in arg_names and not self._seen(out, node.name):
                out.append((node.name, False))
        elif isinstance(node, Call):
            for a in node.args:
                self._collect_byteorder(a, out, arg_names, in_quote)
            if node.name in ('and', 'or'):
                # CAD 短路 and/or：编译为 JMP16 指令，不注册符号槽
                # （i18n-cad 实测无 AND/OR 符号）。
                pass
            elif node.name in self.func_names:
                out.append((node.name, True))
            elif node.name not in arg_names and not self._seen(out, node.name):
                out.append((node.name, False))
        elif isinstance(node, Setq):
            for target, value in node.pairs:
                if value:
                    self._collect_byteorder(value, out, arg_names, in_quote)
                if isinstance(target, Symbol):
                    if target.name not in arg_names and not self._seen(out, target.name):
                        out.append((target.name, False))
                else:
                    self._collect_byteorder(target, out, arg_names, in_quote)
        elif isinstance(node, IfNode):
            # quoted 数据里 `(if ...)` 的 `if` 是符号（CAD 收集 IF，
            # i18n-cad 实测 save-mt `'((if ...))` 收集 IF）；正常代码用条件指令不收集。
            if in_quote and not self._seen(out, 'if'):
                out.append(('if', False))
            if node.cond:
                self._collect_byteorder(node.cond, out, arg_names, in_quote)
            if node.then:
                self._collect_byteorder(node.then, out, arg_names, in_quote)
            if node.else_expr:
                self._collect_byteorder(node.else_expr, out, arg_names, in_quote)
        elif isinstance(node, WhileNode):
            if node.cond:
                self._collect_byteorder(node.cond, out, arg_names, in_quote)
            for expr in node.body:
                self._collect_byteorder(expr, out, arg_names, in_quote)
        elif isinstance(node, Progn):
            for form in node.forms:
                self._collect_byteorder(form, out, arg_names, in_quote)
        elif isinstance(node, ForeachNode):
            for expr in node.body:
                self._collect_byteorder(expr, out, arg_names, in_quote)
            if node.list_expr:
                self._collect_byteorder(node.list_expr, out, arg_names, in_quote)
            if node.var is not None:
                self._collect_byteorder(node.var, out, arg_names, in_quote)
        elif isinstance(node, RepeatNode):
            for expr in node.body:
                self._collect_byteorder(expr, out, arg_names, in_quote)
            if node.count:
                self._collect_byteorder(node.count, out, arg_names, in_quote)
        elif isinstance(node, Cond):
            # CAD cond 字节码：测试体按源码序发出（各子句条件），结果体按源码
            # 倒序发出（末子句体最先）。符号引用序 = 测试正序 + 结果倒序
            # （t05_cond 实测：> < T zero positive negative）。
            clauses = [c for c in node.clauses if c]
            for clause in clauses:
                if clause:
                    self._collect_byteorder(clause[0], out, arg_names, in_quote)
            for clause in reversed(clauses):
                for item in clause[1:]:
                    self._collect_byteorder(item, out, arg_names, in_quote)
        elif isinstance(node, ListExpr):
            for item in node.items:
                self._collect_byteorder(item, out, arg_names, in_quote)
        elif isinstance(node, QuotedExpr):
            if node.expr is not None:
                # CAD 引用单符号 `'a`：编译为 PUSH_G 普通符号槽，不注册
                # CONST（setcmp/setqa 实测 `(set 'a 5)` 的 A、`(setq x 'a)`
                # 的 A 均为普通 SYMBOL 槽）。仅列表/lambda/dotted 等复合
                # 结构才 const 化。
                if isinstance(node.expr, Symbol) and node.expr.name not in ('T', 'nil'):
                    if node.expr.name not in arg_names and not self._seen(out, node.expr.name):
                        out.append((node.expr.name, False))
                else:
                    const = to_const(node.expr)
                    if const is not None:
                        out.append(((CONST_MARK, const), False))
                    else:
                        # 不可常量化的 quoted 表达式运行时拆开构建：其内部
                        # `(if ...)` 等特殊形式的 `if` 作为数据符号收集。
                        self._collect_byteorder(node.expr, out, arg_names, in_quote=True)
        elif isinstance(node, LambdaNode):
            const = to_const(node)
            if const is not None:
                out.append(((CONST_MARK, const), False))
            else:
                out.append(("lambda", False))
                lambda_args = set(node.args)
                for expr in node.body:
                    self._collect_byteorder(expr, out, arg_names | lambda_args, in_quote)
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
                # CAD 引用单符号 `'a`：普通符号槽（PUSH_G），非 CONST。
                if isinstance(node.expr, Symbol) and node.expr.name not in ('T', 'nil'):
                    if node.expr.name not in locals_ and not self._seen(out, node.expr.name):
                        out.append((node.expr.name, False))
                else:
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
