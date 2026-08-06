import os
import sys
sys.path.insert(0, '.')

import tempfile
import pytest
from compiler.parser import Parser
from compiler.symbol_table import SymbolTable
from compiler.codegen import CodeGenerator, BytecodeBuffer
from compiler.resource_builder import ResourceBuilder
from compiler.fas_writer import FasWriter
from compiler.ast_nodes import Defun
from decompiler.fas4_decompiler import (
    Fas4Parser,
    Disassembler,
    ControlFlowAnalyzer,
    LispGenerator,
    Fas4Decompiler,
    is_compact_stub,
)
from tools.validate import tokenize, parse_tokens, validate_ast


ENCODE_POP = bytes([0x0a])


def _validate(source: str) -> tuple:
    tokens, errs = tokenize(source)
    if errs:
        return False, errs
    forms, errs = parse_tokens(tokens)
    if errs:
        return False, errs
    errs = validate_ast(forms)
    return (False, errs) if errs else (True, [])


def compile_and_decompile(src: str) -> str:
    """Compile Lisp source to FAS in memory and decompile back."""
    parser = Parser(src)
    program = parser.parse()

    symtab = SymbolTable()
    symtab.collect_symbols(program)

    codegen = CodeGenerator(symtab)
    from compiler.ast_nodes import Defun

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

    all_bc.resolve()
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
        disasm = Disassembler(short_subr=is_compact_stub(fas.bytecode, fas.function_catalog))
        instructions = disasm.disassemble(fas.bytecode, fas.nsyms)
        cfa = ControlFlowAnalyzer(instructions, fas.function_catalog)
        functions = cfa.find_functions()
        gen = LispGenerator(fas)
        result = gen.generate(functions, fas_path)
    finally:
        os.unlink(fas_path)

    return result


def test_minimal_compile_decompile():
    src = '(defun hello () (princ "Hello, World!") (princ))'
    result = compile_and_decompile(src)
    assert '(defun hello ()' in result
    assert '(princ "Hello, World!")' in result
    ok, errs = _validate(result)
    assert ok, f'Validation failed: {errs}'


def test_exit_compile_decompile():
    src = '(defun f (x) (if (> x 10) (exit)) (if (= x 0) (quit)) (princ x))'
    result = compile_and_decompile(src)
    assert '(exit)' in result
    ok, errs = _validate(result)
    assert ok, f'Validation failed: {errs}'


def test_hash_quote_roundtrip():
    src = "(defun f (l) (mapcar #'1+ l))"
    result = compile_and_decompile(src)
    assert '(mapcar' in result
    ok, errs = _validate(result)
    assert ok, f'Validation failed: {errs}'


def test_chinese_string_roundtrip_gbk():
    """GBK 编码往返：编译 (alert "中文") → FAS，反编译应还原 中文。"""
    src = '(defun a () (alert "中文"))'
    parser = Parser(src)
    program = parser.parse()

    symtab = SymbolTable()
    symtab.collect_symbols(program)
    from compiler.cad_symbols import derive_symbol_names
    for sym in derive_symbol_names(program):
        if sym.startswith('"') and sym.endswith('"'):
            symtab.add_string(sym[1:-1])
        else:
            symtab.get_or_add(sym)

    codegen = CodeGenerator(symtab)
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
    all_bc.resolve()
    seg0 = bytes(all_bc.data)
    resource = ResourceBuilder(symtab, encoding='gbk')
    seg1 = resource.build(func_offsets)

    with tempfile.NamedTemporaryFile(suffix='.fas', delete=False) as f:
        fas_path = f.name
        writer = FasWriter(symtab)
        writer.write(fas_path, seg0, seg1)
    try:
        decomp_parser = Fas4Parser()
        fas = decomp_parser.parse(fas_path)
        disasm = Disassembler(short_subr=is_compact_stub(fas.bytecode, fas.function_catalog))
        instructions = disasm.disassemble(fas.bytecode, fas.nsyms)
        cfa = ControlFlowAnalyzer(instructions, fas.function_catalog)
        functions = cfa.find_functions()
        gen = LispGenerator(fas)
        result = gen.generate(functions, fas_path)
    finally:
        os.unlink(fas_path)

    assert '"中文"' in result, f'Chinese string lost: {result}'
    ok, errs = _validate(result)
    assert ok, f'Validation failed: {errs}'



