#!/usr/bin/env python
"""批量对拍：atlispcc 本地编译 vs CAD 真机（HTTP MCP）编译。

支持任意源目录，用于测试 lib/kernel/packages 下的 .lsp 文件。

用法:
  # 1. 用 CAD 编译生成 golden .fas（需要 CAD 真机连接）
  python scripts/batch_compare.py cad --src ../lib/src --golden tests/cad/lib_golden --cad-root W:/atlisp/lib/src

  # 2. 用 atlispcc 编译生成 ours .fas
  python scripts/batch_compare.py ours --src ../lib/src --ours /tmp/opencode/lib-ours

  # 3. 逐字节比对
  python scripts/batch_compare.py compare --src ../lib/src --golden tests/cad/lib_golden --ours /tmp/opencode/lib-ours

  # 快速测试（编译+对比）
  python scripts/batch_compare.py auto --src ../lib/src --golden tests/cad/lib_golden --cad-root W:/atlisp/lib/src

参数说明:
  --src         源 .lsp 文件目录（相对于 atlispcc 根目录）
  --golden      CAD 编译产物目录（用于 byte-identity 对比）
  --ours        atlispcc 编译产物目录（临时）
  --cad-root    CAD 端 .lsp 文件的根路径（Windows 路径，用于 vlisp-compile）
  --mcp-url     MCP 服务器地址（默认 http://192.168.1.210:8110/mcp）
"""
import argparse
import json
import os
import subprocess
import sys
import time
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MCP_URL = "http://192.168.1.210:8110/mcp"


def collect_src(src_dir):
    """收集源目录下所有 .lsp 文件，返回相对路径列表"""
    files = []
    for dp, _dn, ns in os.walk(src_dir):
        for n in ns:
            if n.endswith(".lsp"):
                rel = os.path.relpath(os.path.join(dp, n), src_dir).replace("\\", "/")
                files.append(rel)
    return sorted(files)


def mcp_call(name, arguments, mcp_url=MCP_URL, timeout=300, retries=3):
    """调用 MCP 服务器（带重试）"""
    req = {
        "jsonrpc": "2.0", "id": 1, "method": "tools/call",
        "params": {"name": name, "arguments": arguments},
    }
    data = json.dumps(req).encode("utf-8")
    last_err = None
    for attempt in range(retries):
        try:
            r = urllib.request.urlopen(urllib.request.Request(
                mcp_url, data=data, headers={"Content-Type": "application/json"}),
                timeout=timeout)
            body = r.read().decode("utf-8")
            obj = json.loads(body)
            result = obj.get("result", {})
            texts = []
            for c in result.get("content", []):
                if c.get("type") == "text":
                    texts.append(c.get("text", ""))
            return {"output": "\n".join(texts), "isError": result.get("isError", False)}
        except Exception as e:
            last_err = e
            if attempt < retries - 1:
                time.sleep(5)
    raise last_err


def _local_to_cad_path(local_path):
    """将本地绝对路径转为 CAD Windows 路径（~/atlisp/ → W:/atlisp/）"""
    abs_path = os.path.abspath(local_path)
    # 共享根: /home/vitalgg/atlisp ↔ W:/atlisp
    home_atlisp = os.path.expanduser("~/atlisp")
    if abs_path.startswith(home_atlisp):
        rest = abs_path[len(home_atlisp):]  # e.g. "/atlispcc/tests/cad/..."
        return "W:/atlisp" + rest.replace("\\", "/")
    return abs_path.replace("\\", "/")


def cad_compile_all(src_dir, golden_dir, cad_root, mcp_url):
    """用 CAD 真机编译所有 .lsp 文件生成 golden .fas（跳过输出已是最新）"""
    files = collect_src(src_dir)
    os.makedirs(golden_dir, exist_ok=True)
    ok = 0
    skip = 0
    fail = []
    for rel in files:
        lsp = cad_root.replace("\\", "/") + "/" + rel
        fas = os.path.join(golden_dir, os.path.splitext(rel)[0] + ".fas")
        os.makedirs(os.path.dirname(fas), exist_ok=True)
        # 源文件在本地可用 mtime 判断（W:/ 与 ~/ 共享目录）
        local_lsp = os.path.join(src_dir, rel)
        if os.path.exists(fas) and os.path.exists(local_lsp) \
                and os.path.getmtime(fas) >= os.path.getmtime(local_lsp):
            skip += 1
            print(f"  [SKIP] {rel}")
            continue
        fas_cad = _local_to_cad_path(fas)
        code = '(vlisp-compile (quote st) "%s" "%s")' % (lsp, fas_cad)
        try:
            r = mcp_call("eval_lisp_with_result", {"code": code}, mcp_url)
            if r["output"].strip() == "T":
                ok += 1
                print(f"  [OK] {rel}")
            else:
                fail.append((rel, r["output"].strip()[:80]))
                print(f"  [FAIL] {rel}: {r['output'].strip()[:60]}")
        except Exception as e:
            fail.append((rel, f"EXC {e}"))
            print(f"  [ERROR] {rel}: {e}")
        time.sleep(0.3)
    print(f"\nCAD compile: OK={ok} SKIP={skip} FAIL={len(fail)}")
    for rel, msg in fail:
        print("  ", rel, "::", msg)
    return ok, fail


