import sys
import os
import argparse
import struct

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from compiler.parser import Parser, ParseError
from compiler.symbol_table import SymbolTable
from compiler.codegen import CodeGenerator, BytecodeBuffer
from compiler.ast_nodes import Defun, Defpackage, InPackage, Setq
from compiler.opt import optimize
from compiler.resource_builder import ResourceBuilder, build_module_code, build_command_module_code, count_resource_records, resolve_encoding
from compiler.fas_writer import FasWriter
from compiler.analyzer import analyze
from compiler.linker import link_fas
from compiler.vlx_builder import build_vlx
from decompiler.fas4_decompiler import Fas4Parser, Disassembler, ControlFlowAnalyzer, LispGenerator, is_compact_stub
from tools.validate import validate_file


ENCODE_POP = bytes([0x0a])


def _collect_builtins_for_stub(symtab, node):
    """stub 模式下将调用到的内建函数注册为符号槽（CAD stub 用符号槽编址调用）。"""
    from compiler.ast_nodes import (
        Call, Defun, Setq, IfNode, WhileNode, ForeachNode,
        RepeatNode, Progn, ListExpr, QuotedExpr, LambdaNode, Cond, Symbol,
    )
    if isinstance(node, Defun):
        for expr in node.body:
            _collect_builtins_for_stub(symtab, expr)
    elif isinstance(node, Call):
        if symtab.is_builtin(node.name) and node.name not in ('T', 'nil'):
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


