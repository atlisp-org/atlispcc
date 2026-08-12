#!/usr/bin/env bash
# engine 对拍：加载 t-series 源码，执行 cad_verify 同款断言，输出 JSON 结果。
# 用法: bash scripts/engine_crosscheck.sh
set -e
cd "$(dirname "$0")/.."

ENGINE_DIR="engine"
OUT_DIR="D:/usr/cygwin64/tmp/opencode/atlispcc-engine-check"
mkdir -p "$OUT_DIR"

# (名称|断言表达式)
CASES='t01_math|(list (add 2 3) (multiply 4 5))
t02_recursion|(list (factorial 5) (factorial 10))
t03_fib|(fib 10)
t04_while|(count-down 3)
t05_cond|(list (classify -5) (classify 0) (classify 7))
t06_strcat|(greet "CAD")
t07_list|(list (get-first (quote (10 20 30))) (get-rest (quote (10 20 30))) (build-list))
t08_apply_mapcar|(list (sum-list (quote (1 2 3 4))) (double-all (quote (1 2 3))))
t09_funcall|(list (square 6) (sum-of-squares 3 4))
t10_init|(get-version)
t11_localvars|(sum-to-n 5)
t12_quote|(list (test-nested-quote) (car (test-cons-quote)) (cdr (test-cons-quote)))
t13_nested_if|(list (max3 3 1 2) (max3 1 5 2) (max3 2 1 7))
t15_cad_funcs|(list (distance (quote (0 0)) (quote (3 4))) (angle (quote (0 0)) (quote (1 0))))
t16_foreach|(sum-foreach (quote (1 2 3 4 5)))
t17_repeat|(repeat-count 5)
t18_multi_recursive|(list (is-even 4) (is-odd 3))
t19_variadic|(list (t19-greet "CAD") (t19-greet "CAD" "Hi") (t19-sum 1 2 3 4))
t21_variadic_extra|(list (t21-greet "CAD") (t21-greet "CAD" "Hi") (t21-sum-rest 1 2 3 4) (t21-product 2 3 4) (t21-first-arg 1 2 3) (t21-first-arg 5))
t20_kwote|(t20-kwote)'

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
  src="tests/cad/${name}.lsp"
  [ -f "$src" ] || { echo "$name,NO_SRC,"; continue; }
  # 跳过 CAD 专属用例
  case "$name" in
    t14_command|t22_activex|t23_command|t24_star_error) echo "$name,SKIP,"; continue;;
  esac
  res=$(run_engine "$name" "$src" "$expr")
  echo "$name,$res"
done <<< "$CASES"
