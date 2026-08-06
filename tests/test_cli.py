"""CLI path tests — cmd_* functions and main() dispatch."""
import os
import sys
import tempfile
import pytest

sys.path.insert(0, '.')
from compiler.cli import cmd_compile, cmd_decompile, cmd_validate, cmd_link, main
from compiler.vlx_builder import build_vlx
from compiler.linker import link_fas
from decompiler.fas4_decompiler import Fas4Parser


def _tmp(name):
    return os.path.join(tempfile.gettempdir(), f'test_cli_{os.urandom(4).hex()}_{name}')


@pytest.mark.parametrize('level', [0, 1, 2, 3])
def test_compile_opt_level(level):
    src = '(defun add (a b) (+ a b))'
    out = _tmp(f'l{level}.fas')
    try:
        result = cmd_compile(src, out, opt_level=level)
        assert os.path.exists(result)
        fas = Fas4Parser().parse(result)
        assert len(fas.bytecode) > 0
    finally:
        if os.path.exists(out):
            os.unlink(out)


def test_compile_analyze_flag():
    out = _tmp('ana.fas')
    try:
        result = cmd_compile('(defun foo () 1)', out, opt_level=2, show_analysis=True)
        assert os.path.exists(result)
    finally:
        if os.path.exists(out):
            os.unlink(out)


def test_compile_default_output():
    """Default output name replaces .lsp with .fas."""
    src_path = _tmp('in.lsp')
    with open(src_path, 'w') as f:
        f.write('(defun foo () 1)')
    expected = src_path.replace('.lsp', '.fas')
    try:
        result = cmd_compile(src_path)
        assert result == expected
        assert os.path.exists(expected)
    finally:
        for p in (src_path, expected):
            if os.path.exists(p):
                os.unlink(p)


@pytest.mark.parametrize('enc', ['utf-8', 'utf-8-sig', 'gbk'])
def test_compile_source_encoding_detection(enc):
    """UTF-8 / UTF-8 BOM / ANSI(GBK) 编码的中文源码均能正确编译读取。"""
    src = '(defun hello () (strcat "你好，" "世界"))'
    src_path = _tmp('enc.lsp')
    out = _tmp('enc.fas')
    try:
        with open(src_path, 'w', encoding=enc) as f:
            f.write(src)
        result = cmd_compile(src_path, out)
        fas = Fas4Parser().parse(result)
        strs = [it[1] for it in fas.resource_items
                if isinstance(it, tuple) and len(it) == 2 and it[0] == 'STRING']
        assert '你好，' in strs
        assert '世界' in strs
    finally:
        for p in (src_path, out):
            if os.path.exists(p):
                os.unlink(p)


def test_compile_source_gbk_file_roundtrip():
    """GBK(ANSI) 源码 + cp936 输出：FAS 字符串为 GBK 字节，反编译正确。"""
    src_path = _tmp('gbk.lsp')
    out = _tmp('gbk.fas')
    try:
        with open(src_path, 'w', encoding='gbk') as f:
            f.write('(defun a () "中文测试")')
        cmd_compile(src_path, out, encoding='cp936')
        fas = Fas4Parser().parse(out)
        sec2 = bytes(fas.sec2_data)
        assert b'\xd6\xd0\xce\xc4\xb2\xe2\xca\xd4' in sec2  # GBK 字节 "中文测试"
    finally:
        for p in (src_path, out):
            if os.path.exists(p):
                os.unlink(p)



def test_cmd_validate_ok():
    p = _tmp('ok.lsp')
    with open(p, 'w') as f:
        f.write('(defun foo () 1)\n')
    try:
        assert cmd_validate(p) == 0
    finally:
        os.unlink(p)


def test_cmd_validate_fail():
    p = _tmp('bad.lsp')
    with open(p, 'w') as f:
        f.write('(defun foo () (if x)\n')
    try:
        assert cmd_validate(p) == 1
    finally:
        os.unlink(p)