def _patch_usubr_idx(seg0: bytes, seg1: bytes, symtab, nsyms: int, func_args=None) -> bytes:
    """修正 stub 字节码的 USUBR 与参数槽索引为 CAD 的 gvar 槽 - 1。

    CAD 实测逆向：
    - USUBR 调用符号的 gvar 槽 = idx + 1（idx = gvar 槽 - 1）
    - 参数绑定/读取槽 = 参数符号的 gvar 槽 - 1（越界符号 gvar 槽假定 = nsyms）
    codegen 用占位生成，此处用资源段 GVARINIT 重建的 gvar 表修正。
    """
    try:
        from core.fas_core import build_mvar_tables
        rg, fg = build_mvar_tables(seg1, nsyms)
    except Exception:
        return seg0
    gvar_map: dict = {}
    for idx, v in enumerate(fg):
        if isinstance(v, tuple) and len(v) == 2 and v[0] in ("SYMBOL", "STRING"):
            gvar_map.setdefault(str(v[1]).upper(), idx)

    def _strip_list_markers(v):
        """symtab 常量结构 → fg 表可比较形式（规范化大小写/INT/REAL/LIST）。

        fg 表里 BUILD_LIST 结果为裸内容元组（无 `'LIST'` 前缀），符号大写、
        整数为裸 int、实数裸 float；symtab CONST entry 保留 `('LIST', items)`、
        `('SYMBOL', name)`、`('INT', v)` 等标记。递归转换以便结构匹配。
        """
        if isinstance(v, tuple) and len(v) == 2:
            if v[0] == 'LIST':
                return tuple(_strip_list_markers(i) for i in v[1])
            if v[0] == 'SYMBOL':
                return ('SYMBOL', str(v[1]).upper())
            if v[0] in ('INT', 'INT8', 'INT32'):
                return int(v[1])
            if v[0] == 'REAL':
                return float(v[1])
            if v[0] in ('STRING', 'T', 'NIL'):
                return v
        if isinstance(v, (list, tuple)):
            return tuple(_strip_list_markers(i) for i in v)
        return v

    # CONST 常量（quoted lambda/list 等）在 fg 表里注册为嵌套结构；用结构匹配
    # 建立 结构 → gvar 槽 映射，供 CONST 引用编址（i18n 实测 ANSI 表 fg[98]、
    # loc-file 单元素列表 fg[94]）。排除原子（SYMBOL/STRING/REAL/CONS/FUNC）。
    const_map: dict = {}
    for idx, v in enumerate(fg):
        if isinstance(v, tuple) and not (len(v) == 2 and v[0] in ('SYMBOL', 'STRING', 'REAL', 'CONS', 'FUNC')):
            const_map.setdefault(v, idx)
    if not gvar_map:
        return seg0
    from decompiler.fas4_decompiler import Disassembler
    try:
        insts = Disassembler(short_subr=True).disassemble(seg0, nsyms, sym_count=len(symtab.entries))
    except Exception:
        return seg0

    def gvar_slot(name: str) -> int:
        # 资源段符号名已大写（_enc_sym），参数名为小写，查找时统一大写。
        return gvar_map.get(str(name).upper(), nsyms)

    def sym_of(idx: int):
        if 0 <= idx < len(symtab.entries) and symtab.entries[idx][0] in ("SYMBOL", "STRING"):
            return str(symtab.entries[idx][1]).upper()
        return None

    out = bytearray()
    multi = bool(func_args) and len(func_args) > 1
    func_iter = iter(func_args or [])
    cur_args = None
    arg_i = 0
    for inst in insts:
        if inst.op_name == "DEFUN":
            cur_args = next(func_iter, None) if func_args else None
            arg_i = 0
        # 参数绑定 PUSH_G（DEFUN 后 argc 个，仅多函数）
        if multi and inst.op_name == "PUSH_G" and cur_args is not None and arg_i < len(cur_args):
            arg = cur_args[arg_i]
            new_idx = gvar_slot(arg) - 1
            if 0 <= new_idx <= 0xFFFF:
                out += bytes([0x09, new_idx & 0xFF, (new_idx >> 8) & 0xFF])
                arg_i += 1
                continue
        # 参数读取 PUSH_VALUE（仅多函数）
        elif multi and inst.op_name == "PUSH_VALUE" and inst.size == 3 and cur_args is not None and inst.operands:
            idx = inst.operands[0]
            argc = len(cur_args)
            i = idx - nsyms + argc
            if 0 <= i < len(cur_args):
                arg = cur_args[i]
                new_idx = gvar_slot(arg) - 1
                if 0 <= new_idx <= 0xFFFF:
                    out += bytes([0x03, new_idx & 0xFF, (new_idx >> 8) & 0xFF])
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
            is_arg_bind = (
                inst.op_name == "PUSH_G"
                and cur_args is not None
                and arg_i < len(cur_args)
            )
            if is_arg_bind:
                arg_i += 1
                out += seg0[inst.offset:inst.offset + inst.size]
                continue
            if multi:
                sym = sym_of(inst.operands[0])
                if sym and sym in gvar_map:
                    new_idx = gvar_map[sym] - 1
                    if 0 <= new_idx <= 0xFFFF:
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
            if (
                inst.op_name == "PUSH_VALUE"
                and cur_args is not None
                and len(cur_args)
                and nsyms - len(cur_args) <= idx0 < nsyms
            ):
                out += seg0[inst.offset:inst.offset + inst.size]
                continue
            if 0 <= idx0 < len(symtab.entries):
                etype = symtab.entries[idx0][0]
                if etype == "CONST":
                    const_structure = symtab.entries[idx0][1]
                    # quoted 单符号 `'sym`：作为符号引用，按 gvar 槽编址
                    # （i18n 实测 `'sym` → SYM 的 gvar 槽；CAD quoted symbol）。
                    if (isinstance(const_structure, tuple) and len(const_structure) == 2
                            and const_structure[0] == 'SYMBOL'):
                        gslot = gvar_map.get(str(const_structure[1]).upper())
                        if gslot is not None:
                            new_idx = gslot - 1
                        else:
                            new_idx = idx0 - len(func_args) + 1
                    else:
                        fgstruct = _strip_list_markers(const_structure)
                        gslot = const_map.get(fgstruct)
                        if gslot is not None:
                            new_idx = gslot - 1
                        else:
                            # 未命中 fg（如简单常量）：沿用原公式
                            # gvar 槽 = symtab 槽 - nfuncs + 2 → 操作数 = - nfuncs + 1。
                            new_idx = idx0 - len(func_args) + 1
                elif etype == "STRING":
                    # 字符串 PUSH_G：多函数注册于符号槽末尾（gvar 槽 = nsyms，
                    # 操作数 = nsyms-1）；单函数 codegen 已输出正确槽，不修正。
                    if multi:
                        new_idx = nsyms - 1
                    else:
                        new_idx = None
                else:
                    new_idx = None
                if new_idx is not None and 0 <= new_idx <= 0xFFFF:
                    opcode = {"PUSH_VALUE": 0x03, "PUSH_G": 0x09, "SETQ_G": 0x06}[inst.op_name]
                    out += bytes([opcode, new_idx & 0xFF, (new_idx >> 8) & 0xFF])
                    continue
        elif inst.op_name == "USUBR" and len(inst.operands) >= 2:
            argc, idx = inst.operands[0], inst.operands[1]
            sym = sym_of(idx)
            if sym and sym in gvar_map:
                new_idx = gvar_map[sym] - 1
                out += bytes([0x35, argc & 0xFF, new_idx & 0xFF])
            else:
                out += seg0[inst.offset:inst.offset + inst.size]
            continue
        out += seg0[inst.offset:inst.offset + inst.size]
    return bytes(out)


