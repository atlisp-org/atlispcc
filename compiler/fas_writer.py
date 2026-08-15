from __future__ import annotations

import struct
import os
import datetime
from typing import List, Optional, Dict, Any
from compiler.symbol_table import SymbolTable


FAS4_MAGIC = b'\r\n FAS4-FILE ; Built by atlispcc!\r\n'
SEG_TERMINATOR = b'\x16\x24\r\n'
CRUNCH_MARKER = b'\n;fas4 crunch\n;'


def _trailer_date() -> str:
    """日期标记，格式如 ``A7/31/26``（无前导零）。"""
    today = datetime.date.today()
    return f'A{today.month}/{today.day}/{today.year % 100}'


def _rolling_xor(data: bytes, key: bytes) -> bytes:
    """FAS4 双字节滚动 XOR（加密与解密使用同一函数，可逆）。"""
    result = bytearray(len(data))
    key_old = key[0]
    kp = 1
    for i in range(len(data)):
        if kp >= len(key):
            kp = 0
        key_new = key[kp]
        result[i] = data[i] ^ key_new ^ key_old
        key_old = key_new
        kp += 1
    return bytes(result)


def build_trailer(seg1_plaintext: bytes, key_len: int = 23) -> tuple:
    """构造 FAS4 尾部（密钥长度字节 + 密钥 + 日期标记）。

    返回 (trailer_bytes, key)，密钥以 ``\\n;fas4 crunch\\n;`` 结尾，
    前面 1 字节记录密钥长度。

    ``key_len`` 为密钥总长度（21~26 字节），其中含 15 字节的
    ``;fas4 crunch`` 标记，其余为随机前缀。默认 23 与 AutoCAD
    编译器产物（tests/cad/t01_math_cad.fas 等 t-series golden）一致。
    """
    if not 21 <= key_len <= 26:
        raise ValueError(f'key_len must be in 21..26 (got {key_len})')
    rlen = key_len - len(CRUNCH_MARKER)
    date = _trailer_date().encode('ascii')
    for _ in range(64):
        prefix = os.urandom(rlen)
        key = prefix + CRUNCH_MARKER
        encrypted = _rolling_xor(seg1_plaintext, key)
        if CRUNCH_MARKER in encrypted:
            continue
        trailer = bytes([len(key)]) + key + b'$;' + date
        if _find_key_in_tail(trailer) == key:
            return trailer, key
    prefix = os.urandom(rlen)
    key = prefix + CRUNCH_MARKER
    trailer = bytes([len(key)]) + key + b'$;' + date
    return trailer, key


def _find_key_in_tail(tail: bytes) -> bytes | None:
    """与 core.fas_core.find_key 相同逻辑的密钥定位（用于自检）。"""
    pos = tail.find(CRUNCH_MARKER)
    if pos < 0:
        return None
    for rlen in range(6, 12):
        key_start = pos - rlen
        key_end = pos + len(CRUNCH_MARKER)
        key_len = key_end - key_start
        lbp = key_start - 1
        if lbp >= 0 and tail[lbp] == key_len:
            return tail[key_start:key_end]
    return None


class FasWriter:
    def __init__(self, symtab: SymbolTable):
        self.symtab = symtab

    def write(self, filepath: str, seg0: bytes, seg1: bytes, sec2_items: int = 0,
              encrypt: bool = True, key_len: int = 23, nsyms: int = -1,
              compact: bool = False):
        if nsyms < 0:
            nsyms = len(self.symtab.entries)

        seg0_header = f'{nsyms} $'.encode('ascii')
        seg0_payload = seg0_header + seg0
        if compact:
            # CAD 紧凑 stub：total_size = len(seg0 字节码) + 1（f4/f4r/f5 实测）。
            # 注意不能写成 len(seg0_payload) - 2：seg0 头部为 `{nsyms} $`，
            # 其长度随 nsyms 位数变化（"6 $" 3 字节 / "12 $" 4 字节），
            # 两套写法仅在 nsyms < 10 时等价。
            total_size = len(seg0) + 1
        else:
            total_size = len(seg0_payload)

        file_header = FAS4_MAGIC
        file_header += str(total_size).encode('ascii') + b'\r\n'

        if encrypt and seg1:
            trailer, key = build_trailer(seg1, key_len=key_len)
            seg1_data = _rolling_xor(seg1, key)
        else:
            seg1_data = seg1
            trailer = b''

        seg1_header = f'{len(seg1_data)} {sec2_items} $'.encode('ascii')

        output = bytearray()
        output.extend(file_header)
        output.extend(seg0_payload)
        # 段终止符：seg0 非空时含 `16`（END_DEFUN 结束函数字节码），
        # seg0 空（纯顶层，无 defun）时以空格占位（CAD set5/setcmp 实测 ` $`）。
        seg_terminator = b' $\r\n' if not seg0 else SEG_TERMINATOR
        output.extend(seg_terminator)
        output.extend(seg1_header)
        output.extend(seg1_data)
        output.extend(trailer)

        with open(filepath, 'wb') as f:
            f.write(bytes(output))

        return filepath
