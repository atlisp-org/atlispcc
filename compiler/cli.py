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


def _collect_builtins_for_stub(symtab, node):
    """stub 模式下将调用到的内建函数注册为符号槽（CAD stub 用符号槽编址调用）。"""
    from compiler.ast import (
        Call, Defun, Setq, IfNode, WhileNode, ForeachNode,
        RepeatNode, Progn, ListExpr, QuotedExpr, LambdaNode, Cond, Symbol,
    )
    if isinstance(node, Defun):
        for expr in node.body:
            _collect_builtins_for_stub(symtab, expr)
    elif isinstance(node, Call):
        if symtab.is_builtin(node.name) and node.name not in ('T', 'nil'):
            symtab.get_or_add(node.name)
        for a in node.args:
            _collect_builtins_for_stub(symtab, a)
    elif isinstance(node, (Setq,)):
        for target, value in node.pairs:
            _collect_builtins_for_stub(symtab, target)
            if value:
                _collect_builtins_for_stub(symtab, value)
    elif isinstance(node, IfNode):
        for child in (node.cond, node.then, node.else_expr):
            if child:
                _collect_builtins_for_stub(symtab, child)
    elif isinstance(node, WhileNode):
        if node.cond:
            _collect_builtins_for_stub(symtab, node.cond)
        for expr in node.body:
            _collect_builtins_for_stub(symtab, expr)
    elif isinstance(node, ForeachNode):
        if node.list_expr:
            _collect_builtins_for_stub(symtab, node.list_expr)
        for expr in node.body:
            _collect_builtins_for_stub(symtab, expr)
    elif isinstance(node, RepeatNode):
        if node.count:
            _collect_builtins_for_stub(symtab, node.count)
        for expr in node.body:
            _collect_builtins_for_stub(symtab, expr)
    elif isinstance(node, Progn):
        for form in node.forms:
            _collect_builtins_for_stub(symtab, form)
    elif isinstance(node, Cond):
        for clause in node.clauses:
            for item in clause:
                _collect_builtins_for_stub(symtab, item)
    elif isinstance(node, ListExpr):
        for item in node.items:
            _collect_builtins_for_stub(symtab, item)
    elif isinstance(node, QuotedExpr):
        if node.expr:
            _collect_builtins_for_stub(symtab, node.expr)
    elif isinstance(node, LambdaNode):
        for expr in node.body:
            _collect_builtins_for_stub(symtab, expr)


