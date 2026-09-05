#!/usr/bin/env python
"""详细单文件对拍：.lasm 文本 diff + 资源项 diff + nsyms。

用法:
  python scripts/fdiff.py std/addsupportpath.lsp
"""
import os, sys, difflib

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


def load_lasm(path):
    from asm.assembler import disassemble_fas
    return disassemble_fas(path)


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("rel", help="相对路径，如 std/addsupportpath.lsp")
    ap.add_argument("--src", default="../lib/src")
    ap.add_argument("--golden", default="tests/cad/lib_golden")
    ap.add_argument("--ours", default="/tmp/opencode/lib-ours")
    ap.add_argument("--items", action="store_true", help="打印双方资源项")
    ap.add_argument("--full", action="store_true", help="打印双方 .lasm 全文")
    args = ap.parse_args()

    gold_path = os.path.join(ROOT, args.golden, os.path.splitext(args.rel)[0] + ".fas")
    ours_path = os.path.join(ROOT, args.ours, os.path.splitext(args.rel)[0] + ".fas")

    g_lasm = load_lasm(gold_path).splitlines()
    o_lasm = load_lasm(ours_path).splitlines()

    from decompiler.fas4_decompiler import Fas4Parser
    g = Fas4Parser().parse(gold_path)
    o = Fas4Parser().parse(ours_path)

    print(f"=== {args.rel} ===")
    print(f"nsyms: gold={g.nsyms} ours={o.nsyms}  (bytecode len gold={len(g.bytecode)} ours={len(o.bytecode)})")

    if getattr(g, 'symbol_slots', None) and getattr(o, 'symbol_slots', None) and o.nsyms != g.nsyms:
        print("gold sym_slots:", [s[1] for s in g.symbol_slots])
        print("ours sym_slots:", [s[1] for s in o.symbol_slots])

    if args.items:
        gi = getattr(g, 'resource_items', None)
        oi = getattr(o, 'resource_items', None)
        if gi is not None and oi is not None:
            print("--- resource_items diff ---")
            n = max(len(gi), len(oi))
            for i in range(n):
                a = gi[i] if i < len(gi) else None
                b = oi[i] if i < len(oi) else None
                if a != b:
                    print(f"  item[{i}] gold={a!r}")
                    print(f"           ours={b!r}")

    if g_lasm != o_lasm:
        print("--- .lasm diff ---")
        for line in difflib.unified_diff(g_lasm, o_lasm, "gold", "ours", lineterm="", n=3):
            if line.startswith(("---", "+++", "@@")):
                continue
            print(" ", line)

    if args.full:
        print("================ GOLD .lasm ================")
        print("\n".join(g_lasm))
        print("================ OURS .lasm ================")
        print("\n".join(o_lasm))


if __name__ == "__main__":
    main()
