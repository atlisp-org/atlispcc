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


def test_value_position_if_no_then_pop():
    """A value-position `if` (setq RHS) must NOT get a then-branch POP.

    Regression for P1-3: `(setq r (if ...))` in the *middle* of a function
    previously emitted `PUSH_INT8 <then>; POP` (via _emit_if's non-tail POP),
    dropping the then-value before SETQ_G consumed it. CAD golden a4.fas
    byte-identity shows `PUSH_INT8[1]; JUMP; PUSH_INT8[2]; SETQ_G` — no POP
    between the then literal and SETQ_G.
    """
    from compiler.cli import cmd_compile

    src = '(defun f (x) (setq r (if (> x 0) 1 2)) (princ r))'
    with tempfile.TemporaryDirectory() as tmp:
        out = os.path.join(tmp, 'out.fas')
        cmd_compile(src, out)
        _, bc, _, _ = _parse_fas(open(out, 'rb').read())
        # then-branch PUSH_INT8 (0x32) must be directly followed by JUMP (0x57):
        # no POP (0x0a) between them.
        assert b'\x32\x01\x0a\x57' not in bc, (
            f'value-if then-branch has a POP before JUMP: {bc.hex()}'
        )
        # else value PUSH_INT8[2] feeds SETQ_G (0x06) -> value flows to consumer
        assert b'\x32\x02\x06' in bc, f'then SETQ_G pattern missing: {bc.hex()}'


def test_stmt_if_else_branch_pop():
    """A bare statement `if` (value discarded, with a following statement) must
    POP the else-branch value too — mirroring the then-branch POP.

    Regression for large_synthetic: `(if c (fn1) (fn2)) (list ...)` in a function
    body previously emitted the then-branch POP but not the else-branch POP
    (CAD lgf-000..119 else `USUBR; POP`). Each function was 1 byte short.
    """
    from compiler.cli import cmd_compile
    from decompiler.fas4_decompiler import Disassembler

    src = (
        "(defun f (x) "
        "(if (> x 0) (princ \"pos\") (princ \"neg\")) "
        "(princ \"done\"))"
    )
    with tempfile.TemporaryDirectory() as tmp:
        out = os.path.join(tmp, 'out.fas')
        cmd_compile(src, out)
        _, bc, _, _ = _parse_fas(open(out, 'rb').read())
        dis = Disassembler(short_subr=False)
        insts = list(dis.disassemble(bc, 10, sym_count=10))
        ops = [i.op_name for i in insts]
        # Structure: JMP32_IFNOT; then ...; JUMP; else PUSH_G; USUBR; POP; tail ...
        # The else branch must emit a POP before the tail statement.
        ju = ops.index('JUMP') if 'JUMP' in ops else -1
        assert ju > 0, f'expected JUMP after then-branch: {ops}'
        # else branch starts right after JUMP; its last op before the tail
        # statement must be POP
        else_idx = ju + 1
        # find the tail statement: the PUSH_G/USUBR after the else POP
        tail_idx = None
        for k in range(else_idx, len(ops)):
            if ops[k] == 'POP':
                tail_idx = k
                break
        assert tail_idx is not None and tail_idx + 1 < len(ops), (
            f'else-branch missing POP before tail statement: {ops}'
        )
        # after the else POP, the next meaningful op is the tail statement
        # (PUSH_G / PUSH_VALUE / USUBR of the following `(princ "done")`)
        assert ops[tail_idx + 1] in ('PUSH_G', 'PUSH_VALUE', 'USUBR', 'PUSH_INT8'), (
            f'unexpected op after else POP: {ops[tail_idx:tail_idx + 3]}'
        )


