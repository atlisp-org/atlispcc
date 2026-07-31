"""VLX Container Builder — package FAS files into a .vlx archive.

Format (reverse-engineered, experimental):
  Header:      12 bytes  magic b"VXL_FIRM\\0\\0\\0\\0"
  EntryCount:   4 bytes  LE uint32
  Directory:    N × variable-length entry records
    name_len:   4 bytes  LE uint32
    name:       name_len bytes (padded to 4)
    offset:     4 bytes  LE uint32 — from data block start
    size:       4 bytes  LE uint32
  DataBlock:    concatenated file contents

  A special _VLX entry holds AutoLISP code evaluated at load time.
  For separate-namespace VLXs it calls vl-doc-export and loads FAS files.
"""

import os
import struct
from typing import List, Optional, Tuple

_VLX_MAGIC = b'VXL_FIRM\x00\x00\x00\x00'
_VLX_ENTRY = b'_VLX'


def _pad4(data: bytes) -> bytes:
    """Pad data to 4-byte boundary."""
    rem = len(data) % 4
    if rem:
        return data + b'\x00' * (4 - rem)
    return data


def _make_vlx_code(exports: List[str], fas_files: List[str]) -> bytes:
    """Generate the _VLX AutoLISP code for namespace setup."""
    lines = []
    for name in exports:
        lines.append(f"(vl-doc-export '{name})")
    for fname in fas_files:
        base = os.path.splitext(os.path.basename(fname))[0]
        lines.append(f'(load "{base}")')
    code = '\n'.join(lines)
    return code.encode('utf-8')


class VlxBuilder:
    def __init__(self):
        self.entries: List[Tuple[str, bytes]] = []

    def add_file(self, name: str, data: bytes):
        self.entries.append((name, data))

    def build(self, output_path: str):
        dir_offset = 12 + 4  # magic + entry_count
        entry_offsets: List[int] = []
        dir_data = bytearray()
        data_block = bytearray()

        for fname, fdata in self.entries:
            entry_offsets.append(len(data_block))
            data_block.extend(fdata)

        entry_count = len(self.entries)
        dir_data.extend(struct.pack('<I', entry_count))

        for i, (fname, fdata) in enumerate(self.entries):
            name_bytes = fname.encode('utf-8')
            dir_data.extend(struct.pack('<I', len(name_bytes)))
            dir_data.extend(name_bytes)
            dir_data.extend(b'\x00' * ((4 - len(name_bytes) % 4) % 4))
            dir_data.extend(struct.pack('<II', entry_offsets[i], len(fdata)))

        with open(output_path, 'wb') as f:
            f.write(_VLX_MAGIC)
            f.write(dir_data)
            f.write(bytes(data_block))


def build_vlx(fas_paths: List[str], output_path: str,
              exports: Optional[List[str]] = None,
              package_name: str = '') -> str:
    builder = VlxBuilder()

    vlx_code = _make_vlx_code(exports or [], fas_paths)
    builder.add_file('_VLX', vlx_code)

    for path in fas_paths:
        base = os.path.basename(path)
        with open(path, 'rb') as f:
            builder.add_file(base, f.read())

    builder.build(output_path)
    return output_path
