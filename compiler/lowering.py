"""Lowering passes for top-level forms (moved from cli.py, 2026-08-28)."""

from compiler.ast_nodes import (
    Call,
    Cond,
    CondDefunBind,
    Defun,
    Defpackage,
    ForeachNode,
    IfNode,
    InPackage,
    LambdaNode,
    ListExpr,
    Program,
    Progn,
    QuotedExpr,
    RepeatNode,
    Setq,
    Symbol,
    WhileNode,
)
def _flatten_top_level_forms(forms):
    """展开顶层 `(progn ...)`：defun/defpackage 提升为顶层，表达式保持语句块。

    AutoLISP 中顶层 progn 的 defun 与表达式等价于直接写在顶层（@lisp 包常
    用 `(progn (defun ...) ...)` 整体包裹），编译时需先展开才能提取 defun。
    但 CAD **不把 progn 的表达式展平为独立顶层 form**——progn 内部表达式
    按语句编译（setq 无 DUP、值被丢弃；@lisp-env `(progn (setq @::*dev-mode-file*
    (strcat ...)) (if ...))` CAD golden 实测 `USUBR; SETQ_G` 无 `0b`、`0a`）。
    故把连续表达式重新包回单个 `Progn` 语句块（保留相对位置），defun/
    defpackage 提升为独立顶层 form（进 seg0 + 函数注册）。仅处理顶层
    （递归处理嵌套顶层 progn），不触碰 defun 体内的 progn。
    """
    out = []
    for f in forms:
        if isinstance(f, Progn):
            inner = _flatten_top_level_forms(f.forms)
            run = []
            for x in inner:
                if isinstance(x, (Defun, Defpackage, InPackage)):
                    if run:
                        out.append(Progn(forms=run))
                        run = []
                    out.append(x)
                else:
                    run.append(x)
            if run:
                out.append(Progn(forms=run))
        else:
            out.append(f)
    return out


def _hoist_conditional_defuns(forms):
    """把条件/嵌套位置的 defun 提升为顶层独立函数（CAD 编译方式）。

    源码形如 `(if cond (defun f () ...))`、`(if cond (progn (defun f ...) ...))`。
    CAD 编译器把其中的 defun 无条件提取为顶层独立函数（进 seg0 + 函数目录 +
    DEFCODE 注册），if 只保留非 defun 表达式；无剩余表达式时整个 if 移除。
    这与 `_lower_nested_defuns`（改写为 setq lambda 数据）不同：提升后函数
    有真实定义（`fboundp` 成立），与 CAD 产物一致。仅提取顶层 if 内的 defun，
    defun 体内的嵌套 defun 仍交给 `_lower_nested_defuns` 处理。
    """
    from compiler.ast_nodes import IfNode as _If, Progn as _Prog

    from compiler.ast_nodes import CondDefunBind as _CDB

    def _extract(expr, out):
        """从表达式子树提取 defun 提升到 out，返回（剩余表达式 or None）。

        提升后 defun 在 if 内用 `CondDefunBind` 标记替换（运行时绑定留
        if 守卫内，CAD panel.lsp 实测），defun 体本身无条件编译进 seg0。
        """
        if isinstance(expr, Defun):
            out.append(expr)
            return _CDB(name=expr.name)
        if isinstance(expr, _Prog):
            remaining = []
            for f in expr.forms:
                rest = _extract(f, out)
                if rest is not None:
                    remaining.append(rest)
            if not remaining:
                return None
            if len(remaining) == 1:
                return remaining[0]
            return _Prog(forms=remaining)
        if isinstance(expr, _If):
            then = _extract(expr.then, out)
            els = _extract(expr.else_expr, out) if expr.else_expr is not None else None
            if then is None and els is None:
                return None
            return _If(cond=expr.cond, then=then, else_expr=els)
        return expr

    out = []
    for f in forms:
        if isinstance(f, _If):
            rest = _extract(f, out)
            if rest is not None:
                out.append(rest)
        else:
            out.append(f)
    return out