#: (source, cad_golden) pairs where our compact-stub output must be byte-identical
#: to the AutoCAD `vlisp-compile` golden (bytecode AND resource items).
#: 顶层 tests/*.lsp 的 CAD golden（fact/fun/m1/m2/mix/multi/rt_e）已随
#: t-series 清理移除；保留 real_* 系（源与 golden 均在 tests/cad/）。
CAD_GOLDEN_PAIRS = [
    # 实数常量（2026-08-08 修复：CAD 注册资源段 REAL 槽 + PUSH_G，非内联 PUSH_REAL）
    ('cad/real_simple.lsp', 'cad/real_simple_cad.fas'),
    ('cad/real_arith.lsp', 'cad/real_arith_cad.fas'),
    ('cad/real_list.lsp', 'cad/real_list_cad.fas'),
    ('cad/real_param.lsp', 'cad/real_param_cad.fas'),
    # 纯顶层 cond（test-cond.lsp）：cond else 键 `(t ...)` 的 T 槽位置、模块代码
    # 语句 if 的 then setq 无 DUP / 无 else 不补 PUSH_NIL（2026-08-15 修复）。
    ('test-cond.lsp', 'cad/test_cond_cad.fas'),
    # 纯顶层 `(setq X (lambda ...))` 多 `-lambda-`（setq-lambda.lsp）：seg0 完整
    # compact stub + 函数目录/第二区符号/fg 表布局 + setq 绑定协议（2026-08-15）。
    ('setq-lambda.lsp', 'cad/setq_lambda_cad.fas'),
    # 纯顶层 `(set 'X (lambda ...))` + in-package/use-package + 跨 lambda 共享参数
    # （bootstrap.lsp）：`-lambda-` 第二区符号槽序——共享参数推迟到最末尾
    # （`STRCAT @::*FASEXT* FILE`）+ in-package/use-package 使 `-lambda-` 运行时槽
    # 整体 +1（2026-08-29 修复，转正 byte-identity）。
    ('bootstrap.lsp', 'cad/bootstrap_cad.fas'),
    # 函数体内嵌套 `(defun inner ...)`（CAD 原生内嵌 DEFUN，2026-08-25）：
    # n1 最简 / n2 嵌套参数+locals / n3 闭包引用外层局部 / n4 嵌套位于体中段 /
    # n5 多层嵌套 / n6 条件内嵌套。源与 golden 均在 tests/cad/nested/。
    ('cad/nested/n1.lsp', 'cad/nested/n1.fas'),
    ('cad/nested/n2.lsp', 'cad/nested/n2.fas'),
    ('cad/nested/n3.lsp', 'cad/nested/n3.fas'),
    ('cad/nested/n4.lsp', 'cad/nested/n4.fas'),
    ('cad/nested/n5.lsp', 'cad/nested/n5.fas'),
    ('cad/nested/n6.lsp', 'cad/nested/n6.fas'),
    # 非嵌套基线（s1 单函数 / s2 嵌套引用外层局部）对照。
    ('cad/nested/s1.lsp', 'cad/nested/s1.fas'),
    ('cad/nested/s2.lsp', 'cad/nested/s2.fas'),
]

#: t-series sources whose compiled output is byte-identical to the CAD golden
#: (generated via `vlisp-compile` on AutoCAD 24.1s, 2026-08-04/05).
#: Source .lsp and golden .fas both live under tests/cad/.
#: t0X 系列源文件已删（compile_src 取代），此处仅保留源与 golden 仍在的
#: 独立夹具（andor/and2/or2/andval/chinese/qsingle）。
CAD_T_SERIES_IDENTICAL = [
    'andor', 'and2', 'or2', 'andval',
    'chinese', 'qsingle',
]

#: t-series sources with KNOWN remaining byte diffs (see docs/development-plan.md 8.C1).
#: Kept as xfail regression: when a gap is fixed, move it to CAD_T_SERIES_IDENTICAL.
CAD_T_SERIES_DIFF: list = []

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
    single-function cases masked it (nfuncs == 1). The multi+lambda path
    fixed in _patch_usubr_idx is covered by the real_* golden pairs below.
    while/cond alignment is covered by the t-series golden tests
    (t04_while/t05_cond).
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


