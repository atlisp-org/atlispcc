import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

from decompiler.fas4_decompiler import (
    Disassembler, Fas4Parser, is_compact_stub, LispGenerator,
    Instruction, FunctionDef, Fas4File,
)

TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.dirname(TESTS_DIR)

PDI_FAS = os.path.join(ROOT_DIR, 'tests', 'cad', 'i18n.fas')
CAD_FAS = os.path.join(ROOT_DIR, 'tests', 'cad', 't01_math_cad.fas')

pytestmark = pytest.mark.skipif(
    not os.path.exists(PDI_FAS),
    reason='tests/cad/i18n.fas reference fixture not present',
)


def _disassemble(fas_path):
    fas = Fas4Parser().parse(fas_path)
    disasm = Disassembler(short_subr=is_compact_stub(fas.bytecode, fas.function_catalog))
    return disasm.disassemble(fas.bytecode, fas.nsyms), fas


def test_disasm_pdi_no_unknown_opcodes():
    insts, _ = _disassemble(PDI_FAS)
    assert len(insts) > 0
    unks = [i for i in insts if i.op_name.startswith('UNK')]
    assert unks == [], f'unknown opcodes: {unks}'


def test_disasm_pdi_offsets_monotonic():
    insts, _ = _disassemble(PDI_FAS)
    for prev, inst in zip(insts, insts[1:]):
        assert inst.offset >= prev.offset + prev.size, (
            f'instruction {prev.op_name}@0x{prev.offset:x} overlaps next {inst.op_name}@0x{inst.offset:x}'
        )


def test_disasm_pdi_structure():
    insts, _ = _disassemble(PDI_FAS)
    opnames = {i.op_name for i in insts}
    for expected in ('DEFUN', 'END_DEFUN', 'INIT_ARGS', 'USUBR', 'PUSH_VALUE', 'SET_LOCAL'):
        assert expected in opnames, f'missing {expected} in {sorted(opnames)}'
    assert 'GET_LOCAL' in opnames or 'GET_LOCAL_WIDE' in opnames, (
        f'missing GET_LOCAL/GET_LOCAL_WIDE in {sorted(opnames)}'
    )


def test_disasm_cad_fas_no_unknown_opcodes():
    if not os.path.exists(CAD_FAS):
        pytest.skip('tests/cad/t01_math_cad.fas reference fixture not present')
    insts, _ = _disassemble(CAD_FAS)
    assert len(insts) > 0
    unks = [i for i in insts if i.op_name.startswith('UNK')]
    assert unks == [], f'unknown opcodes: {unks}'


def _minimal_spec(insts):
    func = FunctionDef('f', 0, [], [], 0, len(insts), insts)
    return {
        'func': func, 'index': 0, 'is_init': False, 'original_name': 'f', 'name': 'f',
        'args': [], 'arg_originals': [], 'locals': [], 'local_originals': [],
        'body_start': 0, 'body_symbols': set(), 'body_strings': set(),
        'slot_names': {}, 'local_used': set(), 'bound_symbol_map': {},
        'bound_gvar_map': {}, 'global_aliases': {}, 'slot_expr_map': {},
        'localized_globals': set(),
    }


def _minimal_gen():
    fas = Fas4File(nsyms=1, bytecode=b'', sec2_data=b'', sec2_items=0,
                   crunch_date='', tail_bytes=b'', key=b'',
                   resource_items=[], resource_items_with_offsets=[],
                   symbols=['f'], resource_gvars=[], function_gvars=[],
                   function_catalog=[])
    return LispGenerator(fas)


def test_render_block_unhandled_opcode_comment():
    """Unknown opcodes render as comment markers instead of raising."""
    insts = [
        Instruction(offset=0, opcode=0x32, op_name='PUSH_INT8', operands=[5], size=2),
        Instruction(offset=2, opcode=0x99, op_name='UNK_99', operands=[], size=1),
        Instruction(offset=3, opcode=0x0a, op_name='POP', operands=[], size=1),
    ]
    gen = _minimal_gen()
    lines = gen._render_block(_minimal_spec(insts), insts, 0, 3, 1)
    text = '\n'.join(lines)
    assert ';; unhandled opcodes: UNK_99' in text, f'missing marker in: {text}'


