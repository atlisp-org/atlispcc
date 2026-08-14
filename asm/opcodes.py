import struct
from typing import List, Any


OPCODES = {
    0x00: ('NIL', ''), 0x01: ('PUSH_NIL', ''), 0x02: ('PUSH_T', ''),
    0x03: ('PUSH_VALUE', '2'), 0x05: ('GET_LOCAL', '1'), 0x06: ('SETQ_G', '2'), 0x07: ('COPY_ELEM', 'bb'),
    0x09: ('PUSH_G', '2'), 0x0a: ('POP', ''), 0x0b: ('DUP', ''),
     0x0c: ('PUSH_G_ALT', '2'), 0x0d: ('JMP16_IFNOT', '2'), 0x0e: ('JMP16_IF', '2'),
     0x14: ('DEFUN', 'h'), 0x15: ('DEFUN_ALT', 'h'), 0x16: ('END_DEFUN', ''),
    0x18: ('INIT_ARGS', '2'),
    0x19: ('CLEAR_ARGS', '2'), 0x1c: ('INIT_DONE', ''),
    0x1e: ('ALPHA', '1'), 0x1f: ('BETA', '1'),
    0x20: ('NOP', ''), 0x21: ('END_DEFUN_CLEANUP', '2'), 0x23: ('NOT', ''), 0x24: ('ATOM', ''),
     0x28: ('CAR', ''), 0x29: ('CDR', ''), 0x2A: ('CONS', ''), 0x32: ('PUSH_INT8', '1'), 0x33: ('PUSH_INT32', '4'),
     0x34: ('EVAL', 'e'), 0x37: ('BUILD_LIST_ALT', '2'), 0x39: ('BUILD_LIST', '2'),
     0x3a: ('DEFCODE', ''), 0x3b: ('PUSH_REAL', 'z'), 0x3c: ('JMP16_IFNOT_ALT', '2'),
     0x3d: ('JMP16_IF_ALT', '2'), 0x3e: ('EXIT_IF_NOT_ZERO', ''), 0x3f: ('EXIT_IF_ZERO', ''),
    0x35: ('USUBR', 'u'),
    0x46: ('FIX_ADD', ''), 0x47: ('FIX_SUB', ''), 0x48: ('FIX_MUL', ''), 0x49: ('FIX_DIV', ''),
    0x4a: ('FIX_MOD', ''), 0x4b: ('FIX_LEQ', ''), 0x4c: ('FIX_GEQ', ''), 0x4d: ('FIX_LT', ''),
    0x4e: ('FIX_GT', ''), 0x4f: ('INC', ''), 0x50: ('DEC', ''),
    0x51: ('FUNC', 'f'), 0x57: ('JUMP', 's4'), 0x5c: ('GET_LOCAL_WIDE', '2'),
     0x5d: ('SET_LOCAL', '2'), 0x5e: ('CLEAR_LOCAL', '2'), 0x62: ('NOP_ALT', ''), 0x63: ('NOP_ALT2', ''),
     0x67: ('JMP32_IFNOT', 's4'), 0x68: ('COND_OR', 's4'), 0x69: ('JUMP_ALT', 's4'),
     0x6a: ('COND_AND', 's4'),
}

OPCODE_TO_NAME = {op: name for op, (name, _) in OPCODES.items()}
NAME_TO_OPCODE = {name: op for op, (name, _) in OPCODES.items()}
OPCODE_FORMAT = {op: fmt for op, (_, fmt) in OPCODES.items()}


OP_TO_BYTECODE = {
    'FIX_ADD': 0x46, 'FIX_SUB': 0x47, 'FIX_MUL': 0x48, 'FIX_DIV': 0x49,
    'FIX_MOD': 0x4a, 'FIX_LEQ': 0x4b, 'FIX_GEQ': 0x4c, 'FIX_LT': 0x4d,
    'FIX_GT': 0x4e, 'NOT': 0x23, 'ATOM': 0x24, 'CAR': 0x28, 'CDR': 0x29,
    'INC': 0x4f, 'DEC': 0x50,
}