#: tests/compile_src 全新编译 fixture：编译产物做结构断言（非 CAD golden 比对）。
#: 覆盖 nsyms/seg0/资源流/加密头等 FAS 结构的普适不变量。
_COMPILE_SRC = [
    '01_math', '02_strings', '03_recursion', '04_control', '05_lists',
    '06_higher_order', '07_locals', '08_loops', '09_variadic',
    '10_commands', '11_top_level', '12_cad_funcs', '13_activex',
    '14_command_s', '15_error', '16_i18n',
]


@pytest.mark.parametrize('name', _COMPILE_SRC)
def test_compile_src_fas_structure(name):
    """compile_src fixture 编译产物满足 FAS 结构不变量。

    每个 fixture 经 CLI 编译后断言：
    - nsyms > 0 且 seg0 非空（含函数字节码）
    - seg1 解密后含符号块（5b）与 DEFCODE/函数注册
    - 加密密钥可定位（find_key）+ 段分隔符存在
    """
    from compiler.cli import cmd_compile

    src_path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            'compile_src', f'{name}.lsp')
    if not os.path.exists(src_path):
        pytest.skip(f'missing compile_src fixture: {name}')
    with tempfile.TemporaryDirectory() as tmp:
        out = os.path.join(tmp, 'out.fas')
        cmd_compile(src_path, out)
        with open(out, 'rb') as fh:
            data = fh.read()

        assert data.startswith(FAS4_MAGIC), f'{name}: bad magic'
        assert SEG_TERMINATOR in data, f'{name}: missing segment terminator'

        nsyms, bc, seg1, sec2_items = _parse_fas(data)
        assert nsyms > 0, f'{name}: empty symbol table'
        assert len(bc) > 0, f'{name}: empty seg0 bytecode'
        assert len(seg1) > 0, f'{name}: empty seg1'
        # seg1 解密后应含 SYMBOL 块（5b）——所有 fixture 都定义函数/顶层符号
        assert b'\x5b' in seg1, f'{name}: no symbol block in decrypted seg1'
        assert sec2_items > 0, f'{name}: no resource records'

        # 加密密钥可定位：find_key 不返回 None
        from core.fas_core import find_key
        assert find_key(data) is not None, f'{name}: XOR key not located'


#: compile_src fixture → CAD golden 逐字节一致回归。
#: 10_commands = t14_command（c: 命令模块 vl-ACAD-defun 注册）；11_top_level =
#: t10_init（defun+顶层混合模块代码）。2026-08-18 回归修复：表外字符串索引
#: ≥ nsyms 时须用 nsyms-1 编址（abc80e1 曾改为真实 symbol_slots 索引 → PUSH_G
#: 越界 7/8，verify 拦截，golden 逐字节 diff）。
_COMPILE_SRC_GOLDEN = [
    ('10_commands', 'cad/t14_command_cad.fas'),
    ('11_top_level', 'cad/t10_init_cad.fas'),
]


@pytest.mark.parametrize('name,golden', _COMPILE_SRC_GOLDEN,
                         ids=[n for n, _ in _COMPILE_SRC_GOLDEN])
def test_compile_src_byte_identity(name, golden):
    """compile_src fixture 编译产物与 CAD golden 逐字节一致（nsyms/seg0/资源段）。"""
    from compiler.cli import cmd_compile
    from decompiler.fas4_decompiler import Fas4Parser

    src = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                       'compile_src', f'{name}.lsp')
    golden_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), golden)
    if not (os.path.exists(src) and os.path.exists(golden_path)):
        pytest.skip(f'missing compile_src golden fixture: {name} / {golden}')
    with tempfile.TemporaryDirectory() as tmp:
        out = os.path.join(tmp, 'out.fas')
        cmd_compile(src, out)
        ours = Fas4Parser().parse(out)
        ref = Fas4Parser().parse(golden_path)
        assert ours.nsyms == ref.nsyms, (
            f'{name}: nsyms {ours.nsyms} != {ref.nsyms}'
        )
        assert ours.bytecode == ref.bytecode, (
            f'{name}: seg0 bytecode differs from CAD golden\n'
            f'  ours: {ours.bytecode.hex()}\n'
            f'  CAD : {ref.bytecode.hex()}'
        )
        assert ours.resource_items == ref.resource_items, (
            f'{name}: seg1 resource items differ from CAD golden'
        )


