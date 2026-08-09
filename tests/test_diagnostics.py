"""诊断类新功能测试：analyze（调用图/依赖分析）与 roundtrip（往返冒烟）。

- analyze: build_from_lsp / build_from_fas 图模型 + 三种输出格式
- roundtrip: 裸内存管线 编译→反编译→validate→compare，PASS 与 FAIL 场景
"""
import os
import subprocess
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from compiler.dep_analysis import (
    build_from_fas,
    build_from_lsp,
    format_dot,
    format_mermaid,
    format_text,
)
from compiler.parser import Parser
from compiler.roundtrip import roundtrip, run_roundtrip

CAD_DIR = os.path.join(ROOT, "tests", "cad")


def _cad(name: str) -> str:
    return os.path.join(CAD_DIR, name)


def _lsp_graph(src: str):
    program = Parser(src).parse()
    return build_from_lsp(program)


def _lsp(src: str):
    return _lsp_graph(src)


# ─── analyze: .lsp ──────────────────────────────────────────────────────────


def test_analyze_lsp_edges_and_externals():
    src = """
    (defun helper (x) (+ x 1))
    (defun main () (helper 2) (princ "ok"))
    """
    g = _lsp(src)
    assert ("main", "helper") in g["edges"]
    assert "+" in g["externals"]
    assert "princ" in g["externals"]


def test_analyze_lsp_roots_via_top_level_call():
    src = '(setq r (run-all)) (defun run-all () (step1) (step2)) (defun step1 ()) (defun step2 ())'
    g = _lsp(src)
    assert "run-all" in g["roots"]
    assert "step1" not in g["roots"]


def test_analyze_lsp_c_commands_are_roots():
    src = '(defun c:cmd () (sub)) (defun sub ())'
    g = _lsp(src)
    assert "c:cmd" in g["roots"]
    assert "sub" not in g["roots"]
    assert g["unused"] == []


def test_analyze_lsp_star_error_root():
    src = '(defun *error* (m) (alert m))'
    g = _lsp(src)
    assert "*error*" in g["roots"]


def test_analyze_lsp_unused_recursive():
    # 递归自调用：自边计入 called_by=1，故自递归函数不被判为 unused；
    # 无外部调用者且非 root 时仍应出现在调用者之外，但这里 f 有自调用。
    src = '(defun f (n) (if (> n 0) (f (1- n)) n))'
    g = _lsp(src)
    assert ("f", "f") in g["edges"]
    # 自调用使 called_by >= 1（自边），因此 f 不落入 unused
    assert g["unused"] == []


def test_analyze_lsp_format_text_contains_counts():
    g = _lsp('(defun a () (b x)) (defun b (x) x)')
    text = format_text(g)
    assert "Functions: 2" in text
    assert "Edges: 1" in text
    assert "a (calls=1" in text


def test_analyze_lsp_format_dot():
    g = _lsp('(defun a () (b)) (defun b ())')
    dot = format_dot(g)
    assert dot.startswith("digraph callgraph")
    assert '"a" -> "b";' in dot
    assert "rankdir" in dot


def test_analyze_lsp_format_mermaid():
    g = _lsp('(defun a () (b)) (defun b ())')
    mm = format_mermaid(g)
    assert mm.startswith("flowchart LR")
    assert "a --> b" in mm
    assert "classDef root" in mm


# ─── analyze: .fas ──────────────────────────────────────────────────────────


def test_analyze_fas_t03_fib():
    fas = _cad("t03_fib_cad.fas")
    if not os.path.exists(fas):
        pytest.skip("CAD golden not present")
    g = build_from_fas(fas)
    names = [n["name"] for n in g["nodes"]]
    assert "FIB" in names
    assert any(ext.startswith(("+", "-", "IF")) for ext in g["externals"])


def test_analyze_fas_t01_has_function():
    fas = _cad("t01_math_cad.fas")
    if not os.path.exists(fas):
        pytest.skip("CAD golden not present")
    g = build_from_fas(fas)
    assert len(g["nodes"]) >= 1
    # 单入口 DEFCODE root：无 unused
    for n in g["nodes"]:
        assert n["name"] in g["roots"] or n["called_by"] > 0


def test_analyze_fas_t10_no_unused():
    fas = _cad("t10_init_cad.fas")
    if not os.path.exists(fas):
        pytest.skip("CAD golden not present")
    g = build_from_fas(fas)
    for n in g["nodes"]:
        assert n["name"] in g["roots"] or n["called_by"] > 0


# ─── roundtrip ──────────────────────────────────────────────────────────────


def test_roundtrip_simple_pass():
    src = '(defun hello () (princ "Hello, World!") (princ))'
    _, report, err = roundtrip(src, opt_level=0)
    assert err is None
    assert report["ok"] is True
    assert report["missing_defuns"] == []
    assert report["missing_strings"] == []


def test_roundtrip_opt2_pass():
    src = '(defun a (x) (+ x 1)) (defun b (y) (a (* y 2)))'
    _, report, err = roundtrip(src, opt_level=2)
    assert err is None
    assert report["ok"] is True


def test_roundtrip_chinese_string():
    src = '(defun t () (alert "中文提醒"))'
    _, report, err = roundtrip(src, opt_level=0)
    assert err is None
    assert report["ok"] is True


def test_roundtrip_foreach_stub():
    src = """(defun sum-list (lst)
  (setq total 0)
  (foreach x lst
    (setq total (+ total x)))
  total)"""
    _, report, err = roundtrip(src, opt_level=0)
    assert err is None
    assert report["ok"] is True


def test_roundtrip_parse_error_reports_failure():
    src = '(defun a () (princ "unclosed"'
    _, report, err = roundtrip(src)
    assert err is not None or report.get("ok") is False


def test_roundtrip_cli_subprocess():
    result = subprocess.run(
        [sys.executable, "-m", "compiler.cli", "roundtrip", os.path.join(ROOT, "tests", "fun.lsp")],
        capture_output=True,
        text=True,
    )
    assert "Result: PASS" in result.stdout
    assert result.returncode == 0


def test_roundtrip_cli_keep_flag():
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "compiler.cli",
            "roundtrip",
            os.path.join(ROOT, "tests", "fun.lsp"),
            "--keep",
        ],
        capture_output=True,
        text=True,
    )
    assert "artifacts:" in result.stdout
    assert result.returncode == 0


def test_roundtrip_cli_fail_returns_one(tmp_path):
    bad = tmp_path / "bad.lsp"
    bad.write_text("(defun a () (princ", encoding="utf-8")
    result = subprocess.run(
        [sys.executable, "-m", "compiler.cli", "roundtrip", str(bad)],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 1


def test_run_roundtrip_nonexistent_source():
    rc = run_roundtrip("__no_such_file__.lsp")
    assert rc in (0, 1)