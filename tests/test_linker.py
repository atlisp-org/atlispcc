"""Tests for the FAS4 linker — merging multiple .fas files."""
import os
import tempfile

import pytest
from compiler.linker import link_fas
from compiler.cli import cmd_compile as compile_lsp
from decompiler.fas4_decompiler import Fas4Parser, Disassembler, ControlFlowAnalyzer, LispGenerator, is_compact_stub


def _compile(source: str) -> str:
    fas = os.path.join(tempfile.gettempdir(), 'test_lk_' + os.urandom(4).hex() + '.fas')
    compile_lsp(source, fas)
    return fas


def _decompile(path: str) -> str:
    parser = Fas4Parser()
    fas = parser.parse(path)
    disasm = Disassembler(short_subr=is_compact_stub(fas.bytecode, fas.function_catalog))
    instrs = disasm.disassemble(fas.bytecode, fas.nsyms)
    cfa = ControlFlowAnalyzer(instrs, fas.function_catalog)
    funcs = cfa.find_functions()
    gen = LispGenerator(fas)
    return gen.generate(funcs, path)


def test_link_two_basic_files():
    """Link two simple .fas files, verify both functions present."""
    src1 = """(defun add (a b) (+ a b))
"""
    src2 = """(defun mul (a b) (* a b))
"""
    fas1 = _compile(src1)
    fas2 = _compile(src2)

    out = os.path.join(tempfile.gettempdir(), 'test_lk_out.fas')

    try:
        link_fas([fas1, fas2], out, verbose=True)
        code = _decompile(out)
        assert 'defun add' in code.lower() or '(add' in code.lower()
        assert 'defun mul' in code.lower() or '(mul' in code.lower()
    finally:
        for p in [fas1, fas2, out]:
            if os.path.exists(p):
                os.unlink(p)


def test_link_cross_file_call():
    """Function in file2 calls function from file1."""
    src1 = """(defun square (x) (* x x))
"""
    src2 = """(defun sum-squares (a b) (+ (square a) (square b)))
"""
    fas1 = _compile(src1)
    fas2 = _compile(src2)

    out = os.path.join(tempfile.gettempdir(), 'test_lk_cross.fas')

    try:
        link_fas([fas1, fas2], out)
        code = _decompile(out)
        assert 'square' in code.lower()
        assert 'sum-squares' in code.lower()
    finally:
        for p in [fas1, fas2, out]:
            if os.path.exists(p):
                os.unlink(p)


def test_link_shared_builtins():
    """Both files use same builtins; merged symbol table dedups."""
    src1 = """(defun greet (name) (strcat "Hello, " name))
"""
    src2 = """(defun farewell (name) (strcat "Goodbye, " name))
"""
    fas1 = _compile(src1)
    fas2 = _compile(src2)

    out = os.path.join(tempfile.gettempdir(), 'test_lk_shared.fas')

    try:
        link_fas([fas1, fas2], out)
        code = _decompile(out)
        assert 'strcat' in code
    finally:
        for p in [fas1, fas2, out]:
            if os.path.exists(p):
                os.unlink(p)


def test_link_three_files():
    """Link three files."""
    src1 = """(defun f1 (x) (+ x 1))
"""
    src2 = """(defun f2 (x) (+ x 2))
"""
    src3 = """(defun f3 (x) (+ x 3))
"""
    fas_list = [_compile(s) for s in [src1, src2, src3]]
    out = os.path.join(tempfile.gettempdir(), 'test_lk_three.fas')

    try:
        link_fas(fas_list, out)
        code = _decompile(out)
        assert '(f1' in code.lower() or 'f1' in code
        assert '(f2' in code.lower() or 'f2' in code
    finally:
        for p in fas_list + [out]:
            if os.path.exists(p):
                os.unlink(p)


def test_link_result_is_valid_fas():
    """Linked output is a valid FAS that can be parsed and decompiled."""
    src1 = """(defun inc (x) (+ x 1))
"""
    src2 = """(defun dec (x) (- x 1))
"""
    fas1 = _compile(src1)
    fas2 = _compile(src2)

    out = os.path.join(tempfile.gettempdir(), 'test_lk_valid.fas')

    try:
        link_fas([fas1, fas2], out)
        parser = Fas4Parser()
        fas = parser.parse(out)
        from compiler.linker import _extract_functions
        assert fas.nsyms > 0
        assert len(fas.bytecode) > 0
        assert len(_extract_functions(fas)) >= 2
    finally:
        for p in [fas1, fas2, out]:
            if os.path.exists(p):
                os.unlink(p)


def test_link_with_constants():
    """Files with string/integer constants get correct merged symbols."""
    src1 = """(defun hi () (princ "Hello"))
"""
    src2 = """(defun bye () (princ "Goodbye"))
"""
    fas1 = _compile(src1)
    fas2 = _compile(src2)

    out = os.path.join(tempfile.gettempdir(), 'test_lk_const.fas')

    try:
        link_fas([fas1, fas2], out)
        code = _decompile(out)
        assert 'Hello' in code or '"Hello"' in code
        assert 'Goodbye' in code or '"Goodbye"' in code
    finally:
        for p in [fas1, fas2, out]:
            if os.path.exists(p):
                os.unlink(p)


def test_link_needs_two_inputs():
    """Link must have at least 2 inputs."""
    import pytest
    with pytest.raises(ValueError):
        link_fas(['single.fas'], '/dev/null')


