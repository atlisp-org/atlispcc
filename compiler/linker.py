"""FAS4 Linker — merge multiple .fas files into one, resolving cross-file symbols."""

import os
import struct
import sys
from typing import List, Dict, Tuple, Set, Any, Optional

from decompiler.fas4_decompiler import Fas4Parser, Disassembler
from compiler.symbol_table import SymbolTable
from compiler.resource_builder import ResourceBuilder, build_module_code, count_resource_records
from compiler.fas_writer import FasWriter
from asm.opcodes import (
    OPCODE_TO_NAME,
    OPCODE_FORMAT,
    encode_op_u16,
    encode_op_noarg,
    encode_op_u8,
    encode_op_s32,
    encode_op_u32,
    encode_bb,
    encode_usubr,
    encode_usubr3,
    encode_func,
    encode_func3,
    encode_defun,
    encode_eval,
    encode_real,
)
from decompiler.fas4_decompiler import is_compact_stub, use_short_subr
from compiler._gvar_map import build_module_gvar_map


def _fas_is_stub(fas) -> bool:
    """用反编译器完整判定（is_compact_stub + DEFCODE/argc 头检测）。"""
    try:
        from decompiler.fas4_decompiler import LispGenerator
        return LispGenerator(fas).is_stub_format
    except Exception:
        from decompiler.fas4_decompiler import detect_layout_bytes

        return detect_layout_bytes(
            fas.bytecode, fas.function_catalog, fas.symbol_slots
        ) == "compact"

_DATA_TYPES = {"SYMBOL", "STRING", "INT8", "INT32", "REAL"}

_SYM_REF_INSTS = {"PUSH_VALUE", "PUSH_G", "PUSH_G_ALT", "SETQ_G"}
_FUNC_REF_INSTS = {"FUNC", "USUBR"}


def _is_data_item(item: Tuple) -> bool:
    """True if item is a data entry that occupies a slot in the symbol table."""
    return len(item) >= 2 and item[0] in _DATA_TYPES


def _data_items(items: List[Tuple]) -> List[Tuple]:
    return [it for it in items if _is_data_item(it)]


def _make_item_key(item: Tuple) -> str:
    return item[0] + ":" + str(item[1])


def _collect_global_data(parsed_fas_list: list) -> List[Tuple]:
    """Merge all data entries across files, preserving first-occurrence order."""
    seen: Set[str] = set()
    merged: List[Tuple] = []
    for fas in parsed_fas_list:
        for item in _data_items_of(fas):
            key = _make_item_key(item)
            if key not in seen:
                seen.add(key)
                merged.append(item)
    return merged


def _build_local_data_map(global_data: List[Tuple], fas) -> Dict[int, int]:
    """Build local→global index map for data entries of one file."""
    g_by_key: Dict[str, int] = {}
    for g_idx, item in enumerate(global_data):
        key = _make_item_key(item)
        if key not in g_by_key:
            g_by_key[key] = g_idx
    local_data = _data_items_of(fas)
    local_map: Dict[int, int] = {}
    for l_idx, item in enumerate(local_data):
        key = _make_item_key(item)
        if key in g_by_key:
            local_map[l_idx] = g_by_key[key]
    return local_map


def _needs_symbol_patch(name: str) -> bool:
    return name in _SYM_REF_INSTS or name in _FUNC_REF_INSTS or name == "DEFUN"


def _warn(msg: str) -> None:
    print(f"WARNING: {msg}", file=sys.stderr)


def _patch_operands(inst, file_sym_map: Dict[int, int], file_sym_slot_map: Optional[Dict[int, int]] = None) -> List:
    name = inst.op_name
    ops = list(inst.operands)
    if not ops:
        return ops
    if name in _SYM_REF_INSTS:
        # PUSH_G/SETQ_G 用符号槽（CAD/单文件编译器约定）；PUSH_VALUE 用 gvar 槽-1
        if name in ("PUSH_G", "PUSH_G_ALT", "SETQ_G") and file_sym_slot_map:
            slot_map = file_sym_slot_map
        else:
            slot_map = file_sym_map
        local_idx = ops[0]
        if local_idx in slot_map:
            ops[0] = slot_map[local_idx]
    elif name in _FUNC_REF_INSTS:
        if len(ops) >= 2:
            local_idx = ops[1]
            if local_idx in file_sym_map:
                ops[1] = file_sym_map[local_idx]
    elif name == "DEFUN":
        if len(ops) >= 4:
            gv = ops[0] | (ops[1] << 8)
            if gv in file_sym_map:
                new_gv = file_sym_map[gv]
            else:
                new_gv = gv
            ops[0] = new_gv & 0xFF
            ops[1] = (new_gv >> 8) & 0xFF
    return ops


