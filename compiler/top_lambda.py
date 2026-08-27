"""Top-level (setq <sym> (lambda ...)) handling (moved from cli.py)."""

from compiler.ast_nodes import (
    Call,
    Cond,
    Defun,
    Defpackage,
    ForeachNode,
    IfNode,
    InPackage,
    LambdaNode,
    ListExpr,
    Progn,
    QuotedExpr,
    RepeatNode,
    Setq,
    Symbol,
    WhileNode,
)
def _lambda_real_args(lam):
    """lambda 真参数：剔除 `/ 局部变量` 分隔符及局部变量（与 defun 同协议）。"""
    args = list(lam.args)
    if "/" in args:
        args = args[: args.index("/")]
    return args


def _has_immediate_lambda(node):
    """检测 AST 是否含立即应用 lambda（`((lambda (a b) ...) args...)`，ListExpr
    头为 LambdaNode）。立即 lambda 在 codegen 里即时发射 `-lambda-` DEFUN +
    EVAL，与 kwote lambda（`(function (lambda ...))` 延迟发射）的 DEFCODE 槽序
    不同——CAD 对含立即 lambda 的函数按**源码序逆序**分配 `-lambda-` 槽
    （safe-eval fn/ok-tail 实测），纯 kwote 函数按 symtab 顺序（log 实测）。
    """
    from compiler.ast_nodes import (
        ListExpr as _LE,
        LambdaNode as _LN,
        QuotedExpr as _Q,
        Call as _C,
        Setq as _S,
        IfNode as _I,
        WhileNode as _W,
        ForeachNode as _F,
        RepeatNode as _R,
        Progn as _P,
        Cond as _Cnd,
        Defun as _D,
    )
    if isinstance(node, _D):
        return any(_has_immediate_lambda(b) for b in node.body)
    if isinstance(node, _LE) and node.items and isinstance(node.items[0], _LN):
        return True
    if isinstance(node, _LE):
        return any(_has_immediate_lambda(i) for i in node.items)
    if isinstance(node, _Q):
        return bool(node.expr) and _has_immediate_lambda(node.expr)
    if isinstance(node, _C):
        return any(_has_immediate_lambda(a) for a in node.args)
    if isinstance(node, _S):
        return any(v and _has_immediate_lambda(v) for _, v in node.pairs)
    if isinstance(node, _I):
        return any(x and _has_immediate_lambda(x) for x in (node.cond, node.then, node.else_expr))
    if isinstance(node, (_W, _F, _R)):
        return any(_has_immediate_lambda(b) for b in node.body)
    if isinstance(node, _P):
        return any(_has_immediate_lambda(b) for b in node.forms)
    if isinstance(node, _Cnd):
        return any(_has_immediate_lambda(x) for cl in node.clauses for x in cl)
    if isinstance(node, _LN):
        return any(_has_immediate_lambda(b) for b in node.body)
    return False


