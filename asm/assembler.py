"""FAS4 assembler/disassembler: .fas ↔ .lasm (Lisp Assembly)."""

import os
import re
from typing import Any, List, Dict, Tuple, Optional

from asm.opcodes import (
    NAME_TO_OPCODE,
    OPCODE_TO_NAME,
    encode_instruction,
    encode_op_u16,
    encode_usubr,
    encode_usubr3,
    encode_func,
    encode_func3,
)
from compiler.symbol_table import SymbolTable
from compiler.resource_builder import ResourceBuilder, count_resource_records, build_module_code
from compiler.fas_writer import FasWriter

# ─── Disassembler (FAS → .lasm text) ─────────────────────────────────────────


def _disasm_op_name(opcode: int) -> str:
    """Return the assembly mnemonic for an opcode."""
    return OPCODE_TO_NAME.get(opcode, f"UNK_{opcode:02x}")


def _detect_compact(fas):
    """健壮的紧凑 stub 检测（disasm/asm 往返专用）。

    返回 ``(compact, instructions)``：``instructions[short_subr]`` 是检测过程中
    已经反汇编出的指令表，供 :func:`disassemble_fas` 复用，避免第三次全量反汇编。

    反编译器共享的 ``is_compact_stub`` 对多函数紧凑 stub 会误判为自包含
    （UNK 平局且 function_catalog 非空时退回自包含）。这里用
    UNK 计数 + DEFUN 头 argc 编码独立判定，保证 .lasm 格式标记正确。

    大文件（nsyms>256）用宽格式 USUBR/FUNC（5/6 字节），须用
    ``short_subr=False`` 解析才正确（短解析会把宽指令拆错产生 UNK）。
    """
    from decompiler.fas4_decompiler import Disassembler, is_compact_stub

    bc = fas.bytecode
    if not bc:
        return False, {}
    sym_count = len(getattr(fas, "symbol_slots", []) or [])
    nsyms = getattr(fas, "nsyms", 0)

    def _defuns_argc(insts):
        # 紧凑 stub 的 DEFUN 头为 argc 编码 `14 <argc> <argc> <argc> 0`；
        # foreach/repeat 函数为 `14 <argc+1> <argc> <argc> 0`（b1=argc+1，t16/t17 实测）；
        # 内嵌 `-lambda-`（kwote 机制）亦 b1=argc+1（0 参 lambda → `14 01 00 00 00`）。
        offsets = [i.offset for i in insts if i.op_name == "DEFUN"]
        if not offsets:
            return None
        for off in offsets:
            if off + 5 > len(bc) or bc[off] != 0x14:
                continue
            a, b_, c, d = bc[off + 1], bc[off + 2], bc[off + 3], bc[off + 4]
            if d == 0:
                # 普通紧凑：`14 <argc>x3`；foreach/repeat/内嵌 -lambda-：
                # `14 <argc+1> <argc> <argc>`（b1=argc+1）；直接体循环+`/ 局部变量`
                # b1=argc+2（@lisp_u add-menus 实测 `14 03 01 01 00`）。
                if not (a == b_ == c or (b_ == c and a in (c + 1, c + 2))):
                    return False
            elif d == 1:
                if not (a == b_ == c):
                    return False
            else:
                return False
        return True

    try:
        i3 = Disassembler(short_subr=True).disassemble(bc, 0, sym_count=sym_count or None)
        i6 = Disassembler(short_subr=False).disassemble(bc, 0, sym_count=sym_count or None)
    except Exception:
        return is_compact_stub(bc, fas.function_catalog, sym_count), {}

    def _unk(insts) -> int:
        return sum(1 for i in insts if i.op_name.startswith("UNK_"))

    c3, c6 = _unk(i3), _unk(i6)
    # 宽格式大文件 stub：短解析拆错宽指令 → c3 多、c6 少/零。
    # 小文件 stub：短解析正确（c3 少）、宽解析把 3 字节当 6 字节拆错（c6 多）。
    # 自包含：短解析拆错长指令（c3 多）、宽解析正确（c6 少）——但自包含文件
    # 的函数目录/结构由 mvar 表区分，此处先排除掉 UNK 为 0 的宽解析（自包含
    # 也用宽编码，二者易混淆），再用 DEFUN 头 argc 编码作最终判定。
    if c3 > 0 and c6 == 0:
        # 短解析有 UNK 而宽解析干净：必为大文件 stub（紧凑）或自包含。
        # 自包含的 DEFUN 头是 gvar 编码（`14 <gv:2> <off:2>`），紧凑 stub 是
        # argc 编码；用宽解析的 DEFUN 头判定。
        r = _defuns_argc(i6)
        if r is not None:
            return r, {True: i3, False: i6}
    elif c6 > 0 and c3 == 0:
        return True, {True: i3, False: i6}  # 短解析干净：小文件 stub

    r = _defuns_argc(i3)
    if r is not None:
        return r, {True: i3, False: i6}
    return is_compact_stub(bc, fas.function_catalog, sym_count), {True: i3, False: i6}


