"""VLX 容器（VRTLIB-1）打包与解包。

容器布局（与 AutoCAD `PRV`/`KLB` 产出的官方归档逐字节一致）::

    "VRTLIB-1"                                8 字节 magic（文件头、文件尾各一处）
    u32 LE  尾部标记偏移                       = 文件长度 - 16
    记录 #0（4 字节对齐）                      LOAD 描述符
        u32 LE  total_len = 7 + len(name) + len(payload)
        u16 LE  tag       1240
        u8      name_len  4
        bytes   "LOAD"
        bytes   LOAD 规格文本（prin1-to-string 形式）
    记录 #1..#n（各自 4 字节对齐）             一个成员一条
        u32 LE  total_len = 7 + name_len + payload_len
        u16 LE  tag       1330 = :fas, 1350 = :DCL, 1335 = :txt, 1340 = :dvb
        u8      name_len
        bytes   NAME   (大写化的 basename，DBCS 按双字节整体保留)
        bytes   payload（与独立产物逐字节相同）
    00 00 00 00 "VRTLIB-1" 00 00 00 00         16 字节文件尾

magic 与首条记录之间没有其它头部结构：``u32@8`` 是文件尾偏移，
``u32@12 / u16@16 / u8@18`` 已经是记录 #0 自己的 ``total_len / tag / name_len``。

旧版 atlispcc 写的是自定义 ``VXL_FIRM`` 容器（CAD 无法加载）；本模块按实测
格式重写，pack 与 parse 互逆。
"""

import os
import struct
import tempfile
from dataclasses import dataclass, field
from typing import List, Optional, Sequence, Tuple

VLX_MAGIC = b"VRTLIB-1"
VLX_ALIGNMENT = 4

TAG_LOAD = 1240
TAG_FAS4 = 1330
TAG_TEXT = 1335
TAG_DVB = 1340
TAG_DCL = 1350

LOAD_NAME = b"LOAD"

# 扩展名 → 记录 tag。未列出的扩展名按纯文本成员打包（不进 LOAD 清单）。
_EXT_TAGS = {
    ".fas": TAG_FAS4,
    ".dcl": TAG_DCL,
    ".txt": TAG_TEXT,
    ".dvb": TAG_DVB,
}

# 记录 tag → LOAD 清单里的键（`ll-resource-key->type` 表）。
_TAG_LOAD_KEYS = {
    TAG_FAS4: "fas",
    TAG_DCL: "DCL",
}


def _is_lead_byte(byte: int) -> bool:
    """CP936 双字节首字节（`_ismbblead` 的 0x81..0xFE 区间）。"""
    return 0x81 <= byte <= 0xFE


def _upcase_mbcs(name: bytes) -> bytes:
    """`nstring-upcase` 的字节级实现：ASCII a-z 转大写，DBCS 首字节与尾字节整体保留。"""
    out = bytearray()
    index = 0
    while index < len(name):
        byte = name[index]
        if _is_lead_byte(byte) and index + 1 < len(name):
            out += name[index : index + 2]
            index += 2
        else:
            out.append(ord(chr(byte).upper()) if 0x61 <= byte <= 0x7A else byte)
            index += 1
    return bytes(out)


def _resolve_encoding(encoding: str = "ansi") -> str:
    """`'ansi'`/空 → 系统 ACP（Windows 中文系统为 gbk）。"""
    from core.fas_core import get_ansi_encoding

    if not encoding or encoding.lower() in ("ansi", "auto", "system"):
        return get_ansi_encoding()
    return encoding


def _encode_text(text: str, encoding: str) -> bytes:
    """编码容器内文本（LOAD 规格 / 成员名），不可编码字符以 ``\\U+XXXX`` 转义。"""
    enc = _resolve_encoding(encoding)
    try:
        return text.encode(enc)
    except UnicodeEncodeError:
        escaped = "".join(ch if ord(ch) < 0x80 else "\\U+%04X" % ord(ch) for ch in text)
        return escaped.encode(enc, errors="replace")


def decode_text(data: bytes, encoding: str = "ansi") -> str:
    """解码容器内文本：优先指定编码，失败退回 GBK / latin-1（不抛异常）。"""
    for candidate in (_resolve_encoding(encoding), "gbk", "latin-1"):
        try:
            return data.decode(candidate)
        except (LookupError, UnicodeDecodeError):
            continue
    return data.decode("latin-1")


def encode_name(name, encoding: str = "ansi") -> bytes:
    """成员名按容器编码（默认系统 ACP）编码；不可编码字符走 ``\\U+XXXX`` 转义。"""
    if isinstance(name, bytes):
        return name
    return _encode_text(name, encoding)


def _align4(length: int) -> int:
    return (length + VLX_ALIGNMENT - 1) // VLX_ALIGNMENT * VLX_ALIGNMENT


