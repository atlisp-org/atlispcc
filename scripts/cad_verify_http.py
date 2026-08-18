#!/usr/bin/env python3
"""CAD 真机测试运行器（HTTP MCP 版）— 编译/加载/断言 tests/compile_src/ 产物。

与 scripts/cad_verify.py 等价，但通过 HTTP MCP（192.168.1.210:8110）驱动
AutoCAD，不依赖本地 atlisp-mcp 二进制。每个用例独立：本地编译 → 同步
（W:/atlisp/atlispcc 与本地一致）→ CAD load → 断言返回值。

用法:
    python scripts/cad_verify_http.py               # 全量
    python scripts/cad_verify_http.py 01_math 16_i18n
"""
import json
import os
import sys
import time
import urllib.request

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

MCP_URL = "http://192.168.1.210:8110/mcp"
GOLD_DIR = os.path.join(_ROOT, "tests", "cad")
REMOTE_DIR = "W:/atlisp/atlispcc/tests/cad"

# 与 scripts/cad_verify.py 相同的用例表
CASES = [
    ("01_math", '(list (add 2 3) (multiply 4 5) (square 6) (sum-of-squares 3 4))',
     [5, 20, 36, 25]),
    ("02_strings", '(list (greet "CAD") (full-name "John" "Doe") (shout "hi"))',
     ["Hello, CAD!", "John Doe", "HI!!"]),
    ("03_recursion", '(list (factorial 5) (factorial 10) (fib 10) (count-to 3))',
     [120, 3628800, 55, 3]),
    ("04_control",
     '(list (classify -5) (classify 0) (classify 7) (max3 3 1 2) (max3 1 5 2)'
     ' (max3 2 1 7) (is-even 4) (is-odd 3))',
     ["negative", "zero", "positive", 3, 5, 7, True, True]),
    ("05_lists",
     '(list (get-first \'(10 20 30)) (get-rest \'(10 20 30)) (build-list)'
     ' (test-nested-quote) (car (test-cons-quote)) (cdr (test-cons-quote)))',
     [10, [20, 30], [1, 2, 3], [1, 2, 3], 1, 2]),
    ("06_higher_order",
     '(list (sum-list \'(1 2 3 4)) (double-all \'(1 2 3)) (kwote-double))',
     [10, [2, 4, 6], 42]),
    ("07_locals", '(sum-to-n 5)', 15),
    ("08_loops",
     '(list (sum-foreach \'(1 2 3 4 5)) (collect-foreach \'(1 2 3)) (repeat-count 5))',
     [15, [2, 4, 6], 5]),
    ("09_variadic",
     '(list (v-greet "CAD") (v-greet "CAD" "Hi") (v-sum-rest 1 2 3 4)'
     ' (v-product 2 3 4) (v-first-arg 1 2 3) (v-first-arg 5)'
     ' (v-pure-optional) (v-pure-optional 1 2))',
     ["Hello, CAD!", "Hi, CAD!", 10, 24, 2, 5, [None, None], [1, 2]]),
    ("10_commands", '(list (c:add 3 4) (c:add 10 -2))', [7, 8]),
    ("11_top_level", '(list (get-version) *version*)', ["1.0", "1.0"]),
    ("12_cad_funcs",
     '(list (get-dist \'(0 0) \'(3 4)) (get-ang \'(0 0) \'(1 0)))',
     [5.0, 0.0]),
    ("16_i18n",
     '(list (@::codepage2lang "ANSI_936") (@::codepage2lang "ANSI_949")'
     ' (@::codepage2lang "ANSI_1258"))',
     [["zh", "zh_CN"], ["kor", "kr"], ["vie", "vi"]]),
    ("13_activex",
     '(list (t22-has-active-doc)'
     ' (t22-positive-count (vla-get-Application (t22-acad-doc))))',
     [True, True]),
    ("14_command_s", '(t23-created-circle-p)', True),
    ("15_error",
     '(list (t24-handler-test) t24-error-msg)',
     ["handler-ran", "handler-ran"]),
]


def mcp_call(name, arguments, timeout=120):
    req = {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
           "params": {"name": name, "arguments": arguments}}
    data = json.dumps(req).encode("utf-8")
    r = urllib.request.urlopen(urllib.request.Request(
        MCP_URL, data=data, headers={"Content-Type": "application/json"}),
        timeout=timeout)
    obj = json.loads(r.read().decode("utf-8"))
    result = obj.get("result", {})
    texts = [c.get("text", "") for c in result.get("content", [])
             if c.get("type") == "text"]
    return {"output": "\n".join(texts), "isError": result.get("isError", False)}


def run_one(module):
    from compiler.cli import cmd_compile

    src = os.path.join(_ROOT, "tests", "compile_src", f"{module}.lsp")
    out = os.path.join(GOLD_DIR, f"cadtest_{module}.fas")
    cmd_compile(src, out)  # verify 默认开启，失败会 exit(2)
    time.sleep(1.5)  # 等同步到 CAD 主机
    remote_fas = f"{REMOTE_DIR}/cadtest_{module}.fas"
    expr = next(c for m, c, _ in CASES if m == module)
    expected = next(e for m, _, e in CASES if m == module)
    code = f'(vl-prin1-to-string (progn (load "{remote_fas}") {expr}))'
    r = mcp_call("eval_lisp_with_result", {"code": code})
    raw = r["output"].strip()
    # vl-prin1-to-string 返回带引号的 LISP 文本 `"..."`；去外层引号后按
    # LISP 语法解析（字符串带引号、列表带括号）。
    if raw.startswith('"') and raw.endswith('"'):
        raw = raw[1:-1]
    return raw, expected


def parse_value(raw):
    """把 CAD 打印值解析为 Python 值（nil/T/数字/字符串/列表）。"""
    try:
        import re

        # nil → None
        if raw in ("nil", "()", ""):
            return None
        # T → True
        if raw in ("T", "t"):
            return True
        # 列表 (a b c) / 嵌套
        if raw.startswith("(") and raw.endswith(")"):
            inner = raw[1:-1]
            items = []
            depth = 0
            in_str = False
            cur = ""
            for ch in inner + " ":
                if ch == '"':
                    in_str = not in_str
                elif ch == "(" and not in_str:
                    depth += 1
                elif ch == ")" and not in_str:
                    depth -= 1
                if depth == 0 and not in_str and ch in " \t":
                    if cur.strip():
                        items.append(parse_value(cur.strip()))
                    cur = ""
                else:
                    cur += ch
            return items
        # 字符串
        if raw.startswith('"') and raw.endswith('"'):
            return raw[1:-1]
        # 数字
        try:
            if "." in raw:
                return float(raw)
            return int(raw)
        except ValueError:
            return raw
    except Exception:
        return raw


def main():
    modules = sys.argv[1:] if len(sys.argv) > 1 else [m for m, _, _ in CASES]
    results = []
    for module in modules:
        try:
            raw, expected = run_one(module)
            got = parse_value(raw)
            ok = got == expected
            results.append((module, ok, raw, expected))
        except SystemExit:
            results.append((module, False, "compile-failed", None))
        except Exception as e:
            results.append((module, False, f"ERR {e}", None))
        print(f"  {module}: {'PASS' if results[-1][1] else 'FAIL'}  got={results[-1][2][:80]}")
    npass = sum(1 for _, ok, _, _ in results if ok)
    print(f"CAD verify (HTTP): {npass}/{len(results)} passed")
    return 0 if npass == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
