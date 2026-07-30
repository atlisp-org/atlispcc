"""FAS4 assembler/disassembler: .fas ↔ .lasm (Lisp Assembly)."""
import os
import re
from typing import List, Dict, Tuple, Optional

from compiler.opcodes import (
    NAME_TO_OPCODE, OPCODE_TO_NAME,
    encode_instruction, encode_op_u16,
)
from compiler.symbol_table import SymbolTable
from compiler.resource_builder import ResourceBuilder
from compiler.fas_writer import FasWriter


# ─── Disassembler (FAS → .lasm text) ─────────────────────────────────────────

# Opcodes that share a name with another opcode — disambiguate in output
_DUPLICATE_NAMES = {
    0x5c: 'GET_LOCAL_WIDE',  # shares name 'GET_LOCAL' with 0x05
}


def _disasm_op_name(opcode: int) -> str:
    """Return the assembly mnemonic, disambiguating duplicates."""
    if opcode in _DUPLICATE_NAMES:
        return _DUPLICATE_NAMES[opcode]
    return OPCODE_TO_NAME.get(opcode, f'UNK_{opcode:02x}')


def _resolve_sym(symbols: List[str], idx: int) -> str:
    if 0 <= idx < len(symbols):
        return symbols[idx]
    return f'[{idx}]'


def _fmt_inst(inst, symbols: List[str]) -> str:
    """Format one instruction as a .lasm line."""
    prefix = f'  0x{inst.offset:04x}:'
    name = _disasm_op_name(inst.opcode)
    ops = list(inst.operands)

    # DEFUN packs 4 bytes → gv(u16), offset(u16)
    if name == 'DEFUN' and len(ops) >= 4:
        gv = ops[0] | (ops[1] << 8)
        off = ops[2] | (ops[3] << 8)
        sym = _resolve_sym(symbols, gv)
        return f'{prefix} DEFUN {sym}, {off}'
    # FUNC/USUBR: second operand is a symbol index
    if name in ('FUNC', 'USUBR') and len(ops) >= 2:
        sym = _resolve_sym(symbols, ops[1])
        rest = [str(ops[0]), sym]
        if len(ops) > 2:
            rest.extend(str(o) for o in ops[2:])
        return f'{prefix} {name} {", ".join(rest)}'
    # PUSH_VALUE/PUSH_G/SETQ_G/PUSH_GLOBAL: first operand is a symbol index
    if name in ('PUSH_VALUE', 'PUSH_G', 'PUSH_GLOBAL', 'SETQ_G') and ops:
        sym_info = _resolve_sym(symbols, ops[0])
        rest = [sym_info]
        rest.extend(str(o) for o in ops[1:3])
        return f'{prefix} {name} {", ".join(rest)}'
    # GET_LOCAL/SET_LOCAL/CLEAR_LOCAL: operand is a local slot index (integer)
    if name in ('GET_LOCAL', 'GET_LOCAL_WIDE', 'SET_LOCAL', 'CLEAR_LOCAL') and ops:
        return f'{prefix} {name} {ops[0]}'

    if not ops:
        return f'{prefix} {name}'
    return f'{prefix} {name} {", ".join(str(o) for o in ops)}'


def disassemble_fas(fas_path: str) -> str:
    """Disassemble a FAS4 file into .lasm text format."""
    from fas4_decompiler import Fas4Parser, Disassembler, ControlFlowAnalyzer

    parser = Fas4Parser()
    fas = parser.parse(fas_path)
    disasm = Disassembler()
    instructions = disasm.disassemble(fas.bytecode, fas.nsyms)
    cfa = ControlFlowAnalyzer(instructions, fas.function_catalog)
    functions = cfa.find_functions()

    lines: List[str] = []
    lines.append('; FAS4 assembly')
    lines.append(f'; Source: {os.path.basename(fas_path)}')
    if fas.crunch_date:
        lines.append(f'; Crunch date: {fas.crunch_date}')
    lines.append('')

    lines.append('.symbols')
    for idx, sym in enumerate(fas.symbols):
        lines.append(f'  {idx}: SYMBOL {sym}')
    lines.append('.end_symbols')
    lines.append('')

    for func in functions:
        fname = func.name if func.name and func.name != 'c:init' else '__init__'
        lines.append(f'.function {fname}, {func.sym_idx}')
        for inst in func.instructions:
            lines.append(_fmt_inst(inst, fas.symbols))
        lines.append('.end_function')
        lines.append('')

    return '\n'.join(lines)


# ─── Assembler (.lasm text → FAS) ────────────────────────────────────────────