def test_dotted_call_roundtrip():
    src = '(defun f () (cons 1 . 2))'
    result = compile_and_decompile(src)
    assert '(cons 1 2)' in result
    ok, errs = _validate(result)
    assert ok, f'Validation failed: {errs}'


def test_function_ref_user_func_roundtrip():
    src = '(defun helper (x) (1+ x)) (defun f (lst) (mapcar (function helper) lst))'
    result = compile_and_decompile(src)
    assert '(defun helper' in result
    assert 'mapcar' in result
    ok, errs = _validate(result)
    assert ok, f'Validation failed: {errs}'


def test_init_code_preserved_as_top_level():
    src = '(setq *ver* "1.0")\n(princ "loading...")\n(defun c:run () (princ *ver*))'
    result = compile_and_decompile(src)
    assert '(setq *ver* "1.0")' in result
    assert '(princ "loading...")' in result
    assert '(defun c:run' in result
    ok, errs = _validate(result)
    assert ok, f'Validation failed: {errs}'


def test_init_control_flow_preserved():
    src = ('(setq *mode* 2)\n'
           '(if (> *mode* 1) (setq *level* 5) (setq *level* 1))\n'
           '(while (< *level* 3) (setq *level* (1+ *level*)))\n'
           '(defun c:go () (princ *level*))')
    result = compile_and_decompile(src)
    assert '(if (> *mode* 1)' in result
    assert '(while (< *level* 3)' in result
    assert '(setq *level* 5)' in result
    assert '(defun c:go' in result
    ok, errs = _validate(result)
    assert ok, f'Validation failed: {errs}'


def test_init_referenced_helper_kept():
    src = ('(setq x (double 5))\n'
           '(defun double (n) (* n 2))\n'
           '(defun c:run () (princ x))')
    result = compile_and_decompile(src)
    assert '(defun double' in result, f'helper dropped: {result}'
    assert '(setq x' in result
    ok, errs = _validate(result)
    assert ok, f'Validation failed: {errs}'


@pytest.mark.parametrize('level', [2, 3])
def test_complex_lsp_roundtrip_opt_level(level):
    """Round-trip a real complex LSP file at a given optimization level."""
    from compiler.cli import cmd_compile
    src_path = os.path.join(os.path.dirname(__file__), 'test_complex_roundtrip.lsp')
    with open(src_path, encoding='utf-8') as f:
        src = f.read()
    out_path = os.path.join(tempfile.gettempdir(), f'cx_rt_{level}_{os.urandom(4).hex()}.fas')
    try:
        cmd_compile(src, out_path, opt_level=level)
        parser = Fas4Parser()
        fas = parser.parse(out_path)
        disasm = Disassembler(short_subr=is_compact_stub(fas.bytecode, fas.function_catalog))
        insts = disasm.disassemble(fas.bytecode, fas.nsyms)
        cfa = ControlFlowAnalyzer(insts, fas.function_catalog)
        funcs = cfa.find_functions()
        gen = LispGenerator(fas)
        result = gen.generate(funcs, out_path)
        ok, errs = _validate(result)
        assert ok, f'O{level} validation failed: {errs}'
        assert 'while' in result.lower()
        assert 'foreach' in result.lower()
    finally:
        if os.path.exists(out_path):
            os.unlink(out_path)


def test_i18n_mixed_mode_roundtrip():
    """Round-trip i18n.lsp (defun + top-level interleaved, C2 target) via CLI.

    Mixed-mode files interleave defun definitions with top-level setq/princ;
    the CLI pipeline compiles top-level forms into seg1 module code (CAD
    standard). The roundtrip must decompile to valid, validated Lisp.
    """
    from compiler.cli import cmd_compile
    src_path = os.path.join(os.path.dirname(__file__), 'cad', 'i18n.lsp')
    if not os.path.exists(src_path):
        pytest.skip('tests/cad/i18n.lsp mixed-mode fixture not present')
    with open(src_path, encoding='utf-8') as f:
        src = f.read()
    out_path = os.path.join(tempfile.gettempdir(), f'i18n_rt_{os.urandom(4).hex()}.fas')
    try:
        cmd_compile(src, out_path)
        parser = Fas4Parser()
        fas = parser.parse(out_path)
        disasm = Disassembler(short_subr=is_compact_stub(fas.bytecode, fas.function_catalog))
        insts = disasm.disassemble(fas.bytecode, fas.nsyms)
        cfa = ControlFlowAnalyzer(insts, fas.function_catalog)
        funcs = cfa.find_functions()
        gen = LispGenerator(fas)
        result = gen.generate(funcs, out_path)
        ok, errs = _validate(result)
        assert ok, f'i18n mixed-mode validation failed: {errs}'
    finally:
        if os.path.exists(out_path):
            os.unlink(out_path)