def _lower_top_level_defun_q(forms):
    """顶层 ``defun-q``（Defun ``quoted=True``）降级为顶层 setq 引用数据。

    CAD 把顶层 ``defun-q`` 编译为纯数据 ``((args...) <docstring> <type>
    <body...>)``（ini/get golden 实测：21 符号槽、无 LAMBDA 符号、``c:main``
    空体、seg0 0 字节），而非可调用 SUBR。改写为
    ``(setq <name> '((args...) <docstring> <type> <body...>))``，复用成熟的
    顶层 setq 引用常量机制（符号/字符串注册进 seg1 资源流）。仅处理顶层
    defun-q；defun 体内的 defun-q 仍交给 ``_lower_nested_defuns``（嵌套位置
    改写为 setq-lambda 数据）。
    """
    out = []
    for f in forms:
        if isinstance(f, Defun) and getattr(f, "quoted", False):
            args_list = ListExpr(items=[Symbol(a) for a in f.args])
            items = [args_list] + list(f.body)
            out.append(
                Setq(
                    pairs=[
                        (
                            Symbol(f.name),
                            QuotedExpr(expr=ListExpr(items=items)),
                        )
                    ]
                )
            )
        else:
            out.append(f)
    return out


def _lower_nested_defuns(forms):
    """把非顶层位置的 defun（条件/嵌套函数定义）改写为 setq 引用的 lambda 数据。

    形如 `(if c (defun f (args) body))`、`(if c (progn (defun f ...) ...))`
    的运行时条件函数定义，编译器只支持顶层 defun。AutoLISP 中符号绑定
    lambda 列表后仍可直接调用（等价 defun-q），故改写为
    `(if c (setq f '(lambda (args) body)))`，保留"条件定义"语义，同时
    复用成熟的引用常量机制（无嵌套 DEFUN/kwote 运行时注册问题）。
    顶层 defun 保持函数定义不动。
    """
    from compiler.ast_nodes import Symbol as _Sym, Setq as _Setq
    from compiler.ast_nodes import QuotedExpr as _Q, ListExpr as _L
    from compiler.cad_symbols import strip_docstring

    def _as_lambda(f: Defun) -> _Q:
        all_args: list = [Symbol(a) for a in f.args]
        all_args += [Symbol(a) for a in f.optional]
        if f.rest:
            all_args += [Symbol("&rest"), Symbol(f.rest)]
        if f.locals:
            all_args += [Symbol("/")] + [Symbol(l) for l in f.locals]
        # 条件/嵌套 defun 改写为 lambda 数据时同样剥离 docstring（base-function
        # CAD 实测 vla-postcommand 条件定义字符串不注册）。
        body = strip_docstring(f.body)
        # `defun-q`（Defun quoted=True）CAD 编译为 kwote `(function (lambda
        # ...))`（setup 嵌套 defun-q 实测 FUNCTION 符号），普通嵌套 defun 用
        # quoted 数据（QUOTE）。
        return _Q(expr=_L(items=[Symbol("lambda"), _L(items=all_args)] + body),
                  kwote=getattr(f, "quoted", False))

    def _rewrite(node):
        if isinstance(node, Defun):
            return _Setq(pairs=[(_Sym(node.name), _as_lambda(node))])
        if isinstance(node, IfNode):
            node.cond = _rewrite(node.cond)
            node.then = _rewrite(node.then)
            if node.else_expr is not None:
                node.else_expr = _rewrite(node.else_expr)
            return node
        if isinstance(node, Progn):
            node.forms = [_rewrite(f) for f in node.forms]
            return node
        if isinstance(node, Cond):
            node.clauses = [tuple(_rewrite(x) for x in c) for c in node.clauses]
            return node
        if isinstance(node, Setq):
            node.pairs = [
                (_rewrite(t), None if v is None else _rewrite(v)) for t, v in node.pairs
            ]
            return node
        if isinstance(node, Call):
            node.args = [_rewrite(a) for a in node.args]
            return node
        if isinstance(node, WhileNode):
            node.cond = _rewrite(node.cond)
            node.body = [_rewrite(f) for f in node.body]
            return node
        if isinstance(node, ForeachNode):
            node.list_expr = _rewrite(node.list_expr)
            node.body = [_rewrite(f) for f in node.body]
            return node
        if isinstance(node, RepeatNode):
            node.count = _rewrite(node.count)
            node.body = [_rewrite(f) for f in node.body]
            return node
        if isinstance(node, ListExpr):
            node.items = [_rewrite(f) for f in node.items]
            return node
        if isinstance(node, LambdaNode):
            node.body = [_rewrite(f) for f in node.body]
            return node
        return node

    out = []
    for f in forms:
        if isinstance(f, (Defpackage, InPackage)):
            out.append(f)
        elif isinstance(f, Defun):
            # 顶层 defun 保持函数定义；其体内嵌套 defun（局部辅助函数模式）
            # 同样改写为 setq 引用的 lambda 数据。
            f.body = [_rewrite(b) for b in f.body]
            out.append(f)
        elif isinstance(f, QuotedExpr):
            # 引用数据内的 `(defun ...)` 是数据（`'(defun)` 等），不改写
            out.append(f)
        else:
            out.append(_rewrite(f))
    return out


