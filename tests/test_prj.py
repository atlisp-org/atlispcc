import json
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from compiler.prj import (
    compile_prj,
    expand_members,
    parse_prj_text,
    run_prj,
)

PRJ = """(VLISP-PROJECT-LIST
  :NAME "demo"
  :OWN-LIST ("src/a.lsp" "src/b")
  :REQUIRE ("src/dep.lsp")
  :PROJECT-KEYS (:BUILD (:OPTIMIZE :LINK) :SAFE-MODE T :MERGED nil :MSGLEVEL 2)
  :FAS-DIRECTORY "./build"
  :CONTEXT-ID :AUTOLISP)
"""


def test_parse_prj_keys():
    spec = parse_prj_text(PRJ, "demo.prj")
    assert spec.name == "demo"
    assert spec.own_list == ["src/a.lsp", "src/b"]
    assert spec.require_list == ["src/dep.lsp"]
    assert spec.fas_directory == "./build"
    assert spec.build_keys() == {
        "merged": False,
        "optimize": True,
        "link": True,
        "localize": False,
        "safe_mode": True,
        "msg_level": 2,
    }
    assert spec.diagnostics == []


def test_parse_prj_standard_build_and_truth_values():
    spec = parse_prj_text(
        "(VLISP-PROJECT-LIST :NAME demo" " :PROJECT-KEYS (:BUILD (:STANDARD) :MERGED T :SAFE-MODE nil :MSGLEVEL 9))"
    )
    assert spec.name == "demo"
    assert spec.merged is True
    assert spec.safe_mode is False
    assert spec.optimize is False
    assert spec.msg_level == 2  # clamped


def test_parse_prj_rejects_non_project_file():
    with pytest.raises(ValueError):
        parse_prj_text("(defun foo () nil)")


def test_unknown_keys_are_reported_not_fatal():
    spec = parse_prj_text('(VLISP-PROJECT-LIST :NAME "x" :BOGUS 1 :PROJECT-KEYS (:WEIRD 2))')
    assert spec.name == "x"
    assert any("BOGUS" in message for message in spec.diagnostics)
    assert any("WEIRD" in message for message in spec.diagnostics)