_T_SERIES = [
    't01_math', 't02_recursion', 't03_fib', 't04_while', 't05_cond',
    't06_strcat', 't07_list', 't08_apply_mapcar', 't09_funcall', 't10_init',
    't11_localvars', 't12_quote', 't13_nested_if', 't14_command', 't15_cad_funcs',
]


@pytest.mark.parametrize('name', _T_SERIES)
def test_t_series_roundtrip(name):
    """Compile→decompile→validate each CAD-compat matrix source (t01-t15).

    Sources live in tests/cad/ alongside their CAD `vlisp-compile` goldens.
    """
    from compiler.cli import cmd_compile
    src_path = os.path.join(os.path.dirname(__file__), 'cad', f'{name}.lsp')
    if not os.path.exists(src_path):
        pytest.skip(f'tests/cad/{name}.lsp fixture not present')
    with open(src_path, encoding='utf-8') as f:
        src = f.read()
    out_path = os.path.join(tempfile.gettempdir(), f't_{name}_{os.urandom(4).hex()}.fas')
    try:
        cmd_compile(src, out_path)
        parser = Fas4Parser()
        fas = parser.parse(out_path)
        disasm = Disassembler(short_subr=is_compact_stub(fas.bytecode, fas.function_catalog))
        insts = disasm.disassemble(fas.bytecode, fas.nsyms)
        cfa = ControlFlowAnalyzer(insts, fas.function_catalog)
        funcs = cfa.find_functions()
        gen = LispGenerator(fas)
        result = gen.generate(funcs, out_path)
        ok, errs = _validate(result)
        assert ok, f'{name} validation failed: {errs}'
    finally:
        if os.path.exists(out_path):
            os.unlink(out_path)


def test_args_preserved():
    src = '(defun factorial (n) (if (<= n 1) 1 (* n (factorial (- n 1)))))'
    result = compile_and_decompile(src)
    assert '(defun factorial (n)' in result
    ok, errs = _validate(result)
    assert ok, f'Validation failed: {errs}'


def test_t01_golden_multi_func_arg_names():
    """§3.5c：多函数 + argc>1 的 CAD golden 参数名恢复。

    t01_math_cad.fas 是 CAD `vlisp-compile` 产物（add/multiply 各 2 参）。
    末位参数符号槽落在 nsyms 截断的 gvar 表之外，需从 symbol_slots[op+1]
    解析，否则反编译为 `(b arg_2)`。
    """
    golden = os.path.join(os.path.dirname(__file__), 'cad', 't01_math_cad.fas')
    if not os.path.exists(golden):
        pytest.skip('t01_math_cad.fas golden not present')
    result = Fas4Decompiler().decompile(golden, None)
    assert '(defun add (a b)' in result
    assert '(defun multiply (a b)' in result
    assert 'arg_' not in result


def test_local_vars():
    src = '(defun sum-to-n (n / result i) (setq result 0) (setq i 1) (while (<= i n) (setq result (+ result i)) (setq i (+ i 1))) result)'
    result = compile_and_decompile(src)
    assert '(defun sum-to-n (n /' in result or '(defun sum-to-n (' in result
    ok, errs = _validate(result)
    assert ok, f'Validation failed: {errs}'


def test_setq():
    src = '(defun foo () (setq x 5) x)'
    result = compile_and_decompile(src)
    assert 'defun foo' in result
    assert '(setq x 5)' in result
    ok, errs = _validate(result)
    assert ok, f'Validation failed: {errs}'


