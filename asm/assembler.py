"""FAS4 assembler/disassembler: .fas ↔ .lasm (Lisp Assembly)."""

import os
import re
from typing import Any, List, Dict, Tuple, Optional

from asm.opcodes import (
    NAME_TO_OPCODE,
    OPCODE_TO_NAME,
    encode_instruction,
    encode_op_u16,
    encode_usubr3,
    encode_func3,
)
from compiler.symbol_table import SymbolTable
from compiler.resource_builder import ResourceBuilder, count_resource_records, build_module_code
from compiler.fas_writer import FasWriter

# ─── Disassembler (FAS → .lasm text) ─────────────────────────────────────────

# Opcodes that share a name with another opcode — disambiguate in output
_DUPLICATE_NAMES = {
    0x5C: "GET_LOCAL_WIDE",  # shares name 'GET_LOCAL' with 0x05
}


def _disasm_op_name(opcode: int) -> str:
    """Return the assembly mnemonic, disambiguating duplicates."""
    if opcode in _DUPLICATE_NAMES:
        return _DUPLICATE_NAMES[opcode]
    return OPCODE_TO_NAME.get(opcode, f"UNK_{opcode:02x}")


def _detect_compact(fas) -> bool:
    """健壮的紧凑 stub 检测（disasm/asm 往返专用）。

    反编译器共享的 ``is_compact_stub`` 对多函数紧凑 stub 会误判为自包含
    （UNK 平局且 function_catalog 非空时退回自包含）。这里用
    UNK 计数 + DEFUN 头 argc 编码独立判定，保证 .lasm 格式标记正确。
    """
    from decompiler.fas4_decompiler import Disassembler, is_compact_stub

    bc = fas.bytecode
    if not bc:
        return False
    sym_count = len(getattr(fas, "symbol_slots", []) or [])
    try:
        i3 = Disassembler(short_subr=True).disassemble(bc, 0, sym_count=sym_count or None)
        i6 = Disassembler(short_subr=False).disassemble(bc, 0, sym_count=sym_count or None)
    except Exception:
        return is_compact_stub(bc, fas.function_catalog, sym_count)

    def _unk(insts) -> int:
        return sum(1 for i in insts if i.op_name.startswith("UNK_"))

    c3, c6 = _unk(i3), _unk(i6)
    if c3 != c6:
        return c3 < c6

    def _defuns_argc(insts):
        # 紧凑 stub 的 DEFUN 头为 argc 编码 `14 <argc> <argc> <argc> 0`
        offsets = [i.offset for i in insts if i.op_name == "DEFUN"]
        if not offsets:
            return None
        for off in offsets:
            if off + 5 > len(bc) or bc[off] != 0x14:
                continue
            a, b_, c, d = bc[off + 1], bc[off + 2], bc[off + 3], bc[off + 4]
            if d == 0:
                if a != c:
                    return False
            elif d == 1:
                if not (a == b_ == c):
                    return False
            else:
                return False
        return True

    r = _defuns_argc(i3)
    if r is not None:
        return r
    return is_compact_stub(bc, fas.function_catalog, sym_count)


def _resolve_sym(symbols: List[str], idx: int) -> str:
    if 0 <= idx < len(symbols):
        return symbols[idx]
    return f"[{idx}]"


def _resolve_sym_safe(symbols: List[str], idx: int) -> str:
    """解析符号操作数：名字唯一时输出名字，重复（递归/跨函数引用）时输出 ``[idx]``，
    保证 .lasm 重新汇编时字节可逆。"""
    if 0 <= idx < len(symbols):
        name = symbols[idx]
        if symbols.count(name) == 1:
            return name
    return f"[{idx}]"


