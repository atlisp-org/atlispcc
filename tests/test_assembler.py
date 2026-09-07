"""Tests for the FAS4 assembler/disassembler (.fas ↔ .lasm)."""
import os
import tempfile

import pytest

from asm.assembler import disassemble_fas, assemble_lasm, assemble_lasm_zelx
from compiler.cli import cmd_compile as compile_lsp
from decompiler.fas4_decompiler import Fas4Parser, LispGenerator


def _compile_lsp(source: str) -> str:
    fas_path = os.path.join(tempfile.gettempdir(), 'test_asm.fas')
    compile_lsp(source, fas_path)
    return fas_path


def _decompile_fas(fas_path: str) -> str:
    parser = Fas4Parser()
    fas = parser.parse(fas_path)
    from decompiler.fas4_decompiler import Disassembler, ControlFlowAnalyzer
    disasm = Disassembler()
    instructions = disasm.disassemble(fas.bytecode, fas.nsyms)
    cfa = ControlFlowAnalyzer(instructions, fas.function_catalog)
    functions = cfa.find_functions()
    gen = LispGenerator(fas)
    return gen.generate(functions, fas_path)


def test_disassemble_assemble_roundtrip():
    source = """
(defun test-func (x)
  (setq y (+ x 1))
  (princ y))
"""
    fas_path = _compile_lsp(source)
    lasm_text = disassemble_fas(fas_path)

    assert '.symbols' in lasm_text
    assert '.function' in lasm_text
    assert 'DEFUN' in lasm_text

    fd, out_path = tempfile.mkstemp(suffix='.fas')
    os.close(fd)
    try:
        assemble_lasm(lasm_text, out_path)
        lsp_code = _decompile_fas(out_path)
        assert len(lsp_code) > 0
        assert 'defun' in lsp_code.lower()
    finally:
        if os.path.exists(out_path):
            os.unlink(out_path)


def test_simple_add_function():
    lasm_text = """; Test: simple add
.symbols
  0: SYMBOL __init__
  1: SYMBOL test-add
  2: SYMBOL x
  3: SYMBOL y
.end_symbols

.function __init__, 0
  0x0000: DEFUN test-add, 0
  0x0005: INIT_ARGS 2
  0x0008: ALPHA 1
  0x000a: PUSH_G x
  0x000c: PUSH_G y
  0x000e: FIX_ADD
  0x000f: CLEAR_LOCAL 1
  0x0011: BETA 0
  0x0013: END_DEFUN
  0x0014: NIL
.end_function
"""
    fd, out_path = tempfile.mkstemp(suffix='.fas')
    os.close(fd)
    try:
        assemble_lasm(lasm_text, out_path)
        lsp_code = _decompile_fas(out_path)
        assert len(lsp_code) > 0
        assert '+' in lsp_code
    finally:
        if os.path.exists(out_path):
            os.unlink(out_path)


def test_assembler_handles_local_vars():
    lasm_text = """; Test local variable handling
.symbols
  0: SYMBOL __init__
  1: SYMBOL my-func
  2: SYMBOL v
  3: SYMBOL n
.end_symbols

.function my-func, 1
  0x0000: DEFUN my-func, 0
  0x0005: INIT_ARGS 1
  0x0008: ALPHA 0
  0x000a: PUSH_G n
  0x000c: GET_LOCAL 0
  0x000e: FIX_ADD
  0x000f: SET_LOCAL 0
  0x0011: BETA 0
  0x0013: END_DEFUN
  0x0014: NIL
.end_function
"""
    fd, out_path = tempfile.mkstemp(suffix='.fas')
    os.close(fd)
    try:
        assemble_lasm(lasm_text, out_path)
        lsp_code = _decompile_fas(out_path)
        assert len(lsp_code) > 0
    finally:
        if os.path.exists(out_path):
            os.unlink(out_path)


def test_disassemble_output_is_parseable():
    source = """
(defun hello ()
  (princ "Hello, World!"))
"""
    fas_path = _compile_lsp(source)
    lasm_text = disassemble_fas(fas_path)

    for line in lasm_text.split('\n'):
        stripped = line.split(';', 1)[0].strip()
        if not stripped:
            continue
        if stripped.startswith('.'):
            assert stripped.startswith(('.format ', '.nsyms ')) or stripped in (
                '.symbols', '.end_symbols',
            ) or stripped.startswith('.function') or stripped.startswith('.end_function')
        elif ':' in stripped[:10]:
            assert any(c.isalpha() for c in stripped[10:]), f'Missing mnemonic: {stripped}'
        elif stripped[0].isdigit() and ': SYMBOL' in stripped:
            continue