def _resolve_sym(symbols: List[str], idx: int) -> str:
    if 0 <= idx < len(symbols):
        return symbols[idx]
    return f"[{idx}]"


def _resolve_sym_safe(
    symbols: List[str],
    idx: int,
    sym_types: Optional[List[str]] = None,
    symbol_counts: Optional[dict] = None,
) -> str:
    """解析符号操作数：名字唯一时输出名字，重复（递归/跨函数引用）或 REAL 槽
    输出 ``[idx]``，保证 .lasm 重新汇编时字节可逆。

    ``symbol_counts`` 为 ``name -> 出现次数``（一次性预计算），避免逐指令
    ``list.count`` 的 O(n²) 扫描。
    """
    if 0 <= idx < len(symbols):
        typ = sym_types[idx] if sym_types else None
        if typ == "REAL":
            return f"[{idx}]"
        name = symbols[idx]
        count = symbol_counts.get(name, 0) if symbol_counts is not None else symbols.count(name)
        if count == 1:
            return name
    return f"[{idx}]"


def _quote_lasm_string(s: str) -> str:
    """把字符串常量转成单行 .lasm 显示形式（引号包裹 + 转义）。"""
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"').replace("\r\n", "\\n").replace("\n", "\\n") + '"'


def _unquote_lasm_string(s: str) -> str:
    """撤销 _quote_lasm_string：``"..."`` → 原始字符串（非引号形式原样返回）。"""
    if not (s.startswith('"') and s.endswith('"') and len(s) >= 2):
        return s
    body = s[1:-1]
    out = []
    i = 0
    while i < len(body):
        c = body[i]
        if c == "\\" and i + 1 < len(body):
            n = body[i + 1]
            out.append({"n": "\n", "\\": "\\", '"': '"'}.get(n, n))
            i += 2
            continue
        out.append(c)
        i += 1
    return "".join(out)


def _is_plain_symbol(name: str) -> bool:
    """SYMBOL 记录是否可裸写：不含破坏 .lasm 行解析的字符。

    引号/分号/逗号/括号/方括号/空白/井号 以及纯数字需转引号形式；
    ``+ - * < > =`` 等运算符符号名可裸写。
    """
    if not name:
        return False
    if name.isdigit() or name.lstrip("-").isdigit():
        return False
    forbidden = set(' \t\r\n;,[]"#(){}')
    return not any(c in forbidden for c in name)


