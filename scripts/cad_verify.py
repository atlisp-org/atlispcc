#!/usr/bin/env python3
"""CAD 真机测试运行器 — 逐个编译/加载/断言 t-series 编译产物。

每个用例独立执行（编译 → 复制到 CAD → 加载 → 断言返回值），避免单个大脚本
在 CAD 会话不稳定时整体中断（§3.7 安全策略）。

覆盖 21 项：t01-t15 + t16_foreach/t17_repeat + t18 相互递归 +
t19_variadic（&optional/&rest）+ t20_kwote（`(function (lambda ...))` 内嵌
函数）+ i18n（混合 defun+顶层+kwote，调 @::codepage2lang）。

用法:
    python scripts/cad_verify.py           # 全量验证 21 项
    python scripts/cad_verify.py t01 t05   # 只验证指定项
"""
import json
import os
import subprocess
import sys
import time

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from compiler.cli import cmd_compile

CAD_DIR = "C:/Users/vitalgg/@lisp"

# 每个用例: (模块名, 加载后断言脚本, 期望 JSON 值)
CASES = [
    ("t01_math", '(list (add 2 3) (multiply 4 5))', [5, 20]),
    ("t02_recursion", '(list (factorial 5) (factorial 10))', [120, 3628800]),
    ("t03_fib", '(fib 10)', 55),
    ("t04_while", '(count-down 3)', "Done!"),
    ("t05_cond", '(list (classify -5) (classify 0) (classify 7))',
     ["negative", "zero", "positive"]),
    ("t06_strcat", '(greet "CAD")', "Hello, CAD!"),
    ("t07_list", '(list (get-first \'(10 20 30)) (get-rest \'(10 20 30)) (build-list))',
     [10, [20, 30], [1, 2, 3]]),
    ("t08_apply_mapcar", '(list (sum-list \'(1 2 3 4)) (double-all \'(1 2 3)))',
     [10, [2, 4, 6]]),
    ("t09_funcall", '(list (square 6) (sum-of-squares 3 4))', [36, 25]),
    ("t10_init", '(get-version)', "1.0"),
    ("t11_localvars", '(sum-to-n 5)', 15),
    ("t12_quote",
     '(list (test-nested-quote) (car (test-cons-quote)) (cdr (test-cons-quote)))',
     [[1, 2, 3], 1, 2]),
    ("t13_nested_if", '(list (max3 3 1 2) (max3 1 5 2) (max3 2 1 7))', [3, 5, 7]),
    ("t14_command", '(list (c:add 3 4) (c:add 10 -2))', [7, 8]),
    ("t15_cad_funcs", '(list (get-dist \'(0 0) \'(3 4)) (get-ang \'(0 0) \'(1 0)))',
     [5.0, 0.0]),
    ("t16_foreach", '(sum-foreach \'(1 2 3 4 5))', 15),
    ("t17_repeat", '(repeat-count 5)', 5),
    ("t18_multi_recursive", '(list (is-even 4) (is-odd 3))', [True, True]),
    # &optional/&rest 可变参数（t19_variadic，CAD 需至少一个必填参数才收集 rest）
    ("t19_variadic",
     '(list (t19-greet "CAD") (t19-greet "CAD" "Hi") (t19-sum 1 2 3 4))',
     ["Hello, CAD!", "Hi, CAD!", 10]),
    # kwote `(function (lambda ...))` / `-lambda-` 内嵌函数完整运行链路
    # （t20_kwote：apply-fn 接收 kwote lambda 并调用，应得 2*21=42）
    ("t20_kwote", '(t20-kwote)', 42),
    # i18n 混合模式（defun+顶层+kwote `-lambda-`）：加载后调用纯函数
    # `@::codepage2lang`（assoc 字符串 key），验证 kwote/嵌套 lambda 运行正确
    ("i18n",
     '(list (@::codepage2lang "ANSI_936") (@::codepage2lang "ANSI_949")'
     ' (@::codepage2lang "ANSI_1258"))',
     [["zh", "zh_CN"], ["kor", "kr"], ["vie", "vi"]]),
]

