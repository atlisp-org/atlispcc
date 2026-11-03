import struct
from contextlib import contextmanager
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
    encode_eval,
    encode_real,
    encode_defun,
)


#: AutoLISP 32 位有符号整数范围（fix 文档：超出该范围的值按截断实数处理）
_INT32_MIN = -2147483648
_INT32_MAX = 2147483647


from compiler.cad_symbols import normalize_vla_name
from compiler.symbol_table import SymbolTable

PUSH_T = NAME_TO_OPCODE["PUSH_T"]  # 0x02
PUSH_NIL = NAME_TO_OPCODE["PUSH_NIL"]  # 0x01
PUSH_VALUE = NAME_TO_OPCODE["PUSH_VALUE"]  # 0x03
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
            if _ast_contains_loop(val):
                return True
        return False
    if isinstance(node, (list, tuple)):
        for it in node:
            if _ast_contains_loop(it):
                return True
    return False


def _direct_loop_depth(node, depth: int = 0) -> int:
    """直接体中 foreach/repeat 的**最大并发嵌套深度**。

    CAD 的 DEFUN 头 b1 = argc + 此深度（每个并发循环占一个列表局部槽）：
    - sum-foreach（1 层）→ b1=argc+1（t16 实测）
    - add-menus/remove-pkg-menu/cache-clear-all（嵌套 2 层）→ b1=argc+2
    - dbclicked（2 个并列循环）→ b1=argc+1
    - 循环在 lambda/defun/quoted 内 → 不计（b1=argc）
    """
    if isinstance(node, (ForeachNode, RepeatNode)):
        d = depth + 1
        for val in vars(node).values():
            d = max(d, _direct_loop_depth(val, depth + 1))
        return d
    if isinstance(node, (LambdaNode, Defun, QuotedExpr)):
        return depth  # 独立函数作用域，不穿透
    if isinstance(node, Node):
        d = depth
        for val in vars(node).values():
            d = max(d, _direct_loop_depth(val, depth))
        return d
    if isinstance(node, (list, tuple)):
        d = depth
        for it in node:
            d = max(d, _direct_loop_depth(it, depth))
        return d
    return depth


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
        # CAD 紧凑 stub 的 USUBR/FUNC：符号槽 ≤255 用 3 字节 `35 <argc> <idx8>`；
        # 符号槽 >255（大文件，atlisp_u 实测）用 5 字节 `35 <argc> <idx16> <flags>`
        # （CAD 大文件 seg0/module code 实测 idx 2537/1036）。按符号表规模统一选择。
        # 用 len(entries)（codegen 会追加嵌套 defun 参数、kwote lambda `-lambda-`
        # 槽等）而非 codegen_nsyms：panel.lsp codegen_nsyms=251 但最终 fas_nsyms
        # =266，若按 251 判 short 会截断 idx>255 的 USUBR（`+` → 0x1a=26），
        # `_patch_usubr_idx` 无法恢复。len(entries)>256 保守判 wide 与 fas_nsyms
        # 判定一致（fas_nsyms = len(entries)-module_reg+1 < len(entries)）。
        self.wide_subr = stub_format and (self.nsyms > 256 or len(symtab.entries) > 256)
        self.local_slots: Dict[str, int] = {}
        self.next_slot = 0
        # 直接体并发循环深度（foreach/repeat 局部槽分配）：同一深度顺序循环
        # 复用同一槽（CAD reactor.lsp 实测两个顺序 foreach 都 SET_LOCAL 2），
        # 嵌套循环递增深度用独立槽（与 DEFUN 头 b1=argc+并发深度对应）。
        self._loop_depth = 0
        # 函数体内嵌套 defun（`_emit_nested_defun`）深度：>0 时参数按真实
        # 符号槽绑定/读取（嵌套参数非顶部槽）。
        self._nested_defun_depth = 0
        # 嵌套 lambda（`-lambda-`，`_emit_nested_lambda`）：>0 时体内参数读取
        # 与嵌套 defun 同规则（真实符号槽，addsupportpath 实测：立即 lambda
        # 读取与宿主函数同名的参数 `lst` 若走单函数 nsyms 顶部槽公式会错 1，
        # CAD 用其真实注册槽）。
        self._in_nested_lambda = False
        # 嵌套函数名兼作外层 `/ 局部`（影子）标志（string-utils s2la）
        self._nested_shadowing = False
        # 控制流标签/槽命名计数器：所有 `_if_*/_while_*/_foreach_*/...` 名字以
        # buf.pos() 为基，但嵌套控制流可能在相同 pos 处开始（外层 if 先编译
        # cond，cond 首 form 是内层 if → 两者基址相同 → 标签名冲突，后 patch
        # 覆盖先 patch，跳转错位。catchapply.lsp `(if (not (vl-catch-all-apply
        # (if ...) ...)) ...)` CAD golden 实测 JMP32_IFNOT 8 vs ours 46）。追加
        # 单调计数器保证全局唯一。
        self._ctl_seq = 0
        self.current_func_name: str = ""
        self.current_func_args: List[str] = []
        self._tail_entry_label: str = ""
        self._in_tail_context: bool = False
        self.func_offset_map: Dict[str, int] = {}
        self.stub_offsets: List[int] = []
        self._nested_lambdas: List[tuple] = []
        self._func_nested_lambdas: dict = {}
        self._nested_defuns: List[tuple] = []
        self._func_nested_defuns: dict = {}
        self._defined_funcs: set = set(defined_funcs or [])
        self._func_ref_slots: Dict[str, int] = {}
        self._ancestor_funcs: List[str] = []
        self._module_mode: bool = False
        # 模块代码（seg1 顶层表达式）编译上下文：与 `_module_mode` 不同，该标志
        # 在 `_emit_stmt`（cond 子句体等语句上下文）清 `_module_mode` 时**保持
        # 不清**——模块代码里的跨函数调用用模块注册槽，不应分配重复符号槽
        # （platform.lsp 顶层 cond 调 `@::set-locale` CAD 实测无重复槽，否则
        # fg 区多出 `@::SET-LOCALE` 重复槽、VAL 与函数名合并进同一 5b 块）。
        self._module_code_ctx: bool = False
        # 语句上下文（值将被 POP 丢弃）：仅裸语句位置（函数体中间语句、
        # progn 中间语句、循环体）置位。值上下文（setq RHS、函数/算术实参）
        # 不置位——_emit_if 据此决定 then 分支尾是否兼 POP。
        self._in_stmt_ctx: bool = False
        # let body 尾 if 的 else fall-through 后 USUBR(2, LET)（CAD 原生 LET
        # 清理，minlet/let3 CAD 真机实测）——`_emit_let` 设置、`_emit_if` 读取。
        self._in_let_tail: int = 0

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

    def _emit_usubr(self, buf: BytecodeBuffer, argc: int, idx: int):
        """stub USUBR：符号槽 ≤255 用 3 字节；>255（大文件）用 5 字节
        `35 <argc> <idx16> <flags=3>`（CAD atlisp_u 实测）。"""
        if self.wide_subr:
            buf.emit(encode_usubr(argc, idx, flags=3))
        else:
            buf.emit(encode_usubr3(argc, idx))

    def _emit_subr_cleanup(self, buf: BytecodeBuffer):
        """调用后清理：小文件 `00 03`（NIL + PUSH_VALUE 0）；大文件 flags=3
        已内联在 5 字节 USUBR 里，无需额外清理（CAD atlisp_u seg0/module code
        实测 USUBR 后直接跟下一指令）。"""
        if not self.wide_subr:
            buf.emit(encode_op_noarg(0x00))
            buf.emit(bytes([PUSH_VALUE]))

    def _emit_func3(self, buf: BytecodeBuffer, argc: int, idx: int):
        """stub FUNC：同 USUBR 的 3/5 字节选择。大文件 FUNC 6 字节
        `51 <argc> <idx16> <flags=1> 00`（CAD atlisp_u 实测 flags=1）。"""
        if self.wide_subr:
            buf.emit(encode_func(argc, idx, flags=1))
        else:
            buf.emit(encode_func3(argc, idx))

    def _emit_arith(self, buf: BytecodeBuffer, op_name: str, args: List[Node]):
        if self.stub_format:
            with self._value_ctx():
                for arg in args:
                    self._emit_expr(buf, arg)
            idx = self.symtab.get_or_add(op_name)
            self._emit_usubr(buf, len(args), idx)
            self._emit_subr_cleanup(buf)
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
            self._emit_usubr(buf, 1, idx)
            self._emit_subr_cleanup(buf)
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

    @contextmanager
    def _value_ctx(self):
        saved = self._in_stmt_ctx
        self._in_stmt_ctx = False
        try:
            yield
        finally:
            self._in_stmt_ctx = saved

    def _ctl(self, prefix: str, pos: int = 0) -> str:
        self._ctl_seq += 1
        return f"_{prefix}_{self._ctl_seq}_{pos}"

    def _is_function_symbol(self, name: str) -> bool:
        """符号是否为本文件定义的函数（模块代码函数别名 setq 用 PUSH_G 判定）。"""
        fo = getattr(self.symtab, "function_offsets", None) or {}
        return name in fo or name.lower() in {str(k).lower() for k in fo}

    def _emit_stmt(self, buf: BytecodeBuffer, node: Node):
        """在语句上下文（值被丢弃）中发射一条表达式。

        语句上下文非尾：值被丢弃，故临时清 `_in_tail_context`，避免 foreach/
        repeat/if 误按尾上下文编译（cond 分支内中间 foreach 实测多出 PUSH_NIL
        + POP 占位，CAD 无此结构——hkrepro `@::handle-keywords` 的
        `(foreach ...)` 后接 `expr`）。
        """
        saved = self._in_stmt_ctx
        saved_tail = self._in_tail_context
        saved_module = self._module_mode
        self._in_stmt_ctx = True
        self._in_tail_context = False
        # 语句上下文（值被丢弃）：清 `_module_mode`，避免 cond 子句体内的 if
        # 误按模块代码顶层 if 编译（then 分支 setq 加 DUP、无 else 补 PUSH_NIL
        # ——test-cond CAD 实测子句体 if 无 `0b`/`01`）。模块代码独立顶层 if
        # 仍经 `_emit_expr` 保留 `_module_mode`。
        self._module_mode = False
        try:
            if isinstance(node, IfNode):
                self._emit_if(buf, node)
            elif isinstance(node, Defun):
                self._emit_nested_defun(buf, node)
            else:
                self._emit_expr(buf, node)
        finally:
            self._in_stmt_ctx = saved
            self._in_tail_context = saved_tail
            self._module_mode = saved_module

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
                    # （t18 小写 t、t22 大写 T golden 实测，大小写不敏感），非
                    # PUSH_T 内联。仅 `(and ...)` 短路尾 / cond else 键等由
                    # 各自发射点处理。SymbolTable 对 t/T 归一化到 `T` 槽。
                    idx = self.symtab.get_or_add(name)
                    self._emit_push_value(buf, idx)
                else:
                    buf.emit(encode_op_noarg(PUSH_T))
            elif self.stub_format:
                if name in self.current_func_args and name in self.local_slots:
                    if self._nested_defun_depth or self._in_nested_lambda:
                        # 嵌套 defun/lambda 参数读取用真实符号槽（收集器分配）
                        idx = self.symtab.get_or_add(name)
                    elif len(self._defined_funcs) <= 1:
                        # 单函数参数读取逆序（CAD simple3/t13 实测：`+ Z Y X`、
                        # `> C B A`——源码第 i 个参数 → 槽 nsyms-1-i）。
                        idx = self.nsyms - 1 - self.local_slots[name]
                    else:
                        # 多函数参数读取：用参数的真实符号槽（get_or_add），
                        # `_patch_usubr_idx` 凭 `sym_of(idx) ∈ cur_args` 识别
                        # 并改写为 gvar 槽。此前用 `codegen_nsyms - argc + i`
                        # 占位，会与真实符号槽碰撞（lambda_body 实测 `t` 槽
                        # == codegen_nsyms-argc，被参数分支误判 → "函数错误: nil"）。
                        idx = self.symtab.get_or_add(name)
                else:
                    idx = self.symtab.get_or_add(name)
                self._emit_push_value(buf, idx)
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
            if _INT32_MIN <= val <= _INT32_MAX:
                if -128 <= val <= 127:
                    buf.emit(encode_op_u8(PUSH_INT8, val & 0xFF))
                else:
                    buf.emit(struct.pack("<Bi", PUSH_INT32, val))
            else:
                # 超出 32 位有符号整数范围（fix 文档）：AutoLISP 读入/返回截断实数，
                # 而非按补码回绕成负数——值原样保留。
                if self.stub_format:
                    idx = self.symtab.add_real(float(val))
                    buf.emit(encode_op_u16(PUSH_G, idx))
                else:
                    buf.emit(encode_real(float(val)))

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
            # CAD 丢弃语句位置（值被丢弃）的裸字符串（docstring/分节注释，
            # `strip_docstring` 只处理 defun 体顶层；progn/if/cond 等内嵌语句
            # 位置的裸串 CAD 同样不发射不注册——example/sort/error-exit golden
            # 实测）。仅值/尾上下文（返回值被使用）的字符串保留。
            if self._in_stmt_ctx:
                return
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
                # `((lambda (a b) body...) args...)` 立即应用：CAD 编译为
                # 「内嵌 -lambda- DEFUN + EVAL」——实参先求值（留栈），JUMP 跳过
                # `-lambda-` DEFUN，然后 `PUSH_G <-lambda->; EVAL argc, 7;
                # CLEAR_ARGS argc`（dcl `(lambda (dcl-str dcl-name) ...)` 实测
                # `USUBR; USUBR; JUMP; DEFUN -lambda-; ...; PUSH_G; EVAL 2, 7;
                # CLEAR_ARGS 2`）。
                _lam = node.items[0]
                _args = node.items[1:]
                _argc = len([a for a in _lam.args if a != "/"])
                with self._value_ctx():
                    for _a in _args:
                        self._emit_expr(buf, _a)
                _lam_idx = self._emit_nested_lambda(buf, _lam)
                buf.emit(encode_op_u16(PUSH_G, _lam_idx))
                buf.emit(encode_eval(_argc, 7))
                return
            if node.items and isinstance(node.items[0], Call):
                # 计算函数调用 `((eval fun) a b)`（list/sort、list/split-by、
                # list/group-by、pickset/get-sub；CAD `EVAL <argc>, 7` 协议）：
                # 求值头表达式得到函数值（最后压栈=栈顶），实参先求值留栈。
                # 旧路径按数据列表 BUILD_LIST 发射，与 CAD EVAL 差 2 字节。
                _cargs = node.items[1:]
                with self._value_ctx():
                    for _ca in _cargs:
                        self._emit_expr(buf, _ca)
                    self._emit_expr(buf, node.items[0])
                buf.emit(encode_eval(len(_cargs), 7))
                self._in_tail_context = saved_tail
                return
            if node.dotted is not None:
                self._emit_expr(buf, node.dotted)
                for item in reversed(node.items):
                    self._emit_expr(buf, item)
                    buf.emit(encode_op_noarg(CONS))
                return
            if not node.items:
                # `()` 空列表 = nil：CAD 仅发射 `PUSH_NIL`（test/clear 实测
                # `(setq *x* ())` → `01 06 04 00`，无 `BUILD_LIST 0`）。
                buf.emit(encode_op_noarg(PUSH_NIL))
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
                # 语句位置裸字符串被丢弃（`_emit_expr` String 分支 in_stmt 空发射）；
                # 其后不得补 POP（error-exit/sort golden：`(progn "分节注释" expr)`
                # CAD 无 `0a`，此前多 1 个 → seg0 +1/+6）。
                if isinstance(form, String):
                    continue
                self._emit_stmt(buf, form)
                # 中间 setq（SETQ_G 已消费栈顶）、中间 if（_emit_if 内部处理）、
                # while/foreach/repeat（自带栈平衡）后均无 POP；仅普通表达式
                # 追加 POP（规则同 generate_function 中间语句）。中间 progn 自身
                # 已 POP 末 form 值（语句上下文，见本分支末），不再补 POP
                # （dialog.lsp DCL 嵌套 `(progn ... (dcl:end-cluster))` CAD 实测
                # 仅 1 个 `0a`，此前多 1 个）。
                if not isinstance(
                    form, (IfNode, Setq, WhileNode, ForeachNode, RepeatNode, Cond, Defun, Progn)
                ):
                    buf.emit(encode_op_noarg(POP))
            if node.forms:
                self._in_tail_context = saved_tail
                _last = node.forms[-1]
                # 语句上下文（值被丢弃）progn 末 `nil`/`T`：PUSH+POP 为纯 no-op，
                # CAD 省略（cl-functions `(progn ... nil)`、permission `(progn
                # ... T)` 模块代码/函数体实测无 `01 0a`/`T 槽;POP`）。尾/值上下文
                # （值被使用）仍发射。语句上下文末裸字符串同理省略。
                _last_const_stmt = (
                    isinstance(_last, Symbol)
                    and _last.name.lower() in ("nil", "t")
                    and not saved_tail
                )
                _last_str_stmt = isinstance(_last, String) and self._in_stmt_ctx and not saved_tail
                if not (_last_const_stmt or _last_str_stmt):
                    self._emit_expr(buf, _last, _tail=saved_tail)
                _selfbal = isinstance(_last, (Setq, WhileNode, ForeachNode, RepeatNode, Progn, Cond))
                if isinstance(_last, IfNode) and self._in_stmt_ctx:
                    _selfbal = True
                # 值上下文（`_in_stmt_ctx=False`、非模块代码，如函数实参的
                # `(progn ...)`）末 form 值保留给外层消费者——不 POP（dialog.lsp
                # `(set_tile ... (progn ... (if ... rd%)))` CAD 实测 else 分支
                # `rd%` 值保留给 set_tile）。语句上下文与模块代码顶层语句
                # （@lisp-env 顶层 `(progn ...)` 值被丢弃）仍 POP。
                if (
                    not saved_tail
                    and (self._in_stmt_ctx or self._module_mode)
                    and not _selfbal
                    and not _last_const_stmt
                    and not _last_str_stmt
                ):
                    buf.emit(encode_op_noarg(POP))
            self._in_tail_context = saved_tail

        elif isinstance(node, Cond):
            self._emit_cond(buf, node)

        elif isinstance(node, LambdaNode):
            # 裸 lambda 值（函数返回/表达式值，load.lsp `@::load-error-handler`
            # `(lambda (msg / fp) ...)` 返回 CAD 实测 `-lambda-` DEFUN）走内嵌
            # `-lambda-`（与 `_emit_setq_value` 同规则）。quoted `'(lambda ...)`
            # 仍走 `_emit_quoted`（数据 const，`_emit_quoted` 的 LambdaNode 分支）。
            lam_idx = self._emit_nested_lambda(buf, node)
            buf.emit(encode_op_u16(PUSH_G, lam_idx))

        elif isinstance(node, Defun):
            # 函数体内嵌套 `(defun inner ...)`（含 if/cond 分支内，n6 实测）：
            # CAD 发射内嵌 DEFUN 块 + PUSH_G/SETQ_G 注册，无值压栈（自平衡）。
            self._emit_nested_defun(buf, node)

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

        if upper == "LET" and args:
            self._emit_let(buf, node)
            return

        if name in ARITH_OP_TO_FAS:
            self._emit_arith(buf, name, args)
            return
        if name in UNARY_OP_TO_FAS and len(args) == 1:
            self._emit_unary(buf, name, args[0])
            return
        if name.lower() in ("and", "or"):
            lname = name.lower()
            if len(args) == 0:
                if lname == "and":
                    buf.emit(encode_op_noarg(PUSH_T))
                else:
                    buf.emit(encode_op_noarg(PUSH_NIL))
                return
            self._emit_short_circuit(buf, lname, args)
            return
        if name == "list":
            if self.stub_format:
                for arg in args:
                    self._emit_expr(buf, arg)
                idx = self.symtab.get_or_add("list")
                self._emit_usubr(buf, len(args), idx)
                self._emit_subr_cleanup(buf)
                return
            for arg in reversed(args):
                self._emit_expr(buf, arg)
            buf.emit(encode_op_u16(BUILD_LIST, len(args)))
            return
        if name == "progn":
            for form in args[:-1]:
                if isinstance(form, String):
                    continue
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
        # `(exit)/(quit)/(abort)`：CAD 编译成普通 `USUBR <argc>, <sym>` 调用
        # （ui/button-select golden `35 00 17 USUBR 0, EXIT`，EXIT 为普通符号
        # 槽）。旧特判发 `PUSH_T; EXIT_IF_NOT_ZERO`（短 3~6 字节）与 CAD 不符，
        # 导致 dcl/new、ui/* 等 10 个含 (exit) 文件 seg0 短 3-6 字节。死代码
        # 消除在 opt.py 走 AST 层（_is_terminal），不依赖此处的字节特判。
        # CAD 把 `command` 内建 SUBR 的调用目标注册为独立符号槽 `ads-cmd`
        # （base-function CAD 实测 `(command ...)` → `ads-cmd`），与值引用
        # 的普通符号槽 `COMMAND`（platform 实测）分离——两者是不同的槽。
        # `command` 本身**不**注册（net/wget 实测无 COMMAND 符号，仅 ads-cmd），
        # 需在 `get_or_add(name)` 之前特判，否则多出 COMMAND 槽。
        if self.stub_format and name == "command":
            idx = self.symtab.get_or_add("ads-cmd")
        else:
            idx = self.symtab.get_or_add(normalize_vla_name(name))
        if (
            self.stub_format
            and not self._module_mode
            and not self._module_code_ctx
            and name in self._defined_funcs
            and name != self.current_func_name
        ):
            # 跨函数调用：CAD 用重复符号槽（首次引用分配新槽）。模块代码
            # （_module_code_ctx）里的跨函数调用用模块注册槽，不分配重复槽。
            if name not in self._func_ref_slots:
                rep = self.symtab.next_repeat_slot(name)
                self._func_ref_slots[name] = rep if rep >= 0 else self.symtab.add_force(name)
            idx = self._func_ref_slots[name]
        elif self.stub_format and (
            name == self.current_func_name
            or (
                self._in_nested_lambda
                and any(str(a).upper() == name.upper() for a in self._ancestor_funcs)
            )
        ):
            # 递归调用（含尾位置）：CAD 用重复符号槽。**嵌套 defun**（函数体内
            # `(defun inner ...)`）的递归槽已由收集器注册（嵌套块 body refs，
            # version @::pkg-deps-tree-rec 递归 `(deps-tree-rec d ...)`），
            # 不再 add_force 新建重复槽——否则多出符号槽（nsyms +1、CAD 无）。
            # **例外**：嵌套名兼作外层 `/ 局部`（影子，string-utils `s2la`）时
            # CAD 独立注册递归槽（不并入名字槽），此时 add_force。
            if self._nested_defun_depth:
                if self._nested_shadowing:
                    rep = self.symtab.next_repeat_slot(name)
                    self._func_ref_slots[name] = rep if rep >= 0 else self.symtab.add_force(name)
                    idx = self._func_ref_slots[name]
                else:
                    idx = self.symtab.get_or_add(name)
            elif name not in self._func_ref_slots:
                rep = self.symtab.next_repeat_slot(name)
                self._func_ref_slots[name] = rep if rep >= 0 else self.symtab.add_force(name)
                idx = self._func_ref_slots[name]
            else:
                idx = self._func_ref_slots[name]
        is_builtin = self.symtab.is_builtin(name)
        if self.stub_format and name == "command":
            # CAD 把 `(command a b ...)` 编译为每个参数一次独立的 `FUNC 1
            # <ads-cmd>` 调用（platform-api `(command "shell" (strcat ...))`
            # 实测：`PUSH_G <arg1>; FUNC 1; NIL PUSH_NIL NIL; POP; ...arg2...;
            # FUNC 1; NIL PUSH_NIL NIL`）。中间 POP 丢弃前次调用结果，末次
            # 调用的值留给外层语句上下文丢弃。此前用单次 `FUNC <argc>` 会报
            # "参数太多"（CAD 的 command 每参数 argc=1）。
            for _i, _arg in enumerate(args):
                with self._value_ctx():
                    self._emit_expr(buf, _arg)
                self._emit_func3(buf, 1, idx)
                if not self.wide_subr:
                    # 小文件 3 字节 FUNC：CAD 追加 `NIL; PUSH_NIL; NIL` 清理
                    # （platform-api 实测）。大文件 6 字节 FUNC flags=1 已内联
                    # 清理语义（CAD atlisp_u 实测 `FUNC; POP`，无 `NIL;
                    # PUSH_NIL; NIL`，同 `_al-bind-alist` 的 wide 逻辑）。
                    buf.emit(encode_op_noarg(0x00))  # NIL
                    buf.emit(encode_op_noarg(PUSH_NIL))  # PUSH_NIL
                    buf.emit(encode_op_noarg(0x00))  # NIL
                if _i < len(args) - 1:
                    buf.emit(encode_op_noarg(POP))
            return
        with self._value_ctx():
            for arg in args:
                self._emit_expr(buf, arg)
        if self.stub_format:
            if name == "command":
                # `command`（CAD 内部 SUBR `ads-cmd`）非 USUBR 内建：CAD 用
                # FUNC 编码调用 + `NIL; PUSH_NIL; NIL` 清理（base-function
                # CAD 实测 `FUNC(1,162); NIL; PUSH_NIL; NIL`，同 `_al-bind-alist`）。
                self._emit_func3(buf, len(args), idx)
                buf.emit(encode_op_noarg(0x00))  # NIL
                buf.emit(encode_op_noarg(PUSH_NIL))  # PUSH_NIL
                buf.emit(encode_op_noarg(0x00))  # NIL
            else:
                self._emit_usubr(buf, len(args), idx)
                # CAD stub: 每次调用后 NIL + PUSH_VALUE[0]（结果清理/保留）
                self._emit_subr_cleanup(buf)
        elif is_builtin:
            self._emit_func3(buf, len(args), idx)
        else:
            self._emit_usubr(buf, len(args), idx)

    def _emit_let(self, buf: BytecodeBuffer, node: Call):
        """CAD 原生 LET（event-bus CAD golden 实测）：

        `(let ((v1 e1) (v2 e2) ...) body...)` →
        ```
        <e1 求值>; USUBR(1, list); <e2 求值>; USUBR(1, list); ...
        EVAL 0, 7          ; LET 内建：绑定列表建立局部环境，执行后续 body
        <body...>
        ```
        不生成 `-lambda-`（fg 注册 LET/LIST 符号，bindings 变量为普通符号槽，
        body 用 PUSH_VALUE 读取——event-bus `(let ((entry (assoc ...))) (if
        entry ...))` 实测 `USUBR; EVAL 0; PUSH_VALUE entry; JMP32_IFNOT`）。
        """
        bindings = node.args[0]
        body = node.args[1:]
        if isinstance(bindings, ListExpr):
            bound = []
            bare = []
            for b in bindings.items:
                if isinstance(b, Call) and b.args:
                    bound.append((b.name, b.args[0]))
                elif isinstance(b, ListExpr) and len(b.items) > 1:
                    v = b.items[0].name if isinstance(b.items[0], Symbol) else str(b.items[0])
                    bound.append((v, b.items[1]))
                else:
                    v = b.name if isinstance(b, Symbol) else str(b)
                    bare.append(v)
            if bare:
                # 带裸变量的 LET（nlp.lsp CAD golden）：**先**把全部裸变量符号
                # `PUSH_VALUE <var>` 推入，再对每个有值绑定 `value; USUBR(1,
                # <var>); NIL; PUSH_VALUE[0]`，最后 `EVAL <n_bare>, 7`（EVAL
                # argc = 裸变量数；CMD-MATCH-WEB `(let ((lst-cmd <e>) expr
                # pkg-to-ins)` 实测 `PUSH_VALUE expr; PUSH_VALUE pkg-to-ins;
                # <e>; USUBR(1,lst-cmd); EVAL 2,7`）。
                for v in bare:
                    self._emit_push_value(buf, self.symtab.get_or_add(v))
                for v, e in bound:
                    # CAD 原生 LET（minlet CAD 真机实测）：绑定值求值后 `USUBR(1,
                    # <绑定变量槽>)`——`(x (1+ a))` 的 USUBR(1,x槽)、event-bus
                    # `(entry (assoc ...))` 的 USUBR(1,entry槽)——非 `(list ...)`。
                    # `_patch_usubr_idx` 映射到 gvar 槽（操作数 = gvar-1）。
                    self._emit_expr(buf, e)
                    v_idx = self.symtab.get_or_add(v)
                    self._emit_usubr(buf, 1, v_idx)
                    # CAD let 绑定构造后清理占位（minlet 实测 `USUBR; NIL;
                    # PUSH_VALUE[0]; EVAL`）——`_emit_subr_cleanup` 小文件输出
                    # `00 03`（NIL + PUSH_VALUE 0）。
                    self._emit_subr_cleanup(buf)
                buf.emit(encode_eval(len(bare), 7))
            else:
                for v, e in bound:
                    # CAD 原生 LET（minlet CAD 真机实测）：绑定值求值后 `USUBR(1,
                    # <绑定变量槽>)`——`(x (1+ a))` 的 USUBR(1,x槽)、event-bus
                    # `(entry (assoc ...))` 的 USUBR(1,entry槽)——非 `(list ...)`。
                    # `_patch_usubr_idx` 映射到 gvar 槽（操作数 = gvar-1）。
                    self._emit_expr(buf, e)
                    v_idx = self.symtab.get_or_add(v)
                    self._emit_usubr(buf, 1, v_idx)
                    # CAD let 绑定构造后清理占位（minlet 实测 `USUBR; NIL;
                    # PUSH_VALUE[0]; EVAL`）——`_emit_subr_cleanup` 小文件输出
                    # `00 03`（NIL + PUSH_VALUE 0）。
                    self._emit_subr_cleanup(buf)
                buf.emit(encode_eval(0, 7))
        _saved_let_tail = self._in_let_tail
        try:
            for _bi, form in enumerate(body):
                if _bi == len(body) - 1:
                    # let 的 body 最后 form 是 let 的值（尾上下文）：if 分支 setq
                    # DUP 保留值（event-bus `(let ((entry ...)) (if entry (setq
                    # ...) (setq ...)))` CAD 实测 `DUP; SETQ_G`）；尾 if 的 end
                    # 后 USUBR(<argc>, LET)（见 `_emit_if` `_in_let_tail`）。argc =
                    # len(body)+1（nlp.lsp CAD golden：cmd-ai-fallback 4 个 body
                    # form → `USUBR(5, LET)`，event-bus/1 form → `USUBR(2, LET)`）。
                    self._in_let_tail = len(body) + 1
                    try:
                        self._emit_expr(buf, form, _tail=True)
                    finally:
                        self._in_let_tail = False
                else:
                    # 非末 form 也是 let 的值来源之一（CAD 累积在栈上，尾部
                    # USUBR(argc, LET) 统一收集）：按**尾/值上下文**编译——else-less
                    # if 补 PUSH_NIL 占位、表达式不 POP、foreach/repeat 走尾协议
                    # （nlp.lsp cmd-ai-fallback 4 form let 实测 forms 0-2 值均保留）。
                    with self._value_ctx():
                        self._emit_expr(buf, form, _tail=True)
        finally:
            self._in_let_tail = _saved_let_tail

    def _emit_setq_expr(self, buf: BytecodeBuffer, target: Node, value: Node):
        if isinstance(target, Symbol):
            with self._value_ctx():
                if (
                    self._module_mode
                    and isinstance(value, Symbol)
                    and self._is_function_symbol(normalize_vla_name(value.name))
                ):
                    # 模块代码中 setq 值 = 函数符号：CAD 用 PUSH_G（@lisp_u
                    # 调度器别名 `(setq @::unschedule-task @::string-to-list)`
                    # 实测 `09 <槽>`）。PUSH_VALUE 读函数槽得 SUBR，SETQ_G
                    # 绑定报"要绑定的对象不正确"。`set` 函数的值仍用 PUSH_VALUE
                    # （CAD compat 别名 `(set 'type-of cl::type-of)` 实测）。
                    _idx = self.symtab.get_or_add(normalize_vla_name(value.name))
                    buf.emit(encode_op_u16(PUSH_G, _idx))
                else:
                    self._emit_setq_value(buf, value)
            if self.stub_format:
                if self._in_tail_context:
                    buf.emit(encode_op_noarg(DUP))
                idx = self.symtab.get_or_add(normalize_vla_name(target.name))
                buf.emit(encode_op_u16(SETQ_G, idx))
            elif target.name in self.local_slots:
                slot = self.local_slots[target.name]
                buf.emit(encode_op_u16(SET_LOCAL_16, slot))
            else:
                idx = self.symtab.get_or_add(normalize_vla_name(target.name))
                buf.emit(encode_op_u16(SETQ_G, idx))
        else:
            with self._value_ctx():
                self._emit_expr(buf, value)
                self._emit_expr(buf, target)
            buf.emit(encode_func(1, self.symtab.get_or_add("set")))

    def _emit_push_value(self, buf: BytecodeBuffer, idx: int):
        """stub PUSH_VALUE：真实符号读取恒发 3 字节 `03 <u16>`（即便 symtab
        槽为 0——模块区注册的顶层变量在函数体区有独立重复槽，codegen 用
        symtab[0] 占位，`_patch_usubr_idx` 需按 gvar 槽重映射；单字节 `03`
        会丢失符号引用信息）。调用后的清理占位 `03` 由 `_emit_subr_cleanup`
        独立发射（golden 实测清理占位前必有 NIL）。大文件宽格式不受此约束
        （flags=3 已内联清理，PV[0] 仍 3 字节）。"""
        if self.stub_format and idx == 0 and not self.wide_subr:
            # 槽 0 无法区分"清理占位"与"真实槽 0 读取"，统一发 3 字节；
            # 仅 _emit_subr_cleanup 发射单字节清理占位。
            buf.emit(encode_op_u16(PUSH_VALUE, idx))
        else:
            buf.emit(encode_op_u16(PUSH_VALUE, idx))

    def _emit_setq_value(self, buf: BytecodeBuffer, value: Node):
        """发射 setq 值：裸 lambda（`(setq *error* (lambda (msg) ...))`）走
        `-lambda-` DEFUN（CAD 实测 `JUMP; DEFUN -lambda-; PUSH_G <-lambda-槽>;
        SETQ_G`），其余走 `_emit_expr`。"""
        if isinstance(value, LambdaNode):
            lam_idx = self._emit_nested_lambda(buf, value)
            buf.emit(encode_op_u16(PUSH_G, lam_idx))
        else:
            self._emit_expr(buf, value)

    def _emit_setq(self, buf: BytecodeBuffer, node: Setq):
        pairs = list(node.pairs)
        n = len(pairs)
        for i, (target, value) in enumerate(pairs):
            if isinstance(target, Symbol) and value:
                with self._value_ctx():
                    self._emit_setq_value(buf, value)
                if self.stub_format:
                    # 多对 setq 最后对：值位置（非语句上下文）总是 DUP 保留
                    # 返回值（CAD p05/i18n 实测 `PUSH; ...; DUP; SETQ_G`，与
                    # tail 无关）；语句上下文（setq 值被丢弃，如 cond 子句体
                    # if-then 分支中间的多对 setq）不 DUP（init/sequence 实测
                    # CAD `32 00; SETQ_G` 无 `0b`）。单对 setq 仅真尾上下文
                    # 才 DUP（test-cond 模块代码语句 if then 单对 `PUSH_G;
                    # SETQ_G` 无 `0b` 实测）。
                    if n > 1 and i == n - 1 and not self._in_stmt_ctx:
                        buf.emit(encode_op_noarg(DUP))
                    elif i == n - 1 and (
                        self._in_tail_context
                        or (not self._in_stmt_ctx and not self._module_mode)
                    ):
                        # 单对 setq：真尾上下文 DUP；**值上下文**（嵌套表达式，
                        # 函数体 `_in_stmt_ctx=False` 且非模块代码，browse
                        # `(mapcar ... (setq allfunlst (fun::get-list)))` 的
                        # setq 值是 mapcar 列表，CAD 实测 `DUP; SETQ_G`）DUP
                        # 保留返回值。模块代码语句（`_module_mode=True`，
                        # test-cond if-then 单对 `PUSH_G; SETQ_G` 无 `0b`）与
                        # 语句上下文不 DUP。
                        buf.emit(encode_op_noarg(DUP))
                    idx = self.symtab.get_or_add(normalize_vla_name(target.name))
                    buf.emit(encode_op_u16(SETQ_G, idx))
                elif target.name in self.local_slots:
                    slot = self.local_slots[target.name]
                    buf.emit(encode_op_u16(SET_LOCAL_16, slot))
                else:
                    idx = self.symtab.get_or_add(normalize_vla_name(target.name))
                    buf.emit(encode_op_u16(SETQ_G, idx))

    def _emit_if(self, buf: BytecodeBuffer, node: IfNode):
        label_else = self._ctl("if_else", buf.pos())
        label_end = self._ctl("if_end", buf.pos())

        # let body 尾 if 的 end 后 USUBR(2, LET)：仅**最外层** if 加（嵌套 if
        # 的 then/else 内 if 不加——nlp 多 let/嵌套过度）。保存并在进入时清
        # 标志（嵌套 if 进入时 False），label_end 处用保存值。
        _saved_let_tail = self._in_let_tail
        self._in_let_tail = False

        # 条件为值位置：`_tail=True` 使条件内值位置的 setq 保留返回值
        # （`DUP; SETQ_G`，platform-api `(if (not (vl-catch-all-error-p
        # (setq status ...))) ...)` CAD 实测 `DUP SETQ_G`），否则 SETQ_G
        # 消费栈顶导致条件判断取错值。与 while 条件同规则。
        self._emit_expr(buf, node.cond or Symbol("nil"), _tail=True)

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
            # then 分支尾上下文：尾 if / 模块代码顶层 if / 值上下文（setq RHS、
            # 外层 if 分支值）需 DUP 保留值（模块代码顶层 if-then-setq，
            # p04/i18n-cad 实测 `0b 06`）。仅独立顶层 if / 尾 if 时 DUP；
            # cond 子句体等语句上下文的 if 的 then 分支 setq 不 DUP
            # （test-cond CAD 实测 `PUSH_G; SETQ_G`）。值上下文（`_in_stmt_ctx`
            # False）的 if 分支值是外层消费者（setq RHS/外层 if）的输入——
            # `_then_tail=True` 使分支末 progn 的 `nil` 值不被 _last_nil_stmt
            # 省略（persist @::get-local-pkg-info `(progn (vl-file-delete ...)
            # nil)` 为 if then 值，CAD 发射 PUSH_NIL）。
            _then_tail = self._in_tail_context or self._module_mode or not self._in_stmt_ctx
            # 语句上下文（`_in_stmt_ctx=True`）且 then 为常量 `nil`/`T`（如
            # init/steps `(if (vl-catch-all-error-p ...) nil)` 语句）：分支值被
            # POP 丢弃，push+pop 是纯 no-op——CAD 省略整个 then 代码（实测
            # `JMP32_IFNOT; JUMP 0` 无 `01 0a`）。值上下文（分支值被使用）不省略。
            _then_const = isinstance(node.then, Symbol) and node.then.name.lower() in ("nil", "t")
            if not (self._in_stmt_ctx and _then_const):
                self._emit_expr(buf, node.then or Symbol("nil"), _tail=_then_tail)
                _then_imm = isinstance(node.then, ListExpr) and node.then.items and isinstance(
                    node.then.items[0], LambdaNode
                )
                if (
                    self._in_stmt_ctx
                    and not isinstance(
                        node.then,
                        (Setq, IfNode, Progn, WhileNode, ForeachNode, RepeatNode, Cond, Defun),
                    )
                    and not (_then_imm and _then_tail)
                ):
                    # 语句上下文（中间 if，值被丢弃）：then 分支值被 POP。值上下文
                    # （setq RHS、函数/算术实参）不 POP——值需流到外层消费者。
                    # then 为 setq 时 SETQ_G 已消费栈顶，无需 POP；普通表达式则
                    # POP 丢弃（i18n-cad update-locale 内层 if-then @::load-module
                    # 后 `POP`）。then 为 progn/if 时由其自身管理栈（i18n-cad
                    # load-locale 外层 if-then=progn 后无额外 POP）。
                    # while/foreach/repeat 自带栈平衡（循环 JUMP 回跳 + CLEAR_ARGS/
                    # 尾协议），then 后无额外 POP（platform-api @::platform-path
                    # 双 while 分支实测 CAD `57 JUMP` 直接退出，无 0a POP）。
                    # then 为立即 lambda 且 `_then_tail=True`（值保留，user-manager
                    # `(if token-callback ((lambda ...) ...) nil)` 实测
                    # `EVAL; JUMP(1); 01; CLEAR_ARGS`）不 POP；`_then_tail=False`
                    # （config-sync/file `(if content ((lambda ...) ...) nil)`
                    # 实测 `EVAL; POP; JUMP(0)`）丢弃 EVAL 结果。
                    # POP 位于 then 末尾、JUMP 之前（ref 实测顺序 `03 0a 57`）。
                    buf.emit(encode_op_noarg(POP))
            jmp2_pos = buf.pos()
            buf.emit(encode_op_s32(JUMP, 0))
            buf.add_patch(jmp2_pos + 1, label_end, 4)
            buf.patch_label(label_else, buf.pos())
            if node.else_expr:
                # 语句上下文（`_in_stmt_ctx=True`）且 else 为常量 `nil`/`T`
                # （platform-api `(if (boundp '@::wget) ... nil)` 语句）：
                # else 分支值被 POP 丢弃，push+pop 是纯 no-op——CAD 省略
                # （实测 `JUMP 0; PUSH_VALUE <return>` 无 `01 0a`）。值上下文
                # （分支值被使用）不省略。
                _else_const = (
                    isinstance(node.else_expr, Symbol)
                    and node.else_expr.name.lower() in ("nil", "t")
                )
                # else 常量省略仅当 then 分支被 POP 丢弃（普通表达式）；then 为
                # 立即 lambda（值保留，EVAL 结果流到 if 假路径）时不省略——CAD
                # user-manager `(if token-callback ((lambda ...) ...) nil)` 实测
                # `EVAL; JUMP(1); 01(nil); CLEAR_ARGS(1)`（then 立即 lambda 无 POP）。
                if not (self._in_stmt_ctx and _else_const and not _then_imm):
                    self._emit_expr(buf, node.else_expr, _tail=self._in_tail_context)
                    if (
                        self._in_stmt_ctx
                        and not _else_const
                        and not isinstance(
                            node.else_expr, (Setq, IfNode, Progn, WhileNode, ForeachNode, RepeatNode, Cond, Defun)
                        )
                    ):
                        # 语句上下文（中间 if，值被丢弃）：else 分支末尾同样 POP 丢弃
                        # 分支值（large_synthetic lgf-000..119 实测 CAD else 分支
                        # `USUBR; POP`）。与 then 分支对称；else 为 setq 时 SETQ_G
                        # 已消费栈顶无需 POP，progn/if/循环由其自身管理栈。else 为
                        # 常量 nil/T 时值留栈由 CLEAR_ARGS 清理（CAD 无 `01 0a`）。
                        buf.emit(encode_op_noarg(POP))
            elif self._in_tail_context or not self._in_stmt_ctx:
                # CAD stub：尾上下文 / 值位置无 else 分支时在 else 标签处补隐式
                # PUSH_NIL（cond 为假时返回 nil），then 分支的 JUMP 跳过它
                # （t9 / base-function 值位置 setq RHS 实测）。中间 if（函数体
                # 或模块代码中间的语句）不补：假路径直接跳下一语句，后续语句
                # 的 POP 丢弃栈顶（i18n-cad update-locale / test-cond CAD 实测）。
                buf.emit(encode_op_noarg(PUSH_NIL))
            buf.patch_label(label_end, buf.pos())
            if _saved_let_tail:
                # let body 尾 if 的 end（then JUMP 目标 + else fall-through 统一）：
                # CAD 发射 `USUBR(<argc>, LET)`（minlet/let3/let4 CAD 真机实测操作数
                # = fg LET 槽 - 1：event-bus 21、let3 1；CAD then JUMP 也执行）。
                # argc = let body form 数 + 1（nlp.lsp cmd-ai-fallback 4 form →
                # `USUBR(5, LET)`；event-bus 1 form → `USUBR(2, LET)`），由
                # `_emit_let` 通过 `_in_let_tail` 传入。`_patch_usubr_idx` 映射
                # 到 gvar 槽。event-bus CAD 实测 USUBR 后 `00 03`（NIL +
                # PUSH_VALUE[0]）清理占位。
                _let_idx = self.symtab.get_or_add("let")
                self._emit_usubr(buf, int(_saved_let_tail), _let_idx)
                self._emit_subr_cleanup(buf)
            self._in_let_tail = _saved_let_tail
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
        label_loop = self._ctl("while_loop", buf.pos())
        label_end = self._ctl("while_end", buf.pos())

        if self._in_tail_context and self.stub_format:
            # 尾 while（函数最后语句）：CAD 在 loop 头前压入 PUSH_NIL 占位、
            # 体开头 POP 弹掉（base-function @::sleep `(while ... (princ))`
            # 实测 `01 ... 0a`，同 foreach stub 的尾协议）。
            buf.emit(encode_op_noarg(PUSH_NIL))
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

        if self._in_tail_context and self.stub_format:
            buf.emit(encode_op_noarg(POP))
        _wbody = node.body
        if len(_wbody) > 1:
            _wbody = [
                x for i, x in enumerate(_wbody)
                if i == len(_wbody) - 1 or not isinstance(x, String)
            ]
        for i, form in enumerate(_wbody):
            last_in_body = i == len(_wbody) - 1
            if self.stub_format and last_in_body and self._in_tail_context:
                # 尾 while 的最后一个体语句是 while 的"值"（尾协议由 loop 头
                # PUSH_NIL 占位 + 体首 POP 处理）：尾上下文发射（setq 补 DUP
                # 保留值，net/headers @::set-headers-ext `(while ... (setq i ...))`
                # CAD 实测 `DUP SETQ_G`）。中间语句仍语句上下文（调用值 POP
                # 丢弃）。单语句体（base-function @::sleep `(princ)`）不受影响。
                self._emit_expr(buf, form, _tail=True)
                continue
            self._emit_stmt(buf, form)
            # CAD stub：中间 setq 无 POP（SETQ_G 自身消费栈顶）；尾 while
            # 体各语句不 POP（值留栈，loop 头 PUSH_NIL 占位由 CLEAR_ARGS/
            # 循环回跳处理，base-function @::sleep `(while ... (princ))`
            # 实测体末无 POP）；中间 while 体非 setq 语句（如 `(princ n)`）
            # 返回值被 POP 丢弃（t04_while 实测）。
            if self.stub_format:
                # foreach/repeat 自带 CLEAR_ARGS/栈平衡（func-analyze `(while
                # ... (foreach ...))` golden foreach 后直接 CLEAR_ARGS;回跳，
                # 无额外 0a——此前 tuple 缺 ForeachNode/RepeatNode 多 1 POP）。
                if isinstance(form, (Setq, WhileNode, IfNode, Cond, Progn, ForeachNode, RepeatNode)):
                    continue
                if self._in_tail_context and last_in_body:
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
        slot = self._get_local_slot(self._ctl("foreach_list", buf.pos()))
        item_slot = self._get_local_slot(self._ctl("foreach_item", buf.pos()))

        # 列表求值是 foreach 的输入（值上下文）：`_value_ctx` 清 `_in_stmt_ctx`，
        # 否则列表为 if 时（dcl @::dcl-run-with-setup `(foreach line (if ...
        # (list dcl-content)) ...)`）else 分支 `(list ...)` 被 `_emit_if` 的
        # 语句 POP 误丢（CAD 实测 `USUBR(1,list); SET_LOCAL` 无 POP）。
        with self._value_ctx():
            self._emit_expr(buf, node.list_expr or Symbol("nil"))
        buf.emit(encode_op_u16(SET_LOCAL_16, slot))

        label_loop = self._ctl("foreach_loop", buf.pos())
        label_end = self._ctl("foreach_end", buf.pos())

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
        if node.name == "vlax-for":
            self._emit_vlax_for_stub(buf, node)
            return
        var_name = node.var.name if isinstance(node.var, Symbol) else "item"
        slot = self._get_local_slot(f"__loop_list__{self._loop_depth}")
        v_idx = self.symtab.get_or_add(var_name)

        # 列表求值是 foreach 的输入（值上下文）：`_value_ctx` 清 `_in_stmt_ctx`，
        # 否则列表为 if 时（dcl @::dcl-run-with-setup `(foreach line (if ...
        # (list dcl-content)) ...)`）else 分支 `(list ...)` 被 `_emit_if` 的
        # 语句 POP 误丢（CAD 实测 `USUBR(1,list); SET_LOCAL` 无 POP）。
        with self._value_ctx():
            self._emit_expr(buf, node.list_expr or Symbol("nil"))
        buf.emit(encode_op_u16(SET_LOCAL_16, slot))
        # CAD 预载：PUSH_G <var>; PUSH_NIL; INIT_ARGS 3
        buf.emit(encode_op_u16(PUSH_G, v_idx))
        buf.emit(encode_op_noarg(PUSH_NIL))
        buf.emit(encode_op_u16(INIT_ARGS, 3))

        label_loop = self._ctl("foreach_stub_loop", buf.pos())
        label_end = self._ctl("foreach_stub_end", buf.pos())
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

        self._loop_depth += 1
        _fbody = node.body
        if len(_fbody) > 1:
            _fbody = [
                x for i, x in enumerate(_fbody)
                if i == len(_fbody) - 1 or not isinstance(x, String)
            ]
        for i, form in enumerate(_fbody):
            if self._in_tail_context and i == len(_fbody) - 1:
                # 尾 foreach 体**最后**语句 = foreach 的"值"（值上下文）：if 无
                # else 补 PUSH_NIL（cache.lsp 尾 foreach 体末 `(if (and ...)
                # (vl-file-delete ...))` CAD 实测 `JMP32_IFNOT; then; JUMP;
                # PUSH_NIL`）、调用不 POP。`_emit_stmt` 会清 `_in_tail_context`
                # 使 if 按语句上下文（无 else 不补 nil、then POP），故最后语句
                # 走 `_emit_expr`。
                self._emit_expr(buf, form)
            else:
                # 非尾 foreach 体语句值被丢弃 → 每句 POP；**尾 foreach 的中间
                # 语句同样 POP**（stat:print `(foreach n @:tmp-stat-result
                # (princ ...) (princ ...) ...)`、dim:multi-dim 尾 foreach 的
                # `(entity:dimaligned ...)` CAD golden 实测 `USUBR; POP`，仅末
                # 语句留值）。setq/if/循环自平衡无 POP。
                self._emit_stmt(buf, form)
                if not isinstance(
                    form,
                    (Setq, IfNode, WhileNode, ForeachNode, RepeatNode, Cond, Progn),
                ):
                    buf.emit(encode_op_noarg(POP))
        self._loop_depth -= 1

        jmp_back = buf.pos()
        buf.emit(encode_op_s32(JUMP, 0))
        buf.add_patch(jmp_back + 1, label_loop, 4)
        buf.label(label_end)
        # 预载参数清理（CAD 实测：foreach 结果不被 POP，而用 CLEAR_ARGS 1）
        buf.emit(encode_op_u16(CLEAR_ARGS, 1))

    def _emit_vlax_for_stub(self, buf: BytecodeBuffer, node: ForeachNode):
        """CAD stub 的 vlax-for ActiveX 集合枚举协议（kernel ui/menu.lsp
        cuix-find-or-create-group CAD golden 实测）：

        ``<coll> 求值 → FUNC 1 <collect-init>; NIL; PUSH_NIL; NIL → SET_LOCAL
        （iterator 状态存 slot）→ PUSH_G <var>; PUSH_NIL; INIT_ARGS 3（预载）→
        loop: GET_LOCAL; FUNC 1 <collect-next>; NIL; PUSH_NIL; NIL; DUP;
        SETQ_G <var>; JMP32_IFNOT end; body(无 POP); JUMP loop;
        end: GET_LOCAL; FUNC 1 <collect-release>; NIL; PUSH_NIL; NIL; POP;
        CLEAR_ARGS 1``

        collect-* 为跨函数共享单槽（小写，`_VLISP_CASE_PRESERVE`），cad_symbols
        按 `collect-init → var → collect-next → body → collect-release` 字节码引用
        序注册；codegen 用 `FUNC 1` 编码调用（同 `command`/`_al-bind-alist` 的
        `NIL; PUSH_NIL; NIL` 清理，非 USUBR 的 `00 03`）。
        """
        var_name = node.var.name if isinstance(node.var, Symbol) else "item"
        slot = self._get_local_slot(f"__loop_list__{self._loop_depth}")
        v_idx = self.symtab.get_or_add(var_name)

        # 集合求值是 vlax-for 的输入（值上下文，同 list foreach）
        with self._value_ctx():
            self._emit_expr(buf, node.list_expr or Symbol("nil"))
        # collect-init：结果（iterator 状态）存 slot
        idx_init = self.symtab.get_or_add("collect-init")
        self._emit_func3(buf, 1, idx_init)
        if not self.wide_subr:
            # 小文件 3 字节 FUNC：CAD 追加 `NIL; PUSH_NIL; NIL` 清理
            # （menu.lsp golden 实测）。大文件 6 字节 FUNC flags=1 已内联
            # 清理语义（CAD atlisp_u 实测 `FUNC; SET_LOCAL`，无 `NIL;
            # PUSH_NIL; NIL`）。
            buf.emit(encode_op_noarg(0x00))  # NIL
            buf.emit(encode_op_noarg(PUSH_NIL))
            buf.emit(encode_op_noarg(0x00))  # NIL
        buf.emit(encode_op_u16(SET_LOCAL_16, slot))
        # CAD 预载：PUSH_G <var>; PUSH_NIL; INIT_ARGS 3
        buf.emit(encode_op_u16(PUSH_G, v_idx))
        buf.emit(encode_op_noarg(PUSH_NIL))
        buf.emit(encode_op_u16(INIT_ARGS, 3))

        label_loop = self._ctl("vlax_for_stub_loop", buf.pos())
        label_end = self._ctl("vlax_for_stub_end", buf.pos())
        if self._in_tail_context:
            # 尾 vlax-for（kwote lambda 体末，make-menu-cuix）：同 list foreach
            # 的 PUSH_NIL 占位 + 体首 POP 协议。
            buf.emit(encode_op_noarg(PUSH_NIL))
        buf.label(label_loop)
        buf.emit(encode_op_u16(GET_LOCAL_16, slot))
        idx_next = self.symtab.get_or_add("collect-next")
        self._emit_func3(buf, 1, idx_next)
        if not self.wide_subr:
            # 小文件 3 字节 FUNC：CAD 追加 `NIL; PUSH_NIL; NIL` 清理
            # （menu.lsp golden 实测）。大文件 6 字节 FUNC flags=1 已内联
            # 清理语义（CAD atlisp_u 实测 `FUNC; DUP`，无 `NIL; PUSH_NIL;
            # NIL`）。
            buf.emit(encode_op_noarg(0x00))  # NIL
            buf.emit(encode_op_noarg(PUSH_NIL))
            buf.emit(encode_op_noarg(0x00))  # NIL
        buf.emit(encode_op_noarg(DUP))
        buf.emit(encode_op_u16(SETQ_G, v_idx))
        jmp_pos = buf.pos()
        buf.emit(encode_op_s32(JMP32_IFNOT, 0))
        buf.add_patch(jmp_pos + 1, label_end, 4)

        if self._in_tail_context:
            buf.emit(encode_op_noarg(POP))

        self._loop_depth += 1
        for i, form in enumerate(node.body):
            if self._in_tail_context and i == len(node.body) - 1:
                # 尾 vlax-for 体最后语句 = vlax-for 的"值"（值上下文）
                self._emit_expr(buf, form)
            else:
                self._emit_stmt(buf, form)
                if (
                    not self._in_tail_context
                    and not isinstance(
                        form,
                        (Setq, IfNode, WhileNode, ForeachNode, RepeatNode, Cond, Progn),
                    )
                ):
                    buf.emit(encode_op_noarg(POP))
        self._loop_depth -= 1

        jmp_back = buf.pos()
        buf.emit(encode_op_s32(JUMP, 0))
        buf.add_patch(jmp_back + 1, label_loop, 4)
        buf.label(label_end)
        # 尾部清理：collect-release 释放 iterator，POP 丢弃结果，CLEAR_ARGS 1
        idx_release = self.symtab.get_or_add("collect-release")
        buf.emit(encode_op_u16(GET_LOCAL_16, slot))
        self._emit_func3(buf, 1, idx_release)
        if not self.wide_subr:
            # 小文件 3 字节 FUNC：CAD 追加 `NIL; PUSH_NIL; NIL` 清理
            # （menu.lsp golden 实测）。大文件 6 字节 FUNC flags=1 已内联
            # 清理语义（CAD atlisp_u 实测 `FUNC; POP`，无 `NIL; PUSH_NIL;
            # NIL`）。
            buf.emit(encode_op_noarg(0x00))  # NIL
            buf.emit(encode_op_noarg(PUSH_NIL))
            buf.emit(encode_op_noarg(0x00))  # NIL
        buf.emit(encode_op_noarg(POP))
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
        # 参数是 or/and 的短路结果来源（值保留在栈上）：按**值位置尾上下文**
        # 编译——参数内 setq 补 DUP 保留值（putclosed `(or ... (setq obj ...))`
        # CAD 实测 `0b`），参数内 if 走值上下文（else-less 补 PUSH_NIL、then
        # 不 POP），同 if/while 条件、let 体各 form 的既有协议。
        if op_name == "and":
            label_end = self._ctl("and_end", buf.pos())
            for arg in args:
                with self._value_ctx():
                    self._emit_expr(buf, arg, _tail=True)
                jmp_pos = buf.pos()
                buf.emit(encode_op_s32(COND_AND, 0))
                buf.add_patch(jmp_pos + 1, label_end, 4)
            buf.emit(encode_op_noarg(PUSH_T))
            buf.label(label_end)
        else:  # or
            label_tail = self._ctl("or_tail", buf.pos())
            label_end = self._ctl("or_end", buf.pos())
            for arg in args:
                with self._value_ctx():
                    self._emit_expr(buf, arg, _tail=True)
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
        label_end = self._ctl("cond_end", buf.pos())
        label_next = None
        for i, clause in enumerate(node.clauses):
            if label_next:
                buf.label(label_next)
            if len(clause) == 0:
                continue
            cond = clause[0]
            actions = clause[1:]
            if len(actions) > 1:
                actions = [
                    x for i, x in enumerate(actions)
                    if i == len(actions) - 1 or not isinstance(x, String)
                ]  # type: ignore[assignment]
            if isinstance(cond, Symbol) and cond.name.lower() == "t":
                for action in actions:
                    self._emit_expr(buf, action)
                break

            self._emit_expr(buf, cond)
            if actions:
                jmp_pos = buf.pos()
                if i < len(node.clauses) - 1:
                    label_next = self._ctl(f"cond_next_{i}", buf.pos())
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
        base = self._ctl("cond", buf.pos())
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
                self._emit_push_value(buf, idx)
            else:
                # 测试值为 cond 的"值"（COND_OR 消费）：`_tail=True` 使测试内
                # 值位置 setq 补 DUP 保留返回值（update `(cond ((setq str-Response
                # (@::http-request ...)) ...) ...)` 实测 `USUBR; DUP; SETQ_G;
                # COND_OR`）。与 if 条件同规则（_emit_if line 755）。
                self._emit_expr(buf, cond, _tail=True)
            condor_pos = buf.pos()
            buf.emit(encode_op_s32(COND_OR, 0))
            buf.add_patch(condor_pos + 1, f"{base}_body_{i}", 4)
        # 全假默认值 + 跳转链：PUSH_NIL 后跳过首个发出体（=末子句体）。
        # CAD 对**末子句为 `(t ...)` else** 且 cond 在**语句上下文**（值被丢弃，
        # cl-macros @::macro-subst `(while form ... (cond ... (t ...)))` 实测
        # `COND_OR; JUMP` 无 `01`）时省略死代码 PUSH_NIL 默认值（t 恒真，
        # fall-through 不可达）；模块代码（platform 顶层 cond `(t ...)`）仍保留。
        # 语句上下文**无 else** 的 cond（voice C:@VOICE `(cond ((= choice "1")
        # ...) ((= choice "2") ...) ((= choice "3") ...))` CAD 实测同样无 `01`）
        # 也省略——cond 自平衡，值被丢弃，fall-through 的 PUSH_NIL 为纯 no-op。
        _last_test = clauses[-1][0]
        _omit_default = self._in_stmt_ctx
        if not _omit_default:
            buf.emit(encode_op_noarg(PUSH_NIL))
        jmp_pos = buf.pos()
        buf.emit(encode_op_s32(JUMP, 0))
        buf.add_patch(jmp_pos + 1, f"{base}_body_{n - 1}_end", 4)
        # 结果体按源码倒序发出：POP + 结果；除最后发出体（=首子句）外各加 JUMP，
        # 跳到下一个发出体之后（即其 JUMP 处），链式跳过其余体。
        for k, i in enumerate(reversed(range(n))):
            actions = clauses[i][1:]
            # CAD 丢弃 cond 子句体中语句位置的裸字符串（分节注释），仅末 form
            # （返回值位置）的字符串保留——与 `strip_docstring`（defun 体）同规则。
            # 收集端（cad_symbols Cond 分支）已同步跳过，codegen 必须一致否则
            # 符号槽错位（grread.lsp `(t "其它情况" (princ gr))` 实测）。
            if len(actions) > 1:
                actions = [
                    x for i, x in enumerate(actions)
                    if i == len(actions) - 1 or not isinstance(x, String)
                ]  # type: ignore[assignment]
            # 语句上下文（值被丢弃）：子句体末/中位置的字面 `nil`/`T` 是纯 no-op
            # （PUSH+POP），CAD 省略（dcl:set-mtext `(cond ((> i% rows) nil) ...)`
            # golden 子句体仅入口 `0a`，无 `01 0a`）。值上下文（cond 结果是该
            # 字面量，如 `(setq x (cond ((p) nil) ...))`）仍需发射。
            if self._in_stmt_ctx:
                actions = [
                    a for a in actions
                    if not (isinstance(a, Symbol) and a.name.lower() in ("nil", "t"))
                ]  # type: ignore[assignment]
            buf.label(f"{base}_body_{i}")
            # CAD stub：空体子句（`(cond (x) ...)`，无动作）不发入口 POP——
            # 测试值留在栈顶作为 cond 结果，COND_OR 真时直接落到该子句结束
            # 位置（init/sequence 空体子句 `(@::*bootstrap-state*)` CAD 实测
            # 无 `0a`，末子句空体后 CLEAR_ARGS 前也无 POP）。非空体才发
            # POP 弹掉测试值。**语句上下文**（值被丢弃）的空体子句仍发 POP
            # 丢弃测试值（system/which `(cond ((eq $platform 'linux)) (t
            # (if ...)))` CAD golden 空子句体 = `0a`，此前漏 POP → 跳距差 1）。
            if actions or self._in_stmt_ctx:
                buf.emit(encode_op_noarg(POP))
            for a in actions[:-1]:
                self._emit_stmt(buf, a)
                # 中间语句丢弃结果：if 自身管理栈（then 末尾已 POP / 无 else 补
                # PUSH_NIL）；setq 由 SETQ_G 消费栈顶；foreach stub 以
                # CLEAR_ARGS 1 平衡栈（hkrepro cond 分支1 实测 CAD 不额外
                # POP）；while/repeat 自带栈平衡（JUMP 回跳 + CLEAR_ARGS/尾
                # 协议，platform-api @::platform-http-head `(while ...)` 后
                # 接 if 实测 CAD 无额外 0a POP）；progn 自身管理。再加 body
                # 层 POP 会双 POP。其余（调用/print 等）发 POP 丢弃。
                if not isinstance(a, (IfNode, Setq, Progn, ForeachNode, WhileNode, RepeatNode, Cond)):
                    buf.emit(encode_op_noarg(POP))
            if actions:
                if self._in_stmt_ctx:
                    # 语句上下文（值被丢弃）：末动作按语句发射（setq 由 SETQ_G
                    # 消费栈顶、调用/print 等追加 POP 丢弃）——cond 自平衡，
                    # 外层不再 POP（cl-macros @::macro-subst while 体 cond 的
                    # t 子句 `(setq result ...)` 实测 `USUBR; SETQ_G` 无 `0a`）。
                    self._emit_stmt(buf, actions[-1])
                    if not isinstance(
                        actions[-1],
                        (IfNode, Setq, Progn, ForeachNode, WhileNode, RepeatNode, Cond),
                    ):
                        buf.emit(encode_op_noarg(POP))
                else:
                    # 值上下文（尾/模块代码/值位置 setq RHS）：末动作是子句的
                    # "值"（cond 结果），表达式发射使 setq 补 DUP 保留返回值
                    # （platform 顶层 cond `(setq is-gcad T)` 实测
                    # `PUSH_G T; DUP; SETQ_G`；`(setq x (cond ...))` 同理）。
                    self._emit_expr(buf, actions[-1], _tail=True)
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
        # repeat 次数是**值**（存局部槽由 FIX_LEQ 循环消费）：次数为 setq 时需
        # 值上下文使 setq 保留返回值（ss2enames `(repeat (setq n (sslength ss))
        # ...)` CAD golden `USUBR; DUP; SETQ_G; SET_LOCAL` 实测，此前 SETQ_G 消
        # 费后 SET_LOCAL 取空栈）。与 foreach list 同规则（`_value_ctx`）。
        with self._value_ctx():
            self._emit_expr(buf, count_expr)
        buf.emit(encode_op_u16(SET_LOCAL_16, slot))
        label_loop = self._ctl("repeat_loop", buf.pos())
        label_end = self._ctl("repeat_end", buf.pos())
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
        slot = self._get_local_slot(f"__loop_list__{self._loop_depth}")
        # repeat 次数是**值**（存局部槽由 FIX_LEQ 循环消费）：次数为 setq 时需
        # 值上下文使 setq 保留返回值（ss2enames `(repeat (setq n (sslength ss))
        # ...)` CAD golden `USUBR; DUP; SETQ_G; SET_LOCAL` 实测）。
        with self._value_ctx():
            self._emit_expr(buf, count_expr)
        buf.emit(encode_op_u16(SET_LOCAL_16, slot))

        if self._in_tail_context and self.stub_format:
            # 尾 repeat（函数最后语句的 repeat，anti-crack `(if (and ...)
            # (repeat 10 ...))` 实测）：同尾 while，loop 头前 PUSH_NIL 占位、
            # JMP32_IFNOT 后 POP 弹掉。
            buf.emit(encode_op_noarg(PUSH_NIL))
        label_loop = self._ctl("repeat_stub_loop", buf.pos())
        label_end = self._ctl("repeat_stub_end", buf.pos())
        buf.label(label_loop)
        buf.emit(encode_op_u16(GET_LOCAL_16, slot))
        buf.emit(encode_op_u8(PUSH_INT8, 0))
        buf.emit(encode_op_noarg(FIX_LEQ))
        jmp_pos = buf.pos()
        buf.emit(encode_op_s32(JMP32_IFNOT, 0))
        buf.add_patch(jmp_pos + 1, label_end, 4)
        if self._in_tail_context and self.stub_format:
            buf.emit(encode_op_noarg(POP))

        buf.emit(encode_op_u16(GET_LOCAL_16, slot))
        buf.emit(encode_op_noarg(DEC))
        buf.emit(encode_op_u16(SET_LOCAL_16, slot))

        self._loop_depth += 1
        if len(body) > 1:
            body = [
                x for i, x in enumerate(body)
                if i == len(body) - 1 or not isinstance(x, String)
            ]
        for i, form in enumerate(body):
            _last = i == len(body) - 1
            if self._in_tail_context and _last:
                # 尾 repeat 的最后体语句是 repeat 的"值"（同尾 while/foreach 的
                # 尾协议）：尾上下文发射（setq 补 DUP 保留值，dialog save-config
                # `(repeat ... (setq i (1+ i)))` CAD 实测 `DUP SETQ_G`）。中间
                # 语句仍语句上下文（调用值 POP 丢弃）。
                self._emit_expr(buf, form, _tail=True)
            else:
                self._emit_stmt(buf, form)
            # CAD stub：体语句值被 POP 丢弃。尾 repeat（函数最后语句，值保留）
            # 最后语句不 POP（t17 实测 `USUBR; PUSH_VALUE`）；非尾 repeat（值被
            # 外层丢弃）所有语句 POP（panel-dcl-column repeat 体 write-line 后
            # `USUBR; POP` golden 实测）。setq 已消费栈顶、if/循环自平衡不 POP。
            if _last and self._in_tail_context:
                continue
            if not isinstance(
                form, (Setq, WhileNode, IfNode, Cond, ForeachNode, RepeatNode, Progn)
            ):
                buf.emit(encode_op_noarg(POP))
        self._loop_depth -= 1

        jmp_back = buf.pos()
        buf.emit(encode_op_s32(JUMP, 0))
        buf.add_patch(jmp_back + 1, label_loop, 4)
        buf.label(label_end)

    def _emit_quoted(self, buf: BytecodeBuffer, node: Optional[Node], skip_reg: Optional[Set] = None):
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
                _nm = normalize_vla_name(name)
                if name in skip_reg:
                    idx = self.symtab.name_to_idx.get(self.symtab._normalize_name(_nm), 0xFFFF)
                elif (
                    self.stub_format
                    and not self._module_mode
                    and name == self.current_func_name
                ):
                    # 引用自身（`'xdata:delete`）：CAD 用重复符号槽（同递归调用），
                    # 不并入函数自身首槽。repeat 槽已由收集器注册（derive_symbol_names
                    # 把 quoted self-ref 当普通符号二次 yield → 收集循环 add_force），
                    # next_repeat_slot 命中；未注册时退回 get_or_add（不新增槽，保 nsyms）。
                    # 不查 _module_code_ctx：该标志模块代码后置位不清除（seg0 亦为 True），
                    # 用 _module_mode（seg0 为 False）+ current_func_name（模块代码为 ''）界定。
                    rep = self.symtab.next_repeat_slot(_nm)
                    idx = rep if rep >= 0 else self.symtab.get_or_add(_nm)
                else:
                    idx = self.symtab.get_or_add(_nm)
                buf.emit(encode_op_u16(PUSH_G, idx))
        elif isinstance(node, Integer):
            val = node.value
            if _INT32_MIN <= val <= _INT32_MAX:
                if -128 <= val <= 127:
                    buf.emit(encode_op_u8(PUSH_INT8, val & 0xFF))
                else:
                    buf.emit(struct.pack("<Bi", PUSH_INT32, val))
            else:
                buf.emit(encode_real(float(val)))
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
        elif isinstance(node, IfNode):
            items = [Symbol("if"), node.cond or Symbol("nil"), node.then or Symbol("nil")]
            if node.else_expr is not None:
                items = items + [node.else_expr]
            for item in reversed(items):
                self._emit_quoted(buf, item, skip_reg)
            buf.emit(encode_op_u16(BUILD_LIST, len(items)))
        elif isinstance(node, Progn):
            items = [Symbol("progn")] + node.forms
            for item in reversed(items):
                self._emit_quoted(buf, item, skip_reg)
            buf.emit(encode_op_u16(BUILD_LIST, len(items)))
        elif isinstance(node, Cond):
            items = [Symbol("cond")] + [ListExpr(items=list(c)) for c in node.clauses]
            for item in reversed(items):
                self._emit_quoted(buf, item, skip_reg)
            buf.emit(encode_op_u16(BUILD_LIST, len(items)))
        elif isinstance(node, Setq):
            items = [Symbol("setq")]
            for t, v in node.pairs:
                items.append(t)
                items.append(v if v is not None else Symbol("nil"))
            for item in reversed(items):
                self._emit_quoted(buf, item, skip_reg)
            buf.emit(encode_op_u16(BUILD_LIST, len(items)))
        elif isinstance(node, WhileNode):
            items = [Symbol("while"), node.cond or Symbol("nil")] + node.body
            for item in reversed(items):
                self._emit_quoted(buf, item, skip_reg)
            buf.emit(encode_op_u16(BUILD_LIST, len(items)))
        elif isinstance(node, ForeachNode):
            items = [Symbol(node.name or "foreach"), node.var or Symbol("nil"), node.list_expr or Symbol("nil")] + node.body
            for item in reversed(items):
                self._emit_quoted(buf, item, skip_reg)
            buf.emit(encode_op_u16(BUILD_LIST, len(items)))
        elif isinstance(node, RepeatNode):
            items = [Symbol("repeat"), node.count or Integer(0)] + node.body
            for item in reversed(items):
                self._emit_quoted(buf, item, skip_reg)
            buf.emit(encode_op_u16(BUILD_LIST, len(items)))
        elif isinstance(node, Defun):
            # 引用数据里的 `(defun name (args) body...)`：还原为数据列表
            arg_items: List[Node] = [Symbol(a) for a in node.args]
            if node.optional:
                arg_items += [Symbol("&optional")] + [Symbol(a) for a in node.optional]
            if node.rest:
                arg_items += [Symbol("&rest"), Symbol(node.rest)]
            if node.locals:
                arg_items += [Symbol("/")] + [Symbol(l) for l in node.locals]
            items = [Symbol("defun"), Symbol(node.name), ListExpr(items=arg_items)] + node.body
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
        if self._module_mode:
            # 顶层 kwote lambda 调用实参（setup `(if @::*uris* (mapcar
            # (function (lambda (x) ...)) ...))`）：CAD 模块代码
            # `JUMP 0; PUSH_G <funcobj>; FUNC 1, kwote`（func-obj 由
            # `_offset_slots` 按 `-lambda-` 占位编址为 DEFCODE 区注册槽）。
            # 不 get_or_add `-lambda-`（否则多一个额外 symtab 条目 → nsyms
            # +1、lam_order 偏移、seg0 `-lambda-` 槽错位）。纯顶层 setq-lambda
            # 绑定（net/wget）不经此处（`_stmt_bytes` top_lambda_slots 特判）。
            lam_idx = self.symtab.name_to_idx.get("-lambda-", 0)
            buf.emit(encode_op_s32(JUMP, 0))
            buf.emit(encode_op_u16(PUSH_G, lam_idx))
            kwote_idx = self.symtab.get_or_add("kwote")
            # 模块代码 FUNC 恒用 6 字节宽格式（CAD setup 实测 `51 01 08 00
            # 01 00`，与 nsyms 无关）。
            buf.emit(encode_func(1, kwote_idx, flags=1))
            return
        lam_idx = self._emit_nested_lambda(buf, node)
        kwote_idx = self.symtab.get_or_add("kwote")
        buf.emit(encode_op_u16(PUSH_G, lam_idx))
        self._emit_func3(buf, 1, kwote_idx)
        # non-wide（3 字节 FUNC）：kwote 调用后 `00 01 00` 清理（i18n CAD
        # 实测）。wide（5/6 字节 FUNC flags=1）已内联清理，不再补 `00 01 00`
        # （panel.lsp kwote lambda 注册 golden 实测 `FUNC[1,203,1,0]` 后直接
        # 下一指令）。
        if not self.wide_subr:
            buf.emit(encode_op_noarg(0x00))
            buf.emit(encode_op_noarg(PUSH_NIL))
            buf.emit(encode_op_noarg(0x00))

    def _emit_nested_lambda(self, buf: BytecodeBuffer, node: LambdaNode) -> int:
        """发射内嵌 `-lambda-` DEFUN（CAD kwote/立即调用共用）。

        返回 `-lambda-` 符号槽（PUSH_G 引用用）。发射序列：
        ``JUMP label; 14 <argc><argc><argc> 00; 体...; CLEAR_ARGS; 16; label:``。
        内嵌 DEFUN 由模块加载器预定义（运行时不执行）。
        """
        args = list(node.args)
        locals_ = []
        if "/" in args:
            _i = args.index("/")
            locals_ = args[_i + 1 :]
            args = args[:_i]
        argc = len(args)
        # 每个内嵌 `-lambda-` 独立符号槽（CAD 实测：t3 槽 18、t4 槽 17、
        # t5 槽 16，nsyms=19，各自独立 DEFCODE 登记）。首个用 get_or_add
        # （保持单 kwote 文件 i18n/t20 的槽位与 golden 逐字节一致），
        # 后续用 add_force 追加重复槽。
        if "-lambda-" in self.symtab.name_to_idx:
            lam_idx = self.symtab.add_force("-lambda-")
        else:
            lam_idx = self.symtab.get_or_add("-lambda-")
        label_after = f"_lambda_{buf.pos()}_{len(self._nested_lambdas)}"
        jmp_pos = buf.pos()
        buf.emit(encode_op_s32(JUMP, 0))
        buf.add_patch(jmp_pos + 1, label_after, 4)
        nested_start = buf.pos()
        # b1 = argc + 直接体并发循环深度（含 foreach/repeat，audit-query
        # 立即 lambda `(foreach e ...)` 实测 `14 04 03 03 00`，与 generate_function
        # line 1523 同规则）；b2/b3 = argc。
        _b1 = argc + _direct_loop_depth(node.body)
        buf.emit(bytes([0x14, _b1 & 0xFF, argc & 0xFF, argc & 0xFF, 0]))
        saved_args = self.current_func_args
        saved_name = self.current_func_name
        saved_slots = self.local_slots
        saved_next = self.next_slot
        saved_loop = self._loop_depth
        saved_nl = self._in_nested_lambda
        self.current_func_name = "-lambda-"
        self._in_nested_lambda = True
        # lambda 参数注册为符号槽，读取用 PUSH_VALUE（CAD 实测：i18n 的
        # `opt%`、06_higher_order 的 `n` 均注册 fg 槽 + PUSH_VALUE 引用，
        # 由 `_patch_usubr_idx` 按 gvar_slot(arg)-1 重映射）。
        self.local_slots = {a: i for i, a in enumerate(args)}
        # 参数占局部槽 0..argc-1；foreach/repeat 列表槽从 argc 起分配
        # （audit-query 立即 lambda `(foreach e ...)` SET_LOCAL 3 = argc）。
        # 嵌套 lambda 是独立函数作用域：`_loop_depth` 归零（与 generate_function
        # line 229 一致）。
        self.next_slot = len(args)
        self._loop_depth = 0
        self._emit_init_args(buf, args, nested=True)
        if locals_:
            # `/ 局部变量` 与 defun 同协议：`_al-bind-alist` 绑定（CAD
            # atlisp_u C:@F kwote lambda 实测 `PUSH_G <const>; FUNC;
            # POP`）。局部变量读取/写入经符号槽（PUSH_VALUE/SETQ_G），
            # 不占局部槽。
            self._emit_al_bind_alist_locals(buf, locals_)
        body = node.body
        if len(body) > 1:
            body = [
                x for i, x in enumerate(body)
                if i == len(body) - 1 or not isinstance(x, String)
            ]
        for expr in body[:-1]:
            self._emit_stmt(buf, expr)
            if not isinstance(expr, (Setq, WhileNode, ForeachNode, RepeatNode, IfNode, Cond, Defun, Progn)):
                buf.emit(encode_op_noarg(POP))
        if body:
            self._emit_expr(buf, body[-1], _tail=True)
        else:
            buf.emit(encode_op_noarg(PUSH_NIL))
        # CAD stub：无参 `-lambda-`（argc=0、无 `/ locals`）直接 END_DEFUN，
        # 不发射 CLEAR_ARGS 0（与顶层 0 参 defun 同规则；platform-api
        # @::platform-http-winhttp 内嵌 0 参 lambda CAD 实测 `16` 收尾）。
        if argc + len(locals_):
            buf.emit(encode_op_u16(CLEAR_ARGS, argc + len(locals_)))
        buf.emit(encode_op_noarg(0x16))
        nested_end = buf.pos()
        self.local_slots = saved_slots
        self.next_slot = saved_next
        self._loop_depth = saved_loop
        self.current_func_args = saved_args
        self.current_func_name = saved_name
        self._in_nested_lambda = saved_nl
        buf.label(label_after)
        if not self._module_mode:
            # 模块代码（seg1 顶层）里的 kwote 内嵌 `-lambda-` 不进 seg0 函数目录：
            # `_nested_lambdas` 的偏移相对模块缓冲区，若混入会污染后续
            # generate_function 的 catalog 偏移（atlisp_u 顶层 `(function
            # (lambda ...))` 实测 89237 > seg0，触发 "Xsubr 偏移超出模块"）。
            self._nested_lambdas.append((nested_start, nested_end, args, lam_idx))
        return lam_idx

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
                # CAD 对含 foreach/repeat 的函数 b1 加 1（t16/t17 实测
                # `14 02 01 01 00`）；直接体并发循环深度（嵌套 2 层 → +2，
                # add-menus/remove-pkg-menu/cache-clear-all 实测 `14 03 01 01 00`）；
                # 嵌套 lambda/defun 内的循环不加（@lisp_u error-handler/
                # screensize 实测）。
                b1 = argc + _direct_loop_depth(func.body)
                buf.emit(bytes([0x14, b1 & 0xFF, argc & 0xFF, argc & 0xFF, 0]))
            return
        idx = self.symtab.idx_of(func.name) or self.symtab.get_or_add(normalize_vla_name(func.name))
        buf.emit(encode_defun(idx, 0))

    def _emit_init_args(self, buf: BytecodeBuffer, args: List[str], nested: bool = False):
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
                if self._nested_defun_depth or nested:
                    # 嵌套 defun / lambda 参数槽 = 真实符号槽（收集器分配，非顶部槽
                    # 公式）。lambda 体读取（PUSH_VALUE）本就用 get_or_add 槽，绑定须
                    # 与其一致（mode.lsp e1/e2 实测绑定槽须为真实符号槽）。
                    idx = self.symtab.get_or_add(arg)
                else:
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
        self._emit_al_bind_alist_locals(buf, func.locals)

    def _emit_al_bind_alist_locals(self, buf: BytecodeBuffer, locals_list: List[str]):
        const = ("LIST", tuple(("SYMBOL", l) for l in locals_list))
        al_idx = self.symtab.get_or_add("_al-bind-alist")
        const_idx = self.symtab.add_constant(const)
        if self.stub_format:
            buf.emit(encode_op_u16(PUSH_G, const_idx))
            self._emit_func3(buf, 1, al_idx)
            if not self.wide_subr:
                # 小文件 3 字节 FUNC：CAD 追加 `NIL; PUSH_NIL; NIL` 清理
                # （t11_localvars golden 实测）。大文件 6 字节 FUNC flags=1
                # 已内联清理语义（CAD atlisp_u 实测 `FUNC; POP`，无
                # `NIL; PUSH_NIL; NIL`，同 `_emit_subr_cleanup` 的 wide 逻辑）。
                buf.emit(encode_op_noarg(0x00))  # NIL
                buf.emit(encode_op_noarg(PUSH_NIL))  # PUSH_NIL
                buf.emit(encode_op_noarg(0x00))  # NIL
            buf.emit(encode_op_noarg(POP))  # POP
        else:
            buf.emit(encode_op_u16(PUSH_G, const_idx))
            buf.emit(encode_func(1, al_idx))
            buf.emit(encode_op_noarg(POP))

    def _emit_nested_defun(self, buf: BytecodeBuffer, node: Defun):
        """发射函数体内嵌套 `(defun inner ...)`（CAD 原生内嵌 DEFUN）。

        CAD n1-n6 实测布局（seg0）：
        ``DEFUN outer; JUMP <skip>; DEFUN inner; <体>; CLEAR_ARGS; END_DEFUN;
        <skip>: PUSH_G <inner-func-obj>; SETQ_G <inner-sym>``
        ——内嵌 DEFUN 出现在外层函数体语句位置，JUMP 跳过（运行时由模块加载器
        预定义，不执行）；随后 PUSH_G/SETQ_G 把符号绑定到函数对象（与模块代码
        函数注册同协议）。嵌套函数也进函数目录（DEFCODE），故记录偏移供
        cli.py 的 func_offsets 登记。
        """
        # 嵌套函数是独立函数作用域：保存并重置 codegen 状态（同 generate_function）。
        saved_name = self.current_func_name
        saved_args = self.current_func_args
        saved_slots = self.local_slots
        saved_next = self.next_slot
        saved_loop = self._loop_depth
        saved_tail = self._tail_entry_label
        saved_stmt = self._in_stmt_ctx
        saved_in_tail = self._in_tail_context

        self.current_func_name = node.name
        all_args = node.args + node.optional + ([node.rest] if node.rest else [])
        self.current_func_args = all_args
        self.local_slots = {}
        self.next_slot = 0
        self._loop_depth = 0
        self._tail_entry_label = f"_tail_entry_{node.name}_{id(node)}"
        # 嵌套函数体是独立求值作用域：体末 form 是函数返回值（值上下文），
        # 不受外层语句上下文（`_emit_stmt` 置 `_in_stmt_ctx`）影响——否则 s2la
        # 尾 `(if ...)` 的 then/else 分支值被误 POP（string-utils CAD 无
        # `0a`），seg0 +2。
        self._in_stmt_ctx = False
        self._in_tail_context = False
        # 嵌套 defun 参数按真实符号槽绑定/读取（Y@6），不走单函数
        # `nsyms-argc+i` 顶部槽公式（外层参数 X 才在顶部）。
        saved_nd_depth = self._nested_defun_depth
        self._nested_defun_depth += 1
        # 嵌套函数名兼作外层 `/ 局部`（影子，string-utils `(defun s2la ...)`
        # 在外层 `/ s2la` 内）：CAD 为递归独立注册符号槽（递归不并入名字槽）。
        saved_nd_shadow = self._nested_shadowing
        self._nested_shadowing = node.name in saved_slots

        label_after = f"_ndef_{buf.pos()}_{len(self._nested_lambdas)}"
        jmp_pos = buf.pos()
        buf.emit(encode_op_s32(JUMP, 0))
        buf.add_patch(jmp_pos + 1, label_after, 4)
        nested_start = buf.pos()

        self._emit_defun_header(buf, node)
        for i, arg in enumerate(all_args):
            self.local_slots[arg] = i
        self.next_slot = max(self.next_slot, len(all_args))
        self._emit_init_args(buf, all_args)
        if self.stub_format and node.locals:
            self._emit_al_bind_alist(buf, node)
        from compiler.cad_symbols import strip_docstring
        body = strip_docstring(node.body)
        for expr in body[:-1]:
            self._emit_stmt(buf, expr)
            if not self.stub_format or isinstance(expr, (Setq, WhileNode, ForeachNode, RepeatNode, Cond, Defun, Progn)):
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
            if node.args or node.locals:
                buf.emit(encode_op_u16(CLEAR_ARGS, len(node.args) + len(node.locals)))
        else:
            self._emit_clear_args(buf, node.args)
        # 嵌套函数以 END_DEFUN 收尾（非末位函数，CAD n1 实测 `16`）。
        buf.emit(encode_op_noarg(0x16))
        nested_end = buf.pos()
        buf.label(label_after)

        self.current_func_name = saved_name
        self.current_func_args = saved_args
        self.local_slots = saved_slots
        self.next_slot = saved_next
        self._loop_depth = saved_loop
        self._tail_entry_label = saved_tail
        self._nested_defun_depth = saved_nd_depth
        self._nested_shadowing = saved_nd_shadow
        self._in_stmt_ctx = saved_stmt
        self._in_tail_context = saved_in_tail

        # 记录嵌套函数（偏移范围 + 名字 + 参数 + 槽占位），cli.py 据此登记
        # func_offsets。sym_idx/fo_idx 供 `_patch_usubr_idx` 重映射 PUSH_G。
        sym_idx = self.symtab.get_or_add(node.name)
        fo_idx = self.symtab.add_funcobj(node.name)
        self._nested_defuns.append((nested_start, nested_end, node.name, all_args, sym_idx, fo_idx))

        # 注册：PUSH_G <inner-func-obj>; SETQ_G <inner-sym>（CAD n1 实测
        # `09 02 00; 06 01 00`）。函数对象槽 = 函数名第二次注册（DEFCODE）。
        buf.emit(encode_op_u16(PUSH_G, fo_idx))
        buf.emit(encode_op_u16(SETQ_G, sym_idx))
        # 嵌套 defun 是函数**返回值**（尾上下文，compat `(defun @::compat1
        # ... )` 内嵌 load-custom 为末语句）时，CAD 再推一次 `PUSH_G <inner-sym>`
        # （绑定后的函数对象作返回值；compat golden 实测 `09 46 00 06 01 00
        # 09 01 00 19 01 00`）。非尾（语句）位置无此推——n1-n6 均非尾。
        if self._in_tail_context:
            buf.emit(encode_op_u16(PUSH_G, sym_idx))

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
        saved_nd_pos = len(self._nested_defuns)
        saved_slots = self.local_slots
        saved_next = self.next_slot
        # 每个函数独立分配局部槽：foreach/repeat 的内部槽（__foreach_list__ 等）
        # 从 0 开始（i18n-cad update-locale-all foreach 槽 0 实测）；next_slot
        # 与 local_slots 不得跨函数累积。
        self.local_slots = {}
        self.next_slot = 0
        self._loop_depth = 0

        self.current_func_name = func.name
        all_args = func.args + func.optional + ([func.rest] if func.rest else [])
        self.current_func_args = all_args
        # 外层函数名栈（generate_function 压入，恢复时弹出）：嵌套 lambda/defun
        # 体内调用**宿主**函数是递归（CAD 用递归重复槽）。嵌套 lambda 的
        # current_func_name 是 `-lambda-`，直接自我比较不会命中（insertpopmenuitems
        # kwote 回调 `(std:insertpopmenuitems tmp subitems)` CAD golden 用重复槽）。
        self._ancestor_funcs.append(func.name)
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

        # CAD 丢弃 defun 体中语句位置的裸字符串（docstring/分节注释，见
        # cad_symbols.strip_docstring 的 CAD 实测）：仅体末 form（返回值）
        # 的字符串保留，不影响 `(strcat "a" "b")` 等表达式内字符串。
        from compiler.cad_symbols import strip_docstring
        body = strip_docstring(func.body)

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
            if not self.stub_format or isinstance(expr, (Setq, WhileNode, ForeachNode, RepeatNode, Cond, Defun, Progn)):
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
        if self._ancestor_funcs:
            self._ancestor_funcs.pop()

        self._func_nested_lambdas[func.name] = [n for n in self._nested_lambdas if saved_nl_pos <= n[0]]
        del self._nested_lambdas[saved_nl_pos:]

        self._func_nested_defuns[func.name] = [n for n in self._nested_defuns if saved_nd_pos <= n[0]]
        del self._nested_defuns[saved_nd_pos:]
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
        # `(defun-q name ...)`：CAD 编译为 kwote `(setq name (function (lambda
        # ...)))`（setup 实测 fg FUNCTION 符号，非 QUOTE 数据）——`-lambda-`
        # DEFUN + PUSH_G 绑定，与 `(setq *error* (lambda ...))` 裸 lambda 同路径。
        quoted = QuotedExpr(expr=lambda_call, kwote=True)

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
