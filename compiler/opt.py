"""AST optimization passes for the FAS4 compiler."""

from typing import Dict, List, Optional, Set, Tuple, Any, Union
from compiler.ast_nodes import (
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
    Defpackage,
    InPackage,
)

PURE_BUILTINS = {
    "+",
    "-",
    "*",
    "/",
    "rem",
    "1+",
    "1-",
    "=",
    "eq",
    "equal",
    "<",
    "<=",
    ">",
    ">=",
    "not",
    "null",
    "atom",
    "listp",
    "numberp",
    "strp",
    "boundp",
    "type",
    "minusp",
    "zerop",
    "car",
    "cdr",
    "caar",
    "cadr",
    "cdar",
    "cddr",
    "caddr",
    "cons",
    "list",
    "reverse",
    "member",
    "assoc",
    "subst",
    "length",
    "nth",
    "subseq",
    "last",
    "vl-remove",
    "strcat",
    "substr",
    "strlen",
    "itoa",
    "atoi",
    "rtos",
    "distof",
    "ascii",
    "chr",
    "strcase",
}


def is_constant(node: Node) -> bool:
    return isinstance(node, (Integer, Real, String)) or (isinstance(node, Symbol) and node.name in ("T", "nil"))


def _py_val(node: Node) -> Any:
    if isinstance(node, Integer):
        return node.value
    if isinstance(node, Real):
        return node.value
    if isinstance(node, String):
        return node.value
    if isinstance(node, Symbol):
        return None if node.name == "nil" else True
    return None


def _ast_val(val: Any) -> Node:
    if isinstance(val, bool):
        return Symbol("T" if val else "nil")
    if isinstance(val, int):
        return Integer(val)
    if isinstance(val, float):
        return Real(val)
    if isinstance(val, str):
        return String(val)
    if isinstance(val, (list, tuple)):
        return QuotedExpr(ListExpr(items=[_ast_val(v) for v in val]))
    if val is None:
        return Symbol("nil")
    return Symbol(str(val))


def eval_const_call(name: str, args: List[Node]) -> Optional[Node]:
    if name not in PURE_BUILTINS:
        return None
    if not all(is_constant(a) for a in args):
        return None
    py_args = [_py_val(a) for a in args]

    try:
        if name == "+":
            result = 0
            for a in py_args:
                result += a
            return _ast_val(result)
        if name == "-":
            if len(py_args) == 1:
                return _ast_val(-py_args[0])
            result = py_args[0]
            for a in py_args[1:]:
                result -= a
            return _ast_val(result)
        if name == "*":
            result = 1
            for a in py_args:
                result *= a
            return _ast_val(result)
        if name == "/":
            if all(isinstance(a, int) for a in py_args):
                result = py_args[0]
                for a in py_args[1:]:
                    result //= a
            else:
                result = py_args[0]
                for a in py_args[1:]:
                    result /= a
            return _ast_val(result)
        if name == "rem":
            return _ast_val(py_args[0] % py_args[1])
        if name == "1+":
            return _ast_val(py_args[0] + 1)
        if name == "1-":
            return _ast_val(py_args[0] - 1)

        if name in ("=", "eq", "equal"):
            return _ast_val(all(a == py_args[0] for a in py_args[1:]))
        if name in ("<",):
            for i in range(len(py_args) - 1):
                if not (py_args[i] < py_args[i + 1]):
                    return Symbol("nil")
            return Symbol("T")
        if name in ("<=",):
            for i in range(len(py_args) - 1):
                if not (py_args[i] <= py_args[i + 1]):
                    return Symbol("nil")
            return Symbol("T")
        if name in (">",):
            for i in range(len(py_args) - 1):
                if not (py_args[i] > py_args[i + 1]):
                    return Symbol("nil")
            return Symbol("T")
        if name in (">=",):
            for i in range(len(py_args) - 1):
                if not (py_args[i] >= py_args[i + 1]):
                    return Symbol("nil")
            return Symbol("T")

        if name == "not":
            return Symbol("T" if not py_args[0] else "nil")
        if name == "null":
            return Symbol("T" if py_args[0] is None else "nil")
        if name == "atom":
            return Symbol("T" if not isinstance(py_args[0], (list, tuple)) else "nil")
        if name == "zerop":
            return Symbol("T" if py_args[0] == 0 else "nil")
        if name == "minusp":
            return Symbol("T" if py_args[0] < 0 else "nil")
        if name == "numberp":
            return Symbol("T" if isinstance(py_args[0], (int, float)) else "nil")
        if name == "strp":
            return Symbol("T" if isinstance(py_args[0], str) else "nil")
        if name == "listp":
            return Symbol("T" if isinstance(py_args[0], (list, tuple)) or py_args[0] is None else "nil")
        if name == "boundp":
            return Symbol("T")

        if name in ("car", "cdr"):
            return Symbol("nil")
        if name in ("caar", "cadr", "cdar", "cddr", "caddr"):
            return Symbol("nil")

        if name == "cons":
            return QuotedExpr(ListExpr(items=[args[0], args[1]]))
        if name == "list":
            return QuotedExpr(ListExpr(items=list(args)))

        if name == "reverse":
            if isinstance(py_args[0], tuple):
                return _ast_val(list(reversed(py_args[0])))
            return Symbol("nil")
        if name == "length":
            if isinstance(py_args[0], (list, tuple)):
                return Integer(len(py_args[0]))
            return Symbol("nil")
        if name == "strlen":
            if isinstance(py_args[0], str):
                return Integer(len(py_args[0]))
            return Symbol("nil")
        if name == "strcat":
            return String("".join(py_args))
        if name == "itoa":
            return String(str(py_args[0]))
        if name == "atoi":
            return Integer(int(py_args[0]))
        if name == "ascii":
            if isinstance(py_args[0], str) and len(py_args[0]) > 0:
                return Integer(ord(py_args[0][0]))
            return Symbol("nil")
        if name == "chr":
            return String(chr(py_args[0]))
        if name == "strcase":
            return String(py_args[0].upper())
    except (TypeError, ValueError, ZeroDivisionError, IndexError):
        return None
    return None