def _fmt_inst(inst, symbols: List[str]) -> str:
    """Format one instruction as a .lasm line."""
    prefix = f"  0x{inst.offset:04x}:"
    name = _disasm_op_name(inst.opcode)
    ops = list(inst.operands)

    # DEFUN packs 4 bytes → gv(u16), offset(u16)
    if name == "DEFUN" and len(ops) >= 4:
        gv = ops[0] | (ops[1] << 8)
        off = ops[2] | (ops[3] << 8)
        sym = _resolve_sym(symbols, gv)
        return f"{prefix} DEFUN {sym}, {off}"
    # FUNC/USUBR: second operand is a symbol index
    if name in ("FUNC", "USUBR") and len(ops) >= 2:
        sym = _resolve_sym_safe(symbols, ops[1])
        rest = [str(ops[0]), sym]
        if len(ops) > 2:
            rest.extend(str(o) for o in ops[2:])
        return f'{prefix} {name} {", ".join(rest)}'
    # PUSH_VALUE/PUSH_G/SETQ_G/PUSH_GLOBAL: first operand is a symbol index
    if name in ("PUSH_VALUE", "PUSH_G", "PUSH_GLOBAL", "SETQ_G") and ops:
        sym_info = _resolve_sym_safe(symbols, ops[0])
        rest = [sym_info]
        rest.extend(str(o) for o in ops[1:3])
        return f'{prefix} {name} {", ".join(rest)}'
    # GET_LOCAL/SET_LOCAL/CLEAR_LOCAL: operand is a local slot index (integer)
    if name in ("GET_LOCAL", "GET_LOCAL_WIDE", "SET_LOCAL", "CLEAR_LOCAL") and ops:
        return f"{prefix} {name} {ops[0]}"

    if not ops:
        return f"{prefix} {name}"
    return f'{prefix} {name} {", ".join(str(o) for o in ops)}'


def disassemble_fas(fas_path: str) -> str:
    """Disassemble a FAS4 file into .lasm text format."""
    from decompiler.fas4_decompiler import Fas4Parser, Disassembler, ControlFlowAnalyzer, is_compact_stub, extract_stub_function_names

    parser = Fas4Parser()
    fas = parser.parse(fas_path)
    compact = _detect_compact(fas)
    disasm = Disassembler(short_subr=compact)
    instructions = disasm.disassemble(fas.bytecode, fas.nsyms,
                                      sym_count=len(fas.symbol_slots) if compact else None)
    cfa = ControlFlowAnalyzer(instructions, fas.function_catalog,
                              function_names=extract_stub_function_names(fas))
    functions = cfa.find_functions()

    lines: List[str] = []
    lines.append("; FAS4 assembly")
    lines.append(f"; Source: {os.path.basename(fas_path)}")
    if fas.crunch_date:
        lines.append(f"; Crunch date: {fas.crunch_date}")
    lines.append(f".format {'compact' if compact else 'selfcontained'}")
    lines.append(f".nsyms {fas.nsyms}")
    lines.append("")

    # 紧凑 stub 格式按资源注册顺序（symbol_slots）编址
    if getattr(fas, "symbol_slots", None):
        symbols = [str(it[1]) for it in fas.symbol_slots]
    else:
        symbols = fas.symbols

    lines.append(".symbols")
    for idx, sym in enumerate(symbols):
        lines.append(f"  {idx}: SYMBOL {sym}")
    lines.append(".end_symbols")
    lines.append("")

    for func in functions:
        fname = func.name if func.name and func.name != "c:init" else "__init__"
        lines.append(f".function {fname}, {func.sym_idx}")
        for inst in func.instructions:
            lines.append(_fmt_inst(inst, symbols))
        lines.append(".end_function")
        lines.append("")

    return "\n".join(lines)


# ─── Assembler (.lasm text → FAS) ────────────────────────────────────────────


def _detect_format(functions: List[Tuple[str, int, List[str]]]) -> str:
    """无 ``.format`` 指令时按指令特征判断格式。

    自包含格式含 END_DEFUN/ALPHA/BETA；紧凑 stub 的 seg0 无这些指令。
    """
    for _name, _idx, body in functions:
        for line in body:
            content = _ADDR_PREFIX.sub("", line).split(";", 1)[0].strip()
            if not content:
                continue
            mnem = content.split()[0].upper()
            if mnem in ("END_DEFUN", "ALPHA", "BETA"):
                return "selfcontained"
    return "compact"


