"""Visual LISP 工程文件（``.prj``）解析与批量编译。

``.prj`` 的根形式是 ``(VLISP-PROJECT-LIST :KEY value ...)``：:

    (VLISP-PROJECT-LIST
      :NAME "demo"
      :OWN-LIST ("src/a.lsp" "src/b.lsp")
      :PROJECT-KEYS (:BUILD (:OPTIMIZE :LINK) :SAFE-MODE T :MERGED nil :MSGLEVEL 1)
      :FAS-DIRECTORY "./build")

本模块只实现编译所需的部分：

- ``:OWN-LIST`` / ``:REQUIRE`` / ``:LOAD`` 成员展开（目录递归收集 ``*.lsp``、
  无扩展名补 ``.lsp``、显式路径原样使用），``:OWN-LIST`` 在前，其后按
  ``:REQUIRE`` → ``:LOAD`` 顺序追加；
- ``:PROJECT-KEYS`` 的 ``:BUILD`` / ``:SAFE-MODE`` / ``:MERGED`` / ``:MSGLEVEL``；
- ``:FAS-DIRECTORY`` 作为输出目录（``-o`` 优先）；
- ``:MERGED`` 为真且产出 ≥2 个模块时，用链接器合成单个 ``<NAME>.fas``。

入口 :func:`parse_prj` / :func:`compile_prj` / :func:`run_prj`。
"""

from __future__ import annotations

import glob
import json
import os
import re
import sys
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

__all__ = ["PrjSpec", "parse_prj", "parse_prj_text", "compile_prj", "run_prj"]


# ---------------------------------------------------------------------------
# AST helpers（复用 compiler.sexpr；关键字一律是 `:KEY` 形式的 Symbol）
# ---------------------------------------------------------------------------

from compiler.sexpr import (  # noqa: E402  (放在数据模型之前的集中导入)
    head_name as _head_name,
    integer as _integer,
    keyword as _keyword,
    keyword_sequence as _keyword_sequence,
    string_list as _string_list,
    text as _text,
    truth as _truth,
)


# ---------------------------------------------------------------------------
# .prj model
# ---------------------------------------------------------------------------


@dataclass
class PrjSpec:
    path: str = ""
    base_dir: str = ""
    name: str = ""
    own_list: List[str] = field(default_factory=list)
    require_list: List[str] = field(default_factory=list)
    load_list: List[str] = field(default_factory=list)
    fas_directory: Optional[str] = None
    tmp_directory: Optional[str] = None
    merged: bool = False
    optimize: bool = False
    link: bool = False
    localize: bool = False
    safe_mode: bool = True
    msg_level: int = 1
    diagnostics: List[str] = field(default_factory=list)

    @property
    def display_name(self) -> str:
        if self.name:
            return self.name
        stem = os.path.splitext(os.path.basename(self.path))[0]
        return stem or "project"

    def build_keys(self) -> Dict[str, Any]:
        return {
            "merged": self.merged,
            "optimize": self.optimize,
            "link": self.link,
            "localize": self.localize,
            "safe_mode": self.safe_mode,
            "msg_level": self.msg_level,
        }


def _parse_project_keys(node: Any, spec: PrjSpec) -> None:
    keys = _keyword_sequence(node)
    index = 0
    while index < len(keys):
        key = _keyword(keys[index])
        if key is None:
            spec.diagnostics.append(f":PROJECT-KEYS: unexpected value {_text(keys[index])!r}; ignored")
            index += 1
            continue
        index += 1
        value = keys[index] if index < len(keys) and _keyword(keys[index]) is None else None
        if value is not None:
            index += 1

        if key == "BUILD":
            names = {(_text(item) or "").upper().lstrip(":") for item in _keyword_sequence(value)}
            names.discard("")
            if "STANDARD" in names:
                spec.optimize = False
                spec.link = False
                spec.localize = False
            if "OPTIMIZE" in names:
                spec.optimize = True
            spec.link = spec.link or "LINK" in names
            spec.localize = spec.localize or "LOCALIZE" in names
        elif key == "SAFE-MODE":
            parsed = _truth(value)
            spec.safe_mode = True if parsed is None else parsed
        elif key == "MERGED":
            parsed = _truth(value)
            spec.merged = False if parsed is None else parsed
        elif key == "MSGLEVEL":
            level = _integer(value)
            spec.msg_level = 1 if level is None else max(0, min(2, level))
        else:
            spec.diagnostics.append(f":PROJECT-KEYS: unknown key :{key}; ignored")