def _patch_usubr_idx(seg0: bytes, seg1: bytes, symtab, nsyms: int, func_args=None) -> bytes:
    """修正 stub 字节码的 USUBR 与参数槽索引为 CAD 的 gvar 槽 - 1。

    CAD 实测逆向：
    - USUBR 调用符号的 gvar 槽 = idx + 1（idx = gvar 槽 - 1）
    - 参数绑定/读取槽 = 参数符号的 gvar 槽 - 1（越界符号 gvar 槽假定 = nsyms）
    codegen 用占位生成，此处用资源段 GVARINIT 重建的 gvar 表修正。
    """
    try:
        from fas_core import build_mvar_tables
        rg, fg = build_mvar_tables(seg1, nsyms)
    except Exception:
        return seg0
    gvar_map: dict = {}
    for idx, v in enumerate(fg):
        if isinstance(v, tuple) and len(v) == 2 and v[0] in ("SYMBOL", "STRING"):
            gvar_map.setdefault(str(v[1]), idx)
    if not gvar_map:
        return seg0
    from fas4_decompiler import Disassembler
    try:
        insts = Disassembler(short_subr=True).disassemble(seg0, nsyms, sym_count=len(symtab.entries))
    except Exception:
        return seg0

    def gvar_slot(name: str) -> int:
        return gvar_map.get(name, nsyms)

    def sym_of(idx: int):
        if 0 <= idx < len(symtab.entries) and symtab.entries[idx][0] in ("SYMBOL", "STRING"):
            return str(symtab.entries[idx][1])
        return None

    out = bytearray()
    multi = bool(func_args) and len(func_args) > 1
    func_iter = iter(func_args or [])
    cur_args = None
    arg_i = 0
    for inst in insts:
        if inst.op_name == "DEFUN":
            cur_args = next(func_iter, None) if func_args else None
            arg_i = 0
        # 参数绑定 PUSH_G（DEFUN 后 argc 个，仅多函数）
        if multi and inst.op_name == "PUSH_G" and cur_args is not None and arg_i < len(cur_args):
            arg = cur_args[arg_i]
            new_idx = gvar_slot(arg) - 1
            if 0 <= new_idx <= 0xFFFF:
                out += bytes([0x09, new_idx & 0xFF, (new_idx >> 8) & 0xFF])
                arg_i += 1
                continue
        # 参数读取 PUSH_VALUE（槽 = nsyms-1-i，仅多函数）
        elif multi and inst.op_name == "PUSH_VALUE" and cur_args is not None and inst.operands:
            idx = inst.operands[0]
            i = nsyms - 1 - idx
            if 0 <= i < len(cur_args):
                arg = cur_args[i]
                new_idx = gvar_slot(arg) - 1
                if 0 <= new_idx <= 0xFFFF:
                    out += bytes([0x03, new_idx & 0xFF, (new_idx >> 8) & 0xFF])
                    continue
        # 其余符号引用（仅多函数）：统一用 gvar 槽 - 1
        if multi and inst.op_name in ("PUSH_VALUE", "PUSH_G", "SETQ_G") and inst.operands:
            sym = sym_of(inst.operands[0])
            if sym and sym in gvar_map:
                new_idx = gvar_map[sym] - 1
                if 0 <= new_idx <= 0xFFFF:
                    opcode = {"PUSH_VALUE": 0x03, "PUSH_G": 0x09, "SETQ_G": 0x06}[inst.op_name]
                    out += bytes([opcode, new_idx & 0xFF, (new_idx >> 8) & 0xFF])
                    continue
        elif inst.op_name == "USUBR" and len(inst.operands) >= 2:
            argc, idx = inst.operands[0], inst.operands[1]
            sym = sym_of(idx)
            if sym and sym in gvar_map:
                new_idx = gvar_map[sym] - 1
                out += bytes([0x35, argc & 0xFF, new_idx & 0xFF])
            else:
                out += seg0[inst.offset:inst.offset + inst.size]
            continue
        out += seg0[inst.offset:inst.offset + inst.size]
    return bytes(out)


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
    defun_forms = [f for f in program.forms if isinstance(f, Defun)]
    # 纯 &rest（min=0）：CAD 实测不收集 rest（b4=01 需至少一个必填参数）
    for f in defun_forms:
        if f.rest and not f.args and not f.optional:
            print(
                f"Warning: function '{f.name}' uses bare &rest (min args = 0); "
                f"CAD does not collect rest args for min=0 — consider adding "
                f"a required param, e.g. (defun {f.name} (x &rest {f.rest}))",
                file=sys.stderr,
            )
    from compiler.cad_symbols import derive_symbol_names
    for sym in derive_symbol_names(program):
        if sym.startswith('"') and sym.endswith('"'):
            symtab.add_string(sym[1:-1])
        elif sym in symtab.name_to_idx:
            # CAD stub：允许符号重复（递归/跨函数引用产生重复槽）
            symtab.add_force(sym)
        else:
            symtab.get_or_add(sym)

    codegen = CodeGenerator(symtab, stub_format=True,
                            defined_funcs=[f.name for f in defun_forms],
                            nsyms=len(symtab.entries) - len(defun_forms) + 1)

    all_bytecode = BytecodeBuffer()
    func_offsets = {}

    other_forms = [f for f in program.forms
                   if not isinstance(f, (Defun, Defpackage, InPackage))]

    for form in other_forms:
        codegen._emit_expr(all_bytecode, form)
        all_bytecode.emit(ENCODE_POP)

    for i, form in enumerate(defun_forms):
        offset = len(all_bytecode.data)
        func_bytecode, _ = codegen.generate_function(form)
        func_offsets[form.name] = offset
        all_bytecode.emit(func_bytecode)
        if i < len(defun_forms) - 1:
            # CAD stub: 函数间分隔符。有参函数 `<argc> 00 16`，无参函数 `16`。
            argc = len(form.args)
            sep = bytes([argc & 0xFF, 0x00, 0x16]) if argc > 0 else bytes([0x16])
            all_bytecode.emit(sep)

    for name, offset in func_offsets.items():
        symtab.add_func_ref(name, offset)

    all_bytecode.resolve()
    seg0 = bytes(all_bytecode.data)

    module_code = build_module_code(len(defun_forms))
    resource = ResourceBuilder(symtab)
    # nsyms = len(entries) - 函数数 + 1（CAD 实测：函数注册 GVARINIT st_init）
    fas_nsyms = len(symtab.entries) - len(defun_forms) + 1
    seg0_payload = f'{fas_nsyms} $'.encode() + seg0
    seg1 = resource.build(func_offsets, module_code=module_code, seg0_payload_len=len(seg0_payload), stub_format=True)
    sec2_items = count_resource_records(seg1)

    # 修正 USUBR/参数槽索引：CAD 用 `gvar 槽 - 1`（gvar 表由资源段 GVARINIT 建立）。
    def _all_params(f):
        return f.args + f.optional + ([f.rest] if f.rest else [])
    seg0 = _patch_usubr_idx(seg0, seg1, symtab, fas_nsyms, [_all_params(f) for f in defun_forms])

    output = output or source.replace('.lsp', '.fas')
    writer = FasWriter(symtab)
    first_argc = len(defun_forms[-1].args) if defun_forms else 0
    writer.write(output, seg0, seg1, sec2_items=sec2_items, first_argc=first_argc,
                 nsyms=fas_nsyms)
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
        cmd_compile(args.source, args.output, opt_level=args.O,
                    show_analysis=args.analyze)
        return 0

    if args.command in ('decompile', 'd'):
        cmd_decompile(args.source, args.output)
        return 0

    if args.command in ('disasm', 'disassemble'):
        cmd_disassemble(args.source, args.output)
        return 0

    if args.command in ('asm', 'assemble'):
        cmd_assemble(args.source, args.output)
        return 0

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
        cmd_link(args.inputs, output, args.verbose)
        return 0

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
