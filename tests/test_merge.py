"""Tests for the source-level merge command (compiler.merge_cmd)."""

import os
from pathlib import Path

import pytest

from compiler.compile_cmd import cmd_compile
from compiler.merge_cmd import cmd_merge, merge_text
from decompiler.fas4_decompiler import Fas4Parser

DATE = "1/1/26"
SALT = "deterministic"


def _src(tmp_path: Path, name: str, text: str) -> str:
    p = tmp_path / name
    p.write_text(text, encoding="utf-8")
    return str(p)


def test_merge_text_order(tmp_path):
    a = _src(tmp_path, "a.lsp", "(defun ma (x) (+ x 1))\n(setq *order-a* 1)\n")
    b = _src(tmp_path, "b.lsp", "(defun mb (y) (* y 2))\n(setq *order-b* 2)\n")
    merged, used = merge_text([a, b])
    assert [k for _, k in used] == ["lsp", "lsp"]
    assert merged.index("ma") < merged.index("*order-a*")
    assert merged.index("*order-a*") < merged.index("mb")
    assert merged.index("mb") < merged.index("*order-b*")


def test_merge_matches_manual_concatenation(tmp_path):
    a = _src(tmp_path, "a.lsp", "(defun ma (x) (+ x 1))\n(setq *order-a* (list 1 2))\n")
    b = _src(tmp_path, "b.lsp", "(defun mb (y) (* y 2))\n(setq *order-b* 3)\n")
    out_merge = str(tmp_path / "merged.fas")
    assert cmd_merge([a, b], output=out_merge, date=DATE, salt=SALT) == 0

    manual = tmp_path / "manual.lsp"
    manual.write_text(
        Path(a).read_text(encoding="utf-8")
        + "\n"
        + Path(b).read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    out_manual = str(tmp_path / "manual.fas")
    cmd_compile(str(manual), out_manual, date=DATE, salt=SALT)

    assert Path(out_merge).read_bytes() == Path(out_manual).read_bytes()


def test_merge_preserves_top_level_expressions(tmp_path):
    a = _src(tmp_path, "a.lsp", "(setq *top-a* (list 1 2))\n(defun ma (x) (+ x 1))\n")
    b = _src(tmp_path, "b.lsp", "(defun mb (y) (* y 2))\n(setq *top-b* 3)\n")
    out = str(tmp_path / "merged.fas")
    assert cmd_merge([a, b], output=out, date=DATE, salt=SALT) == 0

    fas = Fas4Parser().parse(out)
    upper = {str(s).upper() for s in fas.symbols}
    assert "*TOP-A*" in upper, upper
    assert "*TOP-B*" in upper, upper
    assert "MA" in upper and "MB" in upper, upper


def test_merge_fas_requires_explicit_opt_in(tmp_path):
    src = _src(tmp_path, "lib.lsp", "(defun f (x) (+ x 1))\n")
    fas = str(tmp_path / "lib.fas")
    cmd_compile(src, fas, date=DATE, salt=SALT)

    out = str(tmp_path / "out.fas")
    assert cmd_merge([fas], output=out, date=DATE, salt=SALT) == 1
    assert not os.path.exists(out)


def test_merge_fas_with_allow_lossy(tmp_path):
    src = _src(tmp_path, "lib.lsp", "(defun f (x) (+ x 1))\n")
    fas = str(tmp_path / "lib.fas")
    cmd_compile(src, fas, date=DATE, salt=SALT)
    other = _src(tmp_path, "other.lsp", "(defun g (y) (* y 2))\n")

    out = str(tmp_path / "out.fas")
    assert cmd_merge(
        [fas, other], output=out, date=DATE, salt=SALT, allow_lossy_fas=True
    ) == 0
    assert os.path.exists(out)
    parsed = Fas4Parser().parse(out)
    assert parsed.bytecode, "merged output should contain function bytecode"


def test_merge_keep_source(tmp_path):
    a = _src(tmp_path, "a.lsp", "(defun ma (x) (+ x 1))\n")
    b = _src(tmp_path, "b.lsp", "(defun mb (y) (* y 2))\n")
    out = str(tmp_path / "merged.fas")
    keep = str(tmp_path / "merged.lsp")
    assert cmd_merge([a, b], output=out, keep_source=keep, date=DATE, salt=SALT) == 0
    text = Path(keep).read_text(encoding="utf-8")
    assert "merged from: a.lsp" in text
    assert "merged from: b.lsp" in text
    assert "(defun ma" in text and "(defun mb" in text


def test_merge_rejects_unknown_extension(tmp_path):
    p = tmp_path / "x.txt"
    p.write_text("(defun x () 1)\n", encoding="utf-8")
    out = str(tmp_path / "out.fas")
    assert cmd_merge([str(p)], output=out, date=DATE, salt=SALT) == 1
    assert not os.path.exists(out)


def test_merge_rejects_zelx_with_hint(tmp_path):
    p = tmp_path / "x.zelx"
    p.write_bytes(b"!ZAS\x00")
    out = str(tmp_path / "out.fas")
    assert cmd_merge([str(p)], output=out, date=DATE, salt=SALT) == 1