def is_pure(node: Optional[Node]) -> bool:
    if node is None:
        return True
    if isinstance(node, (Integer, Real, String, Symbol)):
        return True
    if isinstance(node, Call):
        if node.name in PURE_BUILTINS:
            return all(is_pure(a) for a in node.args)
        return False
    if isinstance(node, ListExpr):
        return all(is_pure(item) for item in node.items)
    if isinstance(node, QuotedExpr):
        return is_pure(node.expr) if node.expr else True
    if isinstance(node, Progn):
        return all(is_pure(f) for f in node.forms)
    if isinstance(node, LambdaNode):
        return True
    if isinstance(node, Setq):
        return all(is_pure(v) for _, v in node.pairs)
    if isinstance(node, IfNode):
        return is_pure(node.cond) and is_pure(node.then) and (is_pure(node.else_expr) if node.else_expr else True)
    return False


# ─── Pass 1: Constant folding ─────────────────────────────────────────────


def _fold_call(call: Call) -> Node:
    args = [_fold_const(a) or a for a in call.args]
    result = eval_const_call(call.name, args)
    if result is not None:
        return result
    if any(a is not orig for a, orig in zip(args, call.args)):
        return Call(name=call.name, args=args)
    return call


def _fold_const(node: Optional[Node]) -> Optional[Node]:
    if node is None:
        return None
    if isinstance(node, Call):
        return _fold_call(node)
    if isinstance(node, Progn):
        forms = [_fold_const(f) or f for f in node.forms]
        return Progn(forms=forms)
    if isinstance(node, IfNode):
        cond = _fold_const(node.cond)
        then = _fold_const(node.then) if node.then else None
        else_expr = _fold_const(node.else_expr) if node.else_expr else None
        return IfNode(cond=cond, then=then, else_expr=else_expr)
    if isinstance(node, WhileNode):
        cond = _fold_const(node.cond)
        body = [_fold_const(f) or f for f in node.body]
        return WhileNode(cond=cond, body=body)
    if isinstance(node, ForeachNode):
        var = _fold_const(node.var)
        list_expr = _fold_const(node.list_expr)
        body = [_fold_const(f) or f for f in node.body]
        return ForeachNode(var=var, list_expr=list_expr, body=body)
    if isinstance(node, RepeatNode):
        count = _fold_const(node.count)
        body = [_fold_const(f) or f for f in node.body]
        return RepeatNode(count=count, body=body)
    if isinstance(node, Setq):
        pairs = [(t, _fold_const(v) or v) for t, v in node.pairs]
        return Setq(pairs=pairs)
    if isinstance(node, Cond):
        clauses = [tuple(_fold_const(c) or c for c in clause) for clause in node.clauses]
        return Cond(clauses=clauses)
    if isinstance(node, ListExpr):
        return ListExpr(items=[_fold_const(i) or i for i in node.items])
    if isinstance(node, QuotedExpr):
        return QuotedExpr(expr=_fold_const(node.expr) if node.expr else None)
    if isinstance(node, LambdaNode):
        return LambdaNode(args=node.args, body=[_fold_const(f) or f for f in node.body])
    return node


def constant_fold(program: Program) -> Program:
    forms: List[Node] = [f for f in (_fold_const(x) for x in program.forms) if f is not None]
    result: List[Node] = []
    for f in forms:
        if isinstance(f, Defun):
            result.append(
                Defun(
                    name=f.name,
                    args=f.args,
                    locals=f.locals,
                    body=[_fold_const(e) or e for e in f.body],
                    is_command=f.is_command,
                )
            )
        else:
            result.append(f)
    return Program(forms=result)


# ─── Pass 2: Dead branch elimination ──────────────────────────────────────


def _is_always_true(node: Optional[Node]) -> bool:
    return isinstance(node, Symbol) and node.name == "T"


def _is_always_false(node: Optional[Node]) -> bool:
    return isinstance(node, Symbol) and node.name == "nil" or (isinstance(node, Integer) and node.value == 0)


