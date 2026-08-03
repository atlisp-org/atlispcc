import pytest
import os
import sys
import tempfile
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from compiler.parser import Parser
from compiler.symbol_table import SymbolTable
from compiler.codegen import CodeGenerator, BytecodeBuffer
from compiler.ast import Defun, Symbol, Call
from compiler.resource_builder import ResourceBuilder
from compiler.fas_writer import FasWriter
from decompiler.fas4_decompiler import Fas4Parser, Disassembler, ControlFlowAnalyzer, LispGenerator
from asm.opcodes import NAME_TO_OPCODE


def test_defpackage_inpackage():
    source = """
(defpackage vec (:export vec2))
(in-package vec)
(defun vec2 (x) (+ x 1))
"""
    parser = Parser(source)
    program = parser.parse()

    assert parser.packages.current_package == 'vec'
    assert 'vec' in parser.packages.packages
    assert 'vec2' in parser.packages.packages['vec'].exports

    for form in program.forms:
        if isinstance(form, Defun):
            assert form.name == 'vec|vec2'


def test_qualified_call():
    source = """
(defpackage vec (:export vec2))
(in-package app)
(defun foo (x) (vec:vec2 x))
"""
    parser = Parser(source)
    program = parser.parse()

    symtab = SymbolTable(package_table=parser.packages)
    symtab.collect_symbols(program)

    assert 'vec|vec2' in symtab.name_to_idx


def test_unqualified_defun_outside_package():
    source = """
(defun foo (x) (+ x 1))
"""
    parser = Parser(source)
    program = parser.parse()

    for form in program.forms:
        if isinstance(form, Defun):
            assert form.name == 'foo'


def test_compile_decompile_roundtrip_with_package():
    source = """
(defpackage vec (:export vec2))
(in-package vec)
(defun vec2 (x)
  (+ x 1))
"""
    parser = Parser(source)
    program = parser.parse()
    symtab = SymbolTable(package_table=parser.packages)
    symtab.collect_symbols(program)

    codegen = CodeGenerator(symtab)
    buf = BytecodeBuffer()

    for form in program.forms:
        if isinstance(form, Defun):
            offset = len(buf.data)
            bc, _ = codegen.generate_function(form)
            symtab.add_func_ref(form.name, offset)
            buf.emit(bc)

    seg0 = bytes(buf.data)
    resource = ResourceBuilder(symtab)
    seg1 = resource.build(symtab.function_offsets)

    with tempfile.NamedTemporaryFile(suffix='.fas', delete=False) as f:
        tmpname = f.name
    try:
        writer = FasWriter(symtab)
        writer.write(tmpname, seg0, seg1)

        fp = Fas4Parser()
        fas = fp.parse(tmpname)
        assert fas is not None

        disasm = Disassembler()
        instrs = disasm.disassemble(fas.bytecode, fas.nsyms)

        cfa = ControlFlowAnalyzer(instrs, fas.function_catalog)
        funcs = cfa.find_functions()

        gen = LispGenerator(fas)
        result = gen.generate(funcs, tmpname)

        assert 'vec|vec2' not in result
        assert 'vec2' in result.lower() or 'vec:vec2' in result
    finally:
        os.unlink(tmpname)
