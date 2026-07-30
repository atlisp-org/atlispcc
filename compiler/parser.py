from typing import List, Optional
from compiler.lexer import tokenize, Token
from compiler.ast import (
    Node, Program, Symbol, Integer, Real, String,
    ListExpr, QuotedExpr, Defun, Setq, IfNode, WhileNode,
    ForeachNode, Call, Progn, LambdaNode, Cond,
)


class ParseError(Exception):
    pass


class Parser:
    def __init__(self, source: str):
        self.tokens: List[Token] = tokenize(source)
        self.pos = 0

    def peek(self) -> Token:
        return self.tokens[self.pos]

    def advance(self) -> Token:
        tok = self.tokens[self.pos]
        self.pos += 1
        return tok

    def expect(self, kind: str) -> Token:
        tok = self.peek()
        if tok[0] != kind:
            raise ParseError(f'Expected {kind}, got {tok[0]} ({tok[1]}) at line {tok[2]}, col {tok[3]}')
        return self.advance()

    def parse(self) -> Program:
        forms = []
        while self.peek()[0] != 'EOF':
            forms.append(self.parse_form())
        return Program(forms=forms)

    def parse_form(self) -> Node:
        tok = self.peek()
        kind, val, _, _ = tok
        if kind == 'LPAREN':
            return self.parse_list()
        elif kind == 'QUOTE':
            self.advance()
            return QuotedExpr(expr=self.parse_form())
        elif kind == 'SYMBOL':
            self.advance()
            return Symbol(name=val)
        elif kind == 'INTEGER':
            self.advance()
            return Integer(value=int(val))
        elif kind == 'REAL':
            self.advance()
            return Real(value=float(val))
        elif kind == 'STRING':
            self.advance()
            return String(value=val)
        else:
            raise ParseError(f'Unexpected token {kind}: {val} at line {tok[2]}, col {tok[3]}')

    def parse_list(self) -> Node:
        self.expect('LPAREN')
        if self.peek()[0] == 'RPAREN':
            self.advance()
            return ListExpr()
        head = self.parse_form()
        if isinstance(head, Symbol):
            name = head.name
            if name == 'defun' or name == 'defun-q':
                return self._parse_defun(name)
            elif name == 'setq':
                target = self.parse_form()
                val = None if self.peek()[0] == 'RPAREN' else self.parse_form()
                self.expect('RPAREN')
                return Setq(target=target, value=val)
            elif name == 'if':
                cond = self.parse_form()
                then_expr = self.parse_form()
                else_expr = None if self.peek()[0] == 'RPAREN' else self.parse_form()
                self.expect('RPAREN')
                return IfNode(cond=cond, then=then_expr, else_expr=else_expr)
            elif name == 'while':
                cond = self.parse_form()
                body = self._parse_forms_until_rparen()
                return WhileNode(cond=cond, body=body)
            elif name == 'foreach':
                var = self.parse_form()
                list_expr = self.parse_form()
                body = self._parse_forms_until_rparen()
                return ForeachNode(var=var, list_expr=list_expr, body=body)
            elif name == 'progn':
                return Progn(forms=self._parse_forms_until_rparen())
            elif name == 'lambda':
                args_tok = self.peek()
                args = []
                if args_tok[0] == 'LPAREN':
                    self.advance()
                    while self.peek()[0] not in ('RPAREN', 'EOF'):
                        arg = self.parse_form()
                        if isinstance(arg, Symbol):
                            args.append(arg.name)
                    self.expect('RPAREN')
                body = self._parse_forms_until_rparen()
                return LambdaNode(args=args, body=body)
            elif name == 'cond':
                return self._parse_cond()
            elif name in ('quote', 'function'):
                expr = self.parse_form()
                self.expect('RPAREN')
                return QuotedExpr(expr=expr)
            else:
                args = self._parse_forms_until_rparen()
                return Call(name=name, args=args)
        items = [head] + self._parse_forms_until_rparen()
        return ListExpr(items=items)

    def _parse_forms_until_rparen(self) -> List[Node]:
        forms = []
        while self.peek()[0] not in ('RPAREN', 'EOF'):
            forms.append(self.parse_form())
        self.expect('RPAREN')
        return forms

    def _parse_defun(self, kind: str) -> Defun:
        name_tok = self.parse_form()
        name = name_tok.name if isinstance(name_tok, Symbol) else str(name_tok)
        args = []
        locals_list = []
        if self.peek()[0] == 'LPAREN':
            self.advance()
            seen_slash = False
            while self.peek()[0] not in ('RPAREN', 'EOF'):
                tok = self.peek()
                if tok[0] == 'SYMBOL' and tok[1] == '/':
                    seen_slash = True
                    self.advance()
                    continue
                a = self.parse_form()
                if isinstance(a, Symbol):
                    if seen_slash:
                        locals_list.append(a.name)
                    else:
                        args.append(a.name)
            self.expect('RPAREN')
        body = []
        while self.peek()[0] != 'RPAREN':
            body.append(self.parse_form())
        self.expect('RPAREN')
        is_cmd = name.upper().startswith('C:')
        return Defun(name=name, args=args, locals=locals_list, body=body, is_command=is_cmd)

    def _parse_cond(self) -> Cond:
        clauses = []
        while self.peek()[0] != 'RPAREN':
            if self.peek()[0] == 'LPAREN':
                self.advance()
                clause_items = []
                while self.peek()[0] not in ('RPAREN', 'EOF'):
                    clause_items.append(self.parse_form())
                self.expect('RPAREN')
                clauses.append(tuple(clause_items))
            else:
                break
        self.expect('RPAREN')
        return Cond(clauses=clauses)
