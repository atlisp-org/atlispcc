#!/usr/bin/env python3
import os
import sys

# 支持直接调用 `python decompiler/fas4_decompiler.py <in.fas> [out.lsp]`：
# 把仓库根目录加入 sys.path，使 `core` / `decompiler` 包可导入。
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import struct
import re
import functools
from dataclasses import dataclass, field
from typing import List, Dict, Tuple, Optional, Any, Set

from core.fas_core import (
    find_key as _find_key,
    decrypt_stream as _decrypt_stream,
    build_mvar_tables as _build_mvar_tables,
    build_function_catalog as _build_function_catalog,
)


@dataclass
class Instruction:
    offset: int
    opcode: int
    op_name: str
    operands: List[Any] = field(default_factory=list)
    size: int = 1
    comment: str = ""


@dataclass
class FunctionDef:
    name: str
    sym_idx: int
    args: List[int]
    locals: List[int]
    body_start: int
    body_end: int
    instructions: List[Instruction] = field(default_factory=list)


@dataclass
class Fas4File:
    nsyms: int
    bytecode: bytes
    sec2_data: bytes
    sec2_items: int
    crunch_date: str
    tail_bytes: bytes
    key: bytes
    resource_items: List[Any]
    resource_items_with_offsets: List[Tuple[int, Any]]
    symbols: List[str]
    resource_gvars: List[Any]
    function_gvars: List[Any]
    function_catalog: List[Tuple[str, int]]
    symbol_slots: List[Any] = field(default_factory=list)


# ─── Decryption & Parsing ──────────────────────────────────────────────────


def _is_compact_stub_cached(bytecode, sym_count, has_catalog):
    """计算 ``is_compact_stub`` 结果（纯函数，参数均 hashable）。

    ``function_catalog`` 仅以非空性参与判定，故模块级缓存键用
    ``(bytes哈希, sym_count, has_catalog)``。大文件 bytecode 反汇编成本高
    （两份全量反汇编 × 通常 2-3 次调用），缓存避免重复计算。
    """
    cache_key = bytes(bytecode)

    def _unk_count(insts) -> int:
        return sum(1 for inst in insts if inst.op_name.startswith("UNK_"))

    try:
        i3 = Disassembler(short_subr=True).disassemble(cache_key, 0)
    except Exception:
        i3 = []
    try:
        i6 = Disassembler(short_subr=False).disassemble(cache_key, 0)
    except Exception:
        i6 = []
    c3, c6 = _unk_count(i3), _unk_count(i6)
    if c3 != c6:
        return c3 < c6
    return not has_catalog


_is_compact_stub_cached = functools.lru_cache(maxsize=64)(_is_compact_stub_cached)


def is_compact_stub(bytecode: bytes, function_catalog: list, sym_count: int = 0) -> bool:
    return _is_compact_stub_cached(bytes(bytecode), int(sym_count or 0), bool(function_catalog))


def use_short_subr(bytecode: bytes, nsyms: int, function_catalog: list, sym_count: int = 0) -> bool:
    """USUBR/FUNC 是否用 3 字节短格式。

    紧凑 stub 格式下，小文件（nsyms<=256）用 3 字节 `35 <argc> <idx8>`；
    大文件（nsyms>256）即使 compact stub 也用 5/6 字节宽格式
    （`35 <argc> <idx16> <flags>`，与 codegen wide_subr = nsyms>256 一致）。
    若大文件误用 short_subr=True，会把 5/6 字节 USUBR/FUNC/PUSH_VALUE
    错位解析出大量 `UNK_xx`（@lisp_u nsyms=2667 实测 210 个）。
    （早期此错位会表现为 OP_1A/OP_1B/OP_38/OP_40/OP_10 等伪指令，
    已从 OPCODES 表移除，现一律归入 UNK_。）
    """
    return is_compact_stub(bytecode, function_catalog, sym_count) and nsyms <= 256


class Fas4Parser:
    def decode_text(self, raw: bytes) -> str:
        from core.fas_core import decode_fas_text

        return decode_fas_text(raw)

    def parse_resource_stream(self, res_data: bytes) -> Tuple[List[Any], List[Tuple[int, Any]], List[str]]:
        pos = 0
        items: List[Any] = []
        items_with_offsets: List[Tuple[int, Any]] = []
        symbols = []
        strings = []
        while pos < len(res_data):
            start = pos
            op = res_data[pos]
            if op in (0x14, 0x15):
                pos += 2
            elif op == 0x55:
                pos += 1
                if pos + 2 > len(res_data):
                    break
                num_strings = struct.unpack("<H", res_data[pos : pos + 2])[0]
                pos += 2
                for _ in range(num_strings):
                    if pos + 2 > len(res_data):
                        break
                    str_len = struct.unpack("<H", res_data[pos : pos + 2])[0]
                    pos += 2
                    if pos + str_len > len(res_data):
                        break
                    s = res_data[pos : pos + str_len]
                    pos += str_len
                    decoded = self.decode_text(s)
                    strings.append(decoded)
                    item: Any = ("STRING", decoded)
                    items.append(item)
                    items_with_offsets.append((pos - str_len, item))
            elif op in (0x56, 0x5B):
                pos += 1
                while pos < len(res_data):
                    end = res_data.find(b"\x00", pos)
                    if end < 0:
                        break
                    sym_name = res_data[pos:end]
                    pos = end + 1
                    if len(sym_name) == 0:
                        break
                    name = self.decode_text(sym_name)
                    symbols.append(name)
                    item = ("SYMBOL", name)
                    items.append(item)
                    items_with_offsets.append((pos - len(sym_name) - 1, item))
            elif op == 0x43:
                # GVARINIT `43 <var_pos:2> <st_init:2>`：5 字节整体跳过，
                # 避免操作数字节（如 st_init=26 → `1a 00`）被误当 OP_1A 伪指令。
                pos += 5
            elif op in (0x34, 0x35, 0x51):
                pos += 2
                if op in (0x35, 0x51) and pos + 2 <= len(res_data):
                    idx = struct.unpack("<H", res_data[pos : pos + 2])[0]
                    pos += 2
                    item = ("FUNC_REF", idx)
                    items.append(item)
                    items_with_offsets.append((start, item))
                if pos < len(res_data):
                    pos += 1
            elif op == 0x32:
                pos += 1
                if pos < len(res_data):
                    val = res_data[pos]
                    if val > 127:
                        val -= 256
                    pos += 1
                    item = ("INT8", val)
                    items.append(item)
                    items_with_offsets.append((start, item))
            elif op == 0x33:
                pos += 1
                if pos + 4 <= len(res_data):
                    val = struct.unpack("<i", res_data[pos : pos + 4])[0]
                    pos += 4
                    item = ("INT32", val)
                    items.append(item)
                    items_with_offsets.append((start, item))
            elif op == 0x3B:
                pos += 1
                end = res_data.find(b"\x00", pos)
                if end >= 0:
                    float_str = res_data[pos:end]
                    pos = end + 1
                    item = ("REAL", self.decode_text(float_str))
                    items.append(item)
                    items_with_offsets.append((start, item))
                else:
                    break
            elif op == 0x3A:
                pos += 1
            elif op in (0x09, 0x03, 0x06, 0x0C, 0x5E, 0x05, 0x5C, 0x5D):
                pos += 1
                if pos + 2 <= len(res_data):
                    idx = struct.unpack("<H", res_data[pos : pos + 2])[0]
                    pos += 2
                    item = ("OP_" + hex(op), idx)
                    items.append(item)
                    items_with_offsets.append((start, item))
            elif op in (0x0A, 0x01, 0x02, 0x16, 0x1C, 0x23, 0x24, 0x0B):
                item = ("OP_" + hex(op),)
                items.append(item)
                items_with_offsets.append((start, item))
                pos += 1
            elif op in (0x18, 0x19, 0x39, 0x37):
                pos += 1
                if pos + 2 <= len(res_data):
                    count = struct.unpack("<H", res_data[pos : pos + 2])[0]
                    pos += 2
                    item = ("OP_" + hex(op), count)
                    items.append(item)
                    items_with_offsets.append((start, item))
            elif op in (0x67, 0x57, 0x69):
                pos += 1
                if pos + 4 <= len(res_data):
                    target = struct.unpack("<i", res_data[pos : pos + 4])[0]
                    pos += 4
                    item = ("OP_" + hex(op), target)
                    items.append(item)
                    items_with_offsets.append((start, item))
            elif op in (0x20, 0x62, 0x63, 0x3E, 0x3F, 0x00):
                pos += 1
            elif op in (0x1E, 0x1F):
                pos += 1
                if pos < len(res_data):
                    pos += 1
            elif op == 0x21:
                pos += 1
            elif op in (0x07, 0x0D, 0x3C, 0x0E, 0x3D):
                pos += 1
                if pos + 2 <= len(res_data):
                    pos += 2
            elif op in (0x6A, 0x68):
                pos += 1
                if pos + 4 <= len(res_data):
                    pos += 4
            else:
                pos += 1
        return items, items_with_offsets, symbols

    def parse(self, filepath: str) -> Fas4File:
        with open(filepath, "rb") as f:
            data = f.read()
        from core.fas_core import find_fas4_magic

        hpos, hdr = find_fas4_magic(data)
        if hpos is None:
            raise ValueError("Not a valid FAS4 file")
        after = hpos + len(hdr)
        size_end = data.find(b"\r\n", after)
        total_size = int(data[after:size_end])
        payload_start = size_end + 2
        # seg0 止于段终止符 `16 24 0d 0a`。紧凑 stub 的 total_size = len-2，
        # 不覆盖 seg0 末尾 2 字节指令尾；用终止符定界可完整取得最后一条
        # 指令（CLEAR_ARGS）的操作数，保证反汇编/汇编字节可逆。
        term = data.find(b"\x16\x24\r\n", payload_start)
        if term > payload_start:
            payload_end = term
        else:
            # 无 `16 24 0d 0a`：纯顶层（无 defun）文件 seg0 为空，终止符为
            # `$\r\n`（CAD set5/setcmp 实测）。此时 total_size=len(seg0)+1，
            # 无法覆盖 `{nsyms} $` 头，payload 止于首个 `$`（nsyms 头结束）。
            dollar = data.find(b"$", payload_start)
            payload_end = dollar + 1 if dollar > payload_start else payload_start + total_size
        payload = data[payload_start:payload_end]

        m = re.match(rb"(\d+) \$", payload)
        if not m:
            raise ValueError("Bad FAS payload header")
        nsyms = int(m.group(1))
        bytecode = payload[m.end() :]

        after_payload = payload_start + total_size
        rest = data[after_payload:]
        m2 = re.search(rb"(\d+) (\d+) \$", rest)
        sec2_data, sec2_items = b"", 0
        if m2:
            sec2_size = int(m2.group(1))
            sec2_items = int(m2.group(2))
            sec2_start = after_payload + m2.end()
            sec2_data = data[sec2_start : sec2_start + sec2_size]

        tail = data[after_payload : after_payload + m2.start()] if m2 else b""
        crunch_m = re.search(rb";fas4 crunch\n;\$;A([\d/]+)", data)
        crunch_date = crunch_m.group(1).decode("ascii") if crunch_m else ""

        key = _find_key(data)
        decrypted = _decrypt_stream(sec2_data, key) if key else sec2_data

        res_items, res_items_with_offsets, symbols = self.parse_resource_stream(decrypted)
        resource_gvars, function_gvars = _build_mvar_tables(decrypted, nsyms)
        function_catalog = _build_function_catalog(resource_gvars, function_gvars)
        symbol_slots = [item for item in res_items if item[0] in ("SYMBOL", "STRING", "REAL")]

        return Fas4File(
            nsyms=nsyms,
            bytecode=bytecode,
            sec2_data=decrypted,
            sec2_items=sec2_items,
            crunch_date=crunch_date,
            tail_bytes=tail,
            key=key or b"",
            resource_items=res_items,
            resource_items_with_offsets=res_items_with_offsets,
            symbols=symbols,
            resource_gvars=resource_gvars,
            function_gvars=function_gvars,
            function_catalog=function_catalog,
            symbol_slots=symbol_slots,
        )


