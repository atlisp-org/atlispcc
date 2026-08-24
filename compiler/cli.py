import sys
import os
import json
import argparse
import struct
from typing import Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from compiler.parser import Parser, ParseError
from compiler.symbol_table import SymbolTable
from compiler.codegen import CodeGenerator, BytecodeBuffer
from asm.opcodes import encode_usubr
from compiler.ast_nodes import (
    Defun,
    Defpackage,
    InPackage,
    Setq,
    Progn,
    IfNode,
    WhileNode,
    ForeachNode,
    RepeatNode,
    Cond,
    Call,
    LambdaNode,
    ListExpr,
    QuotedExpr,
    Symbol,
    Program,
)
from compiler.opt import optimize
from compiler.resource_builder import (
    ResourceBuilder,
    build_module_code,
    build_command_module_code,
    build_mixed_command_module_code,
    count_resource_records,
    count_resource_items,
    resolve_encoding,
    _real_fmt,
)
from compiler.fas_writer import FasWriter
from compiler.analyzer import analyze
from compiler.linker import link_fas
from compiler.vlx_builder import build_vlx
from decompiler.fas4_decompiler import Fas4Parser, Disassembler, ControlFlowAnalyzer, LispGenerator, is_compact_stub, use_short_subr
from tools.validate import validate_file

ENCODE_POP = bytes([0x0A])


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

    def _extract(expr, out):
        """从表达式子树提取 defun 提升到 out，返回（剩余表达式 or None）。"""
        if isinstance(expr, Defun):
            out.append(expr)
            return None
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
        return _Q(expr=_L(items=[Symbol("lambda"), _L(items=all_args)] + body))

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


def _subr_bytes(opcode: int, argc: int, idx: int, flags: int = 3, wide: bool = False) -> bytes:
    """stub USUBR/FUNC 编码：小文件 3 字节 `op <argc> <idx8>`；
    大文件（idx>255）USUBR 5 字节 `35 <argc> <idx16> <flags=3>`、FUNC 6 字节
    `51 <argc> <idx16> <flags=1> 00`（CAD atlisp_u 实测 USUBR flags=3、
    FUNC flags=1 + 尾 0）。"""
    if wide or idx > 255:
        if opcode == 0x51:
            return bytes([opcode, argc & 0xFF, idx & 0xFF, (idx >> 8) & 0xFF, flags & 0xFF, 0])
        return bytes([opcode, argc & 0xFF, idx & 0xFF, (idx >> 8) & 0xFF, flags & 0xFF])
    return bytes([opcode, argc & 0xFF, idx & 0xFF])


