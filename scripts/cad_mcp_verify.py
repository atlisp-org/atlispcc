#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""完整 CAD 真机验证：t01-t24 全部用例（含 kwote/变参/ActiveX/command/*error*）。
用法: python scripts/cad_mcp_verify.py  （需已连接 CAD）
"""
import subprocess, json, sys, os, re

sys.path.insert(0, os.path.join(os.path.dirname(__file__)))
from mcp_cad import MCPClient

CAD_DIR = "D:/usr/cygwin64/tmp/opencode/cadtest"

# (模块名, 断言表达式, 期望值或匹配规则, 匹配方式: 'eq'|'contains')
CASES = [
    ("t01_math", '(list (add 2 3) (multiply 4 5))', '(5 20)', 'eq'),
    ("t02_recursion", '(list (factorial 5) (factorial 10))', '(120 3628800)', 'eq'),
    ("t03_fib", '(fib 10)', '55', 'eq'),
    ("t04_while", '(count-down 3)', 'Done!', 'contains'),
    ("t05_cond", '(list (classify -5) (classify 0) (classify 7))', '(negative zero positive)', 'eq'),
    ("t06_strcat", '(greet "CAD")', 'Hello, CAD!', 'contains'),
    ("t07_list", '(list (get-first \'(10 20 30)) (get-rest \'(10 20 30)) (build-list))', '(10 (20 30) (1 2 3))', 'eq'),
    ("t08_apply_mapcar", '(list (sum-list \'(1 2 3 4)) (double-all \'(1 2 3)))', '(10 (2 4 6))', 'eq'),
    ("t09_funcall", '(list (square 6) (sum-of-squares 3 4))', '(36 25)', 'eq'),
    ("t10_init", '(type *version*)', 'STR', 'eq'),
    ("t11_localvars", '(sum-to-n 5)', '15', 'eq'),
    ("t12_quote", '(list (test-nested-quote) (car (test-cons-quote)) (cdr (test-cons-quote)))', '((1 2 3) 1 2)', 'eq'),
    ("t13_nested_if", '(list (max3 3 1 2) (max3 1 5 2) (max3 2 1 7))', '(3 5 7)', 'eq'),
    ("t16_foreach", '(sum-foreach \'(1 2 3 4 5))', '15', 'eq'),
    ("t17_repeat", '(repeat-count 5)', '5', 'eq'),
    ("t18_multi_recursive", '(list (is-even 4) (is-odd 3))', '(T T)', 'eq'),
    ("t19_variadic", '(list (t19-greet "CAD") (t19-greet "CAD" "Hi") (t19-sum 1 2 3 4))', '(Hello, CAD! Hi, CAD! 10)', 'eq'),
    ("t20_kwote", '(t20-kwote)', '42', 'eq'),
    ("t21_variadic_extra", '(list (t21-greet "CAD") (t21-greet "CAD" "Hi") (t21-sum-rest 1 2 3 4) (t21-product 2 3 4) (t21-first-arg 1 2 3) (t21-first-arg 5))', '(Hello, CAD! Hi, CAD! 10 24 2 5)', 'eq'),
    ("t22_activex", '(list (t22-has-active-doc) (t22-positive-count (vla-get-Application (t22-acad-doc))))', '(T T)', 'eq'),
    ("t23_command", '(t23-created-circle-p)', 'T', 'eq'),
    ("t24_star_error", '(list (t24-handler-test) t24-error-msg)', '(handler-ran handler-ran)', 'eq'),
]


def main():
    c = MCPClient()
    info = c.tool('get_cad_info', {})
    print('CAD:', info.get('output', '?'))
    passed, failed = 0, []
    for name, expr, expect, mode in CASES:
        fas = os.path.join(CAD_DIR, f"{name}.fas")
        if not os.path.exists(fas):
            failed.append((name, 'NO_FAS'))
            continue
        load = c.tool('eval_lisp_with_result', {'code': f'(load "{fas}")'})
        if load.get('isError'):
            failed.append((name, f'LOAD_ERR: {load.get("output")}'))
            print(f'  {name}: LOAD_ERR {load.get("output")[:80]}')
            continue
        r = c.tool('eval_lisp_with_result', {'code': expr})
        if r.get('isError'):
            failed.append((name, f'EVAL_ERR: {r.get("output")}'))
            print(f'  {name}: EVAL_ERR {r.get("output")[:80]}')
            continue
        got = r.get('output', '')
        ok = (got == expect) if mode == 'eq' else (expect in got)
        if ok:
            passed += 1
            print(f'  {name}: PASS got={got!r}')
        else:
            failed.append((name, f'got {got!r} expect {expect!r}'))
            print(f'  {name}: FAIL got={got!r} expect={expect!r}')
    c.close()
    print(f'\n=== {passed}/{passed+len(failed)} passed ===')
    for name, msg in failed:
        print(f'  FAIL {name}: {msg}')
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main())