def ours_compile_all(src_dir, ours_dir):
    """用 atlispcc 编译所有 .lsp 文件（跳过输出已是最新）"""
    files = collect_src(src_dir)
    os.makedirs(ours_dir, exist_ok=True)
    ok = 0
    skip = 0
    fail = []
    for rel in files:
        src = os.path.join(src_dir, rel)
        out = os.path.join(ours_dir, os.path.splitext(rel)[0] + ".fas")
        os.makedirs(os.path.dirname(out), exist_ok=True)
        if os.path.exists(out) and os.path.getmtime(out) >= os.path.getmtime(src):
            skip += 1
            print(f"  [SKIP] {rel}")
            continue
        r = subprocess.run(
            [sys.executable, "-m", "compiler.cli", "compile", src, out],
            capture_output=True, text=True, cwd=ROOT)
        if r.returncode == 0:
            ok += 1
            print(f"  [OK] {rel}")
        else:
            fail.append((rel, r.stderr.strip()[-120:]))
            print(f"  [FAIL] {rel}: {r.stderr.strip()[-80:]}")
    print(f"\natlispcc compile: OK={ok} SKIP={skip} FAIL={len(fail)}")
    for rel, msg in fail:
        print("  ", rel, "::", msg)
    return ok, fail


def compare_all(src_dir, golden_dir, ours_dir):
    """逐字节比对 atlispcc 编译产物与 CAD golden"""
    files = collect_src(src_dir)
    sys.path.insert(0, ROOT)
    from decompiler.fas4_decompiler import Fas4Parser

    identical = []
    diff = []
    missing = []

    for rel in files:
        golden = os.path.join(golden_dir, os.path.splitext(rel)[0] + ".fas")
        ours = os.path.join(ours_dir, os.path.splitext(rel)[0] + ".fas")
        if not os.path.exists(golden):
            missing.append((rel, "golden"))
            continue
        if not os.path.exists(ours):
            missing.append((rel, "ours"))
            continue
        try:
            g = Fas4Parser().parse(golden)
            o = Fas4Parser().parse(ours)
        except Exception as e:
            diff.append((rel, f"PARSE_ERROR: {e}"))
            continue

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

    print(f"\n=== byte-identity: IDENTICAL={len(identical)} DIFF={len(diff)} MISSING={len(missing)} ===")
    if identical:
        print("IDENTICAL:", ", ".join(identical))
    if missing:
        print("--- MISSING ---")
        for rel, what in missing:
            print(f"  {rel}: {what}")
    if diff:
        print("--- DIFF ---")
        for rel, why in diff:
            print(f"  {rel}: {why}")
    return identical, diff, missing


def main():
    parser = argparse.ArgumentParser(description="批量对拍：atlispcc vs CAD")
    parser.add_argument("command", choices=["cad", "ours", "compare", "auto"],
                        help="cad=CAD编译, ours=atlispcc编译, compare=对比, auto=编译+对比")
    parser.add_argument("--src", required=True, help="源 .lsp 目录（相对于 atlispcc 根）")
    parser.add_argument("--golden", help="CAD golden 目录")
    parser.add_argument("--ours", help="atlispcc 编译输出目录")
    parser.add_argument("--cad-root", help="CAD 端 .lsp 根路径（Windows）")
    parser.add_argument("--mcp-url", default=MCP_URL, help="MCP 服务器地址")
    args = parser.parse_args()

    src_dir = os.path.join(ROOT, args.src) if not os.path.isabs(args.src) else args.src
    golden_dir = args.golden or f"/tmp/opencode/golden-{os.path.basename(args.src)}"
    ours_dir = args.ours or f"/tmp/opencode/ours-{os.path.basename(args.src)}"

    if args.command == "cad":
        if not args.cad_root:
            parser.error("cad 命令需要 --cad-root 参数")
        cad_compile_all(src_dir, golden_dir, args.cad_root, args.mcp_url)

    elif args.command == "ours":
        ours_compile_all(src_dir, ours_dir)

    elif args.command == "compare":
        compare_all(src_dir, golden_dir, ours_dir)

    elif args.command == "auto":
        if not args.cad_root:
            parser.error("auto 命令需要 --cad-root 参数")
        print("=== Step 1: CAD compile ===")
        ok, _ = cad_compile_all(src_dir, golden_dir, args.cad_root, args.mcp_url)
        if ok == 0:
            print("No files compiled, aborting")
            return
        print("\n=== Step 2: atlispcc compile ===")
        ours_compile_all(src_dir, ours_dir)
        print("\n=== Step 3: Compare ===")
        compare_all(src_dir, golden_dir, ours_dir)


if __name__ == "__main__":
    main()