def _patch_usubr_idx(seg0: bytes, seg1: bytes, symtab, nsyms: int, func_args=None, codegen_nsyms: Optional[int] = None,
                     params_by_name: Optional[dict] = None, lambda_args_by_func: Optional[dict] = None,
                     has_top_forms: bool = False, n_real_funcs: int = 1,
                     top_lambda_args: Optional[list] = None,
                     top_lambda_offsets: Optional[dict] = None,
                     module_reg_count: Optional[int] = None) -> bytes:
    """修正 stub 字节码的 USUBR 与参数槽索引为 CAD 的 gvar 槽 - 1。

    CAD 实测逆向：
    - USUBR 调用符号的 gvar 槽 = idx + 1（idx = gvar 槽 - 1）
    - 参数绑定/读取槽 = 参数符号的 gvar 槽 - 1（越界符号 gvar 槽假定 = nsyms）
    codegen 用占位生成，此处用资源段 GVARINIT 重建的 gvar 表修正。

    仅当文件含顶层表达式（has_top_forms=True，顶层符号占用模块注册槽导致
    codegen symtab 序 ≠ 资源注册序）时重映射。纯函数文件（无顶层表达式）
    codegen 槽已与资源 symbol_slots 一致，重映射反而破坏正确输出（多 kwote
    PUSH_G 字符串被 `nsyms-1` 回退改错槽、kwote FUNC 槽错位 → CAD 加载报
    `-lambda-` 类型错误，test-2kwote/platform-api 实测），直接原样返回。

    当 codegen 内嵌 `(function (lambda ...))`（kwote）时，codegen 会把 `-lambda-`
    追加进 symtab.entries，使 fas_nsyms（len(entries)-module_reg_count+1）比
    codegen 构造时的 nsyms 大 1；而 `-lambda-` 不参与资源段符号注册，导致
    seg0 引用（gvar 槽 - 1）整体再偏移 1。此时应使用 gvar 槽 - 2（i18n 实测
    PKG-NAME fg[88]→参数槽 86、ASSOC fg[90]→USUBR 88）。t01 等无 kwote 文件
    fas_nsyms==codegen_nsyms，保持 gvar 槽 - 1。

    注意：offset 仅当所有 `-lambda-` 槽都集中在 symtab.entries **末尾**时才
    生效（t20/i18n 单 kwote 实测 gvar 槽 - 2 真机通过）。多 kwote 文件
    （@lisp_u 89 槽）`-lambda-` 穿插在普通符号之间，无法用统一偏移补偿，
    此时 offset=0（CAD 实测 `nsyms-codegen_nsyms` 过大导致 USUBR/FUNC 索引
    整体错位、加载报参数太少）。
    """
    if not has_top_forms and n_real_funcs <= 1:
        # 单函数无 kwote（`-lambda-`）文件：codegen 槽已与资源 symbol_slots 一致，
        # 重映射反而破坏正确输出（多 kwote PUSH_G 字符串被 `nsyms-1` 回退改错槽、
        # kwote FUNC 槽错位 → CAD 加载报 `-lambda-` 类型错误），直接原样返回。
        # 含内嵌 kwote `-lambda-` 的单函数文件（net/reload.lsp 双 kwote 实测）：
        # `-lambda-` 不参与资源符号注册，按其在所有 `-lambda-` 条目中的序号
        # 编址（lambda i 槽 = nsyms - i，操作数 = nsyms - 1 - i；与多函数
        # lam_order 同规则）。codegen 用 symtab 槽（首个 = codegen 末尾，
        # 与 nsyms-1 通常一致，但多 kwote 时首 lambda 槽 ≠ nsyms-1），须重映射
        # PUSH_G `-lambda-` 引用。仅重映射 `-lambda-`，不动其它符号。
        _lam_entries = [
            (_ei, _e[1]) for _ei, _e in enumerate(symtab.entries)
            if isinstance(_e, tuple) and len(_e) == 2
            and _e[0] == "SYMBOL" and str(_e[1]).upper() == "-LAMBDA-"
        ]
        if not _lam_entries:
            return seg0
        # symtab 中 `-lambda-` 槽 → CAD 槽（nsyms-1-lam_idx），lam_idx 按
        # symtab 出现序。
        _lam_slot_map = {_ei: (nsyms - 1 - _i) for _i, (_ei, _) in enumerate(_lam_entries)}
        from decompiler.fas4_decompiler import Disassembler

        _wide = nsyms > 256
        try:
            _insts = Disassembler(short_subr=not _wide).disassemble(
                seg0, nsyms, sym_count=len(symtab.entries))
        except Exception:
            return seg0
        _out = bytearray()
        for _inst in _insts:
            if _inst.op_name == "PUSH_G" and _inst.operands and _inst.size == 3:
                _i0 = _inst.operands[0]
                if _i0 in _lam_slot_map:
                    _ni = _lam_slot_map[_i0]
                    if 0 <= _ni <= 0xFFFF:
                        _out += bytes([0x09, _ni & 0xFF, (_ni >> 8) & 0xFF])
                        continue
            _out += seg0[_inst.offset : _inst.offset + _inst.size]
        return bytes(_out)
    offset = 0
    if codegen_nsyms is not None and nsyms > codegen_nsyms:
        _trailing_lam = 0
        for _e in reversed(symtab.entries):
            if isinstance(_e, tuple) and len(_e) == 2 and _e[0] == "SYMBOL" and str(_e[1]).upper() == "-LAMBDA-":
                _trailing_lam += 1
            else:
                break
        # 仅单 kwote（恰好 1 个末尾 `-lambda-`）用统一偏移补偿（i18n 实测
        # gvar 槽 - 2）。多 kwote（≥2）`-lambda-` 穿插/多槽时统一偏移会
        # 整体错位 → CAD 加载报"参数太少"/类型错误，此时 offset=0（gvar 槽 - 1，
        # platform-api 双 kwote 实测 GETVAR fg[131]→USUBR 130 正确）。
        if _trailing_lam == 1 and _trailing_lam == nsyms - codegen_nsyms:
            offset = 1
    try:
        from core.fas_core import build_mvar_tables

        rg, fg = build_mvar_tables(seg1, nsyms)
    except Exception:
        return seg0
    # 符号与字符串分表：`fg` 表里 SYMBOL `>` 与 STRING `">"` 可能同 key
    # （符号大写、字符串大小写敏感），单一 gvar_map 靠 setdefault 先到先得，
    # 若字符串先注册会占用符号槽，USUBR/FUNC 引用指向字符串 → CAD
    # `(">" 24.1 20.1)` ill-fun。符号用 gvar_map（优先于字符串），字符串用
    # str_map（符号 `>` 与字符串 `">"` 各自独立槽，互不抢占）。
    gvar_map: dict = {}
    str_map: dict = {}
    for idx, v in enumerate(fg):
        if isinstance(v, tuple) and len(v) == 2 and v[0] in ("SYMBOL", "STRING"):
            # 符号名统一大写（AutoLISP 大小写不敏感）；字符串大小写敏感
            # （base-function 实测 `"date"`（timestamp）与 `"DATE"`（sleep）
            # 是两个不同槽，`.upper()` 会错误合并）。
            key = str(v[1]).upper() if v[0] == "SYMBOL" else str(v[1])
            if v[0] == "SYMBOL":
                # 符号优先：仅当 key 空或已被字符串占用时才写入；符号之间
                # 保持先到先得（递归函数名有重复槽，语义与旧 setdefault 一致）。
                prev = gvar_map.get(key)
                if prev is None or not (
                    isinstance(prev, int)
                    and 0 <= prev < len(fg)
                    and isinstance(fg[prev], tuple)
                    and fg[prev][0] == "SYMBOL"
                ):
                    gvar_map[key] = idx
            else:
                str_map.setdefault(key, idx)
    # `command` 内建 SUBR 在资源段注册名为 `ads-cmd`（base-function CAD 实测），
    # symtab 收集的符号名是 `command`。别名对齐使 FUNC/USUBR 分支能命中。
    if "ADS-CMD" in gvar_map:
        gvar_map.setdefault("COMMAND", gvar_map["ADS-CMD"])
    # 实数常量：codegen 用 symtab REAL 槽（可能偏离资源段 GVARINIT 槽，
    # base-function 实测 0.001 在 symtab 174 而 fg[130]），按值匹配映射。
    real_map: dict = {}
    for idx, v in enumerate(fg):
        if isinstance(v, tuple) and len(v) == 2 and v[0] == "REAL":
            real_map.setdefault(_real_fmt(float(v[1])), idx)
    # 资源流注册序（symbol_slots）：PUSH_G 字符串/表外符号的操作数 = 其在
    # symbol_slots 中的索引（CAD 实测）。此前字符串回退用 `nsyms-1` 硬编码，
    # 对多 kwote 文件（`-lambda-` 参数混入 func_args 使 multi=True）会越界
    # 错槽（platform-api/test-2kwote 的 `"platform"` 在 slot 6 而非末尾，
    # 被改成 nsyms-1=8 → CAD 加载报 `-lambda-` 类型错误）。改用真实注册序。
    _res_symbol_slots: List[str] = []
    try:
        from core.fas_core import parse_resource_stream as _prs

        _ritems, _rsyms, _rstrs = _prs(seg1)
        for _rit in _ritems:
            # symbol_slots = SYMBOL/STRING/REAL 三类（与 decompiler 一致）；
            # 漏 REAL 会使后续索引整体偏 1（platform-api `0.5` REAL 项实测）。
            if isinstance(_rit, tuple) and len(_rit) == 2 and _rit[0] in ("SYMBOL", "STRING", "REAL"):
                _res_symbol_slots.append(str(_rit[1]))
    except Exception:
        _res_symbol_slots = []

    def _res_slot_of(value: str) -> Optional[int]:
        """字符串/符号在资源 symbol_slots 中的索引；未找到返回 None。

        返回**最后一个**出现位置：资源流先注册模块区符号（函数名 + 顶层
        表达式符号），后注册函数体符号（fg 表）。函数体 PUSH_G/PUSH_VALUE
        引用的是 fg 表槽，符号同时出现在模块区与函数体区时（如顶层变量
        `@::*offline-mode*` 在 net/uri.lsp 的 symslot[3] 模块区 + [57] 函数
        体区，nsyms=25）必须取函数体区槽（57 ≥ nsyms → CAD 用 nsyms-1）；
        取模块区槽（3）会算出 3-1=2 的错误操作数。仅出现在模块区（函数名
        等）的符号在函数体区无槽位，取末次=模块区槽，语义不变。

        大小写：先精确匹配（字符串大小写敏感，`"date"`/`"DATE"` 异槽），
        未命中再做不区分大小写匹配（`0x56` 保留大小写块 `_al-bind-alist`/
        `kwote`/`ads-cmd` 以源码大小写入 symbol_slots，而查询方 `_best[0]`/
        `str(name).upper()` 传大写——log.lsp 实测 `_res_slot_of("_AL-BIND-ALIST")`
        精确匹配 None → `_res_offset` 变 None → 表外符号回退 nsyms-1 错槽；
        符号查大小写不敏感，字符串精确命中不受影响）。
        """
        _found: Optional[int] = None
        for _i, _v in enumerate(_res_symbol_slots):
            if str(_v) == value:
                _found = _i
        if _found is None:
            _vu = value.upper()
            for _i, _v in enumerate(_res_symbol_slots):
                if str(_v).upper() == _vu:
                    _found = _i
        return _found

    # 表外符号（DEFCODE module 参数等，如 cmd.lsp C:@U 的 `@::upgrade`）：
    # 其在资源 symbol_slots 的索引含模块区偏移（cmd.lsp @::UPGRADE slot 104
    # vs 实际 fg 槽 94，偏移 10 = 模块注册区符号数）。用 gvar_map 中 **fg 槽
    # 最大**（函数体区末尾）符号的（_res_slot_of - fg 槽）差推出偏移，表外
    # 符号 fg 槽 = _res_slot_of - 偏移。模块区函数名（fg 低位）偏移小
    # （C:@M slot9-gvar2=7），不可用。
    _res_offset: Optional[int] = None
    _best = None
    for _gs, _gv in gvar_map.items():
        if _gs in ("T", "NIL"):
            continue
        if _best is None or _gv > _best[1]:
            _best = (_gs, _gv)
    _best_res = None
    if _best is not None:
        _ri = _res_slot_of(_best[0])
        if _ri is not None:
            _res_offset = _ri - _best[1]
            _best_res = _ri

    def _const_leaves(v):
        """fg 表 const 结构 → 叶子符号名列表（SYMBOL/STRING）。"""
        if isinstance(v, tuple) and len(v) == 2 and v[0] in ("SYMBOL", "STRING"):
            return [str(v[1])]
        if isinstance(v, tuple):
            _out = []
            for _sub in v:
                if isinstance(_sub, tuple):
                    _out.extend(_const_leaves(_sub))
            return _out
        return []

    # fg 表里的 const（quoted 数据）折叠多个 res 槽为一个 fg 槽（net/module
    # `_al-bind-alist '(entry now)` 的 ENTRY/NOW 占 res[110,111]、fg[98] 一个
    # 槽），使 `_res_offset` 在 const 之后失效（MOD-SYM res[112]-12=100，
    # CAD 用 fg[99]=112-13）。记录每个 const 的（res 位置, 叶子数），目标符号
    # res 槽在 const 之后时按叶子数-1 补偏移。
    _const_collapse = []
    for _i, _v in enumerate(fg):
        if isinstance(_v, tuple) and not (
            len(_v) == 2 and _v[0] in ("SYMBOL", "STRING", "REAL", "CONS", "FUNC")
        ):
            _leaves = _const_leaves(_v)
            if len(_leaves) > 1:
                _cpos = _res_slot_of(str(_leaves[0]).upper())
                if _cpos is not None:
                    _const_collapse.append((_cpos, len(_leaves)))

    def _res_to_fg(rs: int) -> int:
        """资源 symbol_slots 索引 → fg 槽（`_res_offset` + const 折叠补偿）。

        const（quoted 数据）折叠多个 res 槽为一个 fg 槽（net/module
        `(entry now)` 占 res[110,111]、fg[98] 一槽），目标 res 槽在 const 之后
        时偏移 +（叶子数-1）。`gvar_slot_res`/表外符号/字符串 fallback 共用。"""
        _off = _res_offset or 0
        if _best_res is not None:
            for _cpos, _lcount in _const_collapse:
                if _best_res < _cpos < rs:
                    _off += _lcount - 1
        return rs - _off

    def _strip_list_markers(v):
        """symtab 常量结构 → fg 表可比较形式（规范化大小写/INT/REAL/LIST）。

        fg 表里 BUILD_LIST 结果为裸内容元组（无 `'LIST'` 前缀），符号大写、
        整数为裸 int、实数裸 float；symtab CONST entry 保留 `('LIST', items)`、
        `('SYMBOL', name)`、`('INT', v)` 等标记。递归转换以便结构匹配。
        """
        if isinstance(v, tuple) and len(v) == 1 and v[0] == "NIL":
            # fg 表里 NIL（PUSH_NIL 内联）表示为 None（build_mvar_tables
            # `op 0x00/0x01` → stack.append(None)），symtab 常量保留
            # `('NIL',)` 标记——结构匹配须归一化为 None，否则 quoted lambda
            # 含 NIL 参数时 const_map 查不到 → PUSH_G 落 nsyms-1（net/headers
            # @::set-timeouts `'(lambda () ...)` 的 `('NIL',)` 实测）。
            return None
        if isinstance(v, tuple) and len(v) == 2:
            if v[0] == "LIST":
                return tuple(_strip_list_markers(i) for i in v[1])
        if isinstance(v, tuple) and len(v) == 3 and v[0] == "LIST" and v[2]:
            # dotted 引用 `'(a . b)`：symtab 常量 `('LIST', (a, b), True)`，fg 表
            # 用 `('CONS', a, b)` 表示（build_mvar_tables `0x2A` 操作）——结构匹配
            # 须归一化为 CONS，否则 const_map 失配 → PUSH_G 落 nsyms-1
            # （cn-commands `'((:vlr-unknownCommand . parse-cmdunknown))` 实测）。
            _items = list(v[1])
            if len(_items) == 2:
                return ("CONS", _strip_list_markers(_items[0]), _strip_list_markers(_items[1]))
            return tuple(_strip_list_markers(i) for i in _items)
        if isinstance(v, tuple) and len(v) == 2:
            if v[0] == "SYMBOL":
                # 符号名统一大写，但 vla-/vlax- 与 VLISP 大小写保留符号保持
                # 原大小写（与 resource_builder._enc_sym 一致）：fg 表里这些
                # 符号保留源码大小写（net/headers `(lambda ... vlax-invoke ...)`
                # 的 vlax-invoke fg 槽小写），结构匹配若大写则 const_map 失配
                # → PUSH_G 落 nsyms-1。
                _sn = str(v[1])
                _lower = _sn.lower()
                from compiler.resource_builder import _VLISP_CASE_PRESERVE as _vcp

                for _canon in _vcp:
                    if _lower == _canon.lower():
                        return ("SYMBOL", _canon)
                if _lower.startswith(("vla-", "vlax-")):
                    return ("SYMBOL", _sn)
                return ("SYMBOL", _sn.upper())
            if v[0] in ("INT", "INT8", "INT32"):
                return int(v[1])
            if v[0] == "REAL":
                return float(v[1])
            if v[0] in ("STRING", "T"):
                return v
        if isinstance(v, (list, tuple)):
            return tuple(_strip_list_markers(i) for i in v)
        return v

    # CONST 常量（quoted lambda/list 等）在 fg 表里注册为嵌套结构；用结构匹配
    # 建立 结构 → gvar 槽 映射，供 CONST 引用编址（i18n 实测 ANSI 表 fg[98]、
    # loc-file 单元素列表 fg[94]）。排除原子（SYMBOL/STRING/REAL/CONS/FUNC）。
    const_map: dict = {}
    for idx, v in enumerate(fg):
        if isinstance(v, tuple) and not (len(v) == 2 and v[0] in ("SYMBOL", "STRING", "REAL", "CONS", "FUNC")):
            const_map.setdefault(v, idx)
    if not gvar_map:
        return seg0
    from decompiler.fas4_decompiler import Disassembler

    # 大文件（nsyms>256）：CAD 用 5 字节 USUBR/FUNC（idx16 + flags=3），
    # 反汇编须用 short_subr=False；小文件保持 3 字节（与 golden 逐字节一致）。
    wide = nsyms > 256
    try:
        insts = Disassembler(short_subr=not wide).disassemble(seg0, nsyms, sym_count=len(symtab.entries))
    except Exception:
        return seg0

    def gvar_slot(name: str) -> int:
        # 资源段符号名已大写（_enc_sym），参数名为小写，查找时统一大写。
        # 返回 (槽位, 是否命中 gvar 表)。未命中返回 (nsyms, False)——CAD 对
        # 表外符号（参数/末尾常量等）按 gvar 槽 = nsyms 编址，此时才需减
        # offset 补偿 `-lambda-` 额外槽；命中 gvar 表的符号其槽位已含
        # `-lambda-` 偏移，不再减（net/cache.lsp 实测 body 符号 gvar-1、
        # 表外参数 nsyms-1-offset 并存）。
        _key = str(name).upper()
        _v = gvar_map.get(_key)
        if _v is not None:
            return _v, True
        return nsyms, False

    def gvar_slot_res(name: str):
        """gvar_slot + 表外符号按 `_res_offset` 编址（scheduler `name`
        symbol_slots[93] - 23 = fg 70 → 操作数 69，CAD 实测；旧 gvar_slot
        未命中回 nsyms-1=72 错槽）。命中 gvar 表或经 `_res_offset` 定位的
        槽位都视为"命中"（返回 True），调用方不再减 offset（`_res_offset`
        定位的 fg 槽已含全部符号，06_higher_order `lst` 13-1=12 实测）。"""
        _gs, _hit = gvar_slot(name)
        if _hit:
            return _gs, True
        if _res_offset is not None:
            _rs = _res_slot_of(str(name).upper())
            if _rs is not None:
                _af = _res_to_fg(_rs)
                if 0 <= _af < nsyms:
                    return _af, True
        return _gs, False

    def sym_of(idx: int):
        if 0 <= idx < len(symtab.entries) and symtab.entries[idx][0] in ("SYMBOL", "STRING"):
            v = symtab.entries[idx][1]
            # 符号名统一大写；字符串大小写敏感（`"date"`/`"DATE"` 异槽）。
            return str(v).upper() if symtab.entries[idx][0] == "SYMBOL" else str(v)
        return None

    # 每个内嵌 `-lambda-` 条目 → 它在所有 `-lambda-` 条目中的序号（0 起）。
    # CAD 立即调用/多 kwote 每个嵌套 lambda 独立槽：lambda i 的 gvar 槽 =
    # nsyms - i（t3=nsyms-1、t4=nsyms-2、t5=nsyms-3），PUSH_G 操作数 =
    # gvar 槽 - 1 = nsyms - 1 - i。
    lam_order: dict = {}
    _li = 0
    for _ei, _e in enumerate(symtab.entries):
        if _e[0] == "SYMBOL" and str(_e[1]).upper() == "-LAMBDA-":
            lam_order[_ei] = _li
            _li += 1

    out = bytearray()
    multi = bool(func_args) and len(func_args) > 1
    # 按函数名解析 DEFUN 参数（robust）：外层 defun 经 symtab.function_offsets
    # 的 offset→name 定位，-lambda- DEFUN 归其所在函数。此前用全局 func_iter
    # 顺序对齐，@lisp_u 508 函数 + 多 kwote 时 _collect_kwote_lambda_args 与
    # codegen -lambda- 生成数不匹配导致 iter 错位（@::load-locale 参数被错配为
    # 他函数参数 → 体内符号全乱、CAD 加载报"参数太少"）。
    params_by_name = params_by_name or {}
    lambda_args_by_func = lambda_args_by_func or {}
    name_by_offset = {}
    for _n, _o in (symtab.function_offsets.items() if hasattr(symtab, "function_offsets") else []):
        name_by_offset[_o] = str(_n).upper()
    cur_args = None
    cur_func = None
    lambda_idx = 0
    arg_i = 0
    # kwote lambda 的 `-lambda-` DEFUN 不注册 name_by_offset：进入时把宿主
    # 函数参数压栈，END_DEFUN 时弹出恢复——否则 lambda 结束后宿主函数体的
    # 参数读取（PUSH_VALUE mod-sym 等）仍用 lambda 的 cur_args（net/module
    # @::handle-module-failure 内嵌 0 参 lambda 后 `(vl-remove mod-sym ...)`
    # 的 mod-sym 读取被误走通用符号映射 → 99 错槽，CAD 用 98）。
    _arg_stack: list = []
    for inst in insts:
        new_idx: Optional[int] = None
        if inst.op_name == "DEFUN":
            _arg_stack.append((cur_args, arg_i))
            fname = name_by_offset.get(inst.offset)
            if fname is not None:
                cur_func = fname
                cur_args = params_by_name.get(fname)
                lambda_idx = 0
            else:
                # 混合文件顶层 setq-lambda（提升为 defun，func_offsets 用
                # `-lambda-` 键）：按 seg0 offset 查原函数名解析参数。
                if top_lambda_offsets and inst.offset in top_lambda_offsets:
                    _orig = top_lambda_offsets[inst.offset]
                    cur_args = params_by_name.get(str(_orig).upper()) if params_by_name else None
                    cur_func = None
                    lambda_idx = 0
                else:
                    # 内嵌 `-lambda-` DEFUN：取所在函数收集的 kwote lambda 参数。
                    # 纯顶层 `(set/setq 'sym (lambda ...))`（无宿主 defun）用
                    # top_lambda_args（按 seg0 出现序 = 源码序）。
                    if top_lambda_args and (cur_func is None or cur_func == "-LAMBDA-"):
                        _la = top_lambda_args
                    else:
                        _la = lambda_args_by_func.get(cur_func, []) if cur_func else []
                    cur_args = _la[lambda_idx] if lambda_idx < len(_la) else None
                    lambda_idx += 1
            arg_i = 0
        elif inst.op_name == "END_DEFUN":
            if _arg_stack:
                cur_args, arg_i = _arg_stack.pop()
        # 参数绑定 PUSH_G（DEFUN 后 argc 个，仅多函数）
        if (multi or top_lambda_args) and inst.op_name == "PUSH_G" and cur_args is not None and arg_i < len(cur_args):
            arg = cur_args[arg_i]
            _gs, _hit = gvar_slot_res(arg)
            new_idx = _gs - 1 - (0 if _hit else offset)
            if 0 <= new_idx <= 0xFFFF:
                out += bytes([0x09, new_idx & 0xFF, (new_idx >> 8) & 0xFF])
                arg_i += 1
                continue
        # 参数读取 PUSH_VALUE（仅多函数）
        elif multi and inst.op_name == "PUSH_VALUE" and inst.size == 3 and cur_args is not None and inst.operands:
            idx = inst.operands[0]
            # 多函数参数读取：codegen 用参数真实符号槽（get_or_add）发射，
            # 凭 sym_of(idx) 是否在 cur_args 识别（此前用 codegen_nsyms-argc+i
            # 占位，会与真实符号槽碰撞——lambda_body 实测 `t` 槽 == 占位值，
            # 被误判为参数 → "函数错误: nil"）。非参数（如 `t`）走常规符号映射。
            _sym = sym_of(idx)
            if _sym and cur_args and _sym in [a.upper() for a in cur_args]:
                i = [a.upper() for a in cur_args].index(_sym)
                if 0 <= i < len(cur_args):
                    arg = cur_args[i]
                    _gs, _hit = gvar_slot_res(arg)
                    new_idx = _gs - 1 - (0 if _hit else offset)
                    if 0 <= new_idx <= 0xFFFF:
                        out += bytes([0x03, new_idx & 0xFF, (new_idx >> 8) & 0xFF])
                        continue
        # 参数写入 SETQ_G（仅多函数）：与参数读取同规则。codegen 对参数
        # `(setq param ...)` 用 symtab.get_or_add(param) 发射（record.lsp
        # `(setq lib-name (read lib-name))` 实测 symtab 槽 32），但参数符号
        # 不注册于资源 fg 表（符号槽末尾，gvar 槽 = nsyms），须按
        # gvar_slot(arg) - 1 重映射（CAD 实测 `SETQ_G[30]` = nsyms-1）。
        elif multi and inst.op_name == "SETQ_G" and inst.size == 3 and cur_args is not None and inst.operands:
            idx = inst.operands[0]
            _sym = sym_of(idx)
            if _sym and cur_args and _sym in [a.upper() for a in cur_args]:
                i = [a.upper() for a in cur_args].index(_sym)
                if 0 <= i < len(cur_args):
                    arg = cur_args[i]
                    _gs, _hit = gvar_slot_res(arg)
                    new_idx = _gs - 1 - (0 if _hit else offset)
                    if 0 <= new_idx <= 0xFFFF:
                        out += bytes([0x06, new_idx & 0xFF, (new_idx >> 8) & 0xFF])
                        continue
        # 其余符号引用：统一用 gvar 槽 - 1。多函数的普通符号走 gvar_map；
        # CONST/STRING 常量引用（PUSH_G 操作数 = gvar 槽 - 1）在单函数
        # 也需修正（codegen 原始槽 = symtab idx，gvar 槽 = idx+1，
        # 操作数 = idx——i18n_v2 实测 ANSI 表 symtab idx 4 → 操作数 3）。
        # 注意：CAD stub 中调用后的占位 PUSH_VALUE[0] 是单字节 `03`（size=1），
        # 并非符号引用，必须跳过，否则被扩展成 3 字节破坏字节一致性。
        if inst.op_name in ("PUSH_VALUE", "PUSH_G", "SETQ_G") and inst.operands and inst.size == 3:
            # 参数绑定 PUSH_G（DEFUN 后 argc 个）：多函数由上方分支修正并
            # continue（不到此处）；单函数 codegen 已输出正确槽（nsyms-1）。
            # 此处跳过，避免被当作 CONST/STRING 误改。
            is_arg_bind = inst.op_name == "PUSH_G" and cur_args is not None and arg_i < len(cur_args)
            if is_arg_bind:
                arg_i += 1
                out += seg0[inst.offset : inst.offset + inst.size]
                continue
            if multi:
                # 字符串（如 `"OFFLINE"`）必须走 str_map（大小写敏感），不能
                # 经 gvar_map——否则与同名符号（net/probe `"OFFLINE"` vs
                # 符号 OFFLINE）冲突，映射到符号槽（fg[11] → 操作数 10）而非
                # 字符串槽（fg[9] → 操作数 8，CAD 实测）。
                if (
                    0 <= inst.operands[0] < len(symtab.entries)
                    and symtab.entries[inst.operands[0]][0] == "STRING"
                    and inst.op_name in ("PUSH_G", "PUSH_VALUE", "SETQ_G")
                ):
                    _sv = str(symtab.entries[inst.operands[0]][1])
                    if _sv in str_map:
                        new_idx = str_map[_sv] - 1
                        if 0 <= new_idx <= 0xFFFF:
                            if inst.op_name == "PUSH_VALUE" and new_idx == 0 and not wide:
                                out += bytes([0x03])
                            else:
                                opcode = {"PUSH_VALUE": 0x03, "PUSH_G": 0x09, "SETQ_G": 0x06}[inst.op_name]
                                out += bytes([opcode, new_idx & 0xFF, (new_idx >> 8) & 0xFF])
                            continue
                sym = sym_of(inst.operands[0])
                if sym and sym in gvar_map:
                    new_idx = gvar_map[sym] - 1
                    # 大文件（wide）SETQ_G：目标符号 fg 槽若与 rg 表列表常量
                    # 槽冲突（@lisp_u 的 foreach 变量 ITEM fg[905] vs
                    # :DIALOG 列表 rg[905] → CAD 报 symbolp），fallback 符号槽
                    # 末尾（CAD 实测 foreach 变量在符号槽末尾）。小文件不检测
                    # （t-series/i18n golden 保持原编址）。
                    if wide and inst.op_name == "SETQ_G" and 0 <= new_idx < len(rg):
                        _rgv = rg[new_idx]
                        if (
                            isinstance(_rgv, tuple)
                            and len(_rgv) > 1
                            and not (len(_rgv) == 2 and _rgv[0] in ("SYMBOL", "STRING", "REAL"))
                        ):
                            new_idx = nsyms - 1 - offset
                    if 0 <= new_idx <= 0xFFFF:
                        if inst.op_name == "PUSH_VALUE" and new_idx == 0 and not wide:
                            out += bytes([0x03])
                        else:
                            opcode = {"PUSH_VALUE": 0x03, "PUSH_G": 0x09, "SETQ_G": 0x06}[inst.op_name]
                            out += bytes([opcode, new_idx & 0xFF, (new_idx >> 8) & 0xFF])
                        continue
                if sym == "-LAMBDA-":
                    # kwote/立即调用内嵌 `-lambda-`：不参与资源段符号注册，按
                    # 其在所有 `-lambda-` 条目中的序号编址（lambda i 槽 =
                    # nsyms - i，操作数 = nsyms - 1 - i；i18n-cad 单 kwote
                    # 实测 `PUSH_G[91]`，nsyms=92；lambda_body 多 lambda
                    # 实测 t3→18、t4→17、t5→16，nsyms=19）。
                    _li = lam_order.get(inst.operands[0], 0)
                    new_idx = nsyms - 1 - _li
                    if 0 <= new_idx <= 0xFFFF:
                        if inst.op_name == "PUSH_VALUE" and new_idx == 0 and not wide:
                            out += bytes([0x03])
                        else:
                            opcode = {"PUSH_VALUE": 0x03, "PUSH_G": 0x09, "SETQ_G": 0x06}[inst.op_name]
                            out += bytes([opcode, new_idx & 0xFF, (new_idx >> 8) & 0xFF])
                        continue
            # 常量引用（quoted lambda 等 CONST 条目）：sym_of 只认 SYMBOL/STRING，
            # CONST 在 fg 表里注册为嵌套结构（gvar 槽 = const_map 命中槽），
            # PUSH_G 操作数 = gvar 槽 - 1（i18n 实测 ANSI 表 fg[98] → 操作数 97）。
            # 字符串（不在 GVARINIT 表）：函数体字符串注册于符号槽末尾
            # （gvar 槽 = nsyms），PUSH_G 操作数 = gvar 槽 - 1 = nsyms - 1
            # （t15 实测 idx 8 → 槽 6、t10 混合模式 idx 8 → 槽 3，nsyms 分别为 7/4）。
            idx0 = inst.operands[0]
            # 参数读取 PUSH_VALUE 的槽（nsyms-argc .. nsyms-1）不是 entry 索引，
            # 单函数 codegen 已输出正确槽，跳过（i18n_v2 实测 offset14 参数读取）。
            # 顶层 `-lambda-`（top_lambda_args）：CAD 用 gvar 槽 - 1 编址
            # （@::vlx 参数 str-vlx fg[9] → 操作数 8），须重映射。
            if (
                inst.op_name == "PUSH_VALUE"
                and cur_args is not None
                and len(cur_args)
                and nsyms - len(cur_args) <= idx0 < nsyms
            ):
                if top_lambda_args:
                    # codegen `-lambda-` 参数读取约定：单 lambda（net/wget，1 个
                    # 顶层 lambda）用 `nsyms-1-slot`（源码第 i 个参数 → 槽
                    # nsyms-1-i，uri/outfile/extra-headers → 30/29/28，idx0 越大
                    # 参数越靠前）；多 lambda（setq-lambda，2 个）用真实符号槽
                    # `get_or_add`（idx0 - (nsyms-len) 直接索引 cur_args）。
                    if len(top_lambda_args) == 1:
                        _pi = (nsyms - 1) - idx0
                    else:
                        _pi = idx0 - (nsyms - len(cur_args))
                    _arg = cur_args[_pi] if 0 <= _pi < len(cur_args) else None
                    if _arg:
                        _gs, _hit = gvar_slot(_arg)
                        _ni = _gs - 1 - (0 if _hit else offset)
                        if 0 <= _ni <= 0xFFFF:
                            out += bytes([0x03] if (inst.op_name == "PUSH_VALUE" and _ni == 0 and not wide) else [0x03, _ni & 0xFF, (_ni >> 8) & 0xFF])
                            continue
                out += seg0[inst.offset : inst.offset + inst.size]
                continue
            if 0 <= idx0 < len(symtab.entries):
                etype = symtab.entries[idx0][0]
                if etype == "CONST":
                    const_structure = symtab.entries[idx0][1]
                    # quoted 单符号 `'sym`：作为符号引用，按 gvar 槽编址
                    # （i18n 实测 `'sym` → SYM 的 gvar 槽；CAD quoted symbol）。
                    if (
                        isinstance(const_structure, tuple)
                        and len(const_structure) == 2
                        and const_structure[0] == "SYMBOL"
                    ):
                        gslot = gvar_map.get(str(const_structure[1]).upper())
                        if gslot is not None:
                            new_idx = gslot - 1
                        else:
                            # 表外 quoted 单符号：注册于符号槽末尾（gvar 槽 =
                            # nsyms，操作数 = nsyms-1）。旧公式 idx0-nfuncs+1
                            # 对大文件（deferred const 区）越界（cache/audit 等
                            # kernel 文件实测 PUSH_G 69/105 ≥ nsyms）。
                            new_idx = nsyms - 1 - offset
                    else:
                        fgstruct = _strip_list_markers(const_structure)
                        gslot = const_map.get(fgstruct)

                        if gslot is not None:
                            new_idx = gslot - 1
                        else:
                            # `_al-bind-alist` 的 locals 常量 `(quote (loc1 ...))`：
                            # 常量 gvar 槽 = `_al-bind-alist` 槽 + 1（t11_localvars
                            # CAD 实测 fg[6]=_al-bind-alist、常量 PUSH_G=6；net/proxy
                            # fg[32]=_al-bind-alist、常量 PUSH_G=32），即 PUSH_G
                            # 操作数 = `_al-bind-alist` 槽。该常量仅在资源流注册
                            # 位置（紧随 `_al-bind-alist`）有意义；build_mvar_tables
                            # 对内嵌 `-lambda-` 的 DEFCODE 会消耗常量，const_map
                            # 查不到 → 需按此关系编址，否则 `nsyms-1` 回退偏移 2
                            # （net/proxy.lsp 实测 OURS 34 vs CAD 32）。
                            if (
                                isinstance(const_structure, tuple)
                                and len(const_structure) == 2
                                and const_structure[0] == "LIST"
                                and isinstance(const_structure[1], (list, tuple))
                                and all(
                                    isinstance(x, tuple)
                                    and len(x) == 2
                                    and x[0] == "SYMBOL"
                                    for x in const_structure[1]
                                )
                            ):
                                _al_slot = gvar_map.get("_AL-BIND-ALIST")
                                if _al_slot is not None:
                                    # 常量 gvar 槽 = `_al-bind-alist` 槽（资源注册序，
                                    # 不随 `-lambda-` 偏移；t11 _al_slot=6 → PUSH_G 6、
                                    # net/proxy _al_slot=32 → 32）。锁 lock.lsp kwote
                                    # offset=1 时 `- offset` 会错成 100（CAD 用 101）。
                                    new_idx = _al_slot
                                    if 0 <= new_idx <= 0xFFFF:
                                        out += bytes(
                                            [0x09, new_idx & 0xFF, (new_idx >> 8) & 0xFF]
                                        )
                                        continue
                            # 未命中 fg 的常量结构（deferred 字节区间引用，
                            # kernel 大文件 `_al-bind-alist '(dir)` 等实测）：
                            # CAD 注册于符号槽末尾，操作数 = nsyms-1
                            # （cache_cad.fas 实测 PUSH_G[60] = nsyms-1）。
                            # 旧公式 idx0-len(func_args)+1 会越界。
                            new_idx = nsyms - 1 - offset
                elif etype == "STRING":
                    # 字符串 PUSH_G：多函数若字符串已在 GVARINIT 表（fg 含 STRING
                    # 项，i18n 实测 `""` fg[44] → 操作数 42 = gvar-1-offset）则按
                    # gvar 槽映射；否则（单函数/表外）注册于符号槽末尾
                    # （gvar 槽 = nsyms，操作数 = nsyms-1，t15 实测）。
                    strval = symtab.entries[idx0][1]
                    gkey = str(strval)  # 字符串大小写敏感（`"date"`/`"DATE"` 异槽）
                    if gkey in str_map:
                        new_idx = str_map[gkey] - 1
                    else:
                        # 表外字符串：优先用资源 symbol_slots 真实索引（platform-api
                        # `"platform"` 在 nsyms 内时 CAD 用真实槽），但该索引
                        # **必须在 gvar 范围内**（t14_command `"Hello from command!"`
                        # 槽 7 ≥ nsyms 6、t10_init `"Hello from lib!"` 槽 8 ≥ nsyms 4
                        # CAD 实测都用 nsyms-1）——越界的函数体字符串按符号槽末尾
                        # 编址（gvar 槽 = nsyms，操作数 = nsyms-1）。
                        _rslot = _res_slot_of(strval)
                        if _rslot is not None and _rslot < nsyms:
                            new_idx = _rslot - 1 - offset
                        elif _res_offset is not None and _rslot is not None:
                            # 表外字符串（init/steps `"flag-nomnl"` symbol_slots[113]
                            # 偏移 6 → fg 107 → 操作数 106，CAD 实测）：同表外符号
                            # 规则 `_rslot - _res_offset`。旧 fallback nsyms-1 偏移 5。
                            _fg_str = _res_to_fg(_rslot)
                            if 0 <= _fg_str < nsyms:
                                new_idx = _fg_str - 1 - offset
                            else:
                                new_idx = nsyms - 1 - offset
                        else:
                            new_idx = nsyms - 1 - offset
                else:
                    # 函数体符号（SYMBOL 且不在 GVARINIT 表——fg 表）：
                    # CAD 对 PUSH_G/PUSH_VALUE/SETQ_G 也用 `gvar 槽 - 1`
                    # （hkrepro 实测 item→1、sym→9 = fg[2]/fg[10] 的 gvar-1）。
                    # 此前仅 USUBR/FUNC 走此映射，单函数普通符号引用（foreach
                    # 循环变量、quoted 符号）保留 symtab 槽——有顶层 form 时
                    # symtab 槽与资源段 gvar 槽错位，CAD 报 `函数错误: :DIALOG`。
                    _sym = sym_of(idx0)
                    if _sym and _sym in gvar_map:
                        new_idx = gvar_map[_sym] - 1
                    elif _sym and cur_args and any(
                        str(a).lower() == _sym.lower() for a in cur_args
                    ):
                        # net/wget 纯顶层 setq-lambda 参数（DEFCODE 第二区，
                        # gvar 槽 = nsyms 表外）：SETQ_G 目标操作数 = gvar_slot
                        # - 1（表外参数 = nsyms-1，uri → 30；与参数读取 PUSH_VALUE
                        # 同规则，line 973）。setq-lambda 参数（str-vlx fg[9]）
                        # 走 gvar_slot 命中分支结果相同（gvar-1）。
                        _gs, _hit = gvar_slot(_sym)
                        new_idx = _gs - 1 - (0 if _hit else offset)
                    else:
                        # 不在 GVARINIT 表（fg）的符号（如 quoted 数据里的特殊
                        # 形式 `setq`/`if`/`lambda` 等，@lisp_u safe-form-p 立即
                        # 应用 lambda 逐元素构建实测）：这些符号注册于资源流
                        # symbol_slots 高位（可能 > nsyms）。CAD 对这些 quoted
                        # 数据用 CONST 整体引用（无独立 PUSH_G），我们逐元素
                        # 构建时须编址到符号槽末尾（gvar 槽 = nsyms，操作数 =
                        # nsyms-1），否则 PUSH_G 越界 → CAD 0xC0000005。
                        # 先查资源 symbol_slots 是否命中 < nsyms 的有效槽。
                        _rs = _res_slot_of(str(_sym)) if _sym else None
                        if _rs is not None and _rs < nsyms:
                            new_idx = _rs - 1 - offset
                        elif (
                            _rs is not None
                            and has_top_forms
                            and module_reg_count is not None
                            and _sym is not None
                            and _res_symbol_slots.count(str(_sym)) > 1
                        ):
                            # 顶层变量在函数体引用（net/probe `@::*network-failure-count*`）：
                            # 符号同时注册于模块区（低位）与函数体区（高位 ≥ nsyms），
                            # 函数体引用用**函数体区槽** = 资源槽 - 模块注册数 - 1
                            # （fg[0] 为代码引用占位：res[108] - 11 - 1 = fg[96]，
                            # operand 95）；旧 fallback `nsyms-1` 偏移 2
                            # （build_mvar_tables 未把该符号放入 fg 表）。仅当
                            # 符号**双注册**（模块区 + 函数体区，count>1）时适用；
                            # 纯函数体符号（scheduler kwote lambda 捕获外层参数
                            # `name` 单注册 symbol_slots[93]）走下方 `_res_offset`
                            # 编址（93 - 23 = fg 70 → 操作数 69，CAD 实测）。
                            _body_slot = _rs - module_reg_count - 1
                            if 0 <= _body_slot < nsyms:
                                new_idx = _body_slot - 1 - offset
                            else:
                                new_idx = nsyms - 1 - offset
                        else:
                            # 纯函数文件（无顶层表达式）表外符号：资源 symbol_slots
                            # 索引与 gvar 槽差固定偏移 `_res_offset`（= 末 fg 符号
                            # 的 _res_slot_of - fg 槽，init/steps FINDFILE
                            # symbol_slots[112] - fg[106] = 6；config/migrate
                            # STRCAT 偏移 12）。init/steps `"flag-nomnl"`
                            # symbol_slots[113] - 6 = fg 107 → 操作数 106、
                            # config/migrate `@::*prefix-config*` 118-12 = 106 →
                            # 105（CAD 实测）。旧 fallback `nsyms-1` 偏移 5/2。
                            if _res_offset is not None and _rs is not None:
                                _fg_ext = _res_to_fg(_rs)
                                if 0 <= _fg_ext < nsyms:
                                    new_idx = _fg_ext - 1
                                else:
                                    new_idx = nsyms - 1 - offset
                            else:
                                new_idx = nsyms - 1 - offset
                if etype == "REAL":
                    # 实数常量按值匹配资源段 REAL 槽（codegen symtab 槽可能
                    # 偏离 GVARINIT，base-function 实测 0.001 槽 174→fg[130]）。
                    # key 用 _real_fmt 规范化：资源流存 15 位（.15g），symtab
                    # 保留完整 float（`(/ 1.0 24.0)`=0.041666666666666664 vs
                    # 资源 `'0.0416666666666667'`），直接 float 比较会失配 → 越界。
                    _ridx = real_map.get(_real_fmt(float(symtab.entries[idx0][1])))
                    new_idx = (_ridx - 1) if _ridx is not None else None
                if new_idx is not None and 0 <= new_idx <= 0xFFFF:
                    if inst.op_name == "PUSH_VALUE" and new_idx == 0 and not wide:
                        out += bytes([0x03])
                    else:
                        opcode = {"PUSH_VALUE": 0x03, "PUSH_G": 0x09, "SETQ_G": 0x06}[inst.op_name]
                        out += bytes([opcode, new_idx & 0xFF, (new_idx >> 8) & 0xFF])
                    continue
        elif inst.op_name == "USUBR" and len(inst.operands) >= 2:
            argc, idx = inst.operands[0], inst.operands[1]
            flags = inst.operands[2] if len(inst.operands) >= 3 else 3
            sym = sym_of(idx)
            if sym and sym in gvar_map:
                new_idx = gvar_map[sym] - 1
                out += _subr_bytes(0x35, argc, new_idx, flags, wide=wide)
            elif sym and 0 <= idx < len(symtab.entries) and symtab.entries[idx][0] == "SYMBOL":
                # 符号槽末尾（超出 gvar 表，fg 仅 nsyms 项）的符号：CAD 按
                # gvar 槽 = nsyms 编址（t22 实测 vlax-get-acad-object 操作数 11 =
                # nsyms-1，符号槽末尾注册），USUBR 操作数 = nsyms - 1。但符号
                # 若在资源 symbol_slots 有真实索引（< nsyms，如 cmd.lsp C:@U 的
                # @::upgrade = symslot[94] 而 build_mvar_tables 把它当 DEFCODE
                # 模块参数解析为 None、gvar_map 查不到）则用真实槽
                # （操作数 = 94-1-offset = 93，CAD 实测）。
                _rslot = _res_slot_of(sym)
                if _rslot is not None:
                    _fg_slot = _rslot - (_res_offset or 0)
                    if 0 <= _fg_slot < nsyms:
                        # 表内符号（资源 5b 块注册、gvar 槽 < nsyms，但被
                        # DEFCODE 消费 → build_mvar_tables 解析为 None）：
                        # 操作数 = gvar 槽 - 1，**不含** offset（cmd.lsp
                        # @::upgrade fg 94→93、command @::internetp fg 150→149，
                        # 后者 gvar 槽恰 = nsyms-1）。
                        new_idx = _fg_slot - 1
                    else:
                        new_idx = nsyms - 1 - offset
                else:
                    new_idx = nsyms - 1 - offset
                if 0 <= new_idx <= 0xFFFF:
                    out += _subr_bytes(0x35, argc, new_idx, flags, wide=wide)
                else:
                    out += seg0[inst.offset : inst.offset + inst.size]
            else:
                out += seg0[inst.offset : inst.offset + inst.size]
            continue
        elif inst.op_name == "FUNC" and len(inst.operands) >= 2:
            # FUNC 第二个操作数为符号引用（gvar 槽 - 1，同 USUBR）。i18n 实测
            # `_al-bind-alist` 调用 FUNC[1,84]（gvar 槽 86 → 84，kwote offset=1）。
            argc, idx = inst.operands[0], inst.operands[1]
            flags = inst.operands[2] if len(inst.operands) >= 3 else 3
            sym = sym_of(idx)
            if sym and sym in gvar_map:
                new_idx = gvar_map[sym] - 1
                out += _subr_bytes(0x51, argc, new_idx, flags, wide=wide)
            elif sym and 0 <= idx < len(symtab.entries) and symtab.entries[idx][0] == "SYMBOL":
                # 同 USUBR：符号槽末尾（超出 gvar 表）的 FUNC 目标 gvar 槽 = nsyms。
                # 符号在资源 symbol_slots 有真实索引（< nsyms）时用真实槽（同
                # USUBR，cmd.lsp @::upgrade symslot[94] → 操作数 93）。
                _rslot = _res_slot_of(sym)
                if _rslot is not None:
                    _fg_slot = _rslot - (_res_offset or 0)
                    if 0 <= _fg_slot < nsyms:
                        # 同 USUBR：表内符号不含 offset。
                        new_idx = _fg_slot - 1
                    else:
                        new_idx = nsyms - 1 - offset
                else:
                    new_idx = nsyms - 1 - offset
                if 0 <= new_idx <= 0xFFFF:
                    out += _subr_bytes(0x51, argc, new_idx, flags, wide=wide)
                else:
                    out += seg0[inst.offset : inst.offset + inst.size]
            else:
                out += seg0[inst.offset : inst.offset + inst.size]
            continue
        out += seg0[inst.offset : inst.offset + inst.size]
    return bytes(out)


