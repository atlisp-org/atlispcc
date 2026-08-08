#!/usr/bin/env python
"""atlispcc 性能基准套件.

用法:
    python scripts/benchmark.py                 # 跑全部内置样本，输出基线报告
    python scripts/benchmark.py --json          # JSON 格式输出
    python scripts/benchmark.py --profile       # 用 cProfile 输出热点（首个样本）
    python scripts/benchmark.py --samples DIR   # 额外扫描目录下的 .lsp/.fas

输出: compile/decompile/link 各阶段耗时（秒）+ 相对基线改善率。
验收以相对改善率而非绝对秒数为准（环境噪声）。
"""
from __future__ import annotations

import argparse
import cProfile
import io
import json
import os
import pstats
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from compiler.cli import cmd_compile, cmd_decompile, cmd_link  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TESTS_CAD = os.path.join(ROOT, "tests", "cad")

# 内置基准样本：相对小但覆盖混合模式/复杂控制流的文件。
BUILTIN_SAMPLES = [
    ("i18n", os.path.join(TESTS_CAD, "i18n.lsp")),
    ("cadtest_v10", os.path.join(TESTS_CAD, "cadtest_v10.lsp")),
    ("cadtest_v17", os.path.join(TESTS_CAD, "cadtest_v17.lsp")),
]


def _glob_lsp(dirpath: str):
    out = []
    for root, _dirs, files in os.walk(dirpath):
        for fn in sorted(files):
            if fn.endswith(".lsp"):
                out.append(os.path.join(root, fn))
    return out


def timeit(fn, *args, **kwargs):
    t0 = time.perf_counter()
    result = fn(*args, **kwargs)
    dt = time.perf_counter() - t0
    return dt, result


def run_compile(src: str, tmpdir: str, opt: int) -> float:
    out = os.path.join(tmpdir, "out.fas")
    dt, _ = timeit(cmd_compile, src, out, opt_level=opt)
    return dt


def run_decompile(fas: str, tmpdir: str) -> float:
    out = os.path.join(tmpdir, "out.lsp")
    dt, _ = timeit(cmd_decompile, fas, out)
    return dt


def run_link(pairs, tmpdir: str) -> float:
    out = os.path.join(tmpdir, "linked.fas")
    dt, _ = timeit(cmd_link, list(pairs), out)
    return dt


def profile_compile(src: str, tmpdir: str) -> str:
    pr = cProfile.Profile()
    pr.enable()
    run_compile(src, tmpdir, 2)
    pr.disable()
    s = io.StringIO()
    ps = pstats.Stats(pr, stream=s).sort_stats("cumulative")
    ps.print_stats(25)
    return s.getvalue()


def main() -> int:
    ap = argparse.ArgumentParser(description="atlispcc 性能基准套件")
    ap.add_argument("--json", action="store_true", help="JSON 输出")
    ap.add_argument("--profile", action="store_true", help="cProfile 热点（首个样本）")
    ap.add_argument("--samples", default="", help="额外扫描的 .lsp 目录")
    ap.add_argument("--opt", type=int, default=2, help="编译优化级别（默认 2）")
    ap.add_argument("--baseline", default="", help="基线 JSON 文件（对比相对改善率）")
    args = ap.parse_args()

    samples = list(BUILTIN_SAMPLES)
    if args.samples:
        for fp in _glob_lsp(args.samples):
            samples.append((os.path.basename(fp)[:30], fp))

    results = {}
    with tempfile.TemporaryDirectory() as tmp:
        for name, src in samples:
            if not os.path.exists(src):
                results[name] = {"error": f"missing {src}"}
                continue
            entry = {}
            entry["compile_O0"] = run_compile(src, tmp, 0)
            entry["compile_O%d" % args.opt] = run_compile(src, tmp, args.opt)
            fas = os.path.join(tmp, name + ".fas")
            cmd_compile(src, fas, opt_level=0)
            entry["decompile"] = run_decompile(fas, tmp)
            results[name] = entry

    # 链接基准：i18n 拆件（若存在）两两链接；否则跳过。
    i18n_split = os.path.join(TESTS_CAD, "i18n_split")
    link_sources = [os.path.join(i18n_split, f) for f in sorted(os.listdir(i18n_split)) if f.endswith(".fas")]
    if len(link_sources) >= 2:
        with tempfile.TemporaryDirectory() as tmp:
            dt, _ = timeit(cmd_link, link_sources[:2], os.path.join(tmp, "l.fas"))
        results["link_i18n_split"] = {"link": dt}

    if args.profile and samples:
        with tempfile.TemporaryDirectory() as tmp:
            print(profile_compile(samples[0][1], tmp))

    baseline = {}
    if args.baseline and os.path.exists(args.baseline):
        with open(args.baseline, "r", encoding="utf-8") as f:
            baseline = json.load(f)

    if args.json:
        print(json.dumps(results, indent=2))
    else:
        print(f"{'sample':<22} {'-O0':>8} {'-O' + str(args.opt):>8} {'decompile':>12}  delta(O{args.opt})")
        for name, entry in results.items():
            if "error" in entry:
                print(f"{name:<22} {entry['error']}")
                continue
            dt = entry.get("compile_O0", 0) or 0
            dt2 = entry.get("compile_O%d" % args.opt, 0) or 0
            dc = entry.get("decompile", 0) or 0
            base = baseline.get(name, {}).get("compile_O%d" % args.opt)
            delta = f"{(dt2 - base) / base * 100:+.1f}%" if base else "-"
            print(f"{name:<22} {dt:8.3f} {dt2:8.3f} {dc:12.3f}  {delta}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