def _count_kwote_lambdas(forms):
    """统计程序中的 `(function (lambda ...))` 数量（kwote 机制每处需独立
    `-lambda-` 槽；当前 catalog 仅支持 1 个，>1 时退回引用数据路径）。"""
    from compiler.ast_nodes import LambdaNode as _Lam, QuotedExpr as _Q

    n = [0]

    def walk(node):
        if isinstance(node, _Q) and node.kwote and isinstance(node.expr, _Lam):
            n[0] += 1
            return
        if isinstance(node, Program):
            for f in node.forms:
                walk(f)
        elif isinstance(node, (list, tuple)):
            for x in node:
                walk(x)
        elif isinstance(node, ListExpr):
            for x in node.items:
                walk(x)
        elif isinstance(node, Call):
            for a in node.args:
                walk(a)
        elif isinstance(node, QuotedExpr):
            walk(node.expr)
        elif isinstance(node, Setq):
            for t, v in node.pairs:
                walk(t)
                if v is not None:
                    walk(v)
        elif isinstance(node, Progn):
            for f in node.forms:
                walk(f)
        elif isinstance(node, Cond):
            for c in node.clauses:
                for x in c:
                    walk(x)
        elif isinstance(node, IfNode):
            walk(node.cond)
            walk(node.then)
            if node.else_expr is not None:
                walk(node.else_expr)
        elif isinstance(node, Defun):
            for b in node.body:
                walk(b)
        elif isinstance(node, (WhileNode, ForeachNode, RepeatNode)):
            for b in getattr(node, "body", []) or []:
                walk(b)
            # 循环的 条件/count/列表 表达式也可能含 kwote（@::panel-dcl-column
            # 实测 `(repeat (- max-menus (length (vl-remove-if
            # (function (lambda ...)) ...))) ...)` 的 kwote 在 count 中）。
            if isinstance(node, WhileNode) and node.cond is not None:
                walk(node.cond)
            elif isinstance(node, RepeatNode) and node.count is not None:
                walk(node.count)
            elif isinstance(node, ForeachNode) and node.list_expr is not None:
                walk(node.list_expr)
        elif isinstance(node, LambdaNode):
            for b in node.body:
                walk(b)

    walk(forms)
    return n[0]


