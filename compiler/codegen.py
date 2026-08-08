import struct
from typing import List, Optional, Dict, Any, Set, Tuple
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
)
from asm.opcodes import (
    NAME_TO_OPCODE,
    encode_usubr,
    encode_usubr3,
    encode_func,
    encode_func3,
    encode_op_u16,
    encode_op_u8,
    encode_op_s32,
    encode_op_noarg,
    encode_real,
    encode_defun,
)


def normalize_vla_name(name):
    """规范化 vla- 前缀的 ActiveX 方法符号名（与 cad_symbols 保持一致）。

    CAD 对 ``vla-get-<Method>`` 等方法符号保留原始大小写且方法名首字母大写
    （t22_activex golden 实测），``vlax-`` 前缀保持小写。非 vla-/vlax- 不变。
    """
    for prefix in ("vla-get-", "vla-put-", "vla-call-", "vla-add-", "vla-insert-"):
        if name.lower().startswith(prefix):
            method = name[len(prefix):]
            if method and method[0].islower():
                return prefix + method[0].upper() + method[1:]
            return name
    return name
from compiler.symbol_table import SymbolTable

PUSH_T = NAME_TO_OPCODE["PUSH_T"]  # 0x02
PUSH_NIL = NAME_TO_OPCODE["PUSH_NIL"]  # 0x01
PUSH_VALUE = NAME_TO_OPCODE["PUSH_VALUE"]  # 0x03
EXIT_IF_NOT_ZERO = NAME_TO_OPCODE["EXIT_IF_NOT_ZERO"]  # 0x3e
PUSH_INT8 = NAME_TO_OPCODE["PUSH_INT8"]  # 0x32
PUSH_INT32 = NAME_TO_OPCODE["PUSH_INT32"]  # 0x33
PUSH_G = NAME_TO_OPCODE["PUSH_G"]  # 0x09
POP = NAME_TO_OPCODE["POP"]  # 0x0a
DUP = NAME_TO_OPCODE["DUP"]  # 0x0b
SETQ_G = NAME_TO_OPCODE["SETQ_G"]  # 0x06
JMP16_IFNOT = NAME_TO_OPCODE["JMP16_IFNOT"]  # 0x0d
JMP16_IF = NAME_TO_OPCODE["JMP16_IF"]  # 0x0e
JMP32_IFNOT = NAME_TO_OPCODE["JMP32_IFNOT"]  # 0x67
COND_OR = NAME_TO_OPCODE["COND_OR"]  # 0x68
COND_AND = NAME_TO_OPCODE["COND_AND"]  # 0x6a
JUMP = NAME_TO_OPCODE["JUMP"]  # 0x57
CONS = NAME_TO_OPCODE["CONS"]
BUILD_LIST = NAME_TO_OPCODE["BUILD_LIST"]  # 0x39
CAR = NAME_TO_OPCODE["CAR"]  # 0x28
CDR = NAME_TO_OPCODE["CDR"]  # 0x29
INIT_ARGS = NAME_TO_OPCODE["INIT_ARGS"]  # 0x18
CLEAR_ARGS = NAME_TO_OPCODE["CLEAR_ARGS"]  # 0x19
END_DEFUN = NAME_TO_OPCODE["END_DEFUN"]  # 0x16
INC = NAME_TO_OPCODE["INC"]  # 0x4f
DEC = NAME_TO_OPCODE["DEC"]  # 0x50
FIX_SUB = NAME_TO_OPCODE["FIX_SUB"]  # 0x47
FIX_DIV = NAME_TO_OPCODE["FIX_DIV"]  # 0x49
FIX_LEQ = NAME_TO_OPCODE["FIX_LEQ"]  # 0x4b
GET_LOCAL_8 = 0x05  # GET_LOCAL with 1-byte operand index
GET_LOCAL_16 = 0x5C  # GET_LOCAL_WIDE with 2-byte operand index
SET_LOCAL_16 = 0x5D  # SET_LOCAL with 2-byte operand index


ARITH_OP_TO_FAS = {
    "+": "FIX_ADD",
    "-": "FIX_SUB",
    "*": "FIX_MUL",
    "/": "FIX_DIV",
    "rem": "FIX_MOD",
    "<=": "FIX_LEQ",
    ">=": "FIX_GEQ",
    "<": "FIX_LT",
    ">": "FIX_GT",
}

UNARY_OP_TO_FAS = {
    "1+": "INC",
    "1-": "DEC",
    "not": "NOT",
    "atom": "ATOM",
    "car": "CAR",
    "cdr": "CDR",
}

LOCAL_SLOT_MAP: Dict[str, int] = {}
NEXT_LOCAL_SLOT = 0


def _ast_contains_loop(node) -> bool:
    """递归检测 AST 是否含 foreach/repeat（CAD 对其 DEFUN 头 b1 加 1）。"""
    if isinstance(node, (ForeachNode, RepeatNode)):
        return True
    if isinstance(node, Node):
        for val in vars(node).values():
            if isinstance(val, Node):
                if _ast_contains_loop(val):
                    return True
            elif isinstance(val, (list, tuple)):
                for it in val:
                    if isinstance(it, Node) and _ast_contains_loop(it):
                        return True
    return False


class BytecodeBuffer:
    def __init__(self):
        self.data = bytearray()
        self.labels: Dict[str, int] = {}
        self.patches: List[Tuple[int, str, int]] = []

    def emit(self, b: bytes):
        self.data.extend(b)

    def pos(self) -> int:
        return len(self.data)

    def label(self, name: str):
        self.labels[name] = self.pos()

    def patch_label(self, name: str, offset: int):
        self.labels[name] = offset

    def add_patch(self, patch_pos: int, target_label: str, op_size: int):
        self.patches.append((patch_pos, target_label, op_size))

    def resolve(self):
        for pos, label, op_size in self.patches:
            target = self.labels.get(label)
            if target is None:
                raise ValueError(f"Unresolved label: {label}")
            rel_offset = target - (pos + op_size)
            self.data[pos : pos + op_size] = struct.pack("<i", rel_offset)[:op_size]

    def size(self) -> int:
        return len(self.data)


