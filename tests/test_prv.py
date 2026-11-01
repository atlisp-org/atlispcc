import json
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from compiler.prv import build_from_prv, parse_prv_text, run_prv
from compiler.vlx_builder import TAG_DCL, TAG_FAS4, TAG_TEXT, read_vlx


PRV = '''(PRV-DEF (:target . "bin/myapp.vlx")
  (:active-x . T)
  (:separate-namespace . T)
  (:protected . T)
  (:load-file-list
    (:lsp "src/core.lsp")
    (:fas "lib/util.fas")
    (:dcl "res/dlg.dcl"))
  (:require-file-list
    (:txt "res/readme.txt"))
  (:ob-directory)
  (:optimization . lsa)
)
'''


def test_parse_prv_switches_and_members():
    spec = parse_prv_text(PRV, 'app.prv')
    assert spec.target == 'bin/myapp.vlx'
    assert spec.active_x is True
    assert spec.separate_namespace is True
    assert spec.protected is True
    assert spec.optimization == 'lsa'
    assert spec.load_list == [
        ('lsp', 'src/core.lsp'),
        ('fas', 'lib/util.fas'),
        ('dcl', 'res/dlg.dcl'),
    ]
    assert spec.require_list == [('txt', 'res/readme.txt')]
    assert spec.diagnostics == []


def test_parse_prv_bare_switch_is_false():
    spec = parse_prv_text('(PRV-DEF (:separate-namespace) (:target . "a.vlx"))')
    assert spec.separate_namespace is False
    assert spec.active_x is False
    assert spec.protected is False
    assert spec.optimization == 'st'


def test_parse_prv_rejects_non_prv():
    with pytest.raises(ValueError):
        parse_prv_text('(defun foo () nil)')


def _make_tree(tmp_path):
    (tmp_path / 'src').mkdir()
    (tmp_path / 'lib').mkdir()
    (tmp_path / 'res').mkdir()
    (tmp_path / 'src' / 'core.lsp').write_text(
        '(defun core-fn (x) (+ x 1))', encoding='utf-8')
    (tmp_path / 'res' / 'dlg.dcl').write_text('// dcl', encoding='utf-8')
    (tmp_path / 'res' / 'readme.txt').write_text('notes', encoding='utf-8')
    prv = tmp_path / 'app.prv'
    prv.write_text(PRV, encoding='utf-8')
    return prv


def test_build_from_prv_packs_members(tmp_path):
    from compiler.compile_cmd import cmd_compile

    prv = _make_tree(tmp_path)
    cmd_compile(str(tmp_path / 'src' / 'core.lsp'), str(tmp_path / 'tmp_core.fas'))
    fas = tmp_path / 'lib' / 'util.fas'
    cmd_compile(str(tmp_path / 'src' / 'core.lsp'), str(fas))

    report = build_from_prv(str(prv), workdir=str(tmp_path / 'work'))
    assert report['errors'] == []
    target = tmp_path / 'bin' / 'myapp.vlx'
    assert report['target'] == str(target)
    assert target.exists()

    archive = read_vlx(str(target))
    names = [member.name for member in archive.members()]
    assert names == [b'CORE.FAS', b'UTIL.FAS', b'DLG.DCL', b'README.TXT']
    tags = [member.tag for member in archive.members()]
    assert tags == [TAG_FAS4, TAG_FAS4, TAG_DCL, TAG_TEXT]
    spec = archive.load_spec()
    assert b'(:protected . T)' in spec
    assert b'(:load-file-list (:fas "core.fas") (:fas "util.fas") (:DCL "dlg.dcl"))' in spec
    # 资源成员不进 LOAD 清单
    assert b'readme.txt' not in spec
    assert json.dumps(report)


def test_build_from_prv_respects_output_override(tmp_path):
    from compiler.compile_cmd import cmd_compile

    prv = _make_tree(tmp_path)
    cmd_compile(str(tmp_path / 'src' / 'core.lsp'), str(tmp_path / 'lib' / 'util.fas'))
    override = tmp_path / 'custom.vlx'
    report = build_from_prv(str(prv), output=str(override), workdir=str(tmp_path / 'work'))
    assert report['target'] == str(override)
    assert override.exists()


def test_build_from_prv_reports_missing_members(tmp_path):
    prv = _make_tree(tmp_path)
    report = build_from_prv(str(prv), workdir=str(tmp_path / 'work'))
    # lib/util.fas 未生成 → 错误记录，其余成员照常打包
    assert any('util.fas' in error for error in report['errors'])
    assert (tmp_path / 'bin' / 'myapp.vlx').exists()


def test_run_prv_returns_nonzero_on_error(tmp_path, capsys):
    prv = _make_tree(tmp_path)
    code = run_prv(str(prv), workdir=str(tmp_path / 'work'))
    assert code == 1
    assert 'util.fas' in capsys.readouterr().out


def test_run_prv_malformed(tmp_path, capsys):
    bad = tmp_path / 'bad.prv'
    bad.write_text('(not-a-prv)', encoding='utf-8')
    assert run_prv(str(bad)) == 1
    assert 'Error' in capsys.readouterr().err
