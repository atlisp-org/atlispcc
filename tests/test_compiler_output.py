"""Standalone compiler output tests: compile Lisp and inspect FAS binary directly."""
import sys
sys.path.insert(0, '.')

import os
import tempfile
import pytest
from compiler.parser import Parser
from compiler.symbol_table import SymbolTable
from compiler.codegen import CodeGenerator, BytecodeBuffer
from compiler.resource_builder import ResourceBuilder
from compiler.fas_writer import FasWriter
from core.fas_core import find_key as fas_find_key
from core.fas_core import decrypt_stream as fas_decrypt_stream

ENCODE_POP = bytes([0x0a])
FAS4_MAGIC = b'\r\n FAS4-FILE ; Built by atlispcc!\r\n'
SEG_TERMINATOR = b'\x16\x24\r\n'


def _compile_to_fas(src: str) -> bytes:
    """Compile Lisp source to FAS binary, return raw bytes."""
    parser = Parser(src)
    program = parser.parse()

    symtab = SymbolTable()
    symtab.collect_symbols(program)

    codegen = CodeGenerator(symtab)
    from compiler.ast_nodes import Defun

    all_bc = BytecodeBuffer()
    func_offsets = {}

    other_forms = [f for f in program.forms if not isinstance(f, Defun)]
    for form in other_forms:
        codegen._emit_expr(all_bc, form)
        all_bc.emit(ENCODE_POP)

    for form in program.forms:
        if isinstance(form, Defun):
            offset = len(all_bc.data)
            fb, _ = codegen.generate_function(form)
            func_offsets[form.name] = offset
            all_bc.emit(fb)

    for name, offset in func_offsets.items():
        symtab.add_func_ref(name, offset)

    all_bc.resolve()
    seg0 = bytes(all_bc.data)
    resource = ResourceBuilder(symtab)
    seg1 = resource.build(func_offsets)

    with tempfile.NamedTemporaryFile(suffix='.fas', delete=False) as f:
        fas_path = f.name
        writer = FasWriter(symtab)
        writer.write(fas_path, seg0, seg1)

    with open(fas_path, 'rb') as fh:
        data = fh.read()
    os.unlink(fas_path)
    return data


def test_magic_header():
    """FAS binary starts with the correct magic string."""
    data = _compile_to_fas('(defun foo () 1)')
    assert data.startswith(FAS4_MAGIC), f"Bad magic: {data[:50]}"


def _parse_fas(data: bytes):
    """Parse FAS binary into its constituent parts.
    Returns (nsyms, seg0_bytecode, seg1_data, seg1_item_count)."""
    # Format:
    #   \r\n FAS4-FILE ; Do not change it!\r\n
    #   <total_size>\r\n
    #   <nsyms> $<bytecode>                   <- seg0 payload
    #   \x16\x24\r\n                           <- SEG_TERMINATOR
    #   <seg1_len> <item_count> $<seg1_data> <trailer>
    parts = data.split(SEG_TERMINATOR)
    assert len(parts) == 2
    seg0_part, seg1_full = parts

    # Find the nsyms header: it's after the magic and total_size lines
    magic_end = seg0_part.index(b'\r\n', 2)  # first \r\n after initial bytes
    size_end = seg0_part.index(b'\r\n', magic_end + 1)  # \r\n after total_size
    nsyms_and_bc = seg0_part[size_end + 2:]

    # nsyms_and_bc = b'<nsyms> $<bytecode>'
    dollar_at = nsyms_and_bc.index(b'$')
    nsyms = int(nsyms_and_bc[:dollar_at - 1])  # before " $"
    bytecode = nsyms_and_bc[dollar_at + 1:]

    # seg1_full: <seg1_len> <item_count> $<seg1_data>\r\n
    seg1_no_trailing = seg1_full.rstrip(b'\r\n')
    dollar_at = seg1_no_trailing.index(b'$')
    seg1_header = seg1_no_trailing[:dollar_at - 1]  # "<len> <count>"
    seg1_data = seg1_no_trailing[dollar_at + 1:]
    header_parts = seg1_header.split(b' ')
    seg1_len = int(header_parts[0])
    sec2_items = int(header_parts[1]) if len(header_parts) >= 2 else 0

    # seg1 is XOR-encrypted; decrypt with the embedded key.
    key = fas_find_key(data)
    if key:
        seg1_data = fas_decrypt_stream(seg1_data, key)

    return nsyms, bytecode, seg1_data, sec2_items


