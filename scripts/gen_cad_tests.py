#!/usr/bin/env python3
"""生成 CAD 真机测试产物。

把 t01-t15 全部编译为 .fas，并复制 CAD 真机测试脚本到 CAD 可访问目录。

用法:
    python scripts/gen_cad_tests.py [cad_dir]
"""
import os
import shutil
import sys

# 加入仓库根到 sys.path（脚本位于 scripts/ 下）
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from compiler.cli import cmd_compile

# 兼容 win32/cygwin 路径：CAD 通过 @lisp 目录访问
DEFAULT_CAD_DIR = "C:/Users/vitalgg/@lisp"

T_SERIES = [
    "t01_math", "t02_recursion", "t03_fib", "t04_while", "t05_cond",
    "t06_strcat", "t07_list", "t08_apply_mapcar", "t09_funcall", "t10_init",
    "t11_localvars", "t12_quote", "t13_nested_if", "t14_command",
    "t15_cad_funcs",
]


def main():
    cad_dir = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_CAD_DIR
    if not os.path.isdir(cad_dir):
        print(f"错误: CAD 目录不存在: {cad_dir}")
        return 1

    root = _ROOT
    src_dir = os.path.join(root, "tests", "cad")

    ok = 0
    for name in T_SERIES:
        src = os.path.join(src_dir, f"{name}.lsp")
        if not os.path.exists(src):
            print(f"  [跳过] {name}.lsp 不存在")
            continue
        out = os.path.join(cad_dir, f"{name}.fas")
        try:
            cmd_compile(src, out)
            ok += 1
        except Exception as e:
            print(f"  [失败] {name}: {e}")

    # 复制真机测试脚本
    verify = os.path.join(root, "tests", "cad_verify.lsp")
    if os.path.exists(verify):
        shutil.copy2(verify, os.path.join(cad_dir, "cad_verify.lsp"))
        print(f"\n已复制测试脚本: {os.path.join(cad_dir, 'cad_verify.lsp')}")
    else:
        print(f"\n警告: {verify} 不存在")

    print(f"编译完成: {ok}/{len(T_SERIES)} 个产物到 {cad_dir}")
    print("在 CAD 中运行: (load \"%s/cad_verify.lsp\")" % cad_dir.replace("\\", "/"))
    return 0 if ok == len(T_SERIES) else 1


if __name__ == "__main__":
    sys.exit(main())
