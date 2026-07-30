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
    return bytes([0x3B]) + s.encode('ascii') + b'\x00'


def res_gvar_init(var_pos: int, st_init: int) -> bytes:
    return bytes([0x43]) + res_u16(var_pos) + res_u16(st_init)


def res_func_triple() -> bytes:
    return bytes([0x3A])


class ResourceBuilder:
    def __init__(self, symtab: SymbolTable):
        self.symtab = symtab
        self.data = bytearray()

    def _push_single_symbol(self, name: str):
        self.data.append(0x5B)
        self.data.extend(name.encode('ascii', errors='replace'))
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

    def _push_string_block(self, s: str):
        encoded = s.encode('ascii', errors='replace')
        self.data.append(0x55)
        self.data.extend(res_u16(1))
        self.data.extend(res_u16(len(encoded)))
        self.data.extend(encoded)

    def build(self, func_offsets: Dict[str, int]) -> bytes:
        entries = self.symtab.entries

        for idx, (entry_type, entry_val) in enumerate(entries):
            if entry_type == 'STRING':
                self._push_string_block(entry_val)
            elif entry_type == 'INT':
                self._push_int(entry_val)
            elif entry_type == 'REAL':
                self.data.extend(res_real_str(f'{entry_val:g}'))
            elif entry_type == 'SYMBOL':
                self._push_single_symbol(entry_val)

        if entries:
            self._push_nil()
            self.data.extend(res_gvar_init(0, len(entries)))

        func_items = []
        for name, offset in func_offsets.items():
            func_items.append((name, offset))

        if func_items:
            for name, offset in func_items:
                self._push_nil()
                self._push_int(offset)
                self._push_single_symbol(name)
                self.data.extend(res_func_triple())

            self._push_t()
            func_var_pos = max(len(entries), 5)
            self.data.extend(res_gvar_init(func_var_pos, len(func_items)))

        return bytes(self.data)