# 已知功能缺陷（混合模式，§8.C2 待修）：t10 的 get-version/hello 符号错位
KNOWN_ISSUES = {
    # 2026-08-05: t10_init 已随 byte-identity 转正，从此处移除
}


class CadProbe:
    def __init__(self):
        self.proc = subprocess.Popen(
            ["atlisp-mcp", "--stdio", "--security-level", "relaxed"],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            bufsize=1, text=True, encoding="utf-8", errors="replace",
        )
        self._id = 0
        self._call("initialize", {
            "protocolVersion": "2024-11-05", "capabilities": {},
            "clientInfo": {"name": "atlispcc-verify", "version": "0.1"},
        })

    def _call(self, method, params):
        self._id += 1
        msg = {"jsonrpc": "2.0", "id": self._id, "method": method, "params": params}
        self.proc.stdin.write(json.dumps(msg) + "\n")
        self.proc.stdin.flush()
        while True:
            line = self.proc.stdout.readline()
            if not line:
                raise RuntimeError("MCP 进程退出")
            data = json.loads(line)
            if data.get("id") == self._id:
                if "error" in data:
                    raise RuntimeError(f"MCP error: {data['error']}")
                return data.get("result")

    def eval(self, code):
        res = self._call("tools/call", {"name": "eval_lisp_with_result", "arguments": {"code": code}})
        try:
            return json.loads(res["content"][0]["text"])
        except Exception:
            return res

    def close(self):
        self.proc.terminate()


def _extract_value(res):
    """从 MCP 结果提取文本值。"""
    if isinstance(res, dict) and res.get("isError"):
        return ("ERROR", res.get("content", [{}])[0].get("text", "?"))
    if isinstance(res, dict) and "content" in res:
        texts = [c.get("text", "") for c in res["content"] if c.get("type") == "text"]
        return texts[0] if texts else ""
    if isinstance(res, str):
        return res
    return str(res)


def verify_case(probe, module, expr, expected):
    fas = os.path.join(CAD_DIR, f"{module}.fas").replace("\\", "/")
    src = os.path.join(_ROOT, "tests", "cad", f"{module}.lsp")
    try:
        cmd_compile(src, fas)
    except Exception as e:
        return False, f"编译失败: {e}"
    # 在 CAD 端做断言：equal 对比实际值与期望（用 quote 传入期望）
    exp_lisp = _to_lisp_literal(expected)
    code = f'(progn (load "{fas}") (equal {expr} \'{exp_lisp}))'
    res = probe.eval(code)
    actual = _extract_value(res)
    if isinstance(actual, tuple) and actual[0] == "ERROR":
        return False, f"执行错误: {actual[1]}"
    if actual == "T":
        return True, f"= {exp_lisp}"
    return False, f"期望 {exp_lisp} 实际 {actual}"


def _to_lisp_literal(value):
    """把 Python 值序列化为 Lisp 字面量（列表/数字/字符串）。"""
    if isinstance(value, list):
        return "(" + " ".join(_to_lisp_literal(v) for v in value) + ")"
    if isinstance(value, str):
        return f'"{value}"'
    if isinstance(value, bool):
        return "T" if value else "nil"
    if isinstance(value, float):
        return repr(value)
    return str(value)


def main():
    args = sys.argv[1:] or [c[0] for c in CASES]
    passed, failed, known = 0, 0, 0
    print("=== CAD 真机验证 ===")
    for module, expr, expected in CASES:
        if module not in args:
            continue
        if module in KNOWN_ISSUES:
            known += 1
            print(f"  [KNOWN] {module}: {KNOWN_ISSUES[module]}")
            continue
        # 每用例独立连接 + 失败重试（CAD 会话偶发失效，§3.7）
        ok, msg = False, "重试耗尽"
        for attempt in range(3):
            probe = CadProbe()
            try:
                ok, msg = verify_case(probe, module, expr, expected)
            except Exception as e:
                ok, msg = False, f"连接异常: {e}"
            finally:
                probe.close()
            if ok:
                break
            time.sleep(1)
        if ok:
            passed += 1
            print(f"  [PASS]  {module}: {msg}")
        else:
            failed += 1
            print(f"  [FAIL]  {module}: {msg}")
    print(f"\n结果: {passed} 通过, {failed} 失败, {known} 已知缺陷")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
