import sys
import os
import argparse

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from compiler.parser import Parser, ParseError
from compiler.symbol_table import SymbolTable
from compiler.codegen import CodeGenerator, BytecodeBuffer
from compiler.ast import Defun, Defpackage, InPackage
from compiler.opt import optimize
from compiler.resource_builder import ResourceBuilder, build_module_code, count_resource_records
from compiler.fas_writer import FasWriter
from compiler.analyzer import analyze
from compiler.linker import link_fas
from compiler.vlx_builder import build_vlx
from fas4_decompiler import Fas4Parser, Disassembler, ControlFlowAnalyzer, LispGenerator, is_compact_stub
from validate import validate_file


ENCODE_POP = bytes([0x0a])


def cmd_compile(source: str, output: str = '', opt_level: int = 0, show_analysis: bool = False) -> str:
    if os.path.exists(source):
        with open(source, 'r', encoding='utf-8') as f:
            source_code = f.read()
    else:
        source_code = source
    parser_obj = Parser(source_code)
    try:
        program = parser_obj.parse()
    except ParseError as e:
        print(f'Parse error: {e}', file=sys.stderr)
        sys.exit(1)

    package_table = parser_obj.packages

    if show_analysis:
        stats = analyze(program)
        print('=== Compilation Analysis ===')
        print(f'  Functions:               {stats["functions"]}')
        print(f'  Top-level forms:         {stats["top_level_forms"]}')
        print(f'  Total instructions:      {stats["total_instructions"]}')
        print(f'  Constants (estimate):    {stats["constants_estimate"]}')
        print(f'  Symbol table entries:    {stats["symbol_table_entries"]}')
        print(f'  Function offsets:        {stats["function_offsets"]}')
        print(f'  Locals (total):          {stats["locals"]}')
        print(f'  Tail-recursive:          {stats["tail_recursive_functions"]}')
        print(f'  External/builtin calls:  {len(stats["builtin_calls"])}')
        for fd in stats['functions_detail']:
            tr = ' [tail-recursive]' if fd['tail_recursive'] else ''
            print(f'    {fd["name"]}: {fd["instructions"]} instr, '
                  f'{fd["args"]} args, {fd["locals"]} locals, '
                  f'calls {fd["calls"]}{tr}')
        print()

    if opt_level:
        program = optimize(program, level=opt_level)
        if show_analysis:
            stats2 = analyze(program)
            print(f'=== After O{opt_level} Optimization ===')
            print(f'  Functions:          {stats2["functions"]} (was {stats["functions"]})')
            print(f'  Instructions:       {stats2["total_instructions"]} (was {stats["total_instructions"]})')
            print(f'  Tail-recursive:     {stats2["tail_recursive_functions"]}')
            print()

    symtab = SymbolTable(package_table=package_table)
    symtab.collect_symbols(program)

    codegen = CodeGenerator(symtab)

    all_bytecode = BytecodeBuffer()
    func_offsets = {}

    defun_forms = [f for f in program.forms if isinstance(f, Defun)]
    other_forms = [f for f in program.forms
                   if not isinstance(f, (Defun, Defpackage, InPackage))]

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

    module_code = build_module_code()
    resource = ResourceBuilder(symtab)
    seg1 = resource.build(func_offsets, module_code=module_code)
    sec2_items = count_resource_records(seg1)

    output = output or source.replace('.lsp', '.fas')
    writer = FasWriter(symtab)
    writer.write(output, seg0, seg1, sec2_items=sec2_items)
    print(f'Compiled to {output}')
    return output


def cmd_decompile(source: str, output: str = '') -> str:
    parser_obj = Fas4Parser()
    fas = parser_obj.parse(source)
    disasm = Disassembler(short_subr=is_compact_stub(fas.bytecode, fas.function_catalog))
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


def cmd_disassemble(source: str, output: str = '') -> str:
    """反汇编 .fas → .lasm（字节码指令列表）。"""
    from compiler.assembler import disassemble_fas
    text = disassemble_fas(source)
    output = output or source.replace('.fas', '.lasm')
    with open(output, 'w', encoding='utf-8') as f:
        f.write(text)
    print(f'Disassembled to {output}')
    return output


