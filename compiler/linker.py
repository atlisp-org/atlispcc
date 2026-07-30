"""FAS4 Linker — merge multiple .fas files into one, resolving cross-file symbols."""
import os
from typing import List, Dict, Tuple, Set, Any

from fas4_decompiler import Fas4Parser, Disassembler
from compiler.symbol_table import SymbolTable
from compiler.resource_builder import ResourceBuilder
from compiler.fas_writer import FasWriter
from compiler.opcodes import (
    OPCODE_TO_NAME, OPCODE_FORMAT,
    encode_op_u16, encode_op_noarg,
    encode_op_u8, encode_op_s32, encode_op_u32, encode_bb,
    encode_usubr, encode_func, encode_defun, encode_eval, encode_real,
)


_DATA_TYPES = {'SYMBOL', 'STRING', 'INT8', 'INT32', 'REAL'}

_SYM_REF_INSTS = {'PUSH_VALUE', 'PUSH_G', 'PUSH_GLOBAL', 'SETQ_G'}
_FUNC_REF_INSTS = {'FUNC', 'USUBR'}


def _is_data_item(item: Tuple) -> bool:
    """True if item is a data entry that occupies a slot in the symbol table."""
    return len(item) >= 2 and item[0] in _DATA_TYPES


def _data_items(items: List[Tuple]) -> List[Tuple]:
    return [it for it in items if _is_data_item(it)]


def _make_item_key(item: Tuple) -> str:
    return item[0] + ':' + str(item[1])


def _collect_global_data(parsed_fas_list: list) -> List[Tuple]:
    """Merge all data entries across files, preserving first-occurrence order."""
    seen: Set[str] = set()
    merged: List[Tuple] = []
    for fas in parsed_fas_list:
        for item in _data_items(fas.resource_items):
            key = _make_item_key(item)
            if key not in seen:
                seen.add(key)
                merged.append(item)
    return merged


def _build_local_data_map(global_data: List[Tuple],
                          local_items: List[Tuple]) -> Dict[int, int]:
    """Build local→global index map for data entries of one file."""
    g_by_key: Dict[str, int] = {}
    for g_idx, item in enumerate(global_data):
        key = _make_item_key(item)
        if key not in g_by_key:
            g_by_key[key] = g_idx
    local_data = _data_items(local_items)
    local_map: Dict[int, int] = {}
    for l_idx, item in enumerate(local_data):
        key = _make_item_key(item)
        if key in g_by_key:
            local_map[l_idx] = g_by_key[key]
    return local_map


def _build_func_map(global_catalog: List[Tuple[str, int]],
                    local_catalog: List[Tuple[str, int]],
                    global_data_count: int) -> Dict[int, int]:
    """Build local→global index map for function catalog entries."""
    g_by_name: Dict[str, int] = {}
    for g_idx, (fname, _) in enumerate(global_catalog):
        g_by_name[fname] = g_idx
    local_map: Dict[int, int] = {}
    for l_idx, (fname, _) in enumerate(local_catalog):
        if fname in g_by_name:
            local_slot = len(_data_items(local_resource_items)) + l_idx
            global_slot = global_data_count + g_by_name[fname]
            local_map[local_slot] = global_slot
    return local_map


def _needs_symbol_patch(name: str) -> bool:
    return name in _SYM_REF_INSTS or name in _FUNC_REF_INSTS or name == 'DEFUN'


def _patch_operands(inst, file_sym_map: Dict[int, int],
                    file_func_map: Dict[int, int]) -> List:
    name = inst.op_name
    ops = list(inst.operands)
    if not ops:
        return ops
    if name in _SYM_REF_INSTS:
        local_idx = ops[0]
        if local_idx in file_sym_map:
            ops[0] = file_sym_map[local_idx]
        elif local_idx in file_func_map:
            ops[0] = file_func_map[local_idx]
    elif name in _FUNC_REF_INSTS:
        if len(ops) >= 2:
            local_idx = ops[1]
            if local_idx in file_sym_map:
                ops[1] = file_sym_map[local_idx]
            elif local_idx in file_func_map:
                ops[1] = file_func_map[local_idx]
    elif name == 'DEFUN':
        if len(ops) >= 4:
            gv = ops[0] | (ops[1] << 8)
            if gv in file_sym_map:
                new_gv = file_sym_map[gv]
            elif gv in file_func_map:
                new_gv = file_func_map[gv]
            else:
                new_gv = gv
            ops[0] = new_gv & 0xFF
            ops[1] = (new_gv >> 8) & 0xFF
    return ops