def _lower_multi_kwote(forms):
    """>1 个 `(function (lambda ...))` 时改写为引用数据 `'(lambda ...)`。

    当前编译器的 kwote 机制只支持 1 个内嵌 `-lambda-` 函数（catalog 单槽）；
    @lisp 包（atlisp_u）含 80 个 kwote 回调，多 `-lambda-` 目录缺失会导致
    CAD 加载报 "函数错误"。AutoLISP 中符号绑定 lambda 列表可直接调用
    （apply/mapcar 实测等价，t_data 验证），故改写为普通引用常量，复用成熟
    的 to_const 路径。单 kwote 文件（i18n/t20）保持 kwote 机制不变。
    """
    if _count_kwote_lambdas(forms) <= 1:
        return forms

    def rewrite(node):
        if isinstance(node, QuotedExpr) and node.kwote and isinstance(node.expr, LambdaNode):
            # 转为引用数据后仍需递归处理 lambda 体内嵌套的 kwote（如
            # `(mapcar (function (lambda (...) (length (vl-remove-if
            # (function (lambda ...)) ...)))) ...)` 体内再套 kwote）。
            lam = node.expr
            lam.body = [rewrite(b) for b in lam.body]
            return QuotedExpr(expr=lam, kwote=False)
        if isinstance(node, Program):
            node.forms = [rewrite(f) for f in node.forms]
            return node
        if isinstance(node, (list, tuple)):
            return [rewrite(x) for x in node]
        if isinstance(node, ListExpr):
            node.items = [rewrite(x) for x in node.items]
            return node
        if isinstance(node, Call):
            node.args = [rewrite(a) for a in node.args]
            return node
        if isinstance(node, QuotedExpr):
            node.expr = rewrite(node.expr)
            return node
        if isinstance(node, Setq):
            node.pairs = [
                (rewrite(t), None if v is None else rewrite(v)) for t, v in node.pairs
            ]
            return node
        if isinstance(node, Progn):
            node.forms = [rewrite(f) for f in node.forms]
            return node
        if isinstance(node, Cond):
            node.clauses = [tuple(rewrite(x) for x in c) for c in node.clauses]
            return node
        if isinstance(node, IfNode):
            node.cond = rewrite(node.cond)
            node.then = rewrite(node.then)
            if node.else_expr is not None:
                node.else_expr = rewrite(node.else_expr)
            return node
        if isinstance(node, Defun):
            node.body = [rewrite(b) for b in node.body]
            return node
        if isinstance(node, (WhileNode, ForeachNode, RepeatNode)):
            node.body = [rewrite(b) for b in node.body]
            if isinstance(node, WhileNode) and node.cond is not None:
                node.cond = rewrite(node.cond)
            elif isinstance(node, RepeatNode) and node.count is not None:
                node.count = rewrite(node.count)
            elif isinstance(node, ForeachNode) and node.list_expr is not None:
                node.list_expr = rewrite(node.list_expr)
            return node
        if isinstance(node, LambdaNode):
            node.body = [rewrite(b) for b in node.body]
            return node
        return node

    return [rewrite(f) for f in forms]


