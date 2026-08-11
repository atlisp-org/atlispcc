from typing import List, Optional
from compiler.lexer import tokenize, Token
from compiler.ast_nodes import (
    Node, Program, Symbol, Integer, Real, String,
    ListExpr, QuotedExpr, Defun, Setq, IfNode, WhileNode,
    ForeachNode, RepeatNode, Call, Progn, LambdaNode, Cond,
    Defpackage, InPackage,
)
from compiler.packages import PackageTable


class ParseError(Exception):
    pass


class Parser:
    def __init__(self, source: str, package_table: Optional[PackageTable] = None):
        self.tokens: List[Token] = tokenize(source)
        self.pos = 0
        self.packages = package_table or PackageTable()

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

    def parse_form(self, quoted: bool = False) -> Node:
        tok = self.peek()
        kind, val, _, _ = tok
        if kind == 'LPAREN':
            return self.parse_list(quoted)
        elif kind == 'QUOTE':
            self.advance()
            return QuotedExpr(expr=self.parse_form(quoted=True))
        elif kind == 'FUNCTION':
            self.advance()
            # `(function X)`：CAD 编译为 kwote 机制（内部 DEFUN/符号引用），
            # 区别于 `'X` 的资源段常量。kwote=True 标记。
            return QuotedExpr(expr=self.parse_form(quoted=True), kwote=True)
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

    def parse_list(self, quoted: bool = False) -> Node:
        self.expect('LPAREN')
        if self.peek()[0] == 'RPAREN':
            self.advance()
            return ListExpr()
        head = self.parse_form(quoted)
        if isinstance(head, Symbol):
            name = head.name
            if quoted and self.peek()[0] == 'RPAREN' and name in (
                'defun', 'defun-q', 'setq', 'if', 'while', 'foreach',
                'repeat', 'progn', 'cond', 'defpackage', 'in-package',
                'lambda', 'quote', 'function', 'set',
            ):
                # 裸引用关键字 `'(defun)`、`'(lambda)`、`'(setq)`、`'(cond)`
                # 是普通数据列表（@::safe-form-p 白名单比对用），不按特殊形式
                # 解析（否则 `'(defun)` 会因缺函数名报错、`'(lambda)`/`'(setq)`
                # 会解析成空结构节点）。
                self.expect('RPAREN')
                return ListExpr(items=[head])
            if name == 'defun' or name == 'defun-q':
                return self._parse_defun(name)
            elif name == 'setq':
                pairs: List[tuple] = []
                while self.peek()[0] != 'RPAREN':
                    target = self.parse_form(quoted)
                    if self.peek()[0] == 'RPAREN':
                        pairs.append((target, None))
                    else:
                        pairs.append((target, self.parse_form(quoted)))
                self.expect('RPAREN')
                return Setq(pairs=pairs)
            elif name == 'if':
                cond = self.parse_form(quoted)
                then_expr = self.parse_form(quoted)
                else_expr = None if self.peek()[0] == 'RPAREN' else self.parse_form(quoted)
                self.expect('RPAREN')
                return IfNode(cond=cond, then=then_expr, else_expr=else_expr)
            elif name == 'while':
                cond = self.parse_form(quoted)
                body = self._parse_forms_until_rparen(quoted)
                return WhileNode(cond=cond, body=body)
            elif name == 'foreach':
                var = self.parse_form(quoted)
                list_expr = self.parse_form(quoted)
                body = self._parse_forms_until_rparen(quoted)
                return ForeachNode(var=var, list_expr=list_expr, body=body)
            elif name == 'repeat':
                count = self.parse_form(quoted)
                body = self._parse_forms_until_rparen(quoted)
                return RepeatNode(count=count, body=body)
            elif name == 'progn':
                return Progn(forms=self._parse_forms_until_rparen(quoted))
            elif name == 'lambda':
                args_tok = self.peek()
                args = []
                if args_tok[0] == 'LPAREN':
                    self.advance()
                    while self.peek()[0] not in ('RPAREN', 'EOF'):
                        arg = self.parse_form(quoted)
                        if isinstance(arg, Symbol):
                            args.append(arg.name)
                    self.expect('RPAREN')
                body = self._parse_forms_until_rparen(quoted)
                return LambdaNode(args=args, body=body)
            elif name == 'cond':
                return self._parse_cond(quoted)
            elif name == 'defpackage':
                return self._parse_defpackage()
            elif name == 'in-package':
                name_tok = self.parse_form(quoted)
                pkg_name = name_tok.name if isinstance(name_tok, Symbol) else str(name_tok)
                self.expect('RPAREN')
                self.packages.set_current(pkg_name)
                return InPackage(name=pkg_name)
            elif name in ('quote', 'function'):
                expr = self.parse_form(quoted=True)
                self.expect('RPAREN')
                return QuotedExpr(expr=expr, kwote=(name == 'function'))
            else:
                items, dotted = self._parse_items_until_rparen(quoted)
                if dotted is not None:
                    if quoted:
                        return ListExpr(items=[head] + items, dotted=dotted)
                    return Call(name=name, args=items + [dotted])
                return Call(name=name, args=items)
        items, dotted = self._parse_items_until_rparen(quoted)
        return ListExpr(items=[head] + items, dotted=dotted)

    def _parse_forms_until_rparen(self, quoted: bool = False) -> List[Node]:
        items, dotted = self._parse_items_until_rparen(quoted)
        if dotted is not None:
            raise ParseError('Unexpected dotted pair')
        return items

    def _parse_items_until_rparen(self, quoted: bool = False) -> "tuple[List[Node], Optional[Node]]":
        items: List[Node] = []
        dotted: Optional[Node] = None
        while self.peek()[0] not in ('RPAREN', 'EOF'):
            if self.peek()[0] == 'DOT':
                self.advance()
                dotted = self.parse_form(quoted)
                if self.peek()[0] != 'RPAREN':
                    raise ParseError('Dotted pair must be the last element')
                break
            items.append(self.parse_form(quoted))
        self.expect('RPAREN')
        return items, dotted

    def _parse_defun(self, kind: str) -> Defun:
        name_tok = self.parse_form()
        raw_name = name_tok.name if isinstance(name_tok, Symbol) else str(name_tok)
        cur = self.packages.current()
        if cur and not raw_name.upper().startswith('C:') and ':' not in raw_name:
            name = self.packages.munge(cur.name, raw_name)
        else:
            name = raw_name
        args = []
        optional_list = []
        rest_var = None
        locals_list = []
        if self.peek()[0] == 'LPAREN':
            self.advance()
            seen_slash = False
            in_optional = False
            while self.peek()[0] not in ('RPAREN', 'EOF'):
                tok = self.peek()
                if tok[0] == 'SYMBOL' and tok[1] == '/':
                    seen_slash = True
                    in_optional = False
                    self.advance()
                    continue
                if tok[0] == 'SYMBOL' and tok[1].lower() == '&optional':
                    in_optional = True
                    self.advance()
                    continue
                if tok[0] == 'SYMBOL' and tok[1].lower() == '&rest':
                    in_optional = False
                    self.advance()
                    a = self.parse_form()
                    if isinstance(a, Symbol):
                        rest_var = a.name
                    elif rest_var is None:
                        rest_var = 'args'
                    continue
                a = self.parse_form()
                if isinstance(a, Symbol):
                    if seen_slash:
                        locals_list.append(a.name)
                    elif in_optional:
                        optional_list.append(a.name)
                    else:
                        args.append(a.name)
            self.expect('RPAREN')
        body = []
        while self.peek()[0] != 'RPAREN':
            body.append(self.parse_form())
        self.expect('RPAREN')
        is_cmd = name.upper().startswith('C:')
        return Defun(name=name, args=args, optional=optional_list, rest=rest_var,
                     locals=locals_list, body=body,
                     is_command=is_cmd, quoted=(kind == 'defun-q'))

    def _parse_defpackage(self) -> Defpackage:
        name_tok = self.parse_form()
        pkg_name = name_tok.name if isinstance(name_tok, Symbol) else str(name_tok)
        use = []
        export = []
        while self.peek()[0] not in ('RPAREN', 'EOF'):
            opt = self.parse_form()
            if isinstance(opt, Call) and opt.name in (':use', 'use', ':export', 'export'):
                items = [a.name for a in opt.args if isinstance(a, Symbol)]
                if opt.name in (':use', 'use'):
                    use.extend(items)
                else:
                    export.extend(items)
            elif isinstance(opt, Symbol):
                opt_name = opt.name
                if opt_name in (':use', 'use'):
                    if self.peek()[0] == 'LPAREN':
                        self.advance()
                        while self.peek()[0] not in ('RPAREN', 'EOF'):
                            sym = self.parse_form()
                            if isinstance(sym, Symbol):
                                use.append(sym.name)
                        self.expect('RPAREN')
                    else:
                        sym = self.parse_form()
                        if isinstance(sym, Symbol):
                            use.append(sym.name)
                elif opt_name in (':export', 'export'):
                    if self.peek()[0] == 'LPAREN':
                        self.advance()
                        while self.peek()[0] not in ('RPAREN', 'EOF'):
                            sym = self.parse_form()
                            if isinstance(sym, Symbol):
                                export.append(sym.name)
                        self.expect('RPAREN')
                    else:
                        sym = self.parse_form()
                        if isinstance(sym, Symbol):
                            export.append(sym.name)
        self.expect('RPAREN')
        self.packages.add_package(pkg_name, use, export)
        return Defpackage(name=pkg_name, use=use, export=export)

    def _parse_cond(self, quoted: bool = False) -> Cond:
        clauses = []
        while self.peek()[0] != 'RPAREN':
            if self.peek()[0] == 'LPAREN':
                self.advance()
                clause_items = []
                while self.peek()[0] not in ('RPAREN', 'EOF'):
                    clause_items.append(self.parse_form(quoted))
                self.expect('RPAREN')
                clauses.append(tuple(clause_items))
            else:
                break
        self.expect('RPAREN')
        return Cond(clauses=clauses)