def _elim_dead_branches(node: Optional[Node]) -> Optional[Node]:
    if node is None:
        return None
    if isinstance(node, Call):
        args = [_elim_dead_branches(a) or a for a in node.args]
        return Call(name=node.name, args=args)
    if isinstance(node, IfNode):
        cond = _elim_dead_branches(node.cond)
        then = _elim_dead_branches(node.then) if node.then else None
        else_expr = _elim_dead_branches(node.else_expr) if node.else_expr else None
        if _is_always_true(cond):
            return then if then else Symbol("nil")
        if _is_always_false(cond):
            return else_expr if else_expr else Symbol("nil")
        return IfNode(cond=cond, then=then, else_expr=else_expr)
    if isinstance(node, WhileNode):
        cond = _elim_dead_branches(node.cond)
        body = [_elim_dead_branches(f) or f for f in node.body]
        if _is_always_false(cond):
            return Symbol("nil")
        return WhileNode(cond=cond, body=body)
    if isinstance(node, Cond):
        new_clauses = []
        for clause in node.clauses:
            if not clause:
                new_clauses.append(clause)
                continue
            c = _elim_dead_branches(clause[0]) or clause[0]
            actions = [_elim_dead_branches(a) or a for a in clause[1:]]
            if _is_always_true(c):
                if actions:
                    return Progn(forms=actions)
                return Symbol("nil")
            if not _is_always_false(c):
                new_clauses.append(tuple([c] + actions))
        if len(new_clauses) == 1:
            clause = new_clauses[0]
            if len(clause) == 1:
                return Symbol("nil")
            if len(clause) == 2:
                return clause[1]
            return Progn(forms=list(clause[1:]))
        return Cond(clauses=new_clauses)
    if isinstance(node, Progn):
        forms = [_elim_dead_branches(f) or f for f in node.forms]
        return Progn(forms=forms)
    if isinstance(node, Setq):
        pairs = [(t, _elim_dead_branches(v) or v) for t, v in node.pairs]
        return Setq(pairs=pairs)
    if isinstance(node, ListExpr):
        return ListExpr(items=[_elim_dead_branches(i) or i for i in node.items])
    if isinstance(node, QuotedExpr):
        return QuotedExpr(expr=_elim_dead_branches(node.expr) if node.expr else None)
    if isinstance(node, LambdaNode):
        return LambdaNode(args=node.args, body=[_elim_dead_branches(f) or f for f in node.body])
    if isinstance(node, ForeachNode):
        var = _elim_dead_branches(node.var)
        list_expr = _elim_dead_branches(node.list_expr)
        body = [_elim_dead_branches(f) or f for f in node.body]
        return ForeachNode(var=var, list_expr=list_expr, body=body)
    if isinstance(node, RepeatNode):
        count = _elim_dead_branches(node.count)
        body = [_elim_dead_branches(f) or f for f in node.body]
        return RepeatNode(count=count, body=body)
    return node


def dead_branch_elim(program: Program) -> Program:
    forms: List[Node] = [f for f in (_elim_dead_branches(x) for x in program.forms) if f is not None]
    result: List[Node] = []
    for f in forms:
        if isinstance(f, Defun):
            result.append(
                Defun(
                    name=f.name,
                    args=f.args,
                    locals=f.locals,
                    body=[_elim_dead_branches(e) or e for e in f.body],
                    is_command=f.is_command,
                )
            )
        else:
            result.append(f)
    return Program(forms=result)


# ─── Pass 3: Peephole optimization ────────────────────────────────────────


def _peephole(node: Optional[Node]) -> Optional[Node]:
    if node is None:
        return None
    if isinstance(node, Call):
        name = node.name
        args = [_peephole(a) or a for a in node.args]
        if name == "progn":
            if len(args) == 0:
                return Symbol("nil")
            if len(args) == 1:
                return args[0]
        if name in ("+", "*"):
            if len(args) == 1:
                return args[0]
        if name == "list":
            if len(args) == 0:
                return Symbol("nil")
        if name == "and":
            if len(args) == 0:
                return Symbol("T")
            if len(args) == 1:
                return args[0]
        if name == "or":
            if len(args) == 0:
                return Symbol("nil")
            if len(args) == 1:
                return args[0]
        if name == "not":
            if len(args) == 1:
                if isinstance(args[0], Symbol) and args[0].name == "nil":
                    return Symbol("T")
                if isinstance(args[0], Symbol) and args[0].name == "T":
                    return Symbol("nil")
        if name == "progn":
            simplified = []
            for a in args:
                if isinstance(a, Progn):
                    simplified.extend(a.forms)
                else:
                    simplified.append(a)
            if len(simplified) != len(args):
                return _peephole(Call(name="progn", args=simplified))
        return Call(name=name, args=args)
    if isinstance(node, Progn):
        forms = [_peephole(f) or f for f in node.forms]
        if not forms:
            return Symbol("nil")
        if len(forms) == 1:
            return forms[0]
        simplified = []
        for f in forms:
            if isinstance(f, Progn):
                simplified.extend(f.forms)
            else:
                simplified.append(f)
        if len(simplified) == 1:
            return simplified[0]
        return Progn(forms=simplified)
    if isinstance(node, IfNode):
        cond = _peephole(node.cond)
        then = _peephole(node.then) if node.then else None
        else_expr = _peephole(node.else_expr) if node.else_expr else None
        return IfNode(cond=cond, then=then, else_expr=else_expr)
    if isinstance(node, WhileNode):
        cond = _peephole(node.cond)
        body = [_peephole(f) or f for f in node.body]
        return WhileNode(cond=cond, body=body)
    if isinstance(node, ForeachNode):
        var = _peephole(node.var)
        list_expr = _peephole(node.list_expr)
        body = [_peephole(f) or f for f in node.body]
        return ForeachNode(var=var, list_expr=list_expr, body=body)
    if isinstance(node, RepeatNode):
        count = _peephole(node.count)
        body = [_peephole(f) or f for f in node.body]
        return RepeatNode(count=count, body=body)
    if isinstance(node, Cond):
        clauses = [tuple(_peephole(c) or c for c in clause) for clause in node.clauses]
        return Cond(clauses=clauses)
    if isinstance(node, Setq):
        pairs = [(t, _peephole(v) or v) for t, v in node.pairs]
        return Setq(pairs=pairs)
    if isinstance(node, Defun):
        body = [_peephole(e) or e for e in node.body]
        body = [e for e in body if not (isinstance(e, Symbol) and e.name == "nil")]
        if not body:
            body = [Symbol("nil")]
        return Defun(
            name=node.name,
            args=node.args,
            locals=node.locals,
            body=body,
            is_command=node.is_command,
        )
    if isinstance(node, ListExpr):
        return ListExpr(items=[_peephole(i) or i for i in node.items])
    if isinstance(node, QuotedExpr):
        return QuotedExpr(expr=_peephole(node.expr) if node.expr else None)
    if isinstance(node, LambdaNode):
        return LambdaNode(args=node.args, body=[_peephole(f) or f for f in node.body])
    return node


