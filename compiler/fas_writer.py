import struct
from typing import List, Optional, Dict, Any
from compiler.symbol_table import SymbolTable


FAS4_MAGIC = b'\r\n FAS4-FILE ; Do not change it!\r\n'
SEG_TERMINATOR = b'\x19\x04\x00\x16\x24\r\n'


class FasWriter:
    def __init__(self, symtab: SymbolTable):
        self.symtab = symtab

    def write(self, filepath: str, seg0: bytes, seg1: bytes, sec2_items: int = 0):
        nsyms = self.symtab.nsyms

        seg0_header = f'{nsyms} $'.encode('ascii')
        seg0_payload = seg0_header + seg0
        total_size = len(seg0_payload)

        file_header = b'\r\n' + FAS4_MAGIC
        file_header += str(total_size).encode('ascii') + b'\r\n'

        seg1_header = f'{len(seg1)} {sec2_items} $'.encode('ascii')

        output = bytearray()
        output.extend(file_header)
        output.extend(seg0_payload)
        output.extend(SEG_TERMINATOR)
        output.extend(seg1_header)
        output.extend(seg1)
        output.extend(b'\r\n')

        with open(filepath, 'wb') as f:
            f.write(bytes(output))

        return filepath
