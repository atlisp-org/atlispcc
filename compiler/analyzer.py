from typing import Dict, List, Set, Tuple, Optional
from compiler.ast import (
    Node,
    Program,
    Symbol,
    Integer,
    Real,
    String,
    ListExpr,
    QuotedExpr,
    Defun,
    Setq,
    IfNode,
    WhileNode,
    ForeachNode,
    RepeatNode,
    Call,
    Progn,
    LambdaNode,
    Cond,
)
from compiler.codegen import CodeGenerator, BytecodeBuffer
from compiler.symbol_table import SymbolTable


def count_instructions(func: Defun, symtab: SymbolTable) -> int:
    codegen = CodeGenerator(symtab)
    bytecode, _ = codegen.generate_function(func)
    return len(bytecode)


def _collect_call_names(node: Optional[Node], calls: Set[str]):
    if node is None:
        return
    if isinstance(node, Call):
        calls.add(node.name)
        for a in node.args:
            _collect_call_names(a, calls)
    elif isinstance(node, Setq):
        for _, v in node.pairs:
            _collect_call_names(v, calls)
    elif isinstance(node, IfNode):
        _collect_call_names(node.cond, calls)
        if node.then:
            _collect_call_names(node.then, calls)
        if node.else_expr:
            _collect_call_names(node.else_expr, calls)
    elif isinstance(node, WhileNode):
        _collect_call_names(node.cond, calls)
        for b in node.body:
            _collect_call_names(b, calls)
    elif isinstance(node, ForeachNode):
        _collect_call_names(node.var, calls)
        _collect_call_names(node.list_expr, calls)
        for b in node.body:
            _collect_call_names(b, calls)
    elif isinstance(node, RepeatNode):
        _collect_call_names(node.count, calls)
        for b in node.body:
            _collect_call_names(b, calls)
    elif isinstance(node, Progn):
        for f in node.forms:
            _collect_call_names(f, calls)
    elif isinstance(node, Cond):
        for cl in node.clauses:
            for c in cl:
                _collect_call_names(c, calls)
    elif isinstance(node, LambdaNode):
        for b in node.body:
            _collect_call_names(b, calls)


def _is_tail_call(node: Node, func_name: str) -> bool:
    if isinstance(node, Call) and node.name == func_name:
        return True
    if isinstance(node, IfNode):
        if node.then and _is_tail_call(node.then, func_name):
            return True
        if node.else_expr and _is_tail_call(node.else_expr, func_name):
            return True
        return False
    if isinstance(node, Cond):
        for clause in node.clauses:
            if clause:
                tail = clause[-1] if len(clause) > 1 else clause[0]
                if _is_tail_call(tail, func_name):
                    return True
        return False
    if isinstance(node, Progn):
        if node.forms:
            return _is_tail_call(node.forms[-1], func_name)
        return False
    return False


def find_tail_recursive(func: Defun) -> bool:
    if not func.body:
        return False
    return _is_tail_call(func.body[-1], func.name)


def estimate_constants(program: Program) -> int:
    count = 0

    def walk(node: Optional[Node]):
        nonlocal count
        if node is None:
            return
        if isinstance(node, (Integer, Real, String)):
            count += 1
        elif isinstance(node, Call):
            for a in node.args:
                walk(a)
        elif isinstance(node, Setq):
            for _, v in node.pairs:
                walk(v)
        elif isinstance(node, IfNode):
            walk(node.cond)
            if node.then:
                walk(node.then)
            if node.else_expr:
                walk(node.else_expr)
        elif isinstance(node, WhileNode):
            walk(node.cond)
            for b in node.body:
                walk(b)
        elif isinstance(node, ForeachNode):
            walk(node.var)
            walk(node.list_expr)
            for b in node.body:
                walk(b)
        elif isinstance(node, RepeatNode):
            walk(node.count)
            for b in node.body:
                walk(b)
        elif isinstance(node, Progn):
            for f in node.forms:
                walk(f)
        elif isinstance(node, Cond):
            for cl in node.clauses:
                for c in cl:
                    walk(c)
        elif isinstance(node, ListExpr):
            for i in node.items:
                walk(i)
        elif isinstance(node, QuotedExpr):
            if node.expr:
                walk(node.expr)
        elif isinstance(node, LambdaNode):
            for b in node.body:
                walk(b)

    for f in program.forms:
        if isinstance(f, Defun):
            for e in f.body:
                walk(e)
        else:
            walk(f)
    return count


def analyze(program: Program) -> Dict:
    symtab = SymbolTable()
    symtab.collect_symbols(program)

    defuns = [f for f in program.forms if isinstance(f, Defun)]
    other = [f for f in program.forms if not isinstance(f, Defun)]

    func_stats = []
    total_instructions = 0
    tail_recursive = []

    for f in defuns:
        inst_count = count_instructions(f, symtab)
        total_instructions += inst_count
        calls: Set[str] = set()
        for e in f.body:
            _collect_call_names(e, calls)

        is_tail_rec = find_tail_recursive(f)
        if is_tail_rec:
            tail_recursive.append(f.name)

        func_stats.append(
            {
                "name": f.name,
                "args": len(f.args),
                "locals": len(f.locals),
                "instructions": inst_count,
                "calls": sorted(calls) if calls else [],
                "tail_recursive": is_tail_rec,
            }
        )

    all_calls: Set[str] = set()
    for f in defuns:
        for e in f.body:
            _collect_call_names(e, all_calls)
    for e in other:
        _collect_call_names(e, all_calls)

    builtin_calls = {c for c in all_calls if c[0].islower() and c != "setq"}
    user_funcs = {f.name for f in defuns}
    extern_calls = builtin_calls - user_funcs

    return {
        "functions": len(defuns),
        "top_level_forms": len(other),
        "total_instructions": total_instructions,
        "constants_estimate": estimate_constants(program),
        "symbol_table_entries": len(symtab.entries),
        "function_offsets": len(symtab.function_offsets),
        "locals": sum(len(f.locals) for f in defuns),
        "tail_recursive_functions": tail_recursive,
        "functions_detail": func_stats,
        "builtin_calls": sorted(extern_calls),
    }