def peephole(program: Program) -> Program:
    forms: List[Node] = [f for f in (_peephole(x) for x in program.forms) if f is not None]
    return Program(forms=forms)


# ─── Pass 4: Dead assignment elimination ──────────────────────────────────


def _collect_var_refs(nodes: List[Node]) -> Set[str]:
    refs: Set[str] = set()

    def walk(node: Optional[Node]):
        if node is None:
            return
        if isinstance(node, Symbol):
            if node.name not in ("T", "nil"):
                refs.add(node.name)
        elif isinstance(node, Call):
            if node.name not in PURE_BUILTINS and node.name not in ("T", "nil", "setq"):
                refs.add(node.name)
            for a in node.args:
                walk(a)
        elif isinstance(node, Setq):
            for target, value in node.pairs:
                if isinstance(target, Symbol):
                    pass
                walk(value)
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
        elif isinstance(node, ListExpr):
            for i in node.items:
                walk(i)
        elif isinstance(node, Cond):
            for clause in node.clauses:
                for c in clause:
                    walk(c)
        elif isinstance(node, LambdaNode):
            for b in node.body:
                walk(b)

    for n in nodes:
        walk(n)
    return refs


def _elim_dead_assign(node: Optional[Node], referenced: Set[str], params: Set[str]) -> Optional[Node]:
    if node is None:
        return None
    if isinstance(node, Setq):
        if is_pure(node):
            live = [(t, _elim_dead_assign(v, referenced, params) or v) for t, v in node.pairs]
            live = [
                (t, v)
                for t, v in live
                if not (isinstance(t, Symbol) and t.name not in referenced and t.name not in params)
            ]
            if not live:
                return Symbol("nil")
            if (
                len(live) == 1
                and live[0][1] is not None
                and not (isinstance(live[0][0], Symbol) and live[0][0].name in referenced)
            ):
                return live[0][1]
            return Setq(pairs=live)
        return Setq(pairs=[(t, _elim_dead_assign(v, referenced, params) or v) for t, v in node.pairs])
    if isinstance(node, Call):
        return Call(name=node.name, args=[_elim_dead_assign(a, referenced, params) or a for a in node.args])
    if isinstance(node, Progn):
        forms = [_elim_dead_assign(f, referenced, params) or f for f in node.forms]
        return Progn(forms=forms)
    if isinstance(node, IfNode):
        return IfNode(
            cond=_elim_dead_assign(node.cond, referenced, params),
            then=_elim_dead_assign(node.then, referenced, params) if node.then else None,
            else_expr=_elim_dead_assign(node.else_expr, referenced, params) if node.else_expr else None,
        )
    if isinstance(node, WhileNode):
        return WhileNode(
            cond=_elim_dead_assign(node.cond, referenced, params),
            body=[_elim_dead_assign(b, referenced, params) or b for b in node.body],
        )
    if isinstance(node, ForeachNode):
        return ForeachNode(
            var=_elim_dead_assign(node.var, referenced, params),
            list_expr=_elim_dead_assign(node.list_expr, referenced, params),
            body=[_elim_dead_assign(b, referenced, params) or b for b in node.body],
        )
    if isinstance(node, RepeatNode):
        return RepeatNode(
            count=_elim_dead_assign(node.count, referenced, params),
            body=[_elim_dead_assign(b, referenced, params) or b for b in node.body],
        )
    if isinstance(node, Cond):
        return Cond(
            clauses=[tuple(_elim_dead_assign(c, referenced, params) or c for c in clause) for clause in node.clauses]
        )
    if isinstance(node, ListExpr):
        return ListExpr(items=[_elim_dead_assign(i, referenced, params) or i for i in node.items])
    if isinstance(node, LambdaNode):
        return LambdaNode(args=node.args, body=[_elim_dead_assign(b, referenced, params) or b for b in node.body])
    return node


def dead_assign_elim(program: Program) -> Program:
    forms: List[Node] = []
    for f in program.forms:
        if isinstance(f, Defun):
            referenced = _collect_var_refs(f.body)
            params = set(f.args)
            new_body: List[Node] = [
                e for e in (_elim_dead_assign(x, referenced, params) for x in f.body) if e is not None
            ]
            forms.append(
                Defun(
                    name=f.name,
                    args=f.args,
                    locals=f.locals,
                    body=new_body,
                    is_command=f.is_command,
                )
            )
        else:
            forms.append(f)
    return Program(forms=forms)


# ─── Pass 5: Constant propagation ──────────────────────────────────────────