def _build_cad_module_code(top_level_bc: bytes, symtab, other_forms, n_funcs: int = 0,
                           top_level_count: int = 0, top_after_defun: bool = False,
                           func_names: object = ()) -> bytes:
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

    module_reg_count = n_funcs + top_level_count
    out = bytearray(b'\x14\x01\x00\x00\x00')  # DEFUN 模块头
    out += bytes([0x09]) + struct.pack('<H', module_reg_count + 1) + b'\x0a'  # 占位

    # 顶层语句按源码位置分组：defun 之后的顶层语句（mix2 的 `(setq x 10)`）
    # 排到函数注册尾之后；defun 之前的排在 JUMP 之前。
    if top_after_defun and other_forms:
        pre_forms = other_forms[:-1]
        post_forms = [other_forms[-1]]
    else:
        pre_forms = other_forms
        post_forms = []

    def _stmt_bytes(form):
        """把单个顶层 form 编译为模块代码语句（setq 用 CAD 的 DUP 模式）。"""
        from compiler.ast_nodes import Symbol, String as _Str
        cg = CodeGenerator(symtab, stub_format=True, nsyms=len(symtab.entries))
        handled = False
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
                elif isinstance(value, Symbol) and value.name == 'nil':
                    pre += bytes([0x01])  # PUSH_NIL（CAD 用 PUSH_NIL 值 nil）
                    v_ok = True
                else:
                    v_idx = _slot_of(symtab, value)
                    if v_idx is None:
                        break  # 复杂值 → 退回通用路径
                    if isinstance(value, Symbol):
                        # 非引号符号值：CAD 用 PUSH_VALUE（setcmp
                        # `(setq _ @::_)` 实测 `03 <槽+1>`）；字符串/引用
                        # 符号（QuotedExpr）用 PUSH_G。
                        pre += bytes([0x03]) + struct.pack('<H', v_idx + 1)
                    else:
                        pre += bytes([0x09]) + struct.pack('<H', v_idx + 1)  # PUSH_G
                    v_ok = True
                if not v_ok:
                    break
                if i == n - 1:
                    pre += b'\x0b'  # DUP（仅在最后一对）
                pre += bytes([0x06]) + struct.pack('<H', t_idx + 1)  # SETQ_G
                pairs_bc += pre
            else:
                return bytes(pairs_bc)
        fb = BytecodeBuffer()
        cg._emit_expr(fb, form)
        fb.resolve()
        bc = bytes(fb.data)
        if isinstance(form, Setq):
            # setq 值非常量（INT/REAL/列表等）：CAD 在 SETQ_G 前插入 DUP
            # 保留返回值（mix2 `(setq x 10)` 实测 `32 0a 0b 06 03 00`）。
            import re
            m = re.compile(b'\x06..', re.S).search(bc)
            if m:
                bc = bc[:m.start()] + b'\x0b' + bc[m.start():]
        return _offset_slots(bc, len(symtab.entries))

    def _emit_stmts(forms, last_no_pop: bool):
        """输出一组语句，每条后 POP；last_no_pop=True 时最后一条不跟 POP。"""
        nonlocal out
        for i, form in enumerate(forms):
            stmt = _stmt_bytes(form)
            out += stmt
            if i < len(forms) - 1 or not last_no_pop:
                out += b'\x0a'  # POP

    _emit_stmts(pre_forms, last_no_pop=(n_funcs == 0 and not post_forms))

    if n_funcs > 0:
        # 有 defun：追加函数注册尾（CAD 实测）。多函数时每函数一组
        # `PUSH_G <b>; SETQ_G <c>`，组间 `PUSH_G <c>; POP; JUMP`；
        # b = 2*n_funcs+1 + top_level_count - i（模块注册偏移）。
        # c 槽 = 源码注册序递减：顶层在 defun 后时（top_after_defun）
        # 函数占 c = n_funcs+1-i、顶层占 1；否则函数占 c = n_funcs-i、
        # 末尾补 `PUSH_G 1`。
        out += b'\x57\x00\x00\x00\x00'  # JUMP
        for i in range(n_funcs):
            b = 2 * n_funcs + 1 + top_level_count - i
            # SETQ_G 目标是第 i 个函数（注册序逆序）的 gvar 槽 = 符号槽 + 1
            # （p03 实测 @::codepage2lang 槽 4 → c=5）。未显式给定函数名时
            # 退化为相对编号 n_funcs-i，与单函数槽=0 情形一致。
            fn_slot = symtab.name_to_idx.get(func_names[i]) if i < len(func_names) and func_names else None
            c = (fn_slot + 1) if fn_slot is not None else (n_funcs - i)
            out += bytes([0x09]) + struct.pack('<H', b)  # PUSH_G b
            out += bytes([0x06]) + struct.pack('<H', c)  # SETQ_G c
            if i < n_funcs - 1 or post_forms:
                out += bytes([0x09]) + struct.pack('<H', c) + b'\x0a'
            if i < n_funcs - 1:
                out += b'\x57\x00\x00\x00\x00'
        if post_forms:
            _emit_stmts(post_forms, last_no_pop=True)
        elif not top_after_defun:
            out += bytes([0x09]) + struct.pack('<H', 1)  # PUSH_G 1
    else:
        if post_forms:
            _emit_stmts(post_forms, last_no_pop=True)
    out += b'\x16'  # END_DEFUN
    return bytes(out)