def _collect_kwote_lambda_args(node):
    """递归收集 `(function (lambda (args...) ...))` 的参数列表（源码顺序）。

    CAD kwote 机制把内嵌 lambda 编译为独立 `-lambda-` DEFUN，其参数绑定/
    读取槽需在 `_patch_usubr_idx` 中修正（i18n-cad `-lambda-` 参数 opt% gvar
    45 → 槽 43）。返回值与 seg0 中 DEFUN 出现顺序一致（在所在函数之后）。
    """
    from compiler.ast_nodes import (
        Symbol,
        String,
        ListExpr,
        QuotedExpr,
        Setq,
        IfNode,
        WhileNode,
        ForeachNode,
        RepeatNode,
        Call,
        Progn,
        LambdaNode,
        Cond,
    )

    if isinstance(node, QuotedExpr) and node.kwote and isinstance(node.expr, LambdaNode):
        yield _lambda_real_args(node.expr)
        for e in node.expr.body:
            yield from _collect_kwote_lambda_args(e)
    elif isinstance(node, ListExpr) and node.items and isinstance(node.items[0], LambdaNode):
        # 立即应用 `((lambda (a b) ...) args...)`：CAD 内嵌 `-lambda-` DEFUN +
        # EVAL，参数列表照常收集（safe-eval `((lambda (fn) (cond ...)) (car
        # form))` → fn、`((lambda (ok tail) ...) ...)` → [ok, tail]，源码序）。
        yield _lambda_real_args(node.items[0])
        for e in node.items[0].body:
            yield from _collect_kwote_lambda_args(e)
        for a in node.items[1:]:
            yield from _collect_kwote_lambda_args(a)
    elif isinstance(node, LambdaNode):
        # 裸 lambda 值（`(setq *error* (lambda (msg) ...))`，CAD `-lambda-`
        # DEFUN）：参数列表照常收集，供 `_patch_usubr_idx` 修正 `-lambda-`
        # 参数绑定/读取槽（update/file-utils/menu 的 `*error*` 处理器）。
        yield _lambda_real_args(node)
        for e in node.body:
            yield from _collect_kwote_lambda_args(e)
    elif isinstance(node, Defun):
        for e in node.body:
            yield from _collect_kwote_lambda_args(e)
    elif isinstance(node, Call):
        for a in node.args:
            yield from _collect_kwote_lambda_args(a)
    elif isinstance(node, Setq):
        for t, v in node.pairs:
            if t is not None:
                yield from _collect_kwote_lambda_args(t)
            if v is not None:
                yield from _collect_kwote_lambda_args(v)
    elif isinstance(node, IfNode):
        for sub in (node.cond, node.then, node.else_expr):
            if sub is not None:
                yield from _collect_kwote_lambda_args(sub)
    elif isinstance(node, WhileNode):
        if node.cond:
            yield from _collect_kwote_lambda_args(node.cond)
        for e in node.body:
            yield from _collect_kwote_lambda_args(e)
    elif isinstance(node, Progn):
        for e in node.forms:
            yield from _collect_kwote_lambda_args(e)
    elif isinstance(node, Cond):
        for clause in node.clauses:
            if isinstance(clause, (list, tuple)):
                for c in clause:
                    yield from _collect_kwote_lambda_args(c)
            else:
                yield from _collect_kwote_lambda_args(clause)
    elif isinstance(node, ListExpr):
        # `((lambda (a b) ...) args...)` 立即应用：内嵌 `-lambda-` DEFUN 参数
        # （与 kwote 同机制，CAD 实测按源码顺序紧跟所在函数之后）。
        if node.items and isinstance(node.items[0], LambdaNode):
            yield _lambda_real_args(node.items[0])
            for e in node.items[0].body:
                yield from _collect_kwote_lambda_args(e)
            for item in node.items[1:]:
                yield from _collect_kwote_lambda_args(item)
        else:
            for item in node.items:
                yield from _collect_kwote_lambda_args(item)
        if node.dotted is not None:
            yield from _collect_kwote_lambda_args(node.dotted)
    elif isinstance(node, ForeachNode):
        if node.var:
            yield from _collect_kwote_lambda_args(node.var)
        if node.list_expr:
            yield from _collect_kwote_lambda_args(node.list_expr)
        for e in node.body:
            yield from _collect_kwote_lambda_args(e)
    elif isinstance(node, RepeatNode):
        if node.count:
            yield from _collect_kwote_lambda_args(node.count)
        for e in node.body:
            yield from _collect_kwote_lambda_args(e)


def _collect_top_lambda_binds(forms):
    """收集顶层 `(set/setq 'sym (lambda ...))` 绑定（纯顶层文件的 CAD 机制）。

    CAD 对**纯顶层文件**（无 defun）的顶层 lambda 编译为 seg0 内嵌
    ``-lambda-`` DEFUN（模块加载器 DEFCODE 注册为可调用 SUBR）+ 模块代码
    ``PUSH_G <sym>; PUSH_G <-lambda-槽>; FUNC_REF set``。有 defun 的混合
    文件（platform 等）顶层 lambda 仍是引用数据（CAD 实测无 `-lambda-` 槽）。
    返回 ``[(sym_name, LambdaNode), ...]``（源码顺序）。
    """
    from compiler.ast_nodes import LambdaNode as _LN, Setq as _Setq

    def _lambda_of(v):
        if isinstance(v, _LN):
            return v
        if isinstance(v, QuotedExpr) and isinstance(v.expr, _LN):
            return v.expr
        return None

    out = []
    for f in forms:
        if isinstance(f, Call) and f.name == "set" and len(f.args) == 2:
            tgt = f.args[0]
            lam = _lambda_of(f.args[1])
            if lam is not None and isinstance(tgt, QuotedExpr) and isinstance(tgt.expr, Symbol):
                out.append((tgt.expr.name, lam))
        elif isinstance(f, _Setq):
            for t, v in f.pairs:
                lam = _lambda_of(v)
                if lam is not None and isinstance(t, Symbol):
                    out.append((t.name, lam))
    return out