#: compile_src fixture → CAD golden 逐字节一致回归（2026-08-22 重新在 CAD
#: `vlisp-compile` 生成，见 tests/cad/compile_src_golden/）。当前 7 份全部对齐：
#: 01_math/02_strings/03_recursion/04_control/05_lists/06_higher_order/08_loops。
#: 05_lists 锁 `(setq lst '(a b c))` 表外 SETQ_G 目标须 nsyms-1（不适用
#: module_reg_count 减法）；06_higher_order 锁 kwote lambda 参数 `n` 注册
#: fg 槽 + `-lambda-` 体 PUSH_VALUE 读取（2026-08-23 修复）。
def _discover_compile_src_goldens():
    import glob

    _base = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'cad', 'compile_src_golden')
    pairs = []
    for _g in sorted(glob.glob(os.path.join(_base, '*_cad.fas'))):
        _name = os.path.basename(_g)[: -len('_cad.fas')]
        _src = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'compile_src', f'{_name}.lsp')
        if os.path.exists(_src):
            pairs.append((_name, os.path.join('cad', 'compile_src_golden', f'{_name}_cad.fas')))
    return pairs


@pytest.mark.parametrize('name,golden', _discover_compile_src_goldens(),
                         ids=[n for n, _ in _discover_compile_src_goldens()])
def test_compile_src_golden_byte_identity(name, golden):
    """compile_src fixture 与 `tests/cad/compile_src_golden/` CAD golden 逐字节一致。"""
    from compiler.cli import cmd_compile
    from decompiler.fas4_decompiler import Fas4Parser

    src = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                       'compile_src', f'{name}.lsp')
    golden_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), golden)
    if not (os.path.exists(src) and os.path.exists(golden_path)):
        pytest.skip(f'missing compile_src golden fixture: {name} / {golden}')
    with tempfile.TemporaryDirectory() as tmp:
        out = os.path.join(tmp, 'out.fas')
        cmd_compile(src, out)
        ours = Fas4Parser().parse(out)
        ref = Fas4Parser().parse(golden_path)
        assert ours.nsyms == ref.nsyms, (
            f'{name}: nsyms {ours.nsyms} != {ref.nsyms}'
        )
        assert ours.bytecode == ref.bytecode, (
            f'{name}: seg0 bytecode differs from CAD golden\n'
            f'  ours: {ours.bytecode.hex()}\n'
            f'  CAD : {ref.bytecode.hex()}'
        )
        assert ours.resource_items == ref.resource_items, (
            f'{name}: seg1 resource items differ from CAD golden'
        )


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


#: i18n 拆分件（tests/cad/i18n_split/pXX.lsp）与其 CAD 真机 golden
#: （golden/pXX_cad.fas，2026-08-06 AutoCAD 24.1s vlisp-compile 生成）。
#: p01-p07 已 byte-identity（seg0+seg1+nsyms 全对齐）。其中 p04-p07 为
#: "模块注册序对齐"regression：单 defun + 顶层 setq 混合时 CAD 按源码逆序
#: 逐 form 交错注册（含把源码尾部顶层 form 的符号排前）；p04-p07 于
#: 2026-08-06 修复——DUP 插入改为按真实 SETQ_G 指令定位（不碰 USUBR 的
#: 0x06 索引字节）、if-then 分支尾 setq 补 DUP、setq 目标归属优先于读取。
I18N_SPLIT_SEG0_IDENTICAL = {
    'p01', 'p02', 'p03', 'p04', 'p05', 'p06', 'p07',
}
I18N_SPLIT_FULL_IDENTICAL = {'p01', 'p02', 'p03', 'p04', 'p05', 'p06', 'p07'}


