#!/usr/bin/env python3
from __future__ import annotations

"""
FAS4 核心模块 — 统一解析、解密、符号表重建。

被 fas-split.py / fas-analyzer.py / fas4_decompiler.py 共享。
"""

import struct
import re
import os
from typing import Any, List, Tuple

# ─── 常量 ──────────────────────────────────────────────────────────────────────

FAS4_MAGIC = b"\r\n FAS4-FILE ; Do not change it!\r\n"
CRUNCH_MARKER = b"\n;fas4 crunch\n;"
FUNC_DEF_OPCODE = bytes([0x14, 0x01, 0x01, 0x01, 0x00])
SEG_TERMINATOR = b"\x16\x24\r\n"

# ─── 加解密 ────────────────────────────────────────────────────────────────────


def mixor_decrypt(data: bytes, key: bytes) -> bytes:
    """双字节滚动 XOR 解密（与 FAS4 运行时相同）。"""
    mk = bytearray(key)
    while len(mk) < len(data) + 1:
        mk = mk + mk
    result = bytearray(len(data))
    for i in range(len(data)):
        result[i] = data[i] ^ mk[i] ^ mk[i + 1]
    return bytes(result)


def decrypt_stream(encrypted: bytes, key: bytes) -> bytes:
    """FAS4 XOR 密码，从 key[1] 开始轮转（与 fas4_decompiler 相同）。"""
    result = bytearray(len(encrypted))
    key_old = key[0]
    kp = 1
    for i in range(len(encrypted)):
        if kp >= len(key):
            kp = 0
        key_new = key[kp]
        result[i] = encrypted[i] ^ key_new ^ key_old
        key_old = key_new
        kp += 1
    return bytes(result)


def find_key(data: bytes) -> bytes | None:
    """通过 crunch 标记向前查找 XOR 密钥。"""
    pos = data.find(CRUNCH_MARKER)
    if pos < 0:
        return None
    for rlen in range(6, 12):
        key_start = pos - rlen
        key_end = pos + len(CRUNCH_MARKER)
        key_len = key_end - key_start
        lbp = key_start - 1
        if lbp >= 0 and data[lbp] == key_len:
            return data[key_start:key_end]
    return None


# ─── 文件解析 ──────────────────────────────────────────────────────────────────


def parse_fas4(filepath: str, decrypt_seg1: bool = True) -> dict:
    """完整解析 FAS4 文件，返回结构化结果。

    返回字典:
     - nsyms: int               全局符号/变量数
     - bytecode: bytes          seg0 字节码
     - segments: list           seg0/seg1 描述
     - key: bytes | None        XOR 密钥
     - res_data_encrypted: bytes  加密的 seg1 数据
     - res_data_decrypted: bytes  解密后的 seg1 数据
     - res_items: int           seg1 中变量/条目数
     - trailer: str             crunch 尾部
    """
    with open(filepath, "rb") as f:
        data = f.read()

    hpos = data.find(FAS4_MAGIC)
    if hpos < 0:
        raise ValueError("Not a valid FAS4 file")

    after = hpos + len(FAS4_MAGIC)
    size_end = data.find(b"\r\n", after)
    total_size = int(data[after:size_end])
    payload_start = size_end + 2
    payload = data[payload_start : payload_start + total_size]

    m = re.match(rb"(\d+) \$", payload)
    if not m:
        raise ValueError("Cannot find nsyms header")
    nsyms = int(m.group(1))
    bytecode = payload[m.end() :]

    after_payload = payload_start + total_size
    rest = data[after_payload:]

    key = find_key(data)
    trailer = ""
    crunch_m = re.search(rb";fas4 crunch\n;\$;A([\d/]+)", data)
    if crunch_m:
        trailer = crunch_m.group(0).decode("ascii", errors="replace")

    m2 = re.search(rb"(\d+) (\d+) \$", rest)
    res_data_encrypted = b""
    res_items = 0
    if m2:
        res_size = int(m2.group(1))
        res_items = int(m2.group(2))
        res_start = after_payload + m2.end()
        res_data_encrypted = data[res_start : res_start + res_size]

    res_data_decrypted = b""
    if key and decrypt_seg1 and res_data_encrypted:
        res_data_decrypted = decrypt_stream(res_data_encrypted, key)

    segments = [
        {
            "index": 0,
            "data": bytecode,
            "total_len": total_size - (m.end() - m.start()),
            "sub_count": nsyms,
        },
        {
            "index": 1,
            "data_encrypted": res_data_encrypted,
            "data_decrypted": res_data_decrypted,
            "total_len": len(res_data_encrypted),
            "sub_count": res_items,
        },
    ]

    return {
        "nsyms": nsyms,
        "bytecode": bytecode,
        "segments": segments,
        "key": key,
        "res_data_encrypted": res_data_encrypted,
        "res_data_decrypted": res_data_decrypted,
        "res_items": res_items,
        "trailer": trailer,
    }