def _fmt_inst(
    inst,
    symbols: List[str],
    sym_types: Optional[List[str]] = None,
    compact: bool = False,
    bytecode: Optional[bytes] = None,
    symbol_counts: Optional[dict] = None,
) -> str:
    """Format one instruction as a .lasm line.

    反汇编在助记符前附带该指令的原始十六进制字节列
    （``0x0000: 14 01 01 01 00  DEFUN 1, 1, 1, 0``），便于对照字节码。
    汇编时 ``_asm_instr`` 会剥离该列，故 disasm→asm 往返仍逐字节一致；
    手工编写的 .lasm 可不含该列。
    """
    prefix = f"  0x{inst.offset:04x}:"
    name = _disasm_op_name(inst.opcode)
    ops = list(inst.operands)

    hex_col = ""
    if bytecode is not None:
        raw = bytecode[inst.offset : inst.offset + inst.size]
        hex_col = " ".join(f"{b:02x}" for b in raw)

    def _line(body: str) -> str:
        if hex_col:
            return f"{prefix} {hex_col:<17} {body}"
        return f"{prefix} {body}"

    # DEFUN：紧凑 stub 为 argc 编码 `14 <argc>x3 <mode>`，4 个字节操作数
    # 原样输出（DEFUN 1, 1, 1, 0）；自包含为 gvar 编码 `14 <gv:2> <off:2>`，
    # 打包成符号 + 偏移（DEFUN f2, 0）。
    if name in ("DEFUN", "DEFUN_ALT") and len(ops) >= 4:
        if compact:
            return _line(f"{name} {ops[0]}, {ops[1]}, {ops[2]}, {ops[3]}")
        gv = ops[0] | (ops[1] << 8)
        off = ops[2] | (ops[3] << 8)
        sym = _resolve_sym(symbols, gv)
        return _line(f"{name} {sym}, {off}")
    # FUNC/USUBR: second operand is a symbol index
    if name in ("FUNC", "USUBR") and len(ops) >= 2:
        sym = _resolve_sym_safe(symbols, ops[1], sym_types, symbol_counts)
        rest = [str(ops[0]), sym]
        if len(ops) > 2:
            rest.extend(str(o) for o in ops[2:])
        return _line(f'{name} {", ".join(rest)}')
    # PUSH_VALUE/PUSH_G/SETQ_G/PUSH_G_ALT: first operand is a symbol index
    if name in ("PUSH_VALUE", "PUSH_G", "PUSH_G_ALT", "SETQ_G") and ops:
        sym_info = _resolve_sym_safe(symbols, ops[0], sym_types, symbol_counts)
        rest = [sym_info]
        rest.extend(str(o) for o in ops[1:3])
        return _line(f'{name} {", ".join(rest)}')
    # GET_LOCAL/SET_LOCAL/CLEAR_LOCAL: operand is a local slot index (integer)
    if name in ("GET_LOCAL", "GET_LOCAL_WIDE", "SET_LOCAL", "CLEAR_LOCAL") and ops:
        return _line(f"{name} {ops[0]}")

    if not ops:
        return _line(name)
    return _line(f'{name} {", ".join(str(o) for o in ops)}')