def _insert_top_lambda_defuns(forms, binds):
    """在顶层 setq-lambda form 之后插入提升的 defun（保留原 setq-lambda form）。

    混合文件 seg0 需要 `-lambda-` stub（按源码位置交错在 defun 之间），模块
    代码又需要保留 `(setq sym (function (lambda ...)))` 以发射 setq-lambda
    绑定。插入 defun 的同时保留原 form（kwote 改写后），两者分别驱动 seg0 与
    模块代码。
    """
    from compiler.ast_nodes import Setq as _Setq

    def _is_lam(v):
        return isinstance(v, QuotedExpr) and v.kwote and isinstance(v.expr, LambdaNode)
    out = []
    for f in forms:
        out.append(f)
        if isinstance(f, _Setq):
            for _t, _v in f.pairs:
                if isinstance(_t, Symbol) and _is_lam(_v):
                    for _s, _l in binds:
                        if _s == _t.name:
                            out.append(_defun_from_lambda(_s, _l))
                            break
        elif isinstance(f, Call) and f.name == "set" and len(f.args) == 2:
            _t0 = f.args[0]
            if isinstance(_t0, QuotedExpr) and isinstance(_t0.expr, Symbol) and _is_lam(f.args[1]):
                for _s, _l in binds:
                    if _s == _t0.expr.name:
                        out.append(_defun_from_lambda(_s, _l))
                        break
    return out


def _rewrite_top_lambda_binds(forms):
    """把顶层 set/setq-lambda 的值改写为 kwote 标记（`(function (lambda ...))`）。

    仅对纯顶层文件调用（有 defun 时 CAD 用引用数据，不改写）。kwote 标记使
    `_stmt_bytes` 能识别顶层 lambda（走 `-lambda-` 绑定路径）。`kwote`/`LAMBDA`
    符号残留由 cmd_compile 在符号收集后清除（CAD 顶层 lambda 无这些槽）。
    """
    from compiler.ast_nodes import LambdaNode as _LN, Setq as _Setq

    def _as_kwote(v):
        if isinstance(v, _LN):
            return QuotedExpr(expr=v, kwote=True)
        if isinstance(v, QuotedExpr) and not v.kwote and isinstance(v.expr, _LN):
            return QuotedExpr(expr=v.expr, kwote=True)
        return v

    for f in forms:
        if isinstance(f, Call) and f.name == "set" and len(f.args) == 2:
            f.args[1] = _as_kwote(f.args[1])
        elif isinstance(f, _Setq):
            f.pairs = [(t, _as_kwote(v)) for t, v in f.pairs]
    return forms


def _defun_from_lambda(name, lam):
    """把 LambdaNode 提升为等价的 Defun（拆分 `/ locals`、`&optional`、`&rest`）。

    LambdaNode.args 是原始平铺列表（含 `/`、`&optional`、`&rest` 标记），
    Defun 需拆分到 args/optional/rest/locals。CAD 对顶层 lambda 同样按
    真实参数数编码（@lisp_u `@::wget` lambda 3 实参，CAD `-lambda-` DEFUN
    头 `[3,3,3,0]`，`/` 后 cmd/headers 为局部变量）。
    """
    args = list(getattr(lam, "args", []) or [])
    optional = []
    rest = None
    locals_ = []
    out_args = []
    i = 0
    while i < len(args):
        a = args[i]
        if a == "&optional":
            i += 1
            while i < len(args) and args[i] not in ("&rest", "/"):
                optional.append(args[i])
                i += 1
            continue
        elif a == "&rest":
            if i + 1 < len(args):
                rest = args[i + 1]
            i += 1
            continue
        elif a == "/":
            locals_ = args[i + 1 :]
            break
        else:
            out_args.append(a)
        i += 1
    return Defun(
        name=name,
        args=out_args,
        optional=optional,
        rest=rest,
        locals=locals_,
        body=list(getattr(lam, "body", []) or []),
    )


def _is_top_lambda_bind(form, tl_names):
    """判断 form 是否为顶层 setq-lambda 绑定（`(set/setq 'X (function (lambda
    ...)))`，X ∈ tl_names）。top_lambda_binds 路径处理，不在此发射 DEFUN。"""
    from compiler.ast_nodes import LambdaNode as _LN, QuotedExpr as _Q, Symbol as _Sy, Call as _C, Setq as _S
    if isinstance(form, _C) and form.name == "set" and len(form.args) == 2:
        _t0, _v1 = form.args
        return (
            isinstance(_t0, _Q) and isinstance(_t0.expr, _Sy) and _t0.expr.name in tl_names
            and (isinstance(_v1, _LN) or (isinstance(_v1, _Q) and isinstance(_v1.expr, _LN)))
        )
    if isinstance(form, _S):
        return any(
            isinstance(_t, _Sy) and _t.name in tl_names
            and (isinstance(_v, _LN) or (isinstance(_v, _Q) and isinstance(_v.expr, _LN)))
            for _t, _v in form.pairs
        )
    return False


