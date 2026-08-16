#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""kernel 逐文件对拍：atlispcc 编译 vs CAD 真机 (vlisp-compile 'st) 编译。

用法:
  python scripts/kernel_compare.py cad        # 仅 CAD 编译（生成 golden .fas）
  python scripts/kernel_compare.py ours       # 仅 atlispcc 编译（生成 ours .fas）
  python scripts/kernel_compare.py compare    # 逐字节比对 nsyms/seg0/seg1
  python scripts/kernel_compare.py all        # 依次执行 ours -> cad -> compare
"""
import json
import os
import re
import subprocess
import sys
import threading
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = "../kernel/src"
CAD_DIR = "/d/atlisp-test/kernel-cad-src"
OURS_DIR = "/d/atlisp-test/kernel-ours"
RESULT = "/d/atlisp-test/kernel-compare.json"


def collect_src():
    files = []
    for dp, _dn, ns in os.walk(SRC):
        for n in ns:
            if n.endswith(".lsp"):
                rel = os.path.relpath(os.path.join(dp, n), SRC).replace("\\", "/")
                files.append(rel)
    return sorted(files)


# ─── CAD 编译 ───────────────────────────────────────────────────────────────


class MCP:
    def __init__(self):
        self.proc = subprocess.Popen(
            ["atlisp-mcp", "--stdio", "--security-level", "relaxed"],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            bufsize=1, text=True, encoding="utf-8", errors="replace",
        )
        self._id = 0
        self._call("initialize", {"protocolVersion": "2024-11-05", "capabilities": {},
                                  "clientInfo": {"name": "kernel-compare", "version": "1"}})

    def _call(self, method, params):
        self._id += 1
        mid = self._id
        msg = {"jsonrpc": "2.0", "id": mid, "method": method, "params": params}
        self.proc.stdin.write(json.dumps(msg) + "\n")
        self.proc.stdin.flush()
        result = {}

        def _read():
            while True:
                line = self.proc.stdout.readline()
                if not line:
                    result["err"] = "EOF"
                    return
                try:
                    d = json.loads(line)
                except Exception:
                    continue
                if d.get("id") == mid:
                    result["data"] = d
                    return

        t = threading.Thread(target=_read, daemon=True)
        t.start()
        t.join(timeout=60)
        if t.is_alive():
            result["err"] = "timeout"
            try:
                self.proc.kill()
            except Exception:
                pass
            return None
        if "err" in result:
            return None
        d = result["data"]
        if "error" in d:
            return ("ERR", d["error"])
        return d.get("result")

    def eval(self, code):
        return self._call("tools/call", {"name": "eval_lisp_with_result",
                                          "arguments": {"code": code}})

    def close(self):
        try:
            self.proc.terminate()
            self.proc.wait(timeout=5)
        except Exception:
            try:
                self.proc.kill()
            except Exception:
                pass


def to_win_path(path):
    """Cygwin `/d/...` → Windows `D:/...`（CAD 是 Windows 程序，只认盘符路径）。"""
    path = path.replace("\\", "/")
    if path.startswith("/") and len(path) > 2 and path[2] == "/":
        return path[1].upper() + ":/" + path[3:]
    return path


def cad_compile_one(rel):
    """CAD vlisp-compile 单个文件。返回 (ok, msg)。"""
    lsp = to_win_path(os.path.join(CAD_DIR, rel))
    fas = os.path.splitext(lsp)[0] + ".fas"
    code = f'(vlisp-compile (quote st) "{lsp}" "{fas}")'
    p = MCP()
    try:
        r = p.eval(code)
    finally:
        p.close()
    if r is None:
        return False, "MCP timeout/EOF"
    if isinstance(r, tuple) and r[0] == "ERR":
        return False, f"MCP error: {r[1]}"
    txt = ""
    try:
        txt = r["content"][0]["text"]
    except Exception:
        pass
    if isinstance(r, dict) and r.get("isError"):
        return False, txt or "CAD error"
    return txt.strip().upper() == "T", (txt or "").strip()


def cmd_cad():
    files = collect_src()
    results = {}
    for i, rel in enumerate(files, 1):
        sys.stdout.write(f"[{i}/{len(files)}] {rel}: ")
        sys.stdout.flush()
        ok = False
        msg = ""
        for attempt in range(4):
            ok, msg = cad_compile_one(rel)
            if ok is not None:
                break
            sys.stdout.write(f"(retry{attempt + 1}) ")
            sys.stdout.flush()
            time.sleep(2)
        fas = os.path.join(CAD_DIR, os.path.splitext(rel)[0] + ".fas")
        size = os.path.getsize(fas) if os.path.exists(fas) else None
        results[rel] = {"ok": ok, "msg": msg, "size": size}
        print(f"ok={ok} size={size} msg={msg!r}")
    with open(RESULT, "w", encoding="utf-8") as fh:
        json.dump({"cad": results}, fh, ensure_ascii=False, indent=2)
    nok = sum(1 for v in results.values() if v["ok"])
    print(f"\nCAD DONE ok={nok}/{len(files)}")


# ─── atlispcc 编译 ──────────────────────────────────────────────────────────


def cmd_ours():
    files = collect_src()
    results = {}
    for i, rel in enumerate(files, 1):
        lsp = os.path.join(SRC, rel)
        fas = os.path.join(OURS_DIR, os.path.splitext(rel)[0] + ".fas")
        os.makedirs(os.path.dirname(fas), exist_ok=True)
        r = subprocess.run(
            [sys.executable, "-m", "compiler.cli", "compile", lsp, fas],
            capture_output=True, text=True, cwd=ROOT,
        )
        ok = r.returncode == 0 and os.path.exists(fas)
        results[rel] = {"ok": ok, "msg": r.stderr.strip()[:120]}
        print(f"[{i}/{len(files)}] {rel}: ok={ok}")
    with open(RESULT, "w", encoding="utf-8") as fh:
        json.dump({"ours": results}, fh, ensure_ascii=False, indent=2)
    nok = sum(1 for v in results.values() if v["ok"])
    print(f"\nOURS DONE ok={nok}/{len(files)}")


# ─── 比对 ───────────────────────────────────────────────────────────────────


def parse_fas(path):
    sys.path.insert(0, ROOT)
    from core.fas_core import parse_fas4
    try:
        p = parse_fas4(path, decrypt_seg1=True)
        return {
            "nsyms": p["nsyms"],
            "bytecode": p["bytecode"],
            "res_items": p["res_items"],
            "res_dec": p["res_data_decrypted"],
        }
    except Exception as e:
        return {"error": str(e)}


def cmd_compare():
    files = collect_src()
    results = {}
    for i, rel in enumerate(files, 1):
        cad_fas = os.path.join(CAD_DIR, os.path.splitext(rel)[0] + ".fas")
        our_fas = os.path.join(OURS_DIR, os.path.splitext(rel)[0] + ".fas")
        if not (os.path.exists(cad_fas) and os.path.exists(our_fas)):
            results[rel] = {"status": "MISSING"}
            print(f"[{i}/{len(files)}] {rel}: MISSING")
            continue
        a, b = parse_fas(cad_fas), parse_fas(our_fas)
        if "error" in a or "error" in b:
            results[rel] = {"status": "PARSE-ERR", "cad": a, "ours": b}
            print(f"[{i}/{len(files)}] {rel}: PARSE-ERR {a.get('error') or b.get('error')}")
            continue
        identical = (
            a["nsyms"] == b["nsyms"]
            and a["bytecode"] == b["bytecode"]
            and a["res_dec"] == b["res_dec"]
        )
        status = "IDENTICAL" if identical else "DIFF"
        results[rel] = {
            "status": status,
            "nsyms": (a["nsyms"], b["nsyms"]),
            "seg0": (len(a["bytecode"]), len(b["bytecode"])),
            "res": (a["res_items"], b["res_items"]),
        }
        print(f"[{i}/{len(files)}] {rel}: {status} nsyms={a['nsyms']}->{b['nsyms']} "
              f"seg0={len(a['bytecode'])}->{len(b['bytecode'])} res={a['res_items']}->{b['res_items']}")
    with open(RESULT, "w", encoding="utf-8") as fh:
        json.dump({"compare": results}, fh, ensure_ascii=False, indent=2)
    nid = sum(1 for v in results.values() if v.get("status") == "IDENTICAL")
    ndiff = sum(1 for v in results.values() if v.get("status") == "DIFF")
    print(f"\nCOMPARE DONE identical={nid} diff={ndiff}")


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "compare"
    if cmd == "cad":
        cmd_cad()
    elif cmd == "ours":
        cmd_ours()
    elif cmd == "compare":
        cmd_compare()
    elif cmd == "all":
        cmd_ours()
        cmd_cad()
        cmd_compare()
    else:
        print(__doc__)


if __name__ == "__main__":
    main()
