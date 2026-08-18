#!/usr/bin/env python
"""kernel 逐文件对拍：atlispcc 本地编译 vs CAD 真机（HTTP MCP）编译。

用法:
  python scripts/kernel_compare_http.py cad          # 仅 CAD 编译（生成 golden .fas 到 W:/.../kernel_golden/）
  python scripts/kernel_compare_http.py ours         # 仅 atlispcc 编译（生成本地 ours .fas）
  python scripts/kernel_compare_http.py compare      # 逐字节比对 nsyms/seg0/seg1（需 golden 已同步回本地）
"""
import glob
import json
import os
import subprocess
import sys
import time
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "..", "kernel", "src")
MCP_URL = "http://192.168.1.210:8110/mcp"
GOLDEN_DIR = os.path.join(ROOT, "tests", "cad", "kernel_golden")
OURS_DIR = "/tmp/opencode/kernel-ours"


def collect_src():
    files = []
    for dp, _dn, ns in os.walk(SRC):
        for n in ns:
            if n.endswith(".lsp"):
                rel = os.path.relpath(os.path.join(dp, n), SRC).replace("\\", "/")
                files.append(rel)
    return sorted(files)


def mcp_call(name, arguments, timeout=120):
    req = {
        "jsonrpc": "2.0", "id": 1, "method": "tools/call",
        "params": {"name": name, "arguments": arguments},
    }
    data = json.dumps(req).encode("utf-8")
    r = urllib.request.urlopen(urllib.request.Request(
        MCP_URL, data=data, headers={"Content-Type": "application/json"}),
        timeout=timeout)
    obj = json.loads(r.read().decode("utf-8"))
    result = obj.get("result", {})
    texts = []
    for c in result.get("content", []):
        if c.get("type") == "text":
            texts.append(c.get("text", ""))
    return {"output": "\n".join(texts), "isError": result.get("isError", False)}


def cad_compile_all():
    files = collect_src()
    ok = 0
    fail = []
    for rel in files:
        lsp = "W:/atlisp/kernel/src/" + rel
        fas = "W:/atlisp/atlispcc/tests/cad/kernel_golden/" + os.path.splitext(rel)[0] + ".fas"
        code = '(vlisp-compile (quote st) "%s" "%s")' % (lsp, fas)
        try:
            r = mcp_call("eval_lisp_with_result", {"code": code})
            if r["output"].strip() == "T":
                ok += 1
            else:
                fail.append((rel, r["output"].strip()[:60]))
        except Exception as e:
            fail.append((rel, f"EXC {e}"))
        time.sleep(0.3)
    print(f"CAD compile: OK={ok} FAIL={len(fail)}")
    for rel, msg in fail:
        print("  ", rel, "::", msg)


def ours_compile_all():
    files = collect_src()
    os.makedirs(OURS_DIR, exist_ok=True)
    ok = 0
    fail = []
    for rel in files:
        src = os.path.join(SRC, rel)
        out = os.path.join(OURS_DIR, os.path.splitext(rel)[0] + ".fas")
        os.makedirs(os.path.dirname(out), exist_ok=True)
        r = subprocess.run(
            [sys.executable, "-m", "compiler.cli", "compile", src, out],
            capture_output=True, text=True)
        if r.returncode == 0:
            ok += 1
        else:
            fail.append((rel, r.stderr.strip()[-120:]))
    print(f"atlispcc compile: OK={ok} FAIL={len(fail)}")
    for rel, msg in fail:
        print("  ", rel, "::", msg)


def compare_all():
    files = collect_src()
    identical = []
    diff = []
    for rel in files:
        golden = os.path.join(GOLDEN_DIR, os.path.splitext(rel)[0] + ".fas")
        ours = os.path.join(OURS_DIR, os.path.splitext(rel)[0] + ".fas")
        if not (os.path.exists(golden) and os.path.exists(ours)):
            diff.append((rel, "missing golden/ours"))
            continue
        from decompiler.fas4_decompiler import Fas4Parser
        g = Fas4Parser().parse(golden)
        o = Fas4Parser().parse(ours)
        if (o.nsyms == g.nsyms and o.bytecode == g.bytecode
                and o.resource_items == g.resource_items):
            identical.append(rel)
        else:
            n_diff = o.nsyms != g.nsyms
            s_diff = o.bytecode != g.bytecode
            r_diff = o.resource_items != g.resource_items
            where = []
            if n_diff:
                where.append(f"nsyms {o.nsyms}vs{g.nsyms}")
            if s_diff:
                where.append("seg0")
            if r_diff:
                where.append("seg1")
            diff.append((rel, ",".join(where)))
    print(f"=== byte-identity: IDENTICAL={len(identical)} DIFF={len(diff)} ===")
    print("IDENTICAL:", ", ".join(identical))
    print("--- DIFF ---")
    for rel, why in diff:
        print(f"  {rel}: {why}")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "compare"
    if cmd == "cad":
        cad_compile_all()
    elif cmd == "ours":
        ours_compile_all()
    elif cmd == "compare":
        compare_all()
    else:
        print(__doc__)
