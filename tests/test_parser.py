import sys
sys.path.insert(0, '.')

from compiler.parser import Parser


def test_parse_defun_no_args():
    src = '(defun hello () (princ "Hello"))'
    p = Parser(src)
    prog = p.parse()
    assert len(prog.forms) == 1
    f = prog.forms[0]
    assert f.name == 'hello'
    assert f.args == []
    assert len(f.body) == 1


def test_parse_defun_with_args():
    src = '(defun add (a b) (+ a b))'
    p = Parser(src)
    prog = p.parse()
    f = prog.forms[0]
    assert f.name == 'add'
    assert f.args == ['a', 'b']
    assert len(f.body) == 1


def test_parse_defun_with_locals():
    src = '(defun foo (a / x y) (setq x a) (+ x y))'
    p = Parser(src)
    prog = p.parse()
    f = prog.forms[0]
    assert f.name == 'foo'
    assert f.args == ['a']
    assert f.locals == ['x', 'y']
    assert len(f.body) == 2


def test_parse_defun_only_locals():
    src = '(defun bar (/ a) a)'
    p = Parser(src)
    prog = p.parse()
    f = prog.forms[0]
    assert f.name == 'bar'
    assert f.args == []
    assert f.locals == ['a']
    assert len(f.body) == 1


def test_parse_setq():
    src = '(defun foo () (setq x 5))'
    p = Parser(src)
    prog = p.parse()
    f = prog.forms[0]
    assert len(f.body) == 1
    setq = f.body[0]
    from compiler.ast import Setq
    assert isinstance(setq, Setq)
    assert setq.target.name == 'x'
    assert setq.value.value == 5


def test_parse_if():
    src = '(defun foo (x) (if (> x 0) "pos" "neg"))'
    p = Parser(src)
    prog = p.parse()
    f = prog.forms[0]
    from compiler.ast import IfNode
    assert isinstance(f.body[0], IfNode)
    if_node = f.body[0]


def test_parse_while():
    src = '(defun foo (n) (while (> n 0) (setq n (- n 1))))'
    p = Parser(src)
    prog = p.parse()
    f = prog.forms[0]
    from compiler.ast import WhileNode
    assert isinstance(f.body[0], WhileNode)


def test_parse_cond():
    src = '(defun foo (x) (cond ((< x 0) "neg") ((> x 0) "pos") (t "zero")))'
    p = Parser(src)
    prog = p.parse()
    f = prog.forms[0]
    from compiler.ast import Cond
    assert isinstance(f.body[0], Cond)
    assert len(f.body[0].clauses) == 3


def test_parse_lambda():
    src = '(defun foo (x) ((lambda (y) (+ y 1)) x))'
    p = Parser(src)
    prog = p.parse()
    f = prog.forms[0]


def test_parse_quote():
    src = "(defun foo () (setq x '(a b c)))"
    p = Parser(src)
    prog = p.parse()
    f = prog.forms[0]
    from compiler.ast import QuotedExpr, ListExpr, Call
    q = f.body[0].value
    assert isinstance(q, QuotedExpr)
    assert isinstance(q.expr, (ListExpr, Call, tuple))


def test_parse_progn():
    src = '(defun foo () (progn (princ "a") (princ "b")))'
    p = Parser(src)
    prog = p.parse()
    f = prog.forms[0]


def test_parse_top_level_init():
    src = '(setq *ver* "1.0")\n(defun foo () nil)'
    p = Parser(src)
    prog = p.parse()
    assert len(prog.forms) == 2
    from compiler.ast import Setq, Defun
    assert isinstance(prog.forms[0], Setq)
    assert isinstance(prog.forms[1], Defun)