def copy_node(node: Optional[Node]) -> Optional[Node]:
    if node is None:
        return None
    if isinstance(node, Integer):
        return Integer(node.value)
    if isinstance(node, Real):
        return Real(node.value)
    if isinstance(node, String):
        return String(node.value)
    if isinstance(node, Symbol):
        return Symbol(node.name)
    if isinstance(node, Call):
        return Call(name=node.name, args=[copy_node(a) or a for a in node.args])
    if isinstance(node, Progn):
        return Progn(forms=[copy_node(f) or f for f in node.forms])
    if isinstance(node, IfNode):
        return IfNode(
            cond=copy_node(node.cond) if node.cond else None,
            then=copy_node(node.then) if node.then else None,
            else_expr=copy_node(node.else_expr) if node.else_expr else None,
        )
    if isinstance(node, WhileNode):
        return WhileNode(cond=copy_node(node.cond), body=[copy_node(b) or b for b in node.body])
    if isinstance(node, ForeachNode):
        return ForeachNode(
            var=copy_node(node.var),
            list_expr=copy_node(node.list_expr),
            body=[copy_node(b) or b for b in node.body],
        )
    if isinstance(node, RepeatNode):
        return RepeatNode(
            count=copy_node(node.count),
            body=[copy_node(b) or b for b in node.body],
        )
    if isinstance(node, Setq):
        return Setq(pairs=[(copy_node(t) or t, copy_node(v) or v) for t, v in node.pairs])
    if isinstance(node, Cond):
        return Cond(clauses=[tuple(copy_node(c) or c for c in clause) for clause in node.clauses])
    if isinstance(node, ListExpr):
        return ListExpr(items=[copy_node(i) or i for i in node.items])
    if isinstance(node, QuotedExpr):
        return QuotedExpr(expr=copy_node(node.expr) if node.expr else None)
    if isinstance(node, LambdaNode):
        return LambdaNode(args=node.args, body=[copy_node(b) or b for b in node.body])
    return node


def _assigned_symbols(node) -> Set[str]:
    """收集节点内所有被赋值（setq / foreach 变量）的符号名。"""

    def walk(n, out: Set[str]):
        if isinstance(n, list):
            for item in n:
                walk(item, out)
        elif isinstance(n, Setq):
            for t, v in n.pairs:
                if isinstance(t, Symbol):
                    out.add(t.name)
                walk(v, out)
        elif isinstance(n, Call):
            for a in n.args:
                walk(a, out)
        elif isinstance(n, IfNode):
            walk(n.cond, out)
            if n.then:
                walk(n.then, out)
            if n.else_expr:
                walk(n.else_expr, out)
        elif isinstance(n, WhileNode):
            walk(n.cond, out)
            walk(n.body, out)
        elif isinstance(n, ForeachNode):
            if isinstance(n.var, Symbol):
                out.add(n.var.name)
            walk(n.list_expr, out)
            walk(n.body, out)
        elif isinstance(n, RepeatNode):
            walk(n.count, out)
            walk(n.body, out)
        elif isinstance(n, Progn):
            walk(n.forms, out)
        elif isinstance(n, Cond):
            for c in n.clauses:
                for item in c:
                    walk(item, out)
        elif isinstance(n, ListExpr):
            for i in n.items:
                walk(i, out)
        elif isinstance(n, QuotedExpr):
            if n.expr:
                walk(n.expr, out)
        elif isinstance(n, LambdaNode):
            walk(n.body, out)

    out: Set[str] = set()
    walk(node, out)
    return out


def _propagate_body(body: List[Node], params: Set[str]) -> List[Node]:
    const_map: Dict[str, Node] = {}

    def subst(node: Optional[Node]) -> Optional[Node]:
        if node is None:
            return None
        if isinstance(node, Symbol):
            if node.name in const_map and node.name not in params:
                return copy_node(const_map[node.name])
            return node
        if isinstance(node, Call):
            return Call(name=node.name, args=[subst(a) or a for a in node.args])
        if isinstance(node, Setq):
            pairs = [(subst(t) or t, subst(v) or v) for t, v in node.pairs]
            return Setq(pairs=pairs)
        if isinstance(node, IfNode):
            cond = subst(node.cond)
            then = subst(node.then) if node.then else None
            else_expr = subst(node.else_expr) if node.else_expr else None
            for v in _assigned_symbols(node):
                const_map.pop(v, None)
            return IfNode(cond=cond, then=then, else_expr=else_expr)
        if isinstance(node, WhileNode):
            loop_vars = _assigned_symbols(node.body)
            for v in loop_vars:
                const_map.pop(v, None)
            return WhileNode(cond=subst(node.cond), body=[subst(b) or b for b in node.body])
        if isinstance(node, ForeachNode):
            loop_vars = _assigned_symbols(node.body)
            if isinstance(node.var, Symbol):
                loop_vars.add(node.var.name)
            for v in loop_vars:
                const_map.pop(v, None)
            return ForeachNode(
                var=subst(node.var),
                list_expr=subst(node.list_expr),
                body=[subst(b) or b for b in node.body],
            )
        if isinstance(node, RepeatNode):
            loop_vars = _assigned_symbols(node.body)
            for v in loop_vars:
                const_map.pop(v, None)
            return RepeatNode(
                count=subst(node.count),
                body=[subst(b) or b for b in node.body],
            )
        if isinstance(node, Progn):
            forms = [subst(f) or f for f in node.forms]
            for v in _assigned_symbols(node):
                const_map.pop(v, None)
            return Progn(forms=forms)
        if isinstance(node, Cond):
            clauses = [tuple(subst(c) or c for c in clause) for clause in node.clauses]
            for v in _assigned_symbols(node):
                const_map.pop(v, None)
            return Cond(clauses=clauses)
        if isinstance(node, ListExpr):
            return ListExpr(items=[subst(i) or i for i in node.items])
        if isinstance(node, QuotedExpr):
            return QuotedExpr(expr=subst(node.expr) if node.expr else None)
        if isinstance(node, LambdaNode):
            return LambdaNode(args=node.args, body=[subst(b) or b for b in node.body])
        return node

    result: List[Node] = []
    for expr in body:
        if isinstance(expr, Setq):
            new_pairs = []
            for target, value in expr.pairs:
                sv = subst(value) or value
                if isinstance(target, Symbol) and is_constant(sv):
                    const_map[target.name] = sv
                elif isinstance(target, Symbol):
                    const_map.pop(target.name, None)
                new_pairs.append((target, sv))
            result.append(Setq(pairs=new_pairs))
        else:
            result.append(subst(expr) or expr)
    return result