def parse_prj_text(text: str, path: str = "") -> PrjSpec:
    """解析 ``.prj`` 源码。缺少 ``(VLISP-PROJECT-LIST …)`` 根形式时抛 ``ValueError``。"""
    from compiler.parser import Parser

    spec = PrjSpec(path=path, base_dir=os.path.dirname(os.path.abspath(path)) if path else "")
    program = Parser(text).parse()
    root = None
    for form in program.forms:
        if _head_name(form).upper() == "VLISP-PROJECT-LIST":
            root = form
            break
    if root is None:
        raise ValueError("not a Visual LISP project file: no (VLISP-PROJECT-LIST ...) form")

    items = _keyword_sequence(root)
    index = 1  # items[0] 是根符号
    while index < len(items):
        key = _keyword(items[index])
        if key is None:
            spec.diagnostics.append(f"unexpected value {_text(items[index])!r}; ignored")
            index += 1
            continue
        index += 1
        # `:CONTEXT-ID :AUTOLISP` 的值本身就是关键字。
        takes_keyword_value = key == "CONTEXT-ID"
        value = items[index] if index < len(items) and (takes_keyword_value or _keyword(items[index]) is None) else None
        if value is not None:
            index += 1

        if key == "NAME":
            spec.name = _text(value) or ""
        elif key == "OWN-LIST":
            spec.own_list = _string_list(value)
        elif key == "REQUIRE":
            spec.require_list = _string_list(value)
        elif key == "LOAD":
            spec.load_list = _string_list(value)
        elif key == "FAS-DIRECTORY":
            spec.fas_directory = _text(value)
        elif key == "TMP-DIRECTORY":
            spec.tmp_directory = _text(value)
        elif key == "PROJECT-KEYS":
            if value is None:
                spec.diagnostics.append(":PROJECT-KEYS has no value; standard mode assumed")
            else:
                _parse_project_keys(value, spec)
        elif key in _IGNORED_KEYS:
            continue  # :COMPILE / :HELP / :CONTEXT-ID 等不参与编译
        else:
            spec.diagnostics.append(f":{key}: unknown project key; ignored")
    return spec


def parse_prj(path: str) -> PrjSpec:
    from core.fas_core import decode_source_text

    with open(path, "rb") as handle:
        text = decode_source_text(handle.read())
    return parse_prj_text(text, path=path)


# ---------------------------------------------------------------------------
# 成员展开与编译
# ---------------------------------------------------------------------------

_DRIVE_RE = re.compile(r"^[A-Za-z]:[\\/]")

# 解析但不参与编译的键（不产生警告）。
_IGNORED_KEYS = {"COMPILE", "HELP", "CONTEXT-ID"}


def _normalize_entry(entry: str) -> str:
    """`.prj` 里常写 Windows 反斜杠；在 POSIX 上按分隔符处理。"""
    return entry.replace("\\", "/")


def _resolve(base_dir: str, entry: str) -> str:
    entry = _normalize_entry(entry)
    if os.path.isabs(entry) or _DRIVE_RE.match(entry):
        return entry
    return os.path.normpath(os.path.join(base_dir, entry))


def _collect_lsp_dir(path: str) -> List[str]:
    found: List[str] = []
    for dirpath, _dirnames, filenames in os.walk(path):
        for filename in filenames:
            if filename.lower().endswith(".lsp"):
                found.append(os.path.join(dirpath, filename))
    found.sort()
    return found


def _is_windows_path_on_posix(entry: str) -> bool:
    return os.name != "nt" and bool(_DRIVE_RE.match(_normalize_entry(entry)))