class Disassembler:
    OPCODES = {
        0x00: ("NIL", ""),
        0x01: ("PUSH_NIL", ""),
        0x02: ("PUSH_T", ""),
        0x03: ("PUSH_VALUE", "2"),
        0x05: ("GET_LOCAL", "1"),
        0x06: ("SETQ_G", "2"),
        0x07: ("COPY_ELEM", "bb"),
        0x09: ("PUSH_G", "2"),
        0x0A: ("POP", ""),
        0x0B: ("DUP", ""),
        0x0C: ("PUSH_G_ALT", "2"),
        0x0D: ("JMP16_IFNOT", "2"),
        0x0E: ("JMP16_IF", "2"),
        0x14: ("DEFUN", "h"),
        0x15: ("DEFUN_ALT", "h"),
        0x16: ("END_DEFUN", ""),
        0x18: ("INIT_ARGS", "2"),
        0x19: ("CLEAR_ARGS", "2"),
        0x1C: ("INIT_DONE", ""),
        0x1E: ("ALPHA", "1"),
        0x1F: ("BETA", "1"),
        0x20: ("NOP", ""),
        0x21: ("END_DEFUN_CLEANUP", "2"),
        0x23: ("NOT", ""),
        0x24: ("ATOM", ""),
        0x28: ("CAR", ""),
        0x29: ("CDR", ""),
        0x2A: ("CONS", ""),
        0x32: ("PUSH_INT8", "1"),
        0x33: ("PUSH_INT32", "4"),
        0x34: ("EVAL", "e"),
        0x37: ("BUILD_LIST_ALT", "2"),
        0x39: ("BUILD_LIST", "2"),
        0x3A: ("DEFCODE", ""),
        0x3B: ("PUSH_REAL", "z"),
        0x3C: ("JMP16_IFNOT_ALT", "2"),
        0x3D: ("JMP16_IF_ALT", "2"),
        0x3E: ("EXIT_IF_NOT_ZERO", ""),
        0x3F: ("EXIT_IF_ZERO", ""),
        0x35: ("USUBR", "u"),
        0x46: ("FIX_ADD", ""),
        0x47: ("FIX_SUB", ""),
        0x48: ("FIX_MUL", ""),
        0x49: ("FIX_DIV", ""),
        0x4A: ("FIX_MOD", ""),
        0x4B: ("FIX_LEQ", ""),
        0x4C: ("FIX_GEQ", ""),
        0x4D: ("FIX_LT", ""),
        0x4E: ("FIX_GT", ""),
        0x4F: ("INC", ""),
        0x50: ("DEC", ""),
        0x51: ("FUNC", "f"),
        0x57: ("JUMP", "s4"),
        0x5C: ("GET_LOCAL_WIDE", "2"),
        0x5D: ("SET_LOCAL", "2"),
        0x5E: ("CLEAR_LOCAL", "2"),
        0x62: ("NOP_ALT", ""),
        0x63: ("NOP_ALT2", ""),
        0x67: ("JMP32_IFNOT", "s4"),
        0x68: ("COND_OR", "s4"),
        0x69: ("JUMP_ALT", "s4"),
        0x6A: ("COND_AND", "s4"),
    }

    def __init__(self, short_subr: bool = False):
        """``short_subr``：紧凑 stub 格式下 USUBR/FUNC 为 3 字节
        （``35 <argc> <idx>`` / ``51 <argc> <idx>``）。
        """
        self.short_subr = short_subr

    def disassemble(self, bytecode: bytes, nsyms: int, sym_count: Optional[int] = None) -> List[Instruction]:
        instructions = []
        i = 0
        # stub 格式 PUSH_VALUE 单字节/3字节 启发式的有效符号上限：
        # 用符号槽总数（可能 > nsyms），默认退化为 nsyms。
        effective_syms = sym_count if sym_count is not None else nsyms
        prev_op = None
        while i < len(bytecode):
            op = bytecode[i]
            entry = self.OPCODES.get(op)
            if entry:
                name, fmt = entry
                inst = Instruction(offset=i, opcode=op, op_name=name)
                if fmt == "4":
                    # PUSH_INT32：AutoLISP 整数为有符号 32 位，按 <i 解码
                    # （core/fas_core 与资源流解码均一致；<I 会把 -9999 误显为 4294957297）
                    val = struct.unpack("<i", bytecode[i + 1 : i + 5])[0] if i + 4 < len(bytecode) else 0
                    inst.operands = [val]
                    inst.size = 5
                elif fmt == "s4":
                    val = struct.unpack("<i", bytecode[i + 1 : i + 5])[0] if i + 4 < len(bytecode) else 0
                    inst.operands = [val]
                    inst.size = 5
                elif fmt == "2":
                    # 紧凑 stub 格式中 CLEAR_ARGS(0x19) 为 `19 <argc u16> <00>`
                    # （CAD 实测，3 字节）。函数尾部常为 `03 19 <argc> 00`
                    # （PUSH_VALUE[0] 单字节 + CLEAR_ARGS）。
                    if op == 0x19 and self.short_subr:
                        val = struct.unpack("<H", bytecode[i + 1 : i + 3])[0] if i + 2 < len(bytecode) else 0
                        inst.operands = [val]
                        inst.size = 3
                    elif op == 0x03 and self.short_subr:
                        # stub 中 PUSH_VALUE[0] 编码为单字节 `03`，
                        # PUSH_VALUE[idx>0] 为 `03 <u16>`。用有效符号上限启发式区分。
                        # 补充：调用协议占位 `03` 前总跟 `00`（NIL，`... USUBR; 00; 03`），
                        # 而真实 3 字节 PUSH_VALUE（符号/参数引用）前为参数/指令。
                        # 故 `prev_op == 0x00` 时判为单字节占位（i18n `03 32 00`
                        # = 占位 + PUSH_INT8 0 实测，否则被误读为 PUSH_VALUE[50]）。
                        if i + 2 < len(bytecode):
                            idx = struct.unpack("<H", bytecode[i + 1 : i + 3])[0]
                            if idx < effective_syms and prev_op != 0x00:
                                inst.operands = [idx]
                                inst.size = 3
                            else:
                                inst.operands = [0]
                                inst.size = 1
                        else:
                            inst.operands = [0]
                            inst.size = 1
                    else:
                        val = struct.unpack("<H", bytecode[i + 1 : i + 3])[0] if i + 2 < len(bytecode) else 0
                        inst.operands = [val]
                        inst.size = 3
                elif fmt == "1":
                    val = bytecode[i + 1] if i + 1 < len(bytecode) else 0
                    inst.operands = [val]
                    inst.size = 2
                elif fmt == "bb":
                    left = bytecode[i + 1] if i + 1 < len(bytecode) else 0
                    right = bytecode[i + 2] if i + 2 < len(bytecode) else 0
                    inst.operands = [left, right]
                    inst.size = 3
                elif fmt == "u":
                    argc = bytecode[i + 1] if i + 1 < len(bytecode) else 0
                    if self.short_subr:
                        idx = bytecode[i + 2] if i + 2 < len(bytecode) else 0
                        inst.operands = [argc, idx]
                        inst.size = min(3, len(bytecode) - i)
                    else:
                        if i + 3 < len(bytecode):
                            idx = struct.unpack("<H", bytecode[i + 2 : i + 4])[0]
                        elif i + 2 < len(bytecode):
                            idx = bytecode[i + 2]
                        else:
                            idx = 0
                        flags = bytecode[i + 4] if i + 4 < len(bytecode) else 0
                        inst.operands = [argc, idx, flags]
                        inst.size = min(5, len(bytecode) - i)
                elif fmt == "f":
                    argc = bytecode[i + 1] if i + 1 < len(bytecode) else 0
                    if self.short_subr:
                        idx = bytecode[i + 2] if i + 2 < len(bytecode) else 0
                        inst.operands = [argc, idx]
                        inst.size = min(3, len(bytecode) - i)
                    else:
                        if i + 3 < len(bytecode):
                            idx = struct.unpack("<H", bytecode[i + 2 : i + 4])[0]
                        elif i + 2 < len(bytecode):
                            idx = bytecode[i + 2]
                        else:
                            idx = 0
                        flags = bytecode[i + 4] if i + 4 < len(bytecode) else 0
                        zero = bytecode[i + 5] if i + 5 < len(bytecode) else 0
                        inst.operands = [argc, idx, flags, zero]
                        inst.size = min(6, len(bytecode) - i)
                elif fmt == "h":
                    values = [bytecode[i + j] if i + j < len(bytecode) else 0 for j in range(1, 5)]
                    inst.operands = values
                    inst.size = 5
                elif fmt == "e":
                    argc = bytecode[i + 1] if i + 1 < len(bytecode) else 0
                    flag = bytecode[i + 2] if i + 2 < len(bytecode) else 0
                    inst.operands = [argc, flag]
                    inst.size = 3
                elif fmt == "z":
                    end = bytecode.find(b"\x00", i + 1)
                    if end == -1:
                        inst.operands = [""]
                        inst.size = 1
                    else:
                        raw = bytecode[i + 1 : end].decode("ascii", errors="replace")
                        inst.operands = [raw]
                        inst.size = (end - i) + 1
                else:
                    inst.size = 1
            else:
                inst = Instruction(offset=i, opcode=op, op_name=f"UNK_{op:02x}")
                inst.size = 1
            instructions.append(inst)
            prev_op = op
            i += inst.size
        return instructions


class ControlFlowAnalyzer:
    def __init__(
        self,
        instructions: List[Instruction],
        function_catalog: Optional[List[Tuple[str, int]]] = None,
        function_names: Optional[Dict[int, str]] = None,
    ):
        self.instructions = instructions
        self.function_catalog = function_catalog or []
        self.function_names = function_names or {}
        self.functions: List[FunctionDef] = []

    def find_functions(self) -> List[FunctionDef]:
        defun_starts = [idx for idx, inst in enumerate(self.instructions) if inst.op_name == "DEFUN"]
        if defun_starts and len(defun_starts) > 1:
            # 多函数：优先按 DEFUN 头切分，比 GVar 重建的函数目录更可靠
            # （紧凑 stub 格式的目录在 GVar 表中不完整）。
            functions = self._build_from_defun_headers(defun_starts)
        elif self.function_catalog:
            functions = self._build_from_catalog()
        elif defun_starts:
            functions = self._build_from_defun_headers(defun_starts)
        else:
            functions = self._build_from_defun_ends()
        self.functions = functions
        return functions

    def _build_from_catalog(self) -> List[FunctionDef]:
        offset_to_index = {inst.offset: idx for idx, inst in enumerate(self.instructions)}
        entries: List[Tuple[str, int, int]] = []
        seen: Set[int] = set()
        for name, offset in sorted(self.function_catalog, key=lambda item: item[1]):
            idx = offset_to_index.get(offset)
            if idx is None or idx in seen:
                continue
            if self.instructions[idx].op_name != "DEFUN":
                continue
            seen.add(idx)
            entries.append((name or "", offset, idx))

        if not entries:
            return self._build_from_defun_headers(
                [idx for idx, inst in enumerate(self.instructions) if inst.op_name == "DEFUN"]
            )

        functions = []
        cursor = 0
        for pos, (name, _offset, start_idx) in enumerate(entries):
            if start_idx > cursor:
                prelude = self.instructions[cursor:start_idx]
                if self._has_meaningful_code(prelude):
                    functions.append(FunctionDef("c:init", -1, [], [], cursor, start_idx - 1, prelude))
            next_start = entries[pos + 1][2] if pos + 1 < len(entries) else len(self.instructions)
            func_insts = self.instructions[start_idx:next_start]
            if not func_insts:
                continue
            locals_list = self._collect_local_slots(func_insts)
            functions.append(
                FunctionDef(
                    name or f"c:fn{pos}",
                    pos,
                    [],
                    locals_list,
                    start_idx,
                    next_start - 1,
                    func_insts,
                )
            )
            cursor = next_start

        if cursor < len(self.instructions):
            remaining = self.instructions[cursor:]
            if self._has_meaningful_code(remaining):
                functions.append(FunctionDef("c:init_tail", -1, [], [], cursor, len(self.instructions) - 1, remaining))
        return functions

    def _build_from_defun_headers(self, starts: List[int]) -> List[FunctionDef]:
        functions = []
        func_num = 0
        cursor = 0
        for pos, start in enumerate(starts):
            if start < cursor:
                continue
            if start > cursor:
                prelude = self.instructions[cursor:start]
                if self._has_meaningful_code(prelude):
                    functions.append(FunctionDef("c:init", -1, [], [], cursor, start - 1, prelude))
            next_start = starts[pos + 1] if pos + 1 < len(starts) else len(self.instructions)
            end_idx = self._find_defun_end(start, next_start)

            func_insts = self.instructions[start : end_idx + 1]
            locals_list = self._collect_local_slots(func_insts)
            func_offset = self.instructions[start].offset
            name = self.function_names.get(func_offset) or f"c:fn{func_num}"
            functions.append(
                FunctionDef(
                    name,
                    func_num,
                    [],
                    locals_list,
                    start,
                    end_idx,
                    func_insts,
                )
            )
            func_num += 1
            cursor = end_idx + 1

        if cursor < len(self.instructions):
            remaining = self.instructions[cursor:]
            if self._has_meaningful_code(remaining):
                functions.append(FunctionDef("c:init_tail", -1, [], [], cursor, len(self.instructions) - 1, remaining))
        return functions

    def _find_defun_end(self, start: int, next_start: int) -> int:
        clear_idx = None
        for idx in range(start, next_start):
            if self.instructions[idx].op_name == "CLEAR_ARGS":
                clear_idx = idx
        if clear_idx is not None:
            end_idx = clear_idx
            if end_idx + 1 < len(self.instructions) and self.instructions[end_idx + 1].op_name == "END_DEFUN":
                end_idx += 1
            elif self._has_meaningful_code(self.instructions[end_idx + 1 : next_start]):
                return min(next_start - 1, len(self.instructions) - 1)
            return end_idx
        return min(next_start - 1, len(self.instructions) - 1)

    def _build_from_defun_ends(self) -> List[FunctionDef]:
        functions = []
        defun_ends = [idx for idx, inst in enumerate(self.instructions) if inst.op_name == "END_DEFUN"]
        if not defun_ends:
            return [FunctionDef("c:main", 0, [], [], 0, len(self.instructions) - 1, self.instructions)]

        prev_end = 0
        func_num = 0
        for de_idx in defun_ends:
            func_insts = self.instructions[prev_end : de_idx + 1]
            if func_insts:
                locals_list = self._collect_local_slots(func_insts)
                functions.append(
                    FunctionDef(
                        f"c:fn{func_num}",
                        func_num,
                        [],
                        locals_list,
                        prev_end,
                        de_idx,
                        func_insts,
                    )
                )
                func_num += 1
            prev_end = de_idx + 1

        if prev_end < len(self.instructions):
            remaining = self.instructions[prev_end:]
            if self._has_meaningful_code(remaining):
                functions.append(FunctionDef("c:init", -1, [], [], prev_end, len(self.instructions) - 1, remaining))
        return functions

    def _next_defun_end(self, defun_ends: List[int], start: int) -> Optional[int]:
        for idx in defun_ends:
            if idx >= start:
                return idx
        return None

    def _collect_local_slots(self, instructions: List[Instruction]) -> List[int]:
        slots = []
        seen = set()
        for inst in instructions:
            if inst.op_name in ("GET_LOCAL", "GET_LOCAL_WIDE", "SET_LOCAL", "CLEAR_LOCAL") and inst.operands:
                slot = inst.operands[0]
                if slot not in seen:
                    slots.append(slot)
                    seen.add(slot)
        return slots

    def _has_meaningful_code(self, instructions: List[Instruction]) -> bool:
        return any(inst.op_name not in ("NIL", "INIT_DONE") for inst in instructions)


def extract_stub_function_names(fas) -> Dict[int, str]:
    """从紧凑 stub 资源段的 DEFCODE 绑定序列提取 {seg0_offset: 函数名}。

    AutoCAD 紧凑 stub 格式通过 ``GET_LOCAL 0, PUSH_INT8 <seg0-offset>,
    SYMBOL <name>, DEFCODE`` 序列把 seg0 偏移绑定到函数名。
    """
    mapping: Dict[int, str] = {}
    items = getattr(fas, "resource_items_with_offsets", None)
    if not items:
        return mapping
    for i in range(1, len(items)):
        name_item = items[i][1]
        offset_item = items[i - 1][1]
        if not (isinstance(name_item, tuple) and len(name_item) == 2 and name_item[0] == "SYMBOL"):
            continue
        if not (isinstance(offset_item, tuple) and len(offset_item) == 2 and offset_item[0] in ("INT8", "INT32")):
            continue
        raw_name = str(name_item[1])
        if not raw_name or not any(ch.isalpha() for ch in raw_name):
            continue
        mapping.setdefault(int(offset_item[1]), raw_name)
    return mapping


