#!/usr/bin/env python3
"""检查 CAD golden .fas 是否仍与当前 .lsp 源一致（识别过期 golden）。

对每个 (.lsp, .fas) 对做符号/字符串集合一致性检查：
  S1  .fas 中的字符串源中不存在 → STALE（源删/改了字符串）
  S2  .fas 中的符号源中不存在（大小写归一化后，排除编译器注入符号） → STALE
  S3  源中非 quoted defun 名不在 .fas 符号集 → STALE（源新增/改名函数）
  其余 FRESH（附 mtime 提示）

用法：
  python scripts/check_golden_fresh.py [--src DIR] [--golden DIR]
                                       [--limit N] [--json] [--show-fresh]
"""

import argparse
import dataclasses
import datetime
import json
import re
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Set

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.fas_core import parse_fas4, parse_resource_stream, decode_source_text
from compiler.lexer import tokenize
from compiler.parser import Parser
from compiler.ast_nodes import Node, Defun
from compiler.resource_builder import _VLISP_CASE_PRESERVE
from compiler.cad_symbols import normalize_vla_name

_CANON = {c.lower(): c for c in _VLISP_CASE_PRESERVE}


def norm_sym(s: str) -> str:
    """源符号 → .fas 注册形式（镜像编译器管线：cad_symbols.normalize_vla_name
    + resource_builder._enc_sym 的字符串形式）。"""
    if s == "ads-cmd":
        return "ads-cmd"
    low = s.lower()
    if low in _CANON:
        return _CANON[low]
    if low.startswith(("vla-", "vlax-")):
        return normalize_vla_name(s)
    return s.upper()


_U_RE = re.compile(r"\\U\+([0-9A-Fa-f]{4})")


def unescape_u(s: str) -> str:
    """还原 .fas 字符串块中的 \\U+XXXX 转义（非 ANSI 字符的注册形式）。"""
    return _U_RE.sub(lambda m: chr(int(m.group(1), 16)), s)


_INJECTED_SRC = [
    "kwote", "_al-bind-alist", "ads-cmd", "vl-ACAD-defun", "vl-acad-defun",
    "-lambda-", "collect-init", "collect-next", "collect-release",
    "fas-polar1", "fas-rtos1", "fas-rtos3", "fas-getvar2", "fas-getvar3",
    "quote",
]
INJECTED: Set[str] = set(_INJECTED_SRC) | {norm_sym(n) for n in _INJECTED_SRC}


def collect_defuns(node: Node, out: Set[str]) -> None:
    if isinstance(node, Defun) and not node.quoted:
        out.add(norm_sym(node.name))
    for f in dataclasses.fields(node):
        v = getattr(node, f.name)
        if isinstance(v, Node):
            collect_defuns(v, out)
        elif isinstance(v, (list, tuple)):
            for item in v:
                if isinstance(item, Node):
                    collect_defuns(item, out)


@dataclass
class SrcInfo:
    strings: Set[str] = field(default_factory=set)
    symbols: Set[str] = field(default_factory=set)
    defuns: Set[str] = field(default_factory=set)
    warning: str = ""


def extract_source(path: Path) -> SrcInfo:
    info = SrcInfo()
    try:
        text = decode_source_text(path.read_bytes())
    except Exception as e:
        info.warning = f"read: {e}"
        return info
    try:
        for kind, val, _l, _c in tokenize(text):
            if kind == "STRING":
                info.strings.add(val)
            elif kind == "SYMBOL":
                info.symbols.add(norm_sym(val))
    except Exception as e:
        info.warning = f"lex: {e}"
        return info
    try:
        collect_defuns(Parser(text).parse(), info.defuns)
    except Exception as e:
        info.warning = f"parse: {e}"
        for m in re.finditer(r"\(\s*defun\s+([^\s()]+)", text):
            info.defuns.add(norm_sym(m.group(1)))
    return info


