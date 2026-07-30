import struct
from typing import List, Optional, Dict, Any, Set, Tuple
from compiler.ast import (
    Node, Program, Symbol, Integer, Real, String,
    ListExpr, QuotedExpr, Defun, Setq, IfNode, WhileNode,
    ForeachNode, Call, Progn, LambdaNode, Cond,
)
from compiler.opcodes import (
    NAME_TO_OPCODE,
    encode_op_noarg, encode_op_u16,
    encode_op_s32, encode_usubr, encode_func, encode_defun,
    encode_real,
)
from compiler.symbol_table import SymbolTable


PUSH_T = NAME_TO_OPCODE['PUSH_T']          # 0x02
PUSH_NIL = NAME_TO_OPCODE['PUSH_NIL']      # 0x01
PUSH_VALUE = NAME_TO_OPCODE['PUSH_VALUE']  # 0x03
PUSH_INT8 = NAME_TO_OPCODE['PUSH_INT8']    # 0x32
PUSH_INT32 = NAME_TO_OPCODE['PUSH_INT32']  # 0x33
PUSH_G = NAME_TO_OPCODE['PUSH_G']          # 0x09
POP = NAME_TO_OPCODE['POP']                # 0x0a
SETQ_G = NAME_TO_OPCODE['SETQ_G']          # 0x06
JMP16_IFNOT = NAME_TO_OPCODE['JMP16_IFNOT']  # 0x0d
JMP16_IF = NAME_TO_OPCODE['JMP16_IF']       # 0x0e
JUMP = NAME_TO_OPCODE['JUMP']               # 0x57
BUILD_LIST = NAME_TO_OPCODE['BUILD_LIST']   # 0x39
CAR = NAME_TO_OPCODE['CAR']                 # 0x28
CDR = NAME_TO_OPCODE['CDR']                 # 0x29
INIT_ARGS = NAME_TO_OPCODE['INIT_ARGS']     # 0x18
CLEAR_ARGS = NAME_TO_OPCODE['CLEAR_ARGS']   # 0x19
END_DEFUN = NAME_TO_OPCODE['END_DEFUN']     # 0x16
INC = NAME_TO_OPCODE['INC']                 # 0x4f
FIX_SUB = NAME_TO_OPCODE['FIX_SUB']         # 0x47
FIX_DIV = NAME_TO_OPCODE['FIX_DIV']         # 0x49
GET_LOCAL_8 = 0x05      # GET_LOCAL with 1-byte operand index
GET_LOCAL_16 = 0x5c     # GET_LOCAL with 2-byte operand index
SET_LOCAL_16 = 0x5d     # SET_LOCAL with 2-byte operand index


ARITH_OP_TO_FAS = {
    '+': 'FIX_ADD', '-': 'FIX_SUB', '*': 'FIX_MUL', '/': 'FIX_DIV',
    'rem': 'FIX_MOD', '<=': 'FIX_LEQ', '>=': 'FIX_GEQ',
    '<': 'FIX_LT', '>': 'FIX_GT',
}

UNARY_OP_TO_FAS = {
    '1+': 'INC', '1-': 'DEC', 'not': 'NOT', 'atom': 'ATOM',
    'car': 'CAR', 'cdr': 'CDR',
}

LOCAL_SLOT_MAP: Dict[str, int] = {}
NEXT_LOCAL_SLOT = 0


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
                raise ValueError(f'Unresolved label: {label}')
            rel_offset = target - (pos + op_size)
            self.data[pos:pos + op_size] = struct.pack('<i', rel_offset)[:op_size]

    def size(self) -> int:
        return len(self.data)


