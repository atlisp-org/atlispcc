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
    # 引用包装符号名：'function'（来自 `(function X)`/`#'X`）或 'quote'
    # （来自 `'X`）。在**引用上下文内**（更大的 quoted 数据里嵌套
    # `'(function (lambda ...))` 或 `''(...)`），kwote 恒为 False（数据），
    # CAD 仍按源符号分别注册 FUNCTION/QUOTE 叶子（setup.lsp kernel golden
    # 用 FUNCTION、text/get-matrix 用 QUOTE 实测），须保留 wrapper 区别。
    # None = 未显式区分（默认按 kwote 推断）。
    wrap: Optional[str] = None


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
    name: str = 'foreach'


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


@dataclass
class CondDefunBind(Node):
    """顶层 if 内条件 `(defun ...)` 的运行时绑定标记。

    由 `_hoist_conditional_defuns` 在提升 defun 时留在 if 的 then 分支：
    defun 体已提升为顶层函数（进 seg0 + DEFCODE），if 内仅保留该标记，
    模块代码编译时发射 CAD 命令注册字节
    ``JUMP +0; PUSH_G <func-obj>; SETQ_G <sym>; PUSH_G <sym>;
    USUBR(1, vl-ACAD-defun); PUSH_NIL; POP``（panel.lsp CAD 实测绑定留在
    `if is-gcad` 守卫内）。符号收集器忽略此节点（名字已由顶层 defun 注册）。
    """

    name: str = ''
