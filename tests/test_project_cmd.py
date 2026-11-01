"""Tests for ``atlispcc project`` (pkg.lsp batch compilation)."""
import json
import os
import sys

import pytest

sys.path.insert(0, '.')

from compiler.project_cmd import (
    compile_project,
    parse_pkg_manifest,
    run_project,
)
from compiler.cli import main


PKG_TEMPLATE = """\
(@::def-pkg '((:NAME . "{name}")
        (:FULL-NAME . "Demo")
        (:VERSION . "0.1.0")
        (:REQUIRED . "base")
        (:FILES "a"
            "sub/b"
            "res.pat"
            "notes.txt")))
"""


def _write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        f.write(text)


def _make_pkg(tmp_path, name='demo', files=None, bad=False):
    pkg_dir = tmp_path / name
    pkg_dir.mkdir(parents=True, exist_ok=True)
    (pkg_dir / 'pkg.lsp').write_text(PKG_TEMPLATE.format(name=name), encoding='utf-8')
    _write(str(pkg_dir / 'a.lsp'), '(defun demo-a () 1)')
    _write(str(pkg_dir / 'sub' / 'b.lsp'), '(defun demo-b () 2)')
    _write(str(pkg_dir / 'res.pat'), '*X, X\n0,0,0,0,10\n')
    _write(str(pkg_dir / 'notes.txt'), 'not a source\n')
    if bad:
        _write(str(pkg_dir / 'a.lsp'), '(defun demo-a () ')
    return pkg_dir


def test_parse_pkg_manifest_lists_sources_and_resources():
    manifest = parse_pkg_manifest(PKG_TEMPLATE.format(name='demo'))
    assert manifest['name'] == 'demo'
    assert manifest['files'] == ['a', 'sub/b', 'res.pat', 'notes.txt']


def test_parse_pkg_manifest_single_string_and_comments():
    text = """
    ;; leading comment
    (@:def-pkg '((:NAME . "one")
                 (:FILES "only")))  ; trailing comment
    """
    manifest = parse_pkg_manifest(text)
    assert manifest['name'] == 'one'
    assert manifest['files'] == ['only']


def test_parse_pkg_manifest_deduplicates():
    text = '(@::def-pkg \'((:NAME . "d") (:FILES "a" "a" "b")))'
    assert parse_pkg_manifest(text)['files'] == ['a', 'b']


def test_compile_project_all_sources(tmp_path):
    pkg_dir = _make_pkg(tmp_path)
    outdir = tmp_path / 'out'
    report = compile_project(str(pkg_dir / 'pkg.lsp'), outdir=str(outdir))
    assert 'error' not in report
    assert report['package']['name'] == 'demo'
    assert report['summary'] == {'total': 4, 'ok': 2, 'error': 0, 'missing': 0, 'skipped': 2}
    assert (outdir / 'a.fas').is_file()
    assert (outdir / 'b.fas').is_file()
    assert all(item['status'] in ('ok', 'skipped') for item in report['files'])


def test_compile_project_missing_source(tmp_path):
    pkg_dir = _make_pkg(tmp_path)
    (pkg_dir / 'sub' / 'b.lsp').unlink()
    report = compile_project(str(pkg_dir))
    assert report['summary']['missing'] == 1
    assert any(item['status'] == 'missing' for item in report['files'])


def test_compile_project_parse_error_is_recorded(tmp_path):
    pkg_dir = _make_pkg(tmp_path, bad=True)
    report = compile_project(str(pkg_dir), outdir=str(tmp_path / 'out'))
    assert report['summary']['error'] == 1
    bad = [item for item in report['files'] if item['status'] == 'error'][0]
    assert 'exited with code' in bad['error'] or bad.get('log')


def test_compile_project_dry_run(tmp_path):
    pkg_dir = _make_pkg(tmp_path)
    report = compile_project(str(pkg_dir), dry_run=True)
    assert report['summary']['ok'] == 0
    assert any(item['status'] == 'would-compile' for item in report['files'])
    assert not any(str(item['output']).endswith('.fas') and os.path.exists(item['output'])
                   for item in report['files'])


def test_compile_project_stop_on_error(tmp_path):
    pkg_dir = _make_pkg(tmp_path, bad=True)
    report = compile_project(str(pkg_dir), stop_on_error=True)
    assert len(report['files']) == 1
    assert report['files'][0]['status'] == 'error'


def test_run_project_json_and_report_file(tmp_path, capsys):
    pkg_dir = _make_pkg(tmp_path)
    report_path = tmp_path / 'report.json'
    code = run_project(str(pkg_dir), outdir=str(tmp_path / 'o'),
                       json_out=True, report_path=str(report_path))
    assert code == 0
    out = json.loads(capsys.readouterr().out)
    assert out['summary']['ok'] == 2
    assert json.loads(report_path.read_text(encoding='utf-8'))['summary']['ok'] == 2


def test_run_project_returns_nonzero_on_error(tmp_path):
    pkg_dir = _make_pkg(tmp_path, bad=True)
    assert run_project(str(pkg_dir), outdir=str(tmp_path / 'o')) == 1


def test_cli_project_dispatch(tmp_path, capsys):
    pkg_dir = _make_pkg(tmp_path)
    argv = sys.argv
    try:
        sys.argv = ['atlispcc', 'project', str(pkg_dir),
                    '-o', str(tmp_path / 'out'), '--json']
        code = main()
    finally:
        sys.argv = argv
    assert code == 0
    data = json.loads(capsys.readouterr().out)
    assert data['summary']['ok'] == 2
