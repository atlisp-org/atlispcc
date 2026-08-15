#!/usr/bin/env bash
# engine 对拍：加载 tests/compile_src/ 源码，执行 cad_verify 同款断言，输出 JSON 结果。
# 用法: bash scripts/engine_crosscheck.sh
set -e
cd "$(dirname "$0")/.."

ENGINE_DIR="engine"
OUT_DIR="D:/usr/cygwin64/tmp/opencode/atlispcc-engine-check"
mkdir -p "$OUT_DIR"

# (名称|断言表达式)  —— 名称 = tests/compile_src/<名称>.lsp（不含扩展名）
CASES='01_math|(list (add 2 3) (multiply 4 5) (square 6) (sum-of-squares 3 4))
02_strings|(list (greet "CAD") (full-name "John" "Doe") (shout "hi"))
03_recursion|(list (factorial 5) (factorial 10) (fib 10) (count-to 3))
04_control|(list (classify -5) (classify 0) (classify 7) (max3 3 1 2) (max3 1 5 2) (max3 2 1 7) (is-even 4) (is-odd 3))
05_lists|(list (get-first (quote (10 20 30))) (get-rest (quote (10 20 30))) (build-list) (test-nested-quote) (car (test-cons-quote)) (cdr (test-cons-quote)))
06_higher_order|(list (sum-list (quote (1 2 3 4))) (double-all (quote (1 2 3))) (kwote-double))
07_locals|(sum-to-n 5)
08_loops|(list (sum-foreach (quote (1 2 3 4 5))) (collect-foreach (quote (1 2 3))) (repeat-count 5))
09_variadic|(list (v-greet "CAD") (v-greet "CAD" "Hi") (v-sum-rest 1 2 3 4) (v-product 2 3 4) (v-first-arg 1 2 3) (v-first-arg 5) (v-pure-optional) (v-pure-optional 1 2))
10_commands|(list (c:hello) (c:add 3 4) (c:add 10 -2))
11_top_level|(list (get-version) *version*)
12_cad_funcs|(list (distance (quote (0 0)) (quote (3 4))) (angle (quote (0 0)) (quote (1 0))))'

run_engine() {
  local name="$1" src="$2" expr="$3" out
  out="$OUT_DIR/$name.check.lsp"
  # 拼源码 + 断言表达式到临时文件
  python - "$src" "$expr" "$out" <<'PYEOF'
import sys
src = open(sys.argv[1], encoding="utf-8").read()
expr = sys.argv[2]
out = sys.argv[3]
with open(out, "w", encoding="utf-8", newline="\n") as f:
    f.write(src + "\n(setq __check__ " + expr + ")\n")
    f.write('(princ "RESULT=") (princ __check__) (terpri)\n')
PYEOF
  local result
  result=$( cd "$ENGINE_DIR" && timeout 60 sbcl --noinform --non-interactive --load atlisp.asd \
      --eval '(handler-bind ((warning (function muffle-warning))) (asdf:load-system "atlisp"))' \
      --eval '(in-package :atlisp)' \
      --eval "(handler-case (progn (al-run-file \"$out\") (finalize-exit-code 0))
                 (error (e) (format *error-output* \"~&ERR ~a~%\" e) (finalize-exit-code 2)))" \
      2>&1 )
  local err
  err=$(echo "$result" | grep -a '^ERR ' | head -1)
  if [ -n "$err" ]; then
    echo "ERROR|$err"
  else
    echo "OK|$(echo "$result" | grep -a 'RESULT=' | sed 's/.*RESULT=//' | tail -1)"
  fi
}

echo "name,status,result"
while IFS='|' read -r name expr; do
  [ -z "$name" ] && continue
  src="tests/compile_src/${name}.lsp"
  [ -f "$src" ] || { echo "$name,NO_SRC,"; continue; }
  # 跳过 CAD 专属/engine 不支持用例
  case "$name" in
    10_commands|11_top_level|12_cad_funcs|13_activex|14_command_s|15_error|16_i18n)
      echo "$name,SKIP,"; continue;;
  esac
  res=$(run_engine "$name" "$src" "$expr")
  echo "$name,$res"
done <<< "$CASES"
