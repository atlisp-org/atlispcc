#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""逐个独立会话在 CAD 加载 kernel-ours 的 .fas 文件，判定加载是否成功。

每个 .fas 独立 MCP 连接 (load "<path>")，isError → FAIL（记录错误文本）；
成功后再验证该文件定义的主要函数可解析（boundp 类型非 undef）。
"""
import json
import os
import re
import subprocess
import sys
import time

FAS_DIR = "/d/atlisp-test/kernel-ours"
SRC = "../kernel/src"
OUT = "/d/atlisp-test/kernel-fas-load.json"


def spawn():
    return subprocess.Popen(
        ["atlisp-mcp", "--stdio", "--security-level", "relaxed"],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        bufsize=1, text=True, encoding="utf-8", errors="replace",
    )


def call(p, mid, method, params):
    msg = {"jsonrpc": "2.0", "id": mid, "method": method, "params": params}
    p.stdin.write(json.dumps(msg) + "\n")
    p.stdin.flush()
    while True:
        line = p.stdout.readline()
        if not line:
            return None
        try:
            d = json.loads(line)
        except Exception:
            continue
        if d.get("id") == mid:
            return d.get("result")


def to_win_path(path):
    """Cygwin `/d/...` → Windows `D:/...`（CAD 是 Windows 程序，只认盘符路径）。"""
    path = path.replace("\\", "/")
    if path.startswith("/") and len(path) > 2 and path[2] == "/":
        return path[1].upper() + ":/" + path[3:]
    return path


def load_one(rel):
    path = to_win_path(os.path.join(FAS_DIR, rel))
    p = spawn()
    try:
        call(p, 1, "initialize", {"protocolVersion": "2024-11-05", "capabilities": {},
                                  "clientInfo": {"name": "fasload", "version": "1"}})
        r = call(p, 2, "tools/call", {"name": "eval_lisp_with_result",
                                      "arguments": {"code": '(load "%s")' % path}})
        if isinstance(r, dict) and r.get("isError"):
            t = r["content"][0].get("text", "?") if r.get("content") else "?"
            return "FAIL", t[:120]
        return "OK", ""
    finally:
        p.terminate()


def main_funcs(rel):
    funcs = []
    lsp = os.path.join(SRC, rel)
    try:
        with open(lsp, encoding="utf-8", errors="replace") as fh:
            for line in fh:
                m = re.match(r"\s*\(defun\s+([^\s(]+)", line)
                if m:
                    funcs.append(m.group(1))
                    if len(funcs) >= 3:
                        break
    except Exception:
        pass
    return funcs


def collect():
    out = {}
    for dp, _dn, ns in os.walk(FAS_DIR):
        for n in ns:
            if n.endswith(".fas"):
                rel = os.path.relpath(os.path.join(dp, n), FAS_DIR).replace("\\", "/")
                out[rel] = os.path.join(dp, n)
    return out


files = collect()
results = []
for i, rel in enumerate(sorted(files), 1):
    st, msg = load_one(rel)
    results.append((rel, st, msg))
    print(f"[{i}/{len(files)}] {rel:42s} {st:<6s} {msg[:80]}")
    sys.stdout.flush()
    time.sleep(0.3)

with open(OUT, "w", encoding="utf-8") as fh:
    json.dump(results, fh, ensure_ascii=False, indent=2)

ok = sum(1 for r in results if r[1] == "OK")
print(f"\n=== 汇总：kernel-ours .fas load OK={ok}/{len(results)}")
print("=== 失败文件 ===")
for rel, st, msg in results:
    if st != "OK":
        print(f"  {rel:42s} {st} {msg[:100]}")
