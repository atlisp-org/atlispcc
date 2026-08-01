"""Dedicated tests for compiler.analyzer — statistics & analysis helpers."""
import sys
sys.path.insert(0, '.')

from compiler.parser import Parser
from compiler.symbol_table import SymbolTable
from compiler.ast import Defun
from compiler.analyzer import (
    count_instructions, find_tail_recursive, estimate_constants, analyze,
)


def _defun(src):
    prog = Parser(src).parse()
    return [f for f in prog.forms if isinstance(f, Defun)][0]


def test_count_instructions_basic():
    f = _defun('(defun foo () 1)')
    n = count_instructions(f, SymbolTable())
    assert n > 0


def test_count_instructions_grows_with_body():
    st = SymbolTable()
    small = count_instructions(_defun('(defun a () 1)'), st)
    st2 = SymbolTable()
    large = count_instructions(_defun('(defun a () (+ 1 2 3 4 5))'), st2)
    assert large > small


def test_find_tail_recursive_direct():
    f = _defun('(defun fact (n) (if (= n 1) 1 (fact (- n 1))))')
    assert find_tail_recursive(f) is True


def test_find_tail_recursive_progn_tail():
    f = _defun('(defun foo (x) (princ x) (foo (1+ x)))')
    assert find_tail_recursive(f) is True


def test_find_tail_recursive_not_tail():
    f = _defun('(defun foo (n) (* n (foo (1- n))))')
    assert find_tail_recursive(f) is False


def test_find_tail_recursive_no_body():
    f = _defun('(defun foo () )')
    assert find_tail_recursive(f) is False


def test_estimate_constants():
    prog = Parser('(defun foo () (+ 1 2.5 "str"))').parse()
    assert estimate_constants(prog) == 3


def test_analyze_stats():
    prog = Parser('''
(defun add (a b) (+ a b))
(defun countdown (n) (if (= n 0) 0 (countdown (- n 1))))
(setq *ver* "1.0")
''').parse()
    stats = analyze(prog)
    assert stats['functions'] == 2
    assert stats['top_level_forms'] == 1
    assert stats['constants_estimate'] >= 2
    assert stats['symbol_table_entries'] > 0
    assert stats['tail_recursive_functions'] == ['countdown']
    assert len(stats['functions_detail']) == 2
    by_name = {d['name']: d for d in stats['functions_detail']}
    assert by_name['add']['args'] == 2
    assert by_name['add']['tail_recursive'] is False
    assert by_name['countdown']['tail_recursive'] is True


def test_analyze_extern_calls():
    prog = Parser('(defun foo (x) (princ x) (strcat "a" "b"))').parse()
    stats = analyze(prog)
    assert 'princ' in stats['builtin_calls']
    assert 'strcat' in stats['builtin_calls']