@dataclass
class FasInfo:
    strings: Set[str] = field(default_factory=set)
    symbols: Set[str] = field(default_factory=set)


def extract_fas(path: Path) -> FasInfo:
    data = parse_fas4(str(path))
    _items, syms, strs = parse_resource_stream(data["res_data_decrypted"])
    return FasInfo(strings={unescape_u(s) for s in strs}, symbols=set(syms))


def check_pair(src: Path, fas: Path) -> Dict:
    result = {
        "src": src.name,
        "state": "FRESH",
        "s1": [],
        "s2": [],
        "s3": [],
        "warning": "",
        "src_mtime": src.stat().st_mtime,
        "fas_mtime": fas.stat().st_mtime,
    }
    try:
        si = extract_source(src)
        fi = extract_fas(fas)
    except Exception as e:
        result["state"] = "ERROR"
        result["warning"] = str(e)
        return result
    if si.warning:
        result["warning"] = si.warning
    s1 = sorted(fi.strings - si.strings)
    s2 = sorted(fi.symbols - si.symbols - INJECTED)
    s3 = sorted(si.defuns - fi.symbols)
    result["s1"], result["s2"], result["s3"] = s1, s2, s3
    if s1 or s2 or s3:
        result["state"] = "STALE"
    return result


def fmt_mtime(ts: float) -> str:
    return datetime.datetime.fromtimestamp(ts).strftime("%m-%d %H:%M")


def main() -> int:
    ap = argparse.ArgumentParser(description="检查 CAD golden .fas 是否过期")
    ap.add_argument("--src", default="../lib/src")
    ap.add_argument("--golden", default="tests/cad/lib_golden")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--show-fresh", action="store_true")
    args = ap.parse_args()

    src_root = Path(args.src).resolve()
    golden_root = Path(args.golden).resolve()

    pairs = []
    for fas in sorted(golden_root.rglob("*.fas")):
        rel = fas.relative_to(golden_root).with_suffix(".lsp")
        src = src_root / rel
        pairs.append((src, fas, str(rel)))

    if args.limit:
        pairs = pairs[: args.limit]

    t0 = time.time()
    results = []
    for src, fas, rel in pairs:
        if not src.exists():
            results.append({
                "src": rel, "state": "MISSING_SRC",
                "s1": [], "s2": [], "s3": [], "warning": "",
            })
            continue
        r = check_pair(src, fas)
        r["src"] = rel
        results.append(r)

    stale = [r for r in results if r["state"] == "STALE"]
    fresh = [r for r in results if r["state"] == "FRESH"]
    errors = [r for r in results if r["state"] == "ERROR"]
    missing = [r for r in results if r["state"] == "MISSING_SRC"]

    if args.json:
        print(json.dumps(results, ensure_ascii=False, indent=1))
    else:
        for r in results:
            if r["state"] == "FRESH" and not args.show_fresh:
                continue
            print(f"{r['state']:>12}  {r['src']}")
            if r["s1"]:
                print(f"              S1 fas-only strings: {r['s1'][:12]}")
            if r["s2"]:
                print(f"              S2 fas-only symbols: {r['s2'][:12]}")
            if r["s3"]:
                print(f"              S3 src-only defuns : {r['s3'][:12]}")
            if r["warning"]:
                print(f"              warn: {r['warning']}")
            if "src_mtime" in r:
                newer = "src>golden" if r["src_mtime"] > r["fas_mtime"] else "golden>=src"
                print(f"              mtime src={fmt_mtime(r['src_mtime'])} golden={fmt_mtime(r['fas_mtime'])} ({newer})")
        print()
        print(f"total={len(results)}  STALE={len(stale)}  FRESH={len(fresh)}  "
              f"ERROR={len(errors)}  MISSING_SRC={len(missing)}  ({time.time() - t0:.1f}s)")
        if stale:
            print("stale files:")
            for r in stale:
                print(f"  {r['src']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())