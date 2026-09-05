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
    # 实数：小数点形式和/或科学计数法。AutoLISP 允许无小数点的指数实数
    # （`1e-6`/`1E6`，CAD golden 注册 REAL `1.0e-06`，compiler/cad_symbols.py
    # 对拍），此前只匹配带小数点的形式导致 `1e-6` 被读成 SYMBOL `1E-6`。
    # 纯整数（`2000`、`1+`/`1-` 等）仍留给 INTEGER/特判，避免 INTEGER 死分支。
    ('REAL', r'-?\d+(?:\.\d+(?:[eE][+-]?\d+)?|[eE][+-]?\d+)'),
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
    # CAD 转义规则（真机实测）：
    #  - 未知转义 `\x` 丢弃反斜杠只留字符：`".\Mx"` → `".Mx"`
    #    （system/winget.lsp `.\Microsoft`，此前保留反斜杠与 golden 差 1 字符）。
    #  - 例外：`\u+XXXX`/`\U+XXXX` 形式的 unicode 转义**原样保留**反斜杠
    #    （text/stringexplode.lsp `\u+23f61` CAD golden 保留 `\`）。
    if ch in ('u', 'U'):
        nxt = m.string[m.end():m.end() + 2]
        if nxt[:1] == '+' and nxt[1:2] and nxt[1] in '0123456789abcdefABCDEF':
            return '\\' + ch
    return ch


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
            if kind in ('INTEGER', 'REAL'):
                # 数字后紧跟符号字符（无分隔，如 `2000i`、层名 `123abc`）：
                # AutoLISP/CAD 把它们整体读作一个符号（system/vers.lsp
                # `(2000i . 15.1)` CAD golden 注册符号 `2000I`，非 `2000`+`I`）。
                # 交替顺序先命中 INTEGER/REAL，此处前视下一个字符判断。
                nxt = m.end()
                if nxt < len(source) and source[nxt] not in ' \t\r\n()\'";':
                    m2 = TOKEN_RE.match(source, pos)
                    # 仅当剩余仍可能被符号规则消费时才重读为 SYMBOL；SYMBOL
                    # 模式不能匹配空。
                    sm = re.compile(r'[^\s()\'";]+').match(source, pos)
                    if sm and sm.end() > pos:
                        kind = 'SYMBOL'
                        val = sm.group()
                        m = sm
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