def tag_for_path(path: str) -> int:
    """按扩展名取记录 tag；未知扩展名按纯文本成员（1335）。"""
    return _EXT_TAGS.get(os.path.splitext(path)[1].lower(), TAG_TEXT)


@dataclass
class VlxMember:
    """容器中的一条成员记录（tag, name, payload 三元组）。"""

    name: bytes
    tag: int
    payload: bytes

    @classmethod
    def fas4(cls, name, payload: bytes) -> "VlxMember":
        return cls(_as_bytes(name), TAG_FAS4, payload)

    @classmethod
    def dcl(cls, name, payload: bytes) -> "VlxMember":
        return cls(_as_bytes(name), TAG_DCL, payload)

    @classmethod
    def text(cls, name, payload: bytes) -> "VlxMember":
        return cls(_as_bytes(name), TAG_TEXT, payload)

    @classmethod
    def load(cls, spec: bytes) -> "VlxMember":
        """记录 #0：``(1240 "LOAD" <spec>)``。"""
        return cls(LOAD_NAME, TAG_LOAD, spec)

    def stored_name(self) -> bytes:
        """写入容器的名字：``nstring-upcase (filename-base path)``。"""
        return _upcase_mbcs(self.name)

    def record_len(self) -> int:
        return 7 + len(self.name) + len(self.payload)

    def load_key(self) -> Optional[str]:
        """该成员在 LOAD 清单中的键；纯文本/未加载成员返回 ``None``。"""
        return _TAG_LOAD_KEYS.get(self.tag)

    def display_name(self, encoding: str = "ansi") -> str:
        return decode_text(self.name, encoding)


def _as_bytes(name) -> bytes:
    if isinstance(name, bytes):
        return name
    return os.fsencode(name)


@dataclass
class VlxLoadSpec:
    """记录 #0 的 LOAD 规格：``prv-make`` 无条件写出的四项列表。

    ``None`` 表示整项省略；``False`` 输出裸键 ``(:separate-namespace)``；
    ``True`` 输出点对 ``(:separate-namespace . T)``。
    """

    protected: Optional[bool] = True
    active_x: Optional[bool] = True
    separate_namespace: Optional[bool] = True
    entries: List[Tuple[str, str]] = field(default_factory=list)

    def with_fas(self, name: str) -> "VlxLoadSpec":
        self.entries.append(("fas", name))
        return self

    def with_dcl(self, name: str) -> "VlxLoadSpec":
        self.entries.append(("DCL", name))
        return self

    def render(self, encoding: str = "ansi") -> bytes:
        options: List[str] = []

        def push(key: str, value: Optional[bool]) -> None:
            if value is True:
                options.append(f"({key} . T)")
            elif value is False:
                options.append(f"({key})")

        push(":protected", self.protected)
        push(":active-x", self.active_x)
        push(":separate-namespace", self.separate_namespace)
        if self.entries:
            members = " ".join(f'(:{key} "{name}")' for key, name in self.entries)
            options.append(f"(:load-file-list {members})")
        else:
            options.append("(:load-file-list)")
        return _encode_text("(" + " ".join(options) + ")", encoding)


def pack_vlx(records: Sequence[VlxMember]) -> bytes:
    """把记录表（含记录 #0）打包为 VRTLIB-1 字节流。"""
    names: List[bytes] = []
    for index, record in enumerate(records):
        name = record.stored_name()
        if not name:
            raise ValueError(f"VLX member #{index} has an empty name")
        if len(name) > 0xFF:
            raise ValueError(f"VLX member #{index} name is {len(name)} bytes (max 255)")
        if record.record_len() > 0xFFFFFFFF:
            raise ValueError(f"VLX member #{index} payload is too large")
        names.append(name)

    out = bytearray()
    out += VLX_MAGIC
    out += b"\x00" * 4  # marker，写入文件尾后回填
    for record, name in zip(records, names):
        out += struct.pack("<IHB", record.record_len(), record.tag, len(name))
        out += name
        out += record.payload
        out += b"\x00" * (_align4(len(out)) - len(out))
    out += b"\x00" * 4
    out += VLX_MAGIC
    out += b"\x00" * 4
    out[8:12] = struct.pack("<I", len(out) - 16)
    return bytes(out)


@dataclass
class VlxArchive:
    """解析后的 VRTLIB-1 归档。"""

    records: List[VlxMember]
    member_offsets: List[int]
    marker: int

    def load(self) -> Optional[VlxMember]:
        return self.records[0] if self.records else None

    def load_spec(self) -> bytes:
        record = self.load()
        return record.payload if record else b""

    def members(self) -> List[VlxMember]:
        return self.records[1:]