def _encode_with_opcode(opcode: int, name: str, operands: List, short_subr: bool = False) -> bytes:
    fmt = OPCODE_FORMAT.get(opcode, "")
    if fmt == "":
        return encode_op_noarg(opcode)
    elif fmt == "1":
        return encode_op_u8(opcode, int(operands[0]))
    elif fmt == "2":
        return encode_op_u16(opcode, int(operands[0]))
    elif fmt == "4":
        return encode_op_s32(opcode, int(operands[0]))
    elif fmt == "s4":
        return encode_op_s32(opcode, int(operands[0]))
    elif fmt == "bb":
        return encode_bb(opcode, int(operands[0]), int(operands[1]))
    elif fmt == "u":
        if short_subr:
            return encode_usubr3(int(operands[0]), int(operands[1]))
        return encode_usubr(int(operands[0]), int(operands[1]), int(operands[2]) if len(operands) > 2 else 0)
    elif fmt == "f":
        if short_subr:
            return encode_func3(int(operands[0]), int(operands[1]))
        return encode_func(int(operands[0]), int(operands[1]), int(operands[2]) if len(operands) > 2 else 0)
    elif fmt == "h":
        gv, off = int(operands[0]), int(operands[1]) if len(operands) > 1 else 0
        return encode_defun(gv, off)
    elif fmt == "e":
        return encode_eval(int(operands[0]), int(operands[1]) if len(operands) > 1 else 0)
    elif fmt == "z":
        return bytes([opcode]) + str(operands[0]).encode("ascii") + b"\x00"
    else:
        raise ValueError(f"Unknown format {fmt} for {name} (op={opcode:02x})")


# ── module code / top-level expressions (seg1 tail) ────────────────────
#
# A compiled unit keeps its top-level (non-defun) expressions in the module
# code that follows the resource stream's INIT_DONE (0x1c).  The module code is
# `DEFUN头 + [顶层语句] + [函数注册组] + END_DEFUN`, with registration groups
# interleaved in source order.  For merging we:
#   1. split the tail after `1c 14 01`,
#   2. drop the header / placeholder / registration groups / tail,
#   3. keep the remaining (top-level) instructions,
#   4. remap their gvar/function slots into the merged module table,
#   5. rebuild one registration block and splice the top-level bytes before
#      its final `PUSH_G 1; END_DEFUN`.
#
# Only linear top-level statements are supported (no if/while/let/lambda,
# no commands).  Anything else is rejected with a clear message.

_MODULE_UNSUPPORTED = {
    "DEFUN", "DEFUN_ALT",
    "JMP16_IFNOT", "JMP16_IF", "JMP16_IFNOT_ALT", "JMP16_IF_ALT",
    "JMP32_IFNOT", "JUMP", "JUMP_ALT", "COND_OR", "COND_AND",
    "GET_LOCAL", "GET_LOCAL_WIDE", "SET_LOCAL", "CLEAR_LOCAL",
    "EXIT_IF_NOT_ZERO", "EXIT_IF_ZERO", "COPY_ELEM", "EVAL",
}

_PUSH_OPS = {
    "PUSH_G", "PUSH_G_ALT", "PUSH_VALUE", "PUSH_INT8", "PUSH_INT32",
    "PUSH_REAL", "PUSH_NIL", "PUSH_T", "GET_LOCAL", "GET_LOCAL_WIDE",
    "DUP", "CAR", "CDR", "NOT", "ATOM", "INC", "DEC",
}
_POP_OPS = {"POP", "SETQ_G", "SET_LOCAL", "CLEAR_LOCAL"}
_ARITH_OPS = {
    "FIX_ADD", "FIX_SUB", "FIX_MUL", "FIX_DIV", "FIX_MOD",
    "FIX_LEQ", "FIX_GEQ", "FIX_LT", "FIX_GT",
}
_SLOT_OPS = {"PUSH_G", "PUSH_G_ALT", "PUSH_VALUE", "SETQ_G"}


def _split_module_code(fas) -> bytes:
    """Return the module-code tail of seg1 (after the resource INIT_DONE)."""
    data = getattr(fas, "sec2_data", b"") or b""
    idx = data.rfind(b"\x1c\x14\x01")
    return data[idx + 1:] if idx >= 0 else b""


def _stack_effect(inst) -> int:
    """Net stack delta of one module-code instruction (linear code only)."""
    name = inst.op_name
    if name in _PUSH_OPS:
        return 1
    if name in _POP_OPS:
        return -1
    if name in _ARITH_OPS or name == "CONS":
        return -1
    if name in ("BUILD_LIST", "BUILD_LIST_ALT"):
        return 1 - int(inst.operands[0])
    if name in ("USUBR", "FUNC"):
        return 1 - int(inst.operands[0])
    if name == "NIL":
        return 0
    raise ValueError(f"unsupported opcode in top-level code: {name}")


def _is_registration_start(insts, i) -> bool:
    """`JUMP 0; PUSH_G; SETQ_G` marks a function-registration group."""
    return (
        i + 2 < len(insts)
        and insts[i].op_name == "JUMP"
        and insts[i].operands
        and insts[i].operands[0] == 0
        and insts[i + 1].op_name == "PUSH_G"
        and insts[i + 2].op_name == "SETQ_G"
    )