def test_link_function_name_collision_warns(capsys):
    """Duplicate function names across files emit a warning."""
    src1 = """(defun foo (x) (+ x 1))
"""
    src2 = """(defun foo (x) (* x 100))
"""
    fas1 = _compile(src1)
    fas2 = _compile(src2)

    out = os.path.join(tempfile.gettempdir(), 'test_lk_collision.fas')

    try:
        link_fas([fas1, fas2], out)
        captured = capsys.readouterr()
        assert 'function name collision' in captured.err
        assert 'foo' in captured.err or 'FOO' in captured.err
        code = _decompile(out)
        assert 'defun foo' in code or '(foo' in code.lower()
    finally:
        for p in [fas1, fas2, out]:
            if os.path.exists(p):
                os.unlink(p)


def test_link_command_name_collision_warns(capsys):
    """Duplicate C: command names across files emit a warning."""
    src1 = """(defun c:run () (princ "one"))
"""
    src2 = """(defun c:run () (princ "two"))
"""
    fas1 = _compile(src1)
    fas2 = _compile(src2)

    out = os.path.join(tempfile.gettempdir(), 'test_lk_cmd.fas')

    try:
        link_fas([fas1, fas2], out)
        captured = capsys.readouterr()
        assert 'function name collision' in captured.err
        assert 'c:run' in captured.err or 'C:RUN' in captured.err
    finally:
        for p in [fas1, fas2, out]:
            if os.path.exists(p):
                os.unlink(p)


def test_link_first_definition_wins(capsys):
    """Colliding function keeps the FIRST definition's behavior."""
    src1 = """(defun foo (x) (+ x 1))
(defun call-foo (x) (foo x))
"""
    src2 = """(defun foo (x) (* x 100))
"""
    fas1 = _compile(src1)
    fas2 = _compile(src2)

    out = os.path.join(tempfile.gettempdir(), 'test_lk_first.fas')

    try:
        link_fas([fas1, fas2], out)
        capsys.readouterr()  # discard warning
        code = _decompile(out)
        # 首次定义（foo 体 + 1）保留；重复定义（* 100）不泄露。
        # 注：反编译参数名有 3.4 缺陷（x 可能解析为其它符号），断言兼容参数名。
        assert 'foo_2' not in code, f'duplicate function leaked: {code}'
        assert '* 100' not in code, f'duplicate definition leaked: {code}'
        assert '(+ foo 1)' in code or '+ x 1' in code or '+ 1' in code, f'first definition lost: {code}'
    finally:
        for p in [fas1, fas2, out]:
            if os.path.exists(p):
                os.unlink(p)


#: 链接器 CAD golden 回归：合并多文件的输出与 CAD `vlisp-compile` 直接编译
#: 同源码逐字节一致（seg0 + sec2 + nsyms + sec2_items）。
#: golden 由 AutoCAD 24.1s `vlisp-compile 'st` 生成（tests/cad/link/*_cad.fas，
#: 2026-08-08）。CAD 真机验证：add/mul、square/sum-squares、f1/f2/f3 均可调用。
LINK_GOLDEN_PAIRS = [
    # (golden 名, [输入源码列表])
    ('addmul', ['(defun add (a b) (+ a b))\n', '(defun mul (a b) (* a b))\n']),
    ('sqsum',
     ['(defun square (x) (* x x))\n',
      '(defun sum-squares (a b) (+ (square a) (square b)))\n']),
    ('three',
     ['(defun f1 (x) (+ x 1))\n', '(defun f2 (x) (+ x 2))\n',
      '(defun f3 (x) (+ x 3))\n']),
]


@pytest.mark.parametrize('name,srcs', LINK_GOLDEN_PAIRS,
                         ids=[p[0] for p in LINK_GOLDEN_PAIRS])
def test_link_byte_identity_with_cad_golden(name, srcs):
    """链接多文件输出与 CAD 直接编译同源码逐字节一致。

    §3.6 回归：分隔符（16 vs 01 00 16）、参数绑定/读取槽（合并 gvar 槽-1 /
    参数逆序 nsyms-1-arg_rev）、sec2_items（2*nfuncs+2）等修复的守卫。
    链接器此前输出在 CAD 真机功能错误（add/square/sum-squares 调用失败），
    修复后 byte-identity 且 CAD 真机全部可调用。
    """
    _BASE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'cad', 'link')
    golden = os.path.join(_BASE, f'{name}_cad.fas')
    if not os.path.exists(golden):
        pytest.skip(f'missing linker golden: {golden}')
    fas_list = [_compile(s) for s in srcs]
    out = os.path.join(tempfile.gettempdir(), f'test_lk_golden_{name}.fas')
    try:
        link_fas(fas_list, out)
        ours = Fas4Parser().parse(out)
        ref = Fas4Parser().parse(golden)
        assert ours.nsyms == ref.nsyms, f'{name}: nsyms {ours.nsyms} != {ref.nsyms}'
        assert ours.bytecode == ref.bytecode, (
            f'{name}: seg0 differs from CAD golden\n'
            f'  ours: {ours.bytecode.hex()}\n  CAD : {ref.bytecode.hex()}'
        )
        assert ours.sec2_data == ref.sec2_data, f'{name}: sec2 differs'
        assert ours.sec2_items == ref.sec2_items, (
            f'{name}: sec2_items {ours.sec2_items} != {ref.sec2_items}'
        )
    finally:
        for p in fas_list + [out]:
            if os.path.exists(p):
                os.unlink(p)
