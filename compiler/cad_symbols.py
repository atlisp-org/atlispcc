"""CAD stub 符号槽顺序推导（AutoCAD 从右到左收集算法）。

CAD 紧凑 stub 格式按符号槽编址，符号槽注册顺序由 AutoCAD 编译器
的"从右到左"扫描决定：
1. 所有函数名逆序（最后一个函数名在前）
2. 从最后一个函数往前，收集函数体符号（内建/字符串逆序，参数最后）
3. 函数名重复（逆序）
"""
from compiler.ast import (
    Symbol, String, Integer, Real, ListExpr, QuotedExpr,
    Defun, Setq, IfNode, WhileNode, ForeachNode, RepeatNode, Call, Progn,
    LambdaNode, Cond,
)


class CadSymbolCollector:
    def __init__(self):
        self.names = []
        self.arg_names = set()
        self.forced = set()

    def add(self, name, force=False):
        if name in ('T', 'nil'):
            return
        if force or name not in self.names:
            self.names.append(name)

    def collect_func_names(self, defuns):
        """收集所有函数名（逆序）。"""
        for f in reversed(defuns):
            self.add(f.name)

    def collect_program(self, program):
        defuns = [f for f in program.forms if isinstance(f, Defun)]
        others = [f for f in program.forms if not isinstance(f, Defun)]
        self.func_names = {f.name for f in defuns}
        # 参数使用统计：argname -> 使用它的函数数
        arg_usage: dict = {}
        for f in defuns:
            for a in f.args:
                arg_usage[a] = arg_usage.get(a, 0) + 1
        # 1. 函数名逆序
        for f in reversed(defuns):
            self.add(f.name)
        # 2. 从后往前收集函数体符号；每个函数的"唯一参数"紧跟其内建
        for f in reversed(defuns):
            self.arg_names = set(f.args)
            for expr in reversed(f.body):
                self.collect_expr(expr)
            for arg in reversed(f.args):
                if arg_usage.get(arg, 0) == 1:
                    self.add(arg)
            for loc in reversed(f.locals):
                self.add(loc)
        # 3. 共享参数（被多函数使用）统一最后
        self.arg_names = set()
        for f in reversed(defuns):
            for arg in reversed(f.args):
                if arg_usage.get(arg, 0) > 1:
                    self.add(arg)
        # 4. 顶层代码
        for form in reversed(others):
            self.collect_expr(form)
        # 5. 函数名重复（逆序）——由 DEFCODE 补充，此处不重复
        return self.names

    def collect_expr(self, node):
        if isinstance(node, Symbol):
            if node.name not in self.arg_names:
                self.add(node.name)
        elif isinstance(node, Call):
            if node.name in self.func_names and node.name not in self.forced:
                # 递归/跨函数调用：首次引用时重复注册（CAD 行为），后续去重
                self.add(node.name, force=True)
                self.forced.add(node.name)
            elif node.name not in self.arg_names:
                self.add(node.name)
            for a in reversed(node.args):
                self.collect_expr(a)
        elif isinstance(node, Setq):
            for target, value in reversed(node.pairs):
                if value:
                    self.collect_expr(value)
                if isinstance(target, Symbol) and target.name not in self.arg_names:
                    self.add(target.name)
                elif not isinstance(target, Symbol):
                    self.collect_expr(target)
        elif isinstance(node, IfNode):
            if node.else_expr:
                self.collect_expr(node.else_expr)
            if node.then:
                self.collect_expr(node.then)
            if node.cond:
                self.collect_expr(node.cond)
        elif isinstance(node, WhileNode):
            for expr in reversed(node.body):
                self.collect_expr(expr)
            if node.cond:
                self.collect_expr(node.cond)
        elif isinstance(node, Progn):
            for form in reversed(node.forms):
                self.collect_expr(form)
        elif isinstance(node, ForeachNode):
            self.add("foreach")
            for expr in reversed(node.body):
                self.collect_expr(expr)
            if node.list_expr:
                self.collect_expr(node.list_expr)
            if node.var is not None:
                self.collect_expr(node.var)
        elif isinstance(node, RepeatNode):
            self.add("repeat")
            for expr in reversed(node.body):
                self.collect_expr(expr)
            if node.count:
                self.collect_expr(node.count)
        elif isinstance(node, Cond):
            for clause in reversed(node.clauses):
                for item in reversed(clause):
                    self.collect_expr(item)
        elif isinstance(node, ListExpr):
            for item in reversed(node.items):
                self.collect_expr(item)
        elif isinstance(node, QuotedExpr):
            if node.expr:
                self.collect_expr(node.expr)
        elif isinstance(node, LambdaNode):
            self.add("lambda")
            for arg in reversed(node.args):
                self.add(arg)
            for expr in reversed(node.body):
                self.collect_expr(expr)
        elif isinstance(node, String):
            self.add('"' + node.value + '"')
        elif isinstance(node, (Integer, Real)):
            pass


def derive_symbol_names(program):
    """返回与 CAD 一致的符号槽顺序列表。

    字符串以 ``"value"`` 形式表示（含引号），符号为普通名字。
    """
    coll = CadSymbolCollector()
    return coll.collect_program(program)
