"""Standalone compiler output tests: compile Lisp and inspect FAS binary directly."""
import sys
sys.path.insert(0, '.')

import os
import tempfile
from compiler.parser import Parser
from compiler.symbol_table import SymbolTable
from compiler.codegen import CodeGenerator, BytecodeBuffer
from compiler.resource_builder import ResourceBuilder
from compiler.fas_writer import FasWriter

ENCODE_POP = bytes([0x0a])
FAS4_MAGIC = b'\r\n FAS4-FILE ; Do not change it!\r\n'
SEG_TERMINATOR = b'\x19\x04\x00\x16\x24\r\n'


def _compile_to_fas(src: str) -> bytes:
    """Compile Lisp source to FAS binary, return raw bytes."""
    parser = Parser(src)
    program = parser.parse()

    symtab = SymbolTable()
    symtab.collect_symbols(program)

    codegen = CodeGenerator(symtab)
    from compiler.ast import Defun

    all_bc = BytecodeBuffer()
    func_offsets = {}

    other_forms = [f for f in program.forms if not isinstance(f, Defun)]
    for form in other_forms:
        codegen._emit_expr(all_bc, form)
        all_bc.emit(ENCODE_POP)

    for form in program.forms:
        if isinstance(form, Defun):
            offset = len(all_bc.data)
            fb, _ = codegen.generate_function(form)
            func_offsets[form.name] = offset
            all_bc.emit(fb)

    for name, offset in func_offsets.items():
        symtab.add_func_ref(name, offset)

    seg0 = bytes(all_bc.data)
    resource = ResourceBuilder(symtab)
    seg1 = resource.build(func_offsets)

    with tempfile.NamedTemporaryFile(suffix='.fas', delete=False) as f:
        fas_path = f.name
        writer = FasWriter(symtab)
        writer.write(fas_path, seg0, seg1)

    with open(fas_path, 'rb') as f:
        data = f.read()
    os.unlink(fas_path)
    return data


def test_magic_header():
    """FAS binary starts with the correct magic string."""
    data = _compile_to_fas('(defun foo () 1)')
    assert data.startswith(FAS4_MAGIC), f"Bad magic: {data[:50]}"


def _parse_fas(data: bytes):
    """Parse FAS binary into its constituent parts.
    Returns (nsyms, seg0_bytecode, seg1_data, seg1_item_count)."""
    # Format:
    #   \r\n FAS4-FILE ; Do not change it!\r\n
    #   <total_size>\r\n
    #   <nsyms> $<bytecode>                   <- seg0 payload
    #   \x19\x04\x00\x16\x24\r\n               <- SEG_TERMINATOR
    #   <seg1_len> <item_count> $<seg1_data>\r\n  <- seg1
    parts = data.split(SEG_TERMINATOR)
    assert len(parts) == 2
    seg0_part, seg1_full = parts

    # Find the nsyms header: it's after the magic and total_size lines
    # The seg0 payload is: "<nsyms> $" + bytecode
    # Find "$" that follows the nsyms count
    # The magic ends with "\r\n", then total_size line ends with "\r\n"
    # After that, the remaining is "<nsyms> $<bytecode>"
    magic_end = seg0_part.index(b'\r\n', 2)  # first \r\n after initial bytes
    size_end = seg0_part.index(b'\r\n', magic_end + 1)  # \r\n after total_size
    nsyms_and_bc = seg0_part[size_end + 2:]

    # nsyms_and_bc = b'<nsyms> $<bytecode>'
    dollar_at = nsyms_and_bc.index(b'$')
    nsyms = int(nsyms_and_bc[:dollar_at - 1])  # before " $"
    bytecode = nsyms_and_bc[dollar_at + 1:]

    # seg1_full: <seg1_len> <item_count> $<seg1_data>\r\n
    seg1_no_trailing = seg1_full.rstrip(b'\r\n')
    dollar_at = seg1_no_trailing.index(b'$')
    seg1_header = seg1_no_trailing[:dollar_at - 1]  # "<len> <count>"
    seg1_data = seg1_no_trailing[dollar_at + 1:]
    header_parts = seg1_header.split(b' ')
    seg1_len = int(header_parts[0])
    sec2_items = int(header_parts[1]) if len(header_parts) >= 2 else 0

    return nsyms, bytecode, seg1_data, sec2_items


def test_two_segments():
    """FAS binary: two segments separated by terminator, with nsyms > 0."""
    data = _compile_to_fas('(defun foo () 1)')
    assert SEG_TERMINATOR in data, "Segment terminator not found"
    nsyms, bc, seg1, _ = _parse_fas(data)
    assert nsyms > 0, f"Expected >0 symbols, got {nsyms}"
    assert len(bc) > 0, "Empty bytecode segment"
    assert len(seg1) > 0, "Empty seg1"


