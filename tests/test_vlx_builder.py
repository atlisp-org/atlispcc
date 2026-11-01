import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from compiler.parser import Parser
from compiler.symbol_table import SymbolTable
from compiler.codegen import CodeGenerator, BytecodeBuffer
from compiler.ast_nodes import Defun
from compiler.resource_builder import ResourceBuilder
from compiler.fas_writer import FasWriter
from compiler.vlx_builder import (
    LOAD_NAME,
    TAG_DCL,
    TAG_FAS4,
    TAG_LOAD,
    TAG_TEXT,
    VLX_ALIGNMENT,
    VLX_MAGIC,
    VlxBuilder,
    VlxLoadSpec,
    VlxMember,
    build_vlx,
    make_load_stub,
    pack_vlx,
    parse_vlx,
    unpack_vlx,
    verify_vlx,
    _upcase_mbcs,
)

SOURCE = """
(defpackage vec (:export vec2))
(in-package vec)
(defun vec2 (x) (+ x 1))
"""


def _make_fas(path):
    parser = Parser(SOURCE)
    program = parser.parse()
    symtab = SymbolTable(package_table=parser.packages)
    symtab.collect_symbols(program)

    codegen = CodeGenerator(symtab)
    buf = BytecodeBuffer()
    for form in program.forms:
        if isinstance(form, Defun):
            offset = len(buf.data)
            bc, _ = codegen.generate_function(form)
            symtab.add_func_ref(form.name, offset)
            buf.emit(bc)

    seg0 = bytes(buf.data)
    resource = ResourceBuilder(symtab)
    seg1 = resource.build(symtab.function_offsets)
    FasWriter(symtab, date="2/3/26", salt="deterministic").write(path, seg0, seg1)


def _tmpdir():
    return tempfile.mkdtemp(prefix="atlispcc_vlx_test_")


def test_pack_parse_roundtrip():
    spec = VlxLoadSpec(entries=[("fas", "app.fas"), ("DCL", "dlg.dcl")])
    records = [
        VlxMember.load(spec.render()),
        VlxMember.fas4("app.fas", b"FASDATA"),
        VlxMember.dcl("dlg.dcl", b"dlg"),
        VlxMember.text("readme.txt", b"hello"),
    ]
    data = pack_vlx(records)

    assert data.startswith(VLX_MAGIC)
    assert data.endswith(b"\x00\x00\x00\x00" + VLX_MAGIC + b"\x00\x00\x00\x00")
    marker = int.from_bytes(data[8:12], "little")
    assert marker == len(data) - 16

    archive = parse_vlx(data)
    assert archive.marker == marker
    assert [r.tag for r in archive.records] == [TAG_LOAD, TAG_FAS4, TAG_DCL, TAG_TEXT]
    assert archive.load().name == LOAD_NAME
    assert b'(:load-file-list (:fas "app.fas") (:DCL "dlg.dcl"))' in archive.load_spec()

    # 名字大写化，payload 逐字节不变
    assert [m.name for m in archive.members()] == [b"APP.FAS", b"DLG.DCL", b"README.TXT"]
    assert [m.payload for m in archive.members()] == [b"FASDATA", b"dlg", b"hello"]

    # 每条记录 4 字节对齐（含记录 #0）
    assert all(offset % VLX_ALIGNMENT == 0 for offset in archive.member_offsets)


def test_record_layout_matches_measured_header():
    records = [VlxMember.load(b"(spec)"), VlxMember.fas4("a.fas", b"xy")]
    data = pack_vlx(records)

    # 记录 #0 的 u32 total, u16 tag, u8 name_len 紧接 12 字节头
    total, tag, name_len = int.from_bytes(data[12:16], "little"), int.from_bytes(data[16:18], "little"), data[18]
    assert (total, tag, name_len) == (7 + 4 + len(b"(spec)"), TAG_LOAD, 4)
    assert data[19:23] == b"LOAD"
    assert data[23 : 23 + len(b"(spec)")] == b"(spec)"
    # 记录 #0 对齐后的下一条记录起点
    second = (12 + total + 3) // 4 * 4
    assert int.from_bytes(data[second : second + 4], "little") == 7 + 5 + 2


def test_load_spec_option_spellings():
    assert (
        VlxLoadSpec(protected=False, active_x=True, separate_namespace=None).render()
        == b"((:protected) (:active-x . T) (:load-file-list))"
    )