def assemble_lasm(lasm_text: str, output_path: str) -> str:
    """Assemble .lasm text into a FAS4 binary file."""

    # === Pass 1: parse structure ===
    symbols_list: List[str] = []
    functions: List[Tuple[str, int, List[str]]] = []
    current_func_name = ""
    current_func_idx = 0
    current_func_body: List[str] = []
    in_symbols = False
    in_function = False
    fmt_dir: Optional[str] = None
    nsyms_dir: Optional[int] = None

    for raw in lasm_text.split("\n"):
        line = raw.split(";", 1)[0].strip()
        if not line:
            continue

        if line.startswith(".format"):
            parts = line.split()
            fmt_dir = parts[1] if len(parts) > 1 else None
        elif line.startswith(".nsyms"):
            parts = line.split()
            nsyms_dir = int(parts[1]) if len(parts) > 1 else None
        elif line == ".symbols":
            in_symbols = True
        elif line == ".end_symbols":
            in_symbols = False
        elif line.startswith(".function"):
            m = re.match(r"\.function\s+(\S+),\s*(\d+)", line)
            if m:
                if in_function:
                    functions.append((current_func_name, current_func_idx, current_func_body))
                current_func_name = m.group(1)
                current_func_idx = int(m.group(2))
                current_func_body = []
                in_function = True
        elif line == ".end_function":
            if in_function:
                functions.append((current_func_name, current_func_idx, current_func_body))
                current_func_name = ""
                current_func_body = []
                in_function = False
        elif in_symbols:
            m = re.match(r"\s*(\d+)\s*:\s*SYMBOL\s+(.+)", line)
            if m:
                idx = int(m.group(1))
                name = m.group(2).strip()
                while len(symbols_list) <= idx:
                    symbols_list.append("")
                symbols_list[idx] = name
        elif in_function:
            current_func_body.append(line)

    if in_function and current_func_name:
        functions.append((current_func_name, current_func_idx, current_func_body))

    fmt = fmt_dir if fmt_dir in ("compact", "selfcontained") else _detect_format(functions)
    if fmt == "compact":
        return _assemble_compact(output_path, symbols_list, functions, nsyms_dir)
    return _assemble_selfcontained(output_path, symbols_list, functions)


def _assemble_selfcontained(output_path: str, symbols_list: List[str],
                            functions: List[Tuple[str, int, List[str]]]) -> str:
    """自包含格式汇编：符号表直接编址，total_size = len(seg0_payload)。"""
    symtab = SymbolTable()
    for sym in symbols_list:
        symtab.get_or_add(sym)

    # === Pass 2: assemble bytecode ===
    init_code = bytearray()
    function_bytes: List[bytes] = []
    function_names: List[str] = []

    for fname, _fidx, body_lines in functions:
        if fname == "__init__":
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

    for fname, fbytes in zip(function_names, function_bytes):
        offset = len(all_bc)
        func_offsets[fname] = offset
        all_bc.extend(fbytes)

    for name in function_names:
        symtab.add_func_ref(name, func_offsets[name])

    seg0 = bytes(all_bc)
    resource = ResourceBuilder(symtab)
    seg1 = resource.build(func_offsets)
    writer = FasWriter(symtab)
    writer.write(output_path, seg0, seg1)
    return output_path