def _build_cad_module_code(
    top_level_bc: bytes,
    symtab,
    other_forms,
    n_funcs: int = 0,
    top_level_count: int = 0,
    top_after_defun: bool = False,
    func_names: object = (),
    n_post_forms: int = 0,
    n_globals: int = 0,
    gvar_map: object = None,
    top_lambda_slots: Optional[dict] = None,
    real_map: Optional[dict] = None,
    n_pre: int = 0,
    skip_funcs: Optional[set] = None,
    n_cmds: int = 0,
    mid_counts: tuple = (),
) -> bytes:
    """把顶层表达式字节码转换为 CAD 风格的模块代码。

    CAD 模块代码规则（逆向，AutoCAD 24.1s 实测）：
    - 符号引用使用 gvar 槽 = 符号槽 + 1
    - 顶部 ``PUSH_G <模块注册符号数+1>; POP`` 占位
    - 顶层 setq → ``PUSH_G <值槽+1>; DUP; SETQ_G <变量槽+1>``
    - 每个顶层语句后 POP（最后一句除外）
    - 有 defun 时追加函数注册尾 ``JUMP + PUSH_G <模块注册+2>; SETQ_G 1; PUSH_G 1``

    对每个顶层 form：setq 用 CAD 的 DUP 模式；其余用 codegen 输出并统一
    符号槽 +1。
    """
    if not other_forms:
        return top_level_bc

    from compiler.codegen import CodeGenerator, BytecodeBuffer

    # c: 命令混合模式：vl-ACAD-defun 在模块注册段占一个符号（+1），使占位符/
    # b 槽/C 槽相对普通混合模式全局 +1（large_synthetic CAD 实测 placeholder
    # 147、reg0 b=277、c=146）。
    module_reg_count = n_funcs + top_level_count + n_cmds
    out = bytearray(b"\x14\x01\x00\x00\x00")  # DEFUN 模块头
    out += bytes([0x09]) + struct.pack("<H", module_reg_count + 1) + b"\x0a"  # 占位

    # 顶层语句按源码位置分组：最后一个 defun 之后的顶层语句（mix2 的
    # `(setq x 10)`、p04 的 `(setq *codepage* ...)` 与 `(if ...)`）排到函数
    # 注册尾之后；defun 之前的排在 JUMP 之前。n_post_forms 由调用方按最后
    # 一个 defun 在 program.forms 中的位置计算，支持多个 post-form（CAD
    # p04-p07 实测）。
    if top_after_defun and other_forms:
        n_post = n_post_forms
        if n_post:
            pre_forms = other_forms[:-n_post]
            post_forms = other_forms[-n_post:]
        else:
            pre_forms = other_forms[:-1]
            post_forms = [other_forms[-1]]
    else:
        pre_forms = other_forms
        post_forms = []

    def _stmt_bytes(form, tail: bool = False):
        """把单个顶层 form 编译为模块代码语句（setq 用 CAD 的 DUP 模式）。

        tail=True 表示该 form 是模块最终保留值（如最后一个 post-form），
        CAD 以其求值结果作为模块代码的返回值——此时 form 内部的尾 setq
        （如 if-then 分支最后一句）需按尾上下文编译（补 DUP，p04 实测）。
        """
        from compiler.ast_nodes import Symbol, String as _Str, Integer as _Int, Real as _Real

        # gvar_map（二次生成）时：模块代码符号引用按资源流实际 gvar 槽重映射。
        _gvar = gvar_map
        _symtab = symtab if _gvar else None

        cg = CodeGenerator(symtab, stub_format=True, nsyms=len(symtab.entries))
        # 模块代码上下文：顶层 if-then 的 setq 需 DUP、无 else if 补 PUSH_NIL
        # （CAD 模块代码实测 `0b 06` / `01 0a`，i18n-cad）。
        cg._module_mode = True
        cg._module_code_ctx = True
        handled = False

        def _slot_gv(idx):
            """symtab idx → 实际 gvar 槽（gvar_map 可用时）；否则 idx+1+n_cmds。"""
            if _gvar and _symtab is not None and 0 <= idx < len(_symtab.entries):
                _t, _v = _symtab.entries[idx]
                if _t in ("SYMBOL", "STRING"):
                    _s = _gvar.get(str(_v).upper())
                    if _s is not None:
                        return _s
            return idx + 1 + n_cmds

        if isinstance(form, Setq):
            # 多对 setq：CAD 输出全部 pair。中间 pair 用
            # `PUSH_<值>; SETQ_G`（无 DUP），最后一个 pair 用
            # `PUSH_<值>; DUP; SETQ_G`。值：`'()`/`nil` → PUSH_NIL，
            # 符号/字符串 → PUSH_G <gvar 槽>。任一对值非常量（INT/REAL/
            # 列表等，需 codegen）时整条退回通用 codegen 路径。
            pairs_bc = bytearray()
            n = len(form.pairs)
            for i, (target, value) in enumerate(form.pairs):
                t_idx = _slot_of(symtab, target)
                if t_idx is None:
                    break
                pre = bytearray()
                if _is_empty_quote(value):
                    pre += bytes([0x01])  # PUSH_NIL
                    v_ok = True
                elif isinstance(value, Symbol) and value.name == "nil":
                    pre += bytes([0x01])  # PUSH_NIL（CAD 用 PUSH_NIL 值 nil）
                    v_ok = True
                else:
                    if isinstance(value, _Int):
                        # 整数字面量：内联 PUSH_INT8 / PUSH_INT32（CAD 模块代码
                        # `setq x 10` 实测 `32 0a 0b 06 03 00`；与 codegen 编码一致），
                        # 无需走通用路径（避免 per-form 反汇编）。
                        val = value.value
                        if -128 <= val <= 127:
                            pre += bytes([0x32, val & 0xFF])  # PUSH_INT8
                        elif -2147483648 <= val <= 2147483647:
                            pre += bytes([0x33]) + struct.pack("<i", val)  # PUSH_INT32
                        else:
                            # 超出 int32 范围：codegen 会按 REAL 编码，退回通用路径
                            break
                        v_ok = True
                    elif isinstance(value, _Real):
                        # 实数常量：纯顶层文件（无 defun，无 fg 表）模块代码用
                        # PUSH_G 引用 REAL 槽（gvar 槽 = 符号槽+1，constants.lsp
                        # CAD golden 实测 `09 1b 00`）。混合文件（有 defun）实数
                        # 注册在 fg 表、模块代码(rg 上下文)读不到，内联
                        # PUSH_REAL `3b <ascii> 00` 保证值正确（@lisp_u
                        # `(setq @::*seconds-per-day* 86400.0)` 实测）。
                        if n_funcs == 0:
                            _rk = f"__real_{value.value}__"
                            _r_idx = symtab.name_to_idx.get(_rk)
                            if _r_idx is not None:
                                pre += bytes([0x09]) + struct.pack("<H", _slot_gv(_r_idx))  # PUSH_G
                                v_ok = True
                            else:
                                from compiler.resource_builder import _real_fmt as _rf

                                pre += b"\x3b" + _rf(float(value.value)).encode("ascii") + b"\x00"
                                v_ok = True
                        else:
                            from compiler.resource_builder import _real_fmt as _rf

                            pre += b"\x3b" + _rf(float(value.value)).encode("ascii") + b"\x00"
                            v_ok = True
                    else:
                        v_idx = _slot_of(symtab, value)
                        if v_idx is None:
                            break  # 复杂值 → 退回通用路径
                        if isinstance(value, Symbol):
                            # 非引号符号值：函数符号（函数别名 setq）CAD 用
                            # PUSH_G（@lisp_u 实测 `(setq @::unschedule-task
                            # @::string-to-list)` → `09 <槽>`）；普通变量用
                            # PUSH_VALUE（setcmp `(setq _ @::_)` 实测
                            # `03 <槽+1>`）。PUSH_VALUE 读函数槽得到 SUBR，
                            # SETQ_G 绑定报"要绑定的对象不正确"。
                            _vn = value.name
                            _fns = symtab.function_offsets if hasattr(symtab, "function_offsets") else {}
                            _is_func = _vn in _fns or _vn in set(func_names) or (
                                _vn.lower() in {str(k).lower() for k in _fns}
                            )
                            if _is_func:
                                pre += bytes([0x09]) + struct.pack("<H", _slot_gv(v_idx))  # PUSH_G
                            else:
                                pre += bytes([0x03]) + struct.pack("<H", _slot_gv(v_idx))  # PUSH_VALUE
                        else:
                            pre += bytes([0x09]) + struct.pack("<H", _slot_gv(v_idx))  # PUSH_G
                        v_ok = True
                if not v_ok:
                    break
                if i == n - 1:
                    pre += b"\x0b"  # DUP（仅在最后一对）
                pre += bytes([0x06]) + struct.pack("<H", _slot_gv(t_idx))  # SETQ_G
                pairs_bc += pre
            else:
                return bytes(pairs_bc)
        if isinstance(form, InPackage):
            # `(in-package :@)`：CAD 发射真实调用 `PUSH_VALUE <:@>; USUBR(1,
            # IN-PACKAGE)`（base-function CAD golden 实测 `03 2f 00 35 01 2e 00
            # 03`；atlisp_u CAD golden 实测 12 次 `GVAR_PUSH 954(:@); FUNC_REF
            # 937,1`——AGENTS.md "模块代码不发射" 旧注释过时，2026-08-16 勘误）。
            # 包名取 form.name（command.lsp `(in-package :C)`，勿硬编码 :@）。
            # 符号 IN-PACKAGE/<包名> 经 _collect_symbol_nodes 注册。
            _pkg_idx = symtab.name_to_idx.get(form.name)
            _fn_idx = symtab.name_to_idx.get("in-package")
            if _pkg_idx is not None and _fn_idx is not None:
                return (
                    bytes([0x03]) + struct.pack("<H", _slot_gv(_pkg_idx))  # PUSH_VALUE :@
                    + encode_usubr(1, _slot_gv(_fn_idx), 3)  # USUBR(1, in-package)
                )
            return bytes([0x01])  # 兜底：槽缺失时退化为 PUSH_NIL 占位
        if isinstance(form, Defpackage):
            # `(defpackage :C (:use :cl) (:export ...))`：CAD 编译为（sub-system/
            # command CAD golden 实测）：
            #   PUSH_VALUE :C（包名）
            #   PUSH_VALUE :CL; USUBR 1, :USE        # 每个 (:use 包) 子句
            #   PUSH_VALUE <exports 正序>; USUBR <n>, :EXPORT
            #   USUBR 3, DEFPACKAGE
            # 各子调用结果都保留在栈上供 defpackage 取用，内部**无** `NIL;
            # PUSH_VALUE 0` 清理（CAD command 实测 raw：`03 26 00 03 25 00 35
            # 01 24 00 03 03 23 00 ... 35 0d 16 00 03 35 03 15 00 03 0a`——
            # 仅 _emit_stmts 在语句末尾补 POP）。USUBR argc=3 取包名、use 结果、
            # export 结果。`defpackage`/`:use`/`:export`/包名/包名列表符号经
            # _collect_symbol_nodes 的 Defpackage 分支注册。
            _fn_defpkg = symtab.name_to_idx.get("defpackage")
            _fn_use = symtab.name_to_idx.get(":use")
            _fn_export = symtab.name_to_idx.get(":export")
            if _fn_defpkg is not None and _fn_use is not None and _fn_export is not None:
                _name_idx = symtab.name_to_idx.get(form.name)
                if _name_idx is not None:
                    parts = [bytes([0x03]) + struct.pack("<H", _slot_gv(_name_idx))]
                    ok = True
                    for _u in form.use:
                        _u_idx = symtab.name_to_idx.get(_u)
                        if _u_idx is None:
                            ok = False
                            break
                        parts.append(bytes([0x03]) + struct.pack("<H", _slot_gv(_u_idx)))
                        parts.append(encode_usubr(1, _slot_gv(_fn_use), 3))
                    if ok:
                        for _e in form.export:
                            _e_idx = symtab.name_to_idx.get(_e)
                            if _e_idx is None:
                                ok = False
                                break
                            parts.append(bytes([0x03]) + struct.pack("<H", _slot_gv(_e_idx)))
                        if ok:
                            if form.export:
                                parts.append(encode_usubr(len(form.export), _slot_gv(_fn_export), 3))
                            parts.append(encode_usubr(3, _slot_gv(_fn_defpkg), 3))
                            return b"".join(parts)
            return bytes([0x01])  # 兜底：槽缺失时退化为 PUSH_NIL 占位
        if isinstance(form, Call) and str(form.name).lower() == "use-package":
            # `(use-package :autolisp)`：同 in-package，CAD 发射真实调用
            # `PUSH_VALUE <:autolisp>; USUBR(1, USE-PACKAGE)`（base-function CAD
            # golden 实测 `03 2d 00 35 01 2c 00 03`；atlisp_u CAD golden 实测 7 次）。
            _arg = form.args[0] if form.args else None
            _arg_idx = (
                symtab.name_to_idx.get(_arg.name)
                if isinstance(_arg, Symbol) else None
            )
            _fn_idx = symtab.name_to_idx.get("use-package")
            if _arg_idx is not None and _fn_idx is not None:
                return (
                    bytes([0x03]) + struct.pack("<H", _slot_gv(_arg_idx))  # PUSH_VALUE :autolisp
                    + encode_usubr(1, _slot_gv(_fn_idx), 3)  # USUBR(1, use-package)
                )
            return bytes([0x01])  # 兜底：槽缺失时退化为 PUSH_NIL 占位
        # 顶层 `(set/setq 'sym (lambda ...))`（纯顶层文件，CAD `-lambda-` SUBR）：
        # 模块代码 `PUSH_G <sym>; PUSH_G <-lambda-槽>; FUNC_REF set`，不经
        # kwote/引用常量（CAD 实测 bootstrap）。`-lambda-` 槽由 seg0 生成阶段
        # 经 top_lambda_slots 映射（DEFCODE 注册为可调用 SUBR）。
        if top_lambda_slots:
            from compiler.ast_nodes import LambdaNode as _LN

            _tgt = None
            _is_lam = False
            if isinstance(form, Call) and form.name == "set" and len(form.args) == 2:
                _t0 = form.args[0]
                if isinstance(_t0, QuotedExpr) and isinstance(_t0.expr, Symbol):
                    _tgt = _t0.expr.name
                _v1 = form.args[1]
                _is_lam = isinstance(_v1, _LN) or (
                    isinstance(_v1, QuotedExpr) and isinstance(_v1.expr, _LN)
                )
            elif isinstance(form, Setq):
                for _t, _v in form.pairs:
                    if isinstance(_t, Symbol):
                        _tgt = _t.name
                        _is_lam = isinstance(_v, _LN) or (
                            isinstance(_v, QuotedExpr) and isinstance(_v.expr, _LN)
                        )
                        break
            if _tgt is not None and _is_lam and _tgt in top_lambda_slots:
                _sym_idx = symtab.name_to_idx.get(_tgt)
                _lam_slot = top_lambda_slots[_tgt]
                _b = bytearray()
                # CAD `(set 'X (lambda ...))`（bootstrap CAD golden 实测）：
                # 模块代码 `PUSH_G <sym>; JUMP 0; PUSH_G <-lambda-槽>; USUBR(2,
                # SET)` ——用 `set` 函数调用绑定（不是 setq 协议）。`-lambda-`
                # 槽 = _lam_slot（不 +1），SET 为模块注册的 set 内建 gvar 槽。
                if isinstance(form, Call) and form.name == "set":
                    _set_idx = symtab.name_to_idx.get("set")
                    if _sym_idx is not None and _set_idx is not None:
                        _b += bytes([0x09]) + struct.pack(
                            "<H", _slot_gv(_sym_idx)
                        )  # PUSH_G <sym>
                        _b += bytes([0x57, 0x00, 0x00, 0x00, 0x00])  # JUMP 0
                        # `-lambda-` 槽是 DEFCODE 区注册的独立 gvar 槽（不在
                        # symtab/gvar_map），PUSH_G = _lam_slot。不能用 _slot_gv
                        # （会把槽当 symtab 索引查 entries → 错位到 gvar_map）。
                        _b += bytes([0x09]) + struct.pack("<H", _lam_slot)  # PUSH_G <-lambda->
                        _b += encode_usubr(
                            2, _slot_gv(_set_idx), 3
                        )  # USUBR(2, set)
                        return bytes(_b)
                # CAD 纯顶层 `(setq X (lambda ...))`（setq-lambda.lsp CAD golden
                # 实测）：模块代码 `JUMP 0; PUSH_G <-lambda-槽>; DUP; SETQ_G <sym>`
                # ——用 setq 协议绑定（不是 `set` 函数）。JUMP 0 为占位跳转。
                _b += bytes([0x57, 0x00, 0x00, 0x00, 0x00])  # JUMP 0
                # `-lambda-` 槽是 DEFCODE 区注册的独立 gvar 槽（不在 symtab/
                # gvar_map），PUSH_G = 符号槽 + 1（_lam_slot 28 → 29）。不能用
                # _slot_gv（会把槽当 symtab 索引查 entries → 错位到 gvar_map）。
                _b += bytes([0x09]) + struct.pack("<H", _lam_slot + 1)  # PUSH_G <-lambda->
                _b += bytes([0x0b])  # DUP
                if _sym_idx is not None:
                    _b += bytes([0x06]) + struct.pack("<H", _slot_gv(_sym_idx))  # SETQ_G <sym>
                return bytes(_b)
        fb = BytecodeBuffer()
        cg._emit_expr(fb, form, _tail=tail)
        fb.resolve()
        bc = bytes(fb.data)
        if isinstance(form, Setq) and not tail and len(form.pairs) == 1:
            # setq 值非常量（INT/REAL/列表等）：CAD 在 SETQ_G 前插入 DUP
            # 保留返回值（mix2 `(setq x 10)` 实测 `32 0a 0b 06 03 00`）。
            # 注意：多对 setq 的末对 DUP 已由 codegen 生成（n>1 末对），
            # 此处仅单对 setq 补 DUP（platform 实测多对末对无额外 `0b`）。
            # 不能简单正则找 `06 ..`——USUBR 的 idx 字节可能为 0x06，
            # 需定位真正的 SETQ_G 指令偏移。
            from decompiler.fas4_decompiler import Disassembler

            _dis = Disassembler(short_subr=not (len(symtab.entries) > 256))
            try:
                _insts = _dis.disassemble(bc, len(symtab.entries), sym_count=len(symtab.entries))
            except Exception:
                _insts = []
            _setq_off = None
            for _i in _insts:
                if _i.op_name == "SETQ_G":
                    _setq_off = _i.offset
            if _setq_off is not None:
                bc = bc[:_setq_off] + b"\x0b" + bc[_setq_off:]
        return _offset_slots(bc, len(symtab.entries), gvar_map=_gvar, symtab=_symtab, real_map=real_map,
                             n_cmds=n_cmds)

    def _emit_stmts(forms, last_no_pop: bool):
        """输出一组语句，每条后 POP；last_no_pop=True 时最后一条不跟 POP。

        自平衡语句（progn/while/foreach/repeat 自身管理栈，`_stmt_bytes` 返回
        已平衡代码）不再追加 POP——cl-macros 顶层 `(progn (setq ...) ...)` 的
        progn 是唯一顶层语句，CAD 模块代码实测 `USUBR; SETQ_G` 后直接 JUMP 注册、
        无 `0a`；@lisp-env 的 mid progn（setq 无 `0b`/`0a`）同规则。直接
        setq（DUP 保留值）/调用/符号仍留值 → 需 POP（event-bus 实测
        `setq ... DUP SETQ_G; POP`）。
        """
        nonlocal out
        _self_balancing = (Progn, WhileNode, ForeachNode, RepeatNode)
        for i, form in enumerate(forms):
            tail = last_no_pop and i == len(forms) - 1
            stmt = _stmt_bytes(form, tail=tail)
            out += stmt
            if (i < len(forms) - 1 or not last_no_pop) and not isinstance(form, _self_balancing):
                out += b"\x0a"  # POP

    # ── 顶层语句分组（CAD 实测）─────────────────────────────────────
    # globals_forms：首个 defun 之前的顶层 setq 语句（模块全局初始化）。
    # mid_forms：首个 defun 与最后一个 defun 之间的顶层语句。
    # post_forms：最后一个 defun 之后的顶层语句。
    # CAD 把**第一个**函数的 JUMP+注册放在 globals 之后（模块代码后续语句
    # 可调用它），把其余函数注册放在所有 mid 语句之后、post 语句之前
    # （i18n/p04 实测）。单函数文件 mid 为空、无尾部注册，等价于并列形式。
    n_globals = max(0, min(n_globals, len(pre_forms)))
    globals_forms = pre_forms[:n_globals]
    mid_forms = pre_forms[n_globals:]
    # 首个函数注册后是否还有后续内容（需 `PUSH_G c; POP` 清理）。
    has_follow = bool(n_funcs > 1 or mid_forms or post_forms)
    # 末全局是 Progn（顶层 `(progn ...)` 展开后 defun 提升、剩余表达式包回
    # Progn，cl-macros/cl-functions/init/compat 实测）：CAD 的纯尾部注册
    # （无 post、无 START 函数）省略 `PUSH_G c; POP` no-op，每组仅
    # `JUMP; PUSH_G b; SETQ_G c`（cl-macros golden 实测）；直接 setq/call
    # 末全局（net/proxy/ax-request）仍保留 no-op。
    _last_global_progn = bool(globals_forms) and isinstance(globals_forms[-1], Progn)
    # post 语句为自平衡块（progn/while/foreach/repeat/cond）时，注册尾
    # `PUSH_G c; POP` no-op 同样省略（cl-functions 末 post PROGN 实测
    # `(setq :@ ':@)` 后直接 END_DEFUN，无 `09 c 00 0a`）。
    _post_selfbal = bool(post_forms) and all(
        isinstance(_p, (Progn, WhileNode, ForeachNode, RepeatNode, Cond))
        for _p in post_forms
    )
    # 末全局是 Progn 且无 post/START（cl-macros）或 post 为自平衡块（cl-functions
    # 末 post PROGN）时，TAIL 注册省略 `PUSH_G c; POP` no-op（START 注册仍保留）。
    _skip_reg_pc = (
        (_last_global_progn and not post_forms and n_pre == 0)
        or _post_selfbal
    )

    _emit_stmts(globals_forms, last_no_pop=(n_funcs == 0 and not post_forms))

    _last_reg_cmd = False
    if n_funcs > 0:
        # c: 命令混合模式：vl-ACAD-defun 在模块注册段占一个符号（gvar 槽 =
        # 源码首个命令的符号槽 + 1，large_synthetic 实测槽 19），其后的
        # 函数 gvar 槽 +1（CMD-000 符号槽 18 → c=20；lgf-var-000 槽 144 →
        # c=146）。命令注册用 CAD 24 字节模式（含 USUBR 调用 vl-ACAD-defun）。
        _first_cmd_slot = None
        if n_cmds and func_names:
            for _fn in func_names:
                if str(_fn).lower().startswith("c:"):
                    _first_cmd_slot = symtab.name_to_idx.get(_fn)
                    break

        def _is_cmd(i):
            return bool(func_names) and i < len(func_names) and str(func_names[i]).lower().startswith("c:")

        def _reg(i):
            # 有 defun：追加函数注册尾（CAD 实测）。每函数一组
            # `PUSH_G <b>; SETQ_G <c>`，组间 `PUSH_G <c>; POP; JUMP`；
            # b = 2*n_funcs+1 + top_level_count + n_cmds - i（模块注册偏移，
            # vl-ACAD-defun 符号使占位符/b 槽全局 +1）。
            # c 槽 = 源码注册序：函数占 c = 符号槽 + 1（p03 实测
            # @::codepage2lang 槽 4 → c=5）；符号槽 ≥ 源码首个命令槽时再 +1
            # （vl 符号占用其后一个槽）；未显式给定函数名时退化为相对编号
            # n_funcs - i。
            nonlocal out
            b = 2 * n_funcs + 1 + top_level_count + n_cmds - i
            fn_slot = symtab.name_to_idx.get(func_names[i]) if i < len(func_names) and func_names else None
            c = (fn_slot + 1) if fn_slot is not None else (n_funcs - i)
            if fn_slot is not None and _first_cmd_slot is not None and fn_slot >= _first_cmd_slot:
                c += 1
            out += bytes([0x09]) + struct.pack("<H", b)  # PUSH_G b
            out += bytes([0x06]) + struct.pack("<H", c)  # SETQ_G c
            return c

        _skip = skip_funcs or set()
        # 首个 defun 与最后一个 defun 之间的顶层语句（含 setq-lambda 绑定）。
        # mid 语句为**别名 set**（`(set 'cl::xxx cl::xxx)`，cl-functions 的
        # #-sbcl + progn 展开模式）时，CAD 把每条 mid 语句与对应函数的注册
        # **交错**（[reg i, mid[i], reg i+1, mid[i+1], ...]）；普通 mid 语句
        # （i18n/platform 的 setq/if）仍全部 mid 先、注册后。
        def _mid_lead_alias(_m):
            _first = _m.forms[0] if isinstance(_m, Progn) else _m
            return (
                isinstance(_first, Call)
                and str(_first.name).lower() == "set"
                and len(_first.args) == 2
                and isinstance(_first.args[0], QuotedExpr)
                and isinstance(_first.args[0].expr, Symbol)
                and isinstance(_first.args[1], Symbol)
            )

        def _mid_is_set(_m):
            _first = _m.forms[0] if isinstance(_m, Progn) else _m
            return isinstance(_first, Call) and str(_first.name).lower() == "set"

        # mid 语句**多数为 `set` 别名绑定**（`(set 'X @::X)`，cl-functions 的
        # #-sbcl + progn 展开、base-function 的 handle-keywords/leap-yearp 等
        # 全部）时，CAD 把每条 mid 语句与对应函数的注册**交错**
        # （[reg i, mid[i], reg i+1, mid[i+1], ...]）；普通 mid 语句
        # （i18n/platform 的 setq/if 占多数）仍全部 mid 先、注册后。
        # base-function 的 mid[0] `(set '$platform (read ...))`（值非符号）
        # 与 mid[5] `(setq @::*mktime-epoch* ...)` 非干净别名 set，但同样交错。
        _interleave_mid = (
            len(mid_forms) > 0
            and sum(_mid_is_set(_m) for _m in mid_forms) * 2 > len(mid_forms)
        )
        # START 函数注册：前 n_pre 个函数（定义在首个顶层语句之前，CAD
        # platform 实测 set-locale/get-locale 在 globals 语句前注册）。
        # 每组 `JUMP; PUSH_G b; SETQ_G c; PUSH_G c; POP`；命令组为 CAD
        # 24 字节模式 `JUMP; PUSH_G b; SETQ_G c; PUSH_G c; USUBR(1,<vl槽>);
        # POP; PUSH_G c; POP`（vl-ACAD-defun 注册命令）。
        _vl_slot = (_first_cmd_slot + 1) if _first_cmd_slot is not None else None
        _mi = 0
        _mid_counts = mid_counts or ()

        def _emit_mid_for(i):
            # 交错模式下按 mid_counts 把函数 i 的 mid 语句分配给它（无 mid 的
            # 函数跳过）。mid_forms 顺序与源码 mid 顺序一致（cl-functions
            # @::eval/@::require 无 mid，不消耗 mid_forms）。
            nonlocal _mi
            if not _interleave_mid:
                return
            _cnt = _mid_counts[i] if i < len(_mid_counts) else 0
            if _cnt > 0 and _mi < len(mid_forms):
                _emit_stmts(mid_forms[_mi : _mi + _cnt], last_no_pop=False)
                _mi += _cnt

        for i in range(min(n_pre, n_funcs)):
            out += b"\x57\x00\x00\x00\x00"
            c = _reg(i)
            if _skip_reg_pc:
                # START 注册也省略 `PUSH_G c; POP` no-op（cl-functions 首个
                # defun cl::stringp 的 START 注册 CAD 实测无 no-op）。
                _emit_mid_for(i)
                continue
            out += bytes([0x09]) + struct.pack("<H", c)
            if _is_cmd(i) and _vl_slot is not None:
                out += bytes([0x35, 0x01]) + struct.pack("<H", _vl_slot) + bytes([0x01, 0x0a])
                out += bytes([0x09]) + struct.pack("<H", c)
            out += b"\x0a"
            _emit_mid_for(i)

        def _reg_emit(i):
            # 其余函数注册（最后一个 defun 之前、post 语句之前）。setq-lambda
            # 函数（skip_funcs）已由 mid_forms 的 setq 绑定，不在此 `_reg`。
            nonlocal out, _last_reg_cmd
            out += b"\x57\x00\x00\x00\x00"
            c = _reg(i)
            _last_reg_cmd = _is_cmd(i)
            if _is_cmd(i) and _vl_slot is not None:
                out += bytes([0x09]) + struct.pack("<H", c)
                out += bytes([0x35, 0x01]) + struct.pack("<H", _vl_slot) + bytes([0x01, 0x0a])
                out += bytes([0x09]) + struct.pack("<H", c)
                # 命令注册 `PUSH_G c; USUBR; POP; PUSH_G c` 对**末尾**命令也发射
                # （CAD command 实测末函数 C:@DIAG 有 vl-ACAD-defun USUBR），但
                # 末尾命令（无后续注册/post_forms）不再跟 `0a` POP（END_DEFUN 前
                # CAD 实测 `... 09 01 00 35 01 12 00 01 0a 09 01 00 16`）。
                if i < n_funcs - 1 or post_forms:
                    out += b"\x0a"
            elif (i < n_funcs - 1 and not _skip_reg_pc) or (post_forms and not _post_selfbal):
                # 非命令注册 `PUSH_G c; POP` no-op：仅当注册后有后续内容
                # （非末尾、post 语句、或非 Progn 末全局的纯尾部）时发射。
                out += bytes([0x09]) + struct.pack("<H", c)
                out += b"\x0a"

        if _interleave_mid:
            # mid 别名 set 与注册交错：每个注册（START/TAIL）后紧跟其对应
            # 函数的 mid set（cl-functions `(set 'cl::xxx cl::xxx)`，按
            # mid_counts 分配，无 mid 函数跳过）。
            for i in range(n_pre, n_funcs):
                if func_names and i < len(func_names) and func_names[i] in _skip:
                    continue
                _reg_emit(i)
                _emit_mid_for(i)
        else:
            _emit_stmts(mid_forms, last_no_pop=False)
            for i in range(n_pre, n_funcs):
                if func_names and i < len(func_names) and func_names[i] in _skip:
                    continue
                _reg_emit(i)
    else:
        _emit_stmts(mid_forms, last_no_pop=(not post_forms))
    if post_forms:
        _emit_stmts(post_forms, last_no_pop=True)
    elif not top_after_defun and not _last_reg_cmd:
        out += bytes([0x09]) + struct.pack("<H", 1)  # PUSH_G 1
    out += b"\x16"  # END_DEFUN
    return bytes(out)


