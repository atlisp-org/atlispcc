"""Dedicated tests for compiler.lexer — tokenization of AutoLISP source."""
import sys
sys.path.insert(0, '.')

from compiler.lexer import tokenize, unescape_string


def _kinds(src):
    return [k for k, _, _, _ in tokenize(src)]


def _values(src):
    return [v for _, v, _, _ in tokenize(src)]


def test_string_token():
    toks = tokenize('"hello"')
    assert toks[0][0] == 'STRING'
    assert toks[0][1] == 'hello'


def test_string_escapes():
    assert unescape_string('"a\\nb\\tc"') == 'a\nb\tc'
    assert unescape_string('"a\\\\b"') == 'a\\b'
    assert unescape_string('"a\\"b"') == 'a"b'
    assert unescape_string('"a\\eb"') == 'a\x1bb'


def test_string_unknown_escape_kept():
    # Unknown escape `\x`：CAD 丢弃反斜杠只留字符（system/winget `.\Microsoft`、
    # CAD 真机 `".\Mx"`→`".Mx"` 实测）；例外是 `\u+XXXX`/`\U+XXXX` unicode
    # 转义**原样保留**（text/stringexplode `\u+23f61` CAD golden 保留反斜杠）。
    assert unescape_string('"a\\zb"') == 'azb'
    assert unescape_string('".\\Mx"') == '.Mx'
    assert unescape_string('"\\u+23f61"') == '\\u+23f61'
    assert unescape_string('"\\U+0041"') == '\\U+0041'


def test_string_contains_comment_chars():
    toks = tokenize('"; not a comment"')
    assert toks[0][0] == 'STRING'
    assert toks[0][1] == '; not a comment'


def test_line_comment():
    src = '(a) ; trailing comment\n(b)'
    vals = _values(src)
    assert 'a' in vals
    assert 'b' in vals


def test_block_comment():
    src = '(a) ;| block ; still inside |; (b)'
    vals = _values(src)
    assert 'a' in vals
    assert 'b' in vals
    assert 'still' not in vals
    assert 'inside' not in vals


def test_block_comment_multiline():
    src = '(a)\n;| line1\nline2 |;\n(b)'
    vals = _values(src)
    assert 'a' in vals
    assert 'b' in vals


def test_utf8_symbols_and_strings():
    toks = tokenize('(princ "中文测试")')
    kinds = _kinds('(princ "中文测试")')
    assert 'STRING' in kinds
    assert toks[1][1] == 'princ'
    assert toks[2][1] == '中文测试'


def test_dotted_token():
    kinds = _kinds("'(a . b)")
    assert 'DOT' in kinds


def test_real_vs_int():
    assert _kinds('1.5')[0] == 'REAL'
    assert _kinds('-3.25')[0] == 'REAL'
    assert _kinds('42')[0] == 'INTEGER'
    assert _kinds('-7')[0] == 'INTEGER'


def test_line_col_tracking():
    toks = tokenize('(a\n  b)')
    line_a = toks[1][2]
    line_b = toks[2][2]
    assert line_a == 1
    assert line_b == 2