def test_cli_disasm_asm_roundtrip():
    """CLI disasm → asm 往返：.fas → .lasm → .fas → 反编译验证。"""
    from compiler.cli import cmd_disassemble, cmd_assemble, cmd_decompile
    fas_path = _compile_lsp('(defun foo (x) (princ (+ x 1)))')

    lasm_path = fas_path.replace('.fas', '.lasm')
    out_path = fas_path.replace('.fas', '_out.fas')
    lsp_path = fas_path.replace('.fas', '_out.lsp')
    try:
        cmd_disassemble(fas_path, lasm_path)
        assert os.path.exists(lasm_path)
        with open(lasm_path, encoding='utf-8') as f:
            text = f.read()
        assert '.symbols' in text
        assert 'FUNC' in text or 'USUBR' in text or 'DEFUN' in text

        cmd_assemble(lasm_path, out_path)
        assert os.path.exists(out_path)
        cmd_decompile(out_path, lsp_path)
        with open(lsp_path, encoding='utf-8') as f:
            code = f.read()
        assert '(defun foo' in code
        assert 'princ' in code
    finally:
        for p in (lasm_path, out_path, lsp_path):
            if os.path.exists(p):
                os.unlink(p)


def _seg0(f):
    d = open(f, "rb").read()
    magic = b"\r\n FAS4-FILE ; Do not change it!\r\n"
    i = len(magic); j = d.find(b"\r\n", i); i = j + 2; j = d.find(b" $", i); i = j + 2
    term = d.find(b"\x16\x24\r\n", i)
    return d[i:term]


def _seg1_plain(f):
    from tools.zelx_info import rolling_xor
    d = open(f, "rb").read()
    magic = b"\r\n FAS4-FILE ; Do not change it!\r\n"
    i = len(magic); j = d.find(b"\r\n", i); i = j + 2; j = d.find(b" $", i); i = j + 2
    term = d.find(b"\x16\x24\r\n", i)
    s1s = term + 4; j = d.find(b" $", s1s)
    parts = d[s1s:j].split()
    enc = d[j + 2:j + 2 + int(parts[0])]
    pos = d.find(b"\n;fas4 crunch\n;")
    for rl in range(6, 12):
        ks = pos - rl; ke = pos + 15
        if d[ks - 1] == (ke - ks):
            return rolling_xor(enc, d[ks:ke])
    return b""


def test_disasm_zelx():
    """.zelx 直接反汇编：zelx→lasm 与 fas→lasm 完全一致。"""
    from compiler.cli import cmd_disassemble

    samples = os.path.join(os.path.dirname(__file__), "..", "samples", "zelx-reversing")
    t1_fas = os.path.join(samples, "t1.fas")
    if not os.path.exists(t1_fas):
        pytest.skip("t1.fas sample missing")
    zlx_lasm = os.path.join(tempfile.gettempdir(), "t1_zlx.lasm")
    fas_lasm = os.path.join(tempfile.gettempdir(), "t1_fas.lasm")
    try:
        cmd_disassemble(os.path.join(samples, "t1.zelx"), zlx_lasm)
        cmd_disassemble(t1_fas, fas_lasm)
        with open(zlx_lasm, encoding="utf-8") as a, open(fas_lasm, encoding="utf-8") as b:
            # zelx 不携带 crunch 日期，恢复的 fas 无日期行；fas 参考内嵌日期。
            # 两者为元数据差异，比对前剔除。
            zlx_lines = [l for l in a.read().splitlines() if not l.startswith("; Crunch date:")]
            fas_lines = [l for l in b.read().splitlines() if not l.startswith("; Crunch date:")]
            assert zlx_lines == fas_lines
    finally:
        for p in (zlx_lasm, fas_lasm):
            if os.path.exists(p):
                os.unlink(p)


def test_lasm_zelx_roundtrip():
    """通用 lasm → zelx：lasm 汇编成 .zelx，再恢复 .fas 与原始一致（seg0+seg1）。"""
    from tools.zelx_to_fas import zelx_to_fas

    samples = os.path.join(os.path.dirname(__file__), "..", "samples", "zelx-reversing")
    t1_fas = os.path.join(samples, "t1.fas")
    if not os.path.exists(t1_fas):
        pytest.skip("t1.fas sample missing")
    zlx_path = os.path.join(tempfile.gettempdir(), "t1_roundtrip.zelx")
    fas_path = os.path.join(tempfile.gettempdir(), "t1_roundtrip_rec.fas")

    try:
        lasm_text = disassemble_fas(t1_fas)
        assemble_lasm_zelx(lasm_text, zlx_path)
        zelx_to_fas(zlx_path, fas_path)
        orig = os.path.join(samples, "t1.fas")
        assert _seg0(orig) == _seg0(fas_path)
        assert _seg1_plain(orig) == _seg1_plain(fas_path)
    finally:
        for p in (zlx_path, fas_path):
            if os.path.exists(p):
                os.unlink(p)