def disassemble_fas(fas_path: str) -> str:
    """Disassemble a FAS4 file into .lasm text format."""
    from decompiler.fas4_decompiler import Fas4Parser, Disassembler, ControlFlowAnalyzer, is_compact_stub, extract_stub_function_names

    parser = Fas4Parser()
    fas = parser.parse(fas_path)
    compact, detected = _detect_compact(fas)
    # 大文件（nsyms>256）紧凑 stub 用宽格式 USUBR/FUNC（5/6 字节），
    # 须以 short_subr=False 解析；小文件用 3 字节短格式。
    wide = compact and getattr(fas, "nsyms", 0) > 256
    short_subr = not wide
    instructions = detected.get(short_subr)
    if instructions is None:
        disasm = Disassembler(short_subr=short_subr)
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
    sym_types: List[str] = []
    if getattr(fas, "symbol_slots", None):
        symbols = []
        for it in fas.symbol_slots:
            typ = it[0]
            val = str(it[1])
            sym_types.append(typ)
            # STRING/REAL 记录（含多行 DCL）转成引号+转义的单行形式，保证 .lasm 字节可逆
            if typ == "SYMBOL" and _is_plain_symbol(val):
                symbols.append(val)
            else:
                symbols.append(_quote_lasm_string(val))
    else:
        symbols = fas.symbols
        sym_types = ["SYMBOL"] * len(symbols)

    symbol_counts: dict = {}
    for sym in symbols:
        symbol_counts[sym] = symbol_counts.get(sym, 0) + 1

    lines.append(".symbols")
    for idx, sym in enumerate(symbols):
        typ = sym_types[idx] if idx < len(sym_types) else "SYMBOL"
        lines.append(f"  {idx}: {typ} {sym}")
    lines.append(".end_symbols")
    lines.append("")

    for func in functions:
        fname = func.name if func.name and func.name != "c:init" else "__init__"
        lines.append(f".function {fname}, {func.sym_idx}")
        for inst in func.instructions:
            lines.append(_fmt_inst(inst, symbols, sym_types, compact=compact,
                                   bytecode=fas.bytecode, symbol_counts=symbol_counts))
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
            content = _strip_hex_bytes(_ADDR_PREFIX.sub("", line)).split(";", 1)[0].strip()
            if not content:
                continue
            mnem = content.split()[0].upper()
            if mnem in ("END_DEFUN", "ALPHA", "BETA"):
                return "selfcontained"
    return "compact"


def assemble_lasm(lasm_text: str, output_path: str, date=None, salt=None) -> str:
    """Assemble .lasm text into a FAS4 binary file.

    ``date``/``salt`` 透传给容器尾部的可复现构建选项（同 ``compile``）。
    """
    # === Pass 1: parse structure ===
    symbols_list: List[str] = []
    symbol_types: List[str] = []
    functions: List[Tuple[str, int, List[str]]] = []
    current_func_name = ""
    current_func_idx = 0
    current_func_body: List[str] = []
    in_symbols = False
    in_function = False
    fmt_dir: Optional[str] = None
    nsyms_dir: Optional[int] = None

    for raw in lasm_text.split("\n"):
        line = _strip_comment(raw).strip()
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
            m = re.match(r"\.function\s+(\S+),\s*(-?\d+)", line)
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
            m = re.match(r"\s*(\d+)\s*:\s*(SYMBOL|STRING|REAL)\s+(.+)", line)
            if m:
                idx = int(m.group(1))
                typ = m.group(2)
                name = m.group(3).strip()
                while len(symbols_list) <= idx:
                    symbols_list.append("")
                    symbol_types.append("SYMBOL")
                symbols_list[idx] = name
                symbol_types[idx] = typ
        elif in_function:
            current_func_body.append(line)

    if in_function and current_func_name:
        functions.append((current_func_name, current_func_idx, current_func_body))

    fmt = fmt_dir if fmt_dir in ("compact", "selfcontained") else _detect_format(functions)
    if fmt == "compact":
        return _assemble_compact(output_path, symbols_list, symbol_types, functions,
                                 nsyms_dir, date=date, salt=salt)
    return _assemble_selfcontained(output_path, symbols_list, symbol_types, functions,
                                   nsyms_dir, date=date, salt=salt)


def assemble_lasm_zelx(lasm_text: str, output_path: str) -> str:
    """通用 lasm → ZWCAD .zelx。

    lasm 助记符描述的是语义（PUSH_G/USUBR/JUMP 等两平台相同），先按 AutoCAD
    字节码汇编成 .fas，再经 ZWCAD opcode 重映射/容器组装为 .zelx。
    """
    import tempfile
    from tools.zelx_build import _build_zelx_fas

    tmp = tempfile.NamedTemporaryFile(suffix=".fas", delete=False)
    tmp.close()
    try:
        assemble_lasm(lasm_text, tmp.name)
        _build_zelx_fas(tmp.name, output_path)
    finally:
        if os.path.exists(tmp.name):
            os.unlink(tmp.name)
    return output_path