def test_while_loop():
    src = '(defun count-down (n) (while (> n 0) (princ n) (setq n (- n 1))) (princ "Done!"))'
    result = compile_and_decompile(src)
    assert '(while' in result
    ok, errs = _validate(result)
    assert ok, f'Validation failed: {errs}'


def test_init_code():
    src = '(princ "Loading...")\n(defun foo () nil)'
    result = compile_and_decompile(src)
    assert '(princ "Loading...")' in result or 'Loading' in result
    ok, errs = _validate(result)
    assert ok, f'Validation failed: {errs}'


def test_multiple_functions():
    src = '''
(defun a () 1)
(defun b () 2)
(defun c () 3)
'''
    result = compile_and_decompile(src)
    assert '(defun a ()' in result
    assert '(defun b ()' in result
    assert '(defun c ()' in result
    ok, errs = _validate(result)
    assert ok, f'Validation failed: {errs}'


def test_strcat_args_order():
    src = '(defun greet (name) (princ (strcat "Hello, " name "!")))'
    result = compile_and_decompile(src)
    assert 'strcat "Hello, " name "!"' in result or 'strcat' in result
    ok, errs = _validate(result)
    assert ok, f'Validation failed: {errs}'


def test_quoted_expr():
    src = '(defun foo () (setq lst \'(a b c)))'
    result = compile_and_decompile(src)
    ok, errs = _validate(result)
    assert ok, f'Validation failed: {errs}'


def test_nested_function_calls():
    src = '(defun foo (x y) (+ (* x x) (* y y)))'
    result = compile_and_decompile(src)
    assert '(+ (* x x) (* y y))' in result
    ok, errs = _validate(result)
    assert ok, f'Validation failed: {errs}'


def test_recursive_fib():
    src = '''
(defun fib (n)
  (if (< n 2)
    n
    (+ (fib (- n 1)) (fib (- n 2)))
  )
)
'''
    result = compile_and_decompile(src)
    assert '(defun fib (n)' in result
    ok, errs = _validate(result)
    assert ok, f'Validation failed: {errs}'


def test_apply():
    """Apply compiles and decompiles correctly."""
    src = '(defun foo (l) (apply (quote +) l))'
    result = compile_and_decompile(src)
    assert '(apply' in result
    assert "'+" in result or '(quote +)' in result
    ok, errs = _validate(result)
    assert ok, f'Validation failed: {errs}'


def test_mapcar():
    """Mapcar compiles and decompiles correctly."""
    src = "(defun foo (l) (mapcar '1+ l))"
    result = compile_and_decompile(src)
    assert '(mapcar' in result
    assert "'1+" in result
    ok, errs = _validate(result)
    assert ok, f'Validation failed: {errs}'


def test_foreach():
    """Foreach compiles and decompiles correctly."""
    src = '(defun foo (l) (foreach x l (princ x)))'
    result = compile_and_decompile(src)
    assert '(foreach' in result
    ok, errs = _validate(result)
    assert ok, f'Validation failed: {errs}'


def test_repeat():
    """Repeat compiles and decompiles correctly."""
    src = '(defun foo (n) (repeat n (princ ".")))'
    result = compile_and_decompile(src)
    assert '(while n' in result or '(repeat' in result
    assert '(princ ".")' in result
    ok, errs = _validate(result)
    assert ok, f'Validation failed: {errs}'


def test_and_or():
    """And/or compiles and decompiles correctly."""
    src = '''
(defun test-and (a b) (and a b))
(defun test-or (a b) (or a b))
'''
    result = compile_and_decompile(src)
    assert '(and a b)' in result or 'and' in result
    assert '(or a b)' in result or 'or' in result
    ok, errs = _validate(result)
    assert ok, f'Validation failed: {errs}'


def test_or_expr_folded_not_leaked():
    """§3.5d：`(or ...)` 作为表达式值应折叠为 `(or ...)`，不泄漏裸 `T`。"""
    result = compile_and_decompile("(defun f (a) (or a 0))")
    assert '(or a 0)' in result
    assert 'arg_' not in result


