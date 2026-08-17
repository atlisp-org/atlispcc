import re
from typing import List, Tuple, Optional


Token = Tuple[str, str, int, int]

TOKEN_SPEC = [
    ('LPAREN', r'\('),
    ('RPAREN', r'\)'),
    ('QUOTE', r"'"),
    ('FUNCTION', r"#'"),
    ('DOT', r'\.'),
    ('STRING', r'"[^"\\]*(?:\\.[^"\\]*)*"'),
    ('REAL', r'-?\d+\.\d+(?:[eE][+-]?\d+)?'),
    ('INTEGER', r'-?\d+'),
    ('SYMBOL', r'[^\s()\'";]+'),
]

TOKEN_RE = re.compile('|'.join(f'(?P<{name}>{pattern})' for name, pattern in TOKEN_SPEC))
STRING_ESC_RE = re.compile(r'\\(.)')

_STRING_ESCAPES = {
    'n': '\n',
    'r': '\r',
    't': '\t',
    'e': '\x1b',
    '\\': '\\',
    '"': '"',
}


def _unescape_match(m: "re.Match[str]") -> str:
    ch = m.group(1)
    if ch in _STRING_ESCAPES:
        return _STRING_ESCAPES[ch]
    return '\\' + ch


def unescape_string(s: str) -> str:
    return STRING_ESC_RE.sub(_unescape_match, s[1:-1])


def tokenize(source: str) -> List[Token]:
    tokens = []
    line = 1
    col = 1
    pos = 0
    while pos < len(source):
        ch = source[pos]
        if ch in ' \t\r':
            col += 1
            pos += 1
            continue
        if ch == '\n':
            line += 1
            col = 1
            pos += 1
            continue
        if ch == ';':
            if source.startswith(';|', pos):
                end = source.find('|;', pos + 2)
                if end < 0:
                    break
                consumed = source[pos:end + 2]
                nl = consumed.rfind('\n')
                if nl >= 0:
                    line += consumed.count('\n')
                    col = len(consumed) - nl
                else:
                    col += len(consumed)
                pos = end + 2
                continue
            end = source.find('\n', pos)
            if end < 0:
                break
            pos = end
            continue
        if source.startswith('1+', pos):
            tokens.append(('SYMBOL', '1+', line, col))
            col += 2
            pos += 2
            continue
        if source.startswith('1-', pos) and (pos + 2 >= len(source) or source[pos + 2] in ' \t\r\n()"\';'):
            tokens.append(('SYMBOL', '1-', line, col))
            col += 2
            pos += 2
            continue
        m = TOKEN_RE.match(source, pos)
        if m:
            kind = m.lastgroup or ''
            val = m.group()
            if kind == 'STRING':
                val = unescape_string(val)
            elif kind == 'SYMBOL' and '.' in val:
                # CAD 词法级符号名规范化：含 `.` 的符号名（`:package.install`
                # `foo.bar` `a.b.c`）截断到第一个 `.`（CAD 真机实测 `'x.y`→`X`
                # `:package.install`→`:PACKAGE` `(defun foo.bar () ...)` 定义
                # 的是 `foo`）。独立的 `.` token（dotted pair `(a . b)`）仍走
                # DOT 分支，不受影响。
                val = val.split('.', 1)[0]
            tokens.append((kind, val, line, col))
            col += len(m.group())
            pos = m.end()
        else:
            tokens.append(('SYMBOL', source[pos], line, col))
            col += 1
            pos += 1
    tokens.append(('EOF', '', line, col))
    return tokens
