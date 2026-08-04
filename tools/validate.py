#!/usr/bin/env python3
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, List, Tuple


SYMBOL_RE = re.compile(r'^[\w\-?!*/=<>+:.]+$')
NUMBER_RE = re.compile(r'^[+-]?(?:\d+(?:\.\d*)?|\.\d+)$')


@dataclass
class Token:
    kind: str
    value: str
    line: int


@dataclass
class Node:
    value: Any
    line: int
    kind: str = 'list'


def tokenize(text: str) -> Tuple[List[Token], List[str]]:
    tokens: List[Token] = []
    errors: List[str] = []
    i = 0
    line = 1
    while i < len(text):
        ch = text[i]
        if ch in ' \t\r':
            i += 1
            continue
        if ch == '\n':
            line += 1
            i += 1
            continue
        if ch == ';':
            while i < len(text) and text[i] != '\n':
                i += 1
            continue
        if ch in '()\'':
            tokens.append(Token(ch, ch, line))
            i += 1
            continue
        if ch == '"':
            start_line = line
            i += 1
            value = []
            while i < len(text):
                ch = text[i]
                if ch == '\\' and i + 1 < len(text):
                    value.append(text[i:i + 2])
                    i += 2
                    continue
                if ch == '"':
                    i += 1
                    break
                if ch == '\n':
                    line += 1
                value.append(ch)
                i += 1
            else:
                errors.append(f'line {start_line}: unterminated string')
            tokens.append(Token('string', ''.join(value), start_line))
            continue

        start = i
        start_line = line
        while i < len(text) and text[i] not in '()\'"; \t\r\n':
            i += 1
        tokens.append(Token('symbol', text[start:i], start_line))
    return tokens, errors


def parse_tokens(tokens: List[Token]) -> Tuple[List[Node], List[str]]:
    errors: List[str] = []
    pos = 0

    def parse_expr() -> Node:
        nonlocal pos
        if pos >= len(tokens):
            raise ValueError('unexpected EOF')
        tok = tokens[pos]
        pos += 1
        if tok.kind == '(':
            items: List[Node] = []
            while pos < len(tokens) and tokens[pos].kind != ')':
                items.append(parse_expr())
            if pos >= len(tokens):
                errors.append(f'line {tok.line}: missing closing parenthesis')
                return Node(items, tok.line, 'list')
            pos += 1
            return Node(items, tok.line, 'list')
        if tok.kind == ')':
            errors.append(f'line {tok.line}: unexpected closing parenthesis')
            return Node([], tok.line, 'list')
        if tok.kind == '\'':
            quoted = parse_expr()
            return Node([Node('quote', tok.line, 'symbol'), quoted], tok.line, 'list')
        if tok.kind == 'string':
            return Node(tok.value, tok.line, 'string')
        return Node(tok.value, tok.line, 'symbol')

    forms: List[Node] = []
    while pos < len(tokens):
        try:
            forms.append(parse_expr())
        except ValueError as exc:
            errors.append(str(exc))
            break
    return forms, errors


def form_text(node: Node, limit: int = 160) -> str:
    def render(item: Node) -> str:
        if item.kind == 'list':
            return '(' + ' '.join(render(child) for child in item.value) + ')'
        if item.kind == 'string':
            text = str(item.value).replace('\\', '\\\\').replace('"', '\\"')
            return f'"{text}"'
        return str(item.value)

    text = render(node)
    return text if len(text) <= limit else text[:limit - 3] + '...'


def is_symbol(node: Node) -> bool:
    if node.kind != 'symbol' or not isinstance(node.value, str):
        return False
    if node.value == 'quote':
        return False
    if NUMBER_RE.match(node.value):
        return False
    return True


def symbol_ok(value: str) -> bool:
    # AutoLISP 中 ':' 是普通字符（如 *string:pad*、c: 命令），包符号也合法。
    return SYMBOL_RE.match(value) is not None


def validate_balance(tokens: List[Token]) -> List[str]:
    errors: List[str] = []
    balance = 0
    for token in tokens:
        if token.kind == '(':
            balance += 1
        elif token.kind == ')':
            balance -= 1
            if balance < 0:
                errors.append(f'line {token.line}: closing parenthesis before opening parenthesis')
                break
    if balance != 0:
        errors.append(f'parentheses: balance is {balance}, expected 0')
    return errors