def test_upcase_mbcs_keeps_dbcs_pairs():
    # 双字节字符（GBK 0xC4 0xE3）整体保留，ASCII 小写变大写
    assert _upcase_mbcs(b"\xc4\xe3abc") == b"\xc4\xe3ABC"


def test_build_vlx_from_fas():
    workdir = _tmpdir()
    fas_path = os.path.join(workdir, "app.fas")
    _make_fas(fas_path)
    vlx_path = os.path.join(workdir, "app.vlx")
    try:
        assert build_vlx([fas_path], vlx_path) == vlx_path
        with open(vlx_path, "rb") as f:
            data = f.read()
        archive = parse_vlx(data)
        assert archive.load().tag == TAG_LOAD
        assert archive.load().name == LOAD_NAME
        spec = archive.load_spec()
        assert b"(:protected . T)" in spec
        assert b'(:load-file-list (:fas "app.fas"))' in spec
        assert len(archive.members()) == 1
        member = archive.members()[0]
        assert member.name == b"APP.FAS"
        assert member.tag == TAG_FAS4
        with open(fas_path, "rb") as f:
            # 成员 payload 与独立 .fas 逐字节相同（容器不重新加密）
            assert member.payload == f.read()
    finally:
        for path in (fas_path, vlx_path):
            if os.path.exists(path):
                os.unlink(path)
        os.rmdir(workdir)


def test_build_vlx_with_exports_and_dcl():
    workdir = _tmpdir()
    fas_path = os.path.join(workdir, "app.fas")
    dcl_path = os.path.join(workdir, "Dlg.dcl")
    txt_path = os.path.join(workdir, "readme.txt")
    _make_fas(fas_path)
    with open(dcl_path, "wb") as f:
        f.write(b"// dialog")
    with open(txt_path, "wb") as f:
        f.write(b"notes")
    vlx_path = os.path.join(workdir, "app.vlx")
    try:
        build_vlx([fas_path, dcl_path, txt_path], vlx_path, exports=["vec2"])
        archive = parse_vlx(open(vlx_path, "rb").read())
        names = [m.name for m in archive.members()]
        tags = [m.tag for m in archive.members()]
        assert names == [b"APP.FAS", b"DLG.DCL", b"README.TXT", b"_VLX"]
        assert tags == [TAG_FAS4, TAG_DCL, TAG_TEXT, TAG_FAS4]
        spec = archive.load_spec()
        assert b'(:fas "app.fas")' in spec
        assert b'(:DCL "Dlg.dcl")' in spec
        assert b'(:fas "_VLX")' in spec
        # 导出桩是可加载的 FAS
        assert archive.members()[-1].payload.startswith(b"\r\n FAS4-FILE")
    finally:
        for path in (fas_path, dcl_path, txt_path, vlx_path):
            if os.path.exists(path):
                os.unlink(path)
        os.rmdir(workdir)


def test_unpack_vlx_writes_members():
    workdir = _tmpdir()
    vlx_path = os.path.join(workdir, "pack.vlx")
    outdir = os.path.join(workdir, "out")
    try:
        pack = pack_vlx(
            [
                VlxMember.load(VlxLoadSpec().render()),
                VlxMember.fas4("one.fas", b"ONE"),
                VlxMember.text("note.txt", b"TWO"),
            ]
        )
        with open(vlx_path, "wb") as f:
            f.write(pack)
        written = unpack_vlx(vlx_path, outdir)
        assert sorted(os.path.basename(p) for p in written) == ["NOTE.TXT", "ONE.FAS"]
        assert open(os.path.join(outdir, "ONE.FAS"), "rb").read() == b"ONE"
    finally:
        for name in os.listdir(outdir) if os.path.isdir(outdir) else []:
            os.unlink(os.path.join(outdir, name))
        if os.path.isdir(outdir):
            os.rmdir(outdir)
        os.unlink(vlx_path)
        os.rmdir(workdir)


def test_parse_rejects_bad_magic_and_marker():
    import pytest

    with pytest.raises(ValueError):
        parse_vlx(b"NOPE" + b"\x00" * 32)

    bad = bytearray(pack_vlx([VlxMember.load(VlxLoadSpec().render())]))
    bad[8:12] = (len(bad) - 20).to_bytes(4, "little")
    with pytest.raises(ValueError):
        parse_vlx(bytes(bad))


