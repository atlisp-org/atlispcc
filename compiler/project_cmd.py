"""Project-level batch compilation for @lisp packages.

Reads ``pkg.lsp`` (``@:def-pkg`` / ``@::def-pkg`` manifest), collects the
``:FILES`` entries that are Lisp sources (no extension or ``.lsp``), and compiles
each one with the normal compiler. Resource entries (``.pat`` / ``.dwg`` / ...)
are skipped.

The public entry point is :func:`compile_project`, which returns a structured
report and never throws for per-file failures. :func:`run_project` adds the CLI
printing / exit-code behaviour used by ``atlispcc project``.
"""

from __future__ import annotations

import contextlib
import io
import json
import os
import sys
import time
from typing import Any, Dict, List, Optional, Tuple

from compiler.compile_cmd import cmd_compile

__all__ = ["compile_project", "run_project", "parse_pkg_manifest"]


# ---------------------------------------------------------------------------
# Minimal Lisp reader (enough for pkg.lsp manifests)
# ---------------------------------------------------------------------------

_TOKEN_END = set(' \t\r\n();"')


def _tokenize(text: str) -> List[Any]:
    tokens: List[Any] = []
    i, n = 0, len(text)
    while i < n:
        ch = text[i]
        if ch in " \t\r\n":
            i += 1
            continue
        if ch == ";":
            j = text.find("\n", i)
            i = n if j < 0 else j + 1
            continue
        if ch in "()":
            tokens.append(ch)
            i += 1
            continue
        if ch == "'":
            tokens.append("'")
            i += 1
            continue
        if ch == '"':
            i += 1
            buf: List[str] = []
            while i < n:
                c = text[i]
                if c == "\\" and i + 1 < n:
                    nxt = text[i + 1]
                    buf.append({"n": "\n", "t": "\t", "r": "\r"}.get(nxt, nxt))
                    i += 2
                    continue
                if c == '"':
                    i += 1
                    break
                buf.append(c)
                i += 1
            tokens.append(("str", "".join(buf)))
            continue
        j = i
        while j < n and text[j] not in _TOKEN_END:
            j += 1
        tokens.append(text[i:j])
        i = j
    return tokens


def _parse(tokens: List[Any]) -> List[Any]:
    pos = 0

    def one() -> Any:
        nonlocal pos
        if pos >= len(tokens):
            return []
        tok = tokens[pos]
        if tok == "(":
            pos += 1
            items: List[Any] = []
            while pos < len(tokens) and tokens[pos] != ")":
                items.append(one())
            if pos < len(tokens):
                pos += 1  # consume ")"
            return items
        if tok == ")":
            pos += 1
            return []
        if tok == "'":
            pos += 1
            return one()
        pos += 1
        return tok

    forms: List[Any] = []
    while pos < len(tokens):
        forms.append(one())
    return forms


def _find_key_values(node: Any, key: str) -> List[List[str]]:
    """Return every ``(:KEY "a" "b")`` value list found in the form tree."""
    found: List[List[str]] = []
    if isinstance(node, list):
        if node and isinstance(node[0], str) and node[0].upper() == key:
            vals = [
                item[1]
                for item in node[1:]
                if isinstance(item, tuple) and item and item[0] == "str"
            ]
            if vals:
                found.append(vals)
        for item in node:
            found.extend(_find_key_values(item, key))
    return found


def _find_key_value(node: Any, key: str) -> Optional[str]:
    values = _find_key_values(node, key)
    return values[0][0] if values else None


def parse_pkg_manifest(text: str) -> Dict[str, Any]:
    """Parse a pkg.lsp manifest string.

    Returns ``{"name": str | None, "files": [str, ...]}``. ``files`` preserves
    the order in the manifest and de-duplicates repeated entries.
    """
    forms = _parse(_tokenize(text))
    files: List[str] = []
    for group in _find_key_values(forms, ":FILES"):
        for item in group:
            if item not in files:
                files.append(item)
    return {"name": _find_key_value(forms, ":NAME"), "files": files}