def _slot_of(symtab, node):
    """返回 AST 节点的符号/字符串槽索引；非字面量返回 None。"""
    from compiler.ast_nodes import Symbol, String as _Str

    if isinstance(node, Symbol):
        from compiler.cad_symbols import normalize_vla_name

        return symtab.name_to_idx.get(SymbolTable._normalize_name(normalize_vla_name(node.name)))
    if isinstance(node, _Str):
        return symtab.name_to_idx.get(f"__str_{node.value}__")
    return None


def _is_empty_quote(node) -> bool:
    """判断是否为空列表引用 `'()`（CAD 用 PUSH_NIL，无常量槽）。"""
    from compiler.ast_nodes import QuotedExpr, ListExpr

    return isinstance(node, QuotedExpr) and isinstance(node.expr, ListExpr) and not node.expr.items


def _offset_slots(bc: bytes, n_sym: int, gvar_map=None, symtab=None, real_map: Optional[dict] = None,
                  n_cmds: int = 0) -> bytes:
    """把字节码中的符号槽引用 +1（CAD 模块代码用 gvar 槽 = 符号槽+1）。

    处理 PUSH_G(0x09)/PUSH_VALUE(0x03)/SETQ_G(0x06)/USUBR(0x35) 的符号槽。
    stub 的 PUSH_VALUE[0]（单字节 ``03``）与调用后清理序列 ``00 03`` 不偏移。

    gvar_map 提供时（模块代码二次生成）：按资源流实际 gvar 槽重映射符号引用。
    commands 混合模式（atlisp_u）下模块注册把函数名逆序置前、顶层符号在后，
    ``symtab_idx+1`` 不再等于实际 gvar 槽，须用资源段 GVARINIT 重建的
    ``{符号名大写: gvar槽}`` 修正（否则顶层函数调用 USUBR 引用错误槽位）。

    n_cmds（vl-ACAD-defun 符号数）：资源模块注册插入 vl-ACAD-defun 使其后
    符号 gvar 槽整体 +1。gvar_map 命中者已含该偏移；未命中（表外符号）的
    fallback ``idx+1`` 须补 ``+n_cmds``，否则模块代码引用错槽
    （atlisp_u ``(set 'e2o 'vlax-ename->vla-object)`` 的 PUSH_VALUE 实测）。
    """
    from decompiler.fas4_decompiler import Disassembler

    # 大文件（nsyms>256）模块代码 USUBR 为 5 字节（idx16+flags），须用
    # short_subr=False 反汇编并按 5 字节重编码（与 codegen wide_subr 一致）。
    wide = n_sym > 256
    dis = Disassembler(short_subr=not wide)
    try:
        insts = dis.disassemble(bc, n_sym, sym_count=n_sym)
    except Exception:
        return bc

    def _slot_for(idx):
        """symtab idx → 实际 gvar 槽（经 gvar_map）；查不到返回 None。"""
        if gvar_map and symtab is not None and 0 <= idx < len(symtab.entries):
            _t, _v = symtab.entries[idx]
            if _t in ("SYMBOL", "STRING"):
                return gvar_map.get(str(_v).upper())
            if _t == "REAL" and real_map is not None:
                # 实数常量：按值匹配资源段 REAL 槽（fg，与函数体 real_map 同基准）；
                # key 用 _real_fmt 规范化（资源流存 15 位，symtab 为完整 float）。
                return real_map.get(_real_fmt(float(_v)))
        return None

    out = bytearray()
    for inst in insts:
        name = inst.op_name
        raw = bc[inst.offset : inst.offset + inst.size]
        if name == "USUBR" and len(inst.operands) >= 2:
            slot = _slot_for(inst.operands[1])
            if slot is not None:
                out += _subr_bytes(0x35, inst.operands[0], slot, flags=3, wide=wide)
            else:
                out += _subr_bytes(0x35, inst.operands[0], inst.operands[1] + 1 + n_cmds, flags=3, wide=wide)
        elif name == "FUNC" and len(inst.operands) >= 2:
            slot = _slot_for(inst.operands[1])
            if slot is not None:
                out += _subr_bytes(0x51, inst.operands[0], slot, flags=1, wide=wide)
            else:
                out += _subr_bytes(0x51, inst.operands[0], inst.operands[1] + 1 + n_cmds, flags=1, wide=wide)
        elif name in ("PUSH_G", "SETQ_G", "PUSH_G_ALT") and len(inst.operands) >= 1:
            slot = _slot_for(inst.operands[0])
            if slot is not None:
                out += bytes([raw[0]]) + struct.pack("<H", slot)
            else:
                out += bytes([raw[0]]) + struct.pack("<H", inst.operands[0] + 1 + n_cmds)
        elif name == "PUSH_VALUE":
            # stub：PUSH_VALUE[0] 单字节 03；idx>0 为 3 字节。
            if len(inst.operands) == 1 and inst.operands[0] == 0 and inst.size == 1:
                out += raw  # 单字节 PUSH_VALUE[0]（调用后清理），不偏移
            elif len(inst.operands) == 1:
                slot = _slot_for(inst.operands[0])
                if slot is not None:
                    out += bytes([raw[0]]) + struct.pack("<H", slot)
                else:
                    out += bytes([raw[0]]) + struct.pack("<H", inst.operands[0] + 1 + n_cmds)
            else:
                out += raw
        else:
            out += raw
    return bytes(out)


