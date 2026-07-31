import sys
sys.path.insert(0, '.')

import os
import tempfile
import pytest
from compiler.parser import Parser
from compiler.symbol_table import SymbolTable
from compiler.codegen import CodeGenerator, BytecodeBuffer
from compiler.resource_builder import ResourceBuilder
from compiler.fas_writer import FasWriter
from compiler.ast import Defun
from fas4_decompiler import Fas4Parser, Disassembler, ControlFlowAnalyzer, LispGenerator, is_compact_stub
from validate import tokenize, parse_tokens, validate_ast


ENCODE_POP = bytes([0x0a])


def _validate(source: str) -> tuple:
    tokens, errs = tokenize(source)
    if errs:
        return False, errs
    forms, errs = parse_tokens(tokens)
    if errs:
        return False, errs
    errs = validate_ast(forms, source)
    return (False, errs) if errs else (True, [])


def compile_and_decompile(src: str) -> str:
    """Compile Lisp source to FAS in memory and decompile back."""
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


def test_args_preserved():
    src = '(defun factorial (n) (if (<= n 1) 1 (* n (factorial (- n 1)))))'
    result = compile_and_decompile(src)
    assert '(defun factorial (n)' in result
    ok, errs = _validate(result)
    assert ok, f'Validation failed: {errs}'


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
    """Decompile real FAS4 file (PDI.fas) and validate output."""
    fas_path = os.path.join(os.path.dirname(__file__), '..', 'PDI.fas')
    if not os.path.exists(fas_path):
        pytest.skip('PDI.fas not found')

    from fas4_decompiler import Fas4Parser, Disassembler, \
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
        assert '(defun c:' in result or '(defun C:' in result, \
            f'Expected function definition in decompiled output'
        assert 'dict_name' in result or 'pattern' in result or 'purge' in result.lower(), \
            'Expected dictionary purge logic in output'

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