def _assemble_compact(output_path: str, symbols_list: List[str],
                      functions: List[Tuple[str, int, List[str]]],
                      nsyms_dir: Optional[int]) -> str:
    """紧凑 stub 汇编：与 CAD 编译器一致的符号槽/加密/stub 布局。

    - 符号按资源注册顺序（symbol_slots）编址，entries = 全部槽 - 末尾函数注册名
    - 指令使用 stub 编码（USUBR/FUNC 3 字节，PUSH_VALUE[0] 单字节）
    - 输出 compact stub：``total_size = len(seg0_payload) - 2``
    """
    func_names = [n for n, _i, _b in functions if n != "__init__"]
    n_func = len(func_names)
    entries = symbols_list[: len(symbols_list) - n_func] if n_func else symbols_list

    symtab = SymbolTable()
    for sym in entries:
        if sym in symtab.name_to_idx:
            symtab.add_force(sym)
        else:
            symtab.get_or_add(sym)

    # === Assemble function bytecode (stub encodings) ===
    seg0 = bytearray()
    func_offsets: Dict[str, int] = {}
    for fname, _fidx, body_lines in functions:
        if fname == "__init__":
            continue
        off = len(seg0)
        fb = bytearray()
        for line in body_lines:
            bc = _asm_instr(line, symtab, symbols_list, compact=True)
            if bc:
                fb.extend(bc)
        seg0.extend(fb)
        func_offsets[fname] = off

    symtab.function_offsets = dict(func_offsets)

    if nsyms_dir is not None:
        fas_nsyms = nsyms_dir
    else:
        fas_nsyms = len(entries) - n_func + 1
    # 顶层表达式符号数：nsyms = len(entries) - (n_func + top_level_count) + 1
    top_level_count = max(0, len(entries) - n_func - fas_nsyms + 1)

    # === Build CAD stub seg1 and write ===
    seg0_payload = f"{fas_nsyms} $".encode() + bytes(seg0)
    module_code = build_module_code(n_func, nsyms=fas_nsyms)
    resource = ResourceBuilder(symtab)
    seg1 = resource.build(func_offsets, module_code=module_code,
                          seg0_payload_len=len(seg0_payload), stub_format=True,
                          top_level_count=top_level_count)
    sec2_items = count_resource_records(seg1)
    min_items = fas_nsyms - 1 if n_func > 1 else fas_nsyms
    if sec2_items < min_items:
        sec2_items = min_items

    writer = FasWriter(symtab)
    writer.write(output_path, bytes(seg0), seg1, sec2_items=sec2_items,
                 nsyms=fas_nsyms, compact=True)
    return output_path


_INSTR_RE = re.compile(r"(\w+)(.*)")
_ADDR_PREFIX = re.compile(r"^0x[0-9a-fA-F]+:")


def _asm_instr(line: str, symtab: SymbolTable, symbols: List[str], compact: bool = False) -> Optional[bytes]:
    """Parse one assembly instruction line and encode to bytes.

    ``compact`` 为紧凑 stub 格式时使用 CAD 编码：
    - USUBR/FUNC 为 3 字节（``35 <argc> <idx8>`` / ``51 <argc> <idx8>``）
    - PUSH_VALUE[0] 为单字节 ``03``；idx>0 仍为 ``03 <u16>``
    """
    content = _ADDR_PREFIX.sub("", line).strip()
    if not content:
        return None

    m = _INSTR_RE.match(content)
    if not m:
        return None

    mnemonic = m.group(1).upper()
    rest = m.group(2).strip()
    operands = _parse_ops(rest, symtab)

    if mnemonic == "GET_LOCAL_WIDE":
        # Use wide GET_LOCAL opcode (0x5c) instead of standard (0x05)
        from asm.opcodes import encode_op_u16

        op = NAME_TO_OPCODE.get("GET_LOCAL", 0xFF)
        # Force opcode 0x5c
        return encode_op_u16(0x5C, int(operands[0]) if operands else 0)

    if compact:
        if mnemonic == "USUBR" and operands:
            return encode_usubr3(int(operands[0]), int(operands[1]) if len(operands) > 1 else 0)
        if mnemonic == "FUNC" and operands:
            return encode_func3(int(operands[0]), int(operands[1]) if len(operands) > 1 else 0)
        if mnemonic == "PUSH_VALUE" and operands and int(operands[0]) == 0:
            return bytes([0x03])

    return encode_instruction(mnemonic, operands)


def _parse_ops(text: str, symtab: SymbolTable) -> List:
    """Parse comma-separated operands, resolving symbol names to indices."""
    if not text.strip():
        return []

    parts = [p.strip() for p in text.split(",")]
    result: List[Any] = []
    for p in parts:
        if not p:
            continue
        if p in symtab.name_to_idx:
            result.append(symtab.name_to_idx[p])
        elif p.startswith("[") and p.endswith("]") and p[1:-1].isdigit():
            result.append(int(p[1:-1]))
        else:
            try:
                result.append(int(p))
            except ValueError:
                try:
                    result.append(float(p))
                except ValueError:
                    raise ValueError(f"Cannot resolve operand: {p!r}")
    return result
