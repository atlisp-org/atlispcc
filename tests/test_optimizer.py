import sys
sys.path.insert(0, '.')

import pytest
from compiler.ast import (
    Program, Defun, Symbol, Integer, String, Call, Setq,
    IfNode, WhileNode, Progn, Cond, ForeachNode, RepeatNode,
)
from compiler.parser import Parser
from compiler.opt import (
    constant_fold, dead_branch_elim, peephole,
    dead_assign_elim, const_propagate, dead_code_elim,
    inline_small_funcs, cross_func_const_propagate, optimize,
)
from compiler.analyzer import analyze, find_tail_recursive


def parse(src: str) -> Program:
    return Parser(src).parse()


# ─── Constant folding ───────────────────────────────────────────────────

def test_const_fold_arith():
    prog = parse('(+ 1 2)')
    result = constant_fold(prog)
    assert isinstance(result.forms[0], Integer)
    assert result.forms[0].value == 3


def test_const_fold_strcat():
    prog = parse('(strcat "a" "b")')
    result = constant_fold(prog)
    assert isinstance(result.forms[0], String)
    assert result.forms[0].value == 'ab'


def test_const_fold_nested():
    prog = parse('(+ 1 (+ 2 3))')
    result = constant_fold(prog)
    assert isinstance(result.forms[0], Integer)
    assert result.forms[0].value == 6


# ─── Dead branch elimination ────────────────────────────────────────────

def test_dead_branch_if_true():
    prog = parse('(if T 1 2)')
    result = dead_branch_elim(prog)
    assert isinstance(result.forms[0], Integer)
    assert result.forms[0].value == 1


def test_dead_branch_if_false():
    prog = parse('(if nil 1 2)')
    result = dead_branch_elim(prog)
    assert isinstance(result.forms[0], Integer)
    assert result.forms[0].value == 2


def test_dead_branch_while_nil():
    prog = parse('(while nil (princ "x"))')
    result = dead_branch_elim(prog)
    assert isinstance(result.forms[0], Symbol)
    assert result.forms[0].name == 'nil'


# ─── Peephole optimization ─────────────────────────────────────────────

def test_peephole_progn_single():
    prog = parse('(progn 42)')
    result = peephole(prog)
    assert isinstance(result.forms[0], Integer)
    assert result.forms[0].value == 42


def test_peephole_list_nil():
    prog = parse('(list)')
    result = peephole(prog)
    assert isinstance(result.forms[0], Symbol)
    assert result.forms[0].name == 'nil'


def test_peephole_and_zero():
    prog = parse('(and)')
    result = peephole(prog)
    assert isinstance(result.forms[0], Symbol)
    assert result.forms[0].name == 'T'


def test_peephole_or_zero():
    prog = parse('(or)')
    result = peephole(prog)
    assert isinstance(result.forms[0], Symbol)
    assert result.forms[0].name == 'nil'


# ─── Dead assignment elimination ────────────────────────────────────────

def test_dead_assign_simple():
    prog = parse('(defun foo () (setq x 5) 42)')
    result = dead_assign_elim(prog)
    result = peephole(result)
    f = result.forms[0]
    assert isinstance(f, Defun)
    assert len(f.body) == 1
    assert isinstance(f.body[0], Integer)
    assert f.body[0].value == 42


def test_dead_assign_live():
    prog = parse('(defun foo () (setq x 5) x)')
    result = dead_assign_elim(prog)
    f = result.forms[0]
    assert isinstance(f, Defun)
    assert len(f.body) == 2


# ─── Constant propagation ──────────────────────────────────────────────

def test_const_propagate_simple():
    prog = parse('(defun foo () (setq x 3) (+ x 1))')
    result = const_propagate(prog)
    f = result.forms[0]
    assert isinstance(f, Defun)
    # x should be replaced by 3
    call = f.body[1]
    assert isinstance(call, Call)
    assert call.name == '+'
    assert isinstance(call.args[0], Integer)
    assert call.args[0].value == 3


# ─── Dead code elimination ─────────────────────────────────────────────