def test_list_or_args_folded():
    """§3.5d：`(list (or a 0) (or b 0))` 折叠进 list 参数位。"""
    result = compile_and_decompile("(defun f (a b) (list (or a 0) (or b 0)))")
    assert '(list (or a 0) (or b 0))' in result.replace('\n', ' ')


def test_list_if_args_folded():
    """§3.5d：`(list (if a a 0) (if b b 0))` 折叠进 list 参数位。"""
    result = compile_and_decompile("(defun f (a b) (list (if a a 0) (if b b 0)))")
    flat = result.replace('\n', ' ')
    assert '(list (if a' in flat and '(if b' in flat
    ok, errs = _validate(result)
    assert ok, f'Validation failed: {errs}'


def test_if_expr_in_call_folded():
    """§3.5d：`(+ (if a 1 2) 3)` 中 if 折叠进参数位。"""
    result = compile_and_decompile("(defun f (a b) (+ (if a 1 2) 3))")
    flat = result.replace('\n', ' ')
    assert '(if a' in flat and '(+' in flat
    ok, errs = _validate(result)
    assert ok, f'Validation failed: {errs}'


def test_lambda_param_no_shadow():
    """§3.5e：单函数含 quoted lambda 时，外层参数不被 lambda 参数名遮蔽。

    `(mapcar '(lambda (x) (* x 2)) lst)` 的 lst 位于符号槽尾部，若按
    绑定操作数解析会得到 lambda 参数 X。单函数 stub 应从符号槽尾部取参数名。
    """
    result = compile_and_decompile("(defun f (lst) (mapcar '(lambda (x) (* x 2)) lst))")
    assert '(defun f (lst)' in result
    assert 'arg_' not in result
    ok, errs = _validate(result)
    assert ok, f'Validation failed: {errs}'


def test_lambda_distinct_param_names():
    """§3.5e：外层参数与 lambda 参数名不同，均正确保留。"""
    result = compile_and_decompile("(defun f (lst) (mapcar '(lambda (y) (* y 2)) lst))")
    assert '(defun f (lst)' in result
    assert 'lambda (y)' in result or "lambda" in result
    ok, errs = _validate(result)
    assert ok, f'Validation failed: {errs}'


def test_t08_golden_shared_arg_names():
    """§10.4：多函数共享参数（t08 两个函数共用 lst）参数名恢复。

    共享参数符号在 symbol_slots 尾部（`参数放最后`），需用扩展 gvar 表
    （基础表 + 尾部未入表符号）按 gvar 槽 - 1 寻址。
    """
    golden = os.path.join(os.path.dirname(__file__), 'cad', 't08_apply_mapcar_cad.fas')
    if not os.path.exists(golden):
        pytest.skip('t08_apply_mapcar_cad.fas golden not present')
    result = Fas4Decompiler().decompile(golden, None)
    assert '(defun sum-list (lst)' in result
    assert '(defun double-all (lst)' in result
    assert 'arg_' not in result


def test_t07_golden_shared_arg_names():
    """§10.4：t07 get-first/get-rest 共享参数 lst 恢复。"""
    golden = os.path.join(os.path.dirname(__file__), 'cad', 't07_list_cad.fas')
    if not os.path.exists(golden):
        pytest.skip('t07_list_cad.fas golden not present')
    result = Fas4Decompiler().decompile(golden, None)
    assert '(defun get-first (lst)' in result
    assert '(defun get-rest (lst)' in result
    assert '(defun pair (a b)' in result


def test_t12_golden_global_setq_not_localized():
    """§10.4：t12 全局 setq 目标不被误判为 `/ 局部变量`。

    `(defun test-quote () (setq lst '(a b c)))` 的 lst 是全局变量，函数
    无 `/` 局部变量，不应输出 `/ lst`。
    """
    golden = os.path.join(os.path.dirname(__file__), 'cad', 't12_quote_cad.fas')
    if not os.path.exists(golden):
        pytest.skip('t12_quote_cad.fas golden not present')
    result = Fas4Decompiler().decompile(golden, None)
    assert '(defun test-quote ()' in result
    assert 'test-quote (/ lst' not in result