def cmd_assemble(source: str, output: str = '') -> str:
    """汇编 .lasm → .fas。"""
    from compiler.assembler import assemble_lasm
    with open(source, 'r', encoding='utf-8') as f:
        text = f.read()
    output = output or source.replace('.lasm', '.fas')
    assemble_lasm(text, output)
    print(f'Assembled to {output}')
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
        description='FAS4 bytecode compiler/decompiler toolchain for AutoLISP-compatible CAD platforms',
    )
    sub = parser.add_subparsers(dest='command', metavar='<command>')

    # compile
    p_compile = sub.add_parser('compile', aliases=['c'], help='Compile .lsp → .fas')
    p_compile.add_argument('source', help='input .lsp file')
    p_compile.add_argument('output', nargs='?', default='', help='output .fas file (optional)')
    p_compile.add_argument('-O', type=int, default=0, choices=[0, 1, 2, 3],
                           help='optimization level (0=none, 1=basic, 2=aggressive, 3=extreme)')
    p_compile.add_argument('--analyze', action='store_true',
                           help='show compilation analysis report')

    # decompile
    p_decompile = sub.add_parser('decompile', aliases=['d'], help='Decompile .fas → .lsp')
    p_decompile.add_argument('source', help='input .fas file')
    p_decompile.add_argument('output', nargs='?', default='', help='output .lsp file (optional)')

    # validate
    p_validate = sub.add_parser('validate', aliases=['v'], help='Validate .lsp syntax')
    p_validate.add_argument('source', help='input .lsp file')

    # disassemble: .fas → .lasm
    p_disasm = sub.add_parser('disasm', aliases=['disassemble'],
                              help='Disassemble .fas → .lasm (bytecode instructions)')
    p_disasm.add_argument('source', help='input .fas file')
    p_disasm.add_argument('output', nargs='?', default='', help='output .lasm file (optional)')

    # assemble: .lasm → .fas
    p_asm = sub.add_parser('asm', aliases=['assemble'],
                           help='Assemble .lasm → .fas')
    p_asm.add_argument('source', help='input .lasm file')
    p_asm.add_argument('output', nargs='?', default='', help='output .fas file (optional)')

    # link
    p_link = sub.add_parser('link', help='Link multiple .fas files into one')
    p_link.add_argument('inputs', nargs='+', help='input .fas files (2 or more)')
    p_link.add_argument('-o', '--output', default='', help='output .fas file')
    p_link.add_argument('--verbose', '-v', action='store_true', help='verbose output')

    # build-vlx
    p_vlx = sub.add_parser('build-vlx', help='Build VLX container from .fas files')
    p_vlx.add_argument('inputs', nargs='+', help='input .fas files')
    p_vlx.add_argument('-o', '--output', default='', help='output .vlx file')
    p_vlx.add_argument('--export', nargs='*', default=[],
                       help='exported function names for namespace isolation')
    p_vlx.add_argument('--package', default='',
                       help='VLX package/application name')

    args = parser.parse_args()

    if args.command is None:
        parser.print_help()
        return 0

    if args.command in ('compile', 'c'):
        return cmd_compile(args.source, args.output, opt_level=args.O,
                           show_analysis=args.analyze)

    if args.command in ('decompile', 'd'):
        return cmd_decompile(args.source, args.output)

    if args.command in ('disasm', 'disassemble'):
        return cmd_disassemble(args.source, args.output)

    if args.command in ('asm', 'assemble'):
        return cmd_assemble(args.source, args.output)

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

    if args.command == 'build-vlx':
        output = args.output
        if not output:
            base = args.inputs[-1].rsplit('.', 1)[0]
            output = f'{base}.vlx'
        result = build_vlx(args.inputs, output,
                           exports=args.export,
                           package_name=args.package)
        print(f'Built {result}')
        return 0

    parser.print_help()
    return 1


if __name__ == '__main__':
    sys.exit(main() or 0)