def validate_ast(forms: List[Node]) -> List[str]:
    errors: List[str] = []

    for form in forms:
        if not isinstance(form.value, list) or not form.value:
            errors.append(f'line {form.line}: malformed top-level form: {form_text(form)}')
            continue
        head = form.value[0].value
        if head == 'defun':
            if len(form.value) >= 3 and is_symbol(form.value[1]) and form.value[2].kind == 'list':
                name = str(form.value[1].value).lower()
                if name.startswith('c:'):
                    required_args = []
                    for arg in form.value[2].value:
                        if arg.kind == 'symbol' and arg.value == '/':
                            break
                        if is_symbol(arg):
                            required_args.append(str(arg.value))
                    if required_args:
                        errors.append(
                            f'line {form.line}: AutoCAD command defun has required args: {", ".join(required_args)}'
                        )
        # 其他顶层形式是合法的模块 init 代码，仅做结构检查

    def walk(node: Node) -> None:
        value = node.value
        if is_symbol(node) and not symbol_ok(value.lower()):
            errors.append(f'line {node.line}: illegal symbol name: {value}')
            return
        if node.kind != 'list' or not value:
            return

        head = value[0].value if value else None
        if head == 'if' and len(value) < 3:
            errors.append(f'line {node.line}: if has too few forms: {form_text(node)}')
        elif head == 'while' and len(value) < 3:
            errors.append(f'line {node.line}: while has no body: {form_text(node)}')
        elif head == 'progn' and len(value) == 1:
            errors.append(f'line {node.line}: empty progn: {form_text(node)}')
        elif head == 'setq' and len(value) % 2 == 0:
            errors.append(f'line {node.line}: setq requires an even number of arguments: {form_text(node)}')
        elif head == 'foreach' and len(value) < 4:
            errors.append(f'line {node.line}: foreach must have var, list, and body: {form_text(node)}')

        for child in value:
            walk(child)

    for form in forms:
        walk(form)

    return errors


#: 危险/不安全函数调用（warn 级，不阻断 validate 返回码）。
DANGEROUS_FUNCS = frozenset(('quit', 'exit', 'startapp'))


def validate_danger(forms: List[Node]) -> List[str]:
    """Detect dangerous function calls (quit/exit/startapp) as warnings."""
    warnings: List[str] = []

    def walk(node: Node) -> None:
        value = node.value
        if node.kind != 'list' or not value:
            return
        head = value[0].value if value else None
        if isinstance(head, str) and head.lower() in DANGEROUS_FUNCS:
            warnings.append(
                f'line {node.line}: warning: dangerous function call: {form_text(node)}'
            )
        for child in value:
            walk(child)

    for form in forms:
        walk(form)
    return warnings


def validate_unused(forms: List[Node]) -> List[str]:
    """Warn about declared-but-unused defun local variables (/ locals)."""
    warnings: List[str] = []

    def collect_symbols(node: Node, acc: List[str]) -> None:
        value = node.value
        if node.kind == 'symbol':
            if is_symbol(node):
                acc.append(str(value).lower())
        elif node.kind == 'list':
            for child in value:
                collect_symbols(child, acc)

    for form in forms:
        if not isinstance(form.value, list) or not form.value:
            continue
        head = form.value[0].value
        if head != 'defun' or len(form.value) < 3 or form.value[2].kind != 'list':
            continue
        params = form.value[2].value
        sep = next((i for i, a in enumerate(params)
                    if a.kind == 'symbol' and a.value == '/'), None)
        if sep is None:
            continue
        locals_list = params[sep + 1:]
        body = form.value[3:]
        used: List[str] = []
        for expr in body:
            collect_symbols(expr, used)
        used_set = set(used)
        for local in locals_list:
            if local.kind != 'symbol' or not is_symbol(local):
                continue
            name = str(local.value).lower()
            if name not in used_set:
                warnings.append(
                    f'line {local.line}: warning: unused local variable: {name}'
                )
    return warnings


def validate_file(path: Path) -> bool:
    text = path.read_text(encoding='utf-8')
    tokens, token_errors = tokenize(text)
    forms, parse_errors = parse_tokens(tokens)
    errors = token_errors + validate_balance(tokens) + parse_errors + validate_ast(forms)
    warnings = validate_danger(forms) + validate_unused(forms)
    if errors:
        print(f'[FAIL] {path}')
        for error in errors:
            print(f'  {error}')
        return False
    if warnings:
        print(f'[WARN] {path}')
        for warning in warnings:
            print(f'  {warning}')
        return True
    print(f'[PASS] {path}')
    return True


def main() -> int:
    if len(sys.argv) < 2:
        print('Usage: python validate.py <file.lsp> [file2.lsp ...]')
        return 2
    ok = True
    for arg in sys.argv[1:]:
        ok = validate_file(Path(arg)) and ok
    return 0 if ok else 1


if __name__ == '__main__':
    raise SystemExit(main())