def _collect_symbol_nodes(node):
    """递归收集 AST 节点中的 Symbol/String 节点。"""
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
        InPackage,
        Defpackage,
    )

    if isinstance(node, Symbol) or isinstance(node, String):
        yield node
    elif isinstance(node, Defpackage):
        # `(defpackage :C (:use :cl) (:export ...))` → 符号 `defpackage`、
        # `:use`、`:export`、包名、use 包、export 符号（CAD 模块代码引用，
        # 与 _register_module 的模块注册顺序一致）。
        yield Symbol("defpackage")
        yield Symbol(":use")
        yield Symbol(":export")
        yield Symbol(node.name)
        for _u in node.use:
            yield Symbol(_u)
        for _e in node.export:
            yield Symbol(_e)
    elif isinstance(node, InPackage):
        # `(in-package :@)` → 符号 `in-package` + 包名 `:@`（CAD 模块代码引用）。
        yield Symbol("in-package")
        yield Symbol(node.name)
    elif isinstance(node, Call):
        yield Symbol(node.name)
        for a in node.args:
            yield from _collect_symbol_nodes(a)
    elif isinstance(node, Setq):
        for t, v in node.pairs:
            if t is not None:
                yield from _collect_symbol_nodes(t)
            if v is not None:
                yield from _collect_symbol_nodes(v)
    elif isinstance(node, IfNode):
        for sub in (node.cond, node.then, node.else_expr):
            if sub is not None:
                yield from _collect_symbol_nodes(sub)
    elif isinstance(node, WhileNode):
        if node.cond:
            yield from _collect_symbol_nodes(node.cond)
        for e in node.body:
            yield from _collect_symbol_nodes(e)
    elif isinstance(node, Progn):
        for e in node.forms:
            yield from _collect_symbol_nodes(e)
    elif isinstance(node, Cond):
        for clause in node.clauses:
            if isinstance(clause, (list, tuple)):
                for c in clause:
                    yield from _collect_symbol_nodes(c)
            else:
                yield from _collect_symbol_nodes(clause)
    elif isinstance(node, ListExpr):
        for item in node.items:
            yield from _collect_symbol_nodes(item)
        if node.dotted is not None:
            yield from _collect_symbol_nodes(node.dotted)
    elif isinstance(node, ForeachNode):
        if node.var:
            yield from _collect_symbol_nodes(node.var)
        if node.list_expr:
            yield from _collect_symbol_nodes(node.list_expr)
        for e in node.body:
            yield from _collect_symbol_nodes(e)
    elif isinstance(node, RepeatNode):
        if node.count:
            yield from _collect_symbol_nodes(node.count)
        for e in node.body:
            yield from _collect_symbol_nodes(e)
    elif isinstance(node, QuotedExpr):
        if node.kwote and isinstance(node.expr, LambdaNode):
            # `(function (lambda ...))`（顶层 setq-lambda 的 kwote 改写）：
            # lambda 体符号不属于**顶层符号**（CAD 把它们放 `-lambda-` 区，
            # 不在模块注册段）。跳过体符号，只保留 lambda 参数名（参数仍需
            # 注册）。否则 top_level_count / max(_top_slots) 被体符号膨胀，
            # `-lambda-` 槽位偏移。
            for a in _lambda_real_args(node.expr):
                yield Symbol(a)
        else:
            yield from _collect_symbol_nodes(node.expr)
    elif isinstance(node, LambdaNode):
        for a in node.args:
            yield Symbol(a)
        for e in node.body:
            yield from _collect_symbol_nodes(e)


def _lambda_real_args(lam):
    """lambda 真参数：剔除 `/ 局部变量` 分隔符及局部变量（与 defun 同协议）。"""
    args = list(lam.args)
    if "/" in args:
        args = args[: args.index("/")]
    return args


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