def test_validate_dangerous_funcs_warn():
    """quit/exit/startapp must be flagged (warning) but still validate (rc 0)."""
    from tools.validate import tokenize, parse_tokens, validate_ast, validate_danger
    src = '(defun run () (startapp "cmd.exe" "dir"))\n(defun stop () (quit))\n'
    tokens, _ = tokenize(src)
    forms, _ = parse_tokens(tokens)
    assert validate_ast(forms) == []
    warns = validate_danger(forms)
    assert len(warns) == 2
    assert all('dangerous' in w for w in warns)


def test_validate_unused_local_warns():
    """Declared-but-unused / locals must be flagged as warnings."""
    from tools.validate import tokenize, parse_tokens, validate_unused
    src = '(defun foo (x / a b) (+ x 1))\n'
    tokens, _ = tokenize(src)
    forms, _ = parse_tokens(tokens)
    warns = validate_unused(forms)
    names = [w for w in warns]
    assert any('a' in w for w in names)
    assert any('b' in w for w in names)
    # used local must not warn
    src2 = '(defun foo (x / a) (setq a (+ x 1)) a)\n'
    tokens, _ = tokenize(src2)
    forms, _ = parse_tokens(tokens)
    assert validate_unused(forms) == []


def test_validate_danger_unused_cli_rc_zero():
    """CLI validate still returns 0 when only warnings are present."""
    from tools.validate import validate_file
    from pathlib import Path
    p = _tmp('warn.lsp')
    with open(p, 'w') as f:
        f.write('(defun run () (startapp "cmd"))\n')
    try:
        assert validate_file(Path(p)) is True
        assert cmd_validate(p) == 0
    finally:
        os.unlink(p)


def test_cmd_link_roundtrip():
    f1 = cmd_compile('(defun a (x) (+ x 1))', _tmp('a.fas'))
    f2 = cmd_compile('(defun b (x) (a x))', _tmp('b.fas'))
    out = _tmp('linked.fas')
    try:
        result = cmd_link([f1, f2], out)
        assert os.path.exists(result)
        fas = Fas4Parser().parse(result)
        assert len(fas.bytecode) > 0
    finally:
        for p in (f1, f2, out):
            if os.path.exists(p):
                os.unlink(p)


def test_build_vlx_container():
    f1 = cmd_compile('(defun main () 1)', _tmp('vlx_a.fas'))
    out = _tmp('app.vlx')
    try:
        result = build_vlx([f1], out, exports=['main'], package_name='app')
        assert os.path.exists(result)
        with open(result, 'rb') as fh:
            data = fh.read()
        assert data[:12] == b'VXL_FIRM\x00\x00\x00\x00'
        assert b'_VLX' in data
        assert b'vl-doc-export' in data
    finally:
        for p in (f1, out):
            if os.path.exists(p):
                os.unlink(p)


def test_main_compile_dispatch(monkeypatch, capsys):
    out = _tmp('main.fas')
    try:
        monkeypatch.setattr(sys, 'argv', ['atlispcc', 'compile', '-O1', '(defun foo () 1)', out])
        rc = main()
        assert rc == 0
        assert os.path.exists(out)
    finally:
        if os.path.exists(out):
            os.unlink(out)


def test_main_validate_dispatch(monkeypatch, capsys):
    p = _tmp('main_ok.lsp')
    with open(p, 'w') as f:
        f.write('(defun foo () 1)\n')
    try:
        monkeypatch.setattr(sys, 'argv', ['atlispcc', 'validate', p])
        rc = main()
        assert rc == 0
    finally:
        os.unlink(p)


def test_main_link_dispatch(monkeypatch):
    f1 = cmd_compile('(defun a (x) (+ x 1))', _tmp('m_a.fas'))
    f2 = cmd_compile('(defun b (x) (* x 2))', _tmp('m_b.fas'))
    out = _tmp('m_linked.fas')
    try:
        monkeypatch.setattr(sys, 'argv', ['atlispcc', 'link', f1, f2, '-o', out])
        rc = main()
        assert rc == 0
        assert os.path.exists(out)
    finally:
        for p in (f1, f2, out):
            if os.path.exists(p):
                os.unlink(p)