def _slot_of(symtab, node):
    """返回 AST 节点的符号/字符串槽索引；非字面量返回 None。"""
    from compiler.ast_nodes import Symbol, String as _Str
    if isinstance(node, Symbol):
        return symtab.name_to_idx.get(node.name)
    if isinstance(node, _Str):
        return symtab.name_to_idx.get(f'__str_{node.value}__')
    return None


def _is_empty_quote(node) -> bool:
    """判断是否为空列表引用 `'()`（CAD 用 PUSH_NIL，无常量槽）。"""
    from compiler.ast_nodes import QuotedExpr, ListExpr
    return isinstance(node, QuotedExpr) and isinstance(node.expr, ListExpr) and not node.expr.items


def _offset_slots(bc: bytes, n_sym: int) -> bytes:
    """把字节码中的符号槽引用 +1（CAD 模块代码用 gvar 槽 = 符号槽+1）。

    处理 PUSH_G(0x09)/PUSH_VALUE(0x03)/SETQ_G(0x06)/USUBR(0x35) 的符号槽。
    stub 的 PUSH_VALUE[0]（单字节 ``03``）与调用后清理序列 ``00 03`` 不偏移。
    """
    from decompiler.fas4_decompiler import Disassembler
    dis = Disassembler(short_subr=True)
    try:
        insts = dis.disassemble(bc, n_sym, sym_count=n_sym)
    except Exception:
        return bc
    out = bytearray()
    for inst in insts:
        name = inst.op_name
        raw = bc[inst.offset:inst.offset + inst.size]
        if name == "USUBR" and len(inst.operands) >= 2:
            out += bytes([0x35, inst.operands[0] & 0xFF, (inst.operands[1] + 1) & 0xFF])
        elif name in ("PUSH_G", "SETQ_G", "PUSH_G_ALT") and len(inst.operands) >= 1:
            idx = inst.operands[0] + 1
            out += bytes([raw[0]]) + struct.pack('<H', idx)
        elif name == "PUSH_VALUE":
            # stub：PUSH_VALUE[0] 单字节 03；idx>0 为 3 字节。
            if len(inst.operands) == 1 and inst.operands[0] == 0 and inst.size == 1:
                out += raw  # 单字节 PUSH_VALUE[0]（调用后清理），不偏移
            elif len(inst.operands) == 1:
                out += bytes([raw[0]]) + struct.pack('<H', inst.operands[0] + 1)
            else:
                out += raw
        else:
            out += raw
    return bytes(out)


def _collect_symbol_nodes(node):
    """递归收集 AST 节点中的 Symbol/String 节点。"""
    from compiler.ast_nodes import (
        Symbol, String, ListExpr, QuotedExpr, Setq, IfNode, WhileNode,
        ForeachNode, RepeatNode, Call, Progn, LambdaNode, Cond,
    )
    if isinstance(node, Symbol) or isinstance(node, String):
        yield node
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
        yield from _collect_symbol_nodes(node.expr)
    elif isinstance(node, LambdaNode):
        for a in node.args:
            yield Symbol(a)
        for e in node.body:
            yield from _collect_symbol_nodes(e)