def cmd_compile(
    source: str,
    output: str = "",
    opt_level: int = 0,
    show_analysis: bool = False,
    encoding: str = "ansi",
    report_json: str = "",
    verify: bool = True,
) -> str:
    if os.path.exists(source):
        from core.fas_core import decode_source_text
        with open(source, "rb") as f:
            source_code = decode_source_text(f.read())
    else:
        source_code = source
    parser_obj = Parser(source_code)
    try:
        program = parser_obj.parse()
    except ParseError as e:
        print(f"Parse error: {e}", file=sys.stderr)
        sys.exit(1)

    # 顶层 `(progn ...)`（@lisp 包整体包裹模式）展开后再提取 defun/顶层表达式
    program.forms = _flatten_top_level_forms(program.forms)
    # 条件/嵌套 defun（`(if c (defun f () ...))`）：先按 CAD 方式把顶层 if 内的
    # defun 提升为独立函数（无条件编译，if 只保留非 defun 表达式），剩余的非顶层
    # 嵌套 defun（defun 体内）再由 _lower_nested_defuns 改写为 setq lambda。
    program.forms = _hoist_conditional_defuns(program.forms)
    # 嵌套 defun（`(defun f () (defun g () ...))`）改写为 `(setq g '(lambda ...))`
    program.forms = _lower_nested_defuns(program.forms)
    # 顶层 `(setq X (lambda ...))`：CAD 编译为可调用 SUBR。
    # - 纯顶层文件（无 defun）：走 CAD `-lambda-` 机制（seg0 紧凑 stub +
    #   DEFCODE 注册 + 模块代码 ``PUSH_G <sym>; PUSH_G <-lambda-槽>;
    #   FUNC_REF set``）。
    # - 混合文件（含 defun）：提升为同名 defun（@lisp_u 实测 CAD `@::fasext`/
    #   `@::vlx`/`@::acadver` 为可调用 SUBR，`(type @::fasext)` → SUBR）。
    #   此前改写成 kwote 但混合文件无 seg0 `-lambda-` 生成/DEFCODE 注册，
    #   模块代码 `FUNC kwote` 无定义 → CAD 加载报 `函数错误: (LAMBDA ...)`
    #   /访问冲突，见 KNOWN_ISSUES。
    _defuns_now = [f for f in program.forms if isinstance(f, Defun)]
    top_lambda_binds = _collect_top_lambda_binds(program.forms)
    # 记录顶层 `(set/setq 'sym (lambda ...))` 的目标符号名（混合文件转为 defun
    # 后用于 func_offsets 以 `-lambda-` 键登记，CAD DEFCODE 尾注册为 `-lambda-`）。
    _top_lambda_names = {s for s, _ in top_lambda_binds}
    if top_lambda_binds:
        program.forms = _rewrite_top_lambda_binds(program.forms)
        if _defuns_now:
            program.forms = _insert_top_lambda_defuns(program.forms, top_lambda_binds)
    # 多 `(function (lambda ...))`（>1）走 CAD kwote 原生路径：每个 kwote 编译为
    # 独立 `-lambda-` 内嵌 DEFUN（`-lambda-#N` 目录键 + DEFCODE 注册，见
    # codegen._emit_nested_lambda / resource_builder）。`_lower_multi_kwote` 仅作为
    # 后备保留（单 kwote 文件不受影响，多 kwote 走原生）。
    # program.forms = _lower_multi_kwote(program.forms)
    # `(let ...)` 先降级为 lambda-apply。`((lambda ...) args)` 立即调用保留
    # ListExpr（head=LambdaNode），codegen 走 CAD「内嵌 -lambda- DEFUN + EVAL」
    # 模式（dcl/permission/audit/user-manager/config-sync/file 实测 `EVAL argc, 7`）。
    program.forms = _lower_let(program.forms)

    package_table = parser_obj.packages

    need_stats = show_analysis or bool(report_json)
    stats: Optional[dict] = None
    stats2: Optional[dict] = None

    if need_stats:
        stats = analyze(program)
        if show_analysis:
            print("=== Compilation Analysis ===")
            print(f'  Functions:               {stats["functions"]}')
            print(f'  Top-level forms:         {stats["top_level_forms"]}')
            print(f'  Total instructions:      {stats["total_instructions"]}')
            print(f'  Constants (estimate):    {stats["constants_estimate"]}')
            print(f'  Symbol table entries:    {stats["symbol_table_entries"]}')
            print(f'  Function offsets:        {stats["function_offsets"]}')
            print(f'  Locals (total):          {stats["locals"]}')
            print(f'  Tail-recursive:          {stats["tail_recursive_functions"]}')
            print(f'  External/builtin calls:  {len(stats["builtin_calls"])}')
            for fd in stats["functions_detail"]:
                tr = " [tail-recursive]" if fd["tail_recursive"] else ""
            print(
                f'    {fd["name"]}: {fd["instructions"]} instr, '
                f'{fd["args"]} args, {fd["locals"]} locals, '
                f'calls {fd["calls"]}{tr}'
            )
            print()

    if opt_level:
        program = optimize(program, level=opt_level)
        if need_stats:
            assert stats is not None
            stats2 = analyze(program)
            assert stats2 is not None
            if show_analysis:
                print(f"=== After O{opt_level} Optimization ===")
                print(f'  Functions:          {stats2["functions"]} (was {stats["functions"]})')
                print(f'  Instructions:       {stats2["total_instructions"]} (was {stats["total_instructions"]})')
                print(f'  Tail-recursive:     {stats2["tail_recursive_functions"]}')
                print()

    symtab = SymbolTable(package_table=package_table)
    defun_forms = [f for f in program.forms if isinstance(f, Defun)]
    # 纯 &rest（min=0）：CAD 实测不收集 rest（b4=01 需至少一个必填参数）
    for _defun in defun_forms:
        if _defun.rest and not _defun.args and not _defun.optional:
            print(
                f"Warning: function '{_defun.name}' uses bare &rest (min args = 0); "
                f"CAD does not collect rest args for min=0 — consider adding "
                f"a required param, e.g. (defun {_defun.name} (x &rest {_defun.rest}))",
                file=sys.stderr,
            )
    from compiler.cad_symbols import derive_symbol_names, is_const_entry

    for sym in derive_symbol_names(program):
        if top_lambda_binds and sym == "kwote":
            # 纯顶层含顶层 `(set/setq 'sym (lambda ...))`（CAD `-lambda-` 机制）：
            # 收集器对 kwote 标记误收 `kwote` 符号（CAD 无此槽，顶层 lambda
            # 不经 kwote 调用）。跳过；`-lambda-` 由 seg0 阶段经 top_lambda_slots
            # 注册，不进 symtab。
            continue
        if is_const_entry(sym):
            symtab.add_constant(sym[1])
        elif isinstance(sym, str) and sym.startswith('__real_') and sym.endswith('__'):
            symtab.add_real(float(sym[len('__real_'):-len('__')]))
        elif sym.startswith('"') and sym.endswith('"'):
            _sv = sym[1:-1]
            if f"__str_{_sv}__" in symtab.name_to_idx:
                # CAD 字符串跨区重复注册：模块区与函数体区各自独立 gvar 槽
                # （platform.lsp `(setq @::*locale* "chs")` 的 "chs" 在模块
                # cond 与函数体各注册一次，fg 表两处都有）。首次 add_string
                # 登记 name_to_idx，二次（重复）直接追加重复 STRING 槽。
                symtab.add_string(_sv, force=True)
            else:
                symtab.add_string(_sv)
        elif sym in symtab.name_to_idx:
            # CAD stub：允许符号重复（递归/跨函数引用产生重复槽）
            symtab.add_force(sym)
        else:
            symtab.get_or_add(sym)

    # 顶层表达式符号（defun 之外）：CAD 把它们的符号并入模块注册段。
    # InPackage/Defpackage 也编译进模块代码（InPackage `PUSH_VALUE :@; FUNC_REF
    # in-package`，Defpackage `PUSH_VALUE :C; (:use ...); (:export ...);
    # USUBR 3, DEFPACKAGE`，CAD 实测），故保留在 other_forms 中。
    other_forms = [f for f in program.forms if not isinstance(f, Defun)]
    # 顶层 form 数（CAD seg1 头 items 公式用），区别于符号数 top_level_count。
    top_form_count = len(other_forms)
    from compiler.ast_nodes import Symbol as _Sym
    from compiler.ast_nodes import String as _StrNode

    _top_syms = []
    for form in other_forms:
        for _n in _collect_symbol_nodes(form):
            if isinstance(_n, _Sym) and _n.name not in _top_syms:
                _top_syms.append(_n.name)
            elif isinstance(_n, _StrNode) and _n.value not in _top_syms:
                _top_syms.append(_n.value)
    # 顶层符号在 entries 中的槽索引（字符串 key 特殊）
    _top_slots = []
    for s in _top_syms:
        if s in symtab.name_to_idx:
            _top_slots.append(symtab.name_to_idx[s])
        elif f"__str_{s}__" in symtab.name_to_idx:
            _top_slots.append(symtab.name_to_idx[f"__str_{s}__"])
    # CAD 模块注册区宽 = 函数名数 + 顶层表达式符号数。由收集器 _register_module
    # 实际注册数推导（module_reg_count = n_funcs + top_level_count）。
    # 不能用 `max(顶层符号槽)+1-n_funcs`：顶层表达式若引用**函数体**符号
    # （高槽位）会严重高估（atlisp_u 实测 3036 vs 实际 342），导致模块代码
    # 函数注册 `PUSH_G b` 槽超出 gvar 表、CAD 不执行模块代码。
    from compiler.cad_symbols import module_reg_count as _mrc
    from compiler.cad_symbols import module_reg_func_count as _mrfc

    if defun_forms:
        # 模块注册区 = n_funcs + top_level_count。由收集器 _register_module
        # 实际注册数推导。不能用 `max(顶层符号槽)+1-n_funcs`：顶层表达式若
        # 引用**函数体**符号（高槽位）会严重高估（atlisp_u 实测 3036 vs
        # 实际 342），导致模块代码函数注册 `PUSH_G b` 槽超出 gvar 表、
        # CAD 不执行模块代码。
        top_level_count = max(0, _mrc(program) - len(defun_forms))
    else:
        # 纯顶层文件：无函数体符号污染，`max(顶层槽)+1` 与 golden 一致
        # （setqa/setcmp/p01 实测）。含顶层 `(set/setq 'sym (lambda ...))`
        # 的文件（setq-lambda.lsp）用模块注册段符号数（`_mrc`）——`max(_top_slots)`
        # 会被 `-lambda-` 第二区体符号膨胀，`-lambda-` 槽位偏移。CAD 的
        # `-lambda-` 槽 = 模块注册段符号数 + 3（fasext）、+2（vlx）。
        if top_lambda_binds:
            top_level_count = max(0, _mrc(program))
        elif _top_slots:
            top_level_count = max(_top_slots) + 1
        else:
            top_level_count = 0

    codegen_nsyms = len(symtab.entries) - len(defun_forms) - top_level_count + 1
    codegen = CodeGenerator(symtab, stub_format=True, defined_funcs=[f.name for f in defun_forms], nsyms=codegen_nsyms)

    func_offsets = {}

    # CAD：顶层表达式（defun 之外的 setq/set 等）编译进 seg1 模块代码，
    # seg0 只含 defun 函数。
    #
    # CAD 模块代码规则（逆向）：
    #   - 模块代码引用 gvar 槽（= 符号槽 + 1）
    #   - 顶层 setq → `PUSH_G <值槽+1>; DUP; SETQ_G <变量槽+1>; POP(非最后)`
    #   - 顶部 `PUSH_G <符号总数+1>; POP` 占位
    #   - 无 defun 时无函数注册尾，以 END_DEFUN 结束
    top_level_bc = BytecodeBuffer()
    codegen._module_mode = True
    codegen._module_code_ctx = True
    for form in other_forms:
        if isinstance(form, (InPackage, Defpackage)):
            # `(in-package :@)`/`(defpackage ...)` 由 _build_cad_module_code 单独
            # 发射（in-package `PUSH_VALUE :@; FUNC_REF in-package`、defpackage
            # `PUSH_VALUE :C; (:use ...); (:export ...); USUBR 3, DEFPACKAGE`），
            # 此处跳过占位生成。
            continue
        # 顶层 `(set/setq 'sym (lambda ...))`（纯顶层文件）：由
        # _build_cad_module_code 按 top_lambda_slots 特判发射 `-lambda-` 绑定，
        # 这里跳过（避免 codegen _emit_kwote 注册多余 `-LAMBDA-` 槽）。
        if top_lambda_binds:
            from compiler.ast_nodes import LambdaNode as _LN

            _is_tl = False
            _tl_names = {s for s, _ in top_lambda_binds}
            if isinstance(form, Call) and form.name == "set" and len(form.args) == 2:
                _t0 = form.args[0]
                _v1 = form.args[1]
                _is_tl = (
                    isinstance(_t0, QuotedExpr) and isinstance(_t0.expr, Symbol)
                    and _t0.expr.name in _tl_names
                    and (isinstance(_v1, _LN) or (isinstance(_v1, QuotedExpr) and isinstance(_v1.expr, _LN)))
                )
            elif isinstance(form, Setq):
                for _t, _v in form.pairs:
                    if isinstance(_t, Symbol) and _t.name in _tl_names and (
                        isinstance(_v, _LN) or (isinstance(_v, QuotedExpr) and isinstance(_v.expr, _LN))
                    ):
                        _is_tl = True
                        break
            if _is_tl:
                continue
        codegen._emit_expr(top_level_bc, form)
        if isinstance(form, Setq):
            top_level_bc.emit(ENCODE_POP)
    codegen._module_mode = False
    top_level_bc.resolve()
    top_level_code = bytes(top_level_bc.data)

    all_bytecode = BytecodeBuffer()
    _top_lam_count = 0
    _top_lambda_key_names: dict = {}
    _top_lambda_offsets: dict = {}
    for i, form in enumerate(defun_forms):
        offset = len(all_bytecode.data)
        func_bytecode, _ = codegen.generate_function(form)
        from compiler.cad_symbols import normalize_vla_name

        if form.name in _top_lambda_names:
            # 混合文件顶层 setq-lambda（已提升为 defun）：CAD 在 DEFCODE 尾
            # 注册为 `-lambda-`（platform.lsp 实测两处 `-lambda-`，offset 大的
            # 先 DEFCODE）。func_offsets 键用 `-lambda-`，使 resource_builder
            # 按 `-lambda-` 编码 DEFCODE（`_is_lambda_key`）。顺序按 seg0 offset
            # 自然排序（源码序 = 定义序），与 CAD 逆序 DEFCODE 一致。
            _lkey = f"-lambda-{'' if _top_lam_count == 0 else '#' + str(_top_lam_count + 1)}"
            func_offsets[_lkey] = offset
            _top_lambda_key_names[_lkey] = form.name
            _top_lambda_offsets[offset] = form.name
            _top_lam_count += 1
        else:
            func_offsets[normalize_vla_name(form.name)] = offset
        all_bytecode.emit(func_bytecode)
        if i < len(defun_forms) - 1:
            # CAD stub: 函数间分隔符 `16`（CLEAR_ARGS `19 <argc> 00` 已由
            # generate_function 生成，仅需追加 END_DEFUN 分隔）。
            all_bytecode.emit(bytes([0x16]))

    # 顶层 `(set/setq 'sym (lambda ...))`（纯顶层文件）：CAD 把内嵌
    # `-lambda-` DEFUN 放 seg0（完整紧凑 stub：`14 <argc><argc><argc> 00` +
    # GET_LOCAL + INIT_ARGS + 体 + CLEAR_ARGS + END_DEFUN，函数间 `16` 分隔），
    # 由 DEFCODE 注册为可调用 SUBR。模块代码用 setq 协议绑定
    # `JUMP 0; PUSH_G <-lambda-槽>; DUP; SETQ_G <sym>`。这里生成 stub 进
    # seg0，登记 `-lambda-` 槽供模块代码引用；有 defun 的混合文件（platform）
    # CAD 用引用数据。
    top_lambda_slots: dict = {}
    if top_lambda_binds and not defun_forms:
        for _ti, (_sym, _lam) in enumerate(top_lambda_binds):
            # 纯顶层 `-lambda-` 是完整 compact stub 函数（CAD 实测 seg0：
            # `14 <argc><argc><argc> 00` + GET_LOCAL_WIDE + INIT_ARGS + 体 +
            # CLEAR_ARGS + END_DEFUN，与普通 defun 一致），由 DEFCODE 注册为
            # 可调用 SUBR。复用 generate_function 生成（_defun_from_lambda 把
            # LambdaNode 转 Defun），避免手动拼 stub 缺 GET_LOCAL/INIT_ARGS/
            # CLEAR_ARGS/END。
            _fdef = _defun_from_lambda(_sym, _lam)
            _fb, _ = codegen.generate_function(_fdef)
            _off = len(all_bytecode.data)
            _key = f"-lambda-#{_ti + 1}" if _ti else "-lambda-"
            func_offsets[_key] = _off
            all_bytecode.emit(_fb)
            # CAD 纯顶层 `-lambda-` 函数间以 END_DEFUN(`16`) 分隔（同 defun，
            # setq-lambda.lsp CAD golden 实测第一个 `-lambda-` 后 `16`）；最后
            # 一个 `-lambda-` 无 END（以 CLEAR_ARGS 结束）。
            if _ti < len(top_lambda_binds) - 1:
                all_bytecode.emit(bytes([0x16]))
            # `-lambda-` 槽 = 顶层符号数 + 2（setq-lambda.lsp golden 实测：
            # 模块代码 `PUSH_G 29`（@::fasext）、`PUSH_G 28`（@::vlx）——gvar 槽 =
            # 符号槽 + 1，符号槽 = top_level_count + 2 - _ti。CAD 的 GVARINIT
            # (top_level_count+2, N) 注册这些超表运行时槽。不能用全部
            # symtab.entries（第二区 `-lambda-` 体符号会膨胀）。多 lambda 逆序
            # 递减。不进 symtab（CAD 无 `-lambda-` 普通符号槽，仅 DEFCODE
            # 区小写注册）。
            _lam_slot = top_level_count + 2 - _ti
            top_lambda_slots[_sym] = _lam_slot
    # 混合文件（platform）：`-lambda-` 运行时槽 = `_reg` 的 b 槽 - 1（模块代码
    # setq-lambda 绑定 `PUSH_G <-lambda->` 复用该函数的 `_reg` b 槽：b =
    # 2*n_funcs+1 + top_level_count - i，`_lam_slot = b - 1`。platform 实测
    # @::fasext i=2 → PUSH_G 69、@::vlx i=3 → PUSH_G 68）。
    elif top_lambda_binds and defun_forms:
        _tl_names_set = set(s for s, _ in top_lambda_binds)
        _tl_index = {
            f.name: idx
            for idx, f in enumerate(defun_forms)
            if f.name in _tl_names_set
        }
        for _sym, _lam in top_lambda_binds:
            _i = _tl_index.get(_sym)
            if _i is None:
                continue
            _lam_slot = 2 * len(defun_forms) + top_level_count - _i
            top_lambda_slots[_sym] = _lam_slot

    # 内嵌 `(function (lambda ...))` / `((lambda ...) args)` DEFUN（kwote/
    # 立即应用机制）：偏移相对所在函数字节码缓冲，需转换为 seg0 绝对偏移。
    # 每个内嵌 DEFUN 用独立 `-lambda-` 目录键（`-lambda-`、`-lambda-#2`、…，
    # CAD 实测每个嵌套 lambda 独立槽 + DEFCODE，逆序弹出分配末尾槽）。
    # 这些键仅用于函数目录（func-ranges）与 DEFCODE 注册，不参与模块注册。
    nested_ends = {}
    nested_list = []
    for name, off in list(func_offsets.items()):
        for rel_start, rel_end in codegen._func_nested_lambdas.get(name, []):
            n_start = off + rel_start
            n_end = off + rel_end
            nested_list.append((n_start, n_end))
    for i, (n_start, n_end) in enumerate(nested_list):
        func_offsets[f"-lambda-#{i + 1}" if i else "-lambda-"] = n_start
        nested_ends[n_start] = n_end

    for name, offset in func_offsets.items():
        # `-lambda-`/`-lambda-#N`（内嵌 DEFUN）不进符号表（仅 DEFCODE 区注册，
        # 顶层 lambda 的 `-lambda-` 槽由 top_lambda_slots 计算）。其余函数名
        # 注册符号槽。
        if isinstance(name, str) and (name == "-lambda-" or name.startswith("-lambda-#")):
            continue
        from compiler.cad_symbols import normalize_vla_name

        symtab.add_func_ref(normalize_vla_name(name), offset)

    all_bytecode.resolve()
    seg0 = bytes(all_bytecode.data)

    # 模块代码：含顶层表达式时用 CAD 风格完整模块代码；否则固定函数注册尾。
    # c: 命令函数：CAD 在模块注册段插入 vl-ACAD-defun 符号并生成命令模块代码。
    # vl-ACAD-defun 仅在模块注册段（resource_gvars）注册，不进符号表（不参与
    # 函数符号槽编址），故 seg0 的 PUSH_VALUE 索引保持不变。
    n_cmds = 1 if any(getattr(f, "is_command", False) or str(f.name).startswith("c:") for f in defun_forms) else 0
    resource = ResourceBuilder(symtab, encoding=encoding)
    # 模块注册函数数 = 模块尾块 defun 数（CAD 只把模块代码引用的尾块函数名
    # 注册进模块注册段；atlisp_u 48，其余 416 个库函数名经函数体符号区注册）。
    _mr_func_count = _mrfc(program)
    module_reg_count = len(defun_forms) + top_level_count
    # 纯顶层含顶层 `(set/setq 'sym (lambda ...))` 时，收集第二区符号
    # （lambda 体符号 + 参数，CAD DEFCODE 区前置注册，fg 表用）。顺序：源码
    # 逆序（@::vlx 在前、@::fasext 在后），各 lambda 体符号 + 参数。与
    # cad_symbols 的 3b 块收集顺序一致。
    _top_lambda_body_syms = None
    if top_lambda_binds:
        from compiler.cad_symbols import CadSymbolCollector, _SeenList

        _syms = []
        _lam_seen = set()  # 跨 lambda 去重（strcat 出现在两个 lambda 体只注册一次）
        for _sym, _lam in reversed(top_lambda_binds):
            from compiler.ast_nodes import Call as _TLCall

            _lam_col = _SeenList()
            for _be in _lam.body:
                CadSymbolCollector()._collect_byteorder(_be, _lam_col, set())
            _fwd = [n for n, _ in _lam_col if n != "__kwote_end__" and n != "kwote"]
            # 最后调用名 = 最后一个 body form 的值（setq 值/末表达式函数名）。
            # setq-lambda vlx/fasext 尾 form 得 strcat；net/wget 尾 form
            # `outfile`（Symbol）→ 无尾调用（null 是中间 if 条件，不剔除）。
            _tc = CadSymbolCollector()._lam_tail_value(_lam.body[-1] if _lam.body else None)
            if _tc is not None:
                _fwd = [n for n in _fwd if n != _tc]
            # 真参数 = `/` 之前；`/` 后的局部变量照常注册为体符号。
            _lam_params = _lam.args
            if "/" in _lam_params:
                _lam_params = _lam_params[:_lam_params.index("/")]
            for _n in reversed(_fwd):
                if isinstance(_n, str) and _n in _lam_params:
                    continue
                if isinstance(_n, str) and _n in _lam_seen:
                    continue
                _lam_seen.add(_n)
                _syms.append(_n)
            # `/ 局部变量`：注入 `_al-bind-alist` 助手 + locals 常量
            # （net/wget CAD 实测 `_al-bind-alist` 在 body 后、参数前）。
            _lam_locals = []
            if "/" in _lam.args:
                _lam_locals = _lam.args[_lam.args.index("/") + 1 :]
            if _lam_locals:
                if "_al-bind-alist" not in _lam_seen:
                    _lam_seen.add("_al-bind-alist")
                    _syms.append("_al-bind-alist")
                _lc = tuple(("SYMBOL", l) for l in _lam_locals)
                if _lc not in _lam_seen:
                    _lam_seen.add(_lc)
                    _syms.append(("__const__", ("LIST", _lc)))
            for _a in reversed(_lam_params):
                if _a not in _lam_seen:
                    _lam_seen.add(_a)
                    _syms.append(_a)
            if _tc is not None and _tc not in _lam_seen:
                _lam_seen.add(_tc)
                _syms.append(_tc)
        _top_lambda_body_syms = _syms
    fas_nsyms = len(symtab.entries) - module_reg_count + 1
    # 纯顶层文件含顶层 `-lambda-`：CAD nsyms = fg 表长度 = 1 + 第二区符号数
    # （setq-lambda.lsp golden nsyms=12 = 1 + 11 个体符号/参数；bootstrap 单
    # lambda 时 = 1 + 1 = 2）。不能再用 `1 + len(top_lambda_binds)`（=3），
    # 否则参数绑定 PUSH_G 的 `gvar_slot(arg)-1` 越界错槽。
    if top_lambda_binds and not defun_forms and _top_lambda_body_syms:
        fas_nsyms = 1 + len(_top_lambda_body_syms)
    _pre_nsyms = fas_nsyms
    if other_forms:
        # 顶层语句在源码中位于最后一个 defun 之后（如 `(set '_ @::_)`、
        # p04 的 `(setq *codepage* ...)` 与 `(if ...)`）时，排到函数注册尾
        # 之后（mix2 实测：`(setq x 10)` 在 defun b 后）。可能多个 post-form。
        from compiler.ast_nodes import Defun as _Defun
        from compiler.ast_nodes import Defpackage as _Defpackage
        from compiler.ast_nodes import InPackage as _InPackage
        from compiler.ast_nodes import Call as _Call

        _last_overall = program.forms[-1] if program.forms else None
        _top_after_defun = _last_overall is not None and not isinstance(
            _last_overall, (_Defun, _Defpackage, _InPackage)
        )
        _last_defun_pos = -1
        _first_defun_pos = -1
        for _i, _f in enumerate(program.forms):
            if isinstance(_f, _Defun):
                if _first_defun_pos < 0:
                    _first_defun_pos = _i
                _last_defun_pos = _i
        # 首个 defun 之前的顶层语句数（模块全局初始化，CAD 在其后立即注册
        # 第一个函数，i18n/p04 实测）。InPackage/Defpackage 均已并入
        # other_forms（模块代码发射调用），计入 globals 组，使其排在函数注册
        # JUMP 之前（CAD base-function/platform-api/command 实测 use-package/
        # in-package/defpackage 均在函数注册前）。
        _n_globals = (
            sum(1 for _f in program.forms[:_first_defun_pos] if not isinstance(_f, _Defun))
            if _first_defun_pos >= 0
            else len(other_forms)
        )
        # 统计最后一个 defun 之后、且非 defun/defpackage 的顶层 form 数。
        # other_forms 与 program.forms 同序（仅过滤 defun/defpackage），
        # 故末尾 n 个 other_forms 即为 post-form。
        _n_post_forms = (
            sum(
                1
                for _f in program.forms[_last_defun_pos + 1 :]
                if not isinstance(_f, (_Defun, _Defpackage, _InPackage))
            )
            if _last_defun_pos >= 0
            else 0
        )
        # START `_reg` 函数数 = globals 之后、首个 mid 顶层语句之前的连续 defun
        # 数（CAD i18n 实测 @::codepage2lang 在 SETQ[0]（模块全局）后立即注册、
        # 在 SETQ[2]（mid 语句）之前；log.lsp 前导 in-package/use-package 跳过
        # 后 log-level/log-level-name 同样 START 注册）。globals（首个 defun
        # 之前的顶层 setq 等）**跳过不 break**——CAD 把 globals 后的函数注册放
        # 在 mid 语句之前。纯函数文件（command.lsp，无 mid 顶层语句）循环走完
        # 所有 defun 后 `_saw_top_stmt=False` → n_pre 归 0（全部 TAIL 注册）。
        _n_pre = 0
        _first_defun_seen = False
        _saw_top_stmt = False
        for _f in program.forms:
            if isinstance(_f, _Defun):
                _first_defun_seen = True
                _n_pre += 1
            elif isinstance(_f, (_Defpackage, _InPackage)) or (
                isinstance(_f, _Call)
                and str(_f.name).lower() in ("use-package", "defpackage")
            ):
                continue
            else:
                if _first_defun_seen:
                    _saw_top_stmt = True
                    break
                # globals（首个 defun 之前的顶层语句）：跳过，START 注册照常
                continue
        if not _first_defun_seen or not _saw_top_stmt:
            _n_pre = 0
        # 每个 defun 之后的 mid 顶层 form 数（仅统计最后一个 defun 之前）。
        # 交错（cl-functions 别名 set）时按此把 mid_forms 分配给对应函数。
        _mid_counts = []
        _cur_fn = None
        for _i, _f in enumerate(program.forms):
            if isinstance(_f, _Defun):
                _mid_counts.append(0)
                _cur_fn = len(_mid_counts) - 1
            elif _cur_fn is not None and not isinstance(_f, (_Defpackage, _InPackage)) and not (
                isinstance(_f, _Call) and str(_f.name).lower() in ("use-package", "defpackage")
            ):
                if _i < _last_defun_pos:
                    _mid_counts[_cur_fn] += 1
        module_code = _build_cad_module_code(
            top_level_code,
            symtab,
            other_forms,
            n_funcs=len(defun_forms),
            top_level_count=top_level_count,
            top_after_defun=_top_after_defun,
            func_names=[f.name for f in defun_forms],
            n_post_forms=_n_post_forms,
            n_globals=_n_globals,
            top_lambda_slots=top_lambda_slots,
            n_pre=_n_pre,
            skip_funcs=_top_lambda_names,
            n_cmds=n_cmds,
            mid_counts=tuple(_mid_counts),
        )
    elif n_cmds:
        # 纯命令文件（全部函数都是命令，无顶层表达式，t14_command）走
        # build_command_module_code（全命令 vl-ACAD-defun 注册）；混合命令文件
        # （config/migrate `C:@PROFILE` + 普通函数）仅命令函数用 vl-ACAD-defun
        # 注册，普通函数用 plain 模式。
        _fn_names = [f.name for f in defun_forms]
        if all(str(n).lower().startswith("c:") for n in _fn_names):
            module_code = build_command_module_code(len(defun_forms))
        else:
            _first_cmd_slot = None
            for _fn in _fn_names:
                if str(_fn).lower().startswith("c:"):
                    _first_cmd_slot = symtab.name_to_idx.get(_fn)
                    break
            # vl-ACAD-defun 的 rg 槽 = 源码首个命令 symtab 槽 + 1（vl 符号占用
            # 其后一槽；config/migrate C:@PROFILE symtab 3 → USUBR 操作数 4）。
            _vl_slot = (_first_cmd_slot + 1) if _first_cmd_slot is not None else 1
            module_code = build_mixed_command_module_code(
                len(defun_forms), vl_idx=_vl_slot, func_names=_fn_names,
                symtab=symtab, first_cmd_slot=_first_cmd_slot,
            )
    else:
        module_code = build_module_code(len(defun_forms), nsyms=_pre_nsyms)

    # 修正 USUBR/参数槽索引：CAD 用 `gvar 槽 - 1`（gvar 表由资源段 GVARINIT 建立）。
    def _all_params(f):
        return f.args + f.optional + ([f.rest] if f.rest else [])

    # func_args 顺序须与 seg0 DEFUN 顺序一致：顶层 defun 参数 + 各函数内嵌
    # kwote `-lambda-` 参数（紧随所在函数之后，i18n-cad 实测）。
    # 参数槽修正采用按名解析（params_by_name / lambda_args_by_func），
    # 不再依赖扁平列表顺序对齐（@lisp_u 大文件 iter 会错位）。
    all_func_args = []
    params_by_name: dict = {}
    lambda_args_by_func: dict = {}
    for _defun in defun_forms:
        _fn = normalize_vla_name(_defun.name)
        _pa = _all_params(_defun)
        all_func_args.append(_pa)
        params_by_name[_fn.upper()] = _pa
        _las = [list(la) for la in _collect_kwote_lambda_args(_defun)]
        lambda_args_by_func[_fn.upper()] = _las
        for la in _las:
            all_func_args.append(la)
    # 混合文件顶层 setq-lambda 以 `-lambda-` 键登记 func_offsets（DEFCODE 尾
    # 注册为 `-lambda-`）：参数修正按原函数名解析（params_by_name 用原名键）。
    for _lkey, _oname in _top_lambda_key_names.items():
        params_by_name[_lkey.upper()] = params_by_name.get(normalize_vla_name(_oname).upper())

    # 第一轮：先用未 patch 的 seg0 建 seg1 以获取 gvar 表。
    # commands 标志：纯命令文件（无顶层表达式，走 build_command_module_code）
    # 与 commands+顶层混合模式均需启用——混合文件 CAD 在模块注册段插入
    # `56 vl-ACAD-defun 00 00` 块（large_synthetic CAD 实测），且 GVARINIT
    # st_init 计入 `+commands`。
    _rb_commands = n_cmds
    seg1 = resource.build(
        func_offsets,
        module_code=module_code,
        total_size=len(seg0) + 1,
        stub_format=True,
        top_level_count=top_level_count,
        commands=_rb_commands,
        nested_ends=nested_ends,
        top_lambda_body_syms=_top_lambda_body_syms,
        module_func_count=_mr_func_count,
    )
    # commands + 顶层混合模式：模块注册把函数名逆序置前、顶层符号在后，
    # 模块代码符号引用（USUBR/PUSH_G）的 `symtab_idx+1` 不再等于实际 gvar 槽，
    # 顶层函数调用会引用错误槽位（atlisp_u 实测 @::poll-wxid 应为 114 而非
    # 248）。用第一轮 seg1 重建 gvar 表，重映射符号引用后二次生成模块代码。
    # 凡含顶层表达式（defun+顶层混合或纯顶层）均需重映射——symtab_idx+1 只在
    # 无顶层表达式时等于实际 gvar 槽（@lisp_u 无 c: 命令，n_cmds=0，此前被
    # `n_cmds and other_forms` 跳过导致 in-package/函数槽错位，2026-08-14）。
    if other_forms:
        # 模块代码符号引用须用资源 gvar 表（table0/rg）的索引——CAD 实测
        # 模块代码 `USUBR(0, 1036)` → rg[1036]=VL-LOAD-COM，操作数 = rg 索引。
        # build_module_gvar_map 的"模块注册段记录序"与此不一致（@lisp_u 实测
        # VL-LOAD-COM 模块注册位 1450 vs rg[1029]），会导致模块代码调用错槽 →
        # CAD 加载报"参数太少"。函数体用 fg（table1），模块代码用 rg（table0），
        # 两表独立（2026-08-14 对拍确认）。
        gvar_map = None
        real_map = None
        try:
            from core.fas_core import build_mvar_tables as _bmt

            _rg, _fg = _bmt(seg1, fas_nsyms)
            gvar_map = {}
            # 先按 symtab 序建立自然映射：模块符号的 gvar 槽 =
            # symtab_idx + 1 + n_cmds（模块注册顺序 = symtab 顺序时）。仅当
            # rg 槽确实持有该符号时采用——重复符号（cl-functions `=` 三槽
            # @[50,51,52]，模块代码引用 52 = symtab idx 51 + 1）若取首槽 50，
            # `_offset_slots` 会把正确的 PV52 重映射成 PV50（pass1 模块代码
            # 与 CAD 逐字节一致，gvar_map 首槽破坏之）。
            for _i in range(len(symtab.entries)):
                _t, _v = symtab.entries[_i]
                if _t not in ("SYMBOL", "STRING"):
                    continue
                _rk = str(_v).upper() if _t == "SYMBOL" else str(_v)
                _natural = _i + 1 + n_cmds
                if 0 <= _natural < len(_rg):
                    _rv = _rg[_natural]
                    if isinstance(_rv, tuple) and len(_rv) == 2 and _rv[0] in ("SYMBOL", "STRING"):
                        _rv_key = str(_rv[1]).upper() if _rv[0] == "SYMBOL" else str(_rv[1])
                        if _rv_key == _rk:
                            gvar_map[_rk] = _natural
            # 补充：模块注册顺序不一致（atlisp_u 函数名逆序）时按 rg 表修正。
            for _idx, _v in enumerate(_rg):
                if isinstance(_v, tuple) and len(_v) == 2 and _v[0] in ("SYMBOL", "STRING"):
                    _key = str(_v[1]).upper() if _v[0] == "SYMBOL" else str(_v[1])
                    if _v[0] == "SYMBOL":
                        _prev = gvar_map.get(_key)
                        if _prev is None or not (
                            isinstance(_prev, int) and 0 <= _prev < len(_rg)
                            and isinstance(_rg[_prev], tuple) and _rg[_prev][0] == "SYMBOL"
                        ):
                            gvar_map[_key] = _idx
                    else:
                        gvar_map.setdefault(_key, _idx)
            # 实数常量：模块代码顶层 setq 的 REAL 值按值匹配 fg 槽
            # （与函数体 real_map 同基准；@lisp_u 顶层 `(setq @::*seconds-per-day*
            # 86400.0)` 实测 fg[2604]，此前 fallback symtab_idx+1 越界 → CAD
            # segfault 0xC0000005）。注意：fg 槽是函数 gvar 表索引，模块代码
            # PUSH_G 是否可用需对拍——若 runtime 只用 table0，则此表仅供参考。
            real_map = {}
            for _idx, _v in enumerate(_fg):
                if isinstance(_v, tuple) and len(_v) == 2 and _v[0] == "REAL":
                    real_map.setdefault(_real_fmt(float(_v[1])), _idx)
            if not gvar_map:
                gvar_map = None
        except Exception:
            gvar_map = None
        if gvar_map:
            # rg 未覆盖的符号（常量、函数体符号等）按 symtab_idx+1 编址回退。
            module_code = _build_cad_module_code(
                top_level_code,
                symtab,
                other_forms,
                n_funcs=len(defun_forms),
                top_level_count=top_level_count,
                top_after_defun=_top_after_defun,
                func_names=[f.name for f in defun_forms],
                n_post_forms=_n_post_forms,
                n_globals=_n_globals,
                gvar_map=gvar_map,
                top_lambda_slots=top_lambda_slots,
                real_map=real_map,
                n_pre=_n_pre,
                skip_funcs=_top_lambda_names,
                n_cmds=n_cmds,
                mid_counts=tuple(_mid_counts),
            )
    seg0 = _patch_usubr_idx(seg0, seg1, symtab, fas_nsyms, all_func_args,
                            codegen_nsyms=codegen_nsyms,
                            params_by_name=params_by_name,
                            lambda_args_by_func=lambda_args_by_func,
                            has_top_forms=bool(other_forms),
                            n_real_funcs=len(defun_forms),
                            top_lambda_args=[_lambda_real_args(la) for _, la in top_lambda_binds]
                            if top_lambda_binds and not defun_forms else None,
                            top_lambda_offsets=_top_lambda_offsets,
                            module_reg_count=module_reg_count)
    # 第二轮：用 patch 后的 seg0 重建 seg1（代码引用长度依赖 seg0 最终长度）。
    seg1 = resource.build(
        func_offsets,
        module_code=module_code,
        total_size=len(seg0) + 1,
        stub_format=True,
        top_level_count=top_level_count,
        commands=_rb_commands,
        nested_ends=nested_ends,
        top_lambda_body_syms=_top_lambda_body_syms,
        module_func_count=_mr_func_count,
    )
    sec2_items = count_resource_items(seg1)
    # 确保 items 与 CAD 编译器一致。CAD 的 items 语义：
    # - 含 defun：2 * 模块注册数 + 2（模块注册数 = defun 数 + 顶层 form 数）。
    #   实测：1 函数→4、2 函数→6、3 函数→8、4 函数→10；mix(1 defun+1
    #   顶层)→6、topsetq(2 顶层)→6、t10(2 defun+2 顶层)→10。
    # - 纯顶层（无 defun）：items = 符号槽数 + 2（setcmp 4 form→5，
    #   符号 SET/_/@::_ 3 个 + 2 = 5）。CAD 加载时按 items 处理
    #   GVARINIT 记录，若偏小会遗漏函数注册。
    # 对拍 CAD 实测：items = 模块注册 GVARINIT st_init + 函数注册 GVARINIT
    # st_init（count_resource_items），混合文件（platform 66+6=72）亦吻合。
    min_items = count_resource_records(seg1)
    if sec2_items < min_items:
        sec2_items = min_items

    output = output or source.replace(".lsp", ".fas")
    # 编译产物验证：防止 CAD 加载时访问冲突 0xC0000005（越界符号引用/
    # 误解析/资源段损坏）。致命问题时报错退出（不写 .fas）；warning 仅提示。
    if verify:
        try:
            from compiler.fas_verify import verify_fas

            ok, _vissues = verify_fas(
                seg0, seg1, fas_nsyms, label=os.path.basename(output) or "output"
            )
            _vwarns = [v for v in _vissues if v.startswith("WARN ")]
            _verrs = [v for v in _vissues if not v.startswith("WARN ")]
            for _vi in _vwarns:
                print(f"verify: {_vi}", file=sys.stderr)
            if _verrs:
                print("Compile verification FAILED:", file=sys.stderr)
                for _vi in _verrs:
                    print(f"  - {_vi}", file=sys.stderr)
                print(
                    "FAS not written (would crash CAD with access violation 0xC0000005). "
                    "Fix the source or report the issue.",
                    file=sys.stderr,
                )
                sys.exit(2)
        except ImportError:
            pass  # 模块缺失时不阻断（验证是增强项）
    writer = FasWriter(symtab)
    writer.write(output, seg0, seg1, sec2_items=sec2_items, nsyms=fas_nsyms, compact=True)
    print(f"Compiled to {output}")

    if report_json:
        assert stats is not None
        report = {
            "tool": "atlispcc",
            "command": "compile",
            "source": source,
            "output": output,
            "opt_level": opt_level,
            "encoding": encoding,
            "analysis": {
                "functions": stats["functions"],
                "top_level_forms": stats["top_level_forms"],
                "total_instructions": stats["total_instructions"],
                "constants_estimate": stats["constants_estimate"],
                "symbol_table_entries": stats["symbol_table_entries"],
                "symbol_slots": stats["symbol_slots"],
                "function_offsets": stats["function_offsets"],
                "locals": stats["locals"],
                "tail_recursive_functions": stats["tail_recursive_functions"],
                "builtin_calls": sorted(stats["builtin_calls"]),
                "functions_detail": stats["functions_detail"],
            },
            "optimized": None,
            "product": {
                "nsyms": fas_nsyms,
                "codegen_nsyms": codegen_nsyms,
                "module_reg_count": module_reg_count,
                "top_level_count": top_level_count,
                "sec2_items": sec2_items,
                "seg0_size": len(seg0),
                "seg1_size": len(seg1),
            },
        }
        if stats2 is not None:
            report["optimized"] = {
                "functions": stats2["functions"],
                "total_instructions": stats2["total_instructions"],
                "tail_recursive_functions": stats2["tail_recursive_functions"],
                "symbol_table_entries": stats2["symbol_table_entries"],
                "functions_detail": stats2["functions_detail"],
            }
        with open(report_json, "w", encoding="utf-8") as fh:
            json.dump(report, fh, indent=2, ensure_ascii=False)
        print(f"Report written to {report_json}")

    return output


