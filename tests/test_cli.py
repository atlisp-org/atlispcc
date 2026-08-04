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