def cmd_compile(source: str, output: str = '', opt_level: int = 0, show_analysis: bool = False,
                encoding: str = 'ansi') -> str:
    if os.path.exists(source):
        with open(source, 'r', encoding='utf-8') as f:
            source_code = f.read()
    else:
        source_code = source
    parser_obj = Parser(source_code)
    try:
        program = parser_obj.parse()
    except ParseError as e:
        print(f'Parse error: {e}', file=sys.stderr)
        sys.exit(1)

    package_table = parser_obj.packages

    if show_analysis:
        stats = analyze(program)
        print('=== Compilation Analysis ===')
        print(f'  Functions:               {stats["functions"]}')
        print(f'  Top-level forms:         {stats["top_level_forms"]}')
        print(f'  Total instructions:      {stats["total_instructions"]}')
        print(f'  Constants (estimate):    {stats["constants_estimate"]}')
        print(f'  Symbol table entries:    {stats["symbol_table_entries"]}')
        print(f'  Function offsets:        {stats["function_offsets"]}')
        print(f'  Locals (total):          {stats["locals"]}')
        print(f'  Tail-recursive:          {stats["tail_recursive_functions"]}')
        print(f'  External/builtin calls:  {len(stats["builtin_calls"])}')
        for fd in stats['functions_detail']:
            tr = ' [tail-recursive]' if fd['tail_recursive'] else ''
        print(f'    {fd["name"]}: {fd["instructions"]} instr, '
              f'{fd["args"]} args, {fd["locals"]} locals, '
              f'calls {fd["calls"]}{tr}')
        print()

    if opt_level:
        program = optimize(program, level=opt_level)
        if show_analysis:
            stats2 = analyze(program)
            print(f'=== After O{opt_level} Optimization ===')
            print(f'  Functions:          {stats2["functions"]} (was {stats["functions"]})')
            print(f'  Instructions:       {stats2["total_instructions"]} (was {stats["total_instructions"]})')
            print(f'  Tail-recursive:     {stats2["tail_recursive_functions"]}')
            print()

    symtab = SymbolTable(package_table=package_table)
    defun_forms = [f for f in program.forms if isinstance(f, Defun)]
    # 纯 &rest（min=0）：CAD 实测不收集 rest（b4=01 需至少一个必填参数）
    for f in defun_forms:
        if f.rest and not f.args and not f.optional:
            print(
                f"Warning: function '{f.name}' uses bare &rest (min args = 0); "
                f"CAD does not collect rest args for min=0 — consider adding "
                f"a required param, e.g. (defun {f.name} (x &rest {f.rest}))",
                file=sys.stderr,
            )
    from compiler.cad_symbols import derive_symbol_names, is_const_entry
    for sym in derive_symbol_names(program):
        if is_const_entry(sym):
            symtab.add_constant(sym[1])
        elif sym.startswith('"') and sym.endswith('"'):
            symtab.add_string(sym[1:-1])
        elif sym in symtab.name_to_idx:
            # CAD stub：允许符号重复（递归/跨函数引用产生重复槽）
            symtab.add_force(sym)
        else:
            symtab.get_or_add(sym)

    # 顶层表达式符号（defun 之外）：CAD 把它们的符号并入模块注册段。
    other_forms = [f for f in program.forms
                   if not isinstance(f, (Defun, Defpackage, InPackage))]
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
        elif f'__str_{s}__' in symtab.name_to_idx:
            _top_slots.append(symtab.name_to_idx[f'__str_{s}__'])
    # CAD 按"最高顶层符号槽号 + 1"计模块注册区宽，const/defun 名等内部槽
    # 一并覆盖（i18n ap03 实测 syscodepage const@idx2 使 @::*I18N* 槽到 idx9，
    # count 应为 max+1 而非顶层去重符号数）。
    if _top_slots:
        top_level_count = max(_top_slots) + 1 - len(defun_forms)
    else:
        top_level_count = 0

    codegen = CodeGenerator(symtab, stub_format=True,
                            defined_funcs=[f.name for f in defun_forms],
                            nsyms=len(symtab.entries) - len(defun_forms) - top_level_count + 1)

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
    for form in other_forms:
        codegen._emit_expr(top_level_bc, form)
        if isinstance(form, Setq):
            top_level_bc.emit(ENCODE_POP)
    top_level_bc.resolve()
    top_level_code = bytes(top_level_bc.data)

    all_bytecode = BytecodeBuffer()
    for i, form in enumerate(defun_forms):
        offset = len(all_bytecode.data)
        func_bytecode, _ = codegen.generate_function(form)
        func_offsets[form.name] = offset
        all_bytecode.emit(func_bytecode)
        if i < len(defun_forms) - 1:
            # CAD stub: 函数间分隔符 `16`（CLEAR_ARGS `19 <argc> 00` 已由
            # generate_function 生成，仅需追加 END_DEFUN 分隔）。
            all_bytecode.emit(bytes([0x16]))

    for name, offset in func_offsets.items():
        symtab.add_func_ref(name, offset)

    all_bytecode.resolve()
    seg0 = bytes(all_bytecode.data)

    # 模块代码：含顶层表达式时用 CAD 风格完整模块代码；否则固定函数注册尾。
    # c: 命令函数：CAD 在模块注册段插入 vl-ACAD-defun 符号并生成命令模块代码。
    # vl-ACAD-defun 仅在模块注册段（resource_gvars）注册，不进符号表（不参与
    # 函数符号槽编址），故 seg0 的 PUSH_VALUE 索引保持不变。
    n_cmds = 1 if any(getattr(f, 'is_command', False) or str(f.name).startswith('c:') for f in defun_forms) else 0
    resource = ResourceBuilder(symtab, encoding=encoding)
    module_reg_count = len(defun_forms) + top_level_count
    fas_nsyms = len(symtab.entries) - module_reg_count + 1
    _pre_nsyms = fas_nsyms
    if other_forms:
        # 顶层语句在源码中位于最后一个 defun 之后（如 `(set '_ @::_)`）时，
        # 排到函数注册尾之后（mix2 实测：`(setq x 10)` 在 defun b 后）。
        _last_overall = program.forms[-1] if program.forms else None
        from compiler.ast_nodes import Defun as _Defun
        _top_after_defun = _last_overall is not None and not isinstance(_last_overall, (_Defun, Defpackage, InPackage))
        module_code = _build_cad_module_code(top_level_code, symtab, other_forms,
                                             n_funcs=len(defun_forms), top_level_count=top_level_count,
                                             top_after_defun=_top_after_defun,
                                             func_names=[f.name for f in defun_forms])
    elif n_cmds:
        module_code = build_command_module_code(len(defun_forms))
    else:
        module_code = build_module_code(len(defun_forms), nsyms=_pre_nsyms)

    # 修正 USUBR/参数槽索引：CAD 用 `gvar 槽 - 1`（gvar 表由资源段 GVARINIT 建立）。
    def _all_params(f):
        return f.args + f.optional + ([f.rest] if f.rest else [])

    # 第一轮：先用未 patch 的 seg0 建 seg1 以获取 gvar 表。
    seg1 = resource.build(func_offsets, module_code=module_code, total_size=len(seg0) + 1, stub_format=True,
                          top_level_count=top_level_count, commands=n_cmds)
    seg0 = _patch_usubr_idx(seg0, seg1, symtab, fas_nsyms, [_all_params(f) for f in defun_forms])
    # 第二轮：用 patch 后的 seg0 重建 seg1（代码引用长度依赖 seg0 最终长度）。
    seg1 = resource.build(func_offsets, module_code=module_code, total_size=len(seg0) + 1, stub_format=True,
                           top_level_count=top_level_count, commands=n_cmds)
    sec2_items = count_resource_records(seg1)
    # 确保 items 与 CAD 编译器一致。CAD 的 items 语义：
    # - 含 defun：2 * 模块注册数 + 2（模块注册数 = defun 数 + 顶层 form 数）。
    #   实测：1 函数→4、2 函数→6、3 函数→8、4 函数→10；mix(1 defun+1
    #   顶层)→6、topsetq(2 顶层)→6、t10(2 defun+2 顶层)→10。
    # - 纯顶层（无 defun）：items = 符号槽数 + 2（setcmp 4 form→5，
    #   符号 SET/_/@::_ 3 个 + 2 = 5）。CAD 加载时按 items 处理
    #   GVARINIT 记录，若偏小会遗漏函数注册。
    if len(defun_forms):
        min_items = 2 * (len(defun_forms) + top_form_count) + 2
    else:
        min_items = len(symtab.entries) + 2
    if sec2_items < min_items:
        sec2_items = min_items

    output = output or source.replace('.lsp', '.fas')
    writer = FasWriter(symtab)
    writer.write(output, seg0, seg1, sec2_items=sec2_items, nsyms=fas_nsyms,
                 compact=True)
    print(f'Compiled to {output}')
    return output