def _lower_immediate_lambda(forms):
    """把 `((lambda (a b) body...) args...)` 立即调用改写为显式
    `(apply '(lambda (a b) body...) (list args...))`。

    CAD 编译器对 `((lambda ...) args)` 用「内嵌 -lambda- DEFUN + EVAL」，
    需要多 `-lambda-` 目录 + 槽修正（当前 catalog 仅支持 1 个，多 lambda
    时 CAD 真机报"参数太少"）。而显式 `(apply '(lambda ...) (list ...))`
    走成熟的引用常量路径，CAD 真机全通过（t8-t12 实测：cond/if/while 体、
    `t` 参数、引用外层参数均正常）。改写在 cad_symbols/codegen 之前进行，
    使槽位注册与显式 apply 完全一致。
    """

    def rewrite(node):
        from compiler.ast_nodes import ListExpr as _LE, LambdaNode as _LN, QuotedExpr as _Q

        if isinstance(node, _LE):
            node.items = [rewrite(i) for i in node.items]
            if node.dotted is not None:
                node.dotted = rewrite(node.dotted)
            if node.items and isinstance(node.items[0], _LN):
                lam = node.items[0]
                lam.body = [rewrite(b) for b in lam.body]
                lam_list = _LE(
                    items=[Symbol("lambda"), _LE(items=[Symbol(a) for a in lam.args])] + lam.body
                )
                args_list = [rewrite(a) for a in node.items[1:]]
                return Call(
                    name="apply",
                    args=[_Q(expr=lam_list), Call(name="list", args=args_list)],
                )
            return node
        if isinstance(node, Call):
            node.args = [rewrite(a) for a in node.args]
            return node
        if isinstance(node, Setq):
            node.pairs = [(rewrite(t), None if v is None else rewrite(v)) for t, v in node.pairs]
            return node
        if isinstance(node, IfNode):
            node.cond = rewrite(node.cond)
            node.then = rewrite(node.then)
            if node.else_expr is not None:
                node.else_expr = rewrite(node.else_expr)
            return node
        if isinstance(node, Progn):
            node.forms = [rewrite(f) for f in node.forms]
            return node
        if isinstance(node, Cond):
            node.clauses = [tuple(rewrite(x) for x in c) for c in node.clauses]
            return node
        if isinstance(node, Defun):
            node.body = [rewrite(b) for b in node.body]
            return node
        if isinstance(node, (WhileNode, ForeachNode, RepeatNode)):
            node.body = [rewrite(b) for b in node.body]
            if isinstance(node, WhileNode) and node.cond is not None:
                node.cond = rewrite(node.cond)
            elif isinstance(node, RepeatNode) and node.count is not None:
                node.count = rewrite(node.count)
            elif isinstance(node, ForeachNode) and node.list_expr is not None:
                node.list_expr = rewrite(node.list_expr)
            return node
        if isinstance(node, LambdaNode):
            node.body = [rewrite(b) for b in node.body]
            return node
        return node

    return [rewrite(f) for f in forms]


def _lower_let(forms):
    """把 `(let ((v1 e1) (v2 e2) ...) body...)` 改写为
    `((lambda (v1 v2 ...) body...) e1 e2 ...)` 立即应用。

    CAD 编译器对 `let` 用「EVAL 引用 lambda + 实参」编译（fg 有 LET 符号槽，
    event-bus `(let ((entry ...)) ...)` 实测 `... USUBR; EVAL 0, const`）；我们
    降级为 lambda-apply，由 `_lower_immediate_lambda` 再改写为
    `(apply '(lambda ...) (list ...))`（成熟引用常量路径，功能正确）。
    仅处理代码位置的 `let`；引用数据（QuotedExpr）内的 `let` 是数据不降级。
    """
    from compiler.ast_nodes import ListExpr as _LE, LambdaNode as _LN, Symbol as _Sym

    def rewrite(node):
        if isinstance(node, _LE):
            node.items = [rewrite(i) for i in node.items]
            if node.dotted is not None:
                node.dotted = rewrite(node.dotted)
            return node
        if isinstance(node, Call) and node.name == "let" and node.args:
            bindings = node.args[0]
            body = node.args[1:]
            vars_: List[str] = []
            inits: List[Node] = []
            if isinstance(bindings, _LE):
                for b in bindings.items:
                    if isinstance(b, _LE) and b.items:
                        v = b.items[0]
                        vars_.append(v.name if isinstance(v, Symbol) else str(v))
                        inits.append(rewrite(b.items[1]) if len(b.items) > 1 else _Sym("nil"))
                    elif isinstance(b, Call):
                        # parser 把 `(v e)` 绑定对解析为 Call(name='v', args=[e])
                        # （`(let ((entry (assoc ...))) ...)` 的 `(entry (assoc
                        # ...))` 首元素是符号 → Call）。旧 else 分支用 str(b)
                        # 当变量名 → `"CALL(NAME='ENTRY'...)"` 错误符号槽。
                        v = b.name
                        vars_.append(v)
                        inits.append(rewrite(b.args[0]) if b.args else _Sym("nil"))
                    else:
                        vars_.append(b.name if isinstance(b, Symbol) else str(b))
                        inits.append(_Sym("nil"))
            lam = _LN(
                args=vars_,
                body=[rewrite(x) for x in body],
            )
            return _LE(items=[lam] + [rewrite(i) for i in inits])
        if isinstance(node, Call):
            node.args = [rewrite(a) for a in node.args]
            return node
        if isinstance(node, Setq):
            node.pairs = [(rewrite(t), None if v is None else rewrite(v)) for t, v in node.pairs]
            return node
        if isinstance(node, IfNode):
            node.cond = rewrite(node.cond)
            node.then = rewrite(node.then)
            if node.else_expr is not None:
                node.else_expr = rewrite(node.else_expr)
            return node
        if isinstance(node, Progn):
            node.forms = [rewrite(f) for f in node.forms]
            return node
        if isinstance(node, Cond):
            node.clauses = [tuple(rewrite(x) for x in c) for c in node.clauses]
            return node
        if isinstance(node, Defun):
            node.body = [rewrite(b) for b in node.body]
            return node
        if isinstance(node, (WhileNode, ForeachNode, RepeatNode)):
            node.body = [rewrite(b) for b in node.body]
            if isinstance(node, WhileNode) and node.cond is not None:
                node.cond = rewrite(node.cond)
            elif isinstance(node, RepeatNode) and node.count is not None:
                node.count = rewrite(node.count)
            elif isinstance(node, ForeachNode) and node.list_expr is not None:
                node.list_expr = rewrite(node.list_expr)
            return node
        if isinstance(node, LambdaNode):
            node.body = [rewrite(b) for b in node.body]
            return node
        return node

    return [rewrite(f) for f in forms]