def const_propagate(program: Program) -> Program:
    forms: List[Node] = []
    for f in program.forms:
        if isinstance(f, Defun):
            params = set(f.args)
            new_body = _propagate_body(f.body, params)
            forms.append(
                Defun(
                    name=f.name,
                    args=f.args,
                    locals=f.locals,
                    body=new_body,
                    is_command=f.is_command,
                )
            )
        else:
            forms.append(f)
    return Program(forms=forms)


# ─── Pass 6: Cross-function constant propagation ──────────────────────────


def _is_constant_func(func: Defun) -> Optional[Node]:
    if func.args or func.locals or len(func.body) != 1:
        return None
    body = func.body[0]
    if isinstance(body, (Integer, Real, String, Symbol)):
        return body
    return None


def _propagate_cross_func_in_body(body: List[Node], const_funcs: Dict[str, Node]) -> List[Node]:
    def subst(node: Optional[Node]) -> Optional[Node]:
        if node is None:
            return None
        if isinstance(node, Call):
            args = [subst(a) or a for a in node.args]
            if node.name in const_funcs and not args:
                return copy_node(const_funcs[node.name])
            return Call(name=node.name, args=args)
        if isinstance(node, Setq):
            return Setq(pairs=[(subst(t) or t, subst(v) or v) for t, v in node.pairs])
        if isinstance(node, IfNode):
            return IfNode(
                cond=subst(node.cond),
                then=subst(node.then) if node.then else None,
                else_expr=subst(node.else_expr) if node.else_expr else None,
            )
        if isinstance(node, WhileNode):
            return WhileNode(cond=subst(node.cond), body=[subst(b) or b for b in node.body])
        if isinstance(node, ForeachNode):
            return ForeachNode(
                var=subst(node.var),
                list_expr=subst(node.list_expr),
                body=[subst(b) or b for b in node.body],
            )
        if isinstance(node, RepeatNode):
            return RepeatNode(count=subst(node.count), body=[subst(b) or b for b in node.body])
        if isinstance(node, Progn):
            return Progn(forms=[subst(f) or f for f in node.forms])
        if isinstance(node, Cond):
            return Cond(clauses=[tuple(subst(c) or c for c in clause) for clause in node.clauses])
        if isinstance(node, ListExpr):
            return ListExpr(items=[subst(i) or i for i in node.items])
        if isinstance(node, QuotedExpr):
            return QuotedExpr(expr=subst(node.expr) if node.expr else None)
        if isinstance(node, LambdaNode):
            return LambdaNode(args=node.args, body=[subst(b) or b for b in node.body])
        return node

    return [subst(e) or e for e in body]


def cross_func_const_propagate(program: Program) -> Program:
    const_funcs: Dict[str, Node] = {}
    for f in program.forms:
        if isinstance(f, Defun) and not f.quoted:
            c = _is_constant_func(f)
            if c is not None:
                const_funcs[f.name] = c

    forms: List[Node] = []
    for f in program.forms:
        if isinstance(f, Defun):
            new_body = _propagate_cross_func_in_body(f.body, const_funcs)
            forms.append(
                Defun(
                    name=f.name,
                    args=f.args,
                    locals=f.locals,
                    body=new_body,
                    is_command=f.is_command,
                    quoted=f.quoted,
                )
            )
        else:
            forms.append(_propagate_cross_func_in_body([f], const_funcs)[0])
    return Program(forms=forms)


# ─── Pass 7: Dead code elimination ────────────────────────────────────────

TERMINAL_CALLS = {"exit", "quit", "abort"}


def _is_terminal(node: Node) -> bool:
    return isinstance(node, Call) and node.name in TERMINAL_CALLS


def _elim_dead_code_in_body(body: List[Node]) -> List[Node]:
    result: List[Node] = []
    for expr in body:
        result.append(_elim_dead_code(expr) or expr)
        if _is_terminal(expr):
            break
    return result


def _elim_dead_code(node: Optional[Node]) -> Optional[Node]:
    if node is None:
        return None
    if isinstance(node, Progn):
        forms = _elim_dead_code_in_body(node.forms)
        return Progn(forms=forms)
    if isinstance(node, IfNode):
        cond = _elim_dead_code(node.cond)
        then = _elim_dead_code(node.then) if node.then else None
        else_expr = _elim_dead_code(node.else_expr) if node.else_expr else None
        return IfNode(cond=cond, then=then, else_expr=else_expr)
    if isinstance(node, WhileNode):
        return WhileNode(
            cond=_elim_dead_code(node.cond),
            body=_elim_dead_code_in_body(node.body),
        )
    if isinstance(node, ForeachNode):
        return ForeachNode(
            var=_elim_dead_code(node.var),
            list_expr=_elim_dead_code(node.list_expr),
            body=_elim_dead_code_in_body(node.body),
        )
    if isinstance(node, RepeatNode):
        return RepeatNode(
            count=_elim_dead_code(node.count),
            body=_elim_dead_code_in_body(node.body),
        )
    if isinstance(node, Cond):
        return Cond(clauses=[tuple(_elim_dead_code(c) or c for c in clause) for clause in node.clauses])
    if isinstance(node, Setq):
        return Setq(pairs=[(t, _elim_dead_code(v) or v) for t, v in node.pairs])
    if isinstance(node, Call):
        return Call(name=node.name, args=[_elim_dead_code(a) or a for a in node.args])
    if isinstance(node, ListExpr):
        return ListExpr(items=[_elim_dead_code(i) or i for i in node.items])
    if isinstance(node, LambdaNode):
        return LambdaNode(args=node.args, body=_elim_dead_code_in_body(node.body))
    return node


