#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""本地对拍：编译 kernel dialog.lsp / panel.lsp 并与仓库 golden 逐字节比对。"""
import os
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from core.fas_core import parse_fas4  # noqa: E402

PAIRS = [
    ("../kernel/src/sub-system/config/dialog.lsp", "tests/cad/kernel_golden/sub-system/config/dialog.fas"),
    ("../kernel/src/sub-system/ui/panel.lsp", "tests/cad/kernel_golden/sub-system/ui/panel.fas"),
]


def hx(a: bytes, b: bytes, label: str) -> None:
    n = max(len(a), len(b))
    diffs = [i for i in range(n) if i >= len(a) or i >= len(b) or a[i] != b[i]]
    print(f"  {label}: len ours={len(a)} golden={len(b)} diffs={len(diffs)}")
    if diffs:
        # 分组成连续区间
        groups, start, prev = [], diffs[0], diffs[0]
        for d in diffs[1:]:
            if d == prev + 1:
                prev = d
            else:
                groups.append((start, prev))
                start = prev = d
        groups.append((start, prev))
        for s, e in groups:
            oa = a[s : e + 1].hex(" ")
            ob = b[s : e + 1].hex(" ")
            print(f"    @{s:#06x}..{e:#06x} ours  = {oa}")
            print(f"               golden= {ob}")


def main() -> None:
    for src, golden in PAIRS:
        name = os.path.basename(src)
        print(f"=== {name} ===")
        with tempfile.TemporaryDirectory() as td:
            out = os.path.join(td, "ours.fas")
            subprocess.run(
                [sys.executable, "-m", "compiler.cli", "compile", "-O0", src, out],
                cwd=ROOT, check=True,
            )
            ours = parse_fas4(out)
            cad = parse_fas4(golden)
        print(f"  nsyms: ours={ours['nsyms']} golden={cad['nsyms']}")
        hx(ours["bytecode"], cad["bytecode"], "seg0")
        hx(ours["res_data_decrypted"], cad["res_data_decrypted"], "seg1")
        print()


if __name__ == "__main__":
    main()