def _extract_module_top(fas) -> Tuple[bytes, List]:
    """Split a module code into ``(top_level_bytes, top_level_instructions)``.

    Raises ``ValueError`` for module code that cannot be merged safely
    (nested defun, jumps, let/locals, commands are rejected by the caller).
    """
    mc = _split_module_code(fas)
    if not mc:
        return b"", []
    if not mc.startswith(b"\x14\x01\x00\x00\x00"):
        raise ValueError("module code does not start with a DEFUN header")
    dis = Disassembler(short_subr=False)
    insts = dis.disassemble(mc, fas.nsyms)
    if not insts or insts[0].op_name != "DEFUN":
        raise ValueError("module code is missing its DEFUN header")

    i = 1
    # Optional placeholder `PUSH_G <module_reg_count+1>; POP`.
    if (i + 1 < len(insts) and insts[i].op_name == "PUSH_G"
            and insts[i + 1].op_name == "POP"):
        i += 2

    top = bytearray()
    top_insts: List = []
    while i < len(insts):
        inst = insts[i]
        if inst.op_name == "END_DEFUN":
            break
        if _is_registration_start(insts, i):
            i += 3
            # optional `PUSH_G <c>; POP` (or the final `PUSH_G 1; END_DEFUN`)
            if i < len(insts) and insts[i].op_name == "PUSH_G":
                if i + 1 < len(insts) and insts[i + 1].op_name == "POP":
                    i += 2
                elif i + 1 < len(insts) and insts[i + 1].op_name == "END_DEFUN":
                    i += 1
                else:
                    i += 1
            continue
        if inst.op_name in _MODULE_UNSUPPORTED:
            raise ValueError(f"module code uses unsupported {inst.op_name}")
        # Remember the offset **inside the extracted block** (gaps from
        # removed registration groups make inst.offset unusable for slicing).
        top_insts.append((inst, len(top)))
        top.extend(mc[inst.offset:inst.offset + inst.size])
        i += 1
    return bytes(top), top_insts


def _balance_bytes(insts) -> bytes:
    """Trailing POPs needed to keep the top-level block stack-neutral."""
    depth = 0
    for inst, _off in insts:
        depth += _stack_effect(inst)
        if depth < 0:
            raise ValueError(f"stack underflow at {inst.op_name}")
    return b"\x0a" * depth


def _remap_module_top(
    top: bytes, insts, file_map: Dict[str, int], merged_map: Dict[str, int]
) -> bytes:
    """Rewrite top-level gvar/function slots into the merged module table."""
    inv = {slot: name for name, slot in file_map.items()}
    out = bytearray()
    for inst, off in insts:
        name = inst.op_name
        if name in _SLOT_OPS:
            idx = int(inst.operands[0])
            sym = inv.get(idx)
            if sym is None:
                raise ValueError(f"unmapped module slot {idx} ({name})")
            new = merged_map.get(sym) or merged_map.get(sym.upper())
            if new is None:
                raise ValueError(f"symbol {sym!r} missing from merged module table")
            out += encode_op_u16(inst.opcode, new)
        elif name in ("USUBR", "FUNC"):
            argc = int(inst.operands[0])
            idx = int(inst.operands[1])
            sym = inv.get(idx)
            if sym is None:
                raise ValueError(f"unmapped module function slot {idx} ({name})")
            new = merged_map.get(sym) or merged_map.get(sym.upper())
            if new is None:
                raise ValueError(f"function {sym!r} missing from merged module table")
            flags = int(inst.operands[2]) if len(inst.operands) > 2 else 0
            if inst.size >= 6:
                out += encode_func(argc, new, flags)
            else:
                out += encode_usubr(argc, new, flags)
        else:
            out += top[off:off + inst.size]
    return bytes(out)


def _build_module_code_with_top(
    n_funcs: int,
    func_order: List[str],
    merged_map: Dict[str, int],
    top_level: bytes,
) -> bytes:
    """Rebuild the module code with one registration block + top-level bytes.

    Mirrors the compiler's layout for a mixed unit:
    ``DEFUN头; PUSH_G <注册数+1>; POP; [每函数注册组]; <顶层语句>; PUSH_G 1; END``
    (top-level statements run after registration, so they may call any merged
    function; their relative order is preserved).
    """
    out = bytearray(b"\x14\x01\x00\x00\x00")
    if n_funcs == 0:
        out += top_level
        out += b"\x16"
        return bytes(out)

    reg_count = len(merged_map)
    top_count = reg_count - n_funcs
    # Placeholder: PUSH_G <module registration count + 1>; POP
    out += b"\x09" + struct.pack("<H", reg_count + 1) + b"\x0a"
    for i, fname in enumerate(func_order):
        c = merged_map.get(str(fname)) or merged_map.get(str(fname).upper())
        if c is None:
            raise ValueError(f"function {fname!r} missing from merged module table")
        b = 2 * n_funcs + top_count + 1 - i
        out += b"\x57\x00\x00\x00\x00"
        out += b"\x09" + struct.pack("<H", b) + b"\x06" + struct.pack("<H", c)
        if i < n_funcs - 1:
            out += b"\x09" + struct.pack("<H", c) + b"\x0a"
        else:
            out += top_level
            out += b"\x09\x01\x00\x16"
    return bytes(out)


