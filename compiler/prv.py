"""Visual LISP 应用程序规范（``.prv``）解析与 VLX 打包。

``.prv`` 由 VLIDE 生成，形状为（路径可用 ``/`` 或 ``\\``，值可带点对）：:

    (PRV-DEF (:target . "bin/myapp.vlx")
      (:active-x . T)
      (:separate-namespace . T)
      (:protected . T)
      (:load-file-list
        (:lsp "src/core.lsp")
        (:fas "lib/util.fas")
        (:prj "src/sub.prj"))
      (:require-file-list
        (:dcl "res/dialog.dcl")
        (:txt "res/readme.txt"))
      (:ob-directory)
      (:optimization . lsa))

打包规则：

- ``:load-file-list`` 决定 LOAD 顺序；``:lsp`` 现场编译成 ``<stem>.fas`` 后作为
  ``:fas`` 成员；``:fas`` 原样放入；``:prj`` 先编译工程（``:MERGED`` 时取合并产物）；
  ``:dcl`` 作为 ``:DCL`` 成员
- ``:require-file-list`` 只作为随包资源（按扩展名给 tag），不进 LOAD 清单
- ``:protected`` / ``:active-x`` / ``:separate-namespace`` 写入 LOAD 规格
- ``:optimization`` 为 ``st`` 时 ``-O0``，``lsm``/``lsa`` 时 ``-O1``
- 输出路径：``-o`` > ``:target``（相对 ``.prv`` 目录）> ``<prv 名>.vlx``

入口 :func:`parse_prv` / :func:`build_from_prv` / :func:`run_prv`。
"""

from __future__ import annotations

import contextlib
import io
import json
import os
import re
import sys
import tempfile
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from compiler.sexpr import args_of, head_name, text, truth

__all__ = ["PrvSpec", "parse_prv", "parse_prv_text", "build_from_prv", "run_prv"]

_DRIVE_RE = re.compile(r"^[A-Za-z]:[\\/]")


@dataclass
class PrvSpec:
    path: str = ""
    base_dir: str = ""
    target: Optional[str] = None
    active_x: bool = False
    separate_namespace: bool = False
    protected: bool = False
    optimization: str = "st"
    # (kind, path)：kind ∈ {'lsp', 'fas', 'prj', 'dcl'}
    load_list: List[Tuple[str, str]] = field(default_factory=list)
    require_list: List[Tuple[str, str]] = field(default_factory=list)
    diagnostics: List[str] = field(default_factory=list)

    @property
    def display_name(self) -> str:
        if self.target:
            return os.path.splitext(os.path.basename(self.target))[0]
        return os.path.splitext(os.path.basename(self.path))[0] or "application"


def _member_entries(items: List[Any], diagnostics: List[str]) -> List[Tuple[str, str]]:
    entries: List[Tuple[str, str]] = []
    for item in items:
        kind = head_name(item).lstrip(":").lower()
        values = args_of(item)
        path = text(values[0]) if values else None
        if not kind or path is None:
            diagnostics.append(f"unexpected file-list entry {item!r}; ignored")
            continue
        entries.append((kind, path))
    return entries


def parse_prv_text(source: str, path: str = "") -> PrvSpec:
    """解析 ``.prv`` 源码；缺少 ``(PRV-DEF ...)`` 根形式时抛 ``ValueError``。"""
    from compiler.parser import Parser

    spec = PrvSpec(
        path=path,
        base_dir=os.path.dirname(os.path.abspath(path)) if path else "",
    )
    program = Parser(source).parse()
    root = None
    for form in program.forms:
        if head_name(form).upper() == "PRV-DEF":
            root = form
            break
    if root is None:
        raise ValueError("not a Visual LISP application file: no (PRV-DEF ...) form")

    for item in args_of(root):
        key = head_name(item).lstrip(":").upper()
        values = args_of(item)
        value = values[0] if values else None
        if not key:
            spec.diagnostics.append(f"unexpected value {text(item)!r}; ignored")
            continue
        if key == "TARGET":
            spec.target = text(value)
        elif key == "ACTIVE-X":
            spec.active_x = bool(truth(value))
        elif key == "SEPARATE-NAMESPACE":
            spec.separate_namespace = bool(truth(value))
        elif key == "PROTECTED":
            spec.protected = bool(truth(value))
        elif key == "OPTIMIZATION":
            spec.optimization = (text(value) or "st").lower()
        elif key == "LOAD-FILE-LIST":
            spec.load_list = _member_entries(values, spec.diagnostics)
        elif key == "REQUIRE-FILE-LIST":
            spec.require_list = _member_entries(values, spec.diagnostics)
        elif key in ("OB-DIRECTORY", "TMP-DIRECTORY"):
            continue  # 编译中间目录，由打包器自行决定
        elif key == "GLOBALS-FILENAME":
            spec.diagnostics.append(f":globals-filename ({text(value)}) is not applied; ignored")
        else:
            spec.diagnostics.append(f":{key} is not applied; ignored")
    return spec