# ─── 资源流（seg1）解析 ──────────────────────────────────────────────────────────


def get_ansi_encoding() -> str:
    """返回 Windows 系统 ANSI 代码页编码（如中文系统 cp936/GBK）。

    非 Windows 平台回退 UTF-8（无 ANSI 概念）。
    """
    if os.name == 'nt':
        try:
            import ctypes
            return f'cp{ctypes.windll.kernel32.GetACP()}'
        except Exception:
            pass
    return 'utf-8'


def decode_fas_text(raw: bytes) -> str:
    """FAS 字符串解码：ascii → utf-8 → 系统 ANSI → gbk → cp1252 → latin-1。

    CAD 编译器将字符串按系统 ANSI 代码页写入（中文系统=GBK，法语=cp1252）。
    先尝试 ASCII/UTF-8（本编译器历史输出），再按本机 ANSI 代码页解，
    最后回退 gbk/cp1252/latin-1。
    """
    chain = ["ascii", "utf-8", get_ansi_encoding(), "gbk", "cp1252", "latin-1"]
    seen = set()
    for enc in chain:
        if enc in seen:
            continue
        seen.add(enc)
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("latin-1", errors="replace")


def parse_resource_stream(res_data: bytes) -> tuple:
    """解析解密后的 seg1 资源流，返回 (items, symbols, strings)。

    items:          [(opcode_type, value...), ...] 所有操作码
    symbols:        [str, ...]  符号名称列表（按出现顺序）
    strings:        [str, ...]  字符串字面量列表（按出现顺序）
    """
    pos = 0
    items: List[Tuple[Any, ...]] = []
    symbols = []
    strings = []

    def decode_text(raw: bytes) -> str:
        return decode_fas_text(raw)

    while pos < len(res_data):
        op = res_data[pos]
        start = pos

        if op in (0x14, 0x15):  # defun 头
            pos += 2
        elif op == 0x55:  # 字符串块
            pos += 1
            if pos + 2 > len(res_data):
                break
            num_strings = struct.unpack("<H", res_data[pos : pos + 2])[0]
            pos += 2
            for _ in range(num_strings):
                if pos + 2 > len(res_data):
                    break
                slen = struct.unpack("<H", res_data[pos : pos + 2])[0]
                pos += 2
                if pos + slen > len(res_data):
                    break
                s = decode_text(res_data[pos : pos + slen])
                pos += slen
                items.append(("STRING", s))
                strings.append(s)
        elif op in (0x56, 0x5B):  # 符号块
            pos += 1
            while pos < len(res_data):
                end = res_data.find(b"\x00", pos)
                if end < 0:
                    break
                sym = res_data[pos:end]
                pos = end + 1
                if not sym:
                    break
                name = decode_text(sym)
                items.append(("SYMBOL", name))
                symbols.append(name)
        elif op == 0x43:  # GVar init
            pos += 1
        elif op in (0x34, 0x35, 0x51):
            pos += 1
            if pos >= len(res_data):
                break
            argc = res_data[pos]
            pos += 1
            if op in (0x35, 0x51) and pos + 2 <= len(res_data):
                idx = struct.unpack("<H", res_data[pos : pos + 2])[0]
                pos += 2
                items.append(("FUNC_REF", idx, argc))
            if pos < len(res_data):
                pos += 1
        elif op == 0x32:  # PUSH_INT8
            pos += 1
            if pos < len(res_data):
                val = res_data[pos]
                if val > 127:
                    val -= 256
                pos += 1
                items.append(("INT8", val))
        elif op == 0x33:  # PUSH_INT32
            pos += 1
            if pos + 4 <= len(res_data):
                val = struct.unpack("<i", res_data[pos : pos + 4])[0]
                pos += 4
                items.append(("INT32", val))
        elif op == 0x3B:  # PUSH_REAL
            pos += 1
            end = res_data.find(b"\x00", pos)
            if end >= 0:
                items.append(("REAL", decode_text(res_data[pos:end])))
                pos = end + 1
            else:
                break
        elif op == 0x3A:  # DEFCODE (FUNC)
            pos += 1
        elif op in (0x09, 0x03):  # GVAR_PUSH
            pos += 1
            if pos + 2 <= len(res_data):
                idx = struct.unpack("<H", res_data[pos : pos + 2])[0]
                pos += 2
                items.append(("GVAR_PUSH", idx))
        elif op in (0x06, 0x1A, 0x1B, 0x0C):  # GVAR_STORE / 其他2字节索引
            pos += 1
            if pos + 2 <= len(res_data):
                idx = struct.unpack("<H", res_data[pos : pos + 2])[0]
                pos += 2
                items.append(("GVAR_STORE", idx))
        elif op == 0x0A:  # POP
            pos += 1
            items.append(("POP",))
        elif op in (0x01, 0x00):  # PUSH_NIL
            pos += 1
            items.append(("NIL",))
        elif op == 0x02:  # PUSH_T
            pos += 1
            items.append(("T",))
        elif op == 0x16:  # END_DEFUN
            pos += 1
            items.append(("END_DEFUN",))
        elif op == 0x1C:  # INIT_DONE
            pos += 1
            items.append(("INIT_DONE",))
        elif op in (0x18, 0x19, 0x39, 0x37):  # 计数操作
            pos += 1
            if pos + 2 <= len(res_data):
                count = struct.unpack("<H", res_data[pos : pos + 2])[0]
                pos += 2
                items.append(("OP_" + hex(op), count))
        elif op in (0x05, 0x5C, 0x5D, 0x5E):  # 局部变量
            pos += 1
            if pos + 2 <= len(res_data):
                idx = struct.unpack("<H", res_data[pos : pos + 2])[0]
                pos += 2
                items.append(("LOCAL", idx))
        elif op in (0x67, 0x57, 0x69, 0x6A, 0x68):  # 跳转
            pos += 1
            if pos + 4 <= len(res_data):
                target = struct.unpack("<i", res_data[pos : pos + 4])[0]
                pos += 4
                items.append(("JUMP", target))
        elif op in (0x0D, 0x3C, 0x0E, 0x3D, 0x07):  # 短跳转
            pos += 1
            if pos + 2 <= len(res_data):
                pos += 2
        elif op in (0x1E, 0x1F):  # ALPHA/BETA
            pos += 1
            if pos < len(res_data):
                pos += 1
        elif op in (0x20, 0x62, 0x63, 0x3E, 0x3F, 0x38, 0x40, 0x21):
            pos += 1
        elif op in (0x0B, 0x23, 0x24, 0x10, 0x28, 0x29, 0x2A):
            pos += 1
            items.append(("OP_" + hex(op),))
        else:
            pos += 1

    return items, symbols, strings