def _data_items_of(fas) -> List[Tuple]:
    """按注册顺序提取符号槽条目（CAD 紧凑格式下直接用 symbol_slots）。"""
    if getattr(fas, "symbol_slots", None):
        items = [item for item in fas.symbol_slots if _is_data_item(item)]
        if _fas_is_stub(fas):
            # stub 符号表需含内建（如 strcat），symbol_slots 可能缺失
            try:
                from core.fas_core import build_mvar_tables
                _, fg = build_mvar_tables(fas.sec2_data, fas.nsyms)
                seen = {_make_item_key(it) for it in items}
                for v in fg:
                    if isinstance(v, tuple) and len(v) == 2 and v[0] in ("SYMBOL", "STRING"):
                        it = (v[0], str(v[1]))
                        if _make_item_key(it) not in seen:
                            seen.add(_make_item_key(it))
                            items.append(it)
            except Exception:
                pass
        return items
    return _data_items(fas.resource_items)


def _extract_functions(fas) -> List[Tuple[str, int]]:
    """提取函数目录。优先用资源重建的目录；紧凑格式用 seg0 DEFUN 头。"""
    if fas.function_catalog:
        return fas.function_catalog
    if not getattr(fas, "symbol_slots", None):
        return []

    # 紧凑 stub 格式：DEFCODE 序列 (PUSH_INT8 <off> + SYMBOL <name>)
    is_stub = _fas_is_stub(fas)
    if is_stub:
        items = fas.resource_items_with_offsets
        stub_funcs: List[Tuple[str, int]] = []
        for i in range(1, len(items)):
            name_item = items[i][1]
            off_item = items[i - 1][1]
            if (
                isinstance(name_item, tuple) and len(name_item) == 2 and name_item[0] == "SYMBOL"
                and isinstance(off_item, tuple) and len(off_item) == 2 and off_item[0] in ("INT8", "INT32")
            ):
                raw_name = str(name_item[1])
                if raw_name and any(ch.isalpha() for ch in raw_name):
                    stub_funcs.append((raw_name, int(off_item[1])))
        if stub_funcs:
            return stub_funcs

    disassembler = Disassembler(short_subr=use_short_subr(fas.bytecode, fas.nsyms, fas.function_catalog, len(fas.symbol_slots)))
    insts = disassembler.disassemble(fas.bytecode, fas.nsyms,
                                     sym_count=len(fas.symbol_slots) if is_stub else None)
    funcs: List[Tuple[str, int]] = []
    for inst in insts:
        if inst.op_name != "DEFUN" or len(inst.operands) < 2:
            continue
        gv = inst.operands[0] | (inst.operands[1] << 8)
        if 0 <= gv < len(fas.symbol_slots):
            val = fas.symbol_slots[gv]
            if isinstance(val, tuple) and len(val) == 2 and val[0] == "SYMBOL":
                funcs.append((str(val[1]), inst.offset))
    return funcs