def cmd_decompile(source: str, output: str = "") -> str:
    parser_obj = Fas4Parser()
    fas = parser_obj.parse(source)
    disasm = Disassembler(short_subr=use_short_subr(fas.bytecode, fas.nsyms, fas.function_catalog))
    instructions = disasm.disassemble(fas.bytecode, fas.nsyms)
    cfa = ControlFlowAnalyzer(instructions, fas.function_catalog)
    functions = cfa.find_functions()
    gen = LispGenerator(fas)
    result = gen.generate(functions, source)

    output = output or source.replace(".fas", "_decomp.lsp")
    with open(output, "w", encoding="utf-8") as f:
        f.write(result)
    print(f"Decompiled to {output}")
    return output


def cmd_disassemble(source: str, output: str = "") -> str:
    """反汇编 .fas / .zelx → .lasm（字节码指令列表）。"""
    from asm.assembler import disassemble_fas

    tmp_fas = ""
    if source.lower().endswith(".zelx"):
        # zelx → fas → lasm：先用逆向恢复出 fas 再反汇编
        import os
        import tempfile
        from tools.zelx_to_fas import zelx_to_fas

        base = os.path.splitext(os.path.basename(source))[0]
        tmp_fas = os.path.join(tempfile.gettempdir(), f"{base}.fas")
        try:
            zelx_to_fas(source, tmp_fas)
            text = disassemble_fas(tmp_fas)
        finally:
            if os.path.exists(tmp_fas):
                os.unlink(tmp_fas)
    else:
        text = disassemble_fas(source)

    output = output or source.rsplit(".", 1)[0] + ".lasm"
    with open(output, "w", encoding="utf-8") as f:
        f.write(text)
    print(f"Disassembled to {output}")
    return output