def test_multiline_string_roundtrip():
    """多行/特殊字符字符串（换行、逗号、分号、引号）在 .lasm 中单行化并可逆汇编。"""
    lsp_path = os.path.join(tempfile.gettempdir(), "ml_str.lsp")
    fas_path = os.path.join(tempfile.gettempdir(), "ml_str.fas")
    out_path = os.path.join(tempfile.gettempdir(), "ml_str_out.fas")
    try:
        with open(lsp_path, "w", encoding="utf-8") as f:
            f.write('(defun f () (strcat "a\\nb,c;d" "e\\"f"))\n')
        compile_lsp(lsp_path, fas_path)
        lasm_text = disassemble_fas(fas_path)
        # 多行/特殊字符字符串必须是单行引号形式且带 STRING 类型，不得有裸延续行
        assert 'STRING "a\\nb,c;d"' in lasm_text
        assemble_lasm(lasm_text, out_path)
        assert _seg0(fas_path) == _seg0(out_path)
        assert _seg1_plain(fas_path) == _seg1_plain(out_path)
    finally:
        for p in (lsp_path, fas_path, out_path):
            if os.path.exists(p):
                os.unlink(p)


def test_wide_subr_large_file_roundtrip():
    """大文件（nsyms>256）宽格式 USUBR/FUNC 往返：seg0+nsyms 逐字节一致。

    回归：asm 此前 compact 模式仅支持 3 字节 USUBR/FUNC，对 nsyms>256 的
    宽格式（5/6 字节）文件会截断索引，导致 disasm→asm 往返 seg0 错位。
    """
    repo = os.path.join(os.path.dirname(__file__), "..")
    src = os.path.normpath(os.path.join(repo, "tests", "atlisp_u.fas"))
    if not os.path.exists(src):
        return  # 大文件样本缺失时跳过
    out_path = os.path.join(tempfile.gettempdir(), "atlisp_u_wide_rt.fas")
    try:
        lasm_text = disassemble_fas(src)
        # 大文件须判定为紧凑 stub 且含宽格式 USUBR（3 操作数）
        assert ".format compact" in lasm_text
        assert "USUBR 1, [2440], 3" in lasm_text or re_wide_usubr(lasm_text)
        assemble_lasm(lasm_text, out_path)
        assert _seg0(src) == _seg0(out_path)
        from decompiler.fas4_decompiler import Fas4Parser
        o = Fas4Parser().parse(src)
        n = Fas4Parser().parse(out_path)
        assert o.nsyms == n.nsyms
    finally:
        if os.path.exists(out_path):
            os.unlink(out_path)


def test_cinit_module_stub_roundtrip():
    """混合模式（defun+顶层）产物的 c:init 模块 stub 段往返写入 seg0。

    回归：ControlFlowAnalyzer 把不在函数目录的模块代码段标记为
    ``c:init``（sym_idx=-1），disasm 输出为 ``.function __init__, -1``，
    但 pass1 正则 ``(\\d+)`` 不匹配负索引且 compact 汇编跳过 ``__init__``，
    导致段被整体丢弃、后续函数偏移错位、seg0 不可恢复。小文件（无
    c:init 段）不受影响。
    """
    from compiler.cli import cmd_compile

    repo = os.path.join(os.path.dirname(__file__), "..")
    src = os.path.normpath(os.path.join(repo, "tests", "atlisp_u.lsp"))
    if not os.path.exists(src):
        return  # fixture 缺失时跳过
    fas_path = os.path.join(tempfile.gettempdir(), "atlisp_u_cinit.fas")
    out_path = os.path.join(tempfile.gettempdir(), "atlisp_u_cinit_rt.fas")
    try:
        cmd_compile(src, fas_path)
        lasm_text = disassemble_fas(fas_path)
        # 含 c:init 段（负索引 `__init__, -1`），是触发回归的必要条件
        assert ".function __init__, -1" in lasm_text
        assemble_lasm(lasm_text, out_path)
        assert _seg0(fas_path) == _seg0(out_path)
        from decompiler.fas4_decompiler import Fas4Parser
        o = Fas4Parser().parse(fas_path)
        n = Fas4Parser().parse(out_path)
        assert o.nsyms == n.nsyms
    finally:
        for p in (fas_path, out_path):
            if os.path.exists(p):
                os.unlink(p)


def re_wide_usubr(text: str) -> bool:
    """检查 .lasm 是否含宽格式 USUBR（USUBR <argc>, <sym>, <flags>）。"""
    import re
    return bool(re.search(r"USUBR \d+, [^,]+,\s*\d+", text))


def test_pure_top_level_selfcontained_nsyms():
    """纯顶层 selfcontained 文件 nsyms 随 .nsyms 指令还原（set5/setcmp/setqa）。"""
    repo = os.path.join(os.path.dirname(__file__), "..")
    for name in ("set5_cad.fas", "setcmp_cad.fas", "setqa_cad.fas"):
        src = os.path.normpath(os.path.join(repo, "tests", "cad", name))
        if not os.path.exists(src):
            continue
        out_path = os.path.join(tempfile.gettempdir(), f"{name}_rt.fas")
        try:
            lasm_text = disassemble_fas(src)
            assert ".format selfcontained" in lasm_text
            assemble_lasm(lasm_text, out_path)
            from decompiler.fas4_decompiler import Fas4Parser
            o = Fas4Parser().parse(src)
            n = Fas4Parser().parse(out_path)
            assert o.nsyms == n.nsyms
            assert o.bytecode == n.bytecode
        finally:
            if os.path.exists(out_path):
                os.unlink(out_path)