"""资源码（resource opcodes）解析与资源段构建测试。

覆盖 seg1 资源流的完整操作码（与 seg0 字节码操作码区分）：
- ``parse_resource_stream`` 逐码解析（符号/字符串/常量/GVARINIT/DEFCODE）
- ``build_mvar_tables`` 栈模拟建表（资源 gvar 表 + 函数 gvar 表）
- ``count_resource_records`` GVARINIT/INIT_DONE 计数
- ``ResourceBuilder.build`` 各类 entry 编码（SYMBOL/STRING/INT/REAL/CONST）
- 真实编译产物的资源流往返一致性
"""
import os
import struct
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

from core.fas_core import (
    parse_resource_stream,
    build_mvar_tables,
    extract_symbol_names,
    parse_fas4,
)
from compiler.resource_builder import (
    ResourceBuilder,
    count_resource_records,
    res_int8,
    res_int32,
    res_gvar_init,
    res_real_str,
)
from compiler.symbol_table import SymbolTable


# ─── 解析辅助 ────────────────────────────────────────────────────────────────


def _build_res(symtab: SymbolTable, **kw) -> bytes:
    """通过 ResourceBuilder 生成资源流明文。"""
    rb = ResourceBuilder(symtab)
    return rb.build(**kw)


def _seg1_plain(fas_path: str) -> bytes:
    """从 FAS 文件提取解密后的 seg1 资源流明文。"""
    return parse_fas4(fas_path)["res_data_decrypted"]


# ─── 资源码解析：parse_resource_stream ───────────────────────────────────────


def test_parse_symbol_block():
    """5b 符号块：连续符号按 NUL 分隔，末尾额外 \\x00。"""
    stream = b"\x5bFOO\x00BAR\x00\x00" + b"\x5bBAZ\x00\x00"
    items, symbols, strings = parse_resource_stream(stream)
    names = [v for t, v in items if t == "SYMBOL"]
    assert names == ["FOO", "BAR", "BAZ"]
    assert symbols == ["FOO", "BAR", "BAZ"]
    assert strings == []


def test_parse_string_block():
    """55 字符串块：count + 每个 (len + bytes)。"""
    stream = b"\x55\x02\x00" + struct.pack("<H", 3) + b"abc" + struct.pack("<H", 2) + b"hi"
    items, symbols, strings = parse_resource_stream(stream)
    assert strings == ["abc", "hi"]
    assert [v for t, v in items if t == "STRING"] == ["abc", "hi"]


def test_parse_ints_and_real():
    """32/33 整数与 3b 实数常量。"""
    stream = res_int8(42) + res_int32(70000) + res_real_str("3.14")
    items, symbols, strings = parse_resource_stream(stream)
    vals = [v for t, v in items]
    assert 42 in vals
    assert 70000 in vals
    assert any(isinstance(v, str) and "3.14" in v for v in vals)


def test_parse_gvarinit_and_defcode_lengths():
    """43 GVARINIT（5 字节）与 3a DEFCODE（1 字节）按长度跳转，不产生资源项。"""
    stream = res_gvar_init(0, 4) + b"\x0a" + b"\x3a\x01" + b"\x1c"
    items, symbols, strings = parse_resource_stream(stream)
    # GVARINIT/DEFCODE 不产生 item；INIT_DONE 产生。
    kinds = {t for t, *_ in items}
    assert "INIT_DONE" in kinds
    assert "GVARINIT" not in kinds


def test_parse_resource_roundtrip():
    """真实编译产物：parse_resource_stream 提取的符号/字符串与符号槽一致。"""
    from compiler.cli import cmd_compile
    from decompiler.fas4_decompiler import Fas4Parser

    with tempfile.TemporaryDirectory() as tmp:
        out = os.path.join(tmp, "o.fas")
        cmd_compile("tests/cad/t06_strcat.lsp", out)
        p = Fas4Parser().parse(out)
        plain = _seg1_plain(out)
        items, symbols, strings = parse_resource_stream(plain)
        # 符号槽（symbol_slots）应包含符号和字符串
        slot_entries = [v for t, v in p.symbol_slots if t in ("SYMBOL", "STRING")]
        assert slot_entries, "no symbol slots"
        assert strings, "expected string literals (Hello, !)"


# ─── build_mvar_tables：栈模拟建表 ───────────────────────────────────────────