def _read_text(path: str) -> str:
    with open(path, "rb") as f:
        raw = f.read()
    for enc in ("utf-8-sig", "gbk", "gb18030"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


# ---------------------------------------------------------------------------
# Project compilation
# ---------------------------------------------------------------------------


def _resolve_pkg(source: str) -> Tuple[str, str]:
    """Return ``(pkg_lsp_path, package_dir)`` from a pkg.lsp or directory."""
    path = os.path.abspath(source)
    if os.path.isdir(path):
        pkg = os.path.join(path, "pkg.lsp")
        return pkg, path
    return path, os.path.dirname(path)


def _classify(entry: str, pkg_dir: str) -> Dict[str, Any]:
    ext = os.path.splitext(entry)[1].lower()
    if ext and ext != ".lsp":
        return {"kind": "resource", "source": entry}
    src = entry if ext == ".lsp" else entry + ".lsp"
    src = src if os.path.isabs(src) else os.path.join(pkg_dir, src)
    return {"kind": "source", "source": os.path.normpath(src)}


def compile_project(
    source: str,
    outdir: str = "",
    opt_level: int = 0,
    encoding: str = "ansi",
    verify: bool = True,
    dry_run: bool = False,
    stop_on_error: bool = False,
) -> Dict[str, Any]:
    """Compile every Lisp source listed in a package manifest.

    ``source`` may point at ``pkg.lsp`` or at the package directory. Per-file
    failures are recorded in the report instead of aborting the run (unless
    ``stop_on_error`` is true). Returns a JSON-serialisable report.
    """
    pkg_path, pkg_dir = _resolve_pkg(source)
    report: Dict[str, Any] = {
        "package": {"pkg": pkg_path, "dir": pkg_dir, "name": None},
        "options": {
            "opt_level": opt_level,
            "outdir": os.path.abspath(outdir) if outdir else "",
            "encoding": encoding,
            "verify": verify,
            "dry_run": dry_run,
        },
        "summary": {"total": 0, "ok": 0, "error": 0, "missing": 0, "skipped": 0},
        "files": [],
    }

    if not os.path.isfile(pkg_path):
        report["error"] = f"pkg.lsp not found: {pkg_path}"
        return report

    try:
        manifest = parse_pkg_manifest(_read_text(pkg_path))
    except Exception as exc:  # malformed manifest must not crash the CLI
        report["error"] = f"failed to parse {pkg_path}: {exc}"
        return report

    report["package"]["name"] = manifest["name"]
    if not manifest["files"]:
        report["error"] = "no :FILES entries found in pkg.lsp"
        return report

    if outdir:
        os.makedirs(outdir, exist_ok=True)

    for entry in manifest["files"]:
        item = _classify(entry, pkg_dir)
        report["summary"]["total"] += 1

        if item["kind"] == "resource":
            report["summary"]["skipped"] += 1
            report["files"].append(
                {"entry": entry, "source": "", "output": "", "status": "skipped",
                 "reason": "resource", "bytes": 0, "elapsed_ms": 0}
            )
            continue

        src = item["source"]
        base = os.path.splitext(os.path.basename(src))[0]
        out = os.path.join(outdir, base + ".fas") if outdir else os.path.splitext(src)[0] + ".fas"
        record: Dict[str, Any] = {
            "entry": entry,
            "source": src,
            "output": out,
            "status": "pending",
            "bytes": 0,
            "elapsed_ms": 0,
        }

        if not os.path.isfile(src):
            record["status"] = "missing"
            report["summary"]["missing"] += 1
            report["files"].append(record)
            if stop_on_error:
                break
            continue

        if dry_run:
            record["status"] = "would-compile"
            report["summary"]["skipped"] += 1
            report["files"].append(record)
            continue

        started = time.time()
        stdout_buf, stderr_buf = io.StringIO(), io.StringIO()
        try:
            with contextlib.redirect_stdout(stdout_buf), contextlib.redirect_stderr(stderr_buf):
                cmd_compile(
                    src,
                    out,
                    opt_level=opt_level,
                    encoding=encoding,
                    verify=verify,
                )
            if not os.path.isfile(out):
                raise RuntimeError("compiler reported success but output file is missing")
            record["status"] = "ok"
            record["bytes"] = os.path.getsize(out)
            report["summary"]["ok"] += 1
        except SystemExit as exc:
            record["status"] = "error"
            record["error"] = f"compiler exited with code {exc.code}"
            report["summary"]["error"] += 1
        except Exception as exc:
            record["status"] = "error"
            record["error"] = str(exc)
            report["summary"]["error"] += 1
        finally:
            record["elapsed_ms"] = int((time.time() - started) * 1000)
            log = (stdout_buf.getvalue() + stderr_buf.getvalue()).strip()
            if log:
                record["log"] = log[-4000:]

        report["files"].append(record)
        if record["status"] == "error" and stop_on_error:
            break

    return report


def _print_text(report: Dict[str, Any]) -> None:
    pkg = report["package"]
    name = pkg.get("name") or os.path.basename(pkg["dir"])
    print(f"Package: {name}  ({pkg['pkg']})")
    if report.get("error"):
        print(f"Error: {report['error']}")
        return
    for item in report["files"]:
        status = item["status"]
        if status == "ok":
            print(f"[ok]      {os.path.basename(item['source'])} -> "
                  f"{os.path.basename(item['output'])} ({item['bytes']} bytes, "
                  f"{item['elapsed_ms']} ms)")
        elif status == "skipped":
            print(f"[skip]    {item['entry']}")
        elif status == "would-compile":
            print(f"[dry-run] {item['source']}")
        elif status == "missing":
            print(f"[missing] {item['source']}")
        else:
            print(f"[error]   {item['source']}: {item.get('error', '')}")
            if item.get("log"):
                for line in item["log"].splitlines():
                    print(f"          {line}")
    s = report["summary"]
    print(f"Summary: {s['ok']} ok, {s['error']} error, "
          f"{s['missing']} missing, {s['skipped']} skipped")


def run_project(
    source: str,
    outdir: str = "",
    opt_level: int = 0,
    encoding: str = "ansi",
    verify: bool = True,
    dry_run: bool = False,
    stop_on_error: bool = False,
    json_out: bool = False,
    report_path: str = "",
) -> int:
    """Compile a package and print the report. Returns a shell exit code."""
    report = compile_project(
        source,
        outdir=outdir,
        opt_level=opt_level,
        encoding=encoding,
        verify=verify,
        dry_run=dry_run,
        stop_on_error=stop_on_error,
    )
    if report_path:
        with open(report_path, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2, ensure_ascii=False)
    if json_out:
        print(json.dumps(report, indent=2, ensure_ascii=False))
    else:
        _print_text(report)

    if report.get("error"):
        return 1
    failed = report["summary"]["error"] + report["summary"]["missing"]
    return 1 if failed else 0
