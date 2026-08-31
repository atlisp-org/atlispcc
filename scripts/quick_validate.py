#!/usr/bin/env python
"""快速验证：仅编译并检查错误，不对比 golden。

用于快速扫描大量 .lsp 文件的编译兼容性，无需 CAD 真机。

用法:
  python scripts/quick_validate.py --src ../lib/src
  python scripts/quick_validate.py --src ../packages
"""
import argparse
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def collect_src(src_dir):
    files = []
    for dp, _dn, ns in os.walk(src_dir):
        for n in ns:
            if n.endswith(".lsp"):
                rel = os.path.relpath(os.path.join(dp, n), src_dir).replace("\\", "/")
                files.append(rel)
    return sorted(files)


def main():
    parser = argparse.ArgumentParser(description="快速验证编译兼容性")
    parser.add_argument("--src", required=True, help="源 .lsp 目录")
    parser.add_argument("-O", "--optimize", type=int, default=0, choices=[0,1,2,3],
                        help="优化级别 (默认 0)")
    parser.add_argument("--stop-on-error", action="store_true", help="遇到错误立即停止")
    args = parser.parse_args()

    src_dir = os.path.join(ROOT, args.src) if not os.path.isabs(args.src) else args.src
    files = collect_src(src_dir)
    print(f"Found {len(files)} .lsp files in {src_dir}\n")

    ok = 0
    fail = []
    skip = []

    for i, rel in enumerate(files, 1):
        src = os.path.join(src_dir, rel)
        print(f"[{i}/{len(files)}] {rel} ... ", end="", flush=True)

        r = subprocess.run(
            [sys.executable, "-m", "compiler.cli", "compile",
             f"-O{args.optimize}", src, "/dev/null"],
            capture_output=True, text=True, cwd=ROOT)

        if r.returncode == 0:
            ok += 1
            print("OK")
        else:
            err = r.stderr.strip().split("\n")[-1][:80]
            fail.append((rel, err))
            print(f"FAIL: {err}")
            if args.stop_on_error:
                break

    print(f"\n=== Summary: OK={ok} FAIL={len(fail)} TOTAL={len(files)} ===")
    if fail:
        print("\nFailed files:")
        for rel, err in fail:
            print(f"  {rel}: {err}")


if __name__ == "__main__":
    main()