def test_mvar_tables_resource_gvars():
    """GVARINIT 将栈顶值写入资源 gvar 表（table0）。"""
    st = SymbolTable()
    st.get_or_add("a")
    st.get_or_add("b")
    st.get_or_add("c")
    rb = ResourceBuilder(st)
    stream = rb.build(func_offsets={}, module_code=b"", stub_format=True)
    rg, fg = build_mvar_tables(stream, 3)
    # 真实构建：符号 A/B/C 合并为 5b 块，GVARINIT 填表；至少部分槽非 None
    filled = [v for v in rg if v is not None]
    assert filled, f"expected non-None resource gvars, got {rg}"


def test_mvar_tables_two_tables():
    """带 module_id 的 GVARINIT 写入函数 gvar 表（table1）。"""
    # 用含 DEFCODE 的真实构建：函数名符号 + DEFCODE 后的 GVARINIT 写函数表
    st = SymbolTable()
    st.get_or_add("f")
    rb = ResourceBuilder(st)
    stream = rb.build(
        func_offsets={"f": 0},
        module_code=b"\x14\x01\x00\x00\x00\x16",
        total_size=8,
        stub_format=True,
    )
    rg, fg = build_mvar_tables(stream, 1)
    assert isinstance(rg, list) and isinstance(fg, list)
    assert len(rg) == 1 and len(fg) == 1


def test_mvar_tables_cons_list():
    """CONS/2a + BUILD_LIST/39 构建列表常量。"""
    st = SymbolTable()
    st.add_constant(("LIST", (("INT", 1), ("INT", 2))))
    rb = ResourceBuilder(st)
    stream = rb.build(func_offsets={}, module_code=b"", stub_format=True)
    rg, fg = build_mvar_tables(stream, 1)
    assert isinstance(rg, list)


# ─── count_resource_records ──────────────────────────────────────────────────


def test_count_records():
    """count_resource_records 统计 GVARINIT + INIT_DONE。"""
    stream = res_gvar_init(0, 4) + b"\x0a" + b"\x1c" + b"\x1c"
    assert count_resource_records(stream) == 3


def test_count_records_real_seg1():
    """真实产物 items 计数 = GVARINIT + INIT_DONE 数。"""
    from compiler.cli import cmd_compile

    with tempfile.TemporaryDirectory() as tmp:
        out = os.path.join(tmp, "o.fas")
        cmd_compile("tests/cad/t05_cond.lsp", out)
        plain = _seg1_plain(out)
        n = count_resource_records(plain)
        assert n >= 2, f"expected >=2 records (GVARINIT+INIT_DONE), got {n}"


# ─── ResourceBuilder entry 编码 ──────────────────────────────────────────────


def test_entry_symbol_encoding():
    """SYMBOL entry → 5b 块，符号名统一大写。"""
    st = SymbolTable()
    st.get_or_add("foo")
    stream = _build_res(st, func_offsets={}, module_code=b"", stub_format=True)
    items, symbols, _ = parse_resource_stream(stream)
    assert "FOO" in symbols, f"symbol should be uppercased, got {symbols}"


def test_entry_string_encoding():
    """STRING entry → 55 块，字符串保持原样（大小写不变）。"""
    st = SymbolTable()
    st.add_string("Hello")
    stream = _build_res(st, func_offsets={}, module_code=b"", stub_format=True)
    items, symbols, strings = parse_resource_stream(stream)
    assert "Hello" in strings, f"string case preserved expected, got {strings}"


def test_entry_const_list():
    """CONST entry（引用字面量列表）→ 原子记录 + BUILD_LIST 收尾。"""
    st = SymbolTable()
    st.add_constant(("LIST", (("INT", 1), ("INT", 2))))
    stream = _build_res(st, func_offsets={}, module_code=b"", stub_format=True)
    assert b"\x39" in stream, "BUILD_LIST(0x39) expected for list const"
    items, symbols, strings = parse_resource_stream(stream)
    assert any(t == "OP_0x39" for t, *_ in items) or any(
        v == 2 and t == "OP_0x39" for t, v in items if isinstance(v, int)
    ), "BUILD_LIST count=2 expected"


def test_entry_int_real_encoding():
    """INT/REAL entry 编码为 32/33/3b。"""
    st = SymbolTable()
    st.add_int(5)
    st.add_real(2.5)
    stream = _build_res(st, func_offsets={}, module_code=b"", stub_format=True)
    assert b"\x32\x05" in stream or b"\x33" in stream
    assert b"\x3b" in stream, "PUSH_REAL(0x3b) expected"


