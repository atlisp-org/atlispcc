#!/usr/bin/env python
"""本地字节比对 harness：atlispcc 编译 vs CAD golden（nested 样本）。

用法: python scripts/nested_compare.py <sample.lsp> [<golden.fas>]
比对 nsyms / seg0 / seg1(res_data_decrypted) 三项。
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from core.fas_core import parse_fas4
from compiler.cli import cmd_compile


def ours_parse(lsp: str):
    fas = "/tmp/opencode/nested-ours.fas"
    if os.path.exists(fas):
        os.remove(fas)
    try:
        cmd_compile(lsp, fas, opt_level=0, verify=False)
    except SystemExit as e:
        return {"error": f"compile-exit {e}"}
    except Exception as e:
        return {"error": f"compile-exc {type(e).__name__}: {e}"}
    if not os.path.exists(fas):
        return {"error": "no-output"}
    return parse_fas4(fas, decrypt_seg1=True)


def golden_parse(fas: str):
    return parse_fas4(fas, decrypt_seg1=True)


def cmp(a, b):
    diffs = []
    for key in ("nsyms",):
        if a.get(key) != b.get(key):
            diffs.append(f"{key} {a.get(key)}vs{b.get(key)}")
    if a.get("bytecode") != b.get("bytecode"):
        diffs.append(f"seg0 {len(a.get('bytecode',b''))}->{len(b.get('bytecode',b''))}")
    if a.get("res_data_decrypted") != b.get("res_data_decrypted"):
        diffs.append("seg1")
    return diffs


def main():
    lsp = sys.argv[1]
    golden = sys.argv[2] if len(sys.argv) > 2 else os.path.splitext(lsp)[0] + ".fas"
    ours = ours_parse(lsp)
    if "error" in ours:
        print("OURS ERROR:", ours["error"])
        return 1
    gold = golden_parse(golden)
    d = cmp(ours, gold)
    if not d:
        print("IDENTICAL  nsyms=%s seg0=%s seg1=%s" % (ours["nsyms"], len(ours["bytecode"]), len(ours["res_data_decrypted"])))
        return 0
    print("DIFF  " + ", ".join(d))
    return 1


if __name__ == "__main__":
    sys.exit(main())