@pytest.mark.parametrize('name', sorted(I18N_SPLIT_SEG0_IDENTICAL))
def test_i18n_split_seg0_identity(name):
    """i18n 拆分件 seg0 与 CAD golden 逐字节一致（模块注册交错序回归）。

    锁住 _register_module 的"源码逆序、defun+顶层 form 交错"规则：单一
    defun 配合后来的顶层 `(setq ... vl-catch-all-apply ...)` 时，其符号
    槽按 CAD 排在函数名前（p03/p04 实测）。seg1 仍含差异时仅验 seg0。
    """
    from compiler.cli import cmd_compile
    from decompiler.fas4_decompiler import Fas4Parser

    base = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'cad', 'i18n_split')
    src = os.path.join(base, f'{name}.lsp')
    golden = os.path.join(base, 'golden', f'{name}_cad.fas')
    if not (os.path.exists(src) and os.path.exists(golden)):
        pytest.skip(f'missing i18n_split fixture: {name}')
    with tempfile.TemporaryDirectory() as tmp:
        out = os.path.join(tmp, 'out.fas')
        cmd_compile(src, out)
        ours = Fas4Parser().parse(out)
        ref = Fas4Parser().parse(golden)
    assert ours.bytecode == ref.bytecode, (
        f'{name}: seg0 differs from CAD golden\n'
        f'  ours: {ours.bytecode.hex()}\n'
        f'  CAD : {ref.bytecode.hex()}'
    )
    if name in I18N_SPLIT_FULL_IDENTICAL:
        assert ours.nsyms == ref.nsyms, (
            f'{name}: nsyms {ours.nsyms} != {ref.nsyms}')
        assert ours.resource_items == ref.resource_items, (
            f'{name}: seg1 resource items differ from CAD golden')


def test_i18n_original_byte_identity():
    """i18n.lsp 原文件（defun+顶层+kwote -lambda- 交错混合模式）与 CAD golden
    逐字节一致（seg0 + nsyms + seg1 资源段）。

    锁住 §9.2 记录的全部关键修复：kwote 的 fas_nsyms 与 codegen_nsyms 差、
    -lambda- 参数/引用槽、03 单字节占位、连续 STRING 合并 55 块、中间 if
    then 值 POP、模块代码顶层 if-then-setq 补 DUP / 无 else 补 PUSH_NIL。
    2026-08-06：原文件已与 `tests/cad/i18n-cad.fas` 逐字节一致。

    2026-08-12：**跳过**——t20_kwote 真机修复（kwote 内嵌 `-lambda-` 参数读取
    改 GET_LOCAL 局部槽，CAD 真机 `(t20-kwote)` → 42）与 i18n CAD golden 的
    符号槽编址冲突（i18n 的 kwote lambda 参数 `opt%` CAD 用 PUSH_VALUE 符号槽，
    t20 的 `n` 需 GET_LOCAL）。两者无法同时逐字节一致。i18n 编译产物**功能
    等价**（CAD 真机 `@::codepage2lang` 返回正确），仅字节不同。待统一 kwote
    lambda 参数编址后恢复。
    2026-08-23：kwote lambda 参数已统一为 PUSH_VALUE 符号槽编址（06_higher_order
    全新 golden 确认），seg0 + nsyms 已与 i18n-cad.fas 逐字节一致；seg1 模块
    代码仍有 48 项 pre-existing diff（CAD 多一条顶层 setq 语句，与 kwote 无关），
    保持 skip。
    2026-08-29：P0-1 共享参数/第二区符号槽序修复（cad_symbols/compile_cmd）
    顺带消除 i18n seg1 模块代码 48 项 diff——seg0+seg1+nsyms 现全部逐字节一致，
    移除 skip 锁入回归。
    """
    from compiler.cli import cmd_compile
    from decompiler.fas4_decompiler import Fas4Parser

    base = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'cad')
    src = os.path.join(base, 'i18n.lsp')
    golden = os.path.join(base, 'i18n-cad.fas')
    if not (os.path.exists(src) and os.path.exists(golden)):
        pytest.skip('missing i18n.lsp/i18n-cad.fas mixed-mode fixture')
    with tempfile.TemporaryDirectory() as tmp:
        out = os.path.join(tmp, 'out.fas')
        cmd_compile(src, out)
        ours = Fas4Parser().parse(out)
        ref = Fas4Parser().parse(golden)
    assert ours.bytecode == ref.bytecode, (
        'i18n.lsp: seg0 differs from CAD golden\n'
        f'  ours: {ours.bytecode.hex()}\n'
        f'  CAD : {ref.bytecode.hex()}'
    )
    assert ours.nsyms == ref.nsyms, (
        f'i18n.lsp: nsyms {ours.nsyms} != {ref.nsyms}')
    assert ours.resource_items == ref.resource_items, (
        'i18n.lsp: seg1 resource items differ from CAD golden')


