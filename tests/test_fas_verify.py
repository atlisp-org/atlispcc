import os
import sys
import struct

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

from compiler.fas_verify import verify_fas
from asm.opcodes import OPCODES
from core.fas_core import parse_fas4

TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.dirname(TESTS_DIR)


def _opcode(name):
    for op, (n, _f) in OPCODES.items():
        if n == name:
            return op
    raise KeyError(name)


def test_verify_ok_on_compiler_output():
    """正常编译产物应通过验证（无致命问题）。"""
    from compiler.cli import cmd_compile
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        out = os.path.join(tmp, "o.fas")
        cmd_compile(os.path.join(TESTS_DIR, "fun.lsp"), out)
        r = parse_fas4(out, decrypt_seg1=True)
        ok, issues = verify_fas(r["bytecode"], r["res_data_decrypted"], r["nsyms"], label="o")
        fatal = [i for i in issues if not i.startswith("WARN ")]
        assert ok, fatal


def test_verify_ok_on_mixed_file():
    """混合文件（defun + 顶层）同样通过验证。"""
    from compiler.cli import cmd_compile
    import tempfile

    mixed = os.path.join(TESTS_DIR, "setq-lambda.lsp")
    if not os.path.exists(mixed):
        pytest.skip("tests/setq-lambda.lsp not present")
    with tempfile.TemporaryDirectory() as tmp:
        out = os.path.join(tmp, "o.fas")
        cmd_compile(mixed, out)
        r = parse_fas4(out, decrypt_seg1=True)
        ok, issues = verify_fas(r["bytecode"], r["res_data_decrypted"], r["nsyms"], label="o")
        fatal = [i for i in issues if not i.startswith("WARN ")]
        assert ok, fatal


def test_verify_flags_symbol_oob():
    """符号引用越界 → 致命问题（0xC0000005 根因）。"""
    pg = _opcode("PUSH_G")
    seg0 = bytes([pg]) + struct.pack("<H", 250)  # 操作数 250 ≥ nsyms 10
    ok, issues = verify_fas(seg0, b"", 10, label="oob")
    assert not ok
    assert any("PUSH_G" in i and "out of gvar range" in i for i in issues)


def test_verify_flags_unk_opcode():
    """未知操作码 → 致命问题（误解析风险）。"""
    ok, issues = verify_fas(b"\xfe\x00", b"", 10, label="unk")
    assert not ok
    assert any("UNK opcodes" in i for i in issues)


def test_verify_warns_local_beyond_argc():
    """局部变量索引超过 DEFUN 头 argc → warning 而非致命。
    （/ 局部变量 与 foreach/repeat 循环槽使 DEFUN 头无法完整推断帧大小）
    """
    from compiler.symbol_table import SymbolTable
    from compiler.resource_builder import ResourceBuilder

    st = SymbolTable()
    st.get_or_add("a")
    rb = ResourceBuilder(st)
    seg1 = rb.build(func_offsets={}, module_code=b"", stub_format=True)

    d = _opcode("DEFUN")
    sl = _opcode("SET_LOCAL")  # fmt 2：<u16>
    # DEFUN 头 `14 <a> <b> <c> <d>`（a=argc+循环深度, b=c=argc）：argc=0 无循环
    seg0 = bytes([d, 0, 0, 0, 0, sl]) + struct.pack("<H", 7)  # SET_LOCAL 7 > argc 0
    ok, issues = verify_fas(seg0, seg1, 1, label="lcl")
    fatal = [i for i in issues if not i.startswith("WARN ")]
    assert ok, fatal  # 局部越界仅是 warning，不阻断
    assert any("SET_LOCAL" in i and i.startswith("WARN ") for i in issues)


def test_verify_seg1_gvar_empty_flags():
    """资源段无法重建 gvar 表 → 致命问题。"""
    ok, issues = verify_fas(b"\x0a\x0a", b"", 10, label="seg1")
    assert not ok
    assert any("gvar tables both empty" in i for i in issues)
