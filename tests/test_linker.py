"""Tests for the FAS4 linker — merging multiple .fas files."""
import os
import tempfile
from compiler.linker import link_fas
from compiler.cli import cmd_compile as compile_lsp
from fas4_decompiler import Fas4Parser, Disassembler, ControlFlowAnalyzer, LispGenerator, is_compact_stub


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