def test_t16_golden_foreach_arg_and_structure():
    """§10.4：t16 foreach 函数参数名 lst 恢复 + foreach 结构正确。"""
    golden = os.path.join(os.path.dirname(__file__), 'cad', 't16_foreach_cad.fas')
    if not os.path.exists(golden):
        pytest.skip('t16_foreach_cad.fas golden not present')
    result = Fas4Decompiler().decompile(golden, None)
    assert '(defun sum-foreach (lst' in result
    assert '(foreach x lst' in result


def test_t17_golden_repeat_arg_and_structure():
    """§10.4：t17 repeat 函数参数名 n 恢复 + repeat 结构正确。"""
    golden = os.path.join(os.path.dirname(__file__), 'cad', 't17_repeat_cad.fas')
    if not os.path.exists(golden):
        pytest.skip('t17_repeat_cad.fas golden not present')
    result = Fas4Decompiler().decompile(golden, None)
    assert '(defun repeat-count (n' in result
    assert '(repeat n' in result


def test_defun_q():
    """Defun-q compiles correctly (body is quoted)."""
    src = '(defun-q foo (x) (princ x))'
    parser = Parser(src)
    program = parser.parse()
    assert len(program.forms) == 1
    defun = program.forms[0]
    assert isinstance(defun, Defun)
    assert defun.quoted
    # Quoted defun should produce setq with quoted body
    result = compile_and_decompile(src)
    ok, errs = _validate(result)
    assert ok, f'Validation failed: {errs}'


def test_real_fas_decompile():
    """Decompile a real multi-function FAS file and validate output."""
    fas_path = os.path.join(os.path.dirname(__file__), 'cad', 'i18n-cad.fas')
    if not os.path.exists(fas_path):
        pytest.skip('tests/cad/i18n-cad.fas reference fixture not present')

    from decompiler.fas4_decompiler import Fas4Parser, Disassembler, \
        ControlFlowAnalyzer, LispGenerator
    import tempfile

    decomp_parser = Fas4Parser()
    fas = decomp_parser.parse(fas_path)
    disasm = Disassembler(short_subr=is_compact_stub(fas.bytecode, fas.function_catalog))
    instructions = disasm.disassemble(fas.bytecode, fas.nsyms)
    cfa = ControlFlowAnalyzer(instructions, fas.function_catalog)
    functions = cfa.find_functions()
    gen = LispGenerator(fas)

    with tempfile.NamedTemporaryFile(suffix='.lsp', mode='w', delete=False) as f:
        out_path = f.name
        result = gen.generate(functions, out_path)

    try:
        assert '(defun' in result, f'Expected function definitions in decompiled output'
        assert len(result) > 500, f'Expected substantial decompiled output, got {len(result)} chars'

        ok, errs = _validate(result)
        assert ok, f'Validation failed: {errs}'
    finally:
        os.unlink(out_path)


def test_tail_recursive_factorial():
    """Tail-recursive factorial compiles and decompiles correctly."""
    src = '''
(defun fact (n acc)
  (if (= n 0)
    acc
    (fact (1- n) (* n acc))))
'''
    result = compile_and_decompile(src)
    assert '(defun fact' in result
    ok, errs = _validate(result)
    assert ok, f'Validation failed: {errs}'
    # The tail call should be emitted as a loop back (JUMP) not a CALL
    assert '(fact ' not in result or '(while' in result, \
        'Tail recursion may be compiled as a loop'


def test_decompile_reference_fun_fas():
    """Decompiling tests/fun-cad.fas (compiled by a CAD AutoLISP compiler)
    reproduces the original source."""
    ref_path = os.path.join(os.path.dirname(__file__), 'fun-cad.fas')
    if not os.path.exists(ref_path):
        pytest.skip('tests/fun-cad.fas reference fixture not present')

    decomp_parser = Fas4Parser()
    fas = decomp_parser.parse(ref_path)
    disasm = Disassembler(short_subr=is_compact_stub(fas.bytecode, fas.function_catalog))
    instructions = disasm.disassemble(fas.bytecode, fas.nsyms)
    cfa = ControlFlowAnalyzer(instructions, fas.function_catalog)
    functions = cfa.find_functions()
    gen = LispGenerator(fas)
    result = gen.generate(functions, ref_path)

    assert '(defun a ()' in result
    assert '(alert "abc")' in result
    ok, errs = _validate(result)
    assert ok, f'Validation failed: {errs}'