class CodeGenerator:
    def __init__(self, symtab: SymbolTable, stub_format: bool = False, defined_funcs=None, nsyms: int = -1):
        self.symtab = symtab
        self.stub_format = stub_format
        # stub 格式参数绑定/读取：参数 i → nsyms-argc+i（最终经 _patch_usubr_idx 修正为 gvar_slot-1）
        self.nsyms = nsyms if nsyms >= 0 else len(symtab.entries)
        self.local_slots: Dict[str, int] = {}
        self.next_slot = 0
        self.current_func_name: str = ""
        self.current_func_args: List[str] = []
        self._tail_entry_label: str = ""
        self._in_tail_context: bool = False
        self.func_offset_map: Dict[str, int] = {}
        self.stub_offsets: List[int] = []
        self._nested_lambdas: List[tuple] = []
        self._func_nested_lambdas: dict = {}
        self._defined_funcs: set = set(defined_funcs or [])
        self._func_ref_slots: Dict[str, int] = {}
        self._module_mode: bool = False
        # 语句上下文（值将被 POP 丢弃）：仅裸语句位置（函数体中间语句、
        # progn 中间语句、循环体）置位。值上下文（setq RHS、函数/算术实参）
        # 不置位——_emit_if 据此决定 then 分支尾是否兼 POP。
        self._in_stmt_ctx: bool = False

    def _get_local_slot(self, name: str) -> int:
        if name not in self.local_slots:
            self.local_slots[name] = self.next_slot
            self.next_slot += 1
        return self.local_slots[name]

    def _emit_call(self, buf: BytecodeBuffer, name: str, argc: int, sym_idx: int, is_builtin: bool = False):
        if is_builtin:
            buf.emit(encode_func(argc, sym_idx))
        else:
            buf.emit(encode_usubr(argc, sym_idx))

    def _emit_arith(self, buf: BytecodeBuffer, op_name: str, args: List[Node]):
        if self.stub_format:
            with self._value_ctx():
                for arg in args:
                    self._emit_expr(buf, arg)
            idx = self.symtab.get_or_add(op_name)
            buf.emit(encode_usubr3(len(args), idx))
            buf.emit(encode_op_noarg(0x00))
            buf.emit(bytes([PUSH_VALUE]))
            return
        fas_op = ARITH_OP_TO_FAS.get(op_name)
        if fas_op:
            if len(args) == 1:
                with self._value_ctx():
                    if op_name == "-":
                        self._emit_expr(buf, Integer(0))
                        self._emit_expr(buf, args[0])
                    elif op_name == "/":
                        self._emit_expr(buf, Integer(1))
                        self._emit_expr(buf, args[0])
                    else:
                        self._emit_expr(buf, Integer(0))
                        self._emit_expr(buf, args[0])
                buf.emit(encode_op_noarg(NAME_TO_OPCODE[fas_op]))
                return
            with self._value_ctx():
                for arg in args:
                    self._emit_expr(buf, arg)
            for _ in range(len(args) - 1):
                buf.emit(encode_op_noarg(NAME_TO_OPCODE[fas_op]))
        else:
            idx = self.symtab.get_or_add(op_name)
            with self._value_ctx():
                for arg in reversed(args):
                    self._emit_expr(buf, arg)
            buf.emit(encode_usubr(len(args), idx))

    def _emit_unary(self, buf: BytecodeBuffer, op_name: str, arg: Node):
        if self.stub_format:
            with self._value_ctx():
                self._emit_expr(buf, arg)
            idx = self.symtab.get_or_add(op_name)
            buf.emit(encode_usubr3(1, idx))
            buf.emit(encode_op_noarg(0x00))
            buf.emit(bytes([PUSH_VALUE]))
            return
        fas_op = UNARY_OP_TO_FAS.get(op_name)
        if fas_op:
            with self._value_ctx():
                self._emit_expr(buf, arg)
            buf.emit(encode_op_noarg(NAME_TO_OPCODE[fas_op]))
        else:
            idx = self.symtab.get_or_add(op_name)
            with self._value_ctx():
                self._emit_expr(buf, arg)
            buf.emit(encode_usubr(1, idx))

    from contextlib import contextmanager

    @contextmanager
    def _value_ctx(self):
        saved = self._in_stmt_ctx
        self._in_stmt_ctx = False
        try:
            yield
        finally:
            self._in_stmt_ctx = saved

    def _emit_stmt(self, buf: BytecodeBuffer, node: Node):
        """在语句上下文（值被丢弃）中发射一条表达式。"""
        saved = self._in_stmt_ctx
        self._in_stmt_ctx = True
        try:
            if isinstance(node, IfNode):
                self._emit_if(buf, node)
            else:
                self._emit_expr(buf, node)
        finally:
            self._in_stmt_ctx = saved

    def _emit_expr(self, buf: BytecodeBuffer, node: Node, _tail: bool = False):
        saved_tail = self._in_tail_context
        if _tail:
            self._in_tail_context = True
        if isinstance(node, Symbol):
            name = normalize_vla_name(node.name)
            if name.lower() == "nil":
                buf.emit(encode_op_noarg(PUSH_NIL))
            elif name.lower() == "t":
                if self.stub_format:
                    # CAD 对值位置的 `T`/`t` 注册符号槽并用 PUSH_VALUE 引用
                    # （t18 小写 t、t22 大写 T golden 实测），非 PUSH_T 内联。
                    # 仅 `(and ...)` 短路尾 / cond else 键等由各自发射点处理。
                    idx = self.symtab.get_or_add(name)
                    buf.emit(encode_op_u16(PUSH_VALUE, idx))
                else:
                    buf.emit(encode_op_noarg(PUSH_T))
            elif self.stub_format:
                if name in self.current_func_args:
                    if len(self._defined_funcs) <= 1:
                        # 单函数参数读取逆序（CAD simple3/t13 实测：`+ Z Y X`、
                        # `> C B A`——源码第 i 个参数 → 槽 nsyms-1-i）。
                        idx = self.nsyms - 1 - self.local_slots[name]
                    else:
                        idx = self.nsyms - len(self.current_func_args) + self.local_slots[name]
                else:
                    idx = self.symtab.get_or_add(name)
                buf.emit(encode_op_u16(PUSH_VALUE, idx))
            elif name in self.local_slots:
                slot = self.local_slots[name]
                if slot < 256:
                    buf.emit(struct.pack("<BB", GET_LOCAL_8, slot))
                else:
                    buf.emit(encode_op_u16(GET_LOCAL_16, slot))
            else:
                idx = self.symtab.get_or_add(name)
                buf.emit(encode_op_u16(PUSH_VALUE, idx))

        elif isinstance(node, Integer):
            val = node.value
            if -128 <= val <= 127:
                buf.emit(encode_op_u8(PUSH_INT8, val & 0xFF))
            else:
                buf.emit(struct.pack("<Bi", PUSH_INT32, val))

        elif isinstance(node, Real):
            if self.stub_format:
                # CAD stub：实数常量注册为资源段 REAL 槽，字节码 PUSH_G 引用
                # （CAD 实测 real/real_arith/real_list/real_param golden：
                # `(defun f () 3.14159)` → PUSH_G 引用 REAL 槽，非内联 PUSH_REAL）。
                idx = self.symtab.add_real(node.value)
                buf.emit(encode_op_u16(PUSH_G, idx))
            else:
                buf.emit(encode_real(node.value))

        elif isinstance(node, String):
            idx = self.symtab.add_string(node.value)
            buf.emit(encode_op_u16(PUSH_G, idx))

        elif isinstance(node, Call):
            self._emit_call_expr(buf, node)

        elif isinstance(node, QuotedExpr):
            if node.kwote:
                self._emit_kwote(buf, node.expr)
            else:
                self._emit_quoted(buf, node.expr)

        elif isinstance(node, ListExpr):
            if node.items and isinstance(node.items[0], LambdaNode):
                self._emit_expr(buf, QuotedExpr(expr=self._lambda_list(node.items[0])))
                self._emit_expr(buf, Call(name="list", args=node.items[1:]))
                buf.emit(encode_func3(2, self.symtab.get_or_add("apply")))
                return
            if node.dotted is not None:
                self._emit_expr(buf, node.dotted)
                for item in reversed(node.items):
                    self._emit_expr(buf, item)
                    buf.emit(encode_op_noarg(CONS))
                return
            buf.emit(encode_op_noarg(PUSH_NIL))
            for item in reversed(node.items):
                self._emit_expr(buf, item)
            buf.emit(encode_op_u16(BUILD_LIST, len(node.items)))

        elif isinstance(node, Setq):
            self._emit_setq(buf, node)

        elif isinstance(node, IfNode):
            self._emit_if(buf, node)

        elif isinstance(node, WhileNode):
            self._emit_while(buf, node)

        elif isinstance(node, ForeachNode):
            self._emit_foreach(buf, node)

        elif isinstance(node, RepeatNode):
            self._emit_repeat(buf, node.count or Integer(0), node.body)

        elif isinstance(node, Progn):
            saved_tail = self._in_tail_context
            for form in node.forms[:-1]:
                # 中间语句（值被 POP 丢弃）：独立清尾上下文，避免内层 if/表达式
                # 误按尾上下文编译（i18n-cad update-locale progn 内层 if 实测）。
                self._in_tail_context = False
                self._emit_stmt(buf, form)
                # 中间 setq（SETQ_G 已消费栈顶）、中间 if（_emit_if 内部处理）、
                # while/foreach/repeat（自带栈平衡）后均无 POP；仅普通表达式
                # 追加 POP（规则同 generate_function 中间语句）。
                if not isinstance(form, (IfNode, Setq, WhileNode, ForeachNode, RepeatNode)):
                    buf.emit(encode_op_noarg(POP))
            if node.forms:
                self._in_tail_context = saved_tail
                self._emit_expr(buf, node.forms[-1], _tail=saved_tail)
                # 中间上下文（非尾）且最后语句是留值表达式（调用/符号/常量）时，
                # 追加 POP 丢弃 progn 值。setq/if/while/foreach/repeat/progn 自身
                # 管理栈（i18n-cad load-locale 内层 if-then=progn(..., close) 后
                # `POP`；外层 if-then=progn(..., 内层 if) 后无 POP）。
                if not saved_tail and not isinstance(
                    node.forms[-1], (Setq, IfNode, WhileNode, ForeachNode, RepeatNode, Progn)
                ):
                    buf.emit(encode_op_noarg(POP))
            self._in_tail_context = saved_tail

        elif isinstance(node, Cond):
            self._emit_cond(buf, node)

        elif isinstance(node, LambdaNode):
            self._emit_expr(buf, QuotedExpr(expr=self._lambda_list(node)))

        else:
            raise NotImplementedError(f"Cannot emit expression: {type(node).__name__}")
        self._in_tail_context = saved_tail

    def _lambda_list(self, node: LambdaNode) -> ListExpr:
        params = ListExpr(items=[Symbol(a) for a in node.args])
        return ListExpr(items=[Symbol("lambda"), params] + node.body)

    def _emit_call_expr(self, buf: BytecodeBuffer, node: Call):
        name = node.name
        upper = name.upper()
        args = node.args

        if name in ARITH_OP_TO_FAS:
            self._emit_arith(buf, name, args)
            return
        if name in UNARY_OP_TO_FAS and len(args) == 1:
            self._emit_unary(buf, name, args[0])
            return
        if name in ("and", "or"):
            if len(args) == 0:
                if name == "and":
                    buf.emit(encode_op_noarg(PUSH_T))
                else:
                    buf.emit(encode_op_noarg(PUSH_NIL))
                return
            self._emit_short_circuit(buf, name, args)
            return
        if name == "list":
            if self.stub_format:
                for arg in args:
                    self._emit_expr(buf, arg)
                idx = self.symtab.get_or_add("list")
                buf.emit(encode_usubr3(len(args), idx))
                buf.emit(encode_op_noarg(0x00))
                buf.emit(bytes([PUSH_VALUE]))
                return
            for arg in reversed(args):
                self._emit_expr(buf, arg)
            buf.emit(encode_op_u16(BUILD_LIST, len(args)))
            return
        if name == "progn":
            for form in args[:-1]:
                self._emit_stmt(buf, form)
                buf.emit(encode_op_noarg(POP))
            if args:
                self._emit_expr(buf, args[-1])
            return
        if name in ("setq",):
            if len(args) >= 2:
                self._emit_setq_expr(buf, args[0], args[1])
            for i in range(2, len(args), 2):
                if i + 1 < len(args):
                    self._emit_setq_expr(buf, args[i], args[i + 1])
            return
        if name == self.current_func_name and self._in_tail_context and not self.stub_format:
            self._emit_tail_call(buf, args)
            return
        if name in ("exit", "quit", "abort"):
            buf.emit(encode_op_noarg(PUSH_T))
            buf.emit(encode_op_noarg(EXIT_IF_NOT_ZERO))
            return
        idx = self.symtab.get_or_add(normalize_vla_name(name))
        if (
            self.stub_format
            and not self._module_mode
            and name in self._defined_funcs
            and name != self.current_func_name
        ):
            # 跨函数调用：CAD 用重复符号槽（首次引用分配新槽）
            if name not in self._func_ref_slots:
                rep = self.symtab.next_repeat_slot(name)
                self._func_ref_slots[name] = rep if rep >= 0 else self.symtab.add_force(name)
            idx = self._func_ref_slots[name]
        elif self.stub_format and name == self.current_func_name:
            # 递归调用（含尾位置）：CAD 用重复符号槽
            if name not in self._func_ref_slots:
                rep = self.symtab.next_repeat_slot(name)
                self._func_ref_slots[name] = rep if rep >= 0 else self.symtab.add_force(name)
            idx = self._func_ref_slots[name]
        is_builtin = self.symtab.is_builtin(name)
        with self._value_ctx():
            for arg in args:
                self._emit_expr(buf, arg)
        if self.stub_format:
            buf.emit(encode_usubr3(len(args), idx))
            # CAD stub: 每次调用后 NIL + PUSH_VALUE[0]（结果清理/保留）
            buf.emit(encode_op_noarg(0x00))
            buf.emit(bytes([PUSH_VALUE]))
        elif is_builtin:
            buf.emit(encode_func3(len(args), idx))
        else:
            buf.emit(encode_usubr3(len(args), idx))

    def _emit_setq_expr(self, buf: BytecodeBuffer, target: Node, value: Node):
        if isinstance(target, Symbol):
            with self._value_ctx():
                self._emit_expr(buf, value)
            if self.stub_format:
                if self._in_tail_context:
                    buf.emit(encode_op_noarg(DUP))
                idx = self.symtab.get_or_add(target.name)
                buf.emit(encode_op_u16(SETQ_G, idx))
            elif target.name in self.local_slots:
                slot = self.local_slots[target.name]
                buf.emit(encode_op_u16(SET_LOCAL_16, slot))
            else:
                idx = self.symtab.get_or_add(target.name)
                buf.emit(encode_op_u16(SETQ_G, idx))
        else:
            with self._value_ctx():
                self._emit_expr(buf, value)
                self._emit_expr(buf, target)
            buf.emit(encode_func(1, self.symtab.get_or_add("set")))

    def _emit_setq(self, buf: BytecodeBuffer, node: Setq):
        pairs = list(node.pairs)
        n = len(pairs)
        for i, (target, value) in enumerate(pairs):
            if isinstance(target, Symbol) and value:
                with self._value_ctx():
                    self._emit_expr(buf, value)
                if self.stub_format:
                    if self._in_tail_context and i == n - 1:
                        buf.emit(encode_op_noarg(DUP))
                    idx = self.symtab.get_or_add(target.name)
                    buf.emit(encode_op_u16(SETQ_G, idx))
                elif target.name in self.local_slots:
                    slot = self.local_slots[target.name]
                    buf.emit(encode_op_u16(SET_LOCAL_16, slot))
                else:
                    idx = self.symtab.get_or_add(target.name)
                    buf.emit(encode_op_u16(SETQ_G, idx))

    def _emit_if(self, buf: BytecodeBuffer, node: IfNode):
        label_else = f"_if_else_{buf.pos()}"
        label_end = f"_if_end_{buf.pos()}"

        self._emit_expr(buf, node.cond or Symbol("nil"))

        if self.stub_format:
            # CAD stub: cond + JMP32_IFNOT <else> + then + JUMP <end> + else。
            # 注意：CAD 的 JMP32_IFNOT(0x67) 语义为"栈顶为假则跳转"(IFNOT)。
            # 无 else 分支时 CAD 不生成 else 代码，label_else 与 label_end 重合于 JUMP 之后。
            # then/else 分支末表达式是 if 的"值"：stub 下分支末尾 setq 无论
            # if 自身是否尾上下文都要 DUP 保留该值（p05 then 分支尾多对 setq
            # 的最后一对 `DUP SETQ_G` 实测）。
            jmp_pos = buf.pos()
            buf.emit(encode_op_s32(JMP32_IFNOT, 0))
            buf.add_patch(jmp_pos + 1, label_else, 4)
            # then 分支尾上下文：尾 if / 模块代码顶层 if 需 DUP 保留值
            # （模块代码顶层 if-then-setq，p04/i18n-cad 实测 `0b 06`）。
            _then_tail = self._in_tail_context or self._module_mode
            self._emit_expr(buf, node.then or Symbol("nil"), _tail=_then_tail)
            if self._in_stmt_ctx and not isinstance(node.then, (Setq, IfNode, Progn)):
                # 语句上下文（中间 if，值被丢弃）：then 分支值被 POP。值上下文
                # （setq RHS、函数/算术实参）不 POP——值需流到外层消费者。
                # then 为 setq 时 SETQ_G 已消费栈顶，无需 POP；普通表达式则
                # POP 丢弃（i18n-cad update-locale 内层 if-then @::load-module
                # 后 `POP`）。then 为 progn/if 时由其自身管理栈（i18n-cad
                # load-locale 外层 if-then=progn 后无额外 POP）。
                # POP 位于 then 末尾、JUMP 之前（ref 实测顺序 `03 0a 57`）。
                buf.emit(encode_op_noarg(POP))
            jmp2_pos = buf.pos()
            buf.emit(encode_op_s32(JUMP, 0))
            buf.add_patch(jmp2_pos + 1, label_end, 4)
            buf.patch_label(label_else, buf.pos())
            if node.else_expr:
                self._emit_expr(buf, node.else_expr, _tail=self._in_tail_context)
            elif self._in_tail_context or self._module_mode:
                # CAD stub：尾上下文 / 模块代码顶层无 else 分支时在 else 标签处
                # 补隐式 PUSH_NIL（cond 为假时返回 nil），then 分支的 JUMP 跳过
                # 它（t9 / i18n-cad 模块代码实测）。中间 if（函数体中间的语句）
                # 不补：假路径直接跳下一语句（i18n-cad update-locale 实测）。
                buf.emit(encode_op_noarg(PUSH_NIL))
            buf.patch_label(label_end, buf.pos())
            return

        if node.else_expr:
            jmp_pos = buf.pos()
            buf.emit(encode_op_u16(JMP16_IFNOT, 0))
            buf.add_patch(jmp_pos + 1, label_else, 2)

            self._emit_expr(buf, node.then or Symbol("nil"), _tail=self._in_tail_context)
            jmp2_pos = buf.pos()
            buf.emit(encode_op_s32(JUMP, 0))
            buf.add_patch(jmp2_pos + 1, label_end, 4)

            buf.patch_label(label_else, buf.pos())
            self._emit_expr(buf, node.else_expr or Symbol("nil"), _tail=self._in_tail_context)
            buf.patch_label(label_end, buf.pos())
        else:
            jmp_pos = buf.pos()
            buf.emit(encode_op_u16(JMP16_IFNOT, 0))
            buf.add_patch(jmp_pos + 1, label_end, 2)

            self._emit_expr(buf, node.then or Symbol("nil"), _tail=self._in_tail_context)
            buf.patch_label(label_end, buf.pos())

    def _emit_while(self, buf: BytecodeBuffer, node: WhileNode):
        label_loop = f"_while_loop_{buf.pos()}"
        label_end = f"_while_end_{buf.pos()}"

        buf.label(label_loop)
        # while 条件里的 setq 需 DUP 保留返回值给 JMP32_IFNOT 判断
        # （i18n-cad load-locale `(while (setq opt% (read-line fp)) ...)` 实测
        # `03 0b 06` = PUSH_VALUE; DUP; SETQ_G）。
        self._emit_expr(buf, node.cond or Symbol("nil"), _tail=True)
        jmp_pos = buf.pos()
        if self.stub_format:
            buf.emit(encode_op_s32(JMP32_IFNOT, 0))
            buf.add_patch(jmp_pos + 1, label_end, 4)
        else:
            buf.emit(encode_op_u16(JMP16_IFNOT, 0))
            buf.add_patch(jmp_pos + 1, label_end, 2)

        for i, form in enumerate(node.body):
            self._emit_stmt(buf, form)
            # CAD stub：中间 setq 无 POP（SETQ_G 自身消费栈顶），仅非 setq 追加。
            # 与 generate_function 顶层体规则一致（t11_localvars 实测）。
            if self.stub_format:
                if isinstance(form, (Setq, WhileNode)):
                    continue
                if i >= len(node.body) - 1:
                    continue
                buf.emit(encode_op_noarg(POP))
            elif i < len(node.body) - 1:
                buf.emit(encode_op_noarg(POP))

        jmp_back = buf.pos()
        buf.emit(encode_op_s32(JUMP, 0))
        buf.add_patch(jmp_back + 1, label_loop, 4)

        buf.label(label_end)

    def _emit_foreach(self, buf: BytecodeBuffer, node: ForeachNode):
        if self.stub_format:
            self._emit_foreach_stub(buf, node)
            return
        var_name = node.var.name if isinstance(node.var, Symbol) else "item"
        slot = self._get_local_slot(f"__foreach_list__{buf.pos()}")
        item_slot = self._get_local_slot(f"__foreach_item__{buf.pos()}")

        self._emit_expr(buf, node.list_expr or Symbol("nil"))
        buf.emit(encode_op_u16(SET_LOCAL_16, slot))

        label_loop = f"_foreach_loop_{buf.pos()}"
        label_end = f"_foreach_end_{buf.pos()}"

        buf.label(label_loop)
        buf.emit(encode_op_u16(GET_LOCAL_16, slot))
        jmp_pos = buf.pos()
        buf.emit(encode_op_u16(JMP16_IFNOT, 0))
        buf.add_patch(jmp_pos + 1, label_end, 2)

        buf.emit(encode_op_u16(GET_LOCAL_16, slot))
        buf.emit(encode_op_noarg(CAR))
        if var_name in self.local_slots:
            vslot = self.local_slots[var_name]
            buf.emit(encode_op_u16(SET_LOCAL_16, vslot))
        else:
            idx = self.symtab.get_or_add(var_name)
            buf.emit(encode_op_u16(SETQ_G, idx))

        buf.emit(encode_op_u16(GET_LOCAL_16, slot))
        buf.emit(encode_op_noarg(CDR))
        buf.emit(encode_op_u16(SET_LOCAL_16, slot))

        for form in node.body:
            self._emit_stmt(buf, form)
            buf.emit(encode_op_noarg(POP))

        jmp_back = buf.pos()
        buf.emit(encode_op_s32(JUMP, 0))
        buf.add_patch(jmp_back + 1, label_loop, 4)

        buf.label(label_end)

    def _emit_foreach_stub(self, buf: BytecodeBuffer, node: ForeachNode):
        """CAD stub 的 foreach 内建调用协议（t16_foreach 逐字节实测）：

        ``列表存 slot → PUSH_G <var>; PUSH_NIL; INIT_ARGS 3（预载）→
        loop: GET_LOCAL; JMP32_IFNOT end; GET_LOCAL; CAR; SETQ_G <var>;
        GET_LOCAL; CDR; SET_LOCAL; body(无 POP); JUMP loop; end: CLEAR_ARGS 1``
        """
        var_name = node.var.name if isinstance(node.var, Symbol) else "item"
        slot = self._get_local_slot(f"__foreach_list__{buf.pos()}")
        v_idx = self.symtab.get_or_add(var_name)

        self._emit_expr(buf, node.list_expr or Symbol("nil"))
        buf.emit(encode_op_u16(SET_LOCAL_16, slot))
        # CAD 预载：PUSH_G <var>; PUSH_NIL; INIT_ARGS 3
        buf.emit(encode_op_u16(PUSH_G, v_idx))
        buf.emit(encode_op_noarg(PUSH_NIL))
        buf.emit(encode_op_u16(INIT_ARGS, 3))

        label_loop = f"_foreach_stub_loop_{buf.pos()}"
        label_end = f"_foreach_stub_end_{buf.pos()}"
        if self._in_tail_context:
            # 尾 foreach（函数最后语句）：CAD 在 loop 头前压入 PUSH_NIL 占位，
            # 体开头 POP 弹掉（i18n-cad update-locale-all 实测 `01 5c 00 00
            # 67 ... 0a`）。中间 foreach（t16）无此结构。
            buf.emit(encode_op_noarg(PUSH_NIL))
        buf.label(label_loop)
        buf.emit(encode_op_u16(GET_LOCAL_16, slot))
        jmp_pos = buf.pos()
        buf.emit(encode_op_s32(JMP32_IFNOT, 0))
        buf.add_patch(jmp_pos + 1, label_end, 4)

        if self._in_tail_context:
            buf.emit(encode_op_noarg(POP))
        buf.emit(encode_op_u16(GET_LOCAL_16, slot))
        buf.emit(encode_op_noarg(CAR))
        buf.emit(encode_op_u16(SETQ_G, v_idx))
        buf.emit(encode_op_u16(GET_LOCAL_16, slot))
        buf.emit(encode_op_noarg(CDR))
        buf.emit(encode_op_u16(SET_LOCAL_16, slot))

        for i, form in enumerate(node.body):
            self._emit_stmt(buf, form)
            # 非尾 foreach（_in_tail_context=False）体最后语句若留值（print/cons
            # 等调用）→ POP 丢弃（i18n-cad save-mt `(print opt% fp)` 后 `POP`）；
            # setq/if 自身管理栈；尾 foreach 无 POP（update-locale-all 实测）。
            if not self._in_tail_context and i == len(node.body) - 1 and not isinstance(form, (Setq, IfNode)):
                buf.emit(encode_op_noarg(POP))

        jmp_back = buf.pos()
        buf.emit(encode_op_s32(JUMP, 0))
        buf.add_patch(jmp_back + 1, label_loop, 4)
        buf.label(label_end)
        # 预载参数清理（CAD 实测：foreach 结果不被 POP，而用 CLEAR_ARGS 1）
        buf.emit(encode_op_u16(CLEAR_ARGS, 1))

    def _emit_short_circuit(self, buf: BytecodeBuffer, op_name: str, args: List[Node]):
        # CAD 对 and/or 用 COND_AND(0x6a)/COND_OR(0x68) 4 字节相对偏移指令
        # （and2/or2/andval CAD 实测），并规范化结果为 T/nil：
        #   (and e1 e2 ... en) →
        #     e1; COND_AND 假跳 END; ...; en; COND_AND 假跳 END; PUSH_T; END:
        #   (or  e1 e2 ... en) →
        #     e1; COND_OR 真跳 TAIL; ...; en; COND_OR 真跳 TAIL;
        #     PUSH_NIL; TAIL: COND_AND 假跳 END; PUSH_T; END:
        # 短路时栈上保留子表达式值作为结果；全真/有真时 PUSH_T 规范化。
        # 不可用 JMP16_IF/JMP16_IFNOT——CAD stub 运行时该指令序列会出错
        # （i18n mark-locale 的 and/or 实测"函数错误"）。
        if op_name == "and":
            label_end = f"_and_end_{buf.pos()}"
            for arg in args:
                self._emit_expr(buf, arg)
                jmp_pos = buf.pos()
                buf.emit(encode_op_s32(COND_AND, 0))
                buf.add_patch(jmp_pos + 1, label_end, 4)
            buf.emit(encode_op_noarg(PUSH_T))
            buf.label(label_end)
        else:  # or
            label_tail = f"_or_tail_{buf.pos()}"
            label_end = f"_or_end_{buf.pos()}"
            for arg in args:
                self._emit_expr(buf, arg)
                jmp_pos = buf.pos()
                buf.emit(encode_op_s32(COND_OR, 0))
                buf.add_patch(jmp_pos + 1, label_tail, 4)
            buf.emit(encode_op_noarg(PUSH_NIL))
            buf.label(label_tail)
            jmp_pos = buf.pos()
            buf.emit(encode_op_s32(COND_AND, 0))
            buf.add_patch(jmp_pos + 1, label_end, 4)
            buf.emit(encode_op_noarg(PUSH_T))
            buf.label(label_end)

    def _emit_cond(self, buf: BytecodeBuffer, node: Cond):
        if self.stub_format:
            self._emit_cond_stub(buf, node)
            return
        label_end = f"_cond_end_{buf.pos()}"
        label_next = None
        for i, clause in enumerate(node.clauses):
            if label_next:
                buf.label(label_next)
            if len(clause) == 0:
                continue
            cond = clause[0]
            actions = clause[1:]
            if isinstance(cond, Symbol) and cond.name.lower() == "t":
                for action in actions:
                    self._emit_expr(buf, action)
                break

            self._emit_expr(buf, cond)
            if actions:
                jmp_pos = buf.pos()
                if i < len(node.clauses) - 1:
                    label_next = f"_cond_next_{buf.pos()}_{i}"
                else:
                    label_next = label_end
                buf.emit(encode_op_u16(JMP16_IFNOT, 0))
                buf.add_patch(jmp_pos + 1, label_next, 2)
                for action in actions:
                    self._emit_expr(buf, action)
                if i < len(node.clauses) - 1:
                    jmp2_pos = buf.pos()
                    buf.emit(encode_op_s32(JUMP, 0))
                    buf.add_patch(jmp2_pos + 1, label_end, 4)
            else:
                buf.emit(encode_op_noarg(POP))
        buf.label(label_end)

    def _emit_cond_stub(self, buf: BytecodeBuffer, node: Cond):
        base = f"_cond_{buf.pos()}"
        clauses = [c for c in node.clauses if c]
        n = len(clauses)
        if n == 0:
            buf.emit(encode_op_noarg(PUSH_NIL))
            return
        # 各子句测试按源码顺序发出；仅 t 子句直接 PUSH_VALUE T（无 NIL 槽对）。
        for i, clause in enumerate(clauses):
            cond = clause[0]
            if isinstance(cond, Symbol) and cond.name.lower() == "t":
                idx = self.symtab.get_or_add(cond.name)
                buf.emit(encode_op_u16(PUSH_VALUE, idx))
            else:
                self._emit_expr(buf, cond)
            condor_pos = buf.pos()
            buf.emit(encode_op_s32(COND_OR, 0))
            buf.add_patch(condor_pos + 1, f"{base}_body_{i}", 4)
        # 全假默认值 + 跳转链：PUSH_NIL 后跳过首个发出体（=末子句体）。
        buf.emit(encode_op_noarg(PUSH_NIL))
        jmp_pos = buf.pos()
        buf.emit(encode_op_s32(JUMP, 0))
        buf.add_patch(jmp_pos + 1, f"{base}_body_{n - 1}_end", 4)
        # 结果体按源码倒序发出：POP + 结果；除最后发出体（=首子句）外各加 JUMP，
        # 跳到下一个发出体之后（即其 JUMP 处），链式跳过其余体。
        for k, i in enumerate(reversed(range(n))):
            actions = clauses[i][1:]
            buf.label(f"{base}_body_{i}")
            buf.emit(encode_op_noarg(POP))
            for a in actions[:-1]:
                self._emit_stmt(buf, a)
                buf.emit(encode_op_noarg(POP))
            if actions:
                self._emit_expr(buf, actions[-1])
            buf.label(f"{base}_body_{i}_end")
            if k < n - 1:
                jp = buf.pos()
                buf.emit(encode_op_s32(JUMP, 0))
                buf.add_patch(jp + 1, f"{base}_body_{i - 1}_end", 4)

    def _emit_repeat(self, buf: BytecodeBuffer, count_expr: Node, body: List[Node]):
        if self.stub_format:
            self._emit_repeat_stub(buf, count_expr, body)
            return
        slot = self._get_local_slot("__repeat__")
        self._emit_expr(buf, count_expr)
        buf.emit(encode_op_u16(SET_LOCAL_16, slot))
        label_loop = f"_repeat_loop_{buf.pos()}"
        label_end = f"_repeat_end_{buf.pos()}"
        buf.label(label_loop)
        buf.emit(encode_op_u16(GET_LOCAL_16, slot))
        jmp_pos = buf.pos()
        buf.emit(encode_op_u16(JMP16_IFNOT, 0))
        buf.add_patch(jmp_pos + 1, label_end, 2)
        for form in body:
            self._emit_stmt(buf, form)
            buf.emit(encode_op_noarg(POP))
        buf.emit(encode_op_u16(GET_LOCAL_16, slot))
        buf.emit(encode_op_noarg(DEC))
        buf.emit(encode_op_u16(SET_LOCAL_16, slot))
        jmp_back = buf.pos()
        buf.emit(encode_op_s32(JUMP, 0))
        buf.add_patch(jmp_back + 1, label_loop, 4)
        buf.label(label_end)

    def _emit_repeat_stub(self, buf: BytecodeBuffer, count_expr: Node, body: List[Node]):
        """CAD stub 的 repeat 递减循环协议（t17_repeat 逐字节实测）：

        ``count 存 slot → loop: GET_LOCAL; PUSH_INT8 0; FIX_LEQ; JMP32_IFNOT end;
        GET_LOCAL; DEC; SET_LOCAL; body(无 POP); JUMP loop; end``
        无预载（不像 foreach），循环结束栈平衡，无需 CLEAR_ARGS。
        """
        slot = self._get_local_slot("__repeat__")
        self._emit_expr(buf, count_expr)
        buf.emit(encode_op_u16(SET_LOCAL_16, slot))

        label_loop = f"_repeat_stub_loop_{buf.pos()}"
        label_end = f"_repeat_stub_end_{buf.pos()}"
        buf.label(label_loop)
        buf.emit(encode_op_u16(GET_LOCAL_16, slot))
        buf.emit(encode_op_u8(PUSH_INT8, 0))
        buf.emit(encode_op_noarg(FIX_LEQ))
        jmp_pos = buf.pos()
        buf.emit(encode_op_s32(JMP32_IFNOT, 0))
        buf.add_patch(jmp_pos + 1, label_end, 4)

        buf.emit(encode_op_u16(GET_LOCAL_16, slot))
        buf.emit(encode_op_noarg(DEC))
        buf.emit(encode_op_u16(SET_LOCAL_16, slot))

        for form in body:
            self._emit_stmt(buf, form)

        jmp_back = buf.pos()
        buf.emit(encode_op_s32(JUMP, 0))
        buf.add_patch(jmp_back + 1, label_loop, 4)
        buf.label(label_end)

    def _emit_quoted(self, buf: BytecodeBuffer, node: Optional[Node], skip_reg: set = None):
        if skip_reg is None:
            skip_reg = set()
        # CAD 紧凑 stub：引用字面量注册为资源段常量，字节码只发一条 PUSH_G。
        if self.stub_format and node is not None:
            from compiler.cad_symbols import to_const

            const = to_const(node)
            if const is not None:
                if const == ("NIL",):
                    # 空列表 `'()` = nil：CAD 用 PUSH_NIL，不注册常量槽
                    # （i18n_v2 顶层 `'()` 实测）。
                    buf.emit(encode_op_noarg(PUSH_NIL))
                    return
                idx = self.symtab.get_const_idx(const)
                if idx is not None:
                    buf.emit(encode_op_u16(PUSH_G, idx))
                    return
        if node is None:
            buf.emit(encode_op_noarg(PUSH_NIL))
        elif isinstance(node, Symbol):
            name = node.name
            if name == "T":
                buf.emit(encode_op_noarg(PUSH_T))
            elif name == "nil":
                buf.emit(encode_op_noarg(PUSH_NIL))
            elif name == "FUNC":
                buf.emit(encode_op_noarg(PUSH_NIL))
            else:
                if name in skip_reg:
                    idx = self.symtab.name_to_idx.get(name, 0xFFFF)
                else:
                    idx = self.symtab.get_or_add(name)
                buf.emit(encode_op_u16(PUSH_G, idx))
        elif isinstance(node, Integer):
            val = node.value
            if -128 <= val <= 127:
                buf.emit(encode_op_u8(PUSH_INT8, val & 0xFF))
            else:
                buf.emit(struct.pack("<Bi", PUSH_INT32, val))
        elif isinstance(node, Real):
            buf.emit(encode_real(node.value))
        elif isinstance(node, ListExpr):
            if node.dotted is not None:
                self._emit_quoted(buf, node.dotted, skip_reg)
                for item in reversed(node.items):
                    self._emit_quoted(buf, item, skip_reg)
                    buf.emit(encode_op_noarg(CONS))
                return
            for item in reversed(node.items):
                self._emit_quoted(buf, item, skip_reg)
            buf.emit(encode_op_u16(BUILD_LIST, len(node.items)))
        elif isinstance(node, LambdaNode):
            lambda_skip = set(node.args) | skip_reg
            args_list = ListExpr(items=[Symbol(a) for a in node.args])
            items = [Symbol("lambda"), args_list] + node.body
            for item in reversed(items):
                if item is args_list:
                    self._emit_quoted(buf, item, lambda_skip)
                else:
                    self._emit_quoted(buf, item, skip_reg)
            buf.emit(encode_op_u16(BUILD_LIST, len(items)))
        elif isinstance(node, String):
            idx = self.symtab.add_string(node.value)
            buf.emit(encode_op_u16(PUSH_G, idx))
        elif isinstance(node, Call):
            items = [Symbol(node.name)] + node.args
            for item in reversed(items):
                self._emit_quoted(buf, item, skip_reg)
            buf.emit(encode_op_u16(BUILD_LIST, len(items)))
        else:
            self._emit_expr(buf, node)

    def _emit_kwote(self, buf: BytecodeBuffer, node: Optional[Node]):
        """``(function X)`` 的 CAD kwote 机制（i18n-cad LOAD-MT 实测）：

        ``(function (lambda (opt%) body...))`` 编译为外层函数内嵌的一个
        ``-lambda-`` DEFUN：外层先发 ``JUMP`` 跳过内嵌 DEFUN（运行时被定义
        由模块加载器完成，不执行），内嵌 DEFUN 独立 ``14 <argc><argc><argc> 00``
        头 + lambda 体 + ``CLEAR_ARGS`` + ``END_DEFUN``，随后引用处发射
        ``PUSH_G <内部函数槽>; FUNC 1, kwote; NIL; PUSH_NIL; NIL``。

        返回 ``(kwote_bytes, nested_offset)``：nested_offset 为内嵌 DEFUN
        相对当前位置的字节偏移（供函数目录登记），kwote_bytes 为 PUSH_G+FUNC
        引用序列。
        """
        if not self.stub_format or not isinstance(node, LambdaNode):
            self._emit_quoted(buf, node)
            return
        argc = len(node.args)
        kwote_idx = self.symtab.get_or_add("kwote")
        lam_idx = self.symtab.get_or_add("-lambda-")
        label_after = f"_kwote_{buf.pos()}_{len(self._nested_lambdas)}"
        jmp_pos = buf.pos()
        buf.emit(encode_op_s32(JUMP, 0))
        buf.add_patch(jmp_pos + 1, label_after, 4)
        nested_start = buf.pos()
        buf.emit(bytes([0x14, argc & 0xFF, argc & 0xFF, argc & 0xFF, 0]))
        saved_args = self.current_func_args
        saved_name = self.current_func_name
        saved_slots = self.local_slots
        self.current_func_name = "-lambda-"
        self.current_func_args = node.args
        self.local_slots = {a: i for i, a in enumerate(node.args)}
        self._emit_init_args(buf, node.args)
        body = node.body
        for expr in body[:-1]:
            self._emit_stmt(buf, expr)
            if not isinstance(expr, (Setq, WhileNode, ForeachNode, RepeatNode)):
                buf.emit(encode_op_noarg(POP))
        if body:
            self._emit_expr(buf, body[-1], _tail=True)
        else:
            buf.emit(encode_op_noarg(PUSH_NIL))
        buf.emit(encode_op_u16(CLEAR_ARGS, argc))
        buf.emit(encode_op_noarg(0x16))
        nested_end = buf.pos()
        self.local_slots = saved_slots
        self.current_func_args = saved_args
        self.current_func_name = saved_name
        buf.label(label_after)
        self._nested_lambdas.append((nested_start, nested_end))
        buf.emit(encode_op_u16(PUSH_G, lam_idx))
        buf.emit(encode_func3(1, kwote_idx))
        buf.emit(encode_op_noarg(0x00))
        buf.emit(encode_op_noarg(PUSH_NIL))
        buf.emit(encode_op_noarg(0x00))

    def _emit_defun_header(self, buf: BytecodeBuffer, func: Defun):
        if self.stub_format:
            argc = len(func.args)
            if func.rest:
                # 无限参数：b4=01，b1/b2/b3 = 最小参数个数（必填）
                buf.emit(bytes([0x14]) + bytes([argc & 0xFF] * 3 + [1]))
            elif func.optional:
                # 有限可选参数：b1=总参数(max)，b2=必填(min)，b3=max
                total = argc + len(func.optional)
                buf.emit(bytes([0x14, total & 0xFF, argc & 0xFF, total & 0xFF, 0]))
            else:
                # 普通定参函数：b1=总参数(=argc)，b2/b3=argc。
                # CAD 对含 foreach/repeat 的函数 b1 加 1（t16/t17 实测 `14 02 01 01 00`）。
                b1 = argc + (1 if _ast_contains_loop(func) else 0)
                buf.emit(bytes([0x14, b1 & 0xFF, argc & 0xFF, argc & 0xFF, 0]))
            return
        idx = self.symtab.idx_of(func.name) or self.symtab.get_or_add(func.name)
        buf.emit(encode_defun(idx, 0))

    def _emit_init_args(self, buf: BytecodeBuffer, args: List[str]):
        if not args:
            return
        if self.stub_format:
            argc = len(args)
            # CAD stub 参数绑定：多函数（nfuncs>1）由 _patch_usubr_idx 统一修正
            # 为 gvar 槽（codegen 保持正序占位）；单函数（nfuncs==1）无 patch，
            # codegen 直接输出 CAD 槽——CAD 实测参数绑定逆序（`PUSH_G` 最后一个
            # 参数先发射，如 t13 `PUSH_G [4],[3],[2]` = C,B,A）。
            single = len(self._defined_funcs) <= 1
            for i, arg in enumerate(args):
                src_i = (argc - 1 - i) if single else i
                idx = self.nsyms - argc + src_i
                buf.emit(encode_op_u16(PUSH_G, idx))
                buf.emit(encode_op_u16(GET_LOCAL_16, i))
            buf.emit(encode_op_u16(INIT_ARGS, len(args) * 2 + 1))
            return
        for i, arg in enumerate(args):
            idx = self.symtab.get_or_add(arg)
            buf.emit(encode_op_u16(PUSH_G, idx))
            buf.emit(struct.pack("<BB", GET_LOCAL_8, i))
        buf.emit(encode_op_u16(INIT_ARGS, len(args) * 2))

    def _emit_al_bind_alist(self, buf: BytecodeBuffer, func: Defun):
        """CAD `/ 局部变量` 绑定协议：`(_al-bind-alist '(loc1 loc2 ...))`。

        t11_localvars 实测序列（INIT_ARGS 之后、函数体之前）：
        ``PUSH_G <const>; FUNC 1, <_al-bind-alist>; NIL; PUSH_NIL; NIL; POP``
        ——把局部变量引用常量 `(quote (loc1 ...))` 压栈，调用 `_al-bind-alist`
        绑定为 nil，再丢弃返回值。`_al-bind-alist` 为保留大小写的 0x56 单符号。
        """
        const = ("LIST", tuple(("SYMBOL", l) for l in func.locals))
        const_idx = self.symtab.add_constant(const)
        al_idx = self.symtab.get_or_add("_al-bind-alist")
        if self.stub_format:
            buf.emit(encode_op_u16(PUSH_G, const_idx))
            buf.emit(encode_func3(1, al_idx))
            buf.emit(encode_op_noarg(0x00))  # NIL
            buf.emit(encode_op_noarg(PUSH_NIL))  # PUSH_NIL
            buf.emit(encode_op_noarg(0x00))  # NIL
            buf.emit(encode_op_noarg(POP))  # POP
        else:
            buf.emit(encode_op_u16(PUSH_G, const_idx))
            buf.emit(encode_func(1, al_idx))
            buf.emit(encode_op_noarg(POP))

    def _emit_tail_call(self, buf: BytecodeBuffer, args: List[Node]):
        for i, arg in enumerate(args):
            if i < len(self.current_func_args):
                self._emit_expr(buf, arg)
                buf.emit(encode_op_u16(SET_LOCAL_16, i))
        jmp_back = buf.pos()
        buf.emit(encode_op_s32(JUMP, 0))
        buf.add_patch(jmp_back + 1, self._tail_entry_label, 4)

    def _emit_clear_args(self, buf: BytecodeBuffer, args: List[str]):
        if self.stub_format:
            # CAD stub: CLEAR_ARGS(0x19) 带 2 字节参数计数（实测 `19 <argc> 00`）。
            buf.emit(encode_op_u16(CLEAR_ARGS, len(args)))
            return
        if args:
            buf.emit(encode_op_u16(CLEAR_ARGS, len(args)))

    def generate_function(self, func: Defun) -> Tuple[bytes, int]:
        if func.quoted:
            return self._generate_quoted_defun(func)

        saved_name = self.current_func_name
        saved_args = self.current_func_args
        saved_label = self._tail_entry_label
        saved_nl_pos = len(self._nested_lambdas)
        saved_slots = self.local_slots
        saved_next = self.next_slot
        # 每个函数独立分配局部槽：foreach/repeat 的内部槽（__foreach_list__ 等）
        # 从 0 开始（i18n-cad update-locale-all foreach 槽 0 实测）；next_slot
        # 与 local_slots 不得跨函数累积。
        self.local_slots = {}
        self.next_slot = 0

        self.current_func_name = func.name
        all_args = func.args + func.optional + ([func.rest] if func.rest else [])
        self.current_func_args = all_args
        self._tail_entry_label = f"_tail_entry_{func.name}_{id(func)}"

        buf = BytecodeBuffer()
        start_offset = 0

        self._emit_defun_header(buf, func)
        start_offset = 3

        for i, arg in enumerate(all_args):
            self.local_slots[arg] = i
        self.next_slot = max(self.next_slot, len(all_args))

        self._emit_init_args(buf, all_args)

        if self.stub_format and func.locals:
            self._emit_al_bind_alist(buf, func)

        buf.label(self._tail_entry_label)

        if not (self.stub_format and func.locals):
            # stub + `/ 局部变量`：CAD 用 `_al-bind-alist` 协议绑定局部变量
            # （符号槽），不占局部槽（i18n-cad load-locale 实测 foreach 槽=参数数）。
            for i, loc in enumerate(func.locals):
                slot = i + len(all_args)
                self.local_slots[loc] = slot
                self.next_slot = max(self.next_slot, slot + 1)

        arity_bound = all_args + func.locals
        for name in set(self.local_slots.keys()) - set(arity_bound):
            pass

        # CAD 忽略 defun 后第一个裸字符串（docstring，AutoLISP 惯例）：
        # `(defun f () "文档说明" body...)` 编译时不生成该字符串
        # （docstr.fas CAD 实测 strings 为空）。仅当它是函数体**首个**独立
        # 字符串字面量时跳过，不影响 `(strcat "a" "b")` 等表达式内字符串。
        body = func.body
        if body and isinstance(body[0], String) and len(body) > 1:
            body = body[1:]

        for expr in body[:-1]:
            self._emit_stmt(buf, expr)
            # CAD stub: SETQ_G 自身消费栈顶值，中间 setq 后无 POP（v10/v11 实测）；
            # while 循环结束栈已清空（条件被 JMP32_IFNOT 消费、体结果各被 POP），
            # 中间 while 后同样无 POP（t04_while 实测）。
            # foreach stub 自带 CLEAR_ARGS 1 清理预载，repeat stub 栈已平衡，
            # 二者中间体后均无 POP（t16/t17 实测）。
            # 中间 if：then 分支为 setq 时 SETQ_G 已消费栈顶，无 POP；then 为
            # 普通表达式时保留值，追加 POP 丢弃（i18n-cad update-locale 实测
            # 内层 if-then @::load-module 调用后 `POP`）。POP 由 _emit_if 在
            # then 分支末尾（JUMP 前）内部处理，此处对 if 一律跳过，避免二次 POP。
            if not self.stub_format or isinstance(expr, (Setq, WhileNode, ForeachNode, RepeatNode)):
                pass
            elif isinstance(expr, IfNode):
                pass
            else:
                buf.emit(encode_op_noarg(POP))
        if body:
            self._emit_expr(buf, body[-1], _tail=True)
        elif self.stub_format:
            buf.emit(encode_op_noarg(PUSH_NIL))

        if self.stub_format:
            # CAD stub: 有参函数以 CLEAR_ARGS(0x19, <argc>) 结尾；无参函数直接结束。
            # 含 `/ 局部变量` 时 CLEAR_ARGS = argc + locals（t11_localvars 实测 3）。
            # 无参但含局部变量的函数（如 @::load-mt `/ *error*`）同样发 CLEAR_ARGS
            # （i18n-cad 实测 `19 01 00` 收尾）。
            if func.args or func.locals:
                buf.emit(encode_op_u16(CLEAR_ARGS, len(func.args) + len(func.locals)))
        else:
            self._emit_clear_args(buf, func.args)

        buf.resolve()

        self.current_func_name = saved_name
        self.current_func_args = saved_args
        self._tail_entry_label = saved_label
        self.local_slots = saved_slots
        self.next_slot = saved_next

        self._func_nested_lambdas[func.name] = [n for n in self._nested_lambdas if saved_nl_pos <= n[0]]
        del self._nested_lambdas[saved_nl_pos:]

        return bytes(buf.data), start_offset

    def _generate_quoted_defun(self, func: Defun) -> Tuple[bytes, int]:
        buf = BytecodeBuffer()

        lambda_body = func.body
        lambda_sym = Symbol("lambda")
        lambda_args: List[Node] = []
        for a in func.args:
            lambda_args.append(Symbol(a))
        if func.locals:
            lambda_args.append(Symbol("/"))
            for l in func.locals:
                lambda_args.append(Symbol(l))
        lambda_call = ListExpr(items=[lambda_sym] + [ListExpr(items=lambda_args)] + lambda_body)
        quoted = QuotedExpr(expr=lambda_call)

        self._emit_setq_expr(buf, Symbol(func.name), quoted)
        buf.resolve()
        return bytes(buf.data), 0

    def generate_init_code(self, forms: List[Node]) -> bytes:
        buf = BytecodeBuffer()
        for form in forms:
            self._emit_expr(buf, form)
            buf.emit(encode_op_noarg(POP))
        buf.resolve()
        return bytes(buf.data)
