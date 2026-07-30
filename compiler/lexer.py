import re
from typing import List, Tuple, Optional


Token = Tuple[str, str, int, int]

TOKEN_SPEC = [
    ('LPAREN', r'\('),
    ('RPAREN', r'\)'),
    ('QUOTE', r"'"),
    ('DOT', r'\.'),
    ('STRING', r'"[^"\\]*(?:\\.[^"\\]*)*"'),
    ('REAL', r'-?\d+\.\d+(?:[eE][+-]?\d+)?'),
    ('INTEGER', r'-?\d+'),
    ('SYMBOL', r'[^\s()\'";]+'),
]

TOKEN_RE = re.compile('|'.join(f'(?P<{name}>{pattern})' for name, pattern in TOKEN_SPEC))
STRING_ESC_RE = re.compile(r'\\(.)')


def unescape_string(s: str) -> str:
    return STRING_ESC_RE.sub(r'\1', s[1:-1])


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
            kind = m.lastgroup
            val = m.group()
            if kind == 'STRING':
                val = unescape_string(val)
            tokens.append((kind, val, line, col))
            col += len(m.group())
            pos = m.end()
        else:
            tokens.append(('SYMBOL', source[pos], line, col))
            col += 1
            pos += 1
    tokens.append(('EOF', '', line, col))
    return tokens
