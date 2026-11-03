from __future__ import annotations

import datetime
import re
import time
from typing import List, Optional, Tuple

from compiler.symbol_table import SymbolTable


FAS4_MAGIC = b"\r\n FAS4-FILE ; Built by atlispcc!\r\n"
SEG_TERMINATOR = b"\x16\x24\r\n"

# 密钥固定尾巴：15 字节。前面是「盐」（Autodesk 官方 6~10 字节）。
CRUNCH_MARKER = b"\n;fas4 crunch\n;"

# Autodesk 官方盐长度 `6 + random&(5)` → 6..10（`make-fas4` 的 p-code：PUSH_INT8 6 /
# PUSH_INT8 5 / random& / + / random-string）。
AUTODESK_SALT_MIN = 6
AUTODESK_SALT_MAX = 10

# `--salt deterministic`：Autodesk 官方取值为 6..10，此处用区间内的固定来源盐，用于可复现构建。
DETERMINISTIC_SALT = bytes(range(1, 9))

_DATE_RE = re.compile(r"^A?(0?[1-9]|1[0-2])/(0?[1-9]|[12]\d|3[01])/(\d{2}|\d{4})$")


class AutodeskRandom:
    """Autodesk 官方 ``random&`` 的 ANSI-C LCG。

    ``state' = (1103515245 · state + 12345) mod 2^32``，输出
    ``(state' & 0xFFFF) mod n``（``0 .. n-1``）。Autodesk 官方用 ``time(NULL)`` 播种，
    所以两次构建的每个 crunched 字节都不同——没有 ``--salt`` 时本模块同样。
    """

    def __init__(self, seed: int):
        self._state = seed & 0xFFFFFFFF

    @property
    def state(self) -> int:
        return self._state

    def below(self, n: int) -> int:
        if n <= 0:
            return 0
        self._state = (self._state * 1103515245 + 12345) & 0xFFFFFFFF
        return (self._state & 0xFFFF) % n

    def random_string(self, length: int) -> bytes:
        """``random-string(n)``：字节域 ``1..255``（永不出现 0x00）、相邻不重复、
        输出顺序为抽取顺序的**逆序**。"""
        drawn: List[int] = []
        while len(drawn) < length:
            byte = 1 + self.below(255)
            while drawn and drawn[-1] == byte:
                byte = 1 + self.below(255)
            drawn.append(byte)
        drawn.reverse()
        return bytes(drawn)


def parse_salt_spec(spec: str) -> Tuple[Optional[bytes], Optional[int]]:
    """解析 ``--salt`` 取值，返回 ``(固定盐, LCG 种子)``，二者最多一个非 None。

    - ``deterministic`` → 固定盐 ``01 02 … 08``（可复现构建）
    - ``seed:<n>``（十进制/0x）→ 用该种子生成 Autodesk 官方形状的盐
    - ``hex:<hex>`` → 直接用这些字节（``hex:0102030405``）
    - 纯十进制/0x 整数 → 视为 LCG 种子
    """
    text = (spec or "").strip()
    if not text:
        return None, None
    lowered = text.lower()
    if lowered == "deterministic":
        return DETERMINISTIC_SALT, None
    if lowered.startswith("seed:"):
        return None, int(lowered[5:], 0)
    if lowered.startswith("hex:"):
        payload = lowered[4:]
        if not payload or len(payload) % 2 or not re.fullmatch(r"[0-9a-f]+", payload):
            raise ValueError(f"--salt hex: expects an even-length hex string (got {text!r})")
        return bytes.fromhex(payload), None
    return None, int(text, 0)


def normalize_date(date) -> str:
    """把日期标记规范化成 ``A<M>/<D>/<YY>``（无前导零）。

    接受 ``datetime.date``、``"7/31/26"``、``"07/31/26"``、``"A7/31/26"``。
    """
    if date is None or date == "":
        today = datetime.date.today()
        return f"A{today.month}/{today.day}/{today.year % 100}"
    if isinstance(date, datetime.date):
        return f"A{date.month}/{date.day}/{date.year % 100}"
    text = str(date).strip()
    match = _DATE_RE.match(text)
    if not match:
        raise ValueError(f"date must look like M/D/YY (got {text!r})")
    month, day, year = match.group(1), match.group(2), match.group(3)
    if len(year) == 4:
        year = year[-2:]
    return f"A{int(month)}/{int(day)}/{year}"


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