def test_two_segments():
    """FAS binary: two segments separated by terminator, with nsyms > 0."""
    data = _compile_to_fas('(defun foo () 1)')
    assert SEG_TERMINATOR in data, "Segment terminator not found"
    nsyms, bc, seg1, _ = _parse_fas(data)
    assert nsyms > 0, f"Expected >0 symbols, got {nsyms}"
    assert len(bc) > 0, "Empty bytecode segment"
    assert len(seg1) > 0, "Empty seg1"


def test_symbol_table_content():
    """Compiled FAS contains expected symbols."""
    data = _compile_to_fas('(defun foo () 1)')
    nsyms, bc, seg1, _ = _parse_fas(data)
    assert nsyms >= 1, f"Expected >=1 symbol (foo), got {nsyms}"


def test_func_def_compile():
    """Compiled function has non-empty bytecode."""
    data = _compile_to_fas('(defun foo () 1)')
    _, bc, _, _ = _parse_fas(data)
    assert len(bc) >= 2, f"Bytecode too short ({len(bc)} bytes)"
    # Should contain: PUSH_INT (0x32) for the integer 1
    assert b'\x32' in bc, "Expected PUSH_INT opcode in function body"


def test_init_code_compile():
    """Top-level init code produces separate bytecode segment."""
    data = _compile_to_fas('(princ "Hello")\n(defun foo () 1)')
    _, bc, seg1, _ = _parse_fas(data)
    assert len(bc) > 0
    # The "Hello" string should be in seg1 (resource section), not bytecode
    assert b'Hello' in seg1, (
        "String literal 'Hello' should be in resource section (seg1)"
    )


def test_local_vars_symbols():
    """Local variables appear in the symbol table."""
    src = '(defun foo (/ x y) (setq x 10) (+ x y))'
    data = _compile_to_fas(src)

    _, _, seg1, _ = _parse_fas(data)

    # seg1 should contain 'foo'/'x'/'y' as symbols (CAD 符号名统一大写)
    assert b'FOO\x00' in seg1, "Symbol 'FOO' missing from seg1"
    assert b'X\x00' in seg1, "Symbol 'X' missing from seg1"
    assert b'Y\x00' in seg1, "Symbol 'Y' missing from seg1"


def test_string_literal_in_seg1():
    """String literals appear in the resource section."""
    src = '(defun hello () (princ "Hello World"))'
    data = _compile_to_fas(src)

    _, _, seg1, _ = _parse_fas(data)

    assert b'Hello World' in seg1, (
        "String literal 'Hello World' not found in seg1"
    )


