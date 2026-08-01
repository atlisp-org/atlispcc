"""FAS4 Linker — merge multiple .fas files into one, resolving cross-file symbols."""

import os
import sys
from typing import List, Dict, Tuple, Set, Any

from fas4_decompiler import Fas4Parser, Disassembler
from compiler.symbol_table import SymbolTable
from compiler.resource_builder import ResourceBuilder, build_module_code, count_resource_records
from compiler.fas_writer import FasWriter
from compiler.opcodes import (
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
from fas4_decompiler import is_compact_stub

_DATA_TYPES = {"SYMBOL", "STRING", "INT8", "INT32", "REAL"}

_SYM_REF_INSTS = {"PUSH_VALUE", "PUSH_G", "PUSH_GLOBAL", "SETQ_G"}
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


def _patch_operands(inst, file_sym_map: Dict[int, int]) -> List:
    name = inst.op_name
    ops = list(inst.operands)
    if not ops:
        return ops
    if name in _SYM_REF_INSTS:
        local_idx = ops[0]
        if local_idx in file_sym_map:
            ops[0] = file_sym_map[local_idx]
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
        return encode_op_u32(opcode, int(operands[0]))
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


def _data_items_of(fas) -> List[Tuple]:
    """按注册顺序提取符号槽条目（CAD 紧凑格式下直接用 symbol_slots）。"""
    if getattr(fas, "symbol_slots", None):
        return [item for item in fas.symbol_slots if _is_data_item(item)]
    return _data_items(fas.resource_items)


def _extract_functions(fas) -> List[Tuple[str, int]]:
    """提取函数目录。优先用资源重建的目录；紧凑格式用 seg0 DEFUN 头。"""
    if fas.function_catalog:
        return fas.function_catalog
    if not getattr(fas, "symbol_slots", None):
        return []

    # 紧凑 stub 格式：DEFCODE 序列 (PUSH_INT8 <off> + SYMBOL <name>)
    is_stub = is_compact_stub(fas.bytecode, fas.function_catalog, len(fas.symbol_slots))
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

    disassembler = Disassembler(short_subr=is_stub)
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


def link_fas(input_paths: List[str], output_path: str, verbose: bool = False) -> str:
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
        for fname, foff in _extract_functions(fas):
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

    # ── Build index maps for each file ──
    # ── Patch bytecode ──
    merged_code = bytearray()
    disassembler = Disassembler()

    for file_idx, fas in enumerate(parsed):
        sm = _build_local_data_map(global_data, fas)
        short_subr = is_compact_stub(fas.bytecode, fas.function_catalog, len(fas.symbol_slots))
        disassembler.short_subr = short_subr
        instructions = disassembler.disassemble(fas.bytecode, fas.nsyms,
                                                sym_count=len(fas.symbol_slots) if short_subr else None)
        patched = bytearray()

        for inst in instructions:
            # stub 格式 DEFUN 头为 argc 编码，无符号索引，不需 patch；
            # 单字节 PUSH_VALUE[0]（调用后清理）同样原样保留。
            skip_defun = short_subr and inst.op_name == "DEFUN"
            skip_single = short_subr and inst.op_name == "PUSH_VALUE" and inst.size == 1
            if _needs_symbol_patch(inst.op_name) and not skip_defun and not skip_single:
                new_ops = _patch_operands(inst, sm)
                bc = _encode_with_opcode(inst.opcode, inst.op_name, new_ops, short_subr=short_subr)
            else:
                bc = fas.bytecode[inst.offset : inst.offset + inst.size]
            patched.extend(bc)

        merged_code.extend(patched)

    # ── Recalculate actual function catalog offsets ──
    # 只更新「首次定义」文件的函数偏移，重复定义不覆盖（避免指向错误副本）。
    final_offset = 0
    for file_idx, fas in enumerate(parsed):
        for i, (fname, foff) in enumerate(_extract_functions(fas)):
            if owners.get(fname) != file_idx:
                continue
            actual_off = final_offset + foff
            for j, (gfname, _) in enumerate(global_func_catalog):
                if gfname == fname:
                    global_func_catalog[j] = (gfname, actual_off)
                    break
        final_offset += len(fas.bytecode)

    # ── Build SymbolTable from global data entries ──
    symtab = SymbolTable()
    for item_type, item_val in global_data:
        if item_type == "SYMBOL":
            symtab.get_or_add(item_val)
        elif item_type == "STRING":
            symtab.add_string(item_val)
        elif item_type in ("INT8", "INT32", "INT"):
            symtab.add_int(int(item_val))
        elif item_type == "REAL":
            symtab.add_real(float(item_val))

    # ── Build func_offsets from global catalog ──
    func_offsets: Dict[str, int] = {}
    for fname, foff in global_func_catalog:
        func_offsets[fname] = foff
        symtab.add_func_ref(fname, foff)

    # ── Write output ──
    seg0 = bytes(merged_code)
    module_code = build_module_code(len(func_offsets))
    resource = ResourceBuilder(symtab)
    seg1 = resource.build(func_offsets, module_code=module_code)
    writer = FasWriter(symtab)
    writer.write(output_path, seg0, seg1, sec2_items=count_resource_records(seg1))

    if verbose:
        total = os.path.getsize(output_path)
        print(f"  Output: {output_path} ({total} bytes)")

    return output_path
