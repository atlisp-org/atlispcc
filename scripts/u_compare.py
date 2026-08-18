#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""@lisp_u CAD vs atlispcc 逐函数对拍。

按 DEFUN 边界切分 seg0，按函数名配对逐函数比对字节码（规避 offset 错位）。
输出：一致函数、不一致函数及首处差异、仅单边存在的函数。
用法: python scripts/u_compare.py <cad.fas> <cc.fas> [--detail]
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from core.fas_core import parse_fas4, build_mvar_tables, build_function_catalog
from decompiler.fas4_decompiler import Disassembler


def load(path):
    r = parse_fas4(path, decrypt_seg1=True)
    nsyms = r["nsyms"]
    bc = r["bytecode"]
    rg, fg = build_mvar_tables(r["res_data_decrypted"], nsyms)
    cat = build_function_catalog(rg, fg)
    dis = Disassembler(short_subr=nsyms <= 256)
    insts = dis.disassemble(bc, nsyms, sym_count=nsyms)
    return r, insts, cat


def split_functions(insts):
    funcs = []
    cur = None
    for i in insts:
        if i.op_name == "DEFUN":
            if cur:
                funcs.append(cur)
            cur = {"start": i.offset, "insts": []}
        if cur is not None:
            cur["insts"].append(i)
    if cur:
        funcs.append(cur)
    return funcs


def fmt(i):
    args = " ".join(str(x) for x in (getattr(i, "args", None) or []))
    return f"{i.op_name} {args}".rstrip()


def name_of(cat, start):
    for n, o in cat:
        if o == start:
            return n
    return None


def main():
    args = sys.argv[1:]
    cad_path, cc_path = args[0], args[1]
    detail = "--detail" in args
    a_r, a_i, a_cat = load(cad_path)
    b_r, b_i, b_cat = load(cc_path)

    fa = split_functions(a_i)
    fb = split_functions(b_i)

    # name -> list of starts, 处理重名
    def build_name_index(cat, funcs):
        idx = {}
        start2name = {}
        for n, o in cat:
            start2name[o] = n
        for f in funcs:
            n = start2name.get(f["start"], f"__anon@{f['start']}")
            idx.setdefault(n, []).append(f)
        return idx

    ia = build_name_index(a_cat, fa)
    ib = build_name_index(b_cat, fb)

    print("== 概览 ==")
    print(f"  CAD: nsyms={a_r['nsyms']} seg0={len(a_r['bytecode'])} funcs={len(fa)}")
    print(f"  CC : nsyms={b_r['nsyms']} seg0={len(b_r['bytecode'])} funcs={len(fb)}")

    same, diff, only_a, only_b = [], [], [], []
    used_b = set()

    # 1) 有名函数按名配对
    for name, fa_list in sorted(ia.items()):
        if name.startswith("__anon"):
            continue
        fb_list = [f for f in ib.get(name, []) if f["start"] not in used_b]
        for i, f in enumerate(fa_list):
            if i < len(fb_list):
                g = fb_list[i]
                used_b.add(g["start"])
                ai = [fmt(x) for x in f["insts"]]
                bi = [fmt(x) for x in g["insts"]]
                if ai == bi:
                    same.append((name, f["start"]))
                else:
                    first = next((k for k in range(max(len(ai), len(bi)))
                                  if k >= len(ai) or k >= len(bi) or ai[k] != bi[k]), None)
                    diff.append((name, f["start"], f"len {len(ai)}->{len(bi)} first_diff#{first}"))
            else:
                only_a.append((name, f["start"]))

    # 2) 剩余函数（匿名 __anon@… / -lambda- / 未配对的）按出现顺序配对
    used_b2 = set(used_b)
    rest_a = []
    rest_b = []
    matched_a = {s for _, s in same} | {s for _, s, _ in diff} | {s for _, s in only_a}
    for name, fa_list in sorted(ia.items()):
        for f in fa_list:
            if f["start"] not in matched_a:
                rest_a.append(f)
    for name, fb_list in sorted(ib.items()):
        for f in fb_list:
            if f["start"] not in used_b2:
                rest_b.append(f)
    # 剩余按顺序配对
    for f, g in zip(rest_a, rest_b):
        ai = [fmt(x) for x in f["insts"]]
        bi = [fmt(x) for x in g["insts"]]
        name = f"__seq@{f['start']}"
        if ai == bi:
            same.append((name, f["start"]))
        else:
            first = next((k for k in range(max(len(ai), len(bi)))
                          if k >= len(ai) or k >= len(bi) or ai[k] != bi[k]), None)
            diff.append((name, f["start"], f"len {len(ai)}->{len(bi)} first_diff#{first}"))
    if len(rest_a) > len(rest_b):
        for f in rest_a[len(rest_b):]:
            only_a.append((f"__seq@{f['start']}", f["start"]))
    if len(rest_b) > len(rest_a):
        for f in rest_b[len(rest_a):]:
            only_b.append((f"__seq@{f['start']}", f["start"]))

    print(f"\n== 函数 ==")
    print(f"  一致: {len(same)}   不一致: {len(diff)}")
    print(f"  仅 CAD 有: {len(only_a)}   仅 CC 有: {len(only_b)}")
    if only_a:
        print("\n  -- 仅 CAD 有 --")
        for name, start in only_a[:60]:
            print(f"    CAD {name} @{start}")
        if len(only_a) > 60:
            print(f"    ... 共 {len(only_a)} 个")
    if only_b:
        print("\n  -- 仅 CC 有 --")
        for name, start in only_b[:40]:
            print(f"    CC  {name} @{start}")
        if len(only_b) > 40:
            print(f"    ... 共 {len(only_b)} 个")
    print("\n  -- 不一致（首 60）--")
    for name, start, info in diff[:60]:
        print(f"    DIFF {name} @{start}  {info}")
    if len(diff) > 60:
        print(f"    ... 共 {len(diff)} 处")
    if detail:
        print("\n-- 一致函数 --")
        for name, start in same:
            print(f"  OK   {name} @{start}")


if __name__ == "__main__":
    main()