def expand_members(
    entries: List[str], base_dir: str, label: str, diagnostics: List[str], missing: Optional[List[str]] = None
) -> List[str]:
    """目录 → 递归 ``*.lsp``（名字排序）；通配符 → glob 展开；无扩展名 → 补 ``.lsp``。"""
    files: List[str] = []
    for entry in entries:
        if _is_windows_path_on_posix(entry):
            diagnostics.append(
                f"{label}: Windows path {entry} is not accessible on this platform; skipped"
            )
            if missing is not None:
                missing.append(_normalize_entry(entry))
            continue
        path = _resolve(base_dir, entry)
        if any(ch in path for ch in "*?["):
            matched: List[str] = []
            for hit in sorted(glob.glob(path)):
                if os.path.isdir(hit):
                    matched.extend(_collect_lsp_dir(hit))
                else:
                    matched.append(hit)
            if not matched:
                diagnostics.append(f"{label}: pattern {entry} matched no files")
                if missing is not None:
                    missing.append(path)
            files.extend(matched)
            continue
        if os.path.isdir(path):
            found = _collect_lsp_dir(path)
            if not found:
                diagnostics.append(f"{label}: directory {entry} has no .lsp sources")
            files.extend(found)
            continue
        if not os.path.splitext(path)[1]:
            path = path + ".lsp"
        if not os.path.isfile(path):
            diagnostics.append(f"{label}: {entry} not found; skipped")
            if missing is not None:
                missing.append(path)
            continue
        files.append(path)
    return files


def _collect_sources(spec: PrjSpec) -> Tuple[List[str], List[str], List[str]]:
    diagnostics: List[str] = []
    missing: List[str] = []
    sources = expand_members(spec.own_list, spec.base_dir, ":OWN-LIST", diagnostics, missing)
    for entries, label in ((spec.require_list, ":REQUIRE"), (spec.load_list, ":LOAD")):
        for path in expand_members(entries, spec.base_dir, label, diagnostics, missing):
            if path.lower().endswith(".lsp"):
                sources.append(path)
            else:
                diagnostics.append(f"{label}: {path} is not a .lsp source; not compiled")
    return sources, missing, diagnostics


def _output_dir(spec: PrjSpec, outdir: str) -> str:
    if outdir:
        return os.path.abspath(outdir)
    if spec.fas_directory:
        return _resolve(spec.base_dir, spec.fas_directory)
    return spec.base_dir


def compile_prj(
    source: str,
    outdir: str = "",
    opt_level: int = 0,
    encoding: str = "ansi",
    verify: bool = True,
    dry_run: bool = False,
    stop_on_error: bool = False,
    date=None,
    salt=None,
) -> Dict[str, Any]:
    """编译一个 ``.prj`` 工程，返回可 JSON 序列化的报告（单文件失败不抛出）。"""
    spec = parse_prj(source)
    sources, missing, diagnostics = _collect_sources(spec)
    target_dir = _output_dir(spec, outdir)
    # `:BUILD (:OPTIMIZE …)` 且调用方没有显式 -O 时，默认开 atlispcc 的 -O1。
    if not opt_level and spec.optimize:
        opt_level = 1

    report: Dict[str, Any] = {
        "project": {
            "prj": os.path.abspath(source),
            "dir": spec.base_dir,
            "name": spec.display_name,
            "build": spec.build_keys(),
        },
        "options": {
            "opt_level": opt_level,
            "outdir": target_dir,
            "encoding": encoding,
            "verify": verify,
            "dry_run": dry_run,
            "date": date or "",
            "salt": salt or "",
        },
        "summary": {"total": 0, "ok": 0, "error": 0, "missing": 0, "skipped": 0},
        "files": [],
        "diagnostics": diagnostics + spec.diagnostics,
        "merged": {"enabled": spec.merged, "status": "pending"},
    }

    if not sources:
        report["error"] = "no Lisp sources found (:OWN-LIST / :REQUIRE / :LOAD are empty)"
        report["merged"]["status"] = "skipped"
        return report

    from compiler.batch import compile_batch

    entries = [(os.path.basename(path), path) for path in missing]
    entries.extend((os.path.basename(src), src) for src in sources)
    files, summary = compile_batch(
        entries,
        target_dir,
        opt_level=opt_level,
        encoding=encoding,
        verify=verify,
        dry_run=dry_run,
        stop_on_error=stop_on_error,
        date=date,
        salt=salt,
    )
    report["files"] = files
    report["summary"] = summary
    built = [str(item["output"]) for item in files if item["status"] == "ok"]

    if not spec.merged:
        report["merged"]["status"] = "disabled"
    elif len(built) < 2:
        report["merged"]["status"] = "skipped"
        report["merged"]["reason"] = "fewer than two modules were built"
    else:
        from compiler.linker import link_fas

        merged_path = os.path.join(target_dir, spec.display_name + ".fas")
        try:
            link_fas(built, merged_path, encoding=encoding, date=date, salt=salt)
            report["merged"].update(
                {
                    "status": "ok",
                    "output": merged_path,
                    "bytes": os.path.getsize(merged_path),
                    "inputs": built,
                }
            )
        except Exception as exc:  # noqa: BLE001 - merge failure is reported, not fatal
            report["merged"].update({"status": "error", "error": str(exc)})
            report["summary"]["error"] += 1

    return report