def test_builder_inserts_load_record_automatically():
    builder = VlxBuilder()
    builder.add_file("app.fas", b"FAS")
    builder.add_file("dlg.dcl", b"DCL")
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "auto.vlx")
        builder.build(path)
        archive = parse_vlx(open(path, "rb").read())
    assert archive.load().tag == TAG_LOAD
    assert b'(:load-file-list (:fas "app.fas") (:DCL "dlg.dcl"))' in archive.load_spec()


def test_verify_vlx_accepts_good_archive_and_flags_bad_tag():
    data = pack_vlx([
        VlxMember.load(VlxLoadSpec().render()),
        VlxMember.fas4("app.fas", b"FAS"),
    ])
    assert verify_vlx(parse_vlx(data)) == []

    bad = bytearray(data)
    bad[16:18] = (999).to_bytes(2, "little")  # 记录 #0 tag
    assert any("expected (1240" in issue for issue in verify_vlx(parse_vlx(bytes(bad))))


def test_verify_vlx_flags_empty_payload_and_duplicates():
    data = pack_vlx([
        VlxMember.load(VlxLoadSpec().render()),
        VlxMember.fas4("a.fas", b""),
        VlxMember.fas4("a.fas", b"X"),
    ])
    issues = verify_vlx(parse_vlx(data))
    assert any("empty payload" in issue for issue in issues)
    assert any("duplicate member name" in issue for issue in issues)


def test_make_load_stub_lists_fas_members_only():
    data = pack_vlx([
        VlxMember.load(VlxLoadSpec().render()),
        VlxMember.fas4("app.fas", b"FAS"),
        VlxMember.dcl("dlg.dcl", b"DCL"),
        VlxMember.text("readme.txt", b"TXT"),
    ])
    stub = make_load_stub(parse_vlx(data))
    assert '(load "APP.FAS")' in stub
    assert 'DLG.DCL' not in stub
    assert 'README.TXT' not in stub


def test_build_vlx_encodes_member_names_with_encoding(tmp_path):
    fas_path = tmp_path / "应用.fas"
    _make_fas(str(fas_path))
    vlx_path = tmp_path / "app.vlx"
    build_vlx([str(fas_path)], str(vlx_path), encoding="gbk")

    archive = parse_vlx(vlx_path.read_bytes())
    stored = archive.members()[0].name
    assert stored == "应用.FAS".encode("gbk")
    assert "应用.fas".encode("gbk") in archive.load_spec()


def test_unpack_vlx_rejects_path_separator_in_member_name(tmp_path):
    import pytest

    data = pack_vlx([
        VlxMember.load(VlxLoadSpec().render()),
        VlxMember(VlxMember.fas4("x", b"X").name.replace(b"x", b".."), TAG_FAS4, b"X"),
    ])
    vlx = tmp_path / "bad.vlx"
    vlx.write_bytes(data)
    with pytest.raises(ValueError):
        unpack_vlx(str(vlx), str(tmp_path / "out"))


def test_build_vlx_export_stub_honours_date_and_salt(tmp_path):
    fas_path = tmp_path / "app.fas"
    _make_fas(str(fas_path))
    first = tmp_path / "a.vlx"
    second = tmp_path / "b.vlx"
    build_vlx([str(fas_path)], str(first), exports=["vec2"], date="2/3/26", salt="deterministic")
    build_vlx([str(fas_path)], str(second), exports=["vec2"], date="2/3/26", salt="deterministic")

    assert first.read_bytes() == second.read_bytes()
    archive = parse_vlx(first.read_bytes())
    stub = [member for member in archive.members() if member.name == b"_VLX"][0]
    assert stub.payload.rstrip().endswith(b"$;A2/3/26")


def test_build_vlx_rejects_duplicate_member_names(tmp_path):
    import pytest

    first = tmp_path / "a"
    second = tmp_path / "b"
    first.mkdir()
    second.mkdir()
    _make_fas(str(first / "same.fas"))
    _make_fas(str(second / "same.fas"))
    with pytest.raises(ValueError, match="duplicate VLX member name"):
        build_vlx([str(first / "same.fas"), str(second / "same.fas")], str(tmp_path / "x.vlx"))