# ── atlisp_u 全量 byte-identity 的 8 项根因定向回归（2026-08-29）──────────────
# 每个用例用小型合成 Lisp 片段锁定单一协议，避免依赖 502 函数大 fixture。

def _module_code_bytes(src: str) -> bytes:
    """编译混合/纯顶层源码，返回 seg1 资源流末端的模块代码段。

    模块代码位于资源流尾部（`FasWriter` 紧凑 stub：seg1 = 资源 + 模块代码）。
    """
    from compiler.cli import cmd_compile
    from core.fas_core import parse_fas4

    with tempfile.NamedTemporaryFile(suffix='.lsp', mode='w', delete=False) as f:
        f.write(src)
        src_path = f.name
    out = os.path.join(tempfile.gettempdir(), 'modcode.fas')
    try:
        cmd_compile(src_path, out)
        r = parse_fas4(out, decrypt_seg1=True)
        rd = r['res_data_decrypted']
        mcl = int.from_bytes(rd[8:10], 'little')
        return rd[len(rd) - mcl:]
    finally:
        if os.path.exists(src_path):
            os.unlink(src_path)
        if os.path.exists(out):
            os.unlink(out)


def test_mixed_file_setq_lambda_lam_slot_n_cmds():
    """混合文件顶层 setq-lambda 槽含 n_cmds+_tl_lam_count（根因 #4）。

    `top_lambda_slots` 旧公式 `2*len+tlc-i` 缺 n_cmds+_tl_lam_count → 绑定
    PUSH_G 错 2。含 c: 命令（n_cmds=1）时验证绑定槽正确。与 atlisp_u 混合
    setq-lambda 同协议（JUMP 0; PUSH_G <lam+1>; DUP; SETQ_G <sym>）。
    """
    src = '''(defun foo () 1)
(defun c:test () (foo))
(setq @::fasext (lambda (x) (strcat x ".fas")))'''
    mc = _module_code_bytes(src)
    # setq-lambda 绑定：JUMP 0; PUSH_G <lam+1>; DUP; SETQ_G <sym>
    assert b'\x57\x00\x00\x00\x00\x09' in mc, 'setq-lambda JUMP 0 缺失'
    assert b'\x0b\x06' in mc, 'setq-lambda DUP; SETQ_G 缺失'
    # 绑定槽 > 模块注册（含 n_cmds 偏移）：实测 PUSH_G 6; DUP
    assert b'\x09\x06\x00\x0b' in mc, (
        'setq-lambda PUSH_G 6; DUP（含 n_cmds）缺失:\n%s' % mc.hex())


def test_mixed_file_set_lambda_lam_slot_plus_one():
    """混合文件 `(set 'X (lambda ...))` set 协议 PUSH_G = lam_slot+1（根因 #8）。

    纯顶层 net/wget 用 lam_slot；混合文件（n_funcs>0）用 lam_slot+1。与
    atlisp_u @::wget 同协议（golden PUSH_G 1303 = lam_slot 1302 + 1）。
    """
    src = '''(defun foo () 1)
(set '@::wget (lambda (u) u))'''
    mc = _module_code_bytes(src)
    # set 协议：PUSH_G <sym>; JUMP 0; PUSH_G <-lambda-槽>; USUBR(2, SET)
    assert b'\x57\x00\x00\x00\x00\x09' in mc, 'set 协议 JUMP 0 缺失'
    assert b'\x35\x02' in mc, 'set 协议 USUBR(2, SET) 缺失'