def test_magic_roundtrip():
    """Compiled FAS: compile -> decompile produces valid Lisp (roundtrip)."""
    from decompiler.fas4_decompiler import Fas4Parser, Disassembler, \
        ControlFlowAnalyzer, LispGenerator, is_compact_stub
    from tools.validate import tokenize, parse_tokens, validate_ast

    src = '(defun hello () (princ "Hello, World!") (princ))'
    parser = Parser(src)
    program = parser.parse()

    symtab = SymbolTable()
    symtab.collect_symbols(program)

    codegen = CodeGenerator(symtab)
    from compiler.ast_nodes import Defun

    all_bc = BytecodeBuffer()
    func_offsets = {}

    for form in program.forms:
        if isinstance(form, Defun):
            offset = len(all_bc.data)
            fb, _ = codegen.generate_function(form)
            func_offsets[form.name] = offset
            all_bc.emit(fb)

    for name, offset in func_offsets.items():
        symtab.add_func_ref(name, offset)

    all_bc.resolve()
    seg0 = bytes(all_bc.data)
    resource = ResourceBuilder(symtab)
    seg1 = resource.build(func_offsets)

    with tempfile.NamedTemporaryFile(suffix='.fas', delete=False) as f:
        fas_path = f.name
        writer = FasWriter(symtab)
        writer.write(fas_path, seg0, seg1)

    try:
        decomp_parser = Fas4Parser()
        fas = decomp_parser.parse(fas_path)
        disasm = Disassembler(short_subr=is_compact_stub(fas.bytecode, fas.function_catalog))
        instructions = disasm.disassemble(fas.bytecode, fas.nsyms)
        cfa = ControlFlowAnalyzer(instructions, fas.function_catalog)
        functions = cfa.find_functions()
        gen = LispGenerator(fas)
        result = gen.generate(functions, fas_path)

        assert '(defun hello ()' in result
        assert '(princ "Hello, World!")' in result

        tokens, errs = tokenize(result)
        assert not errs, f"Tokenization failed: {errs}"
        forms, errs = parse_tokens(tokens)
        assert not errs, f"Parsing failed: {errs}"
        errs = validate_ast(forms)
        assert not errs, f"Validation failed: {errs}"
    finally:
        os.unlink(fas_path)


def test_multi_setq():
    """Multi-value setq compiles correctly."""
    src = '(defun foo () (setq a 1 b 2 c 3) (+ a b c))'
    data = _compile_to_fas(src)
    assert data.startswith(FAS4_MAGIC)
    assert SEG_TERMINATOR in data


@pytest.mark.parametrize('form', ['(exit)', '(quit)'])
def test_exit_quit_emits_exit_opcode(form):
    """(exit)/(quit) compile to PUSH_T + EXIT_IF_NOT_ZERO (0x3e), not a USUBR."""
    data = _compile_to_fas(f'(defun foo () {form})')
    _, bc, _, _ = _parse_fas(data)
    # PUSH_T (0x02) followed by EXIT_IF_NOT_ZERO (0x3e)
    assert b'\x02\x3e' in bc, f'Expected PUSH_T; EXIT_IF_NOT_ZERO, got {bc!r}'
    # 0x35 = USUBR opcode; exit/quit must not be encoded as one
    assert b'\x35' not in bc, f'USUBR emitted for {form}: {bc!r}'


#: (source, cad_golden) pairs where our compact-stub output must be byte-identical
#: to the AutoCAD `vlisp-compile` golden (bytecode AND resource items).
CAD_GOLDEN_PAIRS = [
    ('fact.lsp', 'fact_cad.fas'),
    ('fun.lsp', 'fun-cad.fas'),
    ('m1.lsp', 'm1_cad.fas'),
    ('m2.lsp', 'm2_cad.fas'),
    ('mix.lsp', 'mix_cad.fas'),
    ('multi.lsp', 'multi_cad.fas'),
    ('rt_e.lsp', 'rt_e_cad.fas'),
]

#: t-series sources whose compiled output is byte-identical to the CAD golden
#: (generated via `vlisp-compile` on AutoCAD 24.1s, 2026-08-04).
#: Source .lsp and golden .fas both live under tests/cad/.
CAD_T_SERIES_IDENTICAL = [
    't01_math', 't02_recursion', 't03_fib', 't04_while', 't05_cond',
    't06_strcat', 't07_list', 't08_apply_mapcar', 't09_funcall',
    't10_init', 't11_localvars', 't12_quote', 't13_nested_if',
    't14_command', 't15_cad_funcs', 'andor', 'and2', 'or2', 'andval',
]

#: t-series sources with KNOWN remaining byte diffs (see docs/development-plan.md 8.C1).
#: Kept as xfail regression: when a gap is fixed, move it to CAD_T_SERIES_IDENTICAL.
CAD_T_SERIES_DIFF = []

_BASE_DIR = os.path.dirname(os.path.abspath(__file__))


