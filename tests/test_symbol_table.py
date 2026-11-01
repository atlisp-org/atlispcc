"""Dedicated tests for compiler.symbol_table — symbol collection & resolution."""
import sys
sys.path.insert(0, '.')

from compiler.parser import Parser
from compiler.ast_nodes import Defun, Setq, Call, Symbol
from compiler.symbol_table import SymbolTable, BUILTIN_FUNCTIONS
from compiler.packages import PackageTable


def test_get_or_add_dedups():
    st = SymbolTable()
    i1 = st.get_or_add('foo')
    i2 = st.get_or_add('foo')
    assert i1 == i2
    assert st.idx_of('foo') == i1
    assert st.idx_of('missing') is None


def test_builtin_detection():
    st = SymbolTable()
    assert st.is_builtin('car')
    assert st.is_builtin('CAR')       # case-insensitive
    assert st.is_builtin('strcat')
    assert not st.is_builtin('my-func')
    assert 'car' in BUILTIN_FUNCTIONS


def test_add_string_int_real():
    st = SymbolTable()
    si = st.add_string('hello')
    sj = st.add_string('hello')
    assert si == sj
    ii = st.add_int(42)
    assert st.entries[ii][0] == 'INT'
    ri = st.add_real(3.5)
    assert st.entries[ri][0] == 'REAL'


def test_add_func_ref_updates_nsyms():
    st = SymbolTable()
    before = st.nsyms
    st.add_func_ref('helper', 100)
    assert st.nsyms > before
    assert st.function_offsets['helper'] == 100


def test_resolve_name_plain():
    st = SymbolTable()
    assert st.resolve_name('foo') == 'foo'


def test_resolve_name_package_qualified():
    st = SymbolTable(package_table=PackageTable())
    st.package_table.add_package('vec', [], ['vec2'])
    st.package_table.set_current('vec')
    assert st.resolve_name('vec:vec2') == 'vec|vec2'


def test_collect_symbols_defun():
    src = '(defun add (a b) (+ a b))'
    prog = Parser(src).parse()
    st = SymbolTable()
    st.collect_symbols(prog)
    # 'add', 'a', 'b' collected; '+' is builtin (not collected as symbol)
    assert st.idx_of('add') is not None
    assert st.idx_of('a') is not None
    assert st.idx_of('b') is not None


def test_collect_symbols_call_rewrites_package_ref():
    src = '(defpackage vec (:export vec2))\n(in-package vec)\n(defun vec2 (x) (+ x 1))\n'
    src += '(in-package app)\n(defun main () (vec:vec2 3))'
    prog = Parser(src).parse()
    st = SymbolTable()
    st.collect_symbols(prog)
    # vec2 registered under its munged internal name
    assert st.idx_of('vec|vec2') is not None
    # the qualified call was rewritten on the AST node
    main = [f for f in prog.forms if isinstance(f, Defun) and f.name == 'main'][0]
    call = main.body[0]
    assert isinstance(call, Call)
    assert call.name == 'vec|vec2'


def test_collect_symbols_strings():
    src = '(defun greet () (princ "hi"))'
    prog = Parser(src).parse()
    st = SymbolTable()
    st.collect_symbols(prog)
    assert st.strings == ['hi']


def test_collect_symbols_excludes_nil_t():
    st = SymbolTable()
    st.get_or_add('T')
    st.get_or_add('nil')
    assert st.idx_of('T') is not None
    assert st.idx_of('nil') is not None


def test_case_insensitive_index_matches_legacy_fallback():
    from compiler.symbol_table import SymbolTable

    table = SymbolTable()
    first = table.get_or_add("Status")
    assert table.get_or_add("status") == first
    assert table.get_or_add("STATUS") == first
    assert table.has_case_insensitive("STATUS") is True
    assert table.has_case_insensitive("nope") is False


def test_case_sensitive_symbols_are_not_merged():
    from compiler.symbol_table import SymbolTable

    table = SymbolTable()
    a = table.get_or_add("vla-get-Count")
    b = table.get_or_add("vla-get-count")
    assert a != b
    assert table.has_case_insensitive("vla-get-count") is False

    c = table.get_or_add("kwote")
    d = table.get_or_add("KWOTE")
    assert c != d


def test_private_keys_are_not_case_merged():
    from compiler.symbol_table import SymbolTable

    table = SymbolTable()
    a = table.get_or_add("__str_x__")
    b = table.get_or_add("__STR_X__")
    assert a != b
    assert table.has_case_insensitive("__STR_X__") is False


def test_add_force_does_not_join_the_case_index():
    from compiler.symbol_table import SymbolTable

    table = SymbolTable()
    slot = table.add_force("Temp")
    assert table.has_case_insensitive("TEMP") is False
    fresh = table.get_or_add("TEMP")
    assert fresh != slot
