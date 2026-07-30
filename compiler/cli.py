import sys
import os
import argparse

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from compiler.parser import Parser, ParseError
from compiler.symbol_table import SymbolTable
from compiler.codegen import CodeGenerator, BytecodeBuffer
from compiler.ast import Defun
from compiler.resource_builder import ResourceBuilder
from compiler.fas_writer import FasWriter
from fas4_decompiler import Fas4Parser, Disassembler, ControlFlowAnalyzer, LispGenerator
from compiler.validate import validate_file


ENCODE_POP = bytes([0x0a])


def cmd_compile(args):
    parser = Parser(args.source)
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

    output = args.output or args.source.replace('.lsp', '.fas')
    writer = FasWriter(symtab)
    writer.write(output, seg0, seg1)
    print(f'Compiled to {output}')
    return output


def cmd_decompile(args):
    parser = Fas4Parser()
    fas = parser.parse(args.source)
    disasm = Disassembler()
    instructions = disasm.disassemble(fas.bytecode, fas.nsyms)
    cfa = ControlFlowAnalyzer(instructions, fas.function_catalog)
    functions = cfa.find_functions()
    gen = LispGenerator(fas)
    result = gen.generate(functions, args.source)

    output = args.output or args.source.replace('.fas', '_decomp.lsp')
    with open(output, 'w', encoding='utf-8') as f:
        f.write(result)
    print(f'Decompiled to {output}')
    return output


def cmd_validate(args):
    import pathlib
    ok = validate_file(pathlib.Path(args.source))
    return 0 if ok else 1


def main():
    if len(sys.argv) == 1:
        print('atlispcc - FAS4 bytecode compiler/decompiler toolchain')
        print()
        print('Usage:')
        print('  atlispcc compile <input.lsp> [output.fas]')
        print('  atlispcc decompile <input.fas> [output.lsp]')
        print('  atlispcc validate <input.lsp>')
        print()
        print('Short form (defaults to compile):')
        print('  atlispcc <input.lsp> [output.fas]')
        sys.exit(0)

    if sys.argv[1] in ('compile', 'decompile', 'validate'):
        subcmd = sys.argv[1]
        source = sys.argv[2] if len(sys.argv) > 2 else None
        if not source:
            print(f'Usage: atlispcc {subcmd} <input> [output]')
            sys.exit(1)
        output = sys.argv[3] if len(sys.argv) > 3 else None

        if subcmd == 'compile':
            cmd_compile(type('Args', (), {'source': source, 'output': output})())
        elif subcmd == 'decompile':
            cmd_decompile(type('Args', (), {'source': source, 'output': output})())
        elif subcmd == 'validate':
            cmd_validate(type('Args', (), {'source': source})())
    else:
        source = sys.argv[1]
        output = sys.argv[2] if len(sys.argv) > 2 else None
        cmd_compile(type('Args', (), {'source': source, 'output': output})())


if __name__ == '__main__':
    main()
