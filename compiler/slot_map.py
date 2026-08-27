"""Bytecode slot-mapping helpers (moved from cli.py)."""

import struct
from typing import Optional

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
from compiler.patch import _subr_bytes
from compiler.resource_builder import _real_fmt
from compiler.symbol_table import SymbolTable
from compiler.top_lambda import _lambda_real_args
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
                  n_cmds: int = 0, tl_funcobj_slot: Optional[int] = None,
                  first_cmd_slot: Optional[int] = None) -> bytes:
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

    def _fb(idx):
        """fallback gvar 槽：CONST（引用字面量）的 vl-ACAD-defun 移位（+n_cmds）
        仅当 const 注册在首个 c: 命令之后（menu/voice const 在 vl-ACAD-defun
        之后 → +n_cmds；panel `'("1" "AI" ...)` 在 foreach 组、位于 C:% 之前 →
        不加）；SYMBOL/STRING 表外符号仍 +n_cmds（atlisp_u `(set 'e2o ...)`
        实测）。"""
        if symtab is not None and 0 <= idx < len(symtab.entries):
            if symtab.entries[idx][0] == "CONST":
                if first_cmd_slot is not None and idx > first_cmd_slot:
                    return idx + 1 + n_cmds
                return idx + 1
        return idx + 1 + n_cmds

    out = bytearray()
    for inst in insts:
        name = inst.op_name
        raw = bc[inst.offset : inst.offset + inst.size]
        if name == "USUBR" and len(inst.operands) >= 2:
            slot = _slot_for(inst.operands[1])
            if slot is not None:
                out += _subr_bytes(0x35, inst.operands[0], slot, flags=3, wide=wide)
            else:
                out += _subr_bytes(0x35, inst.operands[0], _fb(inst.operands[1]), flags=3, wide=wide)
        elif name == "FUNC" and len(inst.operands) >= 2:
            slot = _slot_for(inst.operands[1])
            if slot is not None:
                out += _subr_bytes(0x51, inst.operands[0], slot, flags=1, wide=wide)
            else:
                out += _subr_bytes(0x51, inst.operands[0], _fb(inst.operands[1]), flags=1, wide=wide)
        elif name in ("PUSH_G", "SETQ_G", "PUSH_G_ALT") and len(inst.operands) >= 1:
            slot = _slot_for(inst.operands[0])
            if slot is not None:
                out += bytes([raw[0]]) + struct.pack("<H", slot)
            elif (
                tl_funcobj_slot is not None
                and name == "PUSH_G"
                and symtab is not None
                and 0 <= inst.operands[0] < len(symtab.entries)
                and symtab.entries[inst.operands[0]][0] == "SYMBOL"
                and str(symtab.entries[inst.operands[0]][1]).upper() == "-LAMBDA-"
            ):
                # 顶层 kwote lambda 的 func-obj 槽（DEFCODE 区注册的模块 rg
                # 槽，不在 gvar_map）：setup `(if @::*uris* (mapcar (function
                # (lambda (x) ...)) ...))` CAD 实测 PUSH_G 29。
                out += bytes([raw[0]]) + struct.pack("<H", tl_funcobj_slot)
            else:
                out += bytes([raw[0]]) + struct.pack("<H", _fb(inst.operands[0]))
        elif name == "PUSH_VALUE":
            # stub：PUSH_VALUE[0] 单字节 03；idx>0 为 3 字节。
            if len(inst.operands) == 1 and inst.operands[0] == 0 and inst.size == 1:
                out += raw  # 单字节 PUSH_VALUE[0]（调用后清理），不偏移
            elif len(inst.operands) == 1:
                slot = _slot_for(inst.operands[0])
                if slot is not None:
                    out += bytes([raw[0]]) + struct.pack("<H", slot)
                else:
                    out += bytes([raw[0]]) + struct.pack("<H", _fb(inst.operands[0]))
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


