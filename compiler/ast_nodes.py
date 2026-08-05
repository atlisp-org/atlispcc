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
    dotted: Optional['Node'] = None


@dataclass
class QuotedExpr(Node):
    expr: Optional['Node'] = None
    # `(function X)` 语法（AutoLISP 引用函数）：CAD 编译为内部嵌套 DEFUN +
    # kwote/-lambda- 机制，区别于 `'X`（quote，注册为资源段常量）。
    # kwote=True 表示来自 `(function ...)` 而非 `'...`。
    kwote: bool = False


@dataclass
class Defun(Node):
    name: str = ''
    args: List[str] = field(default_factory=list)
    optional: List[str] = field(default_factory=list)
    rest: Optional[str] = None
    locals: List[str] = field(default_factory=list)
    body: List['Node'] = field(default_factory=list)
    is_command: bool = False
    quoted: bool = False


@dataclass
class Setq(Node):
    pairs: List[tuple] = field(default_factory=list)


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
class RepeatNode(Node):
    count: Optional['Node'] = None
    body: List['Node'] = field(default_factory=list)


@dataclass
class Cond(Node):
    clauses: List[tuple] = field(default_factory=list)


@dataclass
class Defpackage(Node):
    name: str = ''
    use: List[str] = field(default_factory=list)
    export: List[str] = field(default_factory=list)


@dataclass
class InPackage(Node):
    name: str = ''