def test_render_block_unhandled_branch_comment():
    """A branch that cannot be reconstructed emits a marker comment."""
    insts = [
        Instruction(offset=0, opcode=0x32, op_name='PUSH_INT8', operands=[1], size=2),
        Instruction(offset=2, opcode=0x0d, op_name='JMP16_IFNOT', operands=[50], size=3),
        Instruction(offset=5, opcode=0x0a, op_name='POP', operands=[], size=1),
    ]
    gen = _minimal_gen()
    lines = gen._render_block(_minimal_spec(insts), insts, 0, 3, 1)
    text = '\n'.join(lines)
    assert ';; unhandled branch' in text, f'missing branch marker in: {text}'


def test_opcode_tables_in_sync():
    """Disassembler and compiler opcode tables must be identical."""
    from asm import opcodes as compiler_opcodes
    assert Disassembler.OPCODES == compiler_opcodes.OPCODES


def test_new_opcode_decoding():
    """The added opcode entries decode with expected sizes."""
    bc = bytes([
        0x0c, 0x34, 0x12,           # PUSH_G_ALT: op + u16
        0x15, 0, 0, 0, 0,           # DEFUN_ALT: op + 4 bytes
        0x37, 0x02, 0x00,           # BUILD_LIST_ALT: op + u16
    ])
    insts = Disassembler(short_subr=False).disassemble(bc, 8)
    assert insts[0].op_name == 'PUSH_G_ALT' and insts[0].size == 3
    assert insts[0].operands == [0x1234]
    assert insts[1].op_name == 'DEFUN_ALT' and insts[1].size == 5
    assert insts[2].op_name == 'BUILD_LIST_ALT' and insts[2].size == 3
    assert insts[2].offset == 8


def test_phantom_opcodes_disassemble_as_unknown():
    """伪指令字节（10/1a/1b/38/40）不是真实操作码，反汇编为 UNK_。

    107 个 CAD 产物实测这些字节从不在指令边界出现（仅作其他指令的
    操作数或符号/字符串载荷，见 docs/opcodes.md「伪指令说明」）。
    它们已从 OPCODES 表移除，此处验证单字节出现时安全降级为 UNK_。
    """
    for op in (0x10, 0x1a, 0x1b, 0x38, 0x40):
        insts = Disassembler(short_subr=False).disassemble(bytes([op]), 0)
        assert len(insts) == 1, f'0x{op:02x} should be 1 instruction'
        assert insts[0].op_name == f'UNK_{op:02x}', insts[0].op_name
        assert insts[0].size == 1


def test_parse_empty_seg0_pure_top_level(tmp_path):
    """纯顶层（无 defun）文件的空 seg0 可解析（回归：`atlispcc disasm`
    对 `(alert "xx")` 编译产物曾报 "Bad FAS payload header"）。

    空 seg0 无 `16 24 0d 0a` 终止符，须用 `{nsyms} $` 头的 `$` 定界 payload。
    """
    import tempfile
    from compiler.cli import cmd_compile
    from asm.assembler import disassemble_fas

    src = '(alert "hello")\n'
    fas_path = os.path.join(tempfile.gettempdir(), 'empty_seg0_test.fas')
    try:
        cmd_compile(src, fas_path)
        fas = Fas4Parser().parse(fas_path)
        assert fas.bytecode == b'', f'空 seg0 应无字节码: {fas.bytecode.hex()}'
        # disasm 全链路不崩溃
        text = disassemble_fas(fas_path)
        assert 'ALERT' in text or 'alert' in text
    finally:
        if os.path.exists(fas_path):
            os.unlink(fas_path)
