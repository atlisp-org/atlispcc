from typing import List, Dict, Tuple, Any, Optional, Set
from compiler.ast import (
    Node, Program, Symbol, Integer, Real, String,
    ListExpr, QuotedExpr, Defun, Setq, IfNode, WhileNode,
    ForeachNode, RepeatNode, Call, Progn, LambdaNode, Cond,
    Defpackage, InPackage,
)
from compiler.packages import PackageTable, PACKAGE_SEP


BUILTIN_FUNCTIONS = {
    '+', '-', '*', '/', 'rem', '1+', '1-', '<', '<=', '>', '>=',
    '=', 'eq', 'equal', 'not', 'and', 'or', 'null', 'atom', 'listp',
    'numberp', 'strp', 'boundp', 'type', 'minusp', 'zerop',
    'car', 'cdr', 'caar', 'cadr', 'cdar', 'cddr', 'caddr', 'cadar',
    'cons', 'list', 'append', 'reverse', 'member', 'assoc', 'subst',
    'length', 'nth', 'subseq', 'last', 'vl-remove', 'vl-remove-if',
    'apply', 'mapcar', 'foreach', 'while', 'repeat', 'lambda', 'progn',
    'if', 'cond', 'setq', 'set', 'quote', 'function', 'eval',
    'progn', 'progn1', 'progn2',
    'strcat', 'substr', 'strlen', 'itoa', 'atoi', 'rtos', 'distof',
    'ascii', 'chr', 'strcase', 'vl-string-search', 'vl-string-subst',
    'polar', 'distance', 'angle', 'inters',
    'getvar', 'setvar', 'getenv', 'setenv',
    'vlax-get-property', 'vlax-put-property', 'vlax-invoke',
    'vlax-get-or-create-object', 'vlax-create-object', 'vlax-release-object',
    'vlax-make-variant', 'vlax-variant-value', 'vlax-safearray-fill',
    'vlax-safearray->list', 'vlax-ename->vla-object', 'vlax-vla-object->ename',
    'vl-cmdf', 'command', 'vl-bt',
    'princ', 'print', 'prin1', 'prompt', 'terpri', 'read', 'read-char',
    'write-line', 'write-char', 'load', 'eval',
    'entmake', 'entmakex', 'entget', 'entmod', 'entdel', 'entlast', 'entnext',
    'entsel', 'nentsel', 'nentselp', 'ssget', 'sslength', 'ssname', 'ssadd', 'ssdel', 'ssmemb',
    'tblnext', 'tblobjname', 'tblsearch', 'handent',
    'vport', 'trans', 'wcmatch', 'cond',
    'open', 'close', 'read-line', 'read-char', 'write-line', 'write-char',
    'findfile', 'getfiled',
    'startapp', 'vl-file-copy',
    'acad_strlsort', 'vl-sort', 'vl-sort-i',
    'dictadd', 'dictnext', 'dictremove', 'dictrename', 'dictsearch',
    'layoutlist',
    'axedyn-reaccreate', 'projet_pa_projet_ar_projet',
}