def dead_code_elim(program: Program) -> Program:
    forms: List[Node] = []
    for f in program.forms:
        if isinstance(f, Defun):
            forms.append(
                Defun(
                    name=f.name,
                    args=f.args,
                    locals=f.locals,
                    body=_elim_dead_code_in_body(f.body),
                    is_command=f.is_command,
                )
            )
        else:
            forms.append(_elim_dead_code(f) or f)
    return Program(forms=forms)


# ─── Pass 7: Small function inlining (O3) ────────────────────────────────


def _count_calls(program: Program) -> Dict[str, int]:
    counts: Dict[str, int] = {}

    def walk(node: Optional[Node]):
        if node is None:
            return
        if isinstance(node, Call):
            counts[node.name] = counts.get(node.name, 0) + 1
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
            for c in node.clauses:
                for item in c:
                    walk(item)
        elif isinstance(node, ListExpr):
            for i in node.items:
                walk(i)
        elif isinstance(node, LambdaNode):
            for b in node.body:
                walk(b)

    for f in program.forms:
        if isinstance(f, Defun):
            for e in f.body:
                walk(e)
        else:
            walk(f)
    return counts


def _inline_defun(call: Call, func: Defun, call_counts: Dict[str, int]) -> Optional[Node]:
    if func.locals:
        return None
    if len(func.body) > 5:
        return None
    if len(call.args) != len(func.args):
        return None

    body = [copy_node(e) or e for e in func.body]

    def _rename_args(node: Optional[Node], arg_map: Dict[str, Node]) -> Optional[Node]:
        if node is None:
            return None
        if isinstance(node, Symbol):
            if node.name in arg_map:
                return copy_node(arg_map[node.name])
            return node
        if isinstance(node, Call):
            return Call(name=node.name, args=[_rename_args(a, arg_map) or a for a in node.args])
        if isinstance(node, Setq):
            return Setq(pairs=[(_rename_args(t, arg_map) or t, _rename_args(v, arg_map) or v) for t, v in node.pairs])
        if isinstance(node, IfNode):
            cond = _rename_args(node.cond, arg_map)
            then = _rename_args(node.then, arg_map) if node.then else None
            else_expr = _rename_args(node.else_expr, arg_map) if node.else_expr else None
            return IfNode(cond=cond, then=then, else_expr=else_expr)
        if isinstance(node, WhileNode):
            return WhileNode(
                cond=_rename_args(node.cond, arg_map),
                body=[_rename_args(b, arg_map) or b for b in node.body],
            )
        if isinstance(node, ForeachNode):
            return ForeachNode(
                var=_rename_args(node.var, arg_map),
                list_expr=_rename_args(node.list_expr, arg_map),
                body=[_rename_args(b, arg_map) or b for b in node.body],
            )
        if isinstance(node, RepeatNode):
            return RepeatNode(
                count=_rename_args(node.count, arg_map),
                body=[_rename_args(b, arg_map) or b for b in node.body],
            )
        if isinstance(node, Progn):
            return Progn(forms=[_rename_args(f, arg_map) or f for f in node.forms])
        if isinstance(node, Cond):
            return Cond(clauses=[tuple(_rename_args(c, arg_map) or c for c in clause) for clause in node.clauses])
        if isinstance(node, ListExpr):
            return ListExpr(items=[_rename_args(i, arg_map) or i for i in node.items])
        if isinstance(node, QuotedExpr):
            return QuotedExpr(expr=_rename_args(node.expr, arg_map) if node.expr else None)
        if isinstance(node, LambdaNode):
            return LambdaNode(args=node.args, body=[_rename_args(b, arg_map) or b for b in node.body])
        return node

    arg_map = {}
    for param, arg in zip(func.args, call.args):
        arg_map[param] = arg

    inlined = [_rename_args(e, arg_map) or e for e in body]
    if len(inlined) == 1:
        return inlined[0]
    return Progn(forms=inlined)