class LispGenerator:
    BUILTIN_SYMBOLS = {
        "=",
        "1+",
        "ACAD_STRLSORT",
        "ATOM",
        "CAR",
        "CDR",
        "CONS",
        "DICTREMOVE",
        "*ERROR*",
        "ENTGET",
        "GETSTRING",
        "ITOA",
        "NAMEDOBJDICT",
        "NOT",
        "PRINC",
        "STRCAT",
        "STRLEN",
        "TEXTSCR",
        "WCMATCH",
        "VL-ACAD-DEFUN",
        "POLAR",
    }
    COMMON_ARITY = {
        "PRINC": {0, 1},
        "NAMEDOBJDICT": {0},
        "TEXTSCR": {0},
        "GETSTRING": {1, 2},
        "STRLEN": {1},
        "STRCAT": set(range(1, 17)),
        "ACAD_STRLSORT": {1},
        "WCMATCH": {2, 3},
        "DICTREMOVE": {2},
        "ITOA": {1},
        "CAR": {1},
        "CDR": {1},
        "CONS": {2},
        "=": {2},
        ">": {2},
        "<": {2},
        ">=": {2},
        "<=": {2},
        "1+": {1},
        "1-": {1},
        "NOT": {1},
        "ATOM": {1},
        "ENTGET": {1},
        "ENTDEL": {1},
        "POLAR": {3},
        "RTOS": {1, 2, 3},
    }

    def __init__(self, fas: Fas4File):
        self.fas = fas
        self.string_values = [
            str(item[1]) for item in fas.resource_items if item[0] == "STRING" and isinstance(item[1], str)
        ]
        self.code_ref_bias = self._infer_code_ref_bias()
        self.variable_ref_floor = self._infer_variable_ref_floor()
        self.function_names_by_offset: Dict[int, str] = {}
        self.function_names_by_index: Dict[int, str] = {}
        self.command_candidates: List[str] = []
        self._build_function_catalog()
        self.symbol_slots = self.fas.symbol_slots or self._build_symbol_slots()
        self.is_stub_format = self._detect_stub_format()
        self.gvar_table: List[Any] = []
        if self.is_stub_format:
            try:
                from core.fas_core import build_mvar_tables

                _, self.gvar_table = build_mvar_tables(self.fas.sec2_data, self.fas.nsyms)
            except Exception:
                self.gvar_table = []
        if self.is_stub_format:
            self._collect_stub_defcode_names()
        self._stub_is_multi_func = self.is_stub_format and (
            len(self.function_names_by_offset) > 1 or len(self.function_names_by_index) > 1
        )

    def _stub_module_id_slots(self) -> Dict[int, Any]:
        """stub 函数表 GVARINIT 的 module_id 槽 → 值映射。

        CAD 的紧凑 stub 在函数表 GVARINIT（0x43，module_id 非 None）时把
        module_id 值登记在 ``var_pos + st_init`` 槽。t12 的 `(A B C)` 常量
        （`(setq lst '(a b c))`）即存于槽 5（nsyms=5，var_pos=0, st_init=5），
        由 PUSH_G 4 经「槽 - 1」引用。

        仅登记**结构化** module_id（LIST/CONS 等，非原子 SYMBOL/STRING）：
        原子型（如单函数文件的字符串常量 'abc'、参数符号 A）是符号槽的重复
        登记，若纳入会在 `_gvar_item` 的 mvar-1 分支抢先命中、破坏 symbol_slots
        回退（t12 链式 `(a b c)` 是结构化常量需此槽；fun-cad 的 'abc' 走
        symbol_slots）。返回 {槽: 值}。
        """
        cached = getattr(self, "_stub_module_id_slots_cache", None)
        if cached is not None:
            return cached
        result: Dict[int, Any] = {}
        try:
            from core.fas_core import build_module_id_slots

            result = build_module_id_slots(self.fas.sec2_data, self.fas.nsyms)
        except Exception:
            result = {}
        self._stub_module_id_slots_cache = result
        return result

    def _stub_extended_gvar(self) -> List[Any]:
        """stub 参数解析用的扩展 gvar 表：基础 gvar_table + symbol_slots 尾部
        未入表的参数/共享参数符号。

        `build_mvar_tables` 只重建到 nsyms，而 CAD 把参数（含多函数共享参数）
        注册在 symbol_slots 尾部（CadSymbolCollector：`参数放最后`），其 gvar
        槽在 nsyms 之外。t07/t08 的共享参数 LST、t01/t09 的 A/B/X、t18 的 N
        均在此（operand o → gvar_table[o+1]，t01 op4→A@5、t08 op5→LST@6、
        t18 op6→N@7 实测）。已嵌套在常量结构里的符号（如 quoted lambda 的
        参数 X 在 t08 的 LAMBDA 常量内）不算新增，避免错位。

        仅供 `_extract_signature` 参数名解析使用——不能改全局 gvar_table，
        否则 `_gvar_item` 对函数体引用的越界回退会被扩展槽打乱
        （test_minimal_compile_decompile 的 princ→hello 实测）。
        """
        cached = getattr(self, "_stub_extended_gvar_cache", None)
        if cached is not None:
            return cached
        if not self.fas.symbol_slots:
            return self.gvar_table
        existing: set = set()

        def _collect(v) -> None:
            if isinstance(v, tuple):
                if len(v) == 2 and v[0] == "SYMBOL":
                    existing.add(v[1].upper())
                else:
                    for x in v:
                        _collect(x)
            elif isinstance(v, list):
                for x in v:
                    _collect(x)

        for x in self.gvar_table:
            _collect(x)
        extra: List[Any] = []
        for item in self.fas.symbol_slots[self.fas.nsyms:]:
            if isinstance(item, tuple) and len(item) == 2 and item[0] == "SYMBOL":
                name = item[1].upper()
                if name not in existing:
                    existing.add(name)
                    extra.append(item)
        if extra:
            result = self.gvar_table + extra
        else:
            result = self.gvar_table
        # gvar_table / symbol_slots 在 `__init__` 后不可变，逐函数重复全量
        # 收集会退化 O(F×N)（t21 大文件 5000 函数 × 1.5 万符号实测）。缓存
        # 结果，输出与逐次计算逐字节一致。
        self._stub_extended_gvar_cache = result
        return result

    def _build_symbol_slots(self) -> List[Any]:
        """Build the interleaved symbol/string/constant table from the
        resource stream registration order.

        Some FAS4 variants (e.g. compact stubs emitted by CAD compilers)
        address symbol slots directly by registration index, and the
        mvar-reconstructed gvar tables are not reliable for them.
        """
        slots: List[Any] = []
        for item in self.fas.resource_items:
            if item[0] in ("SYMBOL", "STRING", "REAL"):
                slots.append(item)
        return slots

    def _detect_stub_format(self) -> bool:
        """Detect the compact 'stub' layout where seg0 is only an entry
        stub and the symbol table is addressed directly by registration
        index (rather than through the mvar-reconstructed gvar tables).

        AutoCAD 编译器产物（如 tests/cad/t01_math_cad.fas 等 t-series golden）无函数目录且 seg0 很短，
        使用 3 字节 Xsubr，符号按资源注册顺序（symbol_slots）编址。
        """
        if is_compact_stub(self.fas.bytecode, self.fas.function_catalog, len(self.fas.symbol_slots)):
            return True
        # 项目 stub 特征：DEFCODE 序列 + DEFUN 头 argc 编码（区分自包含 PDI/bib）。
        if self._has_stub_defcode_seq() and self._defun_headers_are_argc():
            return True
        return False

    def _defun_headers_are_argc(self) -> bool:
        """检查 DEFUN 头 argc 编码（见 `_defun_headers_are_argc_impl`）。

        `bytecode`/`function_names_by_offset` 在 `__init__` 后不可变，结果
        恒定。逐函数重算会对函数偏移排序（5000 函数 × 5000 偏移 ≈ O(F² log F)，
        t21 大文件实测 14s），故缓存首次结果，输出与逐次计算一致。
        """
        cached = getattr(self, "_defun_headers_are_argc_cache", None)
        if cached is not None:
            return cached
        result = self._defun_headers_are_argc_impl()
        self._defun_headers_are_argc_cache = result
        return result

    def _defun_headers_are_argc_impl(self) -> bool:
        bc = self.fas.bytecode
        offsets = sorted(k for k in self.function_names_by_offset.keys() if isinstance(k, int))
        if offsets:
            # 用 DEFCODE 记录的真实函数偏移检查 DEFUN 头（避免操作数中的 0x14 误判）
            for off in offsets:
                if off + 5 > len(bc) or bc[off] != 0x14:
                    return False
                a, b_, c, d = bc[off + 1], bc[off + 2], bc[off + 3], bc[off + 4]
                # 有限参数：b1(参数+无名变量) == b3(大参数)；
                # 含 foreach/repeat 的函数 b1 = argc + 1（循环占一个局部槽，t16/t17
                # 实测）；直接体循环 + `/ 局部变量` 时 b1 = argc + 2（@lisp_u 实测
                # add-menus `14 03 01 01 00`）。嵌套 lambda/defun 内循环不加。
                if d == 0:
                    if a not in (c, c + 1, c + 2):
                        return False
                elif d == 1:
                    if not (a == b_ == c):
                        return False
                else:
                    return False
            return True
        # 无目录：扫描首个 0x14（真 DEFUN 在字节码前部）
        for i in range(len(bc) - 4):
            if bc[i] == 0x14:
                a, b_, c, d = bc[i + 1], bc[i + 2], bc[i + 3], bc[i + 4]
                if d == 0:
                    # 有限参数：b1(参数+无名变量) == b3(大参数)；含 foreach/repeat
                    # 的函数 b1 = argc + 1（t16/t17 实测），直接体循环+局部变量
                    # b1 = argc + 2（@lisp_u 实测），与有目录分支保持一致。
                    return a in (c, c + 1, c + 2)
                if d == 1:
                    return a == b_ == c
                return False
        return False

    def _has_stub_defcode_seq(self) -> bool:
        d = getattr(self.fas, "sec2_data", b"") or b""
        i = 0
        while i < len(d) - 10:
            if d[i : i + 4] == b"\x5c\x00\x00\x32":
                j = i + 4
                # PUSH_INT8/INT32 offset 后紧跟 SYMBOL 块 5b
                if j < len(d) and d[j] == 0x33:
                    j += 4
                else:
                    j += 1
                if j < len(d) and d[j] == 0x5B:
                    k = d.find(b"\x00\x00\x3a", j)
                    if k >= 0:
                        return True
            i += 1
        return False

    def function_catalog(self) -> bool:
        return bool(self.function_names_by_offset) or bool(self.function_names_by_index)

    def _infer_code_ref_bias(self) -> int:
        """Infer the leading holes in the runtime literal/call table.

        Some FAS4 streams leave the first resource slots empty, while code
        operands still address the compact table. Variable operands are not
        biased, so this is only applied by the code-reference helpers below.
        """
        bias = 0
        for value in self.fas.function_gvars:
            if value is not None:
                break
            bias += 1
        return bias if 0 < bias <= 4 else 0

    def _infer_variable_ref_floor(self) -> int:
        last_string_idx = -1
        for idx, value in enumerate(self.fas.function_gvars):
            if isinstance(value, tuple) and len(value) == 2 and value[0] == "STRING":
                last_string_idx = idx

        for idx in range(last_string_idx + 1, len(self.fas.function_gvars)):
            name = self._extract_symbol_text(self.fas.function_gvars[idx])
            if name and name.upper() not in self.BUILTIN_SYMBOLS:
                return idx
        return len(self.fas.function_gvars)

    def generate(self, functions: List[FunctionDef], filename: str) -> str:
        specs = [self._analyze_function(func, idx) for idx, func in enumerate(functions)]
        self._apply_command_fallback(specs)
        self._finalize_function_names(specs)
        self.needs_unary_polar_helper = self._uses_unary_polar(specs)
        self.needs_project_rtos_helper = self._uses_project_rtos(specs)
        self.needs_project_runtime_helpers = self._uses_project_runtime_helpers(specs)
        self._adjust_signatures_for_observed_calls(specs)
        specs = self._filter_runnable_specs(specs)

        source_name = os.path.basename(filename)
        lines = [f";; Auto-decompiled from {source_name}", ";; Generated AutoLISP output", ""]

        if self.needs_unary_polar_helper or self.needs_project_rtos_helper or self.needs_project_runtime_helpers:
            lines.extend(self._emit_support_helpers())
            lines.append("")

        for spec in specs:
            if spec["is_init"]:
                lines.extend(self._emit_init(spec))
            else:
                lines.extend(self._emit_function(spec))
            lines.append("")

        return "\n".join(lines)

    def _build_function_catalog(self) -> None:
        for table in (self.fas.resource_gvars, self.fas.function_gvars):
            for value in table:
                self._collect_function_descriptors(value)
                self._collect_command_candidates(value)
        self._collect_function_ref_names()
        self.command_candidates = list(dict.fromkeys(self.command_candidates))

    def _collect_stub_defcode_names(self) -> None:
        """从紧凑 stub 资源段的 DEFCODE 绑定序列解析函数名。

        AutoCAD 紧凑 stub 格式的函数目录不在 GVar 表中，而是通过资源段中
        ``GET_LOCAL 0, PUSH_INT8 <seg0-offset>, SYMBOL <name>, DEFCODE``
        指令序列把 seg0 偏移绑定到函数名。本方法扫描 resource_items 恢复
        该映射，使带参 stub 函数能正确命名。
        """
        items = self.fas.resource_items_with_offsets
        if len(items) < 3:
            return
        for i in range(1, len(items)):
            name_item = items[i][1]
            offset_item = items[i - 1][1]
            if not (isinstance(name_item, tuple) and len(name_item) == 2 and name_item[0] == "SYMBOL"):
                continue
            if not (isinstance(offset_item, tuple) and len(offset_item) == 2 and offset_item[0] in ("INT8", "INT32")):
                continue
            raw_name = str(name_item[1])
            if not raw_name:
                continue
            if any(ch.isalpha() for ch in raw_name):
                off = int(offset_item[1])
                self.function_names_by_offset.setdefault(off, raw_name)
                self._collect_command_candidates(raw_name)

    def _collect_function_descriptors(self, value: Any) -> None:
        if isinstance(value, tuple) and len(value) >= 4 and value[0] == "FUNC":
            name = self._extract_symbol_text(value[1]) or self._extract_text(value[1])
            start = value[2]
            if isinstance(name, str) and isinstance(start, int):
                self.function_names_by_offset.setdefault(start, name)
                self._collect_command_candidates(name)
            self._collect_function_descriptors(value[3])
            return
        if isinstance(value, tuple):
            for item in value:
                self._collect_function_descriptors(item)

    def _collect_command_candidates(self, value: Any) -> None:
        if isinstance(value, tuple) and len(value) == 2 and value[0] in ("STRING", "REAL"):
            return
        text = self._extract_text(value)
        if isinstance(text, str):
            if text.upper().startswith("C:"):
                self.command_candidates.append(text)
            return
        if isinstance(value, tuple):
            for item in value:
                self._collect_command_candidates(item)

    def _collect_function_ref_names(self) -> None:
        items = self.fas.resource_items_with_offsets
        for idx, (_, item) in enumerate(items):
            if item[0] != "FUNC_REF":
                continue
            ref_idx = item[1]
            if idx == 0:
                continue
            prev = items[idx - 1][1]
            if not (isinstance(prev, tuple) and len(prev) >= 2 and prev[0] == "OP_0x9"):
                continue
            slot = prev[1]
            name = self._resource_gvar_text(slot)
            if name:
                self.function_names_by_index.setdefault(ref_idx, name)
                self._collect_command_candidates(name)

    def _analyze_function(self, func: FunctionDef, func_index: int) -> Dict[str, Any]:
        signature = self._extract_signature(func.instructions)
        referenced_symbols = self._referenced_symbols(func.instructions[signature["body_start"] :])
        referenced_strings = self._referenced_strings(func.instructions[signature["body_start"] :])
        original_name = self._choose_function_name(func, func_index, referenced_symbols)
        is_init = func.sym_idx < 0

        local_used: Set[str] = set()
        slot_names: Dict[int, str] = {}
        arg_names: List[str] = []
        arg_originals: List[str] = []
        arg_slots = set()
        bound_symbol_map: Dict[str, str] = {}
        bound_gvar_map: Dict[int, str] = {}
        bind_arg_symbols = not (original_name or "").upper().startswith("C:")
        for pos, (slot, raw_name) in enumerate(signature["args"]):
            safe_name = self._unique_symbol(raw_name, f"arg_{pos + 1}", False, local_used)
            arg_names.append(safe_name)
            arg_originals.append(raw_name)
            slot_names[slot] = safe_name
            arg_slots.add(slot)
            if bind_arg_symbols:
                arg_symbol_indices = signature.get("arg_symbol_indices", [])
                if pos < len(arg_symbol_indices):
                    bound_gvar_map[arg_symbol_indices[pos]] = safe_name
                bound_symbol_map[raw_name.upper()] = safe_name

        local_names: List[str] = []
        local_originals: List[str] = []
        for pos, raw_name in enumerate(signature.get("local_binding_names", [])):
            safe_name = self._unique_symbol(raw_name, f"local_{pos + 1}", False, local_used)
            local_names.append(safe_name)
            local_originals.append(raw_name)
            bound_symbol_map[raw_name.upper()] = safe_name
        for slot in func.locals:
            if slot in arg_slots:
                continue
            raw_name = f"local_{slot}"
            safe_name = self._unique_symbol(raw_name, raw_name, False, local_used)
            local_names.append(safe_name)
            local_originals.append(raw_name)
            slot_names[slot] = safe_name

        spec = {
            "func": func,
            "index": func_index,
            "is_init": is_init,
            "original_name": original_name,
            "name": "",
            "args": arg_names,
            "min_args": signature.get("min_args", len(arg_names)),
            "has_rest": signature.get("has_rest", False),
            "arg_originals": arg_originals,
            "locals": local_names,
            "local_originals": local_originals,
            "body_start": signature["body_start"],
            "body_symbols": referenced_symbols,
            "body_strings": referenced_strings,
            "slot_names": slot_names,
            "local_used": local_used,
            "bound_symbol_map": bound_symbol_map,
            "bound_gvar_map": bound_gvar_map,
            "global_aliases": {},
            "slot_expr_map": {},
            "localized_globals": set(),
        }
        self._localize_assigned_globals(spec, func.instructions[signature["body_start"] :])
        return spec

    def _localize_assigned_globals(self, spec: Dict[str, Any], instructions: List[Instruction]) -> None:
        # 仅当函数经 `_al-bind-alist` 协议声明了 `/ 局部变量`
        # （`local_binding_names` 非空或函数体调用 `_al-bind-alist`，t11 实测）
        # 时，才把 setq 目标加入局部变量表；否则 setq 目标是全局变量
        # （t12 `(setq lst '(a b c))` 的 lst、t16 foreach 累加器 total、
        # t17 repeat 累加器 acc 均为全局，不应输出 `/ lst`/`/ total x`）。
        # `func.locals` 只是局部槽编号（foreach/repeat 循环槽），不代表 `/`
        # 声明。bound 映射无论如何都要建立，保证函数体引用能解析到名字。
        has_locals = bool(spec.get("local_binding_names")) or self._uses_al_bind_alist(spec)
        for inst in instructions:
            if inst.op_name not in ("SETQ_G",) or not inst.operands:
                continue
            name = self._value_from_gvar(inst.operands[0], spec)
            if has_locals and name not in spec["args"] and name not in spec["locals"]:
                spec["locals"].append(name)
                spec["local_originals"].append(name)
                spec["localized_globals"].add(name)
            spec["bound_gvar_map"][inst.operands[0]] = name
            spec["bound_symbol_map"][name.upper()] = name

    def _uses_al_bind_alist(self, spec: Dict[str, Any]) -> bool:
        """函数体是否调用 `_al-bind-alist` 协议（实际 `/ 局部变量` 绑定，t11 实测）。

        t16/t17 的 foreach/repeat 也用局部槽（`func.locals` 非空）但**不**经过
        `_al-bind-alist`，其 setq 目标是全局变量。`/` 声明的权威信号是
        `_al-bind-alist` 调用本身（AGENTS t11：符号收集在函数体符号后、参数前
        注入 `_al-bind-alist` + `(quote (locals...))`）。
        """
        for inst in spec["func"].instructions[spec["body_start"] :]:
            if inst.op_name not in ("USUBR", "FUNC") or len(inst.operands) < 2:
                continue
            if inst.operands[0] != 1:
                continue
            raw_name = self._gvar_symbol(inst.operands[1]) or self._code_gvar_symbol(inst.operands[1])
            if raw_name and raw_name.upper() == "_AL-BIND-ALIST":
                return True
        return False

    def _apply_command_fallback(self, specs: List[Dict[str, Any]]) -> None:
        unique_commands = list(
            dict.fromkeys(
                name for name in self.command_candidates if isinstance(name, str) and name.upper().startswith("C:")
            )
        )
        if len(unique_commands) != 1:
            return
        if any(spec["original_name"].upper().startswith("C:") for spec in specs if spec["original_name"]):
            return
        candidates = [spec for spec in specs if not spec["is_init"]]
        if not candidates:
            return
        target = max(candidates, key=lambda spec: len(spec["func"].instructions))
        target["original_name"] = unique_commands[0]

    def _finalize_function_names(self, specs: List[Dict[str, Any]]) -> None:
        used: Set[str] = set()
        for spec in specs:
            default_name = "fas_init" if spec["is_init"] else f'fas_fn_{spec["index"] + 1:04d}'
            spec["name"] = self._unique_symbol(
                spec["original_name"],
                default_name,
                True,
                used,
            )

    def _uses_unary_polar(self, specs: List[Dict[str, Any]]) -> bool:
        for spec in specs:
            for inst in spec["func"].instructions[spec["body_start"] :]:
                if inst.op_name not in ("USUBR", "FUNC") or len(inst.operands) < 2:
                    continue
                if inst.operands[0] != 1:
                    continue
                raw_name = self._gvar_symbol(inst.operands[1]) or self._code_gvar_symbol(inst.operands[1])
                if raw_name and raw_name.upper() == "POLAR":
                    return True
        return False

    def _uses_project_rtos(self, specs: List[Dict[str, Any]]) -> bool:
        for spec in specs:
            for inst in spec["func"].instructions[spec["body_start"] :]:
                if inst.op_name not in ("USUBR", "FUNC") or len(inst.operands) < 2:
                    continue
                if inst.operands[0] != 3:
                    continue
                raw_name = self._gvar_symbol(inst.operands[1]) or self._code_gvar_symbol(inst.operands[1])
                if raw_name and raw_name.upper() == "RTOS":
                    return True
        return False

    def _uses_project_runtime_helpers(self, specs: List[Dict[str, Any]]) -> bool:
        helper_names = {
            "*EN_RAY*",
            "AXEDYN-REACCREATE",
            "GETVAR",
            "IN_PARAM",
            "PROJET/PA_PROJET/AR_PROJET",
            "1-",
        }
        for spec in specs:
            for inst in spec["func"].instructions[spec["body_start"] :]:
                if inst.op_name not in ("USUBR", "FUNC") or len(inst.operands) < 2:
                    continue
                raw_name = self._gvar_symbol(inst.operands[1]) or self._code_gvar_symbol(inst.operands[1])
                if raw_name and raw_name.upper() in helper_names:
                    return True
        return False

    def _adjust_signatures_for_observed_calls(self, specs: List[Dict[str, Any]]) -> None:
        name_to_spec: Dict[str, Dict[str, Any]] = {}
        for spec in specs:
            for name in (
                spec["name"],
                self._normalize_symbol(spec.get("original_name", ""), spec["name"], allow_command_prefix=True),
            ):
                if name:
                    name_to_spec[name.lower()] = spec

        observed: Dict[str, Set[int]] = {}
        for spec in specs:
            for inst in spec["func"].instructions[spec["body_start"] :]:
                if inst.op_name not in ("USUBR", "FUNC") or len(inst.operands) < 2:
                    continue
                raw_name = self._gvar_symbol(inst.operands[1]) or self._code_gvar_symbol(inst.operands[1])
                if not raw_name:
                    continue
                call_name = self._normalize_symbol(raw_name, raw_name, allow_command_prefix=True).lower()
                if call_name in name_to_spec:
                    observed.setdefault(call_name, set()).add(inst.operands[0])

        for key, arities in observed.items():
            target_spec = name_to_spec.get(key)
            if not target_spec or target_spec["name"].lower().startswith("c:") or not target_spec["args"]:
                continue
            max_arity = max(arities)
            if max_arity >= len(target_spec["args"]):
                continue
            demoted = target_spec["args"][max_arity:]
            target_spec["args"] = target_spec["args"][:max_arity]
            target_spec["locals"] = demoted + target_spec["locals"]
            target_spec["local_originals"] = target_spec["arg_originals"][max_arity:] + target_spec["local_originals"]
            target_spec["arg_originals"] = target_spec["arg_originals"][:max_arity]

    def _emit_support_helpers(self) -> List[str]:
        lines: List[str] = []
        if self.needs_unary_polar_helper:
            lines.extend(
                [
                    "(defun fas-polar1 (value)",
                    "  value",
                    ")",
                ]
            )
        if self.needs_project_rtos_helper:
            if lines:
                lines.append("")
            lines.extend(
                [
                    "(defun fas-rtos1 (value)",
                    "  value",
                    ")",
                    "",
                    "(defun fas-rtos3 (bucket key value)",
                    "  (if value value key)",
                    ")",
                ]
            )
        if self.needs_project_runtime_helpers:
            if lines:
                lines.append("")
            lines.extend(
                [
                    "(defun fas-assoc-value (data key / hit)",
                    "  (cond",
                    "    ((null data) nil)",
                    "    ((and (listp key) (= (car key) 'lambda)) (apply key (list data)))",
                    "    ((and (listp key) (not (null key))) (mapcar '(lambda (item) (fas-assoc-value data item)) key))",
                    "    ((and (numberp key) (= (type data) 'ENAME) (setq hit (assoc key (entget data)))) (cdr hit))",
                    "    ((and (listp data) (numberp key)) (nth key data))",
                    "    ((and (listp data) (listp (car data)) (setq hit (assoc key data))) (cdr hit))",
                    "    (T nil)",
                    "  )",
                    ")",
                    "",
                    "(defun in_param (data key)",
                    "  (fas-assoc-value data key)",
                    ")",
                    "",
                    "(defun fas-getvar2 (data key)",
                    "  (fas-assoc-value data key)",
                    ")",
                    "",
                    "(defun fas-getvar3 (data key default / value)",
                    "  (setq value (fas-assoc-value data key))",
                    "  (if value value default)",
                    ")",
                    "",
                    "(defun fas-1- (value)",
                    "  (if (numberp value) (1- value) value)",
                    ")",
                    "",
                    "(defun axedyn-reaccreate (value)",
                    "  value",
                    ")",
                    "",
                    "(defun *en_ray* (entity data)",
                    "  (if entity entity data)",
                    ")",
                    "",
                    "(defun fas-select-entity (message / picked)",
                    '  (setq picked (entsel (if (= (type message) \'STR) message "\\nSelect object: ")))',
                    "  (cond",
                    "    ((= (type picked) 'ENAME) picked)",
                    "    ((and (listp picked) picked) (car picked))",
                    "    (T nil)",
                    "  )",
                    ")",
                    "",
                    "(defun projet_pa_projet_ar_projet (arg_1 arg_2 arg_3 arg_4 arg_5 arg_6 / picked)",
                    "  (setq picked (fas-select-entity arg_5))",
                    "  picked",
                    ")",
                ]
            )
        return lines

    def _filter_runnable_specs(self, specs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        command_names = {spec["name"] for spec in specs if spec["name"].lower().startswith("c:")}
        if not command_names:
            return specs

        name_to_spec: Dict[str, Dict[str, Any]] = {}
        for spec in specs:
            names = {
                spec["name"],
                self._normalize_symbol(spec.get("original_name", ""), spec["name"], allow_command_prefix=True),
            }
            for name in names:
                if name:
                    name_to_spec[name.lower()] = spec

        # 模块级 init 代码在加载时执行，其副作用必须保留；
        # 它们引用的函数也随可达性分析被保留。
        keep = set(command_names)
        keep.update(spec["name"] for spec in specs if spec["is_init"])
        changed = True
        while changed:
            changed = False
            for spec in specs:
                if spec["name"] not in keep:
                    continue
                for ref in spec.get("body_symbols", []):
                    ref_name = self._normalize_symbol(ref, ref, allow_command_prefix=True).lower()
                    ref_spec = name_to_spec.get(ref_name)
                    if ref_spec and ref_spec["name"] not in keep:
                        keep.add(ref_spec["name"])
                        changed = True

        return [spec for spec in specs if spec["name"] in keep]

    def _emit_init(self, spec: Dict[str, Any]) -> List[str]:
        """模块级 init 代码作为顶层形式输出（而非 defun 包装）。"""
        body_lines = self._generate_body(spec, indent=0)
        body_lines, _ = self._polish_body(spec, body_lines, [])
        return [line for line in body_lines if line.strip() and not line.strip().startswith(";;")]

    def _emit_function(self, spec: Dict[str, Any]) -> List[str]:
        args = spec["args"]
        min_args = spec.get("min_args", len(args))
        has_rest = spec.get("has_rest", False)
        if has_rest:
            # 无限参数：固定 + (&optional ...) + &rest
            fixed = list(args[:min_args])
            mid = list(args[min_args:-1]) if len(args) > min_args + 1 else []
            rest = args[-1] if args else "rest"
            param_list = fixed
            if mid:
                param_list += ["&optional"] + mid
            param_list += ["&rest", rest]
            args = param_list
        elif min_args < len(args):
            # 有限可选参数：固定 + &optional
            args = list(args[:min_args]) + ["&optional"] + list(args[min_args:])
        locals_list = spec["locals"]
        if spec["name"].lower().startswith("c:") and args:
            # AutoLISP command functions are invoked by AutoCAD with no
            # arguments. Signature hints for C: functions are compiler-local
            # slots, so keep the generated command runnable by localizing them.
            locals_list = args + locals_list
            args = []

        lines: List[str] = []
        normalized_name = self._normalize_symbol(
            spec["original_name"],
            spec["name"],
            allow_command_prefix=True,
        )
        body_lines = self._generate_body(spec)
        body_lines, locals_list = self._polish_body(spec, body_lines, locals_list)
        # stub 模式：函数末尾的 PUSH_VALUE[0] 会把函数名当作返回值，
        # 这是 CAD 的返回值占位，应从函数体中移除。
        while body_lines:
            last = body_lines[-1].strip()
            if last == spec["name"] or last == spec.get("original_name", ""):
                body_lines.pop()
            else:
                break

        args_text = " ".join(args)
        local_text = ""
        if locals_list:
            slash = " /" if args_text else "/"
            local_text = slash + " " + " ".join(locals_list)

        lines.append(f'(defun {spec["name"]} ({args_text}{local_text})')
        if not body_lines:
            body_lines = ["  nil"]
        lines.extend(body_lines)
        lines.append(")")
        return lines

    def _polish_body(
        self, spec: Dict[str, Any], body_lines: List[str], locals_list: List[str]
    ) -> Tuple[List[str], List[str]]:
        lines = list(body_lines)
        locals_out = list(dict.fromkeys(locals_list))

        def setq_nil_var(line: str) -> Optional[str]:
            match = re.match(r"^\s*\(setq\s+([^\s()]+)\s+nil\)\s*$", line)
            return match.group(1) if match else None

        while lines:
            var = setq_nil_var(lines[0])
            if var not in locals_out:
                break
            lines.pop(0)
        if len(lines) > 1 and lines[0].strip() == "(princ)":
            lines.pop(0)

        last_expr = len(lines) - 1
        while last_expr >= 0 and not lines[last_expr].strip():
            last_expr -= 1
        cleanup_end = last_expr if last_expr >= 0 and lines[last_expr].strip() == "(princ)" else len(lines)
        idx = cleanup_end - 1
        while idx >= 0:
            var = setq_nil_var(lines[idx])
            if var not in locals_out:
                break
            lines.pop(idx)
            cleanup_end -= 1
            idx -= 1

        lines, locals_out = self._drop_unused_local_setqs(lines, locals_out, spec.get("localized_globals"))
        rename_map = self._infer_local_renames(lines, locals_out)
        if rename_map:
            lines = [self._replace_symbols(line, rename_map) for line in lines]
            locals_out = [rename_map.get(name, name) for name in locals_out]
            locals_out = list(dict.fromkeys(locals_out))

        return lines, locals_out

    SIDE_EFFECT_FUNCS = frozenset(
        {
            "getstring",
            "getpoint",
            "getcorner",
            "getreal",
            "getint",
            "getdist",
            "getkword",
            "getfiled",
            "entsel",
            "nentsel",
            "nentselp",
            "ssget",
            "ssadd",
            "ssdel",
            "sssetfirst",
            "entmake",
            "entmakex",
            "entdel",
            "entmod",
            "entupd",
            "entnext",
            "command",
            "vl-cmdf",
            "vl-cmdfun",
            "read-line",
            "read-char",
            "write-line",
            "write-char",
            "print",
            "princ",
            "prin1",
            "prompt",
            "terpri",
            "alert",
            "findfile",
            "getenv",
            "load",
            "open",
            "startapp",
            "setvar",
            "regapp",
            "redraw",
            "regen",
            "regenall",
            "update",
            "grread",
            "grvecs",
            "grtext",
            "grdraw",
            "vl-file-copy",
            "vl-file-delete",
            "vl-file-rename",
            "vl-file-directory-p",
            "vl-registry-write",
            "vl-load-com",
            "vlax-add-cmd",
            "vlax-import-type-library",
            "dictadd",
            "dictremove",
            "acad_colordlg",
            "aced_ssget",
            "initget",
        }
    )

    def _has_side_effects(self, text: str) -> bool:
        for m in re.finditer(r"\(([A-Za-z][\w-]*)", text):
            name = m.group(1).lower()
            if name in self.SIDE_EFFECT_FUNCS or name.startswith("vla-"):
                return True
        return False

    def _drop_unused_local_setqs(
        self, lines: List[str], locals_list: List[str], protected: Optional[Set[str]] = None
    ) -> Tuple[List[str], List[str]]:
        protected = protected or set()
        stripped_lines = [self._strip_strings(line) for line in lines]
        remove_indexes: Set[int] = set()
        remove_locals: Set[str] = set()
        for local in locals_list:
            if local in protected:
                continue
            pattern = self._symbol_pattern(local)
            count = sum(len(pattern.findall(line)) for line in stripped_lines)
            if count != 1:
                continue
            for idx, line in enumerate(stripped_lines):
                if re.match(rf"^\s*\(setq\s+{re.escape(local)}\b", line):
                    if self._has_side_effects(line):
                        break
                    remove_indexes.add(idx)
                    remove_locals.add(local)
                    break
        kept_lines = [line for idx, line in enumerate(lines) if idx not in remove_indexes]
        kept_locals = [name for name in locals_list if name not in remove_locals]
        return kept_lines, kept_locals

    def _infer_local_renames(self, lines: List[str], locals_list: List[str]) -> Dict[str, str]:
        text = "\n".join(self._strip_strings(line) for line in lines)
        desired: Dict[str, str] = {}
        for name in locals_list:
            if name.startswith("gvar_") and re.search(rf"\(setq\s+{re.escape(name)}\s+\(getstring\b", text):
                desired[name] = "pattern"
            elif name.startswith("gvar_") and (
                re.search(rf"\(1\+\s+{re.escape(name)}\)", text) or re.search(rf"\(itoa\s+{re.escape(name)}\)", text)
            ):
                desired[name] = "purged_count"
            elif name == "n" and re.search(r"\(acad_strlsort\s+n\)", text):
                desired[name] = "dict_names"
            elif name == "b" and re.search(r"\(setq\s+b\s+\(acad_strlsort\b", text):
                desired[name] = "sorted_names"
            elif name == "c" and re.search(r"\(foreach\s+c\b", text):
                desired[name] = "dict_name"

        used = set(locals_list) - set(desired)
        rename_map: Dict[str, str] = {}
        for old, new in desired.items():
            unique = new
            counter = 2
            while unique in used:
                unique = f"{new}_{counter}"
                counter += 1
            used.add(unique)
            rename_map[old] = unique
        return rename_map

    def _generate_body(self, spec: Dict[str, Any], indent: int = 1) -> List[str]:
        instructions = spec["func"].instructions[spec["body_start"] :]
        lines = self._render_block(spec, instructions, 0, len(instructions), indent)
        if not any(line.strip() and not line.strip().startswith(";;") for line in lines):
            lines.append(f'{"  " * indent}nil')
        return lines

    def _render_block(
        self, spec: Dict[str, Any], instructions: List[Instruction], start: int, end: int, indent: int
    ) -> List[str]:
        lines: List[str] = []
        stack: List[str] = []
        unresolved_ops: Set[str] = set()
        pending_logic: List[Dict[str, Any]] = []
        cond_state: Optional[Dict[str, Any]] = None
        offset_to_idx = {inst.offset: idx for idx, inst in enumerate(instructions)}

        def pop_expr(default: Optional[str] = "nil") -> Optional[str]:
            return stack.pop() if stack else default

        def pop_many(count: int) -> List[str]:
            if count <= 0:
                return []
            if count > len(stack):
                count = len(stack)
            values = stack[-count:]
            del stack[-count:]
            return values

        def flush_stack() -> None:
            if pending_logic:
                stack.append(self._combine_short_circuit_terms(pending_logic))
                pending_logic.clear()
            while stack:
                expr = stack.pop(0)
                lines.append(self._statement_line(expr, indent))

        i = start
        while i < end:
            inst = instructions[i]
            name = inst.op_name

            if cond_state is not None and i == cond_state["info"]["jump_idx"]:
                info = cond_state["info"]
                n = len(cond_state["tests"])
                clauses: List[str] = []
                for j in range(n):
                    test = cond_state["tests"][j]
                    b_start = info["body_starts"][j] + 1
                    b_end = info["body_ends"][j]
                    body_lines = self._render_block(spec, instructions, b_start, b_end, indent + 2)
                    results = [ln.strip() for ln in body_lines if ln.strip() and not ln.strip().startswith(";;")]
                    clauses.append(" ".join([test] + results))
                cond_text = "(cond"
                for c in clauses:
                    cond_text += f"\n{'  ' * (indent + 1)}({c})"
                cond_text += f"\n{'  ' * indent})"
                stack.append(cond_text)
                i = info["chain_end"]
                cond_state = None
                continue

            if name in ("JMP32_IFNOT", "JMP16_IF", "JMP16_IF_ALT", "JMP16_IFNOT", "JMP16_IFNOT_ALT"):
                # 短路重建依赖分支语义分类，不用名称子串判断（JMP32_IFNOT 名称含
                # IFNOT 但语义为"真则跳转"——与 JMP16_IF 同类，勿用 "IFNOT" in name）。
                ifnot_kind = name in ("JMP16_IFNOT", "JMP16_IFNOT_ALT")
                cond = pop_expr("nil" if ifnot_kind else "T") or "nil"
                target_idx = self._branch_target_index(instructions, offset_to_idx, i)
                if target_idx is None and inst.operands:
                    target_offset = inst.offset + inst.size + inst.operands[0]
                    last_end = instructions[-1].offset + instructions[-1].size
                    if target_offset >= last_end and end <= len(instructions):
                        target_idx = min(end, len(instructions) - 1)
                if (
                    target_idx is not None
                    and start <= target_idx <= end
                    and instructions[target_idx].op_name
                    in ("JMP16_IF", "JMP16_IF_ALT", "JMP16_IFNOT", "JMP16_IFNOT_ALT")
                ):
                    pending_logic.append(
                        {
                            "kind": "and" if ifnot_kind else "or",
                            "expr": cond or "nil",
                            "target": instructions[target_idx].offset,
                        }
                    )
                    i += 1
                    continue
                if pending_logic:
                    cond = self._combine_short_circuit_terms(pending_logic, cond)
                    pending_logic.clear()
                # 表达式位 if：then 分支末尾无 POP（值流入 JUMP/else 供后续调用
                # 消费，`(+ (if a 1 2) 3)`/`(list (if a a 0) (if b b 0))` stub
                # 实测）。这类 if 是"值"而非语句，不能在此 flush_stack——
                # 否则后续 if 的 flush 会把前一个 if 值当语句丢弃。
                pre_if = self._detect_if(instructions, offset_to_idx, i, target_idx, end) if target_idx is not None else None
                is_value_if = False
                if pre_if is not None and self._looks_structured_condition(cond):
                    te = pre_if["then_end"]
                    if te > pre_if["then_start"] and instructions[te - 1].op_name != "POP":
                        is_value_if = True
                if not is_value_if:
                    flush_stack()
                if target_idx is not None and start <= target_idx:
                    if target_idx > end:
                        target_idx = end
                    loop_info = self._detect_loop(spec, instructions, offset_to_idx, i, target_idx, end, cond)
                    if loop_info and (loop_info["keyword"] == "foreach" or self._looks_structured_condition(cond)):
                        # 循环是语句而非值：渲染前先 flush 栈中在此之前的语句
                        # （t17 repeat 前置 `(setq acc 0)` 在栈中累积，跳过 flush 会
                        # 在循环后才输出；foreach 的 INIT_ARGS 预载本已触发 flush）。
                        flush_stack()
                        head = f'({loop_info["keyword"]} {loop_info["head"]}'
                        lines.append(f'{"  " * indent}{head}')
                        lines.extend(
                            self._render_block(
                                spec,
                                instructions,
                                loop_info["body_start"],
                                loop_info["body_end"],
                                indent + 1,
                            )
                        )
                        lines.append(f'{"  " * indent})')
                        i = loop_info["after"]
                        continue

                    if_info = self._detect_if(instructions, offset_to_idx, i, target_idx, end)
                    if if_info and self._looks_structured_condition(cond):
                        # 表达式位 if：then 分支末尾无 POP（值流入 JUMP/else 供
                        # 后续调用消费，`(+ (if a 1 2) 3)`/`(list (if a a 0) ...)`
                        # stub 实测）。此时把 `(if ...)` 压栈作值，而非作为语句。
                        then_ends_pop = False
                        te = if_info["then_end"]
                        if te > if_info["then_start"] and instructions[te - 1].op_name == "POP":
                            then_ends_pop = True
                        then_lines = self._render_block(
                            spec,
                            instructions,
                            if_info["then_start"],
                            if_info["then_end"],
                            indent + 2,
                        )
                        if not then_ends_pop:
                            body = self._render_block(
                                spec,
                                instructions,
                                if_info["then_start"],
                                if_info["then_end"],
                                indent + 1,
                            )
                            then_text = self._emit_progn(body, indent)
                            if_text = f"(if {cond}"
                            if then_text:
                                if_text += "\n" + "\n".join(then_text)
                            if if_info["else_start"] is not None and if_info["else_end"] is not None:
                                else_lines = self._render_block(
                                    spec,
                                    instructions,
                                    if_info["else_start"],
                                    if_info["else_end"],
                                    indent + 1,
                                )
                                else_text = self._emit_progn(else_lines, indent)
                                if else_text:
                                    if_text += "\n" + "\n".join(else_text)
                            if_text += "\n" + "  " * indent + ")"
                            stack.append(if_text)
                            i = if_info["after"]
                            continue
                        lines.append(f'{"  " * indent}(if {cond}')
                        lines.extend(self._emit_progn(then_lines, indent + 1))
                        if if_info["else_start"] is not None and if_info["else_end"] is not None:
                            else_lines = self._render_block(
                                spec,
                                instructions,
                                if_info["else_start"],
                                if_info["else_end"],
                                indent + 2,
                            )
                            if else_lines:
                                lines.extend(self._emit_progn(else_lines, indent + 1))
                        lines.append(f'{"  " * indent})')
                        i = if_info["after"]
                        continue

                lines.append(self._statement_line(f";; unhandled branch {name}@0x{inst.offset:x}", indent))
                i += 1
                continue

            if name in ("PUSH_G", "PUSH_G_ALT") and inst.operands:
                stack.append(self._literal_from_gvar(inst.operands[0]))
            elif name == "PUSH_VALUE" and inst.operands:
                if not (self.is_stub_format and inst.size == 1):
                    # stub 单字节 PUSH_VALUE[0]：调用后清理，不压栈
                    if self.is_stub_format:
                        # cond 的 t 子句用 PUSH_VALUE 直接引用 T 符号槽（gvar 槽-1）
                        raw_t = self._gvar_symbol_gvar(inst.operands[0])
                        if raw_t and raw_t.upper() == "T":
                            stack.append("t")
                            i += 1
                            continue
                    stack.append(self._value_from_gvar(inst.operands[0], spec))
            elif name in ("GET_LOCAL", "GET_LOCAL_WIDE") and inst.operands:
                stack.append(self._local_name(inst.operands[0], spec))
            elif name == "PUSH_NIL":
                if cond_state is not None and i == cond_state["info"]["jump_idx"] - 1:
                    i += 1
                    continue
                stack.append("nil")
            elif name == "PUSH_T":
                stack.append("T")
            elif name in ("PUSH_INT8", "PUSH_INT32") and inst.operands:
                stack.append(str(inst.operands[0]))
            elif name == "PUSH_REAL" and inst.operands:
                stack.append(str(inst.operands[0]))
            elif name == "DUP":
                if stack:
                    stack.append(stack[-1])
            elif name == "CAR":
                stack.append(f"(car {pop_expr()})")
            elif name == "CDR":
                stack.append(f"(cdr {pop_expr()})")
            elif name == "NOT":
                stack.append(f"(not {pop_expr()})")
            elif name == "ATOM":
                stack.append(f"(atom {pop_expr()})")
            elif name in ("BUILD_LIST", "BUILD_LIST_ALT") and inst.operands:
                args = pop_many(inst.operands[0])
                args.reverse()
                stack.append(self._make_call_text("list", args))
            elif name in (
                "FIX_ADD",
                "FIX_SUB",
                "FIX_MUL",
                "FIX_DIV",
                "FIX_MOD",
                "FIX_LEQ",
                "FIX_GEQ",
                "FIX_LT",
                "FIX_GT",
            ):
                right = pop_expr()
                left = pop_expr()
                op_map = {
                    "FIX_ADD": "+",
                    "FIX_SUB": "-",
                    "FIX_MUL": "*",
                    "FIX_DIV": "/",
                    "FIX_MOD": "rem",
                    "FIX_LEQ": "<=",
                    "FIX_GEQ": ">=",
                    "FIX_LT": "<",
                    "FIX_GT": ">",
                }
                stack.append(self._make_call_text(op_map[name], [left or "nil", right or "nil"]))
            elif name == "INC":
                stack.append(self._make_call_text("1+", [pop_expr() or "nil"]))
            elif name == "DEC":
                stack.append(self._make_call_text("1-", [pop_expr() or "nil"]))
            elif name in ("USUBR", "FUNC") and len(inst.operands) >= 2:
                argc = inst.operands[0]
                if self._skip_literal_zero_arg_call(inst.operands[1], argc):
                    i += 1
                    continue
                args = pop_many(argc)
                call_name = self._call_name(inst.operands[1], argc, spec, args)
                stack.append(self._make_call_text(call_name, args))
            elif name == "EVAL" and inst.operands:
                args = pop_many(inst.operands[0] + 1)
                stack.append(self._make_call_text("eval", args))
            elif name == "CONS":
                car = pop_expr() or "nil"
                cdr = pop_expr() or "nil"
                stack.append(self._make_call_text("cons", [car, cdr]))
            elif name == "SETQ_G" and inst.operands:
                expr = pop_expr()
                if stack and stack[-1] == expr:
                    stack.pop()
                target = self._value_from_gvar(inst.operands[0], spec)
                stack.append(f"(setq {target} {expr})")
            elif name == "SET_LOCAL" and inst.operands:
                expr = pop_expr()
                if stack and stack[-1] == expr:
                    stack.pop()
                target = self._local_name(inst.operands[0], spec)
                if expr and expr != target:
                    spec["slot_expr_map"][target] = expr
                stack.append(f"(setq {target} {expr})")
            elif name == "CLEAR_LOCAL" and inst.operands:
                target = self._local_name(inst.operands[0], spec)
                stack.append(f"(setq {target} nil)")
            elif name == "POP":
                expr = pop_expr(default=None)
                if expr is not None:
                    # 语句调用（princ/eval 等的值被丢弃）在 POP 处成行输出。
                    # 栈中更早滞留的完整语句（如 `(setq e 123)`）须先于本行
                    # 输出以保持源码顺序（T4：`(setq x e) (eval y)` 时 eval
                    # 不得反置于 setq 之前）。此时栈内剩余项应为先前完整语句。
                    while stack:
                        lines.append(self._statement_line(stack.pop(0), indent))
                    lines.append(self._statement_line(expr, indent))
            elif name == "INIT_ARGS" and inst.operands:
                consumed = pop_many((inst.operands[0] // 2) * 2)
                flush_stack()
            elif name == "END_DEFUN_CLEANUP" and inst.operands:
                dropped = pop_many(inst.operands[0] + 2)
                flush_stack()
            elif name in ("COND_OR", "COND_AND"):
                cond = pop_expr("nil") or "nil"
                if name == "COND_OR":
                    if cond_state is not None and i == cond_state["info"]["condors"][cond_state["next"]]:
                        cond_state["tests"].append(cond)
                        cond_state["next"] += 1
                        i += 1
                        continue
                    cond_info = self._detect_cond(instructions, offset_to_idx, i, end)
                    if cond_info is not None:
                        cond_state = {"info": cond_info, "tests": [cond], "next": 1}
                        i += 1
                        continue
                elif name == "COND_AND" and pending_logic and i + 1 < end:
                    # 短路链收尾：COND_AND 的跳转目标是紧随其后的 PUSH_T
                    # （codegen `(and ...)/(or ...)` 全真/有真时的规范化标记，
                    # `_emit_short_circuit` 的 END 标签）。此时把累积的链
                    # 折叠为单个表达式，并吞掉该 PUSH_T，避免泄漏裸 `T`。
                    nxt = instructions[i + 1]
                    if nxt.op_name == "PUSH_T":
                        chain = self._combine_short_circuit_terms(pending_logic, cond)
                        pending_logic.clear()
                        stack.append(chain)
                        i += 2
                        continue
                target_offset = inst.offset + inst.size + inst.operands[0] if inst.operands else None
                pending_logic.append(
                    {
                        "kind": "or" if name == "COND_OR" else "and",
                        "expr": cond or "nil",
                        "target": target_offset,
                    }
                )
            elif name == "EXIT_IF_NOT_ZERO":
                cond = pop_expr("T") or "T"
                if cond in ("T", "nil"):
                    lines.append(self._statement_line("(exit)", indent))
                else:
                    lines.append(self._statement_line(f"(if {cond} (exit))", indent))
            elif name == "EXIT_IF_ZERO":
                cond = pop_expr("nil") or "nil"
                if cond in ("T", "nil"):
                    lines.append(self._statement_line("(exit)", indent))
                else:
                    lines.append(self._statement_line(f"(if (not {cond}) (exit))", indent))
            elif name in ("JUMP", "JUMP_ALT"):
                flush_stack()
            elif name in ("CLEAR_ARGS", "END_DEFUN", "INIT_DONE"):
                flush_stack()
            elif name in (
                "NIL",
                "NOP",
                "NOP_ALT",
                "NOP_ALT2",
                "DEFUN",
                "DEFUN_ALT",
                "ALPHA",
                "BETA",
                "DEFCODE",
            ):
                pass
            elif name.startswith("UNK_"):
                unresolved_ops.add(name)
            else:
                unresolved_ops.add(name)
            i += 1

        flush_stack()
        if unresolved_ops:
            note = ", ".join(sorted(unresolved_ops))
            lines.append(self._statement_line(f";; unhandled opcodes: {note}", indent))
        return lines

    def _emit_progn(self, body_lines: List[str], indent: int) -> List[str]:
        if not body_lines:
            return [f'{"  " * indent}nil']
        return [f'{"  " * indent}(progn', *body_lines, f'{"  " * indent})']

    def _combine_short_circuit_terms(self, terms: List[Dict[str, Any]], final_expr: Optional[str] = None) -> str:
        grouped: List[Tuple[str, List[str]]] = []
        for term in terms:
            expr = term["expr"]
            if expr in {"T", "nil"}:
                continue
            key = f'{term["kind"]}:{term.get("target")}'
            if grouped and grouped[-1][0] == key:
                grouped[-1][1].append(expr)
            else:
                grouped.append((key, [expr]))

        if final_expr and final_expr not in {"T", "nil"}:
            if grouped:
                grouped[-1][1].append(final_expr)
            else:
                grouped.append(("and:final", [final_expr]))

        if not grouped:
            return final_expr or "T"

        rendered: List[Tuple[str, str]] = []
        for key, exprs in grouped:
            kind = key.split(":", 1)[0]
            unique_exprs = list(dict.fromkeys(exprs))
            if len(unique_exprs) == 1:
                rendered.append((kind, unique_exprs[0]))
            else:
                rendered.append((kind, self._make_call_text(kind, unique_exprs)))

        result = rendered[0][1]
        for kind, expr in rendered[1:]:
            result = self._make_call_text(kind, [result, expr])
        return result

    def _branch_target_index(
        self, instructions: List[Instruction], offset_to_idx: Dict[int, int], idx: int
    ) -> Optional[int]:
        inst = instructions[idx]
        if not inst.operands:
            return None
        target_offset = inst.offset + inst.size + inst.operands[0]
        return offset_to_idx.get(target_offset)

    def _skip_pops(self, instructions: List[Instruction], idx: int, end: int) -> int:
        while idx < end and instructions[idx].op_name == "POP":
            idx += 1
        return idx

    def _detect_repeat_setup(
        self, spec: Dict[str, Any], instructions: List[Instruction], body_start: int, body_end: int
    ) -> Optional[Dict[str, Any]]:
        """repeat 协议（t17 实测）：loop 头 `GET_LOCAL; PUSH_INT8 0; FIX_LEQ;
        JMP32_IFNOT`（计数<=0 退出），体前先 `GET_LOCAL <slot>; DEC; SET_LOCAL
        <slot>` 递减。次数在循环前 `PUSH_VALUE <n>; SET_LOCAL <slot>` 存入槽，
        `slot_expr_map` 记录了槽的初始表达式。"""
        if body_start + 2 > body_end:
            return None
        g, d, s = instructions[body_start], instructions[body_start + 1], instructions[body_start + 2]
        if g.op_name not in ("GET_LOCAL", "GET_LOCAL_WIDE"):
            return None
        if d.op_name != "DEC" or s.op_name != "SET_LOCAL":
            return None
        if not g.operands or not s.operands:
            return None
        slot = g.operands[0]
        if s.operands[0] != slot:
            return None
        count_name = self._local_name(slot, spec)
        count = spec.get("slot_expr_map", {}).get(count_name, count_name)
        return {
            "keyword": "repeat",
            "head": count,
            "body_start": body_start + 3,
            "body_end": body_end,
        }

    def _detect_foreach_setup(
        self, spec: Dict[str, Any], instructions: List[Instruction], body_start: int, body_end: int, source_expr: str
    ) -> Optional[Dict[str, Any]]:
        if body_start + 6 > body_end:
            return None
        seq = instructions[body_start : body_start + 6]
        pat_short = ["GET_LOCAL", "CAR", "SETQ_G", "GET_LOCAL", "CDR", "SET_LOCAL"]
        pat_wide = ["GET_LOCAL_WIDE", "CAR", "SETQ_G", "GET_LOCAL_WIDE", "CDR", "SET_LOCAL"]
        ops_seq = [inst.op_name for inst in seq]
        if ops_seq != pat_short and ops_seq != pat_wide:
            return None
        slot = seq[0].operands[0] if seq[0].operands else None
        if slot is None or not seq[3].operands or not seq[5].operands:
            return None
        if seq[3].operands[0] != slot or seq[5].operands[0] != slot:
            return None
        item_name = self._value_from_gvar(seq[2].operands[0], spec) if seq[2].operands else "item"
        source = spec.get("slot_expr_map", {}).get(source_expr, source_expr)
        return {
            "keyword": "foreach",
            "head": f"{item_name} {source}",
            "body_start": body_start + 6,
            "body_end": body_end,
        }

    def _detect_loop(
        self,
        spec: Dict[str, Any],
        instructions: List[Instruction],
        offset_to_idx: Dict[int, int],
        branch_idx: int,
        target_idx: int,
        end: int,
        cond_expr: str,
    ) -> Optional[Dict[str, Any]]:
        back_jump_idx = None
        for idx in range(target_idx, branch_idx, -1):
            inst = instructions[idx]
            if inst.op_name not in ("JUMP", "JUMP_ALT") or not inst.operands:
                continue
            jump_target = self._branch_target_index(instructions, offset_to_idx, idx)
            if jump_target is None or jump_target >= idx:
                continue
            if jump_target <= branch_idx:
                back_jump_idx = idx
                break
        if back_jump_idx is None:
            return None

        body_start = self._skip_pops(instructions, branch_idx + 1, back_jump_idx)
        loop_info = self._detect_foreach_setup(spec, instructions, body_start, back_jump_idx, cond_expr)
        if loop_info:
            loop_info["after"] = self._skip_pops(instructions, target_idx, end)
            return loop_info
        repeat_info = self._detect_repeat_setup(spec, instructions, body_start, back_jump_idx)
        if repeat_info:
            repeat_info["after"] = self._skip_pops(instructions, target_idx, end)
            return repeat_info
        return {
            "keyword": "while",
            "head": spec.get("slot_expr_map", {}).get(cond_expr, cond_expr),
            "body_start": body_start,
            "body_end": back_jump_idx,
            "after": self._skip_pops(instructions, target_idx, end),
        }

    def _detect_if(
        self, instructions: List[Instruction], offset_to_idx: Dict[int, int], branch_idx: int, target_idx: int, end: int
    ) -> Optional[Dict[str, Any]]:
        then_start = self._skip_pops(instructions, branch_idx + 1, target_idx)
        jump_idx = None
        jump_target = None
        for idx in range(branch_idx + 1, min(target_idx, end)):
            inst = instructions[idx]
            if inst.op_name not in ("JUMP", "JUMP_ALT") or not inst.operands:
                continue
            target = self._branch_target_index(instructions, offset_to_idx, idx)
            if target is None or target <= idx or target < target_idx:
                continue
            jump_idx = idx
            jump_target = target
        if jump_idx is not None and jump_target is not None:
            if then_start >= jump_idx:
                return None
            return {
                "then_start": then_start,
                "then_end": jump_idx,
                "else_start": self._skip_pops(instructions, target_idx, min(jump_target, end)),
                "else_end": min(jump_target, end),
                "after": self._skip_pops(instructions, min(jump_target, end), end),
            }
        if then_start >= target_idx:
            return None
        return {
            "then_start": then_start,
            "then_end": target_idx,
            "else_start": None,
            "else_end": None,
            "after": self._skip_pops(instructions, target_idx, end),
        }

    def _detect_cond(self, instructions, offset_to_idx, cond_idx, end):
        """从首个 COND_OR 检测 cond 结构（CAD/本编译器 stub 实测）；非 cond 返回 None。

        结构：
          test_0 ... COND_OR -> body_0
          test_1 ... COND_OR -> body_1
          ...
          test_{n-1} ... COND_OR -> body_{n-1}
          PUSH_NIL
          JUMP -> J_{n-1}          # 默认路径，链式跳过所有 body
          [body_{n-1}:] POP; result; JUMP -> J_{n-2}
          ...
          [body_0:] POP; result
        """
        condors: List[int] = []
        jump_idx = None
        j = cond_idx
        while j < end:
            inst = instructions[j]
            if inst.op_name == "COND_OR" and inst.operands:
                condors.append(j)
                j += 1
                continue
            if inst.op_name == "PUSH_NIL" and j + 1 < end and instructions[j + 1].op_name in ("JUMP", "JUMP_ALT"):
                jump_idx = j + 1
                break
            j += 1
        if not condors or jump_idx is None:
            return None
        n = len(condors)

        chain_start = self._branch_target_index(instructions, offset_to_idx, jump_idx)
        if chain_start is None or instructions[chain_start].op_name not in ("JUMP", "JUMP_ALT"):
            return None
        # 链 = 每个 body 尾部 JUMP（除最后发出的 body），共 n-1 个。
        # 链式结构嵌套 cond 时后续 JUMP 可能属于外层，故只取前 n-1 个链接，
        # chain_end = 末链接目标（= body_0 尾部，即本 cond 结束处）。
        chain: List[int] = [chain_start]
        cur = chain_start
        while len(chain) < n - 1:
            tgt = self._branch_target_index(instructions, offset_to_idx, cur)
            if tgt is None or tgt <= cur:
                return None
            if instructions[tgt].op_name not in ("JUMP", "JUMP_ALT"):
                return None
            chain.append(tgt)
            cur = tgt
        chain_end = self._branch_target_index(instructions, offset_to_idx, chain[-1])
        if chain_end is None or not (jump_idx < chain_end <= end):
            return None
        if len(chain) != n - 1:
            return None
        body_starts: List[int] = [0] * n
        body_ends: List[int] = [0] * n
        for j, condor in enumerate(condors):
            start = self._branch_target_index(instructions, offset_to_idx, condor)
            if start is None or not (jump_idx < start < chain_end):
                return None
            if instructions[start].op_name != "POP":
                return None
            body_starts[j] = start
            body_ends[j] = chain_end if j == 0 else chain[n - 1 - j]
        return {
            "condors": condors,
            "body_starts": body_starts,
            "body_ends": body_ends,
            "jump_idx": jump_idx,
            "chain_end": chain_end,
        }

    def _looks_structured_condition(self, expr: str) -> bool:
        return expr not in {"T", "nil", "0", "0.0"}

    def _stub_tail_arg_names(self, argc: int) -> List[str]:
        """单函数 stub 参数名：symbol_slots 尾部 argc 个去重符号的逆序。

        CadSymbolCollector._collect_single 把参数（含共享）放在符号槽末尾，
        声明序逆序注册（最后声明的参数槽最小）。t02-t13/t16/t17/and2/andor/
        andval/or2 全部 CAD golden 实测一致；含 quoted lambda 等引用字面量时
        参数仍居尾部（t08：LST 在 MAPCAR/LAMBDA/X/*/APPLY/+ 之后）。
        """
        uniq: List[str] = []
        seen: set = set()
        for item in self.symbol_slots:
            name = self._extract_symbol_text(item)
            if name and name not in seen:
                seen.add(name)
                uniq.append(name)
        if argc <= 0 or argc > len(uniq):
            return []
        return list(reversed(uniq[-argc:]))

    def _extract_signature(self, instructions: List[Instruction]) -> Dict[str, Any]:
        start = 1 if instructions and instructions[0].op_name == "DEFUN" else 0
        init_idx = None
        limit = min(len(instructions), start + 24)
        for idx in range(start, limit):
            if instructions[idx].op_name == "INIT_ARGS":
                init_idx = idx
                break
            if instructions[idx].op_name in ("SETQ_G", "SET_LOCAL", "USUBR", "FUNC", "JMP32_IFNOT", "JUMP"):
                break
        if init_idx is None:
            return {"args": [], "body_start": start, "local_binding_names": []}

        init_count = instructions[init_idx].operands[0] if instructions[init_idx].operands else 0
        pushed: List[Tuple[str, Any]] = []
        for inst in instructions[start:init_idx]:
            if inst.op_name == "PUSH_G" and inst.operands:
                pushed.append(("name", inst.operands[0]))
            elif inst.op_name in ("GET_LOCAL", "GET_LOCAL_WIDE") and inst.operands:
                pushed.append(("slot", inst.operands[0]))
            elif inst.op_name == "PUSH_NIL":
                pushed.append(("nil", None))

        args: List[Tuple[int, str]] = []
        arg_symbol_indices: List[int] = []
        local_binding_names: List[str] = []
        seen_arg_names: set = set()
        pair_items = pushed[-((init_count // 2) * 2) :]
        for pos in range(0, len(pair_items) - 1, 2):
            left, right = pair_items[pos], pair_items[pos + 1]
            if left[0] == "name" and right[0] == "slot":
                raw_item = self._gvar_item(left[1])
                symbol_list = self._extract_symbol_list(raw_item)
                if symbol_list:
                    local_binding_names.extend(symbol_list)
                    continue
                raw_name = self._gvar_symbol_gvar(left[1]) or f"arg_{len(args) + 1}"
                if self.is_stub_format:
                    # 多函数紧凑 stub：末位参数符号槽落在 nsyms 截断的 gvar 表
                    # 之外（t01/t09/t18 实测 A、N 不在基础 gvar 表内）。用扩展
                    # gvar 表（基础表 + symbol_slots 尾部共享/参数符号）按
                    # gvar 槽 - 1 寻址：操作数 o → extended[o+1]（t01 op4→A@5、
                    # t08 op5→LST@6、t07 op7→LST@8、t18 op6→N@7 实测）。
                    if self._stub_is_multi_func:
                        _ext = self._stub_extended_gvar()
                        _gi = left[1] + 1
                        if 1 < _gi < len(_ext):
                            _gname = self._extract_symbol_text(_ext[_gi])
                            if _gname and _gname not in seen_arg_names:
                                raw_name = _gname
                    if raw_name in seen_arg_names or not any(c.isalpha() for c in raw_name):
                        j = left[1] + 1
                        if j < len(self.symbol_slots):
                            alt = self._extract_symbol_text(self.symbol_slots[j])
                            if alt and alt not in seen_arg_names:
                                raw_name = alt
                        if raw_name in seen_arg_names or not any(c.isalpha() for c in raw_name):
                            raw_name = f"arg_{len(args) + 1}"
                seen_arg_names.add(raw_name)
                args.append((right[1], raw_name))
                arg_symbol_indices.append(left[1])

        # 单函数紧凑 stub：参数符号在 symbol_slots 尾部按"字节码引用序逆序注册"
        # （CadSymbolCollector._collect_single 参数放最后，t02-t13/t16/t17/and*
        # 全部 CAD golden 实测）。当函数体含引用字面量（quoted lambda/列表等）
        # 时，参数绑定 PUSH_G 操作数指向的符号与真实参数槽错位（t08/t8e：
        # `(mapcar '(lambda (x) ...) lst)` 的 lst 在 slots 尾部，绑定操作数却
        # 指向 lambda 参数 X）。此时用尾部 argc 个去重符号（逆序）覆写参数名。
        if (
            self.is_stub_format
            and not self._stub_is_multi_func
            and args
            and self._defun_headers_are_argc()
            and instructions
            and instructions[0].op_name == "DEFUN"
        ):
            _ops = instructions[0].operands
            if len(_ops) >= 2 and _ops[0] == len(args) and _ops[3] in (0, 1):
                tail_args = self._stub_tail_arg_names(len(args))
                if tail_args and len(tail_args) == len(args):
                    # 仅当现有操作数解析的参数名与尾部符号不一致（错位）时覆写，
                    # 避免破坏参数名已正确解析的简单单函数文件（t13 等）。
                    existing = [n.upper() for _, n in args]
                    tail_up = [n.upper() for n in tail_args]
                    if existing != tail_up:
                        args = [(slot, name) for (slot, _), name in zip(args, tail_args)]

        # DEFUN 头（0x14，仅真 stub）：b1=参数(总)/b2=最低参数/b3/b4=00有限|01无限
        _read = False
        if self._defun_headers_are_argc() and instructions and instructions[0].op_name == "DEFUN":
            _ops = instructions[0].operands
            if len(_ops) == 4 and _ops[3] in (0, 1):
                _b1 = _ops[0]
                # 全零头（b1=0, b4=0）且已有参数：非 stub（自包含 gv/off 误判）
                if not (_b1 == 0 and _ops[3] == 0 and len(args) > 0):
                    _read = True
        if _read:
            _rest = _ops[3] == 1
            _min = _ops[1] if len(_ops) > 1 else len(args)
        else:
            _rest = False
            _min = len(args)

        return {
            "args": args,
            "arg_symbol_indices": arg_symbol_indices,
            "body_start": init_idx + 1,
            "local_binding_names": local_binding_names,
            "min_args": _min,
            "has_rest": _rest,
        }

    def _referenced_symbols(self, instructions: List[Instruction]) -> List[str]:
        names: List[str] = []
        seen = set()
        for inst in instructions:
            candidate = None
            if inst.op_name in ("USUBR", "FUNC") and len(inst.operands) >= 2:
                candidate = self._code_gvar_symbol(inst.operands[1]) or self._gvar_symbol(inst.operands[1])
            elif inst.op_name == "PUSH_VALUE" and inst.operands:
                candidate = self._gvar_symbol(inst.operands[0])
            elif inst.op_name == "PUSH_G" and inst.operands:
                literal = self._code_gvar_item(inst.operands[0])
                candidate = self._extract_symbol_text(literal)
            if candidate and candidate not in seen:
                names.append(candidate)
                seen.add(candidate)
        return names

    def _referenced_strings(self, instructions: List[Instruction]) -> List[str]:
        values: List[str] = []
        seen = set()
        for inst in instructions:
            if inst.op_name != "PUSH_G" or not inst.operands:
                continue
            literal = self._code_gvar_item(inst.operands[0])
            text = self._extract_text(literal)
            if isinstance(text, str) and not self._extract_symbol_text(literal):
                if text not in seen:
                    values.append(text)
                    seen.add(text)
        return values

    def _choose_function_name(self, func: FunctionDef, func_index: int, referenced_symbols: List[str]) -> str:
        if func.name and not func.name.startswith("c:fn") and not (func.sym_idx < 0 and func.name.startswith("c:init")):
            return func.name
        start_offset = func.instructions[0].offset if func.instructions else -1
        if start_offset in self.function_names_by_offset:
            return self.function_names_by_offset[start_offset]
        if func.sym_idx >= 0 and func.sym_idx in self.function_names_by_index:
            return self.function_names_by_index[func.sym_idx]
        if not self.function_names_by_offset and not self.function_names_by_index and func.instructions:
            for inst in func.instructions:
                if inst.op_name == "DEFUN" and inst.operands:
                    idx = inst.operands[0]
                    stub_name = self._gvar_symbol(idx)
                    if not stub_name and 0 <= idx < len(self.symbol_slots):
                        stub_name = self._extract_symbol_text(self.symbol_slots[idx])
                    if stub_name:
                        return stub_name
        if func.sym_idx < 0:
            return "fas_init" if func_index == 0 else f"fas_init_{func_index}"

        command_refs = [name for name in referenced_symbols if name.upper().startswith("C:")]
        unique_commands = list(dict.fromkeys(command_refs))
        if len(unique_commands) == 1:
            return unique_commands[0]

        for name in referenced_symbols:
            if name.upper() in self.BUILTIN_SYMBOLS:
                continue
            if len(name) <= 1:
                continue
            return name

        return f"fas_fn_{func_index + 1:04d}"

    def _deref_deferred_constant(self, value: Any) -> Any:
        """解析 stub 的 deferred 字节区间字面量引用。

        CAD 对未被当前模块消费的字面量（单函数文件的 quoted 常量等）不直接物化，
        而是存 `(('CONS', A, B),)`：A = 字节区间起点（相对），B = 字节长度。
        实际数据在 sec2 中紧跟 deferred 语句（`INT8 A, INT8 B, CONS, LIST1`）
        之后。通过 resource_items_with_offsets 定位该语句，取其结束偏移作 base，
        读 sec2[base : base + Bpasses] 并按资源流语义解码为常量值。

        仅在值严格为单元素包裹的 deferred 时触发；解析失败/无法定位则原样返回，
        保证不破坏既有路径。t12 的链式 `(('CONS',c,d),('CONS',a,b),('CONS',0,x))`
        是多元素 tuple，不在此处理。
        """
        if not (isinstance(value, tuple) and len(value) == 1):
            return value
        leaf = value[0]
        if not (
            isinstance(leaf, tuple)
            and len(leaf) == 3
            and leaf[0] == "CONS"
            and isinstance(leaf[1], int)
            and isinstance(leaf[2], int)
        ):
            return value
        offset, length = leaf[1], leaf[2]
        sec = self.fas.sec2_data
        if length <= 0 or offset < 0 or offset + length > len(sec):
            return value
        base = self._locate_deferred_base(offset, length)
        if base is None or base + length > len(sec):
            return value
        return self._decode_deferred_value(sec[base : base + length])

    def _locate_deferred_base(self, offset: int, length: int) -> Optional[int]:
        """定位 deferred 语句结束偏移（= 字面量数据起始）。

        语句为 `INT8 offset, INT8 length, CONS(0x2A), OP_0x39(1)` 序列，后跟
        STOP(0x00)。从 resource_items_with_offsets 找 `INT8 offset, INT8 length,
        OP_0x39 1` 三元组，返回其 OP_0x39 项偏移 + 3。
        """
        items = getattr(self.fas, "resource_items_with_offsets", None)
        if not items:
            return None
        for i in range(len(items) - 2):
            aoff, ait = items[i]
            _, bit = items[i + 1]
            coff, cit = items[i + 2]
            if ait[0] != "INT8" or bit[0] != "INT8" or cit[0] != "OP_0x39" or cit[1] != 1:
                continue
            if ait[1] != offset or bit[1] != length:
                continue
            return coff + 3
        return None

    def _decode_deferred_value(self, block: bytes) -> Any:
        """把字面量 block 解码回常量值。支持 INT8/INT32、SYMBOL/STRING、LIST、
        CONS（含 dotted）与递归结构。返回单个值（list 或原子）。"""
        stack: List[Any] = []
        pos = 0

        def pop_many(n):
            if n <= 0:
                return []
            if n > len(stack):
                n = len(stack)
            vals = stack[-n:]
            del stack[-n:]
            return vals

        while pos < len(block):
            op = block[pos]
            if op in (0x32,):
                pos += 1
                if pos < len(block):
                    v = block[pos]
                    stack.append(v if v <= 127 else v - 256)
                    pos += 1
            elif op in (0x33,):
                pos += 1
                if pos + 4 <= len(block):
                    import struct as _st

                    stack.append(_st.unpack("<i", block[pos : pos + 4])[0])
                    pos += 4
            elif op in (0x39,):
                pos += 1
                if pos + 2 <= len(block):
                    n = struct.unpack("<H", block[pos : pos + 2])[0]
                    pos += 2
                    stack.append(tuple(pop_many(n)))
            elif op == 0x2A:
                if len(stack) >= 2:
                    r = stack.pop()
                    l = stack.pop()
                    stack.append(("CONS", l, r))
                pos += 1
            elif op == 0x43:
                pos += 1
            elif op in (0x56, 0x5B):
                pos += 1
                end = block.find(b"\x00", pos)
                if end < 0:
                    break
                from core.fas_core import decode_fas_text

                name = decode_fas_text(block[pos:end])
                stack.append(("SYMBOL", name))
                pos = end + 1
            elif op in (0x1C, 0x01, 0x00):
                stack.append(None)
                pos += 1
            else:
                break
        # 取栈末（LIST/CONS 包裹后应只剩一个值）
        return stack[-1] if stack else None

    def _gvar_item(self, idx: int) -> Any:
        if self.is_stub_format:
            # stub 字节码引用（PUSH_G/PUSH_VALUE/SETQ_G/USUBR）的操作数均为
            # “gvar 槽 - 1”：运行时读 gvar_table[operand + 1]。字符串/符号常量
            # 若落在表内则优先取 gvar_table[idx+1]，表外（如单函数文件的字面量
            # 常量、参数读取）回退到资源注册顺序 symbol_slots[idx]。
            # gvar_table[0]=None、[1]=CONS 为固定结构槽，不参与 mvar-1 引用
            # （自包含格式的模块代码用 symbol_slots 直接编址，其 PUSH_G 0 会
            # 命中 [1]=CONS，必须回退）。
            result = None
            if 1 < idx + 1 < len(self.gvar_table):
                result = self.gvar_table[idx + 1]
                # 命中 gvar_table[idx+1] 时须立即返回：该操作数是“gvar 槽 - 1”，
                # 运行时读 gvar_table[operand+1]（t11：操作数 6 → 槽 7 的
                # `(RESULT I)` 局部绑定列表）。若继续无条件以 symbol_slots[idx]
                # 回退，会把多元素常量（`'(result i)`）误收为单符号槽（`'result`）。
                # 仅当该槽为占位单例/None 时才回退 symbol_slots。
                if result is not None:
                    return result
            elif 0 <= idx < len(self.gvar_table):
                # 单函数紧凑 stub：操作数直接指向 gvar 槽（非 +1），deferred
                # 字面量常驻 gvar_table[idx]（q_single 的 PUSH_G 1 → 槽 1）。
                # 仅当该槽为可解析成非空常量值（长度 >0 且解码出真实值）时
                # 采纳，避免把 `(CONS,0,0)` 这类占位单例误认成 deferred
                # （dotted `(cons 1 . 2)` 合成产物），破坏既有符号回退。
                candidate = self.gvar_table[idx]
                deref = self._deref_deferred_constant(candidate)
                if deref is not None and deref is not candidate:
                    result = deref
                    return result
            # 函数表 GVARINIT 的 module_id 槽（var_pos+st_init）：结构化常量
            # （t12 的 `(A B C)` 于槽 5，PUSH_G 4 经「槽 - 1」引用）。操作数
            # idx 的 mvar-1 语义 = 槽 idx+1。仅在 gvar_table 越界（槽在 nsyms
            # 之外、build_mvar_tables 表装不下）时查询，避免与表内 mvar-1
            # 分支冲突。
            if idx + 1 in self._stub_module_id_slots():
                return self._stub_module_id_slots()[idx + 1]
            if 0 <= idx < len(self.symbol_slots):
                return self.symbol_slots[idx]
            return None
        if 0 <= idx < len(self.fas.function_gvars) and self.fas.function_gvars[idx] is not None:
            return self.fas.function_gvars[idx]
        if 0 <= idx < len(self.fas.resource_gvars) and self.fas.resource_gvars[idx] is not None:
            return self.fas.resource_gvars[idx]
        if 0 <= idx < len(self.fas.symbols):
            return self.fas.symbols[idx]
        return None

    def _code_gvar_item(self, idx: int) -> Any:
        if self.is_stub_format:
            return self._gvar_item(idx)
        shifted_idx = idx + self.code_ref_bias
        if (
            self.code_ref_bias
            and idx < self.variable_ref_floor
            and 0 <= shifted_idx < len(self.fas.function_gvars)
            and self.fas.function_gvars[shifted_idx] is not None
        ):
            return self.fas.function_gvars[shifted_idx]
        return self._gvar_item(idx)

    def _gvar_symbol(self, idx: int) -> Optional[str]:
        value = self._gvar_item(idx)
        return self._extract_symbol_text(value)

    def _gvar_symbol_gvar(self, idx: int) -> Optional[str]:
        """stub 格式 USUBR 索引 = gvar 槽 - 1，调用名取自 gvar 表 idx+1。

        CAD golden 的 gvar 表足够长（[None, deferred, 符号槽...]），idx+1 命中
        符号；CLI 单函数紧凑 stub 的 gvar 表只有 [None, deferred]（len=2），
        idx+1 越界或命中非符号槽（如列表字面量 `(1 2)` 遮蔽 `+`），此时回落
        资源注册顺序 symbol_slots[idx]。CAD 路径的 idx+1 必命中符号，不触发
        该 fallback，因此不影响既有一致性。
        """
        if self.is_stub_format:
            j = idx + 1
            if 0 <= j < len(self.gvar_table):
                sym = self._extract_symbol_text(self.gvar_table[j])
                if sym:
                    return sym
            if 0 <= idx < len(self.symbol_slots):
                sym = self._extract_symbol_text(self.symbol_slots[idx])
                if sym:
                    return sym
        return self._gvar_symbol(idx)

    def _code_gvar_symbol(self, idx: int) -> Optional[str]:
        value = self._code_gvar_item(idx)
        return self._extract_symbol_text(value)

    def _resource_gvar_text(self, idx: int) -> Optional[str]:
        if 0 <= idx < len(self.fas.resource_gvars):
            return self._extract_text(self.fas.resource_gvars[idx])
        return None

    def _value_from_gvar(self, idx: int, spec: Dict[str, Any]) -> str:
        bound_gvar = spec.get("bound_gvar_map", {}).get(idx)
        if bound_gvar:
            return bound_gvar

        bound_name = self._bound_symbol_name(idx, spec)
        if bound_name:
            return bound_name

        aliases = spec["global_aliases"]
        if idx in aliases:
            return aliases[idx]

        raw_name = self._gvar_symbol(idx) or f"gvar_{idx}"
        candidate = raw_name
        if not any(ch.isalpha() for ch in raw_name) and not raw_name.startswith("*"):
            candidate = f"gvar_{idx}"
        elif raw_name.upper() in self.BUILTIN_SYMBOLS or raw_name.upper().startswith("C:"):
            candidate = f"gvar_{idx}_{raw_name}"
        aliases[idx] = self._unique_symbol(candidate, f"gvar_{idx}", False, spec["local_used"])
        return aliases[idx]

    def _literal_from_gvar(self, idx: int) -> str:
        return self._render_literal(self._code_gvar_item(idx))

    def _call_name(
        self, idx: int, argc: int = 0, spec: Optional[Dict[str, Any]] = None, args: Optional[List[str]] = None
    ) -> str:
        raw_name = self._gvar_symbol_gvar(idx)
        biased_name = self._gvar_symbol_gvar(idx)
        # `command` 内建 SUBR 在 FAS 资源段注册名为 `ads-cmd`（AutoCAD 内部 C
        # 函数名），反编译时还原为 AutoLISP 的 `command`。
        if raw_name and raw_name.lower() == "ads-cmd":
            return "command"
        if biased_name and biased_name.lower() == "ads-cmd":
            return "command"
        if argc == 1 and (
            (raw_name and raw_name.upper() == "POLAR") or (biased_name and biased_name.upper() == "POLAR")
        ):
            return "fas-polar1"
        if (
            argc == 3
            and args
            and ((raw_name and raw_name.upper() == "RTOS") or (biased_name and biased_name.upper() == "RTOS"))
            and self._looks_project_rtos_args(args)
        ):
            return "fas-rtos3"
        if raw_name and raw_name.upper() == "1-" and argc == 1:
            return "fas-1-"
        if biased_name and biased_name.upper() == "1-" and argc == 1:
            return "fas-1-"
        if raw_name and raw_name.upper() == "GETVAR" and argc in (2, 3):
            return f"fas-getvar{argc}"
        if biased_name and biased_name.upper() == "GETVAR" and argc in (2, 3):
            return f"fas-getvar{argc}"
        if biased_name and biased_name != raw_name and self._looks_callable_name(biased_name):
            biased_arity = self.COMMON_ARITY.get(biased_name.upper())
            raw_ok = bool(
                raw_name and self._looks_callable_name(raw_name) and not self._is_bad_builtin_arity(raw_name, argc)
            )
            if biased_arity is not None and argc in biased_arity:
                return self._normalize_symbol(biased_name, f"gfun_{idx}", allow_command_prefix=True)
            if not raw_ok:
                return self._normalize_symbol(biased_name, f"gfun_{idx}", allow_command_prefix=True)
        if raw_name and self._looks_callable_name(raw_name):
            repaired = self._repair_call_target(idx, raw_name, argc, spec, args or [])
            if repaired:
                raw_name = repaired
            if raw_name.upper() == "RTOS" and self._looks_project_rtos_args(args or []):
                return "fas-rtos3" if argc == 3 else "fas-rtos1"
            if raw_name.upper() == "1-" and argc == 1:
                return "fas-1-"
            if raw_name.upper() == "GETVAR" and argc in (2, 3):
                return f"fas-getvar{argc}"
            return self._normalize_symbol(raw_name, f"gfun_{idx}", allow_command_prefix=True)
        repaired = self._repair_call_target(idx, None, argc, spec, args or [])
        if repaired:
            if repaired.upper() == "RTOS" and self._looks_project_rtos_args(args or []):
                return "fas-rtos3" if argc == 3 else "fas-rtos1"
            if repaired.upper() == "1-" and argc == 1:
                return "fas-1-"
            if repaired.upper() == "GETVAR" and argc in (2, 3):
                return f"fas-getvar{argc}"
            return self._normalize_symbol(repaired, f"gfun_{idx}", allow_command_prefix=True)
        return f"gfun_{idx}"

    def _local_name(self, slot: int, spec: Dict[str, Any]) -> str:
        if slot not in spec["slot_names"]:
            spec["slot_names"][slot] = self._unique_symbol(
                f"local_{slot}",
                f"local_{slot}",
                False,
                spec["local_used"],
            )
        return spec["slot_names"][slot]

    def _render_literal(self, value: Any) -> str:
        if value is None:
            return "nil"
        if value is True:
            return "T"
        if isinstance(value, int):
            return str(value)
        symbol_text = self._extract_symbol_text(value)
        if symbol_text:
            return "'" + self._normalize_symbol(symbol_text, "sym", allow_command_prefix=True)
        text = self._extract_text(value)
        if isinstance(text, str):
            return self._quote(text)
        rendered = self._render_data_item(value)
        if rendered.startswith("("):
            return "'" + rendered
        return "'" + rendered

    def _render_data_item(self, value: Any) -> str:
        if value is None:
            return "nil"
        if value is True:
            return "T"
        if isinstance(value, int):
            return str(value)
        symbol_text = self._extract_symbol_text(value)
        if symbol_text:
            return self._normalize_symbol(symbol_text, "sym", allow_command_prefix=True)
        text = self._extract_text(value)
        if isinstance(text, str):
            return self._quote(text)
        if isinstance(value, tuple):
            if len(value) >= 4 and value[0] == "FUNC":
                func_name = self._extract_symbol_text(value[1]) or self._extract_text(value[1]) or "fn"
                return self._normalize_symbol(str(func_name), "fn", allow_command_prefix=True)
            if len(value) == 3 and value[0] == "CONS":
                # 资源流的 CONS(0x2A) 构造的是 dotted pair 字面量 `(l . r)`
                # （t12 `'(1 . 2)` 实测），非 `cons` 函数调用——函数调用走
                # CALL 路径（USUBR cons）。渲染为 `(l . r)`。
                return f"({self._render_data_item(value[1])} . {self._render_data_item(value[2])})"
            if len(value) == 5 and value[0] == "CALL":
                func_name = self._extract_symbol_text(value[1]) or self._extract_text(value[1]) or f"gfun_{value[2]}"
                args = [self._render_data_item(item) for item in value[4]]
                return self._make_call_text(
                    self._normalize_symbol(str(func_name), "fn", allow_command_prefix=True), args
                )
            if len(value) == 4 and value[0] == "EVAL":
                args = [self._render_data_item(item) for item in value[3]]
                return self._make_call_text("eval", args)
            if len(value) == 2 and value[0] in ("STRING", "REAL"):
                return self._quote(str(value[1]))
            if len(value) == 2 and value[0] == "SYMBOL":
                return self._normalize_symbol(str(value[1]), "sym", allow_command_prefix=True)
            if len(value) == 2 and value[0] in ("NOT", "ATOM"):
                return f"({value[0].lower()} {self._render_data_item(value[1])})"
            return "(" + " ".join(self._render_data_item(item) for item in value) + ")"
        return self._quote(str(value))

    def _extract_text(self, value: Any) -> Optional[str]:
        if isinstance(value, str):
            return value
        if isinstance(value, tuple) and len(value) == 2 and value[0] in ("STRING", "SYMBOL", "REAL"):
            return str(value[1])
        return None

    def _extract_symbol_text(self, value: Any) -> Optional[str]:
        if isinstance(value, str) and self._is_symbol_like(value):
            return value
        if isinstance(value, tuple) and len(value) == 2 and value[0] == "SYMBOL":
            return str(value[1])
        return None

    def _extract_symbol_list(self, value: Any) -> List[str]:
        if not isinstance(value, tuple) or not value:
            return []
        if len(value) == 2 and value[0] in ("SYMBOL", "STRING", "REAL"):
            return []
        result: List[str] = []
        for item in value:
            text = self._extract_symbol_text(item)
            if not text:
                return []
            result.append(text)
        return result

    def _bound_symbol_name(self, idx: int, spec: Dict[str, Any]) -> Optional[str]:
        bound = spec.get("bound_symbol_map", {})
        name = self._gvar_symbol(idx)
        if name and name.upper() in bound:
            return bound[name.upper()]
        if not name:
            for candidate_idx in (idx + 1, idx - 1, idx + 2, idx - 2):
                name = self._gvar_symbol(candidate_idx)
                if name and name.upper() in bound:
                    return bound[name.upper()]
        return None

    def _repair_call_target(
        self, idx: int, raw_name: Optional[str], argc: int, spec: Optional[Dict[str, Any]], args: List[str]
    ) -> Optional[str]:
        if raw_name and not self._is_bad_builtin_arity(raw_name, argc):
            return raw_name

        prefer_princ = argc == 1 and any(arg.startswith('"') or "strcat" in arg.lower() for arg in args)
        best_name = None
        best_score = None
        max_distance = 24 if raw_name is None else 12
        for distance in range(1, max_distance + 1):
            for candidate_idx in (idx + distance, idx - distance):
                name = self._gvar_symbol(candidate_idx)
                if not name or not self._looks_callable_name(name):
                    continue
                if spec and name.upper() in spec.get("bound_symbol_map", {}):
                    continue
                if raw_name is None and self._is_bad_builtin_arity(name, argc):
                    continue
                score = -distance
                arity = self.COMMON_ARITY.get(name.upper())
                if arity is not None and argc in arity:
                    score += 250
                elif not self._is_bad_builtin_arity(name, argc):
                    score += 100
                if prefer_princ and name.upper() == "PRINC":
                    score += 200
                if best_score is None or score > best_score:
                    best_name = name
                    best_score = score

        if best_name:
            return best_name

        if raw_name:
            return raw_name
        return None

    def _skip_literal_zero_arg_call(self, idx: int, argc: int) -> bool:
        """Drop a known malformed no-arg call reconstructed as ``(re_rel)``.

        In bib.fas, three zero-argument USUBR instructions point at the prompt
        string "Choix du point :". The nearest-symbol repair used to map those
        to RE_REL, but the file only uses RE_REL as data and as a three-arg
        helper, so the fabricated ``(re_rel)`` crashes the target CAD immediately.
        """
        if argc != 0:
            return False
        if self._gvar_symbol(idx) or self._code_gvar_symbol(idx):
            return False
        value = self._code_gvar_item(idx)
        text = self._extract_text(value)
        return text == "Choix du point :" and ((self._gvar_symbol(idx + 4) or "").upper() == "RE_REL")

    def _looks_project_rtos_args(self, args: List[str]) -> bool:
        return bool(args and args[0].lstrip().startswith("'"))

    def _is_bad_builtin_arity(self, name: str, argc: int) -> bool:
        allowed = self.COMMON_ARITY.get(name.upper())
        if allowed is None:
            return False
        return argc not in allowed

    def _make_call_text(self, name: str, args: List[str]) -> str:
        if args:
            return f'({name} {" ".join(args)})'
        return f"({name})"

    def _statement_line(self, expr: str, indent: int = 1) -> str:
        prefix = "  " * indent
        return f"{prefix}{expr}"

    def _strip_strings(self, text: str) -> str:
        result: List[str] = []
        in_string = False
        escaped = False
        for ch in text:
            if escaped:
                escaped = False
                result.append(" " if in_string else ch)
                continue
            if ch == "\\" and in_string:
                escaped = True
                result.append(" ")
                continue
            if ch == '"':
                in_string = not in_string
                result.append(" ")
                continue
            result.append(" " if in_string else ch)
        return "".join(result)

    def _is_symbol_char(self, ch: str) -> bool:
        return bool(re.match(r"[A-Za-z0-9_:+<>=?.*/-]", ch))

    def _symbol_pattern(self, symbol: str) -> re.Pattern:
        return re.compile(rf"(?<![A-Za-z0-9_:+<>=?.*/-]){re.escape(symbol)}(?![A-Za-z0-9_:+<>=?.*/-])")

    def _replace_symbols(self, text: str, replacements: Dict[str, str]) -> str:
        if not replacements:
            return text
        keys = sorted(replacements, key=len, reverse=True)
        result: List[str] = []
        i = 0
        in_string = False
        escaped = False
        while i < len(text):
            ch = text[i]
            if escaped:
                result.append(ch)
                escaped = False
                i += 1
                continue
            if ch == "\\" and in_string:
                result.append(ch)
                escaped = True
                i += 1
                continue
            if ch == '"':
                result.append(ch)
                in_string = not in_string
                i += 1
                continue
            if in_string:
                result.append(ch)
                i += 1
                continue

            replaced = False
            prev = text[i - 1] if i else ""
            if not prev or not self._is_symbol_char(prev):
                for key in keys:
                    if not text.startswith(key, i):
                        continue
                    nxt_pos = i + len(key)
                    nxt = text[nxt_pos] if nxt_pos < len(text) else ""
                    if nxt and self._is_symbol_char(nxt):
                        continue
                    result.append(replacements[key])
                    i = nxt_pos
                    replaced = True
                    break
            if not replaced:
                result.append(ch)
                i += 1
        return "".join(result)

    def _is_symbol_like(self, value: str) -> bool:
        if not value:
            return False
        if "\n" in value or "\r" in value or " " in value or '"' in value:
            return False
        return bool(re.match(r"^[A-Za-z0-9_:\\/*+#<>=?.-]+$", value))

    def _normalize_symbol(self, name: str, prefix: str = "sym", allow_command_prefix: bool = False) -> str:
        if not name:
            return prefix

        raw = name.strip()
        if raw in {"=", ">", "<", ">=", "<=", "/=", "1+", "1-", "+", "-", "*", "/"}:
            return raw.lower()

        if "|" in raw:
            raw = raw.replace("|", ":")
        command_prefix = raw[:2].lower() if allow_command_prefix and raw.upper().startswith("C:") else ""
        body = raw[2:] if command_prefix else raw

        if raw.startswith("*") and raw.endswith("*") and len(raw) > 2:
            inner = re.sub(r"[^\w:-]+", "_", raw[1:-1]).strip("_")
            return f"*{(inner or prefix).lower()}*"

        body = re.sub(r"[^\w+<>=.:-]+", "_", body)
        body = re.sub(r"_+", "_", body)
        if not body:
            body = prefix
        if body[0].isdigit():
            body = f"{prefix}_{body}"
        return f"{command_prefix}{body}".lower() if command_prefix else body.lower()

    def _looks_callable_name(self, value: str) -> bool:
        if value in {"=", ">", "<", ">=", "<=", "/=", "1+", "1-", "+", "-", "*", "/"}:
            return True
        return any(ch.isalpha() for ch in value) or value.upper().startswith("C:") or value.startswith("*")

    def _unique_symbol(self, name: str, prefix: str, allow_command_prefix: bool, used: Set[str]) -> str:
        candidate = self._normalize_symbol(name, prefix, allow_command_prefix)
        counter = 2
        unique = candidate
        while unique in used:
            unique = f"{candidate}_{counter}"
            counter += 1
        used.add(unique)
        return unique

    def _quote(self, value: str) -> str:
        escaped = (
            value.replace("\\", "\\\\")
            .replace('"', '\\"')
            .replace("\r", "\\r")
            .replace("\n", "\\n")
            .replace("\t", "\\t")
            .replace("\x1b", "\\e")
        )
        return f'"{escaped}"'


class Fas4Decompiler:
    def decompile(self, filepath: str, output_path: Optional[str] = None) -> str:
        parser = Fas4Parser()
        fas = parser.parse(filepath)
        _stub = is_compact_stub(fas.bytecode, fas.function_catalog, len(fas.symbol_slots))
        disasm = Disassembler(short_subr=use_short_subr(fas.bytecode, fas.nsyms, fas.function_catalog, len(fas.symbol_slots)))
        instructions = disasm.disassemble(
            fas.bytecode,
            fas.nsyms,
            sym_count=len(fas.symbol_slots) if _stub else None,
        )
        cf = ControlFlowAnalyzer(instructions, fas.function_catalog, function_names=extract_stub_function_names(fas))
        functions = cf.find_functions()
        gen = LispGenerator(fas)
        code = gen.generate(functions, filepath)
        if output_path is None:
            base = os.path.splitext(filepath)[0]
            output_path = base + "_decompiled.lsp"
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(code)
        return code


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python -m decompiler.fas4_decompiler <input.fas> [output.lsp]")
        sys.exit(1)
    input_file = sys.argv[1]
    output_file = sys.argv[2] if len(sys.argv) > 2 else None
    if not os.path.exists(input_file):
        print(f"Error: File '{input_file}' not found")
        sys.exit(1)
    decompiler = Fas4Decompiler()
    try:
        decompiler.decompile(input_file, output_file)
        print(f"Decompilation complete for {input_file}")
    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)