def link_fas(input_paths: List[str], output_path: str, verbose: bool = False,
             encoding: str = 'ansi', date=None, salt=None,
             merge_top_level: bool = False) -> str:
    if len(input_paths) < 2:
        raise ValueError("Need at least 2 input .fas files to link")

    if verbose:
        print(f'Linking {len(input_paths)} files: {", ".join(input_paths)}')

    # ── Parse all inputs ──
    parsed = []
    for fpath in input_paths:
        parser = Fas4Parser()
        fas = parser.parse(fpath)
        parsed.append(fas)
        if verbose:
            di = len(_data_items_of(fas))
            fc = len(fas.function_catalog)
            print(f"  {os.path.basename(fpath)}: {di} data items, " f"{fc} functions, {len(fas.bytecode)} bytes code")

    # ── Build global data entries (deduped, order-preserving) ──
    global_data = _collect_global_data(parsed)

    # ── Build global function catalog (first-definition-wins) ──
    seen_funcs: Set[str] = set()
    owners: Dict[str, int] = {}
    global_func_catalog: List[Tuple[str, int]] = []
    for file_idx, fas in enumerate(parsed):
        # _extract_functions 返回 DEFCODE 逆序，反转恢复源码定义顺序
        # （模块代码/DEFUN 头槽依赖源码顺序）
        for fname, foff in reversed(_extract_functions(fas)):
            if fname in seen_funcs:
                _warn(
                    f'function name collision: "{fname}" defined in multiple files; '
                    f"keeping the first definition (file #{owners[fname]})"
                )
                continue
            seen_funcs.add(fname)
            owners[fname] = file_idx
            global_func_catalog.append((fname, foff))

    if verbose:
        print(f"  Merged: {len(global_data)} data entries, " f"{len(global_func_catalog)} functions")

    # ── Build SymbolTable from global data entries ──
    # 符号顺序复刻 cmd 编译器（derive_symbol_names）：函数名逆序 +
    # 函数逆序收集函数体符号（跨函数引用用重复槽）。这是 CAD 兼容关键——
    # build_module_code 的 PUSH_G idx 依赖该布局（跨调用函数须在
    # 共享内建之后的固定槽，否则 CAD 加载后绑定错/调用卡死）。
    symtab = SymbolTable()
    _fidx = {id(fas): idx for idx, fas in enumerate(parsed)}
    _func_order: List[str] = []
    # 函数名按源码逆序：文件逆序 + 文件内 DEFCODE 顺序（_extract_functions = 逆序）
    for fas in reversed(parsed):
        for fname, _ in _extract_functions(fas):
            if owners.get(fname) != _fidx[id(fas)]:
                continue  # 重复定义：仅首次定义参与
            _func_order.append(fname)
            symtab.get_or_add(fname)
    _func_names = set(_func_order)

    # 顶层表达式用到的符号/字符串必须进入**模块注册段**（模块代码按该表
    # 编址）。只合顶层时启用；纯函数链接保持原有布局（golden 字节不变）。
    _top_symbols: List[Tuple[str, str]] = []
    _top_symbol_count = 0
    if merge_top_level:
        _seen_top: Set[str] = set()
        for _fas in parsed:
            _file_funcs_upper = {
                str(f).upper() for f, _ in _extract_functions(_fas)
            }
            _type_map: Dict[str, Tuple[str, str]] = {}
            for _t, _v in _fas.symbol_slots:
                _key = str(_v).upper()
                if _t == "STRING" or _key not in _type_map:
                    _type_map[_key] = (_t, str(_v))
            for _sym in build_module_gvar_map(_fas.sec2_data):
                if _sym in _file_funcs_upper or _sym in _seen_top:
                    continue
                _seen_top.add(_sym)
                _top_symbols.append(_type_map.get(_sym, ("SYMBOL", _sym)))
        for _t, _v in _top_symbols:
            if _t == "STRING":
                if _v not in symtab.name_to_idx:
                    symtab.add_string(_v)
            elif _v not in symtab.name_to_idx:
                symtab.get_or_add(_v)
        _top_symbol_count = len(_top_symbols)

    def _file_body_slots(fas):
        """文件符号槽：去掉前部（模块注册函数名）与尾部（模块重复）区域。

        返回 (body, args)：单函数文件分离「函数体符号 + 参数」（单函数 slots
        布局 = 函数名 + 体符号 + 参数，参数为 body 末尾 argc 个）；多函数文件
        参数穿插在各函数体内，不分离（返回全部 body，args 为空）。
        """
        file_funcs = [f for f, _ in _extract_functions(fas)]
        slots = fas.symbol_slots
        # 模块注册段（函数名 + 顶层符号）不进入函数体符号：
        # 顶层合并时按解析出的模块注册宽度跳过，否则沿用「函数数个」。
        if merge_top_level:
            try:
                start = len(build_module_gvar_map(fas.sec2_data))
            except Exception:
                start = len(file_funcs)
        else:
            start = len(file_funcs)
        end = len(slots) - len(file_funcs)
        if end < start:
            end = len(slots)
        body = []
        for s in slots[start:end]:
            if _is_data_item(s):
                body.append((s[0], str(s[1])))
        if len(file_funcs) == 1:
            argc = _total_argc(fas)
            if argc > 0 and len(body) >= argc:
                args = body[-argc:]
                body = body[:-argc]
            else:
                args = []
            return body, args
        return body, []

    def _total_argc(fas) -> int:
        """文件的全部参数数（DEFUN 头 argc 之和）。"""
        from decompiler.fas4_decompiler import Disassembler as _Dis
        try:
            _d = _Dis(short_subr=_fas_is_stub(fas))
            _insts = _d.disassemble(fas.bytecode, fas.nsyms)
        except Exception:
            return 0
        total = 0
        for _in in _insts:
            if _in.op_name == "DEFUN" and len(_in.operands) >= 1:
                total += int(_in.operands[0])
        return total

    def _skip_dup_file(fas) -> bool:
        _file_funcs = [f for f, _ in _extract_functions(fas)]
        return bool(_file_funcs) and all(owners.get(f) != _fidx[id(fas)] for f in _file_funcs)

    # 函数体符号：按文件 slots 顺序（slots 已是 cmd derive_symbol_names 顺序），
    # 文件逆序合并；跨函数引用用重复槽（add_force 去重）。参数分离：共享参数
    # （跨文件同名）最后统一注册，非共享参数紧跟所属文件体符号。
    _forced: Set[str] = set()
    _shared_args: Set[str] = set()
    _file_body: List[List[Tuple[str, str]]] = []
    _file_args: List[List[Tuple[str, str]]] = []
    # 先收集全部体符号 + 参数，统计共享参数
    _arg_usage: Dict[str, int] = {}
    for fas in reversed(parsed):
        if _skip_dup_file(fas):
            continue
        _body, _args = _file_body_slots(fas)
        _file_body.append(_body)
        _file_args.append(_args)
        for _t, _v in _args:
            _arg_usage[_v] = _arg_usage.get(_v, 0) + 1
    _shared_args = {a for a, c in _arg_usage.items() if c > 1}
    for _bi, _body in enumerate(_file_body):
        for it_type, it_val in _body:
            if it_type == "SYMBOL":
                nm = str(it_val)
                if nm in _func_names and nm not in _forced:
                    symtab.add_force(nm)
                    _forced.add(nm)
                elif nm not in _func_names and nm not in symtab.name_to_idx:
                    symtab.get_or_add(nm)
            elif it_type == "STRING":
                if str(it_val) not in symtab.name_to_idx:
                    symtab.add_string(str(it_val))
        # 非共享参数紧跟所属文件体符号
        for it_type, it_val in _file_args[_bi]:
            if it_val not in _shared_args and it_type == "SYMBOL" and it_val not in symtab.name_to_idx:
                symtab.get_or_add(it_val)
            elif it_val not in _shared_args and it_type == "STRING" and str(it_val) not in symtab.name_to_idx:
                symtab.add_string(str(it_val))
    # 共享参数最后统一注册（CAD 多函数布局：体符号 → 非共享参数 → 共享参数）
    for _t, _v in [(t, v) for _bi in range(len(_file_args)) for t, v in _file_args[_bi]]:
        if _v in _shared_args:
            if _t == "SYMBOL" and _v not in symtab.name_to_idx:
                symtab.get_or_add(_v)
            elif _t == "STRING" and _v not in symtab.name_to_idx:
                symtab.add_string(_v)
    # INT/REAL 常量（symbol_slots 不含）按 global_data 补充
    for item_type, item_val in global_data:
        if item_type in ("INT8", "INT32", "INT"):
            symtab.add_int(int(item_val))
        elif item_type == "REAL":
            symtab.add_real(float(item_val))

    # ── 初步资源段：确定合并后 gvar 槽（stub 字节码索引用槽-1） ──
    _pre_func_offsets = {fname: foff for fname, foff in global_func_catalog}
    for fname, foff in global_func_catalog:
        symtab.add_func_ref(fname, foff)
    _pre_module_code = build_module_code(len(_pre_func_offsets))
    _pre_sec1 = ResourceBuilder(symtab, encoding=encoding).build(
        _pre_func_offsets, module_code=_pre_module_code, stub_format=True,
        top_level_count=_top_symbol_count,
    )
    # 模块注册表（符号名 → gvar 槽）：模块代码里的槽引用按此表编址。
    # 顶层表达式的符号已在 symtab 中（global_data），所以该表在最终 seg1 中不变。
    try:
        _merged_module_map = build_module_gvar_map(_pre_sec1)
    except Exception:
        _merged_module_map = {}
    _pre_nsyms = len(symtab.entries)
    from core.fas_core import build_mvar_tables
    try:
        _, _pre_fg = build_mvar_tables(_pre_sec1, _pre_nsyms)
    except Exception:
        _pre_fg = []
    _pre_gvar: Dict[str, int] = {}
    for _i, _v in enumerate(_pre_fg):
        if isinstance(_v, tuple) and len(_v) == 2 and _v[0] in ("SYMBOL", "STRING"):
            _pre_gvar.setdefault(str(_v[1]), _i)
    # 合并 symbol_slots（资源注册顺序）：参数绑定/读取槽在 gvar 表外时
    # 用符号槽 - 1（CAD 实测）。从初步资源段解析符号注册顺序。
    _pre_slot: Dict[str, int] = {}
    try:
        _items, _, _syms = Fas4Parser().parse_resource_stream(_pre_sec1)
        for _i, _s in enumerate(_syms):
            _pre_slot.setdefault(str(_s), _i)
    except Exception:
        pass

    # ── Build index maps for each file ──
    # ── Patch bytecode ──
    merged_code = bytearray()
    disassembler = Disassembler()
    merged_nsyms = len(symtab.entries) - len(global_func_catalog) + 1

    for file_idx, fas in enumerate(parsed):
        # 全重复文件（所有函数均非首次定义）跳过：字节码不合并，
        # 避免「3 个字节码函数 + 2 个目录」不一致导致 CAD 加载错。
        _file_funcs = [f for f, _ in _extract_functions(fas)]
        if _file_funcs and all(owners.get(f) != file_idx for f in _file_funcs):
            continue
        short_subr = _fas_is_stub(fas)
        if short_subr:
            # stub 字节码索引 = gvar 槽-1：按 file fg（gvar 表）还原符号，
            # 再映射到合并 gvar 槽-1。
            sym_by_idx = {}
            try:
                from core.fas_core import build_mvar_tables as _bmt
                _, _ffg = _bmt(fas.sec2_data, fas.nsyms)
            except Exception:
                _ffg = []
            # fg（gvar 槽-1）优先：USUBR/符号引用按 CAD gvar 槽-1 编址
            for _i, _v in enumerate(_ffg):
                if isinstance(_v, tuple) and len(_v) == 2 and _v[0] in ("SYMBOL", "STRING"):
                    sym_by_idx[_i - 1] = str(_v[1])
            # slots 索引补充：单函数 PUSH_G（entries/symbol_slots 索引）与字符串
            for i, s in enumerate(fas.symbol_slots):
                if _is_data_item(s) and s[0] in ("SYMBOL", "STRING"):
                    sym_by_idx.setdefault(i, str(s[1]))
            sm = {}
            sm_slot = {}
            for i, sym in sym_by_idx.items():
                if sym in _pre_gvar:
                    sm[i] = _pre_gvar[sym] - 1
                    for j, (et, ev) in enumerate(symtab.entries):
                        if et in ("SYMBOL", "STRING") and str(ev) == sym:
                            sm_slot[i] = j
                            break
                else:
                    # fg 外（nsyms 截断）符号：用合并 symtab 槽，反编译 fallback 到 symbol_slots
                    for j, (et, ev) in enumerate(symtab.entries):
                        if et in ("SYMBOL", "STRING") and str(ev) == sym:
                            sm[i] = j
                            sm_slot[i] = j
                            break
        else:
            sm = _build_local_data_map(global_data, fas)
        disassembler.short_subr = short_subr
        instructions = disassembler.disassemble(fas.bytecode, fas.nsyms,
                                                sym_count=len(fas.symbol_slots) if short_subr else None)
        patched = bytearray()
        # stub 多文件合并：参数绑定/读取槽 = 参数符号在**合并 gvar 表**的槽 - 1
        # （CAD 实测：mix 参数 A/B 合并 gvar 槽 5/4 → 操作数 4/3；square 参数 X
        # 超出合并 gvar 表 → 合并符号槽 7 - 1 = 6）。符号名经 sym_by_idx
        # （文件侧 fg 槽-1 / slots 索引 → 名）反查后映射 _pre_gvar，表外符号
        # 用合并符号槽（symtab.entries 索引）减 1。
        cur_argc = 0          # 全部参数数（DEFUN 后到 INIT_ARGS 的绑定）
        in_param_bind = False
        cur_arg_rev = 0       # 当前参数在声明逆序中的索引（argc-1 递减）

        def _param_slot(idx, arg_rev):
            """文件侧参数槽 idx → 合并后操作数。

            参数绑定 PUSH_G 操作数：单函数文件 = 符号槽，多函数文件 = 符号槽-1
            （CAD 实测：foo 参数 X 符号槽 4 → 操作数 3）。从文件 symbol_slots
            反查符号名，再映射到合并 gvar 槽-1（表内）或 nsyms-1-arg_rev（表外）。
            """
            multi = len(_extract_functions(fas)) > 1
            file_slot = idx + 1 if multi else idx
            sym = None
            if 0 <= file_slot < len(fas.symbol_slots):
                s = fas.symbol_slots[file_slot]
                if isinstance(s, tuple) and len(s) == 2 and s[0] in ("SYMBOL", "STRING"):
                    sym = str(s[1])
            if sym is None:
                sym = sym_by_idx.get(idx)
            if sym is not None and sym in _pre_gvar:
                return _pre_gvar[sym] - 1
            # 表外参数：逆序槽（nsyms - 1 - arg_rev）
            return merged_nsyms - 1 - arg_rev

        for inst in instructions:
            if inst.op_name == "DEFUN":
                # 0x14 头 4 字节：b1/b2/b3 与 b4；参数绑定数由 DEFUN 头 argc
                # （b1）推得——参数绑定在 DEFUN 与 INIT_ARGS 之间，此时尚未
                # 遇到 INIT_ARGS，需用 b1 作为当前函数 argc。
                b1 = inst.operands[0] if len(inst.operands) > 0 else 0
                b4 = inst.operands[3] if len(inst.operands) > 3 else 0
                in_param_bind = (b1 > 0) or (b4 == 1)
                cur_argc = b1
                cur_arg_rev = 0
                bc = fas.bytecode[inst.offset : inst.offset + inst.size]
            elif short_subr and inst.op_name == "PUSH_G" and in_param_bind:
                # 参数绑定（DEFUN 后到 INIT_ARGS，含 &optional/&rest）：
                # 操作数 = 合并 gvar 槽 - 1（表内）；表外参数按参数序（从 0
                # 递增）用 nsyms - 1 - arg_rev。CAD 实测：add 参数 A（第一个）
                # 绑定 nsyms-1、B（第二个）nsyms-2。
                idx = inst.operands[0]
                new_idx = _param_slot(idx, cur_arg_rev)
                cur_arg_rev += 1
                bc = bytes([0x09, new_idx & 0xFF, (new_idx >> 8) & 0xFF])
            elif short_subr and inst.op_name == "INIT_ARGS":
                # 参数绑定区结束；INIT_ARGS = 2*全部参数数 + 1
                val = inst.operands[0] if inst.operands else 0
                cur_argc = (val - 1) // 2 if val else 0
                in_param_bind = False
                cur_arg_rev = 0
                bc = fas.bytecode[inst.offset : inst.offset + inst.size]
            elif short_subr and inst.op_name == "PUSH_VALUE" and inst.size > 1 and cur_argc:
                # 参数读取：idx 在 [nsyms-全部参数, nsyms-1] 区间即参数
                idx = inst.operands[0]
                if fas.nsyms - cur_argc <= idx < fas.nsyms:
                    arg_rev = fas.nsyms - 1 - idx  # 参数逆序索引（读槽从高到低）
                    new_idx = _param_slot(idx, arg_rev)
                    bc = bytes([0x03, new_idx & 0xFF, (new_idx >> 8) & 0xFF])
                else:
                    skip_single = False
                    if _needs_symbol_patch(inst.op_name) and not skip_single:
                        new_ops = _patch_operands(inst, sm, sm_slot)
                        bc = _encode_with_opcode(inst.opcode, inst.op_name, new_ops, short_subr=short_subr)
                    else:
                        bc = fas.bytecode[inst.offset : inst.offset + inst.size]
            else:
                # stub 格式 DEFUN 头为 argc 编码，无符号索引，不需 patch；
                # 单字节 PUSH_VALUE[0]（调用后清理）同样原样保留。
                skip_defun = short_subr and inst.op_name == "DEFUN"
                skip_single = short_subr and inst.op_name == "PUSH_VALUE" and inst.size == 1
                if _needs_symbol_patch(inst.op_name) and not skip_defun and not skip_single:
                    new_ops = _patch_operands(inst, sm, sm_slot)
                    bc = _encode_with_opcode(inst.opcode, inst.op_name, new_ops, short_subr=short_subr)
                else:
                    bc = fas.bytecode[inst.offset : inst.offset + inst.size]
            patched.extend(bc)

        if file_idx > 0:
            # 多函数合并：函数间插入 END_DEFUN 分隔符（CAD stub 格式为单个
            # `16`，实测 t01_math_cad.fas / link_ref.fas 两函数间仅 `16`）。
            merged_code.extend(b'\x16')
        merged_code.extend(patched)

    # ── Recalculate actual function catalog offsets ──
    # 只更新「首次定义」文件的函数偏移，重复定义不覆盖（避免指向错误副本）。
    final_offset = 0
    for file_idx, fas in enumerate(parsed):
        _file_funcs = [f for f, _ in _extract_functions(fas)]
        if _file_funcs and all(owners.get(f) != file_idx for f in _file_funcs):
            continue  # 全重复文件已跳过合并
        for i, (fname, foff) in enumerate(_extract_functions(fas)):
            if owners.get(fname) != file_idx:
                continue
            actual_off = final_offset + foff
            for j, (gfname, _) in enumerate(global_func_catalog):
                if gfname == fname:
                    global_func_catalog[j] = (gfname, actual_off)
                    break
        final_offset += len(fas.bytecode) + (1 if file_idx < len(parsed) - 1 else 0)

    # ── Write output ──
    seg0 = bytes(merged_code)
    func_offsets = {fname: foff for fname, foff in global_func_catalog}
    for fname, foff in func_offsets.items():
        symtab.add_func_ref(fname, foff)
    # ── Top-level expressions (seg1 module code) ──
    merged_top = bytearray()
    _top_detected = False
    for _path, _fas in zip(input_paths, parsed):
        if _skip_dup_file(_fas):
            continue
        try:
            _top, _top_insts = _extract_module_top(_fas)
        except ValueError as exc:
            if merge_top_level:
                raise ValueError(
                    f"cannot merge top-level expressions from "
                    f"{os.path.basename(_path)}: {exc}"
                ) from exc
            continue
        if not _top_insts:
            continue
        _top_detected = True
        if not merge_top_level:
            continue
        if not _merged_module_map:
            raise ValueError("cannot read the merged module registration table")
        _file_map = build_module_gvar_map(_fas.sec2_data)
        merged_top += _remap_module_top(
            _top, _top_insts, _file_map, _merged_module_map
        )
        merged_top += _balance_bytes(_top_insts)

    if _top_detected and not merge_top_level:
        _warn(
            "input .fas contains top-level expressions; they are DROPPED "
            "(pass --merge-top-level to merge them)"
        )

    if merged_top:
        module_code = _build_module_code_with_top(
            len(func_offsets),
            [f for f, _ in global_func_catalog],
            _merged_module_map,
            bytes(merged_top),
        )
    else:
        module_code = build_module_code(len(func_offsets))
    resource = ResourceBuilder(symtab, encoding=encoding)
    nsyms = len(symtab.entries) - len(func_offsets) + 1
    seg1 = resource.build(func_offsets, module_code=module_code,
                          total_size=len(seg0) + 1, stub_format=True,
                          top_level_count=_top_symbol_count)
    # items 与 CAD 编译器一致：2 * 模块注册数 + 2。CAD 加载时按 items 处理
    # GVARINIT，偏小会遗漏函数注册（实测 2 函数 → 6，而 count_resource_records
    # 仅 4）。合并顶层表达式时 count_resource_records 会更大，max 兜底。
    min_items = 2 * len(func_offsets) + 2
    sec2_items = max(count_resource_records(seg1), min_items)
    writer = FasWriter(symtab, date=date, salt=salt)
    writer.write(output_path, seg0, seg1, sec2_items=sec2_items,
                 nsyms=nsyms, compact=True)

    if verbose:
        total = os.path.getsize(output_path)
        print(f"  Output: {output_path} ({total} bytes)")

    return output_path