def _collect_builtins_for_stub(symtab, node):
    """stub 模式下将调用到的内建函数注册为符号槽（CAD stub 用符号槽编址调用）。"""
    from compiler.ast_nodes import (
        Call,
        Defun,
        Setq,
        IfNode,
        WhileNode,
        ForeachNode,
        RepeatNode,
        Progn,
        ListExpr,
        QuotedExpr,
        LambdaNode,
        Cond,
        Symbol,
    )

    if isinstance(node, Defun):
        for expr in node.body:
            _collect_builtins_for_stub(symtab, expr)
    elif isinstance(node, Call):
        if symtab.is_builtin(node.name) and node.name not in ("T", "nil"):
            symtab.get_or_add(node.name)
        for a in node.args:
            _collect_builtins_for_stub(symtab, a)
    elif isinstance(node, (Setq,)):
        for target, value in node.pairs:
            _collect_builtins_for_stub(symtab, target)
            if value:
                _collect_builtins_for_stub(symtab, value)
    elif isinstance(node, IfNode):
        for child in (node.cond, node.then, node.else_expr):
            if child:
                _collect_builtins_for_stub(symtab, child)
    elif isinstance(node, WhileNode):
        if node.cond:
            _collect_builtins_for_stub(symtab, node.cond)
        for expr in node.body:
            _collect_builtins_for_stub(symtab, expr)
    elif isinstance(node, ForeachNode):
        if node.list_expr:
            _collect_builtins_for_stub(symtab, node.list_expr)
        for expr in node.body:
            _collect_builtins_for_stub(symtab, expr)
    elif isinstance(node, RepeatNode):
        if node.count:
            _collect_builtins_for_stub(symtab, node.count)
        for expr in node.body:
            _collect_builtins_for_stub(symtab, expr)
    elif isinstance(node, Progn):
        for form in node.forms:
            _collect_builtins_for_stub(symtab, form)
    elif isinstance(node, Cond):
        for clause in node.clauses:
            for item in clause:
                _collect_builtins_for_stub(symtab, item)
    elif isinstance(node, ListExpr):
        for item in node.items:
            _collect_builtins_for_stub(symtab, item)
    elif isinstance(node, QuotedExpr):
        if node.expr:
            _collect_builtins_for_stub(symtab, node.expr)
    elif isinstance(node, LambdaNode):
        for expr in node.body:
            _collect_builtins_for_stub(symtab, expr)