def cmd_assemble(source: str, output: str = "") -> str:
    """汇编 .lasm → .fas。"""
    from asm.assembler import assemble_lasm

    with open(source, "rb") as f:
        from core.fas_core import decode_source_text
        text = decode_source_text(f.read())
    output = output or source.replace(".lasm", ".fas")
    assemble_lasm(text, output)
    print(f"Assembled to {output}")
    return output


def cmd_validate(source: str) -> int:
    import pathlib

    ok = validate_file(pathlib.Path(source))
    return 0 if ok else 1


def cmd_analyze(
    source: str,
    format: str = "text",
    output: str = "",
    no_cc: bool = False,
) -> int:
    """源码/FAS 调用图与依赖分析。

    format: text | dot | mermaid | json
    """
    from compiler.dep_analysis import build_from_lsp, build_from_fas
    from compiler.dep_analysis import format_text, format_dot, format_mermaid

    if source.lower().endswith(".fas") or source.lower().endswith(".zelx"):
        graph = build_from_fas(source)
    else:
        if os.path.exists(source):
            from core.fas_core import decode_source_text

            with open(source, "rb") as f:
                source_code = decode_source_text(f.read())
        else:
            source_code = source
        parser_obj = Parser(source_code)
        try:
            program = parser_obj.parse()
        except ParseError as e:
            print(f"Parse error: {e}", file=sys.stderr)
            return 1
        graph = build_from_lsp(program)

    # `--no-cc`：不把 c:*/*error* 显式提升为 root（仍保留顶层表达式 root）。
    if no_cc:
        roots = {r for r in graph["roots"] if r.startswith("c:") or r == "*error*"}
        for node in graph["nodes"]:
            if node["name"] in roots:
                node["root"] = False
        graph["roots"] = sorted(r for r in graph["roots"] if r not in roots)

    if format == "json":
        import json as _json

        text = _json.dumps(graph, indent=2, ensure_ascii=False)
    elif format == "dot":
        text = format_dot(graph)
    elif format == "mermaid":
        text = format_mermaid(graph)
    else:
        text = format_text(graph)

    if output:
        with open(output, "w", encoding="utf-8") as f:
            f.write(text)
    else:
        print(text)
    return 0


def cmd_info(source: str, json_out: bool = False) -> dict:
    """FAS/ZELX 快速概览 — 文件头/段规模/函数目录/符号/字符串，不触发完整反编译。

    实现复用 core/fas_core.parse_fas4（与 tools/fas-analyzer.py 同源），
    .zelx 输入走 tools.zelx_info.parse_zelx 解密载荷。
    """
    from core.fas_core import parse_fas4
    from core.fas_core import parse_resource_stream, build_mvar_tables, build_function_catalog

    if source.lower().endswith(".zelx"):
        from tools.zelx_info import parse_zelx

        z = parse_zelx(source)
        import collections
        import math

        entropy = sum(
            (-v / len(z["payload"])) * math.log2(v / len(z["payload"]))
            for v in collections.Counter(z["payload"]).values()
        )
        info = {
            "file": source,
            "format": "zelx",
            "size": z["size"],
            "zelx": {
                "X": z["X"],
                "Y": z["Y"],
                "Z": z["Z"],
                "sub": list(z["sub"]),
                "payload_size": z["seg2len"],
                "key_len": z["key_len"],
                "payload_entropy": round(entropy, 3),
            },
        }
        if not json_out:
            print(f"file size      : {z['size']}")
            print(f"ZAS header X   : {z['X']}  Y: {z['Y']}  Z(seg1 len): {z['Z']}")
            print(f"seg2 sub-hdr   : [len={z['sub'][0]}][{z['sub'][1]}][{z['sub'][2]}]")
            print(f"payload len    : {z['seg2len']}")
            print(f"key len        : {z['key_len']}")
            print(f"payload entropy: {entropy:.3f}")
        return info

    parsed = parse_fas4(source)
    nsyms = parsed["nsyms"]
    bytecode = parsed["bytecode"]
    seg0_total = len(bytecode)
    seg1_enc = parsed["res_data_encrypted"]
    seg1_dec = parsed["res_data_decrypted"]
    key = parsed["key"]
    res_items = parsed["res_items"]
    trailer = parsed["trailer"]

    # 格式类型：紧凑 stub / 自包含。沿用 fas-analyzer 的启发式。
    fmt = "compact-stub"
    if seg1_dec:
        resource_items, symbols, strings = parse_resource_stream(seg1_dec)
        resource_gvars, function_gvars = build_mvar_tables(seg1_dec, nsyms)
        catalog = build_function_catalog(resource_gvars, function_gvars)
    else:
        resource_items, symbols, strings = [], [], []
        catalog = []

    info = {
        "file": source,
        "size": os.path.getsize(source),
        "format": fmt,
        "nsyms": nsyms,
        "seg0_size": seg0_total,
        "seg1_size": len(seg1_enc),
        "seg1_decrypted_size": len(seg1_dec),
        "items": res_items,
        "key_size": len(key) if key else 0,
        "func_count": len(catalog),
        "catalog": catalog,
        "symbol_count": len(symbols),
        "string_count": len(strings),
        "trailer": trailer,
    }
    if not json_out:
        print(f"=== FAS4 概览 ===")
        print(f"文件      : {source}")
        print(f"大小      : {os.path.getsize(source)} bytes")
        print(f"格式      : {fmt}")
        print(f"nsyms     : {nsyms}")
        print(f"Seg0      : {seg0_total} bytes")
        print(f"Seg1      : {len(seg1_enc)} bytes (encrypted) / {len(seg1_dec)} bytes (decrypted)")
        print(f"items     : {res_items}")
        print(f"XOR key   : {len(key) if key else 0} bytes")
        if trailer:
            print(f"尾部      : {trailer[:60]}")
        if catalog:
            print(f"\n函数目录  : {len(catalog)} 条目")
            for name, off in catalog[:15]:
                print(f"  {name:30s} @ {off}")
            if len(catalog) > 15:
                print(f"  ... ({len(catalog) - 15} more)")
        if symbol_count := info["symbol_count"]:
            print(f"\n符号      : {symbol_count}")
            for s in symbols[:20]:
                print(f"  {s}")
            if symbol_count > 20:
                print(f"  ... ({symbol_count - 20} more)")
        if strings:
            print(f"\n字符串    : {len(strings)}")
            for s in strings[:10]:
                print(f"  {s!r}")
            if len(strings) > 10:
                print(f"  ... ({len(strings) - 10} more)")
    return info


def cmd_link(inputs: list, output: str, verbose: bool = False, encoding: str = "ansi") -> str:
    return link_fas(inputs, output, verbose, encoding=encoding)


def main():
    parser = argparse.ArgumentParser(
        prog="atlispcc",
        description="FAS4 bytecode compiler/decompiler toolchain for AutoLISP-compatible CAD platforms",
    )
    sub = parser.add_subparsers(dest="command", metavar="<command>")

    # compile
    p_compile = sub.add_parser("compile", aliases=["c"], help="Compile .lsp → .fas")
    p_compile.add_argument("source", help="input .lsp file")
    p_compile.add_argument("output", nargs="?", default="", help="output .fas file (optional)")
    p_compile.add_argument(
        "-O",
        type=int,
        default=0,
        choices=[0, 1, 2, 3],
        help="optimization level (0=none, 1=basic, 2=aggressive, 3=extreme)",
    )
    p_compile.add_argument("--analyze", action="store_true", help="show compilation analysis report")
    p_compile.add_argument(
        "--report",
        default="",
        help="write a structured compilation report (JSON) to the given path",
    )
    p_compile.add_argument(
        "--encoding",
        default="ansi",
        help="string/symbol encoding for FAS output "
        "(ansi=system codepage on Windows, default; or utf-8, gbk, cp936, ...)",
    )
    p_compile.add_argument(
        "--no-verify",
        dest="verify",
        action="store_false",
        help="skip post-compile verification (checks for bytecode that could "
        "crash CAD with access violation 0xC0000005)",
    )

    # decompile
    p_decompile = sub.add_parser("decompile", aliases=["d"], help="Decompile .fas → .lsp")
    p_decompile.add_argument("source", help="input .fas file")
    p_decompile.add_argument("output", nargs="?", default="", help="output .lsp file (optional)")

    # info: quick overview without full decompile
    p_info = sub.add_parser("info", help="Quick overview of a .fas/.zelx file (header, segments, function catalog)")
    p_info.add_argument("source", help="input .fas or .zelx file")
    p_info.add_argument("--json", action="store_true", help="print machine-readable JSON instead of text")

    # analyze: call-graph / dependency analysis (.lsp or .fas)
    p_analyze = sub.add_parser("analyze", help="Call graph / dependency analysis of a .lsp or .fas file")
    p_analyze.add_argument("source", help="input .lsp or .fas file")
    p_analyze.add_argument(
        "--format",
        "-f",
        choices=["text", "dot", "mermaid", "json"],
        default="text",
        help="output format (default: text)",
    )
    p_analyze.add_argument("-o", "--output", default="", help="write result to file instead of stdout")
    p_analyze.add_argument("--no-cc", action="store_true", help="do not treat c:* / *error* as entry roots")

    # roundtrip: compile → decompile → validate → compare smoke test
    p_roundtrip = sub.add_parser(
        "roundtrip",
        help="Smoke-test: compile .lsp → FAS → decompile → validate → compare",
    )
    p_roundtrip.add_argument("source", help="input .lsp file")
    p_roundtrip.add_argument(
        "-O",
        "--opt",
        type=int,
        default=0,
        choices=[0, 1, 2, 3],
        help="optimization level for the compile step (default: 0)",
    )
    p_roundtrip.add_argument(
        "--keep",
        action="store_true",
        help="keep intermediate .fas and decompiled .lsp in a temp dir and print their paths",
    )

    # validate
    p_validate = sub.add_parser("validate", aliases=["v"], help="Validate .lsp syntax")
    p_validate.add_argument("source", help="input .lsp file")

    # build zelx: .lsp/.fas → .zelx (ZWCAD)
    p_zelx = sub.add_parser("zelx", help="Build .zelx from .lsp/.fas (ZWCAD)")
    p_zelx.add_argument("source", help="input .lsp or .fas file")
    p_zelx.add_argument("output", nargs="?", default="", help="output .zelx file (optional)")

    # unzelx: .zelx → .fas
    p_unzelx = sub.add_parser("unzelx", help="Recover .fas from .zelx (ZWCAD)")
    p_unzelx.add_argument("source", help="input .zelx file")
    p_unzelx.add_argument("output", nargs="?", default="", help="output .fas file (optional)")

    # disassemble: .fas → .lasm
    p_disasm = sub.add_parser(
        "disasm", aliases=["disassemble"], help="Disassemble .fas/.zelx → .lasm (bytecode instructions)"
    )
    p_disasm.add_argument("source", help="input .fas or .zelx file")
    p_disasm.add_argument("output", nargs="?", default="", help="output .lasm file (optional)")

    # assemble: .lasm → .fas
    p_asm = sub.add_parser("asm", aliases=["assemble"], help="Assemble .lasm → .fas (or .zelx with --zelx)")
    p_asm.add_argument("source", help="input .lasm file")
    p_asm.add_argument("output", nargs="?", default="", help="output file (optional)")
    p_asm.add_argument("--zelx", action="store_true", help="assemble to ZWCAD .zelx")

    # link
    p_link = sub.add_parser("link", help="Link multiple .fas files into one")
    p_link.add_argument("inputs", nargs="+", help="input .fas files (2 or more)")
    p_link.add_argument("-o", "--output", default="", help="output .fas file")
    p_link.add_argument("--verbose", "-v", action="store_true", help="verbose output")
    p_link.add_argument(
        "--encoding",
        default="ansi",
        help="string/symbol encoding for linked FAS output (default: ansi=system codepage)",
    )

    # build-vlx
    p_vlx = sub.add_parser("build-vlx", help="Build VLX container from .fas files")
    p_vlx.add_argument("inputs", nargs="+", help="input .fas files")
    p_vlx.add_argument("-o", "--output", default="", help="output .vlx file")
    p_vlx.add_argument("--export", nargs="*", default=[], help="exported function names for namespace isolation")
    p_vlx.add_argument("--package", default="", help="VLX package/application name")

    args = parser.parse_args()

    if args.command is None:
        parser.print_help()
        return 0

    if args.command in ("compile", "c"):
        cmd_compile(
            args.source,
            args.output,
            opt_level=args.O,
            show_analysis=args.analyze,
            encoding=args.encoding,
            report_json=args.report,
            verify=args.verify,
        )
        return 0

    if args.command in ("decompile", "d"):
        cmd_decompile(args.source, args.output)
        return 0

    if args.command == "info":
        info = cmd_info(args.source, json_out=args.json)
        if args.json:
            print(json.dumps(info, indent=2, ensure_ascii=False))
        return 0

    if args.command == "analyze":
        return cmd_analyze(args.source, format=args.format, output=args.output, no_cc=args.no_cc)

    if args.command == "roundtrip":
        from compiler.roundtrip import run_roundtrip

        return run_roundtrip(args.source, opt_level=args.opt, keep=args.keep)

    if args.command in ("disasm", "disassemble"):
        cmd_disassemble(args.source, args.output)
        return 0

    if args.command in ("asm", "assemble"):
        if args.zelx:
            from asm.assembler import assemble_lasm_zelx

            with open(args.source, "rb") as f:
                from core.fas_core import decode_source_text
                text = decode_source_text(f.read())
            output = args.output or args.source.replace(".lasm", ".zelx")
            assemble_lasm_zelx(text, output)
            print(f"Assembled to {output}")
        else:
            cmd_assemble(args.source, args.output)
        return 0

    if args.command in ("validate", "v"):
        return cmd_validate(args.source)

    if args.command == "zelx":
        from tools.zelx_build import build_zelx

        output = args.output or args.source.rsplit(".", 1)[0] + ".zelx"
        build_zelx(args.source, output)
        print(f"Built {output}")
        return 0

    if args.command == "unzelx":
        from tools.zelx_to_fas import zelx_to_fas

        output = args.output or args.source.rsplit(".", 1)[0] + ".fas"
        zelx_to_fas(args.source, output)
        print(f"Built {output}")
        return 0

    if args.command == "link":
        if len(args.inputs) < 2:
            print("Error: need at least 2 input .fas files to link", file=sys.stderr)
            return 1
        output = args.output
        if not output:
            base = args.inputs[-1].rsplit(".", 1)[0]
            output = f"{base}_linked.fas"
        cmd_link(args.inputs, output, args.verbose, args.encoding)
        return 0

    if args.command == "build-vlx":
        output = args.output
        if not output:
            base = args.inputs[-1].rsplit(".", 1)[0]
            output = f"{base}.vlx"
        result = build_vlx(args.inputs, output, exports=args.export, package_name=args.package)
        print(f"Built {result}")
        return 0

    parser.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main() or 0)
