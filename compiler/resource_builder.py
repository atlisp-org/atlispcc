import struct
from typing import List, Dict, Any, Tuple, Optional
from compiler.symbol_table import SymbolTable


def res_u16(v: int) -> bytes:
    return struct.pack('<H', v)


def res_s32(v: int) -> bytes:
    return struct.pack('<i', v)


def res_int8(v: int) -> bytes:
    return bytes([0x32]) + struct.pack('<b', v)


def res_int32(v: int) -> bytes:
    return bytes([0x33]) + res_s32(v)


def res_real_str(s: str) -> bytes:
    return bytes([0x3B]) + s.encode('utf-8') + b'\x00'


def res_gvar_init(var_pos: int, st_init: int) -> bytes:
    return bytes([0x43]) + res_u16(var_pos) + res_u16(st_init)


def res_func_triple() -> bytes:
    return bytes([0x3A])


def build_module_code(n_funcs: int = 1) -> bytes:
    """生成 CAD 风格模块代码（seg1 尾部的模块入口）。

    单函数（n=1）为固定 24 字节结构。多函数版本已逆向出规律
    （每函数 ``PUSH_G <n+1-i> POP JUMP PUSH_G <2n+1-i> SETQ_G <n-i>``），
    但对反编译器的 INIT_DONE 解析有副作用，默认保持单函数结构。
    """
    if n_funcs <= 1:
        return bytes.fromhex(
            '14010000000902000a570000000009030006010009010016'
        )
    out = bytearray(b'\x14\x01\x00\x00\x00')
    for i in range(n_funcs):
        a = n_funcs + 1 - i
        b = 2 * n_funcs + 1 - i
        c = n_funcs - i
        out += b'\x09' + res_u16(a) + b'\x0a\x57\x00\x00\x00\x00'
        out += b'\x09' + res_u16(b) + b'\x06' + res_u16(c)
    out += b'\x09' + res_u16(1) + b'\x16'
    return bytes(out)


def count_resource_records(res_stream: bytes) -> int:
    """统计资源流中的 GVARINIT(0x43) 与 INIT_DONE(0x1c) 记录数。

    AutoCAD 的 seg1 头 ``<len> <items> $`` 中 items 即此计数。
    """
    count = 0
    pos = 0
    while pos < len(res_stream):
        op = res_stream[pos]
        if op == 0x43 and pos + 5 <= len(res_stream):
            count += 1
            pos += 5
        elif op == 0x1c:
            count += 1
            pos += 1
        else:
            pos += 1
    return count


