import os
import sys
import tempfile

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from compiler.fas_writer import (
    CRUNCH_MARKER,
    DETERMINISTIC_SALT,
    AutodeskRandom,
    _find_key_in_tail,
    build_trailer,
    normalize_date,
    parse_salt_spec,
)


def test_autodesk_lcg_matches_ansi_c_recurrence():
    rng = AutodeskRandom(1)
    # 第一个状态：1 * 1103515245 + 12345 = 1103527590
    assert rng.below(1000) == (1103527590 & 0xFFFF) % 1000
    assert rng.state == 1103527590


def test_random_string_autodesk_shape():
    rng = AutodeskRandom(20261101)
    salt = rng.random_string(10)
    assert len(salt) == 10
    assert all(1 <= byte <= 255 for byte in salt)
    assert all(a != b for a, b in zip(salt, salt[1:]))
    # 同种子同输出
    assert AutodeskRandom(20261101).random_string(10) == salt


def test_random_string_is_reversed_draw_order():
    rng = AutodeskRandom(7)
    drawn = []
    while len(drawn) < 6:
        byte = 1 + rng.below(255)
        while drawn and drawn[-1] == byte:
            byte = 1 + rng.below(255)
        drawn.append(byte)
    assert AutodeskRandom(7).random_string(6) == bytes(reversed(drawn))


def test_parse_salt_spec():
    assert parse_salt_spec("") == (None, None)
    assert parse_salt_spec("deterministic") == (DETERMINISTIC_SALT, None)
    assert parse_salt_spec("seed:42") == (None, 42)
    assert parse_salt_spec("42") == (None, 42)
    assert parse_salt_spec("hex:0102030405") == (b"\x01\x02\x03\x04\x05", None)
    with pytest.raises(ValueError):
        parse_salt_spec("hex:012")


def test_normalize_date():
    assert normalize_date(None) == normalize_date(__import__("datetime").date.today())
    assert normalize_date("7/31/26") == "A7/31/26"
    assert normalize_date("07/31/2026") == "A7/31/26"
    assert normalize_date("A11/1/26") == "A11/1/26"
    with pytest.raises(ValueError):
        normalize_date("2026-11-01")


def test_build_trailer_layout_with_explicit_salt():
    payload = bytes(range(1, 64))
    salt = bytes([9, 8, 7, 6, 5, 4])
    trailer, key = build_trailer(payload, salt=salt, date="2/3/26")

    assert key == salt + CRUNCH_MARKER
    assert trailer[0] == len(key)
    assert trailer[1 : 1 + len(key)] == key
    assert trailer.endswith(b"$;A2/3/26")
    assert _find_key_in_tail(trailer) == key


def test_build_trailer_is_seed_reproducible():
    payload = b"some resource stream" * 8
    first = build_trailer(payload, seed=1234, date="2/3/26")
    second = build_trailer(payload, seed=1234, date="2/3/26")
    third = build_trailer(payload, seed=4321, date="2/3/26")
    assert first == second
    assert first != third
    # 盐长度按 Autodesk 官方规则 6..10
    assert 6 <= len(first[1]) - len(CRUNCH_MARKER) <= 10


def test_build_trailer_rejects_bad_key_len():
    with pytest.raises(ValueError):
        build_trailer(b"x", key_len=30)
    with pytest.raises(ValueError):
        build_trailer(b"x", salt=b"")


def test_find_key_reads_written_container():
    from core.fas_core import find_key

    payload = b"\x14\x01\x01\x01\x00" * 4
    trailer, key = build_trailer(payload, salt=DETERMINISTIC_SALT, date="2/3/26")
    blob = b"header" + payload + trailer
    assert find_key(blob) == key


def test_compile_is_reproducible_with_date_and_salt():
    from compiler.compile_cmd import cmd_compile

    workdir = tempfile.mkdtemp(prefix="atlispcc_salt_test_")
    first = os.path.join(workdir, "a.fas")
    second = os.path.join(workdir, "b.fas")
    try:
        cmd_compile("(defun demo (x) (+ x 1))", first, date="2/3/26", salt="deterministic")
        cmd_compile("(defun demo (x) (+ x 1))", second, date="2/3/26", salt="deterministic")
        with open(first, "rb") as handle:
            first_bytes = handle.read()
        with open(second, "rb") as handle:
            second_bytes = handle.read()
        assert first_bytes == second_bytes
        assert first_bytes.rstrip().endswith(b"$;A2/3/26")
    finally:
        for path in (first, second):
            if os.path.exists(path):
                os.unlink(path)
        os.rmdir(workdir)


def test_build_trailer_can_return_ciphertext():
    from compiler.fas_writer import _rolling_xor

    payload = b"seg1 payload" * 5
    trailer, key, ciphertext = build_trailer(
        payload, salt=DETERMINISTIC_SALT, date="2/3/26", return_ciphertext=True
    )
    plain, key2 = build_trailer(payload, salt=DETERMINISTIC_SALT, date="2/3/26")
    assert (trailer, key) == (plain, key2)
    assert ciphertext == _rolling_xor(payload, key)
    assert _rolling_xor(ciphertext, key) == payload


def test_assembler_accepts_date_and_salt(tmp_path):
    from compiler.cli import cmd_compile, cmd_disassemble
    from asm.assembler import assemble_lasm

    source = tmp_path / "src.lsp"
    source.write_text('(defun f (x) (+ x 1))', encoding="utf-8")
    fas = tmp_path / "src.fas"
    cmd_compile(str(source), str(fas))
    lasm = tmp_path / "src.lasm"
    cmd_disassemble(str(fas), str(lasm))

    text = lasm.read_text(encoding="utf-8")
    first = tmp_path / "a.fas"
    second = tmp_path / "b.fas"
    assemble_lasm(text, str(first), date="2/3/26", salt="deterministic")
    assemble_lasm(text, str(second), date="2/3/26", salt="deterministic")
    assert first.read_bytes() == second.read_bytes()
    assert first.read_bytes().rstrip().endswith(b"$;A2/3/26")


def test_build_trailer_rejects_salt_outside_vendor_range():
    with pytest.raises(ValueError):
        build_trailer(b"x", salt=b"abcde")       # 5 bytes
    with pytest.raises(ValueError):
        build_trailer(b"x", salt=b"0123456789A")  # 11 bytes