def _tl_kwote_lambdas(node):
    """收集顶层 form 中作为**调用实参**的 kwote lambda（`(function (lambda ...))`）。

    setup `(if @::*uris* (mapcar (function (lambda (x) ...)) ...))` 实测：CAD 把
    该 lambda 编译为 seg0 内嵌 `-lambda-` DEFUN。**setq 直接值**（`(setq X
    (function (lambda ...)))`，由 top_lambda_binds 提升/`-lambda-` 路径处理）
    不收集——避免与既有机制重复发射。
    """
    from compiler.ast_nodes import (
        QuotedExpr as _Q,
        LambdaNode as _LN,
        Call as _C,
        IfNode as _I,
        Progn as _P,
        WhileNode as _W,
        ForeachNode as _F,
        RepeatNode as _R,
        Cond as _Cnd,
        Setq as _S,
        ListExpr as _LE,
    )

    if isinstance(node, _Q) and getattr(node, "kwote", False) and isinstance(node.expr, _LN):
        yield node.expr
    elif isinstance(node, _C):
        for _a in node.args:
            yield from _tl_kwote_lambdas(_a)
    elif isinstance(node, _S):
        for _t, _v in node.pairs:
            if _v is not None and not (
                isinstance(_v, _Q) and getattr(_v, "kwote", False)
                and isinstance(_v.expr, _LN)
            ):
                yield from _tl_kwote_lambdas(_v)
    elif isinstance(node, _I):
        for _x in (node.cond, node.then, node.else_expr):
            if _x:
                yield from _tl_kwote_lambdas(_x)
    elif isinstance(node, _P):
        for _f_ in node.forms:
            yield from _tl_kwote_lambdas(_f_)
    elif isinstance(node, _W):
        if node.cond:
            yield from _tl_kwote_lambdas(node.cond)
        for _f_ in node.body:
            yield from _tl_kwote_lambdas(_f_)
    elif isinstance(node, _F):
        if node.list_expr:
            yield from _tl_kwote_lambdas(node.list_expr)
        for _f_ in node.body:
            yield from _tl_kwote_lambdas(_f_)
    elif isinstance(node, _R):
        if node.count:
            yield from _tl_kwote_lambdas(node.count)
        for _f_ in node.body:
            yield from _tl_kwote_lambdas(_f_)
    elif isinstance(node, _Cnd):
        for _c in node.clauses:
            for _x in _c:
                yield from _tl_kwote_lambdas(_x)
    elif isinstance(node, _LE):
        for _it in node.items:
            yield from _tl_kwote_lambdas(_it)
    elif isinstance(node, _LN):
        for _f_ in node.body:
            yield from _tl_kwote_lambdas(_f_)


def _convert_top_lambda_to_defuns(forms):
    """把混合文件顶层 `(setq X (lambda ...))` / `(set 'X (lambda ...))` 提升为
    独立 defun。

    CAD 对混合文件顶层 lambda 编译为可调用 SUBR（seg0 `-lambda-` DEFUN +
    DEFCODE 注册 + 模块代码 `set` 绑定，`(type @::acadver)` → SUBR、
    `(@::acadver)` → 值）。atlispcc 直接提升为同名 defun 等价实现：X 成为
    普通函数（callable SUBR），加载时由 DEFCODE 注册，模块代码中对 X 的
    顶层调用（如 `(@::fasext "@lisp")`、`(@::acadver)`）可正常执行。

    纯顶层文件（无 defun）仍走 CAD `-lambda-` 机制（_rewrite_top_lambda_binds），
    本函数只处理混合文件。`(set 'fasext @::*fasext*)` 等非 lambda 绑定保留。
    """
    from compiler.ast_nodes import LambdaNode as _LN, Setq as _Setq

    def _lambda_of(v):
        if isinstance(v, _LN):
            return v
        if isinstance(v, QuotedExpr) and isinstance(v.expr, _LN):
            return v.expr
        return None

    out = []
    for f in forms:
        if isinstance(f, Call) and f.name == "set" and len(f.args) == 2:
            tgt = f.args[0]
            lam = _lambda_of(f.args[1])
            if lam is not None and isinstance(tgt, QuotedExpr) and isinstance(tgt.expr, Symbol):
                out.append(_defun_from_lambda(tgt.expr.name, lam))
                continue
        elif isinstance(f, _Setq):
            new_pairs = []
            has_lambda_pair = False
            for t, v in f.pairs:
                lam = _lambda_of(v)
                if lam is not None and isinstance(t, Symbol):
                    out.append(_defun_from_lambda(t.name, lam))
                    has_lambda_pair = True
                else:
                    new_pairs.append((t, v))
            if new_pairs:
                out.append(_Setq(pairs=new_pairs))
            elif not has_lambda_pair:
                out.append(f)
            continue
        out.append(f)
    return out


