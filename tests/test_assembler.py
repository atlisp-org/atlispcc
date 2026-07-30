"""Tests for the FAS4 assembler/disassembler (.fas ↔ .lasm)."""
import os
import tempfile

from compiler.assembler import disassemble_fas, assemble_lasm
from compiler.cli import cmd_compile as compile_lsp
from fas4_decompiler import Fas4Parser, LispGenerator


def _compile_lsp(source: str) -> str:
    fas_path = os.path.join(tempfile.gettempdir(), 'test_asm.fas')
    compile_lsp(source, fas_path)
    return fas_path


def _decompile_fas(fas_path: str) -> str:
    parser = Fas4Parser()
    fas = parser.parse(fas_path)
    from fas4_decompiler import Disassembler, ControlFlowAnalyzer
    disasm = Disassembler()
    instructions = disasm.disassemble(fas.bytecode, fas.nsyms)
    cfa = ControlFlowAnalyzer(instructions, fas.function_catalog)
    functions = cfa.find_functions()
    gen = LispGenerator(fas)
    return gen.generate(functions, fas_path)


def test_disassemble_assemble_roundtrip():
    source = """
(defun test-func (x)
  (setq y (+ x 1))
  (princ y))
"""
    fas_path = _compile_lsp(source)
    lasm_text = disassemble_fas(fas_path)

    assert '.symbols' in lasm_text
    assert '.function' in lasm_text
    assert 'DEFUN' in lasm_text

    fd, out_path = tempfile.mkstemp(suffix='.fas')
    os.close(fd)
    try:
        assemble_lasm(lasm_text, out_path)
        lsp_code = _decompile_fas(out_path)
        assert len(lsp_code) > 0
        assert 'defun' in lsp_code.lower()
    finally:
        if os.path.exists(out_path):
            os.unlink(out_path)


def test_simple_add_function():
    lasm_text = """; Test: simple add
.symbols
  0: SYMBOL __init__
  1: SYMBOL test-add
  2: SYMBOL x
  3: SYMBOL y
.end_symbols

.function __init__, 0
  0x0000: DEFUN test-add, 0
  0x0005: INIT_ARGS 2
  0x0008: ALPHA 1
  0x000a: PUSH_G x
  0x000c: PUSH_G y
  0x000e: FIX_ADD
  0x000f: CLEAR_LOCAL 1
  0x0011: BETA 0
  0x0013: END_DEFUN
  0x0014: NIL
.end_function
"""
    fd, out_path = tempfile.mkstemp(suffix='.fas')
    os.close(fd)
    try:
        assemble_lasm(lasm_text, out_path)
        lsp_code = _decompile_fas(out_path)
        assert len(lsp_code) > 0
        assert '+' in lsp_code
    finally:
        if os.path.exists(out_path):
            os.unlink(out_path)


def test_assembler_handles_local_vars():
    lasm_text = """; Test local variable handling
.symbols
  0: SYMBOL __init__
  1: SYMBOL my-func
  2: SYMBOL v
  3: SYMBOL n
.end_symbols

.function my-func, 1
  0x0000: DEFUN my-func, 0
  0x0005: INIT_ARGS 1
  0x0008: ALPHA 0
  0x000a: PUSH_G n
  0x000c: GET_LOCAL 0
  0x000e: FIX_ADD
  0x000f: SET_LOCAL 0
  0x0011: BETA 0
  0x0013: END_DEFUN
  0x0014: NIL
.end_function
"""
    fd, out_path = tempfile.mkstemp(suffix='.fas')
    os.close(fd)
    try:
        assemble_lasm(lasm_text, out_path)
        lsp_code = _decompile_fas(out_path)
        assert len(lsp_code) > 0
    finally:
        if os.path.exists(out_path):
            os.unlink(out_path)


def test_disassemble_output_is_parseable():
    source = """
(defun hello ()
  (princ "Hello, World!"))
"""
    fas_path = _compile_lsp(source)
    lasm_text = disassemble_fas(fas_path)

    for line in lasm_text.split('\n'):
        stripped = line.split(';', 1)[0].strip()
        if not stripped:
            continue
        if stripped.startswith('.'):
            assert stripped in (
                '.symbols', '.end_symbols',
            ) or stripped.startswith('.function') or stripped.startswith('.end_function')
        elif ':' in stripped[:10]:
            assert any(c.isalpha() for c in stripped[10:]), f'Missing mnemonic: {stripped}'
        elif stripped[0].isdigit() and ': SYMBOL' in stripped:
            continue
