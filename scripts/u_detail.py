#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""查看指定函数在 CAD / CC 两侧的实际字节码对比。"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from core.fas_core import parse_fas4, build_mvar_tables, build_function_catalog
from decompiler.fas4_decompiler import Disassembler


def load(p):
    r = parse_fas4(p, decrypt_seg1=True)
    nsyms = r["nsyms"]
    bc = r["bytecode"]
    rg, fg = build_mvar_tables(r["res_data_decrypted"], nsyms)
    cat = build_function_catalog(rg, fg)
    dis = Disassembler(short_subr=nsyms <= 256)
    return r, dis.disassemble(bc, nsyms, sym_count=nsyms), cat


def func_by_name(insts, cat, name):
    offs = [o for n, o in cat if n == name]
    if not offs:
        return None, None
    off = offs[0]
    nxt = [i.offset for i in insts if i.op_name == "DEFUN" and i.offset > off]
    end = nxt[0] if nxt else 10 ** 9
    return off, [i for i in insts if off <= i.offset < end]


def main():
    names = sys.argv[1:] or ["@::EDIT-CONFIG", "@::CHECK-NEW-VERSION", "@::MAKE-MENU",
                             "@::ERROR-HANDLER", "@::COMPAT1", "@::MACRO-SUBST",
                             "@::SAFE-FORM-P", "@::SET-USER-INFO"]
    cad = load("/cygdrive/c/Users/vitalgg/@lisp/@lisp_u_cad.fas")
    cc = load("/cygdrive/c/Users/vitalgg/@lisp/@lisp_u_cc.fas")
    for name in names:
        print("############", name)
        for tag, d in [("CAD", cad), ("CC", cc)]:
            _, insts, cat = d
            off, body = func_by_name(insts, cat, name)
            print("=== %s @%s len=%s ===" % (tag, off, len(body) if body else None))
            if body:
                for i in body[:22]:
                    print("   %6d %-18s %s" % (i.offset, i.op_name, (getattr(i, "args", []) or [])))
        print()


if __name__ == "__main__":
    main()