def test_symbol_table_content():
    """Compiled FAS contains expected symbols."""
    data = _compile_to_fas('(defun foo () 1)')
    nsyms, bc, seg1, _ = _parse_fas(data)
    assert nsyms >= 2, f"Expected >=2 symbols (foo + 1), got {nsyms}"


def test_func_def_compile():
    """Compiled function has non-empty bytecode."""
    data = _compile_to_fas('(defun foo () 1)')
    _, bc, _, _ = _parse_fas(data)
    assert len(bc) >= 2, f"Bytecode too short ({len(bc)} bytes)"
    # Should contain: PUSH_INT (0x32) for the integer 1
    assert b'\x32' in bc, "Expected PUSH_INT opcode in function body"


def test_init_code_compile():
    """Top-level init code produces separate bytecode segment."""
    data = _compile_to_fas('(princ "Hello")\n(defun foo () 1)')
    _, bc, seg1, _ = _parse_fas(data)
    assert len(bc) > 0
    # The "Hello" string should be in seg1 (resource section), not bytecode
    assert b'Hello' in seg1, (
        "String literal 'Hello' should be in resource section (seg1)"
    )


def test_local_vars_symbols():
    """Local variables appear in the symbol table."""
    src = '(defun foo (/ x y) (setq x 10) (+ x y))'
    data = _compile_to_fas(src)

    parts = data.split(SEG_TERMINATOR)
    seg1_part = parts[1]

    # seg1 should contain 'x' and 'y' as symbols
    assert b'foo\x00' in seg1_part, "Symbol 'foo' missing from seg1"
    assert b'x\x00' in seg1_part, "Symbol 'x' missing from seg1"
    assert b'y\x00' in seg1_part, "Symbol 'y' missing from seg1"


def test_string_literal_in_seg1():
    """String literals appear in the resource section."""
    src = '(defun hello () (princ "Hello World"))'
    data = _compile_to_fas(src)

    parts = data.split(SEG_TERMINATOR)
    seg1_part = parts[1]

    assert b'Hello World' in seg1_part, (
        "String literal 'Hello World' not found in seg1"
    )


def test_magic_roundtrip():
    """Compiled FAS: compile -> decompile produces valid Lisp (roundtrip)."""
    from fas4_decompiler import Fas4Parser, Disassembler, \
        ControlFlowAnalyzer, LispGenerator
    from validate import tokenize, parse_tokens, validate_ast

    src = '(defun hello () (princ "Hello, World!") (princ))'
    parser = Parser(src)
    program = parser.parse()

    symtab = SymbolTable()
    symtab.collect_symbols(program)

    codegen = CodeGenerator(symtab)
    from compiler.ast import Defun

    all_bc = BytecodeBuffer()
    func_offsets = {}

    for form in program.forms:
        if isinstance(form, Defun):
            offset = len(all_bc.data)
            fb, _ = codegen.generate_function(form)
            func_offsets[form.name] = offset
            all_bc.emit(fb)

    for name, offset in func_offsets.items():
        symtab.add_func_ref(name, offset)

    seg0 = bytes(all_bc.data)
    resource = ResourceBuilder(symtab)
    seg1 = resource.build(func_offsets)

    with tempfile.NamedTemporaryFile(suffix='.fas', delete=False) as f:
        fas_path = f.name
        writer = FasWriter(symtab)
        writer.write(fas_path, seg0, seg1)

    try:
        decomp_parser = Fas4Parser()
        fas = decomp_parser.parse(fas_path)
        disasm = Disassembler()
        instructions = disasm.disassemble(fas.bytecode, fas.nsyms)
        cfa = ControlFlowAnalyzer(instructions, fas.function_catalog)
        functions = cfa.find_functions()
        gen = LispGenerator(fas)
        result = gen.generate(functions, fas_path)

        assert '(defun hello ()' in result
        assert '(princ "Hello, World!")' in result

        tokens, errs = tokenize(result)
        assert not errs, f"Tokenization failed: {errs}"
        forms, errs = parse_tokens(tokens)
        assert not errs, f"Parsing failed: {errs}"
        errs = validate_ast(forms, result)
        assert not errs, f"Validation failed: {errs}"
    finally:
        os.unlink(fas_path)


def test_multi_setq():
    """Multi-value setq compiles correctly."""
    src = '(defun foo () (setq a 1 b 2 c 3) (+ a b c))'
    data = _compile_to_fas(src)
    assert data.startswith(FAS4_MAGIC)
    assert SEG_TERMINATOR in data