def parse_prv(path: str) -> PrvSpec:
    from core.fas_core import decode_source_text

    with open(path, "rb") as handle:
        return parse_prv_text(decode_source_text(handle.read()), path=path)


def _normalize(entry: str) -> str:
    return entry.replace("\\", "/")


def _resolve(base_dir: str, entry: str) -> str:
    entry = _normalize(entry)
    if os.path.isabs(entry) or _DRIVE_RE.match(entry):
        return entry
    return os.path.normpath(os.path.join(base_dir, entry))


def _cleanup(workdir: str, remove: bool) -> None:
    if not remove:
        return
    for dirpath, dirnames, filenames in os.walk(workdir, topdown=False):
        for filename in filenames:
            try:
                os.unlink(os.path.join(dirpath, filename))
            except OSError:
                pass
        for dirname in dirnames:
            try:
                os.rmdir(os.path.join(dirpath, dirname))
            except OSError:
                pass
    try:
        os.rmdir(workdir)
    except OSError:
        pass


def build_from_prv(
    prv_path: str,
    output: str = "",
    workdir: str = "",
    encoding: str = "ansi",
    date=None,
    salt=None,
    verbose: bool = False,
) -> Dict[str, Any]:
    """按 ``.prv`` 打包 VLX，返回可 JSON 序列化的报告（单成员失败不抛出）。"""
    from compiler.compile_cmd import cmd_compile
    from compiler.vlx_builder import (
        TAG_FAS4,
        VlxLoadSpec,
        VlxMember,
        encode_name,
        pack_vlx,
        tag_for_path,
    )

    spec = parse_prv(prv_path)
    report: Dict[str, Any] = {
        "prv": os.path.abspath(prv_path),
        "target": "",
        "encoding": encoding,
        "switches": {
            "protected": spec.protected,
            "active_x": spec.active_x,
            "separate_namespace": spec.separate_namespace,
            "optimization": spec.optimization,
        },
        "members": [],
        "compiled": [],
        "errors": [],
        "diagnostics": list(spec.diagnostics),
    }

    if not spec.load_list:
        report["errors"].append(":load-file-list is empty; nothing to pack")
        return report

    target = output or (
        _resolve(spec.base_dir, spec.target)
        if spec.target
        else os.path.join(spec.base_dir, spec.display_name + ".vlx")
    )
    report["target"] = os.path.abspath(target)

    cleanup_workdir = not workdir
    workdir = os.path.abspath(workdir) if workdir else tempfile.mkdtemp(prefix="atlispcc_prv_")
    os.makedirs(workdir, exist_ok=True)
    opt_level = 0 if spec.optimization in ("", "st") else 1

    members: List[VlxMember] = []
    load_entries: List[Tuple[str, str]] = []

    def add_member(payload: bytes, name: str, tag: int, load_key: Optional[str]) -> None:
        members.append(VlxMember(encode_name(name, encoding), tag, payload))
        report["members"].append({"name": name, "tag": tag, "size": len(payload)})
        if load_key:
            load_entries.append((load_key, name))

    def read_bytes(path: str) -> Optional[bytes]:
        try:
            with open(path, "rb") as handle:
                return handle.read()
        except OSError as exc:
            report["errors"].append(f"cannot read {path}: {exc}")
            return None

    for kind, entry in spec.load_list:
        src = _resolve(spec.base_dir, entry)
        if kind == "fas":
            if not os.path.isfile(src):
                report["errors"].append(f":fas member not found: {src}")
                continue
            payload = read_bytes(src)
            if payload is not None:
                add_member(payload, os.path.basename(src), TAG_FAS4, "fas")
        elif kind in ("dcl", "txt"):
            if not os.path.isfile(src):
                report["errors"].append(f":{kind} member not found: {src}")
                continue
            payload = read_bytes(src)
            if payload is not None:
                load_key = "DCL" if kind == "dcl" else None
                add_member(payload, os.path.basename(src), tag_for_path(src), load_key)
        elif kind == "lsp":
            if not os.path.isfile(src):
                report["errors"].append(f":lsp source not found: {src}")
                continue
            stem = os.path.splitext(os.path.basename(src))[0]
            fas_path = os.path.join(workdir, stem + ".fas")
            out_buf, err_buf = io.StringIO(), io.StringIO()
            try:
                with contextlib.redirect_stdout(out_buf), contextlib.redirect_stderr(err_buf):
                    cmd_compile(
                        src,
                        fas_path,
                        opt_level=opt_level,
                        encoding=encoding,
                        date=date,
                        salt=salt,
                    )
                payload = read_bytes(fas_path)
                if payload is None:
                    report["errors"].append(f"compiler produced no output for {src}")
                    continue
                report["compiled"].append({"source": src, "output": fas_path})
                add_member(payload, stem + ".fas", TAG_FAS4, "fas")
            except SystemExit as exc:
                report["errors"].append(
                    f"compile failed for {src} (exit {exc.code}): "
                    + (err_buf.getvalue() or out_buf.getvalue()).strip()[-2000:]
                )
            except Exception as exc:  # noqa: BLE001 - per-member failure is reported
                report["errors"].append(f"compile failed for {src}: {exc}")
        elif kind == "prj":
            if not os.path.isfile(src):
                report["errors"].append(f":prj project not found: {src}")
                continue
            from compiler.prj import compile_prj

            sub = compile_prj(
                src,
                outdir=os.path.join(workdir, os.path.splitext(os.path.basename(src))[0]),
                opt_level=opt_level,
                encoding=encoding,
                date=date,
                salt=salt,
            )
            report["diagnostics"].extend(sub.get("diagnostics", []))
            if sub.get("error"):
                report["errors"].append(f"{src}: {sub['error']}")
            merged = sub.get("merged", {})
            outputs = (
                [merged["output"]]
                if merged.get("status") == "ok"
                else [item["output"] for item in sub.get("files", []) if item["status"] == "ok"]
            )
            for path in outputs:
                payload = read_bytes(path)
                if payload is not None:
                    add_member(payload, os.path.basename(path), TAG_FAS4, "fas")
        else:
            report["diagnostics"].append(f":load-file-list entry :{kind} is not supported; ignored")

    for kind, entry in spec.require_list:
        src = _resolve(spec.base_dir, entry)
        if not os.path.isfile(src):
            report["errors"].append(f":{kind} resource not found: {src}")
            continue
        payload = read_bytes(src)
        if payload is not None:
            add_member(payload, os.path.basename(src), tag_for_path(src), None)

    if not members:
        report["errors"].append("no members were produced")
        _cleanup(workdir, cleanup_workdir)
        return report

    load_spec = VlxLoadSpec(
        protected=spec.protected,
        active_x=spec.active_x,
        separate_namespace=spec.separate_namespace,
        entries=load_entries,
    )
    data = pack_vlx([VlxMember.load(load_spec.render(encoding))] + members)
    try:
        os.makedirs(os.path.dirname(os.path.abspath(target)) or ".", exist_ok=True)
        with open(target, "wb") as handle:
            handle.write(data)
    except OSError as exc:
        report["errors"].append(f"cannot write {target}: {exc}")
        _cleanup(workdir, cleanup_workdir)
        return report

    _cleanup(workdir, cleanup_workdir)
    report["size"] = len(data)
    if verbose:
        report["products"] = [
            {"name": item["name"], "tag": item["tag"], "size": item["size"]} for item in report["members"]
        ]
    return report