def cmd_decompile(source: str, output: str = '') -> str:
    parser_obj = Fas4Parser()
    fas = parser_obj.parse(source)
    disasm = Disassembler(short_subr=is_compact_stub(fas.bytecode, fas.function_catalog))
    instructions = disasm.disassemble(fas.bytecode, fas.nsyms)
    cfa = ControlFlowAnalyzer(instructions, fas.function_catalog)
    functions = cfa.find_functions()
    gen = LispGenerator(fas)
    result = gen.generate(functions, source)

    output = output or source.replace('.fas', '_decomp.lsp')
    with open(output, 'w', encoding='utf-8') as f:
        f.write(result)
    print(f'Decompiled to {output}')
    return output


def cmd_disassemble(source: str, output: str = '') -> str:
    """反汇编 .fas / .zelx → .lasm（字节码指令列表）。"""
    from asm.assembler import disassemble_fas

    tmp_fas = ''
    if source.lower().endswith('.zelx'):
        # zelx → fas → lasm：先用逆向恢复出 fas 再反汇编
        import os
        import tempfile
        from tools.zelx_to_fas import zelx_to_fas
        base = os.path.splitext(os.path.basename(source))[0]
        tmp_fas = os.path.join(tempfile.gettempdir(), f'{base}.fas')
        try:
            zelx_to_fas(source, tmp_fas)
            text = disassemble_fas(tmp_fas)
        finally:
            if os.path.exists(tmp_fas):
                os.unlink(tmp_fas)
    else:
        text = disassemble_fas(source)

    output = output or source.rsplit('.', 1)[0] + '.lasm'
    with open(output, 'w', encoding='utf-8') as f:
        f.write(text)
    print(f'Disassembled to {output}')
    return output