class ResourceBuilder:
    def __init__(self, symtab: SymbolTable):
        self.symtab = symtab
        self.data = bytearray()

    def _push_single_symbol(self, name: str):
        self.data.append(0x5B)
        self.data.extend(name.encode('utf-8', errors='replace'))
        self.data.append(0)
        self.data.append(0)

    def _push_int(self, v: int):
        if -128 <= v <= 127:
            self.data.extend(res_int8(v))
        else:
            self.data.extend(res_int32(v))

    def _push_nil(self):
        self.data.append(0x01)

    def _push_t(self):
        self.data.append(0x02)

    def build(self, func_offsets: Dict[str, int], module_code: bytes = b'', seg0_payload_len: int = 0,
              stub_format: bool = False) -> bytes:
        """构建与 AutoCAD 编译器一致的 seg1 资源流。

        结构：
        - 模块头 + 模块代码引用 + 全部函数名符号 + GVARINIT + POP
        - 函数代码引用 + 其余符号/字符串 + GET_LOCAL + GVARINIT + POP
        - 每个函数一个 DEFCODE（GET_LOCAL + PUSH_INT8 <offset> + SYMBOL + DEFCODE）
        - GVARINIT + INIT_DONE
        - 模块代码
        """
        entries = self.symtab.entries
        if not entries:
            return bytes(self.data)

        out = bytearray()
        entry_count = len(entries)

        # ── 模块注册 ────────────────────────────────────────────────────
        out += b'\x14\x01\x01\x01\x00'
        out += self._code_ref_bytes(len(module_code))
        func_names_all = list(func_offsets.keys()) if func_offsets else [self._entry_name(entries[0])]
        if stub_format:
            # CAD 模块注册：所有函数名（源码逆序）+ PUSH_NIL + GVARINIT。
            fn_bytes = bytearray()
            for fname in reversed(func_names_all):
                fn_bytes += str(fname).encode('utf-8', errors='replace') + b'\x00'
            out += b'\x5b' + bytes(fn_bytes) + b'\x00'
            out += b'\x01' * 2
            out += res_gvar_init(0, len(func_names_all) + 2) + b'\x0a'
        else:
            self._push_entry(out, entries[0])
            out += b'\x01' * (entry_count - 1)
            out += res_gvar_init(0, entry_count) + b'\x0a'

        # ── 函数注册 ────────────────────────────────────────────────────
        if stub_format and func_offsets and len(func_offsets) > 1:
            out += self._func_ranges_bytes(func_offsets, seg0_payload_len or 0)
        else:
            ref_len = seg0_payload_len if seg0_payload_len else self._first_function_len(module_code)
            out += self._code_ref_bytes(ref_len)
        if stub_format:
            # CAD 符号格式: 连续 SYMBOL 合并为单个 5b 块，遇 STRING 分块。
            # 跳过模块已注册的函数名（entries 开头的 func_count 个）。
            skip_first = len(func_names_all)
            symbol_bytes = bytearray()
            for i, (entry_type, entry_val) in enumerate(entries[1:]):
                if i < skip_first - 1 and entry_type == 'SYMBOL':
                    continue
                if entry_type == 'SYMBOL':
                    symbol_bytes += str(entry_val).encode('utf-8', errors='replace') + b'\x00'
                elif entry_type == 'STRING':
                    if symbol_bytes:
                        out += b'\x5b' + bytes(symbol_bytes) + b'\x00'
                        symbol_bytes = bytearray()
                    self._push_entry(out, (entry_type, entry_val))
                else:
                    if symbol_bytes:
                        out += b'\x5b' + bytes(symbol_bytes) + b'\x00'
                        symbol_bytes = bytearray()
                    self._push_entry(out, (entry_type, entry_val))
            if symbol_bytes:
                out += b'\x5b' + bytes(symbol_bytes) + b'\x00'
        else:
            for entry_type, entry_val in entries[1:]:
                self._push_entry(out, (entry_type, entry_val))
        out += b'\x5c\x00\x00'
        if stub_format:
            # CAD: 函数注册 GVARINIT st_init = 注册符号数 + 1 = len(entries) - skip_first + 1。
            # 该 st_init 亦等于 nsyms。
            reg_count = len(entries) - skip_first + 1
            out += res_gvar_init(0, reg_count) + b'\x0a'
        else:
            out += res_gvar_init(0, entry_count) + b'\x0a'

        # ── 函数定义（每个函数一个 DEFCODE）──────────────────────────────
        # CAD 为每个函数生成: GET_LOCAL 0, PUSH_INT8 <seg0-offset>,
        # SYMBOL <name>, DEFCODE(3a), 01。stub 格式按源码逆序注册。
        func_names = list(func_offsets.keys()) if func_offsets else []
        if not func_names:
            name0 = self._entry_name(entries[0])
            func_names = [name0]
        if stub_format:
            func_names = list(reversed(func_names))
        for fi, fname in enumerate(func_names):
            off = func_offsets.get(fname, 0)
            if stub_format:
                if -128 <= off <= 127:
                    out += b'\x5c\x00\x00\x32' + bytes([off & 0xFF])
                else:
                    out += b'\x5c\x00\x00' + res_int32(off)
                out += b'\x5b' + str(fname).encode('utf-8', errors='replace') + b'\x00\x00'
                # CAD 只有最后一个 DEFCODE 追加 01（stub 格式）。
                out += b'\x3a\x01' if fi == len(func_names) - 1 else b'\x3a'
            else:
                if -128 <= off <= 127:
                    out += b'\x5c\x00\x00\x32' + bytes([off & 0xFF])
                else:
                    out += b'\x5c\x00\x00' + res_int32(off)
                out += b'\x5b' + str(fname).encode('utf-8', errors='replace') + b'\x00\x00'
                out += b'\x3a\x01'
        out += res_gvar_init(len(func_names) + 2 if stub_format else max(0, entry_count - 1),
                             len(func_names) if stub_format else len(func_names))
        out += b'\x1c'

        # ── 模块代码 ────────────────────────────────────────────────────
        out += module_code

        return bytes(out)

    @staticmethod
    def _push_entry(out: bytearray, entry: Tuple[str, Any]):
        entry_type, entry_val = entry
        if entry_type == 'SYMBOL':
            out += b'\x5b' + str(entry_val).encode('utf-8', errors='replace') + b'\x00\x00'
        elif entry_type == 'STRING':
            encoded = str(entry_val).encode('utf-8', errors='replace')
            out += b'\x55\x01\x00' + res_u16(len(encoded)) + encoded
        elif entry_type == 'INT':
            val = int(entry_val)
            out += res_int8(val) if -128 <= val <= 127 else res_int32(val)
        elif entry_type == 'REAL':
            out += res_real_str(f'{entry_val:g}')

    @staticmethod
    def _entry_name(entry: Tuple[str, Any]) -> str:
        return str(entry[1])

    @staticmethod
    def _code_ref_bytes(length: int) -> bytes:
        """``32 00 32 <len> 2a 39 01 00`` — CAD 代码引用字节（单函数）。"""
        if -128 <= length <= 127:
            return bytes([0x32, 0x00, 0x32, length & 0xFF, 0x2A, 0x39, 0x01, 0x00])
        return bytes([0x32, 0x00]) + res_int32(length) + bytes([0x2A]) + res_u16(1) + b'\x00'

    @staticmethod
    def _func_ranges_bytes(func_offsets: Dict[str, int], total_len: int) -> bytes:
        """多函数代码引用：每个函数的 (start, end) 范围，从末尾逆序。

        ``32 <start> 32 <end> 2a ... 39 <count> 00``。
        """
        offsets = sorted((v, k) for k, v in func_offsets.items())
        out = bytearray()
        ranges = []
        for i, (off, name) in enumerate(offsets):
            end = offsets[i + 1][0] if i + 1 < len(offsets) else total_len
            ranges.append((off, end))
        for start, end in reversed(ranges):
            out += bytes([0x32, start & 0xFF])
            out += bytes([0x32, end & 0xFF]) if end <= 127 else bytes([0x33]) + res_s32(end)
            out += b'\x2a'
        out += bytes([0x39]) + res_u16(len(ranges))
        return bytes(out)

    @staticmethod
    def _first_function_len(module_code: bytes) -> int:
        """模块代码中第一个函数（到首个 JUMP 指令为止）的长度。"""
        pos = 0
        while pos < len(module_code):
            if module_code[pos] == 0x57 and pos + 5 <= len(module_code):
                return pos + 5
            if module_code[pos] == 0x16:
                return pos + 1
            pos += 1
        return len(module_code)