class CodeGenerator:
    def __init__(self, symtab: SymbolTable):
        self.symtab = symtab
        self.local_slots: Dict[str, int] = {}
        self.next_slot = 0
        self.func_offset_map: Dict[str, int] = {}
        self.stub_offsets: List[int] = []

    def _get_local_slot(self, name: str) -> int:
        if name not in self.local_slots:
            self.local_slots[name] = self.next_slot
            self.next_slot += 1
        return self.local_slots[name]

    def _emit_call(self, buf: BytecodeBuffer, name: str,
                   argc: int, sym_idx: int, is_builtin: bool = False):
        if is_builtin:
            buf.emit(encode_func(argc, sym_idx))
        else:
            buf.emit(encode_usubr(argc, sym_idx))

    def _emit_arith(self, buf: BytecodeBuffer, op_name: str, args: List[Node]):
        fas_op = ARITH_OP_TO_FAS.get(op_name)
        if fas_op:
            if len(args) == 1:
                if op_name == '-':
                    self._emit_expr(buf, Integer(0))
                    self._emit_expr(buf, args[0])
                    buf.emit(encode_op_noarg(FIX_SUB))
                elif op_name == '/':
                    self._emit_expr(buf, Integer(1))
                    self._emit_expr(buf, args[0])
                    buf.emit(encode_op_noarg(FIX_DIV))
                else:
                    self._emit_expr(buf, Integer(0))
                    self._emit_expr(buf, args[0])
                    buf.emit(encode_op_noarg(NAME_TO_OPCODE[fas_op]))
                return
            for arg in args:
                self._emit_expr(buf, arg)
            for _ in range(len(args) - 1):
                buf.emit(encode_op_noarg(NAME_TO_OPCODE[fas_op]))
        else:
            idx = self.symtab.get_or_add(op_name)
            for arg in reversed(args):
                self._emit_expr(buf, arg)
            buf.emit(encode_usubr(len(args), idx))

    def _emit_unary(self, buf: BytecodeBuffer, op_name: str, arg: Node):
        fas_op = UNARY_OP_TO_FAS.get(op_name)
        if fas_op:
            self._emit_expr(buf, arg)
            buf.emit(encode_op_noarg(NAME_TO_OPCODE[fas_op]))
        else:
            idx = self.symtab.get_or_add(op_name)
            self._emit_expr(buf, arg)
            buf.emit(encode_usubr(1, idx))

    def _emit_expr(self, buf: BytecodeBuffer, node: Node):
        if isinstance(node, Symbol):
            name = node.name
            if name == 'T':
                buf.emit(encode_op_noarg(PUSH_T))
            elif name == 'nil':
                buf.emit(encode_op_noarg(PUSH_NIL))
            else:
                idx = self.symtab.get_or_add(name)
                buf.emit(encode_op_u16(PUSH_VALUE, idx))

        elif isinstance(node, Integer):
            val = node.value
            if -128 <= val <= 127:
                buf.emit(encode_op_u16(PUSH_INT8, val & 0xFF))
            else:
                buf.emit(struct.pack('<Bi', PUSH_INT32, val))

        elif isinstance(node, Real):
            buf.emit(encode_real(node.value))

        elif isinstance(node, String):
            idx = self.symtab.add_string(node.value)
            buf.emit(encode_op_u16(PUSH_G, idx))

        elif isinstance(node, Call):
            self._emit_call_expr(buf, node)

        elif isinstance(node, QuotedExpr):
            self._emit_quoted(buf, node.expr)

        elif isinstance(node, ListExpr):
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

        elif isinstance(node, Progn):
            for form in node.forms[:-1]:
                self._emit_expr(buf, form)
                buf.emit(encode_op_noarg(POP))
            if node.forms:
                self._emit_expr(buf, node.forms[-1])

        elif isinstance(node, Cond):
            self._emit_cond(buf, node)

        elif isinstance(node, LambdaNode):
            self._emit_expr(buf, QuotedExpr(expr=ListExpr(items=[Symbol('lambda')] + node.body)))

        else:
            raise NotImplementedError(f'Cannot emit expression: {type(node).__name__}')

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
        if name in ('and', 'or') and len(args) >= 1:
            self._emit_short_circuit(buf, name, args)
            return
        if name == 'list':
            for arg in reversed(args):
                self._emit_expr(buf, arg)
            buf.emit(encode_op_u16(BUILD_LIST, len(args)))
            return
        if name == 'progn':
            for form in args[:-1]:
                self._emit_expr(buf, form)
                buf.emit(encode_op_noarg(POP))
            if args:
                self._emit_expr(buf, args[-1])
            return
        if name in ('setq',):
            if len(args) >= 2:
                self._emit_setq_expr(buf, args[0], args[1])
            for i in range(2, len(args), 2):
                if i + 1 < len(args):
                    self._emit_setq_expr(buf, args[i], args[i + 1])
            return
        if name == 'repeat' and len(args) >= 2:
            self._emit_repeat(buf, args[0], args[1:])
            return

        idx = self.symtab.get_or_add(name)
        is_builtin = self.symtab.is_builtin(name)
        for arg in args:
            self._emit_expr(buf, arg)
        if is_builtin:
            buf.emit(encode_func(len(args), idx))
        else:
            buf.emit(encode_usubr(len(args), idx))

    def _emit_setq_expr(self, buf: BytecodeBuffer, target: Node, value: Node):
        if isinstance(target, Symbol):
            self._emit_expr(buf, value)
            idx = self.symtab.get_or_add(target.name)
            buf.emit(encode_op_u16(SETQ_G, idx))
        else:
            self._emit_expr(buf, value)
            self._emit_expr(buf, target)
            buf.emit(encode_func(1, self.symtab.get_or_add('set')))

    def _emit_setq(self, buf: BytecodeBuffer, node: Setq):
        for target, value in node.pairs:
            if isinstance(target, Symbol) and value:
                self._emit_expr(buf, value)
                idx = self.symtab.get_or_add(target.name)
                buf.emit(encode_op_u16(SETQ_G, idx))
                buf.emit(encode_op_noarg(POP))

    def _emit_if(self, buf: BytecodeBuffer, node: IfNode):
        label_else = f'_if_else_{buf.pos()}'
        label_end = f'_if_end_{buf.pos()}'

        self._emit_expr(buf, node.cond)

        if node.else_expr:
            jmp_pos = buf.pos()
            buf.emit(encode_op_u16(JMP16_IFNOT, 0))
            buf.add_patch(jmp_pos + 1, label_else, 2)

            self._emit_expr(buf, node.then)
            jmp2_pos = buf.pos()
            buf.emit(encode_op_s32(JUMP, 0))
            buf.add_patch(jmp2_pos + 1, label_end, 4)

            buf.patch_label(label_else, buf.pos())
            self._emit_expr(buf, node.else_expr)
            buf.patch_label(label_end, buf.pos())
        else:
            jmp_pos = buf.pos()
            buf.emit(encode_op_u16(JMP16_IFNOT, 0))
            buf.add_patch(jmp_pos + 1, label_end, 2)

            self._emit_expr(buf, node.then)
            buf.patch_label(label_end, buf.pos())

    def _emit_while(self, buf: BytecodeBuffer, node: WhileNode):
        label_loop = f'_while_loop_{buf.pos()}'
        label_end = f'_while_end_{buf.pos()}'

        buf.label(label_loop)
        self._emit_expr(buf, node.cond)
        jmp_pos = buf.pos()
        buf.emit(encode_op_u16(JMP16_IFNOT, 0))
        buf.add_patch(jmp_pos + 1, label_end, 2)

        for form in node.body:
            self._emit_expr(buf, form)
            buf.emit(encode_op_noarg(POP))

        jmp_back = buf.pos()
        buf.emit(encode_op_s32(JUMP, 0))
        buf.add_patch(jmp_back + 1, label_loop, 4)

        buf.label(label_end)

    def _emit_foreach(self, buf: BytecodeBuffer, node: ForeachNode):
        var_name = node.var.name if isinstance(node.var, Symbol) else 'item'
        slot = self._get_local_slot(f'__foreach_list__{buf.pos()}')
        item_slot = self._get_local_slot(f'__foreach_item__{buf.pos()}')

        self._emit_expr(buf, node.list_expr)
        buf.emit(encode_op_u16(SET_LOCAL_16, slot))

        label_loop = f'_foreach_loop_{buf.pos()}'
        label_end = f'_foreach_end_{buf.pos()}'

        buf.label(label_loop)
        buf.emit(encode_op_u16(GET_LOCAL_16, slot))
        buf.emit(encode_op_noarg(PUSH_NIL))
        jmp_pos = buf.pos()
        buf.emit(encode_op_u16(JMP16_IFNOT, 0))
        buf.add_patch(jmp_pos + 1, label_end, 2)

        buf.emit(encode_op_u16(GET_LOCAL_16, slot))
        buf.emit(encode_op_noarg(CAR))
        idx = self.symtab.get_or_add(var_name)
        buf.emit(encode_op_u16(SETQ_G, idx))

        buf.emit(encode_op_u16(GET_LOCAL_16, slot))
        buf.emit(encode_op_noarg(CDR))
        buf.emit(encode_op_u16(SET_LOCAL_16, slot))

        for form in node.body:
            self._emit_expr(buf, form)
            buf.emit(encode_op_noarg(POP))

        jmp_back = buf.pos()
        buf.emit(encode_op_s32(JUMP, 0))
        buf.add_patch(jmp_back + 1, label_loop, 4)

        buf.label(label_end)

    def _emit_short_circuit(self, buf: BytecodeBuffer, op_name: str, args: List[Node]):
        label_end = f'_sc_end_{buf.pos()}'
        op = JMP16_IFNOT if op_name == 'and' else JMP16_IF
        for i, arg in enumerate(args[:-1]):
            self._emit_expr(buf, arg)
            jmp_pos = buf.pos()
            buf.emit(encode_op_u16(op, 0))
            buf.add_patch(jmp_pos + 1, label_end, 2)
        self._emit_expr(buf, args[-1])
        buf.label(label_end)

    def _emit_cond(self, buf: BytecodeBuffer, node: Cond):
        label_end = f'_cond_end_{buf.pos()}'
        label_next = None
        for i, clause in enumerate(node.clauses):
            if label_next:
                buf.label(label_next)
            if len(clause) == 0:
                continue
            cond = clause[0]
            actions = clause[1:]
            if isinstance(cond, Symbol) and cond.name.lower() == 't':
                for action in actions:
                    self._emit_expr(buf, action)
                break

            self._emit_expr(buf, cond)
            if actions:
                jmp_pos = buf.pos()
                label_next = f'_cond_next_{buf.pos()}_{i}'
                buf.emit(encode_op_u16(JMP16_IFNOT, 0))
                buf.add_patch(jmp_pos + 1, label_next, 2)
                for action in actions:
                    self._emit_expr(buf, action)
                if i < len(node.clauses) - 1:
                    jmp2_pos = buf.pos()
                    label_end_label = label_end
                    buf.emit(encode_op_s32(JUMP, 0))
                    buf.add_patch(jmp2_pos + 1, label_end_label, 5)
            else:
                buf.emit(encode_op_noarg(POP))
        buf.label(label_end)

    def _emit_repeat(self, buf: BytecodeBuffer, count_expr: Node, body: List[Node]):
        slot = self._get_local_slot('__repeat__')
        self._emit_expr(buf, count_expr)
        buf.emit(encode_op_u16(SET_LOCAL_16, slot))
        label_loop = f'_repeat_loop_{buf.pos()}'
        label_end = f'_repeat_end_{buf.pos()}'
        buf.label(label_loop)
        buf.emit(encode_op_u16(GET_LOCAL_16, slot))
        buf.emit(encode_op_noarg(INC))
        jmp_pos = buf.pos()
        buf.emit(encode_op_u16(JMP16_IFNOT, 0))
        buf.add_patch(jmp_pos + 1, label_end, 2)
        buf.emit(encode_op_u16(SET_LOCAL_16, slot))
        for form in body:
            self._emit_expr(buf, form)
            buf.emit(encode_op_noarg(POP))
        jmp_back = buf.pos()
        buf.emit(encode_op_s32(JUMP, 0))
        buf.add_patch(jmp_back + 1, label_loop, 4)
        buf.label(label_end)

    def _emit_quoted(self, buf: BytecodeBuffer, node: Optional[Node]):
        if node is None:
            buf.emit(encode_op_noarg(PUSH_NIL))
        elif isinstance(node, Symbol):
            name = node.name
            if name == 'T':
                buf.emit(encode_op_noarg(PUSH_T))
            elif name == 'nil':
                buf.emit(encode_op_noarg(PUSH_NIL))
            elif name == 'FUNC':
                buf.emit(encode_op_noarg(PUSH_NIL))
            else:
                idx = self.symtab.get_or_add(name)
                buf.emit(encode_op_u16(PUSH_G, idx))
        elif isinstance(node, Integer):
            val = node.value
            if -128 <= val <= 127:
                buf.emit(encode_op_u16(PUSH_INT8, val & 0xFF))
            else:
                buf.emit(struct.pack('<Bi', PUSH_INT32, val))
        elif isinstance(node, Real):
            buf.emit(encode_real(node.value))
        elif isinstance(node, ListExpr):
            items = node.items
            if items and isinstance(items[0], Symbol) and items[0].name == 'lambda':
                buf.emit(encode_op_noarg(PUSH_NIL))
            else:
                buf.emit(encode_op_noarg(PUSH_NIL))
                for item in reversed(items):
                    self._emit_quoted(buf, item)
                buf.emit(encode_op_u16(BUILD_LIST, len(items)))
        elif isinstance(node, String):
            idx = self.symtab.add_string(node.value)
            buf.emit(encode_op_u16(PUSH_G, idx))
        elif isinstance(node, Call):
            idx = self.symtab.get_or_add(node.name)
            buf.emit(encode_op_u16(PUSH_G, idx))
        else:
            self._emit_expr(buf, node)

    def _emit_defun_header(self, buf: BytecodeBuffer, func: Defun):
        idx = self.symtab.idx_of(func.name) or self.symtab.get_or_add(func.name)
        buf.emit(encode_defun(idx, 0))

    def _emit_init_args(self, buf: BytecodeBuffer, args: List[str]):
        for i, arg in enumerate(args):
            idx = self.symtab.get_or_add(arg)
            buf.emit(encode_op_u16(PUSH_G, idx))
            buf.emit(struct.pack('<BB', GET_LOCAL_8, i))
        buf.emit(encode_op_u16(INIT_ARGS, len(args) * 2))

    def _emit_clear_args(self, buf: BytecodeBuffer, args: List[str]):
        if args:
            buf.emit(encode_op_u16(CLEAR_ARGS, len(args)))

    def generate_function(self, func: Defun) -> Tuple[bytes, int]:
        buf = BytecodeBuffer()
        start_offset = 0

        self._emit_defun_header(buf, func)
        start_offset = 3

        for i, arg in enumerate(func.args):
            self.local_slots[arg] = i

        self._emit_init_args(buf, func.args)

        for i, loc in enumerate(func.locals):
            slot = i + len(func.args)
            self.local_slots[loc] = slot
            self.next_slot = max(self.next_slot, slot + 1)

        arity_bound = func.args + func.locals
        for name in set(self.local_slots.keys()) - set(arity_bound):
            pass

        for expr in func.body[:-1]:
            self._emit_expr(buf, expr)
            buf.emit(encode_op_noarg(POP))
        if func.body:
            self._emit_expr(buf, func.body[-1])

        self._emit_clear_args(buf, func.args)
        buf.emit(encode_op_noarg(END_DEFUN))

        buf.resolve()
        return bytes(buf.data), start_offset

    def generate_init_code(self, forms: List[Node]) -> bytes:
        buf = BytecodeBuffer()
        for form in forms:
            self._emit_expr(buf, form)
            buf.emit(encode_op_noarg(POP))
        buf.resolve()
        return bytes(buf.data)
