#!/usr/bin/env python3
"""生成确定性的大型合成 LSP fixture（nsyms > 256，触发宽格式 USUBR/FUNC）。

大文件编译路径（5/6 字节 USUBR/FUNC、模块注册、跨函数引用）此前只由
`tests/atlisp_u.lsp`（@lisp 综合包）覆盖，且测试在 fixture 缺失时跳过。
本脚本生成自包含、确定性的合成大文件，供 tests/test_large_file.py 使用。

用法:
    python scripts/gen_large_fixture.py [-o tests/large_synthetic.lsp]
"""
import os
import sys

_DEFAULT_OUT = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "tests",
    "large_synthetic.lsp",
)

#: 函数数量。每个函数至少贡献函数名 + 参数 + 局部变量 ≈ 4 个唯一符号，
#: 保证编译产物 nsyms > 256（触发宽格式路径）。120 函数足够越过阈值。
N_FUNCS = 120

_HEADER = """\
;; 大型合成 fixture（由 scripts/gen_large_fixture.py 生成，勿手改）。
;; 覆盖：nsyms>256 宽格式 USUBR/FUNC、多函数交叉引用、局部变量、
;; 顶层表达式、命令、变参。确定性内容：同一脚本输出逐字节一致。
"""


def _func(i):
    n = f"lgf-{i:03d}"
    nxt = f"lgf-{(i + 1) % N_FUNCS:03d}"
    prev = f"lgf-{(i - 1) % N_FUNCS:03d}"
    a, b, r = f"a-{i:03d}", f"b-{i:03d}", f"r-{i:03d}"
    s = f"s-{i:03d}"
    return f"""\
(defun {n} ({a} {b} / {r} {s})
  (setq {r} (+ {a} {b}))
  (setq {s} (strcat (itoa {r}) " [%03d]"))
  (if (> {r} 100)
    (progn
      (setq {r} (- {r} 100))
      ({prev} {r} {b}))
    ({nxt} {r} {a}))
  (list {a} {b} {r} {s}))
"""


def _top_level(i):
    name = f"lgf-top-{i:03d}"
    return f"(setq {name} (* {i} 2))\n"


def _command(i):
    n = f"c:lgf-cmd-{i:03d}"
    tgt = f"lgf-{i:03d}"
    return f"""\
(defun {n} ()
  (princ "{n}")
  (princ ({tgt} 1 2))
  (princ))
"""


def _variadic(i):
    n = f"lgf-var-{i:03d}"
    return f"""\
(defun {n} ({n}-a &optional {n}-opt &rest {n}-rest)
  (cons {n}-a (cons {n}-opt {n}-rest)))
"""


def generate() -> str:
    lines = [_HEADER, ""]
    # 变参函数穿插：&optional/&rest 编译路径
    for i in range(0, N_FUNCS, 20):
        lines.append(_variadic(i))
        lines.append("")
    # 普通函数主体
    for i in range(N_FUNCS):
        lines.append(_func(i))
        lines.append("")
    # 命令函数
    for i in range(0, N_FUNCS, 30):
        lines.append(_command(i))
        lines.append("")
    # 顶层表达式（混合模式 → seg1 模块代码）
    for i in range(0, N_FUNCS, 10):
        lines.append(_top_level(i))
    lines.append("(princ \"large-synthetic loaded\")\n")
    return "\n".join(lines)


def main() -> int:
    out = _DEFAULT_OUT
    args = sys.argv[1:]
    if len(args) >= 2 and args[0] in ("-o", "--output"):
        out = args[1]
    elif args:
        out = args[0]
    text = generate()
    with open(out, "w", encoding="utf-8") as f:
        f.write(text)
    print(f"wrote {out}: {len(text.splitlines())} lines")
    return 0


if __name__ == "__main__":
    sys.exit(main())