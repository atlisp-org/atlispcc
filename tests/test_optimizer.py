import sys
sys.path.insert(0, '.')

import pytest
from compiler.ast_nodes import (
    Program, Defun, Symbol, Integer, String, Call, Setq,
    IfNode, WhileNode, Progn, Cond, ForeachNode, RepeatNode,
)
from compiler.parser import Parser
from compiler.opt import (
    constant_fold, dead_branch_elim, peephole,
    dead_assign_elim, const_propagate, dead_code_elim,
    inline_small_funcs, cross_func_const_propagate, optimize,
    remove_dead_functions,
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


# ─── Dead function removal (O3) ────────────────────────────────────────


def test_remove_dead_uncalled():
    src = '''
(defun helper () 1)
(defun orphan () 2)
(defun c:run () (helper))
'''
    prog = parse(src)
    result = remove_dead_functions(prog)
    assert [f.name for f in result.forms if isinstance(f, Defun)] == ['helper', 'c:run']


def test_remove_dead_keeps_called_and_command():
    src = '''
(defun used () 1)
(defun c:cmd () (used))
(defun orphan () 2)
'''
    prog = parse(src)
    result = remove_dead_functions(prog)
    names = {f.name for f in result.forms if isinstance(f, Defun)}
    assert names == {'used', 'c:cmd'}


def test_remove_dead_keeps_quoted_ref():
    src = '''
(defun helper (x) (1+ x))
(defun main (lst) (mapcar 'helper lst))
(defun c:go () (main nil))
'''
    prog = parse(src)
    result = remove_dead_functions(prog)
    names = {f.name for f in result.forms if isinstance(f, Defun)}
    assert names == {'helper', 'main', 'c:go'}


def test_remove_dead_keeps_quoted_list_head():
    src = '''
(defun cb () 1)
(defun c:go () (apply 'cb nil))
'''
    prog = parse(src)
    result = remove_dead_functions(prog)
    names = {f.name for f in result.forms if isinstance(f, Defun)}
    assert names == {'cb', 'c:go'}


def test_remove_dead_library_keeps_all():
    src = '''
(defun a () 1)
(defun b () (a))
'''
    prog = parse(src)
    result = remove_dead_functions(prog)
    assert {f.name for f in result.forms if isinstance(f, Defun)} == {'a', 'b'}


def test_const_propagate_loop_carried():
    """Loop-carried variables must NOT be const-propagated into the loop."""
    src = '''
(defun f (rows / i n)
  (setq i 0)
  (setq n (length rows))
  (while (< i n)
    (setq i (1+ i))
  )
  i
)'''
    prog = parse(src)
    result = const_propagate(prog)
    f = result.forms[0]
    while_node = f.body[2]
    assert isinstance(while_node, WhileNode)
    assert isinstance(while_node.cond.args[0], Symbol)
    assert while_node.cond.args[0].name == 'i'
    body_setq = while_node.body[0]
    assert isinstance(body_setq, Setq)
    assert isinstance(body_setq.pairs[0][0], Symbol)


def test_const_propagate_branch_assigned_invalidated():
    """A variable assigned inside an if-branch loses its constant afterward."""
    src = '''
(defun f (x / y)
  (setq y 0)
  (if x (setq y 5) (setq y 6))
  (+ y 1)
)'''
    prog = parse(src)
    result = const_propagate(prog)
    f = result.forms[0]
    last = f.body[-1]
    assert isinstance(last, Call)
    assert isinstance(last.args[0], Symbol)
    assert last.args[0].name == 'y'


def test_const_propagate_repeat_loop_carried():
    src = '''
(defun f (n / acc)
  (setq acc 0)
  (repeat n
    (setq acc (1+ acc))
  )
  acc
)'''
    prog = parse(src)
    result = const_propagate(prog)
    f = result.forms[0]
    repeat_node = f.body[1]
    assert isinstance(repeat_node, RepeatNode)
    body_setq = repeat_node.body[0]
    assert isinstance(body_setq.pairs[0][0], Symbol)
    assert body_setq.pairs[0][0].name == 'acc'


def test_remove_dead_wired_in_o3():
    src = '''
(defun keep (x) (1+ x))
(defun c:run () (keep 1))
(defun unused (x) (* x 2))
'''
    prog = parse(src)
    result = optimize(prog, level=3)
    names = {f.name for f in result.forms if isinstance(f, Defun)}
    assert 'unused' not in names
    assert 'c:run' in names