def _register_slot(symtab: SymbolTable, typ: str, display: str) -> int:
    """按 .lasm 顺序注册一个符号槽，保留 STRING/REAL/SYMBOL 类型。返回槽索引。

    ``display`` 为 STRING/REAL 时是引号转义形式；重复槽直接追加（保持顺序），
    并让 ``name_to_idx`` 指向该新槽。
    """
    val = _unquote_lasm_string(display) if display.startswith('"') else display
    if typ == "STRING":
        key = f"__str_{val}__"
    elif typ == "REAL":
        key = f"__real_{float(val)}__"
    else:
        key = val
    if key in symtab.name_to_idx:
        idx = len(symtab.entries)
        symtab.entries.append((typ, float(val) if typ == "REAL" else val))
        symtab.name_to_idx[key] = idx
        return idx
    if typ == "STRING":
        idx = len(symtab.entries)
        symtab.name_to_idx[key] = idx
        symtab.entries.append(("STRING", val))
        symtab.strings.append(val)
        return idx
    if typ == "REAL":
        return symtab.add_real(float(val))
    return symtab.get_or_add(val)


def _assemble_selfcontained(output_path: str, symbols_list: List[str],
                            symbol_types: List[str],
                            functions: List[Tuple[str, int, List[str]]],
                            nsyms_dir: Optional[int] = None,
                            date=None, salt=None) -> str:
    """自包含格式汇编：符号表直接编址，total_size = len(seg0_payload)。"""
    symtab = SymbolTable()
    for i, sym in enumerate(symbols_list):
        typ = symbol_types[i] if i < len(symbol_types) else "SYMBOL"
        _register_slot(symtab, typ, sym)

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
        # 空体函数（纯顶层文件的合成入口，如 set5 的 `c:main`）：seg0 无字节码，
        # 不注册为真实函数（否则 nsyms 多 1）。
        if not fb and not function_bytes:
            continue
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
    writer = FasWriter(symtab, date=date, salt=salt)
    # 支持 .nsyms 指令覆盖（纯顶层 selfcontained 的 nsyms = 模块注册符号数）。
    if nsyms_dir is not None:
        writer.write(output_path, seg0, seg1, nsyms=nsyms_dir)
    else:
        writer.write(output_path, seg0, seg1)
    return output_path


def _assemble_compact(output_path: str, symbols_list: List[str], symbol_types: List[str],
                      functions: List[Tuple[str, int, List[str]]],
                      nsyms_dir: Optional[int], date=None, salt=None) -> str:
    """紧凑 stub 汇编：与 CAD 编译器一致的符号槽/加密/stub 布局。

    - 符号按资源注册顺序（symbol_slots）编址，entries = 全部槽 - 末尾函数注册名
    - 指令使用 stub 编码（小文件 USUBR/FUNC 3 字节、PUSH_VALUE[0] 单字节；
      大文件 nsyms>256 用 5/6 字节宽格式）
    - 输出 compact stub：``total_size = len(seg0_payload) - 2``
    """
    func_names = [n for n, _i, _b in functions if n != "__init__"]
    n_func = len(func_names)
    entries = symbols_list[: len(symbols_list) - n_func] if n_func else symbols_list

    if nsyms_dir is not None:
        fas_nsyms = nsyms_dir
    else:
        fas_nsyms = len(entries) - n_func + 1
    # 大文件（nsyms>256）紧凑 stub 用宽格式 USUBR/FUNC（5/6 字节）
    wide = fas_nsyms > 256

    symtab = SymbolTable()
    for i, sym in enumerate(entries):
        typ = symbol_types[i] if i < len(symbol_types) else "SYMBOL"
        _register_slot(symtab, typ, sym)

    # === Assemble function bytecode (stub encodings) ===
    seg0 = bytearray()
    func_offsets: Dict[str, int] = {}
    for fname, _fidx, body_lines in functions:
        fb = bytearray()
        for line in body_lines:
            bc = _asm_instr(line, symtab, symbols_list, compact=True, wide=wide)
            if bc:
                fb.extend(bc)
        if fname == "__init__":
            # c:init（模块代码 stub / 顶层表达式）在 seg0 中是真实字节，
            # 必须写回原位（不注册为函数、不进目录、不计数）。
            seg0.extend(fb)
            continue
        off = len(seg0)
        seg0.extend(fb)
        func_offsets[fname] = off

    symtab.function_offsets = dict(func_offsets)

    # 顶层表达式符号数：nsyms = len(entries) - (n_func + top_level_count) + 1
    top_level_count = max(0, len(entries) - n_func - fas_nsyms + 1)

    # === Build CAD stub seg1 and write ===
    module_code = build_module_code(n_func, nsyms=fas_nsyms)
    resource = ResourceBuilder(symtab)
    seg1 = resource.build(func_offsets, module_code=module_code,
                          total_size=len(seg0) + 1, stub_format=True,
                          top_level_count=top_level_count)
    sec2_items = count_resource_records(seg1)
    min_items = fas_nsyms - 1 if n_func > 1 else fas_nsyms
    if sec2_items < min_items:
        sec2_items = min_items

    writer = FasWriter(symtab, date=date, salt=salt)
    writer.write(output_path, bytes(seg0), seg1, sec2_items=sec2_items,
                 nsyms=fas_nsyms, compact=True)
    return output_path


