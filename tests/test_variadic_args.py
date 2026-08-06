import os
import sys
import tempfile

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from compiler.cli import cmd_compile
from decompiler.fas4_decompiler import (
    ControlFlowAnalyzer,
    Disassembler,
    Fas4Parser,
    LispGenerator,
    is_compact_stub,
)


def _decompile(src: str) -> str:
    d = tempfile.mkdtemp()
    fas = os.path.join(d, "t.fas")
    cmd_compile(src, fas)
    parsed = Fas4Parser().parse(fas)
    disasm = Disassembler(short_subr=is_compact_stub(parsed.bytecode, parsed.function_catalog))
    instructions = disasm.disassemble(parsed.bytecode, parsed.nsyms)
    funcs = ControlFlowAnalyzer(instructions, parsed.function_catalog).find_functions()
    return LispGenerator(parsed).generate(funcs, fas)


def test_optional_args_markup():
    out = _decompile("(defun f (a &optional b) (list a b))")
    assert "&optional" in out
    assert "(defun f (" in out


def test_rest_args_markup():
    out = _decompile("(defun g (a &rest r) (list a r))")
    assert "&rest" in out
    assert "(defun g (" in out


def test_rest_param_name_recovered_single():
    out = _decompile("(defun foobar (a &rest n) (apply '+ (cons a n)))")
    assert "(defun foobar (a &rest n)" in out
    assert "arg_" not in out


def test_rest_only_markup():
    out = _decompile("(defun sum (&rest n) n)")
    assert "&rest" in out
    assert "(defun sum (" in out


def test_optional_and_rest_markup():
    out = _decompile("(defun h (a &optional b &rest r) (list a b r))")
    assert "&optional" in out and "&rest" in out
    assert "(defun h (a &optional b &rest r)" in out


def test_optional_param_name_recovered_single():
    out = _decompile("(defun g (a &optional b) (list a b))")
    assert "(defun g (a &optional b)" in out
    assert "arg_" not in out


def test_plain_args_no_markup():
    out = _decompile("(defun p (a b) (+ a b))")
    assert "&optional" not in out
    assert "&rest" not in out


def test_multiple_optional_params():
    out = _decompile("(defun f (a &optional b c) (list a b c))")
    assert "(defun f (a &optional b c)" in out
    assert "arg_" not in out


def test_optional_only_no_required():
    out = _decompile("(defun f (&optional a b) (list a b))")
    assert "(defun f (&optional a b)" in out
    assert "arg_" not in out


def test_optional_and_rest_combined():
    out = _decompile("(defun f (a &optional b &rest r) (list a b r))")
    assert "(defun f (a &optional b &rest r)" in out
    assert "arg_" not in out


def test_multiple_required_then_rest():
    out = _decompile("(defun f (a b &rest r) (cons a (cons b r)))")
    assert "(defun f (a b &rest r)" in out
    assert "arg_" not in out


def test_rest_with_apply_quote_plus():
    out = _decompile("(defun f (a &rest r) (apply (quote +) (cons a r)))")
    assert "(defun f (a &rest r)" in out
    assert "(apply '+ (cons a r))" in out
    assert "arg_" not in out


def test_rest_forwarded_to_other_call():
    out = _decompile("(defun f (a &rest r) (g a r))")
    assert "(defun f (a &rest r)" in out
    assert "arg_" not in out


def test_rest_recursive():
    out = _decompile("(defun f (n &rest r) (if r (f n (cdr r)) n))")
    assert "(defun f (n &rest r)" in out
    assert "arg_" not in out
