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
    from compiler.ast_nodes import Setq
    assert isinstance(setq, Setq)
    assert setq.pairs[0][0].name == 'x'
    assert setq.pairs[0][1].value == 5


def test_parse_if():
    src = '(defun foo (x) (if (> x 0) "pos" "neg"))'
    p = Parser(src)
    prog = p.parse()
    f = prog.forms[0]
    from compiler.ast_nodes import IfNode
    assert isinstance(f.body[0], IfNode)
    if_node = f.body[0]


def test_parse_while():
    src = '(defun foo (n) (while (> n 0) (setq n (- n 1))))'
    p = Parser(src)
    prog = p.parse()
    f = prog.forms[0]
    from compiler.ast_nodes import WhileNode
    assert isinstance(f.body[0], WhileNode)


def test_parse_cond():
    src = '(defun foo (x) (cond ((< x 0) "neg") ((> x 0) "pos") (t "zero")))'
    p = Parser(src)
    prog = p.parse()
    f = prog.forms[0]
    from compiler.ast_nodes import Cond
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
    from compiler.ast_nodes import QuotedExpr, ListExpr, Call
    q = f.body[0].pairs[0][1]
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
    from compiler.ast_nodes import Setq, Defun
    assert isinstance(prog.forms[0], Setq)
    assert isinstance(prog.forms[1], Defun)


def test_lexer_1plus_1minus():
    """Lexer recognizes 1+ and 1- as symbols."""
    from compiler.lexer import tokenize
    toks = tokenize('(1+ 2)')
    kinds = [k for k, _, _, _ in toks]
    assert kinds[1] == 'SYMBOL', f'Expected SYMBOL for 1+, got {kinds[1]}'
    assert toks[1][1] == '1+', f'Expected "1+", got {toks[1][1]}'

    toks = tokenize('(1- 2)')
    kinds = [k for k, _, _, _ in toks]
    assert kinds[1] == 'SYMBOL', f'Expected SYMBOL for 1-, got {kinds[1]}'
    assert toks[1][1] == '1-', f'Expected "1-", got {toks[1][1]}'

    toks = tokenize("(mapcar '1+ l)")
    vals = [v for _, v, _, _ in toks]
    assert '1+' in vals, f'Expected 1+ in tokens, got {vals}'


def test_lexer_function_macro():
    """Lexer recognizes #' as the function reader macro (not a '#' symbol)."""
    from compiler.lexer import tokenize
    toks = tokenize("#'car")
    kinds = [k for k, _, _, _ in toks]
    assert kinds[0] == 'FUNCTION', f'Expected FUNCTION token, got {kinds[0]}'
    assert kinds[1] == 'SYMBOL'
    assert kinds[2] == 'EOF'


def test_parse_function_macro_symbol():
    """#'foo parses to QuotedExpr(Symbol foo), same as (function foo)."""
    from compiler.ast_nodes import QuotedExpr, Symbol
    p = Parser("(defun f () #'car)")
    f = p.parse().forms[0]
    q = f.body[0]
    assert isinstance(q, QuotedExpr)
    assert isinstance(q.expr, Symbol)
    assert q.expr.name == 'car'


def test_parse_function_macro_lambda():
    """#'(lambda ...) parses to QuotedExpr containing a lambda form."""
    from compiler.ast_nodes import QuotedExpr, LambdaNode
    p = Parser("(defun f () #'(lambda (x) (1+ x)))")
    f = p.parse().forms[0]
    q = f.body[0]
    assert isinstance(q, QuotedExpr)
    assert isinstance(q.expr, LambdaNode)
    assert q.expr.args == ['x']


def test_parse_function_macro_in_mapcar():
    """mapcar #'1+ compiles correctly via round-trip semantics."""
    from compiler.ast_nodes import Call, QuotedExpr, Symbol
    p = Parser("(defun f (l) (mapcar #'1+ l))")
    f = p.parse().forms[0]
    call = f.body[0]
    assert isinstance(call, Call)
    assert call.name == 'mapcar'
    q = call.args[0]
    assert isinstance(q, QuotedExpr)
    assert isinstance(q.expr, Symbol)
    assert q.expr.name == '1+'


def test_parse_dotted_call():
    """(cons 1 . 2) in call position parses to Call with the dotted tail as arg."""
    from compiler.ast_nodes import Call, Integer
    p = Parser("(defun f () (cons 1 . 2))")
    f = p.parse().forms[0]
    call = f.body[0]
    assert isinstance(call, Call)
    assert call.name == 'cons'
    assert len(call.args) == 2
    assert isinstance(call.args[0], Integer) and call.args[0].value == 1
    assert isinstance(call.args[1], Integer) and call.args[1].value == 2


def test_parse_quoted_dotted_data():
    """'(a . b) in data position stays a dotted ListExpr (not a call)."""
    from compiler.ast_nodes import QuotedExpr, ListExpr, Symbol
    p = Parser("(defun f () (setq x '(a . b)))")
    f = p.parse().forms[0]
    val = f.body[0].pairs[0][1]
    assert isinstance(val, QuotedExpr)
    inner = val.expr
    assert isinstance(inner, ListExpr)
    assert inner.dotted is not None
    assert isinstance(inner.dotted, Symbol) and inner.dotted.name == 'b'
    assert len(inner.items) == 1 and inner.items[0].name == 'a'


def test_parse_quoted_bare_special_forms_are_data():
    """裸引用关键字 `'(defun)`/`'(lambda)`/`'(setq)`/`'(cond)` 是普通数据列表，
    不按特殊形式解析（`'(defun)` 曾因缺函数名报错，其余曾解析为空结构节点）。"""
    from compiler.ast_nodes import QuotedExpr, ListExpr, Symbol
    for expr, kw in [("'(defun)", 'defun'), ("'(lambda)", 'lambda'),
                     ("'(setq)", 'setq'), ("'(cond)", 'cond')]:
        p = Parser("(defun f () (setq wl '(x)) (member fn %s))" % expr)
        # 直接解析裸引用：`(defun f () (setq wl '(x)) ...)` 里的引用在语句中
        q = Parser(expr).parse().forms[0]
        assert isinstance(q, QuotedExpr)
        inner = q.expr
        assert isinstance(inner, ListExpr), f'{expr} -> {type(inner).__name__}'
        assert len(inner.items) == 1
        assert isinstance(inner.items[0], Symbol) and inner.items[0].name == kw


def test_parse_quoted_lambda_body_keeps_special_forms():
    """引用 lambda 体内特殊形式保留结构节点（编译为可执行代码，i18n load-mt
    实测），不被当作数据列表展开。"""
    from compiler.ast_nodes import QuotedExpr, LambdaNode, IfNode, Setq
    p = Parser("(defun f (x) (function (lambda (y) (if (= x 1) (setq y 2)))))")
    f = p.parse().forms[0]
    q = f.body[0]
    assert isinstance(q, QuotedExpr)
    lam = q.expr
    assert isinstance(lam, LambdaNode)
    assert isinstance(lam.body[0], IfNode)
    assert isinstance(lam.body[0].then, Setq)