_INSTR_RE = re.compile(r"(\w+)(.*)")
_ADDR_PREFIX = re.compile(r"^0x[0-9a-fA-F]+:")
# 反汇编行首的原始字节列（`14 01 01 01 00  DEFUN ...`），汇编时剥离。
# 助记符如 DEC/BETA/CAR 首两字符虽可恰为十六进制位，但后随字符非空白，
# 故不会误剥离无字节列的手工 .lasm。
_HEX_BYTES_RE = re.compile(r"^(?:[0-9a-fA-F]{2}\s+)+")


def _strip_hex_bytes(content: str) -> str:
    """去掉行首十六进制字节列，返回剩余指令文本（含助记符）。"""
    content = content.strip()
    return _HEX_BYTES_RE.sub("", content, count=1).strip()


def _strip_comment(line: str) -> str:
    """去掉行注释（``;``），但忽略引号字符串内部的 ``;``。"""
    out = []
    inq = False
    i = 0
    while i < len(line):
        c = line[i]
        if inq:
            out.append(c)
            if c == "\\" and i + 1 < len(line):
                out.append(line[i + 1])
                i += 2
                continue
            if c == '"':
                inq = False
        elif c == '"':
            inq = True
            out.append(c)
        elif c == ";":
            break
        else:
            out.append(c)
        i += 1
    return "".join(out)


def _split_ops(text: str) -> List[str]:
    """按逗号切分操作数，但尊重引号包裹的字符串（含逗号/空格不切分）。"""
    result: List[str] = []
    cur: List[str] = []
    inq = False
    i = 0
    while i < len(text):
        c = text[i]
        if inq:
            cur.append(c)
            if c == "\\" and i + 1 < len(text):
                cur.append(text[i + 1])
                i += 2
                continue
            if c == '"':
                inq = False
        elif c == '"':
            inq = True
            cur.append(c)
        elif c == ",":
            result.append("".join(cur))
            cur = []
        else:
            cur.append(c)
        i += 1
    result.append("".join(cur))
    return [p.strip() for p in result]


