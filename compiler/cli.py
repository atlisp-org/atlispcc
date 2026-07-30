import sys
import os
import argparse

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from compiler.parser import Parser, ParseError
from compiler.symbol_table import SymbolTable
from compiler.codegen import CodeGenerator, BytecodeBuffer
from compiler.ast import Defun
from compiler.opt import optimize
from compiler.resource_builder import ResourceBuilder
from compiler.fas_writer import FasWriter
from compiler.linker import link_fas
from fas4_decompiler import Fas4Parser, Disassembler, ControlFlowAnalyzer, LispGenerator
from validate import validate_file


ENCODE_POP = bytes([0x0a])


def cmd_compile(source: str, output: str = '', opt_level: int = 0) -> str:
    parser_obj = Parser(source)
    try:
        program = parser_obj.parse()
    except ParseError as e:
        print(f'Parse error: {e}', file=sys.stderr)
        sys.exit(1)

    if opt_level:
        program = optimize(program, level=opt_level)

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

    output = output or source.replace('.lsp', '.fas')
    writer = FasWriter(symtab)
    writer.write(output, seg0, seg1)
    print(f'Compiled to {output}')
    return output


def cmd_decompile(source: str, output: str = '') -> str:
    parser_obj = Fas4Parser()
    fas = parser_obj.parse(source)
    disasm = Disassembler()
    instructions = disasm.disassemble(fas.bytecode, fas.nsyms)
    cfa = ControlFlowAnalyzer(instructions, fas.function_catalog)
    functions = cfa.find_functions()
    gen = LispGenerator(fas)
    result = gen.generate(functions, source)

    output = output or source.replace('.fas', '_decomp.lsp')
    with open(output, 'w', encoding='utf-8') as f:
        f.write(result)
    print(f'Decompiled to {output}')
    return output


def cmd_validate(source: str) -> int:
    import pathlib
    ok = validate_file(pathlib.Path(source))
    return 0 if ok else 1


def cmd_link(inputs: list, output: str, verbose: bool = False) -> str:
    return link_fas(inputs, output, verbose)


def main():
    parser = argparse.ArgumentParser(
        prog='atlispcc',
        description='FAS4 bytecode compiler/decompiler toolchain for AutoCAD/BricsCAD',
    )
    sub = parser.add_subparsers(dest='command', metavar='<command>')

    # compile
    p_compile = sub.add_parser('compile', aliases=['c'], help='Compile .lsp → .fas')
    p_compile.add_argument('source', help='input .lsp file')
    p_compile.add_argument('output', nargs='?', default='', help='output .fas file (optional)')
    p_compile.add_argument('-O', type=int, default=0, choices=[0, 1, 2],
                           help='optimization level (0=none, 1=basic, 2=aggressive)')

    # decompile
    p_decompile = sub.add_parser('decompile', aliases=['d'], help='Decompile .fas → .lsp')
    p_decompile.add_argument('source', help='input .fas file')
    p_decompile.add_argument('output', nargs='?', default='', help='output .lsp file (optional)')

    # validate
    p_validate = sub.add_parser('validate', aliases=['v'], help='Validate .lsp syntax')
    p_validate.add_argument('source', help='input .lsp file')

    # link
    p_link = sub.add_parser('link', help='Link multiple .fas files into one')
    p_link.add_argument('inputs', nargs='+', help='input .fas files (2 or more)')
    p_link.add_argument('-o', '--output', default='', help='output .fas file')
    p_link.add_argument('--verbose', '-v', action='store_true', help='verbose output')

    args = parser.parse_args()

    if args.command is None:
        parser.print_help()
        return 0

    if args.command in ('compile', 'c'):
        return cmd_compile(args.source, args.output, opt_level=args.O)

    if args.command in ('decompile', 'd'):
        return cmd_decompile(args.source, args.output)

    if args.command in ('validate', 'v'):
        return cmd_validate(args.source)

    if args.command == 'link':
        if len(args.inputs) < 2:
            print('Error: need at least 2 input .fas files to link', file=sys.stderr)
            return 1
        output = args.output
        if not output:
            base = args.inputs[-1].rsplit('.', 1)[0]
            output = f'{base}_linked.fas'
        return cmd_link(args.inputs, output, args.verbose)

    parser.print_help()
    return 1


if __name__ == '__main__':
    sys.exit(main() or 0)