def build_mvar_tables(res_data: bytes, nsyms: int) -> tuple:
    """重建 FAS4 的两个 GVar 表。

    返回 (resource_gvars: list, function_gvars: list)，
    每个长度为 nsyms，None 表示未赋值。
    """
    tables: dict = {0: [None] * nsyms, 1: [None] * nsyms}
    stack: list = []

    def table0(idx):
        return tables[0][idx] if 0 <= idx < nsyms else None

    def pop_default(default=None):
        return stack.pop() if stack else default

    def pop_many(count):
        if count <= 0:
            return []
        if count > len(stack):
            count = len(stack)
        values = stack[-count:]
        del stack[-count:]
        return values

    pos = 0
    while pos < len(res_data):
        op = res_data[pos]

        if op in (0x00, 0x01):
            stack.append(None)
            pos += 1
        elif op == 0x02:
            stack.append(True)
            pos += 1
        elif op == 0x0A:
            if stack:
                stack.pop()
            pos += 1
        elif op == 0x0B:
            if stack:
                stack.append(stack[-1])
            pos += 1
        elif op in (0x14, 0x15):
            if pos + 5 > len(res_data):
                break
            stack.append(("DEFHDR", tuple(res_data[pos + 1 : pos + 5])))
            pos += 5
        elif op in (0x03, 0x09):
            if pos + 3 > len(res_data):
                break
            idx = struct.unpack("<H", res_data[pos + 1 : pos + 3])[0]
            stack.append(table0(idx))
            pos += 3
        elif op == 0x06:
            if pos + 3 > len(res_data):
                break
            idx = struct.unpack("<H", res_data[pos + 1 : pos + 3])[0]
            if 0 <= idx < nsyms:
                tables[0][idx] = pop_default()
            pos += 3
        elif op == 0x2A:
            if len(stack) >= 2:
                right = stack.pop()
                left = stack.pop()
                stack.append(("CONS", left, right))
            pos += 1
        elif op in (0x28, 0x29):
            value = pop_default()
            if op == 0x28:
                if isinstance(value, tuple) and len(value) == 3 and value[0] == "CONS":
                    stack.append(value[1])
                elif isinstance(value, tuple) and value:
                    stack.append(value[0])
                else:
                    stack.append(("CAR", value))
            else:
                if isinstance(value, tuple) and len(value) == 3 and value[0] == "CONS":
                    stack.append(value[2])
                elif isinstance(value, tuple) and len(value) > 1:
                    stack.append(tuple(value[1:]))
                else:
                    stack.append(("CDR", value))
            pos += 1
        elif op == 0x32:
            if pos + 2 > len(res_data):
                break
            stack.append(struct.unpack("<b", res_data[pos + 1 : pos + 2])[0])
            pos += 2
        elif op == 0x33:
            if pos + 5 > len(res_data):
                break
            stack.append(struct.unpack("<i", res_data[pos + 1 : pos + 5])[0])
            pos += 5
        elif op == 0x39:
            if pos + 3 > len(res_data):
                break
            count = struct.unpack("<H", res_data[pos + 1 : pos + 3])[0]
            stack.append(tuple(pop_many(count)))
            pos += 3
        elif op == 0x34:
            if pos + 3 > len(res_data):
                break
            argc = res_data[pos + 1]
            flags = res_data[pos + 2]
            args = pop_many(argc + 1)
            stack.append(("EVAL", argc, flags, tuple(args)))
            pos += 3
        elif op in (0x35, 0x51):
            if pos + 5 > len(res_data):
                break
            argc = res_data[pos + 1]
            idx = struct.unpack("<H", res_data[pos + 2 : pos + 4])[0]
            flags = res_data[pos + 4]
            args = pop_many(argc)
            stack.append(("CALL", table0(idx), idx, flags, tuple(args)))
            pos += 5
        elif op == 0x55:
            pos += 1
            if pos + 2 > len(res_data):
                break
            num_strings = struct.unpack("<H", res_data[pos : pos + 2])[0]
            pos += 2
            for _ in range(num_strings):
                if pos + 2 > len(res_data):
                    break
                slen = struct.unpack("<H", res_data[pos : pos + 2])[0]
                pos += 2
                if pos + slen > len(res_data):
                    break
                s = res_data[pos : pos + slen]
                pos += slen
                stack.append(("STRING", decode_fas_text(s)))
        elif op in (0x56, 0x5B):
            pos += 1
            while pos < len(res_data):
                end = res_data.find(b"\x00", pos)
                if end < 0:
                    break
                sym = res_data[pos:end]
                pos = end + 1
                if not sym:
                    break
                stack.append(("SYMBOL", decode_fas_text(sym)))
        elif op == 0x3A:
            if len(stack) >= 3:
                name = stack.pop()
                start = stack.pop()
                module = stack.pop()
                stack.append(("FUNC", name, start, module))
            pos += 1
        elif op == 0x43:
            if pos + 5 > len(res_data):
                break
            var_pos = struct.unpack("<H", res_data[pos + 1 : pos + 3])[0]
            st_init = struct.unpack("<H", res_data[pos + 3 : pos + 5])[0]
            module_id = stack.pop() if stack else None
            table_idx = 0 if module_id is None else 1
            for idx in range(var_pos + st_init - 1, var_pos - 1, -1):
                if not stack:
                    break
                value = stack.pop()
                if 0 <= idx < nsyms:
                    tables[table_idx][idx] = value
            pos += 5
        elif op == 0x23:
            stack.append(("NOT", pop_default()))
            pos += 1
        elif op == 0x24:
            stack.append(("ATOM", pop_default()))
            pos += 1
        elif op in (0x57, 0x67, 0x68, 0x69, 0x6A, 0x6B):
            pos += 5
        elif op in (0x05, 0x07, 0x0C, 0x0D, 0x0E, 0x1A, 0x1B, 0x37, 0x3C, 0x3D, 0x5C, 0x5D, 0x5E):
            pos += 3
        elif op in (0x1E, 0x1F):
            pos += 2
        elif op in (0x16, 0x1C, 0x20, 0x62, 0x63):
            pos += 1
        elif op == 0x3B:
            end = res_data.find(b"\x00", pos + 1)
            if end < 0:
                break
            stack.append(("REAL", decode_fas_text(res_data[pos + 1 : end])))
            pos = end + 1
        else:
            pos += 1

    return tables[0], tables[1]