def _inline_in_node(node: Optional[Node], funcs: Dict[str, Defun], call_counts: Dict[str, int]) -> Optional[Node]:
    if node is None:
        return None
    if isinstance(node, Call):
        args = [_inline_in_node(a, funcs, call_counts) or a for a in node.args]
        if node.name in funcs:
            inlined = _inline_defun(Call(name=node.name, args=args), funcs[node.name], call_counts)
            if inlined is not None:
                return inlined
        return Call(name=node.name, args=args)
    if isinstance(node, Progn):
        return Progn(forms=[_inline_in_node(f, funcs, call_counts) or f for f in node.forms])
    if isinstance(node, IfNode):
        return IfNode(
            cond=_inline_in_node(node.cond, funcs, call_counts),
            then=_inline_in_node(node.then, funcs, call_counts) if node.then else None,
            else_expr=_inline_in_node(node.else_expr, funcs, call_counts) if node.else_expr else None,
        )
    if isinstance(node, WhileNode):
        return WhileNode(
            cond=_inline_in_node(node.cond, funcs, call_counts),
            body=[_inline_in_node(b, funcs, call_counts) or b for b in node.body],
        )
    if isinstance(node, ForeachNode):
        return ForeachNode(
            var=_inline_in_node(node.var, funcs, call_counts),
            list_expr=_inline_in_node(node.list_expr, funcs, call_counts),
            body=[_inline_in_node(b, funcs, call_counts) or b for b in node.body],
        )
    if isinstance(node, RepeatNode):
        return RepeatNode(
            count=_inline_in_node(node.count, funcs, call_counts),
            body=[_inline_in_node(b, funcs, call_counts) or b for b in node.body],
        )
    if isinstance(node, Cond):
        return Cond(
            clauses=[tuple(_inline_in_node(c, funcs, call_counts) or c for c in clause) for clause in node.clauses]
        )
    if isinstance(node, Setq):
        return Setq(pairs=[(t, _inline_in_node(v, funcs, call_counts) or v) for t, v in node.pairs])
    if isinstance(node, ListExpr):
        return ListExpr(items=[_inline_in_node(i, funcs, call_counts) or i for i in node.items])
    if isinstance(node, LambdaNode):
        return LambdaNode(args=node.args, body=[_inline_in_node(b, funcs, call_counts) or b for b in node.body])
    return node


def _collect_quoted_symbols(program: Program) -> Set[str]:
    """收集引号形式中出现的符号名（如 `apply`/`mapcar 'foo` 的函数引用）。

    保守策略：引号内的符号一律视为潜在函数引用，避免误删被
    apply/mapcar/funcall 等间接调用的函数。
    """

    def collect_in(node):
        if node is None:
            return
        if isinstance(node, Symbol):
            refs.add(node.name)
        elif isinstance(node, ListExpr):
            for i in node.items:
                collect_in(i)
            collect_in(node.dotted)
        elif isinstance(node, QuotedExpr):
            collect_in(node.expr)

    def walk(node: Optional[Node]) -> None:
        if node is None:
            return
        if isinstance(node, QuotedExpr):
            collect_in(node.expr)
            return
        if isinstance(node, Call):
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
            for c in node.clauses:
                for item in c:
                    walk(item)
        elif isinstance(node, ListExpr):
            for i in node.items:
                walk(i)
        elif isinstance(node, LambdaNode):
            for b in node.body:
                walk(b)

    refs: Set[str] = set()
    for f in program.forms:
        if isinstance(f, Defun):
            for e in f.body:
                walk(e)
        else:
            walk(f)
    return refs


def remove_dead_functions(program: Program) -> Program:
    """移除未被引用且非命令的函数。

    仅当程序存在明确的入口点（至少一个 C: 命令或顶层代码）时才移除——
    纯库文件（只有 defun，无命令/顶层代码）无法判断哪些函数会被外部
    调用，因此一律保留，避免误删入口/导出函数。
    """
    has_entry = any(
        (isinstance(f, Defun) and f.is_command) or not isinstance(f, (Defun, Defpackage, InPackage))
        for f in program.forms
    )
    if not has_entry:
        return program

    call_counts = _count_calls(program)
    quoted_refs = _collect_quoted_symbols(program)
    forms: List[Node] = []
    for f in program.forms:
        if isinstance(f, Defun):
            if f.name not in call_counts and f.name not in quoted_refs and not f.is_command:
                continue
        forms.append(f)
    return Program(forms=forms)


def inline_small_funcs(program: Program) -> Program:
    call_counts = _count_calls(program)
    funcs: Dict[str, Defun] = {}
    for f in program.forms:
        if isinstance(f, Defun) and not f.is_command and not f.quoted:
            if f.name in call_counts and call_counts[f.name] == 1 and len(f.body) <= 5 and not f.locals:
                funcs[f.name] = f

    result: List[Node] = []
    for f in program.forms:
        if isinstance(f, Defun) and f.name in funcs:
            result.append(f)
        elif isinstance(f, Defun):
            new_body = [_inline_in_node(e, funcs, call_counts) or e for e in f.body]
            result.append(
                Defun(
                    name=f.name,
                    args=f.args,
                    locals=f.locals,
                    body=new_body,
                    is_command=f.is_command,
                    quoted=f.quoted,
                )
            )
        else:
            result.append(_inline_in_node(f, funcs, call_counts) or f)

    cleaned: List[Node] = []
    for f in result:
        if isinstance(f, Defun) and f.name in funcs:
            call_counts.pop(f.name, None)
            continue
        cleaned.append(f)
    return Program(forms=cleaned)


# ─── Main entry point ─────────────────────────────────────────────────────


def optimize(program: Program, level: int = 1) -> Program:
    if level >= 1:
        program = constant_fold(program)
        program = dead_branch_elim(program)
        program = peephole(program)
    if level >= 2:
        program = dead_assign_elim(program)
        program = const_propagate(program)
        program = constant_fold(program)
        program = peephole(program)
    if level >= 3:
        program = cross_func_const_propagate(program)
        program = dead_code_elim(program)
        program = inline_small_funcs(program)
        program = remove_dead_functions(program)
        program = constant_fold(program)
        program = dead_branch_elim(program)
        program = peephole(program)
        program = dead_assign_elim(program)
        program = const_propagate(program)
        program = constant_fold(program)
        program = peephole(program)
    return program
