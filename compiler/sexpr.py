"""配置文件 S 表达式读取助手（pkg.lsp / .prj / .prv 共用）。

基于 :mod:`compiler.parser` 的 AST 约定：

- 关键字 ``:KEY`` 解析为 ``Symbol(name=':KEY')``
- 字符串 → ``String(value=...)``，整数 → ``Integer``
- ``(a b c)`` 在 head 是符号时解析为 ``Call(name='a', args=[b, c])``，
  否则为 ``ListExpr(items=[...])``

注意 ``Call`` 的 head 不在 ``args`` 里：需要 ``[head, *args]`` 形式的关键字
列表用 :func:`sequence`，只想要元素（``(LIST "a")`` 的函数名要丢掉）时用
:func:`args_of`。
"""

from __future__ import annotations

from typing import Any, List, Optional


def head_name(node: Any) -> str:
    """``Call``/``ListExpr`` 的 head 符号名；其它返回空串。"""
    from compiler.ast_nodes import Call, ListExpr, Symbol

    if isinstance(node, Call):
        return node.name
    if isinstance(node, ListExpr) and node.items and isinstance(node.items[0], Symbol):
        return node.items[0].name
    return ""


def sequence(node: Any) -> List[Any]:
    """``[head, *args]``：保留 ``Call`` 的 head（关键字列表需要）。"""
    from compiler.ast_nodes import Call, ListExpr, Symbol

    if isinstance(node, Call):
        return [Symbol(node.name)] + list(node.args)
    if isinstance(node, ListExpr):
        return list(node.items)
    if node is None:
        return []
    return [node]


def args_of(node: Any) -> List[Any]:
    """``Call`` 的 ``args``（丢弃 head）；``ListExpr`` 的全部元素。"""
    from compiler.ast_nodes import Call, ListExpr

    if isinstance(node, Call):
        return list(node.args)
    if isinstance(node, ListExpr):
        return list(node.items)
    if node is None:
        return []
    return [node]


#: ``sequence`` 的别名：用于 ``:PROJECT-KEYS`` 这类关键字列表。
keyword_sequence = sequence


def keyword(node: Any) -> Optional[str]:
    """``Symbol(':NAME')`` → ``'NAME'``（大写，去冒号）。"""
    from compiler.ast_nodes import Symbol

    if isinstance(node, Symbol) and node.name.startswith(":"):
        return node.name[1:].upper()
    return None


def text(node: Any) -> Optional[str]:
    """字符串 / 符号的字面文本。"""
    from compiler.ast_nodes import String, Symbol

    if isinstance(node, String):
        return node.value
    if isinstance(node, Symbol):
        return node.name
    return None


def truth(node: Any) -> Optional[bool]:
    """``T`` → True、``nil``/``()`` → False、其它 → None。"""
    value = text(node)
    if value is None:
        return None
    lowered = value.lower()
    if lowered == "t":
        return True
    if lowered in ("nil", "()"):
        return False
    return None


def integer(node: Any) -> Optional[int]:
    from compiler.ast_nodes import Integer, Real

    if isinstance(node, (Integer, Real)):
        return int(node.value)
    return None


def string_list(node: Any) -> List[str]:
    """``("a" "b")`` / ``"a"`` → ``['a', 'b']``；非字符串条目跳过。"""
    from compiler.ast_nodes import String, Symbol

    values: List[Any]
    if node is None:
        return []
    values = args_of(node)
    out: List[str] = []
    for item in values:
        if isinstance(item, String):
            out.append(item.value)
        elif isinstance(item, Symbol) and not item.name.startswith(":"):
            out.append(item.name)
    return out