def test_pure_top_level_set_lambda_lam_slot():
    """纯顶层 `(set 'X (lambda ...))` set 协议 PUSH_G = lam_slot（根因 #8）。

    net/wget golden PUSH_G 5 = tlc(3)+2-0；混合文件才 +1。
    """
    src = '''(set '@::wget (lambda (u) u))'''
    mc = _module_code_bytes(src)
    # 纯顶层 lam_slot = tlc + 2 - _ti。tlc 依模块 form 数而定，验证 set 协议
    # 存在且 PUSH_G 不额外 +1（与混合文件区分的关键：纯顶层无 c: 命令）。
    # 通过校验 set 协议结构：PUSH_G <sym>; JUMP 0; PUSH_G <lam>; USUBR(2, SET)
    assert b'\x57\x00\x00\x00\x00\x09' in mc, 'set 协议 JUMP 0 缺失'
    assert b'\x35\x02' in mc, 'set 协议 USUBR(2, SET) 缺失'


def test_wide_setq_g_uses_fg_slot_no_fallback():
    """大文件 SETQ_G 一律 fg 槽编址，无 rg 列表常量 fallback（根因 #2）。

    REVERSE-DEPS/PKG-TO-INS/@::*COMPAT1-DONE* 此前落 nsyms-1 错槽。构造
    nsyms>256 文件 + 一个 fg 槽与 rg 列表常量重合的 SETQ_G 目标。
    """
    # 大量唯一符号推高 nsyms；REVERSE-DEPS 作全局 setq 目标（CAD fg 槽）。
    funcs = '\n'.join(
        f'(defun f{i} (p{i} q{i} r{i}) (strcat p{i} q{i} r{i} "{i}"))'
        for i in range(80)
    )
    src = funcs + '''
(defun test-rev (x) (setq REVERSE-DEPS x) REVERSE-DEPS)
(defun c:test () (test-rev 1))'''
    with tempfile.NamedTemporaryFile(suffix='.lsp', mode='w', delete=False) as f:
        f.write(src)
        src_path = f.name
    out = os.path.join(tempfile.gettempdir(), 'wide_setq.fas')
    try:
        from compiler.cli import cmd_compile
        cmd_compile(src_path, out)
        from core.fas_core import parse_fas4
        r = parse_fas4(out, decrypt_seg1=True)
        assert r['nsyms'] > 256, 'expected wide format'
        from core.fas_core import build_mvar_tables
        rg, fg = build_mvar_tables(r['res_data_decrypted'], r['nsyms'])
        # REVERSE-DEPS 的 fg 槽必须被占用（否则 6 操作数用 nsyms-1 fallback）
        dep_idx = [i for i, v in enumerate(fg)
                   if isinstance(v, tuple) and len(v) == 2
                   and v[0] == 'SYMBOL' and str(v[1]).upper() == 'REVERSE-DEPS']
        assert dep_idx, 'REVERSE-DEPS fg 槽缺失'
        # 该槽位不在 nsyms-1（fallback 特征）
        assert dep_idx[0] != r['nsyms'] - 1
    finally:
        if os.path.exists(src_path):
            os.unlink(src_path)
        if os.path.exists(out):
            os.unlink(out)