def build_function_catalog(resource_gvars: list, function_gvars: list) -> list:
    """从两个 GVar 表中收集所有 FUNC 条目。

    返回 [(name: str, bytecode_offset: int), ...] 按 offset 排序。
    """
    seen = set()
    catalog = []

    def extract_text(value):
        if isinstance(value, str):
            return value
        if isinstance(value, tuple) and len(value) == 2 and value[0] in ("STRING", "SYMBOL"):
            return str(value[1])
        return None

    def walk(value):
        if not isinstance(value, tuple):
            return
        if len(value) >= 4 and value[0] == "FUNC":
            raw_name = extract_text(value[1]) or ""
            start = value[2]
            if isinstance(start, int) and start not in seen:
                seen.add(start)
                catalog.append((str(raw_name), start))
            walk(value[3])
            return
        for item in value:
            walk(item)

    for table in (resource_gvars, function_gvars):
        for value in table:
            walk(value)

    catalog.sort(key=lambda item: item[1])
    return catalog


def resolve_symbol_name(sym_idx: int, str_list: list, sub_count: int) -> str | None:
    """将符号索引映射为名称（处理紧凑/完整编码）。"""
    if not str_list:
        return None
    effective_count = min(len(str_list), sub_count)
    if effective_count < sub_count:
        base = sub_count - effective_count
        adjusted = sym_idx - base
        if 0 <= adjusted < effective_count:
            return str_list[adjusted]
    elif 0 <= sym_idx < effective_count:
        return str_list[sym_idx]
    return None