def _print_report(report: Dict[str, Any]) -> None:
    print(f"PRV: {report['prv']}")
    switches = report["switches"]
    enabled = [name for name in ("protected", "active-x", "separate-namespace") if switches.get(name.replace("-", "_"))]
    print(f"Switches: {', '.join(enabled) if enabled else 'none'}  "
          f"optimization={switches['optimization']}")
    for message in report.get("diagnostics", []):
        print(f"[note]    {message}")
    for item in report.get("members", []):
        print(f"[member]  {item['name']}  tag={item['tag']}  size={item['size']}")
    for error in report.get("errors", []):
        print(f"[error]   {error}")
    if report.get("target") and os.path.isfile(report.get("target", "")):
        print(f"Built {report['target']} ({report.get('size', 0)} bytes)")


def run_prv(
    prv_path: str,
    output: str = "",
    workdir: str = "",
    encoding: str = "ansi",
    date=None,
    salt=None,
    json_out: bool = False,
    report_path: str = "",
) -> int:
    """打包 ``.prv`` 并打印报告。返回 shell 退出码。"""
    try:
        report = build_from_prv(
            prv_path,
            output=output,
            workdir=workdir,
            encoding=encoding,
            date=date,
            salt=salt,
        )
    except Exception as exc:  # noqa: BLE001 - malformed .prv must not traceback
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
        _print_report(report)
    return 1 if report.get("errors") else 0