def build_trailer(
    seg1_plaintext: bytes,
    key_len: Optional[int] = None,
    salt: Optional[bytes] = None,
    seed: Optional[int] = None,
    date=None,
    salt_len: Optional[int] = None,
    return_ciphertext: bool = False,
) -> tuple:
    """构造 FAS4 尾部（密钥长度字节 + 密钥 + 日期标记）。

    返回 ``(trailer_bytes, key)``。密钥 = 盐 + 15 字节 ``;fas4 crunch`` 标记，
    前缀 1 字节记录密钥总长度。

    - ``salt`` 给定：直接使用（不做随机重抽，构建可复现）；
    - ``seed`` 给定：按其 LCG 生成，长度默认按官方规则抽 ``6 + random&(5)``；
    - 两者都未给定：用当前时间播种的 LCG 生成（与 Autodesk 官方一样每次不同）；
    - ``key_len`` 为密钥总长度（21~26）；给定时盐长 = ``key_len - 15``；
    - ``salt_len`` 显式指定盐长（6~10）；
    - ``date`` 为尾部日期标记，``None`` 取当天；
    - ``return_ciphertext=True`` 时额外返回本次校验用的密文，调用方可直接
      写盘，省掉再加密一遍（大 seg1 的加密是纯 Python 循环）。
    """
    if key_len is not None and not 21 <= key_len <= 26:
        raise ValueError(f"key_len must be in 21..26 (got {key_len})")
    if salt_len is None:
        salt_len = (key_len - len(CRUNCH_MARKER)) if key_len is not None else None
    if salt_len is not None and not AUTODESK_SALT_MIN <= salt_len <= AUTODESK_SALT_MAX:
        raise ValueError(f"salt len must be in {AUTODESK_SALT_MIN}..{AUTODESK_SALT_MAX} (got {salt_len})")
    if salt is not None and not salt:
        raise ValueError("salt must be non-empty")
    if salt is not None and not AUTODESK_SALT_MIN <= len(salt) <= AUTODESK_SALT_MAX:
        # 读取端按 6..10 回溯定位密钥；其它长度写出的产物无法被 find_key 识别。
        raise ValueError(
            f"salt must be {AUTODESK_SALT_MIN}..{AUTODESK_SALT_MAX} bytes "
            f"(got {len(salt)})"
        )

    stamp = normalize_date(date).encode("ascii")
    fixed = salt is not None
    rng = AutodeskRandom(int(time.time()) if seed is None else seed)

    for _ in range(64):
        if fixed:
            current = salt
        else:
            length = (
                salt_len
                if salt_len is not None
                else (AUTODESK_SALT_MIN + rng.below(AUTODESK_SALT_MAX - AUTODESK_SALT_MIN + 1))
            )
            current = rng.random_string(length)
        key = current + CRUNCH_MARKER  # type: ignore[operator]
        encrypted = _rolling_xor(seg1_plaintext, key)
        # 密文中出现标记会让读取端把数据误解为尾部；重抽（固定盐则报错）。
        if CRUNCH_MARKER in encrypted:
            if fixed:
                raise ValueError("salt makes the crunch marker appear in the payload")
            continue
        trailer = bytes([len(key)]) + key + b"$;" + stamp
        if _find_key_in_tail(trailer) == key:
            if return_ciphertext:
                return trailer, key, encrypted
            return trailer, key
        if fixed:
            break
    raise ValueError("could not build a FAS4 trailer for this payload")


def _find_key_in_tail(tail: bytes) -> bytes | None:
    """与 core.fas_core.find_key 相同逻辑的密钥定位（用于自检）。"""
    pos = tail.find(CRUNCH_MARKER)
    if pos < 0:
        return None
    for rlen in range(AUTODESK_SALT_MIN, AUTODESK_SALT_MAX + 2):
        key_start = pos - rlen
        key_end = pos + len(CRUNCH_MARKER)
        key_len = key_end - key_start
        lbp = key_start - 1
        if lbp >= 0 and tail[lbp] == key_len:
            return tail[key_start:key_end]
    return None


class FasWriter:
    def __init__(
        self,
        symtab: SymbolTable,
        date=None,
        salt=None,
        seed: Optional[int] = None,
        salt_len: Optional[int] = None,
    ):
        """``date``/``salt``/``seed`` 为容器尾部的可复现构建选项。

        ``salt`` 可为字节串或 ``--salt`` 形式的字符串（见 :func:`parse_salt_spec`）。
        """
        self.symtab = symtab
        self.date = date
        self.salt_len = salt_len
        if isinstance(salt, str):
            salt_bytes, salt_seed = parse_salt_spec(salt)
            self.salt = salt_bytes
            if salt_seed is not None and seed is None:
                seed = salt_seed
        else:
            self.salt = salt
        self.seed = seed

    def write(
        self,
        filepath: str,
        seg0: bytes,
        seg1: bytes,
        sec2_items: int = 0,
        encrypt: bool = True,
        key_len: int = 23,
        nsyms: int = -1,
        compact: bool = False,
        date=None,
        salt=None,
        seed: Optional[int] = None,
    ):
        if nsyms < 0:
            nsyms = len(self.symtab.entries)

        seg0_header = f"{nsyms} $".encode("ascii")
        seg0_payload = seg0_header + seg0
        if compact:
            total_size = len(seg0) + 1
        else:
            total_size = len(seg0_payload)

        file_header = FAS4_MAGIC
        file_header += str(total_size).encode("ascii") + b"\r\n"

        if encrypt and seg1:
            trailer, key, seg1_data = build_trailer(
                seg1,
                key_len=key_len,
                salt=self.salt if salt is None else salt,
                seed=self.seed if seed is None else seed,
                date=self.date if date is None else date,
                salt_len=self.salt_len,
                return_ciphertext=True,
            )
        else:
            seg1_data = seg1
            trailer = b""

        seg1_header = f"{len(seg1_data)} {sec2_items} $".encode("ascii")

        output = bytearray()
        output.extend(file_header)
        output.extend(seg0_payload)
        # 段终止符：seg0 非空时含 `16`（END_DEFUN 结束函数字节码），
        # seg0 空（纯顶层，无 defun）时以空格占位（CAD set5/setcmp 实测 ` $`）。
        seg_terminator = b" $\r\n" if not seg0 else SEG_TERMINATOR
        output.extend(seg_terminator)
        output.extend(seg1_header)
        output.extend(seg1_data)
        output.extend(trailer)

        with open(filepath, "wb") as f:
            f.write(bytes(output))

        return filepath