def parse_vlx(data: bytes) -> VlxArchive:
    """解析 VRTLIB-1 归档（``pack_vlx`` 的逆操作）。"""
    if not data.startswith(VLX_MAGIC):
        raise ValueError("not a VRTLIB-1 archive (magic missing)")
    if len(data) < 12:
        raise ValueError("truncated VRTLIB-1 header")
    marker = struct.unpack("<I", data[8:12])[0]
    if marker > len(data) or len(data) - marker != 16:
        raise ValueError(
            f"VRTLIB-1 trailing marker must sit 16 bytes before EOF " f"(marker={marker}, size={len(data)})"
        )

    records: List[VlxMember] = []
    offsets: List[int] = []
    cursor = 12
    while cursor + 7 <= marker:
        offset = cursor
        total_len, tag, name_len = struct.unpack("<IHB", data[cursor : cursor + 7])
        cursor += 7
        if total_len < 7 + name_len:
            raise ValueError(f"record @{offset}: total_len {total_len} < own header")
        if cursor + name_len + (total_len - 7 - name_len) > marker:
            raise ValueError(f"record @{offset}: payload runs past the footer")
        name = data[cursor : cursor + name_len]
        cursor += name_len
        payload_len = total_len - 7 - name_len
        payload = data[cursor : cursor + payload_len]
        cursor += payload_len
        offsets.append(offset)
        records.append(VlxMember(bytes(name), tag, bytes(payload)))
        cursor = _align4(cursor)

    return VlxArchive(records=records, member_offsets=offsets, marker=marker)


def verify_vlx(archive: VlxArchive) -> List[str]:
    """结构校验：LOAD 记录、成员对齐、重名、空归档等。

    返回问题列表（空 = 通过）。用于 ``unpack-vlx --verify`` 与测试。
    """
    issues: List[str] = []
    if not archive.records:
        return ["archive has no records"]
    load = archive.records[0]
    if load.tag != TAG_LOAD or load.name != LOAD_NAME:
        issues.append(
            f"record #0 is tag={load.tag} name={load.name!r}, expected (1240, 'LOAD')"
        )
    if not archive.members():
        issues.append("archive has no members")
    seen = set()
    for index, record in enumerate(archive.members(), start=1):
        if record.tag not in (TAG_FAS4, TAG_DCL, TAG_TEXT, TAG_DVB):
            issues.append(f"record #{index} has unknown tag {record.tag}")
        name = record.stored_name()
        if name in seen:
            issues.append(f"duplicate member name {name!r}")
        seen.add(name)
        if not record.payload:
            issues.append(f"record #{index} ({name!r}) has an empty payload")
    for index, offset in enumerate(archive.member_offsets):
        if offset % VLX_ALIGNMENT:
            issues.append(f"record #{index} offset {offset} is not {VLX_ALIGNMENT}-byte aligned")
    return issues


def make_load_stub(archive: VlxArchive, encoding: str = "ansi") -> str:
    """生成加载桩：按记录顺序 ``(load "NAME")`` 各 FAS 成员。"""
    lines = [";; generated by atlispcc unpack-vlx"]
    for record in archive.members():
        if record.tag == TAG_FAS4:
            lines.append(f'(load "{record.display_name(encoding)}")')
    return "\n".join(lines) + "\n"


def read_vlx(path: str) -> VlxArchive:
    with open(path, "rb") as handle:
        return parse_vlx(handle.read())


def unpack_vlx(path: str, outdir: str, encoding: str = "ansi") -> List[str]:
    """把归档成员解包到 ``outdir``，返回写出的文件路径（记录 #0 不写出）。

    重名时追加 ``.1``、``.2``… 后缀，避免静默覆盖。
    """
    archive = read_vlx(path)
    os.makedirs(outdir, exist_ok=True)
    written: List[str] = []
    used = set()
    for record in archive.members():
        base = record.display_name(encoding)
        if (
            os.sep in base
            or (os.altsep and os.altsep in base)
            or base in (".", "..")
            or "\x00" in base
            or os.path.basename(base) != base
        ):
            raise ValueError(f"VLX member name {base!r} is not a safe file name")
        candidate = base
        serial = 1
        while candidate in used:
            candidate = f"{base}.{serial}"
            serial += 1
        used.add(candidate)
        target = os.path.join(outdir, candidate)
        with open(target, "wb") as handle:
            handle.write(record.payload)
        written.append(target)
    return written


def _make_export_code(exports: Sequence[str]) -> bytes:
    """生成导出桩源码：``(vl-doc-export 'name)`` 逐行。

    容器本身不承载命名空间导出，导出必须由 FAS 代码在加载时调用
    ``vl-doc-export``；因此 ``--export`` 会额外编译一个 ``_VLX`` 成员并排进
    LOAD 清单末尾。
    """
    lines = [f"(vl-doc-export '{name})" for name in exports]
    return ("\n".join(lines) + "\n").encode("utf-8")