def _print_text(report: Dict[str, Any]) -> None:
    project = report["project"]
    print(f"Project: {project['name']}  ({project['prj']})")
    keys = project["build"]
    enabled = [key for key in ("optimize", "link", "localize", "merged") if keys.get(key)]
    print(f"Build keys: {' '.join(enabled) if enabled else 'standard'}")
    for message in report.get("diagnostics", []):
        print(f"[note]    {message}")
    if report.get("error"):
        print(f"Error: {report['error']}")
        return
    for item in report["files"]:
        status = item["status"]
        if status == "ok":
            print(
                f"[ok]      {os.path.basename(item['source'])} -> "
                f"{os.path.basename(item['output'])} ({item['bytes']} bytes, "
                f"{item['elapsed_ms']} ms)"
            )
        elif status == "would-compile":
            print(f"[dry-run] {item['source']}")
        elif status == "missing":
            print(f"[missing] {item['source']}")
        else:
            print(f"[error]   {item['source']}: {item.get('error', '')}")
            if item.get("log"):
                for line in item["log"].splitlines():
                    print(f"          {line}")
    merged = report["merged"]
    if merged["status"] == "ok":
        print(
            f"[merged]  -> {os.path.basename(merged['output'])} "
            f"({merged['bytes']} bytes from {len(merged['inputs'])} modules)"
        )
    elif merged["status"] == "error":
        print(f"[merged]  error: {merged.get('error', '')}")
    summary = report["summary"]
    print(
        f"Summary: {summary['ok']} ok, {summary['error']} error, "
        f"{summary['missing']} missing, {summary['skipped']} skipped"
    )


def run_prj(
    source: str,
    outdir: str = "",
    opt_level: int = 0,
    encoding: str = "ansi",
    verify: bool = True,
    dry_run: bool = False,
    stop_on_error: bool = False,
    json_out: bool = False,
    report_path: str = "",
    date=None,
    salt=None,
) -> int:
    """编译 ``.prj`` 并打印报告。返回 shell 退出码。"""
    try:
        report = compile_prj(
            source,
            outdir=outdir,
            opt_level=opt_level,
            encoding=encoding,
            verify=verify,
            dry_run=dry_run,
            stop_on_error=stop_on_error,
            date=date,
            salt=salt,
        )
    except Exception as exc:  # noqa: BLE001 - malformed .prj must not traceback
        if json_out:
            print(json.dumps({"error": f"{type(exc).__name__}: {exc}"}, indent=2, ensure_ascii=False))
        else:
            print(f"Error: {exc}", file=sys.stderr)
        return 1

    if report_path:
        with open(report_path, "w", encoding="utf-8") as handle:
            json.dump(report, handle, indent=2, ensure_ascii=False)
    if json_out:
        print(json.dumps(report, indent=2, ensure_ascii=False))
    else:
        _print_text(report)

    if report.get("error"):
        return 1
    failed = report["summary"]["error"] + report["summary"]["missing"]
    return 1 if failed else 0