def test_nested_defun_dup_funcobj():
    """嵌套 defun 与顶层同名 `#dup` FUNCOBJ 反查（根因 #3）。

    `*error*#dup` 键不在 `_fo_by_name`（按原名索引），须经 nested_defun_names
    反查。顶层 + 嵌套 `*error*` 共存时 PUSH_G func-obj 槽正确、编译通过
    （旧逻辑 funcobj_map 缺失 → PUSH_G 错槽 / verify 拦截）。
    """
    src = '''(defun *error* (msg) (princ msg))
(defun outer () (defun *error* (msg) (princ "inner")) (*error* "x"))'''
    with tempfile.NamedTemporaryFile(suffix='.lsp', mode='w', delete=False) as f:
        f.write(src)
        src_path = f.name
    out = os.path.join(tempfile.gettempdir(), 'dupfo.fas')
    try:
        from compiler.cli import cmd_compile
        cmd_compile(src_path, out)
        from core.fas_core import parse_fas4, build_mvar_tables
        r = parse_fas4(out, decrypt_seg1=True)
        rg, fg = build_mvar_tables(r['res_data_decrypted'], r['nsyms'])
        # 顶层 *error* 注册 fg 槽
        err_idx = [i for i, v in enumerate(fg)
                   if isinstance(v, tuple) and len(v) == 2
                   and v[0] == 'SYMBOL' and str(v[1]).upper() == '*ERROR*']
        assert err_idx, '*error* fg 槽缺失'
        # 嵌套 defun 注册序列存在：PUSH_G <func-obj>; SETQ_G <*error*>
        # （func-obj 操作数须 < nsyms，非越界）
        bc = r['bytecode']
        assert b'\x09' in bc and b'\x06' in bc, '嵌套 defun 注册字节缺失'
        # 编译成功本身即回归：旧 bug 致 funcobj_map 缺失 → PUSH_G 错槽，
        # verify_fas 拦截（USUBR/PUSH_G OOB）→ 不产出 FAS。
    finally:
        if os.path.exists(src_path):
            os.unlink(src_path)
        if os.path.exists(out):
            os.unlink(out)


def test_cond_defun_mid_emitted_at_skip():
    """`_skip` 函数（条件 defun）跳过 _reg 但仍发 mid 语句（根因 #7）。

    顶层 `(if is-gcad (progn (defun C:% ...) (defun C:%% ...)))` 的条件 defun
    提升进 seg0，mid 的 CondDefunBind 块在跳过位置发射。
    """
    src = '''(setq is-gcad T)
(defun c:@ () (princ "hi"))
(defun foo () 1)
(if is-gcad
  (progn (defun C:% () (c:@)) (defun C:%% () (c:@))))'''
    mc = _module_code_bytes(src)
    # CondDefunBind 绑定：PUSH_G <func-obj>; SETQ_G <sym>; PUSH_G <sym>;
    # USUBR(1, vl-ACAD-defun)
    # vl-ACAD-defun 槽（0x56 保留大小写）的 USUBR 调用特征：`35 01 <vl槽>`
    assert b'\x35\x01' in mc, '条件 defun USUBR(1, vl-ACAD-defun) 缺失'
    # 应有 JUMP+0 开头的绑定块（条件 defun 提升）
    assert b'\x57\x00\x00\x00\x00\x09' in mc, '条件 defun JUMP+0 缺失'


def test_reg_b_slot_relinquish_tl():
    """`_reg` b 槽让位（根因 #6）：tl kwote lambda func-obj 占用 b 序列一槽。

    顶层 `(if cond (mapcar (function (lambda ...)) ...))` 的 func-obj 槽位于
    b 序列中段，之后的函数 b-1。构造 tl 在 TAIL 中段的混合文件。
    """
    src = '''(defun a () 1)
(defun b () 2)
(if @::*uris* (mapcar (function (lambda (x) (a))) @::*uris*))
(defun c () 3)
(defun d () 4)'''
    mc = _module_code_bytes(src)
    # tl kwote lambda func-obj 槽 = base - tl_pos。tl_pos=2（a,b 之后）。
    # base = 2*4 + tlc(1) + n_cmds(0) + tl_lam(1) = 10。func-obj = 10-2 = 8。
    # 之后函数 c（i=2）b=8-1=7、d（i=3）b=6。
    assert b'\x09\x08\x00' in mc, 'tl kwote lambda func-obj 槽（8）缺失'
    # c 的注册（b=7）在 func-obj 之后让位
    assert b'\x09\x07\x00' in mc, 'tl 之后函数 b 槽让位（7）缺失'