def _compile_fas_bytes(source: str, encoding: str = "ansi", date=None, salt=None) -> bytes:
    """用 CLI 编译管线把 AutoLISP 源码编译为 FAS 字节（内存返回）。"""
    import contextlib
    import io

    from compiler.compile_cmd import cmd_compile

    workdir = tempfile.mkdtemp(prefix="atlispcc_vlx_")
    target = os.path.join(workdir, "_vlx.fas")
    out_buf, err_buf = io.StringIO(), io.StringIO()
    try:
        with contextlib.redirect_stdout(out_buf), contextlib.redirect_stderr(err_buf):
            cmd_compile(source, target, encoding=encoding, date=date, salt=salt)
        if not os.path.isfile(target):
            raise RuntimeError(
                "VLX export stub failed to compile: "
                + (err_buf.getvalue() or out_buf.getvalue()).strip()[-2000:]
            )
        with open(target, "rb") as handle:
            return handle.read()
    except SystemExit as exc:
        raise RuntimeError(
            f"VLX export stub failed to compile (exit {exc.code}): "
            + (err_buf.getvalue() or out_buf.getvalue()).strip()[-2000:]
        ) from None
    finally:
        for name in os.listdir(workdir):
            try:
                os.unlink(os.path.join(workdir, name))
            except OSError:
                pass
        try:
            os.rmdir(workdir)
        except OSError:
            pass


def build_vlx(
    inputs: Sequence[str],
    output_path: str,
    exports: Optional[Sequence[str]] = None,
    protected: Optional[bool] = True,
    active_x: Optional[bool] = True,
    separate_namespace: Optional[bool] = True,
    encoding: str = "ansi",
    date=None,
    salt=None,
) -> str:
    """把 FAS/DCL/文本成员打包成 VRTLIB-1 的 ``.vlx``。

    - ``.fas`` → tag 1330，进 LOAD 清单 ``(:fas "…")``
    - ``.dcl`` → tag 1350，进 LOAD 清单 ``(:DCL "…")``
    - 其它扩展名 → tag 1335（``:txt``），只作为随包资源，不进 LOAD 清单
    - ``exports`` 非空时额外编译 ``_VLX`` 导出桩成员（``date``/``salt`` 透传给该次编译）
    """
    spec = VlxLoadSpec(
        protected=protected,
        active_x=active_x,
        separate_namespace=separate_namespace,
    )
    records: List[VlxMember] = []
    for path in inputs:
        if not os.path.exists(path):
            raise FileNotFoundError(path)
        with open(path, "rb") as handle:
            payload = handle.read()
        name = os.path.basename(path)
        tag = tag_for_path(path)
        record = VlxMember(encode_name(name, encoding), tag, payload)
        records.append(record)
        key = record.load_key()
        if key:
            spec.entries.append((key, name))

    if exports:
        stub_name = "_VLX"
        stub = _compile_fas_bytes(
            _make_export_code(exports).decode("utf-8"),
            encoding=encoding,
            date=date,
            salt=salt,
        )
        records.append(VlxMember.fas4(stub_name, stub))
        spec.entries.append(("fas", stub_name))

    seen_names = set()
    for record in records:
        stored = record.stored_name()
        if stored in seen_names:
            raise ValueError(f"duplicate VLX member name {stored.decode('latin-1')!r}")
        seen_names.add(stored)

    table = [VlxMember.load(spec.render(encoding))] + records
    data = pack_vlx(table)
    with open(output_path, "wb") as handle:
        handle.write(data)
    return output_path


class VlxBuilder:
    """增量式打包器（``add_file`` 累积记录，``build`` 落盘）。

    ``build`` 在首位不是 LOAD 记录时自动补一条（LOAD 规格按已有 `.fas`/`.DCL`
    成员生成），避免产出 CAD 不会加载的归档。
    """

    def __init__(self, encoding: str = "ansi"):
        self.entries: List[VlxMember] = []
        self.encoding = encoding

    def add_file(self, name: str, data: bytes, tag: Optional[int] = None):
        self.entries.append(
            VlxMember(
                encode_name(name, self.encoding),
                tag if tag is not None else tag_for_path(name),
                data,
            )
        )

    def add_member(self, member: VlxMember) -> None:
        self.entries.append(member)

    def build(self, output_path: str) -> str:
        records = list(self.entries)
        if not records or records[0].tag != TAG_LOAD:
            spec = VlxLoadSpec()
            for record in records:
                key = record.load_key()
                if key:
                    spec.entries.append((key, record.display_name(self.encoding)))
            records.insert(0, VlxMember.load(spec.render(self.encoding)))
        with open(output_path, "wb") as handle:
            handle.write(pack_vlx(records))
        return output_path