def _asm_instr(line: str, symtab: SymbolTable, symbols: List[str], compact: bool = False, wide: bool = False) -> Optional[bytes]:
    """Parse one assembly instruction line and encode to bytes.

    ``compact`` 为紧凑 stub 格式时使用 CAD 编码：
    - USUBR/FUNC 为 3 字节（``35 <argc> <idx8>`` / ``51 <argc> <idx8>``）；
      大文件（``wide=True``，nsyms>256）用 5/6 字节宽格式
      （``35 <argc> <idx16> <flags=3>`` / ``51 <argc> <idx16> <flags=1> 00``）
    - PUSH_VALUE[0] 为单字节 ``03``；idx>0 仍为 ``03 <u16>``
    """
    content = _strip_hex_bytes(_ADDR_PREFIX.sub("", line))
    if not content:
        return None

    m = _INSTR_RE.match(content)
    if not m:
        return None

    mnemonic = m.group(1).upper()
    rest = m.group(2).strip()
    operands = _parse_ops(rest, symtab)

    if mnemonic == "GET_LOCAL_WIDE":
        # Wide GET_LOCAL opcode (0x5c); canonical name in NAME_TO_OPCODE.
        from asm.opcodes import encode_op_u16

        return encode_op_u16(NAME_TO_OPCODE["GET_LOCAL_WIDE"], int(operands[0]) if operands else 0)

    if compact:
        if mnemonic in ("DEFUN", "DEFUN_ALT") and len(operands) == 4:
            # 紧凑 stub DEFUN 头为 argc 编码 `14 <argc>x3 <mode>`：
            # 4 个操作数直接作为原始字节写回（DEFUN 1, 1, 1, 0）。
            return bytes([0x14 if mnemonic == "DEFUN" else 0x15]) + bytes(
                int(o) & 0xFF for o in operands
            )
        if mnemonic == "USUBR" and operands:
            if wide:
                # 大文件宽格式：`35 <argc> <idx16> <flags=3>`
                flags = int(operands[2]) if len(operands) > 2 else 3
                return encode_usubr(int(operands[0]), int(operands[1]) if len(operands) > 1 else 0, flags)
            return encode_usubr3(int(operands[0]), int(operands[1]) if len(operands) > 1 else 0)
        if mnemonic == "FUNC" and operands:
            if wide:
                # 大文件宽格式：`51 <argc> <idx16> <flags=1> 00`
                flags = int(operands[2]) if len(operands) > 2 else 1
                return encode_func(int(operands[0]), int(operands[1]) if len(operands) > 1 else 0, flags)
            return encode_func3(int(operands[0]), int(operands[1]) if len(operands) > 1 else 0)
        if mnemonic == "PUSH_VALUE" and operands and int(operands[0]) == 0:
            # 小文件（3 字节 stub）中调用后清理占位 `00 03` 的 PUSH_VALUE[0]
            # 为单字节 `03`。大文件宽格式下 PUSH_VALUE[0] 是 3 字节 `03 00 00`
            # （CAD 大文件实测），压缩为单字节会丢字节，保持 3 字节。
            if not wide:
                return bytes([0x03])

    return encode_instruction(mnemonic, operands)


def _parse_ops(text: str, symtab: SymbolTable) -> List:
    """Parse comma-separated operands, resolving symbol names to indices.

    引号包裹的 ``"..."`` 操作数是字符串常量（_quote_lasm_string 产物），
    解引号后在符号表里查索引。
    """
    if not text.strip():
        return []

    result: List[Any] = []
    for p in _split_ops(text):
        if not p:
            continue
        if p.startswith('"'):
            val = _unquote_lasm_string(p)
            # 引号操作数可能是 STRING/REAL 常量槽，或带特殊字符的 SYMBOL 槽
            for key in (f"__str_{val}__", f"__real_{val}__", val):
                if key in symtab.name_to_idx:
                    result.append(symtab.name_to_idx[key])
                    break
            else:
                raise ValueError(f"Cannot resolve string operand: {val}")
        elif p.lstrip('-').isdigit():
            # 纯整数操作数（DEFUN argc 编码、INIT_ARGS 等）优先解析为整数，
            # 避免与符号表中纯数字名的槽索引冲突。
            result.append(int(p))
        elif p in symtab.name_to_idx:
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