def _golden_paths(src_name, golden_name):
    src = os.path.join(_BASE_DIR, src_name)
    golden = os.path.join(_BASE_DIR, golden_name)
    if not (os.path.exists(src) and os.path.exists(golden)):
        pytest.skip(f'missing golden fixture: {src_name}/{golden_name}')
    return src, golden


@pytest.mark.parametrize('src_name,golden_name', CAD_GOLDEN_PAIRS,
                         ids=[s for s, _ in CAD_GOLDEN_PAIRS])
def test_byte_identity_with_cad_golden(src_name, golden_name):
    """Compiled compact-stub output must be byte-identical to a CAD golden.

    Regression guard: multi-function + quoted-lambda previously emitted
    PUSH_G <symtab idx> for the lambda const instead of <gvar slot - 1>;
    single-function cases masked it (nfuncs == 1). rt_e.lsp covers the
    multi+lambda path fixed in _patch_usubr_idx. while/cond alignment is
    covered by the t-series golden tests (t04_while/t05_cond).
    """
    from compiler.cli import cmd_compile
    from decompiler.fas4_decompiler import Fas4Parser

    src, golden = _golden_paths(src_name, golden_name)
    with tempfile.TemporaryDirectory() as tmp:
        out = os.path.join(tmp, 'out.fas')
        cmd_compile(src, out)
        ours = Fas4Parser().parse(out)
        ref = Fas4Parser().parse(golden)
        assert ours.nsyms == ref.nsyms, (
            f'{src_name}: nsyms {ours.nsyms} != {ref.nsyms}'
        )
        assert ours.bytecode == ref.bytecode, (
            f'{src_name}: seg0 bytecode differs from CAD golden\n'
            f'  ours: {ours.bytecode.hex()}\n'
            f'  CAD : {ref.bytecode.hex()}'
        )
        assert ours.resource_items == ref.resource_items, (
            f'{src_name}: seg1 resource items differ from CAD golden'
        )


def _t_series_golden_paths(name):
    """Return (src, golden) for a t-series CAD golden under tests/cad/.

    Both the source .lsp and the CAD golden .fas live in tests/cad/ so the
    golden sample set is self-contained there.
    """
    _BASE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'cad')
    src = os.path.join(_BASE, f'{name}.lsp')
    golden = os.path.join(_BASE, f'{name}_cad.fas')
    if not (os.path.exists(src) and os.path.exists(golden)):
        pytest.skip(f'missing t-series golden fixture: {name}')
    return src, golden


@pytest.mark.parametrize('name', CAD_T_SERIES_IDENTICAL)
def test_t_series_byte_identity(name):
    """t-series outputs confirmed byte-identical to CAD `vlisp-compile` goldens.

    Goldens regenerated on AutoCAD 24.1s (2026-08-04), see tests/cad/t*_cad.fas.
    """
    from compiler.cli import cmd_compile
    from decompiler.fas4_decompiler import Fas4Parser

    src, golden = _t_series_golden_paths(name)
    with tempfile.TemporaryDirectory() as tmp:
        out = os.path.join(tmp, 'out.fas')
        cmd_compile(src, out)
        ours = Fas4Parser().parse(out)
        ref = Fas4Parser().parse(golden)
        assert ours.nsyms == ref.nsyms, f'{name}: nsyms {ours.nsyms} != {ref.nsyms}'
        assert ours.bytecode == ref.bytecode, (
            f'{name}: seg0 bytecode differs from CAD golden\n'
            f'  ours: {ours.bytecode.hex()}\n'
            f'  CAD : {ref.bytecode.hex()}'
        )
        assert ours.resource_items == ref.resource_items, (
            f'{name}: seg1 resource items differ from CAD golden'
        )


