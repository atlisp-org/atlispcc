from dataclasses import dataclass, field
from typing import List, Any, Optional


@dataclass
class Node:
    pass


@dataclass
class Program(Node):
    forms: List['Node'] = field(default_factory=list)


@dataclass
class Symbol(Node):
    name: str = ''


@dataclass
class Integer(Node):
    value: int = 0


@dataclass
class Real(Node):
    value: float = 0.0


@dataclass
class String(Node):
    value: str = ''


@dataclass
class ListExpr(Node):
    items: List['Node'] = field(default_factory=list)


@dataclass
class QuotedExpr(Node):
    expr: Optional['Node'] = None


@dataclass
class Defun(Node):
    name: str = ''
    args: List[str] = field(default_factory=list)
    locals: List[str] = field(default_factory=list)
    body: List['Node'] = field(default_factory=list)
    is_command: bool = False


@dataclass
class Setq(Node):
    target: Optional['Node'] = None
    value: Optional['Node'] = None


@dataclass
class IfNode(Node):
    cond: Optional['Node'] = None
    then: Optional['Node'] = None
    else_expr: Optional['Node'] = None


@dataclass
class WhileNode(Node):
    cond: Optional['Node'] = None
    body: List['Node'] = field(default_factory=list)


@dataclass
class ForeachNode(Node):
    var: Optional['Node'] = None
    list_expr: Optional['Node'] = None
    body: List['Node'] = field(default_factory=list)


@dataclass
class Call(Node):
    name: str = ''
    args: List['Node'] = field(default_factory=list)


@dataclass
class Progn(Node):
    forms: List['Node'] = field(default_factory=list)


@dataclass
class LambdaNode(Node):
    args: List[str] = field(default_factory=list)
    body: List['Node'] = field(default_factory=list)


@dataclass
class Cond(Node):
    clauses: List[tuple] = field(default_factory=list)