def test_dead_code_after_exit():
    prog = parse('(defun foo () (exit) (princ "dead"))')
    result = dead_code_elim(prog)
    f = result.forms[0]
    assert isinstance(f, Defun)
    assert len(f.body) == 1


def test_dead_code_after_quit():
    prog = parse('(progn (quit) (princ "dead"))')
    result = dead_code_elim(prog)
    p = result.forms[0]
    assert isinstance(p, Progn)
    assert len(p.forms) == 1


# ─── Inlining ──────────────────────────────────────────────────────────

def test_inline_no_args():
    src = '''
(defun get-five () 5)
(defun foo () (get-five))
'''
    prog = parse(src)
    result = inline_small_funcs(prog)
    # get-five should be inlined, removing the defun
    assert len(result.forms) == 1
    assert isinstance(result.forms[0], Defun)
    assert result.forms[0].name == 'foo'
    assert isinstance(result.forms[0].body[0], Integer)
    assert result.forms[0].body[0].value == 5


# ─── Analyzer ─────────────────────────────────────────────────────────

def test_analyzer_basic():
    prog = parse('(defun foo (x) (+ x 1))')
    stats = analyze(prog)
    assert stats['functions'] == 1
    assert stats['functions_detail'][0]['name'] == 'foo'
    assert stats['functions_detail'][0]['args'] == 1
    assert stats['total_instructions'] > 0
    assert 'tail_recursive_functions' in stats


def test_analyzer_tail_recursive():
    src = '''
(defun fact (n acc)
  (if (= n 0)
    acc
    (fact (1- n) (* n acc))))
'''
    prog = parse(src)
    assert find_tail_recursive(prog.forms[0])
    stats = analyze(prog)
    assert 'fact' in stats['tail_recursive_functions']


def test_analyzer_not_tail_recursive():
    src = '''
(defun foo (n)
  (if (= n 0)
    1
    (+ n (foo (1- n)))))
'''
    prog = parse(src)
    assert not find_tail_recursive(prog.forms[0])


# ─── Cross-function constant propagation ───────────────────────────────

def test_cross_func_const_propagate():
    src = '''
(defun get-five () 5)
(defun foo () (get-five))
'''
    prog = parse(src)
    result = cross_func_const_propagate(prog)
    foo = result.forms[1]
    assert isinstance(foo, Defun)
    assert foo.name == 'foo'
    # (get-five) should be replaced by 5
    assert isinstance(foo.body[0], Integer)
    assert foo.body[0].value == 5


def test_cross_func_non_const_unchanged():
    src = '''
(defun add (a b) (+ a b))
(defun foo () (add 1 2))
'''
    prog = parse(src)
    result = cross_func_const_propagate(prog)
    foo = result.forms[1]
    assert isinstance(foo, Defun)
    # add is not constant (has args), should remain a call
    assert isinstance(foo.body[0], Call)
    assert foo.body[0].name == 'add'


# ─── Full pipeline (O3) ────────────────────────────────────────────────

def test_o3_pipeline():
    src = '''
(defun add (a b) (+ a b))
(defun foo () (add 1 2))
'''
    prog = parse(src)
    result = optimize(prog, level=3)
    # add should be inlined into foo: (+ 1 2) → 3
    # foo remains (entry point), add is removed after inlining
    assert len(result.forms) == 1
    f = result.forms[0]
    assert isinstance(f, Defun)
    assert f.name == 'foo'
    assert len(f.body) == 1
    assert isinstance(f.body[0], Integer)
    assert f.body[0].value == 3


def test_o3_with_cross_func_const():
    src = '''
(defun five () 5)
(defun add (a b) (+ a b))
(defun foo () (add (five) 3))
'''
    prog = parse(src)
    result = optimize(prog, level=3)
    # five is constant-replaced and inlined; add is inlined
    # foo should remain (entry point)
    foo = None
    for f in result.forms:
        if isinstance(f, Defun) and f.name == 'foo':
            foo = f
            break
    assert foo is not None
    assert isinstance(foo.body[0], Integer)
    assert foo.body[0].value == 8