@pytest.mark.parametrize('name', CAD_T_SERIES_DIFF)
def test_t_series_byte_identity_known_diff(name):
    """t-series with KNOWN remaining byte diffs (see development-plan.md 8.C1).

    xfail placeholder: as each gap is fixed, move the name into
    CAD_T_SERIES_IDENTICAL and drop this expectation.
    """
    from compiler.cli import cmd_compile
    from decompiler.fas4_decompiler import Fas4Parser

    src, golden = _t_series_golden_paths(name)
    with tempfile.TemporaryDirectory() as tmp:
        out = os.path.join(tmp, 'out.fas')
        cmd_compile(src, out)
        ours = Fas4Parser().parse(out)
        ref = Fas4Parser().parse(golden)
        if ours.nsyms == ref.nsyms and ours.bytecode == ref.bytecode \
                and ours.resource_items == ref.resource_items:
            pytest.fail(
                f'{name}: now byte-identical! Move to CAD_T_SERIES_IDENTICAL '
                f'and remove from CAD_T_SERIES_DIFF.'
            )
        pytest.xfail(
            f'{name}: known byte diff vs CAD golden '
            f'(nsyms {ours.nsyms}vs{ref.nsyms})'
        )


#: 纯顶层（无 defun）文件：空 seg0 使 Fas4Parser 无法解析（"Bad FAS
#: payload header"），故直接解密对比 seg1 资源流与文件头。
PURE_TOP_LEVEL_CASES = [
    ('set5.lsp', 'set5_cad.fas'),
    ('setqa.lsp', 'setqa_cad.fas'),
    ('setcmp.lsp', 'setcmp_cad.fas'),
]


def _decrypt_seg1(path):
    """返回 (magic 之后的文件头到 res 头前的字节, 解密后的 seg1)。

    头部比较跳过 magic 文本（新产物用 `Built by atlispcc!`，CAD golden 用
    `Do not change it!`），只比较 total_size/nsyms/seg0/res 头等结构部分。
    """
    import re
    from core.fas_core import CRUNCH_MARKER, find_fas4_magic
    data = open(path, 'rb').read()
    pos = data.find(CRUNCH_MARKER)
    assert pos > 0, f'{path}: no crunch marker'
    ms = list(re.finditer(rb'(\d+) (\d+) \$', data))
    m = ms[-1]
    rsz = int(m.group(1))
    key = None
    for k in range(pos - 80, pos):
        klen = pos + len(CRUNCH_MARKER) - k
        if k - 1 >= 0 and data[k - 1] == klen:
            key = data[k:pos + len(CRUNCH_MARKER)]
            enc = data[m.end():k - 1]
            if len(enc) == rsz:
                _, magic = find_fas4_magic(data)
                head_start = 0 if magic is None else len(magic)
                return data[head_start:m.end()], fas_decrypt_stream(enc, key)
    assert key is not None, f'{path}: cannot locate XOR key'
    _, magic = find_fas4_magic(data)
    head_start = 0 if magic is None else len(magic)
    return data[head_start:m.end()], fas_decrypt_stream(
        data[m.end():m.end() + rsz], key)


@pytest.mark.parametrize('src_name,golden_name', PURE_TOP_LEVEL_CASES)
def test_pure_top_level_byte_identity(src_name, golden_name):
    """纯顶层（无 defun）文件头 + seg1 与 CAD golden 完全一致。

    覆盖引用单符号 `'a` 作为普通符号槽（非 CONST）、空 seg0 终止符、
    setq 值 PUSH_VALUE/PUSH_G 区分、seg1 头 items 用 form 数等规则。
    """
    from compiler.cli import cmd_compile

    src, golden = _golden_paths(
        os.path.join('cad', src_name), os.path.join('cad', golden_name))
    with tempfile.TemporaryDirectory() as tmp:
        out = os.path.join(tmp, 'out.fas')
        cmd_compile(src, out)
        ours_head, ours_seg1 = _decrypt_seg1(out)
        ref_head, ref_seg1 = _decrypt_seg1(golden)
        assert ours_head == ref_head, (
            f'{src_name}: file head differs from CAD golden\n'
            f'  ours: {ours_head.hex()}\n'
            f'  CAD : {ref_head.hex()}'
        )
        assert ours_seg1 == ref_seg1, (
            f'{src_name}: seg1 differs from CAD golden\n'
            f'  ours: {ours_seg1.hex()}\n'
            f'  CAD : {ref_seg1.hex()}'
        )