def _encode_with_opcode(opcode: int, name: str, operands: List) -> bytes:
    fmt = OPCODE_FORMAT.get(opcode, '')
    if fmt == '':
        return encode_op_noarg(opcode)
    elif fmt == '1':
        return encode_op_u8(opcode, int(operands[0]))
    elif fmt == '2':
        return encode_op_u16(opcode, int(operands[0]))
    elif fmt == '4':
        return encode_op_u32(opcode, int(operands[0]))
    elif fmt == 's4':
        return encode_op_s32(opcode, int(operands[0]))
    elif fmt == 'bb':
        return encode_bb(opcode, int(operands[0]), int(operands[1]))
    elif fmt == 'u':
        return encode_usubr(int(operands[0]), int(operands[1]),
                           int(operands[2]) if len(operands) > 2 else 0)
    elif fmt == 'f':
        return encode_func(int(operands[0]), int(operands[1]),
                          int(operands[2]) if len(operands) > 2 else 0)
    elif fmt == 'h':
        gv, off = int(operands[0]), int(operands[1]) if len(operands) > 1 else 0
        return encode_defun(gv, off)
    elif fmt == 'e':
        return encode_eval(int(operands[0]), int(operands[1]) if len(operands) > 1 else 0)
    elif fmt == 'z':
        return bytes([opcode]) + str(operands[0]).encode('ascii') + b'\x00'
    else:
        raise ValueError(f'Unknown format {fmt} for {name} (op={opcode:02x})')


def _data_items_of(fas) -> List[Tuple]:
    return _data_items(fas.resource_items)


def link_fas(input_paths: List[str], output_path: str, verbose: bool = False) -> str:
    if len(input_paths) < 2:
        raise ValueError('Need at least 2 input .fas files to link')

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
            print(f'  {os.path.basename(fpath)}: {di} data items, '
                  f'{fc} functions, {len(fas.bytecode)} bytes code')

    # ── Build global data entries (deduped, order-preserving) ──
    global_data = _collect_global_data(parsed)

    # ── Build global function catalog (first-definition-wins) ──
    seen_funcs: Set[str] = set()
    global_func_catalog: List[Tuple[str, int]] = []
    for fas in parsed:
        for fname, foff in fas.function_catalog:
            if fname not in seen_funcs:
                seen_funcs.add(fname)
                global_func_catalog.append((fname, foff))

    if verbose:
        print(f'  Merged: {len(global_data)} data entries, '
              f'{len(global_func_catalog)} functions')

    # ── Build index maps for each file ──
    # ── Patch bytecode ──
    merged_code = bytearray()
    offset_bias = 0
    disassembler = Disassembler()

    for file_idx, fas in enumerate(parsed):
        sm = _build_local_data_map(global_data, fas.resource_items)
        instructions = disassembler.disassemble(fas.bytecode, fas.nsyms)
        patched = bytearray()

        for inst in instructions:
            if _needs_symbol_patch(inst.op_name):
                new_ops = _patch_operands(inst, sm, {})
                bc = _encode_with_opcode(inst.opcode, inst.op_name, new_ops)
            else:
                bc = fas.bytecode[inst.offset:inst.offset + inst.size]
            patched.extend(bc)

        merged_code.extend(patched)

        # Adjust function catalog offsets with cumulative bytecode length
        offset_bias += len(fas.bytecode)

    # ── Recalculate actual function catalog offsets ──
    final_offset = 0
    for fas in parsed:
        for i, (fname, foff) in enumerate(fas.function_catalog):
            actual_off = final_offset + foff
            for j, (gfname, _) in enumerate(global_func_catalog):
                if gfname == fname:
                    global_func_catalog[j] = (gfname, actual_off)
                    break
        final_offset += len(fas.bytecode)

    # ── Build SymbolTable from global data entries ──
    symtab = SymbolTable()
    for item_type, item_val in global_data:
        if item_type == 'SYMBOL':
            symtab.get_or_add(item_val)
        elif item_type == 'STRING':
            symtab.add_string(item_val)
        elif item_type in ('INT8', 'INT32', 'INT'):
            symtab.add_int(int(item_val))
        elif item_type == 'REAL':
            symtab.add_real(float(item_val))

    # ── Build func_offsets from global catalog ──
    func_offsets: Dict[str, int] = {}
    for fname, foff in global_func_catalog:
        func_offsets[fname] = foff
        symtab.add_func_ref(fname, foff)

    # ── Write output ──
    seg0 = bytes(merged_code)
    resource = ResourceBuilder(symtab)
    seg1 = resource.build(func_offsets)
    writer = FasWriter(symtab)
    writer.write(output_path, seg0, seg1)

    if verbose:
        total = os.path.getsize(output_path)
        print(f'  Output: {output_path} ({total} bytes)')

    return output_path