class SymbolTable:
    def __init__(self, package_table: Optional[PackageTable] = None):
        self.name_to_idx: Dict[str, int] = {}
        self.entries: List[Tuple[str, Any]] = []
        self.strings: List[str] = []
        self.function_offsets: Dict[str, int] = {}
        self.code_ref_bias = 0
        self.dispatch_stubs: Dict[str, int] = {}
        self.package_table = package_table or PackageTable()

    def get_or_add(self, name: str) -> int:
        name = str(name)
        if name not in self.name_to_idx:
            idx = len(self.entries)
            self.name_to_idx[name] = idx
            self.entries.append(('SYMBOL', name))
        return self.name_to_idx[name]

    def add_string(self, s: str) -> int:
        if isinstance(s, int) or s.lstrip('-').isdigit():
            return self.get_or_add(s)
        key = f'__str_{s}__'
        if key not in self.name_to_idx:
            idx = len(self.entries)
            self.name_to_idx[key] = idx
            self.entries.append(('STRING', s))
            self.strings.append(s)
        return self.name_to_idx[key]

    def add_int(self, value: int) -> int:
        key = f'__int_{value}__'
        if key not in self.name_to_idx:
            idx = len(self.entries)
            self.name_to_idx[key] = idx
            self.entries.append(('INT', value))
        return self.name_to_idx[key]

    def add_real(self, value: float) -> int:
        key = f'__real_{value}__'
        if key not in self.name_to_idx:
            idx = len(self.entries)
            self.name_to_idx[key] = idx
            self.entries.append(('REAL', value))
        return self.name_to_idx[key]

    def add_func_ref(self, name: str, offset: int):
        self.function_offsets[name] = offset
        self.get_or_add(name)

    @property
    def nsyms(self) -> int:
        base = len(self.entries)
        func_count = len(self.function_offsets)
        func_var_pos = max(base, 5)
        return max(base + func_count, func_var_pos + func_count)

    def resolve_name(self, name: str) -> str:
        if ':' in name:
            return self.package_table.resolve(name)
        return name

    def resolve_func_name(self, name: str) -> str:
        cur = self.package_table.current()
        if cur and name not in ('T', 'nil') and not name.startswith('C:') and not self.is_builtin(name):
            return self.package_table.munge(cur.name, name)
        return name

    def is_builtin(self, name: str) -> bool:
        return name.upper() in {n.upper() for n in BUILTIN_FUNCTIONS}

    def idx_of(self, name: str) -> Optional[int]:
        return self.name_to_idx.get(str(name))

    def collect_symbols(self, node: Node):
        if isinstance(node, Program):
            for form in node.forms:
                self.collect_symbols(form)
        elif isinstance(node, Defpackage):
            pass
        elif isinstance(node, InPackage):
            pass
        elif isinstance(node, Defun):
            resolved = self.resolve_func_name(node.name)
            self.get_or_add(resolved)
            for arg in node.args:
                self.get_or_add(arg)
            for loc in node.locals:
                self.get_or_add(loc)
            for expr in node.body:
                self.collect_symbols(expr)
        elif isinstance(node, Setq):
            for target, value in node.pairs:
                self.collect_symbols(target)
                if value:
                    self.collect_symbols(value)
        elif isinstance(node, IfNode):
            if node.cond:
                self.collect_symbols(node.cond)
            if node.then:
                self.collect_symbols(node.then)
            if node.else_expr:
                self.collect_symbols(node.else_expr)
        elif isinstance(node, WhileNode):
            self.collect_symbols(node.cond)
            for expr in node.body:
                self.collect_symbols(expr)
        elif isinstance(node, ForeachNode):
            if node.var:
                self.collect_symbols(node.var)
            if node.list_expr:
                self.collect_symbols(node.list_expr)
            for expr in node.body:
                self.collect_symbols(expr)
        elif isinstance(node, RepeatNode):
            if node.count:
                self.collect_symbols(node.count)
            for expr in node.body:
                self.collect_symbols(expr)
        elif isinstance(node, Call):
            call_name = node.name
            if ':' in call_name:
                call_name = self.resolve_name(call_name)
                node.name = call_name
            if not self.is_builtin(call_name) and call_name not in ('T', 'nil'):
                self.get_or_add(call_name)
            for arg in node.args:
                self.collect_symbols(arg)
        elif isinstance(node, Symbol):
            if node.name not in ('T', 'nil') and ':' in node.name:
                resolved = self.resolve_name(node.name)
                node.name = resolved
                self.get_or_add(resolved)
            elif node.name not in ('T', 'nil'):
                self.get_or_add(node.name)
        elif isinstance(node, String):
            self.add_string(node.value)
        elif isinstance(node, ListExpr):
            for item in node.items:
                self.collect_symbols(item)
        elif isinstance(node, QuotedExpr):
            if node.expr:
                self.collect_symbols(node.expr)
        elif isinstance(node, Progn):
            for form in node.forms:
                self.collect_symbols(form)
        elif isinstance(node, LambdaNode):
            for arg in node.args:
                self.get_or_add(arg)
            for expr in node.body:
                self.collect_symbols(expr)
        elif isinstance(node, Cond):
            for clause in node.clauses:
                for item in clause:
                    self.collect_symbols(item)
