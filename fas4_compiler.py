#!/usr/bin/env python3
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from compiler.parser import Parser, ParseError
from compiler.symbol_table import SymbolTable
from compiler.codegen import CodeGenerator, BytecodeBuffer
from compiler.ast import Defun
from compiler.resource_builder import ResourceBuilder
from compiler.fas_writer import FasWriter


ENCODE_POP = bytes([0x0a])


def compile_lisp(source: str, output_path: str) -> str:
    parser = Parser(source)
    try:
        program = parser.parse()
    except ParseError as e:
        print(f'Parse error: {e}', file=sys.stderr)
        sys.exit(1)

    symtab = SymbolTable()
    symtab.collect_symbols(program)

    codegen = CodeGenerator(symtab)

    all_bytecode = BytecodeBuffer()
    func_offsets = {}

    defun_forms = [f for f in program.forms if isinstance(f, Defun)]
    other_forms = [f for f in program.forms if not isinstance(f, Defun)]

    for form in other_forms:
        codegen._emit_expr(all_bytecode, form)
        all_bytecode.emit(ENCODE_POP)

    for form in defun_forms:
        offset = len(all_bytecode.data)
        func_bytecode, _ = codegen.generate_function(form)
        func_offsets[form.name] = offset
        all_bytecode.emit(func_bytecode)

    for name, offset in func_offsets.items():
        symtab.add_func_ref(name, offset)

    seg0 = bytes(all_bytecode.data)

    resource = ResourceBuilder(symtab)
    seg1 = resource.build(func_offsets)

    writer = FasWriter(symtab)
    writer.write(output_path, seg0, seg1)

    return output_path


def main():
    if len(sys.argv) < 2:
        print('Usage: python fas4_compiler.py <input.lsp> [output.fas]')
        sys.exit(1)

    input_path = sys.argv[1]
    output_path = sys.argv[2] if len(sys.argv) > 2 else input_path.replace('.lsp', '.fas')

    with open(input_path, 'r', encoding='utf-8', errors='replace') as f:
        source = f.read()

    result = compile_lisp(source, output_path)
    print(f'Compiled to {result}')


if __name__ == '__main__':
    main()