def test_expand_members_directory_extensionless_and_missing(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    (src / "b.lsp").write_text("(defun b () nil)", encoding="utf-8")
    (src / "a.lsp").write_text("(defun a () nil)", encoding="utf-8")
    (src / "note.txt").write_text("x", encoding="utf-8")
    (tmp_path / "top.lsp").write_text("(defun top () nil)", encoding="utf-8")

    diagnostics = []
    files = expand_members(["src", "top"], str(tmp_path), ":OWN-LIST", diagnostics)
    assert [os.path.basename(path) for path in files] == ["a.lsp", "b.lsp", "top.lsp"]

    diagnostics = []
    files = expand_members(["nope.lsp"], str(tmp_path), ":OWN-LIST", diagnostics)
    assert files == []
    assert any("not found" in message for message in diagnostics)


def _write_project(tmp_path, merged, name="demo"):
    src = tmp_path / "src"
    src.mkdir(exist_ok=True)
    (src / "a.lsp").write_text("(defun a-fn (x) (+ x 1))", encoding="utf-8")
    (src / "b.lsp").write_text("(defun b-fn (y) (* y 2))", encoding="utf-8")
    prj = tmp_path / "demo.prj"
    prj.write_text(
        "(VLISP-PROJECT-LIST\n"
        f'  :NAME "{name}"\n'
        '  :OWN-LIST ("src/a.lsp" "src/b.lsp" "src/missing.lsp")\n'
        f'  :PROJECT-KEYS (:BUILD (:STANDARD) :MERGED {"T" if merged else "nil"})\n'
        '  :FAS-DIRECTORY "./build")\n',
        encoding="utf-8",
    )
    return prj


def test_compile_prj_uses_fas_directory(tmp_path):
    prj = _write_project(tmp_path, merged=False)
    report = compile_prj(str(prj))

    assert report["project"]["name"] == "demo"
    assert report["options"]["outdir"] == str(tmp_path / "build")
    assert report["summary"]["ok"] == 2
    assert report["summary"]["missing"] == 1
    assert (tmp_path / "build" / "a.fas").exists()
    assert (tmp_path / "build" / "b.fas").exists()
    assert report["merged"]["status"] == "disabled"
    assert any("missing.lsp" in message for message in report["diagnostics"])
    assert json.dumps(report)  # JSON-serialisable


def test_compile_prj_merged_links_one_module(tmp_path):
    prj = _write_project(tmp_path, merged=True)
    report = compile_prj(str(prj))

    assert report["merged"]["status"] == "ok"
    merged = tmp_path / "build" / "demo.fas"
    assert merged.exists()
    assert report["merged"]["output"] == str(merged)
    assert os.path.getsize(merged) > 0


def test_compile_prj_outdir_override(tmp_path):
    prj = _write_project(tmp_path, merged=False)
    override = tmp_path / "elsewhere"
    report = compile_prj(str(prj), outdir=str(override))
    assert report["options"]["outdir"] == str(override)
    assert (override / "a.fas").exists()


def test_compile_prj_dry_run(tmp_path):
    prj = _write_project(tmp_path, merged=False)
    report = compile_prj(str(prj), dry_run=True)
    assert report["summary"]["skipped"] == 2
    assert report["merged"]["status"] == "disabled"
    assert not (tmp_path / "build" / "a.fas").exists()


def test_run_prj_returns_nonzero_on_missing(tmp_path, capsys):
    prj = _write_project(tmp_path, merged=False)
    code = run_prj(str(prj))
    assert code == 1
    out = capsys.readouterr().out
    assert "demo" in out
    assert "[missing]" in out


def test_run_prj_json_output(tmp_path, capsys):
    prj = _write_project(tmp_path, merged=False)
    code = run_prj(str(prj), json_out=True, report_path=str(tmp_path / "report.json"))
    payload = json.loads(capsys.readouterr().out)
    assert payload["summary"]["ok"] == 2
    assert code == 1
    assert json.loads((tmp_path / "report.json").read_text(encoding="utf-8"))["project"]["name"] == "demo"


def test_run_prj_malformed_is_reported(tmp_path, capsys):
    prj = tmp_path / "bad.prj"
    prj.write_text("(not-a-project)", encoding="utf-8")
    assert run_prj(str(prj)) == 1
    assert "Error" in capsys.readouterr().err


def test_compile_prj_reproducible_with_date_and_salt(tmp_path):
    prj = _write_project(tmp_path, merged=True)
    first = tmp_path / "out1"
    second = tmp_path / "out2"
    compile_prj(str(prj), outdir=str(first), date="2/3/26", salt="deterministic")
    compile_prj(str(prj), outdir=str(second), date="2/3/26", salt="deterministic")

    for name in ("a.fas", "b.fas", "demo.fas"):
        assert (first / name).read_bytes() == (second / name).read_bytes()
        assert (first / name).read_bytes().rstrip().endswith(b"$;A2/3/26")


def test_expand_members_accepts_windows_separators(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    (src / "a.lsp").write_text('(defun a () nil)', encoding="utf-8")
    diagnostics = []
    files = expand_members(["src\\a.lsp"], str(tmp_path), ":OWN-LIST", diagnostics)
    assert [os.path.basename(path) for path in files] == ["a.lsp"]
    assert diagnostics == []


def test_expand_members_supports_glob_patterns(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    for name in ("b.lsp", "a.lsp", "skip.txt"):
        (src / name).write_text('(defun x () nil)', encoding="utf-8")
    diagnostics = []
    files = expand_members(["src/*.lsp"], str(tmp_path), ":OWN-LIST", diagnostics)
    assert [os.path.basename(path) for path in files] == ["a.lsp", "b.lsp"]

    diagnostics = []
    assert expand_members(["src/*.zzz"], str(tmp_path), ":OWN-LIST", diagnostics) == []
    assert any("matched no files" in message for message in diagnostics)