def assemble_lasm(lasm_text: str, output_path: str) -> str:
    """Assemble .lasm text into a FAS4 binary file."""

    # === Pass 1: parse structure ===
    symbols_list: List[str] = []
    functions: List[Tuple[str, int, List[str]]] = []
    current_func_name = ''
    current_func_idx = 0
    current_func_body: List[str] = []
    in_symbols = False
    in_function = False

    for raw in lasm_text.split('\n'):
        line = raw.split(';', 1)[0].strip()
        if not line:
            continue

        if line == '.symbols':
            in_symbols = True
        elif line == '.end_symbols':
            in_symbols = False
        elif line.startswith('.function'):
            m = re.match(r'\.function\s+(\S+),\s*(\d+)', line)
            if m:
                if in_function:
                    functions.append((current_func_name, current_func_idx, current_func_body))
                current_func_name = m.group(1)
                current_func_idx = int(m.group(2))
                current_func_body = []
                in_function = True
        elif line == '.end_function':
            if in_function:
                functions.append((current_func_name, current_func_idx, current_func_body))
                current_func_name = ''
                current_func_body = []
                in_function = False
        elif in_symbols:
            m = re.match(r'\s*(\d+)\s*:\s*SYMBOL\s+(.+)', line)
            if m:
                idx = int(m.group(1))
                name = m.group(2).strip()
                while len(symbols_list) <= idx:
                    symbols_list.append('')
                symbols_list[idx] = name
        elif in_function:
            current_func_body.append(line)

    if in_function and current_func_name:
        functions.append((current_func_name, current_func_idx, current_func_body))

    # === Build SymbolTable with all symbols ===
    symtab = SymbolTable()
    for sym in symbols_list:
        symtab.get_or_add(sym)

    # === Pass 2: assemble bytecode ===
    init_code = bytearray()
    function_bytes: List[bytes] = []
    function_names: List[str] = []

    for fname, _fidx, body_lines in functions:
        if fname == '__init__':
            for line in body_lines:
                bc = _asm_instr(line, symtab, symbols_list)
                if bc:
                    init_code.extend(bc)
            continue

        fb = bytearray()
        for line in body_lines:
            bc = _asm_instr(line, symtab, symbols_list)
            if bc:
                fb.extend(bc)
        function_bytes.append(bytes(fb))
        function_names.append(fname)

    # === Build function catalog and write FAS ===
    func_offsets: Dict[str, int] = {}
    all_bc = bytearray(init_code)

    for fname, fb in zip(function_names, function_bytes):
        offset = len(all_bc)
        func_offsets[fname] = offset
        all_bc.extend(fb)

    for name in function_names:
        symtab.add_func_ref(name, func_offsets[name])

    seg0 = bytes(all_bc)
    resource = ResourceBuilder(symtab)
    seg1 = resource.build(func_offsets)
    writer = FasWriter(symtab)
    writer.write(output_path, seg0, seg1)
    return output_path


_INSTR_RE = re.compile(r'(\w+)(.*)')
_ADDR_PREFIX = re.compile(r'^0x[0-9a-fA-F]+:')


def _asm_instr(line: str, symtab: SymbolTable, symbols: List[str]) -> Optional[bytes]:
    """Parse one assembly instruction line and encode to bytes."""
    content = _ADDR_PREFIX.sub('', line).strip()
    if not content:
        return None

    m = _INSTR_RE.match(content)
    if not m:
        return None

    mnemonic = m.group(1).upper()
    rest = m.group(2).strip()
    operands = _parse_ops(rest, symtab)

    if mnemonic == 'GET_LOCAL_WIDE':
        # Use wide GET_LOCAL opcode (0x5c) instead of standard (0x05)
        from compiler.opcodes import encode_op_u16
        op = NAME_TO_OPCODE.get('GET_LOCAL', 0xff)
        # Force opcode 0x5c
        return encode_op_u16(0x5c, int(operands[0]) if operands else 0)

    return encode_instruction(mnemonic, operands)


def _parse_ops(text: str, symtab: SymbolTable) -> List:
    """Parse comma-separated operands, resolving symbol names to indices."""
    if not text.strip():
        return []

    parts = [p.strip() for p in text.split(',')]
    result = []
    for p in parts:
        if not p:
            continue
        if p in symtab.name_to_idx:
            result.append(symtab.name_to_idx[p])
        elif p.startswith('[') and p.endswith(']') and p[1:-1].isdigit():
            result.append(int(p[1:-1]))
        else:
            try:
                result.append(int(p))
            except ValueError:
                try:
                    result.append(float(p))
                except ValueError:
                    raise ValueError(f'Cannot resolve operand: {p!r}')
    return result