ARITH_OP_MAP = {
    '+': 'FIX_ADD', '-': 'FIX_SUB', '*': 'FIX_MUL', '/': 'FIX_DIV',
    'rem': 'FIX_MOD', '<=': 'FIX_LEQ', '>=': 'FIX_GEQ', '<': 'FIX_LT',
    '>': 'FIX_GT', '1+': 'INC', '1-': 'DEC',
    'not': 'NOT', 'atom': 'ATOM', 'car': 'CAR', 'cdr': 'CDR',
}


def encode_op_noarg(op: int) -> bytes:
    return bytes([op])


def encode_op_u16(op: int, val: int) -> bytes:
    return struct.pack('<BH', op, val)


def encode_op_u8(op: int, val: int) -> bytes:
    return struct.pack('<BB', op, val & 0xFF)


def encode_op_s32(op: int, val: int) -> bytes:
    return struct.pack('<Bi', op, val)


def encode_op_u32(op: int, val: int) -> bytes:
    return struct.pack('<BI', op, val)


def encode_bb(op: int, left: int, right: int) -> bytes:
    return struct.pack('<BBB', op, left & 0xFF, right & 0xFF)


def encode_usubr(argc: int, idx: int, flags: int = 0) -> bytes:
    return struct.pack('<BBHB', 0x35, argc & 0xFF, idx & 0xFFFF, flags & 0xFF)


def encode_usubr3(argc: int, idx: int) -> bytes:
    """3 字节 Xsubr：``35 <argc> <idx>`` — AutoCAD 紧凑 stub 格式。"""
    return struct.pack('<BBB', 0x35, argc & 0xFF, idx & 0xFF)


def encode_func(argc: int, idx: int, flags: int = 0) -> bytes:
    return struct.pack('<BBHBB', 0x51, argc & 0xFF, idx & 0xFFFF, flags & 0xFF, 0)


def encode_func3(argc: int, idx: int) -> bytes:
    """3 字节 Func：``51 <argc> <idx>`` — AutoCAD 紧凑 stub 格式。"""
    return struct.pack('<BBB', 0x51, argc & 0xFF, idx & 0xFF)


def encode_defun(gvar_ref: int, offset: int = 0) -> bytes:
    return struct.pack('<BHH', 0x14, gvar_ref & 0xFFFF, offset & 0xFFFF)


def encode_eval(argc: int, flag: int = 0) -> bytes:
    return struct.pack('<BBB', 0x34, argc & 0xFF, flag & 0xFF)


def encode_real(value: float) -> bytes:
    # .15g：足够精确保存 double，同时小数值（3.14159/0.5 等）与 :g 输出一致，
    # 避免大整数转实数时被 :g 缩写成科学计数法（4294957297 → 4.29496e+09）。
    s = f'{value:.15g}'.encode('ascii')
    return bytes([0x3b]) + s + b'\x00'


def encode_instruction(name: str, operands: List[Any]) -> bytes:
    op = NAME_TO_OPCODE.get(name)
    if op is None:
        raise ValueError(f'Unknown opcode name: {name}')
    fmt = OPCODE_FORMAT.get(op, '')
    if fmt == '':
        return encode_op_noarg(op)
    elif fmt == '1':
        return encode_op_u8(op, int(operands[0]))
    elif fmt == '2':
        return encode_op_u16(op, int(operands[0]))
    elif fmt == '4':
        return encode_op_s32(op, int(operands[0]))
    elif fmt == 's4':
        return encode_op_s32(op, int(operands[0]))
    elif fmt == 'bb':
        return encode_bb(op, int(operands[0]), int(operands[1]))
    elif fmt == 'u':
        return encode_usubr(int(operands[0]), int(operands[1]), int(operands[2]) if len(operands) > 2 else 0)
    elif fmt == 'f':
        return encode_func(int(operands[0]), int(operands[1]), int(operands[2]) if len(operands) > 2 else 0)
    elif fmt == 'h':
        gv, off = int(operands[0]), int(operands[1]) if len(operands) > 1 else 0
        return encode_defun(gv, off)
    elif fmt == 'e':
        return encode_eval(int(operands[0]), int(operands[1]) if len(operands) > 1 else 0)
    elif fmt == 'z':
        return bytes([op]) + str(operands[0]).encode('ascii') + b'\x00'
    else:
        raise ValueError(f'Unknown format: {fmt}')
