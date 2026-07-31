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


def build_module_code() -> bytes:
    """生成 CAD 风格模块代码（seg1 尾部的模块入口）。

    与 AutoCAD 编译器对 ``(defun name () ...)`` 类文件产生的模块代码一致：
    模块入口 DEFUN + 函数注册/求值代码 + END_DEFUN。
    """
    return bytes.fromhex(
        '14010000000902000a570000000009030006010009010016'
    )


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

    def build(self, func_offsets: Dict[str, int], module_code: bytes = b'') -> bytes:
        """构建与 AutoCAD 编译器一致的 seg1 资源流。

        结构：
        - 模块头 + 模块代码引用 + 首符号 + GVARINIT + POP
        - 函数代码引用 + 其余符号/字符串 + GET_LOCAL + GVARINIT + POP
        - 函数定义（DEFCODE）+ GVARINIT + INIT_DONE
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
        self._push_entry(out, entries[0])
        out += b'\x01' * (entry_count - 1)
        out += res_gvar_init(0, entry_count) + b'\x0a'

        # ── 函数注册 ────────────────────────────────────────────────────
        first_func_len = self._first_function_len(module_code)
        out += self._code_ref_bytes(first_func_len)
        for entry_type, entry_val in entries[1:]:
            self._push_entry(out, (entry_type, entry_val))
        out += b'\x5c\x00\x00'
        out += res_gvar_init(0, entry_count) + b'\x0a'

        # ── 函数定义 ────────────────────────────────────────────────────
        name0 = self._entry_name(entries[0])
        out += b'\x5c\x00\x00\x32\x00\x5b' + name0.encode('utf-8', errors='replace') + b'\x00\x00'
        out += b'\x3a\x01'
        out += res_gvar_init(entry_count, 1)
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
        """``32 00 32 <len> 2a 39 01 00`` — CAD 代码引用字节。"""
        if -128 <= length <= 127:
            return bytes([0x32, 0x00, 0x32, length & 0xFF, 0x2A, 0x39, 0x01, 0x00])
        return bytes([0x32, 0x00]) + res_int32(length) + bytes([0x2A]) + res_u16(1) + b'\x00'

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
