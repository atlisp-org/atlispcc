import pytest
import os
import sys
import tempfile
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from compiler.parser import Parser
from compiler.symbol_table import SymbolTable
from compiler.codegen import CodeGenerator, BytecodeBuffer
from compiler.ast import Defun
from compiler.resource_builder import ResourceBuilder
from compiler.fas_writer import FasWriter
from compiler.vlx_builder import build_vlx, VlxBuilder, _VLX_MAGIC


def test_vlx_basic_structure():
    builder = VlxBuilder()
    builder.add_file('test.txt', b'hello')
    builder.add_file('data.bin', b'\x01\x02\x03\x04')

    with tempfile.NamedTemporaryFile(suffix='.vlx', delete=False) as f:
        tmpname = f.name
    try:
        builder.build(tmpname)

        with open(tmpname, 'rb') as f:
            data = f.read()

        assert data[:12] == _VLX_MAGIC
        entry_count = int.from_bytes(data[12:16], 'little')
        assert entry_count == 2
    finally:
        os.unlink(tmpname)


def test_vlx_build_with_fas():
    source = """
(defpackage vec (:export vec2))
(in-package vec)
(defun vec2 (x) (+ x 1))
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
        fas_path = f.name
    try:
        writer = FasWriter(symtab)
        writer.write(fas_path, seg0, seg1)

        vlx_path = fas_path.replace('.fas', '.vlx')
        try:
            result = build_vlx([fas_path], vlx_path,
                              exports=['vec2'],
                              package_name='vec')

            assert os.path.exists(result)
            assert result == vlx_path

            with open(vlx_path, 'rb') as f:
                data = f.read()
            assert data[:12] == _VLX_MAGIC
        finally:
            if os.path.exists(vlx_path):
                os.unlink(vlx_path)
    finally:
        os.unlink(fas_path)


def test_vlx_make_vlx_code():
    from compiler.vlx_builder import _make_vlx_code
    code = _make_vlx_code(['foo', 'bar'], ['app.fas', 'lib.fas'])
    text = code.decode('utf-8')
    assert "(vl-doc-export 'foo)" in text
    assert "(vl-doc-export 'bar)" in text
    assert '(load "app")' in text
    assert '(load "lib")' in text