def cmd_assemble(source: str, output: str = '') -> str:
    """汇编 .lasm → .fas。"""
    from asm.assembler import assemble_lasm
    with open(source, 'r', encoding='utf-8') as f:
        text = f.read()
    output = output or source.replace('.lasm', '.fas')
    assemble_lasm(text, output)
    print(f'Assembled to {output}')
    return output


def cmd_validate(source: str) -> int:
    import pathlib
    ok = validate_file(pathlib.Path(source))
    return 0 if ok else 1


def cmd_link(inputs: list, output: str, verbose: bool = False, encoding: str = 'ansi') -> str:
    return link_fas(inputs, output, verbose, encoding=encoding)


def main():
    parser = argparse.ArgumentParser(
        prog='atlispcc',
        description='FAS4 bytecode compiler/decompiler toolchain for AutoLISP-compatible CAD platforms',
    )
    sub = parser.add_subparsers(dest='command', metavar='<command>')

    # compile
    p_compile = sub.add_parser('compile', aliases=['c'], help='Compile .lsp → .fas')
    p_compile.add_argument('source', help='input .lsp file')
    p_compile.add_argument('output', nargs='?', default='', help='output .fas file (optional)')
    p_compile.add_argument('-O', type=int, default=0, choices=[0, 1, 2, 3],
                           help='optimization level (0=none, 1=basic, 2=aggressive, 3=extreme)')
    p_compile.add_argument('--analyze', action='store_true',
                           help='show compilation analysis report')
    p_compile.add_argument('--encoding', default='ansi',
                           help='string/symbol encoding for FAS output '
                                '(ansi=system codepage on Windows, default; or utf-8, gbk, cp936, ...)')

    # decompile
    p_decompile = sub.add_parser('decompile', aliases=['d'], help='Decompile .fas → .lsp')
    p_decompile.add_argument('source', help='input .fas file')
    p_decompile.add_argument('output', nargs='?', default='', help='output .lsp file (optional)')

    # validate
    p_validate = sub.add_parser('validate', aliases=['v'], help='Validate .lsp syntax')
    p_validate.add_argument('source', help='input .lsp file')

    # build zelx: .lsp/.fas → .zelx (ZWCAD)
    p_zelx = sub.add_parser('zelx', help='Build .zelx from .lsp/.fas (ZWCAD)')
    p_zelx.add_argument('source', help='input .lsp or .fas file')
    p_zelx.add_argument('output', nargs='?', default='', help='output .zelx file (optional)')

    # unzelx: .zelx → .fas
    p_unzelx = sub.add_parser('unzelx', help='Recover .fas from .zelx (ZWCAD)')
    p_unzelx.add_argument('source', help='input .zelx file')
    p_unzelx.add_argument('output', nargs='?', default='', help='output .fas file (optional)')

    # disassemble: .fas → .lasm
    p_disasm = sub.add_parser('disasm', aliases=['disassemble'],
                              help='Disassemble .fas/.zelx → .lasm (bytecode instructions)')
    p_disasm.add_argument('source', help='input .fas or .zelx file')
    p_disasm.add_argument('output', nargs='?', default='', help='output .lasm file (optional)')

    # assemble: .lasm → .fas
    p_asm = sub.add_parser('asm', aliases=['assemble'],
                           help='Assemble .lasm → .fas (or .zelx with --zelx)')
    p_asm.add_argument('source', help='input .lasm file')
    p_asm.add_argument('output', nargs='?', default='', help='output file (optional)')
    p_asm.add_argument('--zelx', action='store_true', help='assemble to ZWCAD .zelx')

    # link
    p_link = sub.add_parser('link', help='Link multiple .fas files into one')
    p_link.add_argument('inputs', nargs='+', help='input .fas files (2 or more)')
    p_link.add_argument('-o', '--output', default='', help='output .fas file')
    p_link.add_argument('--verbose', '-v', action='store_true', help='verbose output')
    p_link.add_argument('--encoding', default='ansi',
                        help='string/symbol encoding for linked FAS output (default: ansi=system codepage)')

    # build-vlx
    p_vlx = sub.add_parser('build-vlx', help='Build VLX container from .fas files')
    p_vlx.add_argument('inputs', nargs='+', help='input .fas files')
    p_vlx.add_argument('-o', '--output', default='', help='output .vlx file')
    p_vlx.add_argument('--export', nargs='*', default=[],
                       help='exported function names for namespace isolation')
    p_vlx.add_argument('--package', default='',
                       help='VLX package/application name')

    args = parser.parse_args()

    if args.command is None:
        parser.print_help()
        return 0

    if args.command in ('compile', 'c'):
        cmd_compile(args.source, args.output, opt_level=args.O,
                    show_analysis=args.analyze, encoding=args.encoding)
        return 0

    if args.command in ('decompile', 'd'):
        cmd_decompile(args.source, args.output)
        return 0

    if args.command in ('disasm', 'disassemble'):
        cmd_disassemble(args.source, args.output)
        return 0

    if args.command in ('asm', 'assemble'):
        if args.zelx:
            from asm.assembler import assemble_lasm_zelx
            with open(args.source, 'r', encoding='utf-8') as f:
                text = f.read()
            output = args.output or args.source.replace('.lasm', '.zelx')
            assemble_lasm_zelx(text, output)
            print(f'Assembled to {output}')
        else:
            cmd_assemble(args.source, args.output)
        return 0

    if args.command in ('validate', 'v'):
        return cmd_validate(args.source)

    if args.command == 'zelx':
        from tools.zelx_build import build_zelx
        output = args.output or args.source.rsplit('.', 1)[0] + '.zelx'
        build_zelx(args.source, output)
        print(f'Built {output}')
        return 0

    if args.command == 'unzelx':
        from tools.zelx_to_fas import zelx_to_fas
        output = args.output or args.source.rsplit('.', 1)[0] + '.fas'
        zelx_to_fas(args.source, output)
        print(f'Built {output}')
        return 0

    if args.command == 'link':
        if len(args.inputs) < 2:
            print('Error: need at least 2 input .fas files to link', file=sys.stderr)
            return 1
        output = args.output
        if not output:
            base = args.inputs[-1].rsplit('.', 1)[0]
            output = f'{base}_linked.fas'
        cmd_link(args.inputs, output, args.verbose, args.encoding)
        return 0

    if args.command == 'build-vlx':
        output = args.output
        if not output:
            base = args.inputs[-1].rsplit('.', 1)[0]
            output = f'{base}.vlx'
        result = build_vlx(args.inputs, output,
                           exports=args.export,
                           package_name=args.package)
        print(f'Built {result}')
        return 0

    parser.print_help()
    return 1


if __name__ == '__main__':
    sys.exit(main() or 0)