def infer_code_ref_bias(function_gvars: list) -> int:
    """推断 function_gvars 开头空槽数（某些 FAS 有偏移）。"""
    bias = 0
    for value in function_gvars:
        if value is not None:
            break
        bias += 1
    return bias if 0 < bias <= 4 else 0


def extract_symbol_names(res_data: bytes) -> list:
    """从解密 seg1 中提取 [XXX 字符串（轻量，无需完整解析）。"""
    names = []
    i = 0
    while i < len(res_data):
        if res_data[i] == 0x5B:
            j = i + 1
            buf = bytearray()
            while j < len(res_data) and res_data[j] != 0:
                if res_data[j] >= 32:
                    buf.append(res_data[j])
                else:
                    break
                j += 1
            if buf and j > i + 1 and res_data[j] == 0:
                names.append(buf.decode("utf-8", errors="replace"))
                i = j
        i += 1
    return names


# ─── 函数桩提取（seg0） ──────────────────────────────────────────────────────


def extract_stubs(bytecode: bytes) -> list:
    """从 seg0 字节码中提取所有 DEFUN 桩。

    返回 [{
        'offset': int,
        'data': bytes,
        'sym_idx': int | None,
        'selector': int | None,
        'is_dispatch': bool,
    }, ...]
    """
    stubs = []
    pos = 0
    while True:
        m = bytecode.find(FUNC_DEF_OPCODE, pos)
        if m == -1:
            break
        next_m = bytecode.find(FUNC_DEF_OPCODE, m + 5)
        if next_m == -1:
            stub_data = bytecode[m:]
        else:
            stub_data = bytecode[m:next_m]

        # 提取符号索引: 09 XX XX 5C 00 00
        sym_idx = None
        for j in range(len(stub_data) - 5):
            if (
                stub_data[j] == 0x09
                and stub_data[j + 3] == 0x5C
                and stub_data[j + 4] == 0x00
                and stub_data[j + 5] == 0x00
            ):
                sym_idx = stub_data[j + 1] | (stub_data[j + 2] << 8)
                break

        is_dispatch = any(stub_data[j] == 0x32 for j in range(len(stub_data) - 1))

        selector = None
        if is_dispatch:
            for j in range(len(stub_data) - 1):
                if stub_data[j] == 0x32:
                    selector = stub_data[j + 1]
                    break

        stubs.append(
            {
                "offset": m,
                "data": stub_data,
                "sym_idx": sym_idx,
                "selector": selector,
                "is_dispatch": is_dispatch,
            }
        )
        pos = m + 5
    return stubs


# ─── FAS 构建 ──────────────────────────────────────────────────────────────────


def build_single_function_fas(
    magic: bytes, stub_data: bytes, seg1_data: bytes | None, seg1_sub_count: int, trailer: bytes | str
) -> bytes:
    """从桩构建单函数 FAS 文件。

    如果 seg1_data 为 None → 单段格式（自包含桩 trimmed）。
    否则 → 双段格式（含 seg1）。
    """
    if isinstance(trailer, str):
        trailer = trailer.encode("ascii")

    seg0_total = len(stub_data)
    seg0_header = f"{seg0_total}\r\n1 $".encode("ascii")

    out = bytearray()
    out.extend(magic)
    out.extend(seg0_header)
    out.extend(stub_data)

    if seg1_data is None:
        out.extend(b"\r\n")
        out.extend(trailer)
    else:
        out.extend(b"\x16\x24\r\n")
        seg1_header = f"{len(seg1_data)} {seg1_sub_count} $".encode("ascii")
        out.extend(seg1_header)
        out.extend(seg1_data)
        out.extend(b"\r\n")
        out.extend(trailer)

    return bytes(out)