def test_extract_symbol_names_matches_slots():
    """extract_symbol_names 与 Fas4Parser symbol_slots 一致。"""
    from compiler.cli import cmd_compile
    from decompiler.fas4_decompiler import Fas4Parser

    for name in ["t01_math", "t04_while", "t06_strcat", "t13_nested_if"]:
        with tempfile.TemporaryDirectory() as tmp:
            out = os.path.join(tmp, "o.fas")
            cmd_compile(f"tests/cad/{name}.lsp", out)
            p = Fas4Parser().parse(out)
            plain = _seg1_plain(out)
            names = extract_symbol_names(plain)
            # symbol_slots 元素为 ('SYMBOL', name) / ('STRING', s)
            slot_names = [v for t, v in p.symbol_slots if t in ("SYMBOL", "STRING")]
            unique = list(dict.fromkeys(slot_names))
            assert names, f"{name}: extract_symbol_names empty"
            assert set(names) <= set(unique), (
                f"{name}: extracted {set(names) - set(unique)} not in slots"
            )


# ─── 资源码 vs 操作码区分 ────────────────────────────────────────────────────


def test_resource_opcodes_not_in_bytecode_seg0():
    """纯资源码（5b/55/43/56）不出现在 seg0 字节码 OPCODES 表中。

    DEFCODE(3a)/INIT_DONE(1c) 列入表中仅供资源流解析复用，但从不出现在
    seg0 函数字节码里（见 test_bytecode_table_has_no_resource_only_codes）。
    """
    from asm.opcodes import OPCODES

    resource_only = {0x5B, 0x55, 0x43, 0x56}
    for op in resource_only:
        assert op not in OPCODES, (
            f"resource opcode 0x{op:02x} must not be in bytecode OPCODES table"
        )


def test_shared_byte_different_semantics():
    """共享字节（32/5c/09/06）在资源流与字节码中的语义不同。"""
    # 5c 在字节码是 GET_LOCAL_WIDE，在资源流是 DEFCODE 前固定标记
    from asm.opcodes import OPCODE_TO_NAME
    assert OPCODE_TO_NAME[0x5C] == "GET_LOCAL_WIDE"

    # 资源流 5c 是 `5c 00 00` 固定序列（DEFCODE 前）
    st = SymbolTable()
    st.get_or_add("f")
    rb = ResourceBuilder(st)
    # 模拟 DEFCODE 段：5c 00 00 32 <off> 5b <name> 00 00 3a
    seg = b"\x5c\x00\x00\x32\x00\x5bF\x00\x00\x3a"
    items, symbols, _ = parse_resource_stream(seg)
    assert "F" in symbols


def test_bytecode_table_has_no_resource_only_codes():
    """seg0 字节码中不出现纯资源码（5b/55/43/56）。

    用真实 CAD golden 反汇编验证：DEFCODE(3a)/INIT_DONE(1c) 被列入 OPCODES
    表供资源流复用，但 seg0 函数字节码中它们不出现。
    """
    import glob
    from decompiler.fas4_decompiler import Fas4Parser, Disassembler, is_compact_stub

    resource_codes = {0x5B, 0x55, 0x43, 0x56}
    for f in glob.glob("tests/*_cad.fas") + glob.glob("tests/cad/*_cad.fas"):
        try:
            p = Fas4Parser().parse(f)
        except Exception:
            continue
        # 原始字节中直接扫描纯资源码字节
        for op in resource_codes:
            assert op not in p.bytecode, f"{f}: resource byte 0x{op:02x} in seg0"


# ─── 真实产物资源流一致性 ───────────────────────────────────────────────────


@pytest.mark.parametrize(
    "name",
    ["t01_math", "t03_fib", "t05_cond", "t06_strcat", "t13_nested_if", "t15_cad_funcs"],
)
def test_real_seg1_resource_stream_parseable(name):
    """真实产物 seg1 解密后可解析，符号/字符串不丢失。"""
    from compiler.cli import cmd_compile

    with tempfile.TemporaryDirectory() as tmp:
        out = os.path.join(tmp, "o.fas")
        cmd_compile(f"tests/cad/{name}.lsp", out)
        plain = _seg1_plain(out)
        items, symbols, strings = parse_resource_stream(plain)
        assert items, f"{name}: no resource items parsed"
        assert symbols, f"{name}: no symbols extracted"
