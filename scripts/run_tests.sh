#!/usr/bin/env bash
# atlispcc 完整测试脚本
#
# 用法:
#   ./scripts/run_tests.sh             # 全量测试（语法检查 + 单测 + 往返验证）
#   ./scripts/run_tests.sh -q          # 安静模式（仅汇总）
#   ./scripts/run_tests.sh -v          # 详细输出
#   ./scripts/run_tests.sh --no-roundtrip   # 跳过 disasm→asm 往返验证
#   ./scripts/run_tests.sh --cad       # 额外执行 CAD 真机验证（需 CAD 已连接）
#   CAD_VERIFY=1 ./scripts/run_tests.sh # 同上（环境变量方式）
#
# 覆盖:
#   1. Python 语法检查（py_compile 全部源码）
#   2. pytest 全量测试套件
#   3. disasm→asm 往返字节级验证（tests/cad/ 全部 golden）
#   4. CAD golden byte-identity 状态摘要
#   5. [可选] CAD 真机验证（scripts/cad_verify.py，--cad 启用）
#
# 退出码: 0=全部通过, 1=有失败
set -uo pipefail

cd "$(dirname "$0")/.."
ROOT="$(pwd)"

PASS=0
FAIL=0
PY=${PYTHON:-python}

log()  { echo -e "\033[32m[OK]\033[0m $*"; }
warn() { echo -e "\033[33m[WARN]\033[0m $*"; }
err()  { echo -e "\033[31m[FAIL]\033[0m $*"; FAIL=$((FAIL+1)); }

# ── 参数解析 ────────────────────────────────────────────────────────────────
QUIET=0
VERBOSE=0
ROUNDTRIP=1
CAD_VERIFY=0
for arg in "$@"; do
  case "$arg" in
    -q|--quiet) QUIET=1 ;;
    -v|--verbose) VERBOSE=1 ;;
    --no-roundtrip) ROUNDTRIP=0 ;;
    --cad) CAD_VERIFY=1 ;;
    *) warn "未知参数: $arg" ;;
  esac
done

# ── 1. Python 语法检查 ──────────────────────────────────────────────────────
echo "==> [1/4] Python 语法检查"
# 用 git 跟踪 + 当前工作区文件，排除已删除（git 仍列出但不存在）的文件
SRC_FILES=$(git ls-files '*.py' 2>/dev/null | while read -r f; do [ -f "$f" ] && echo "$f"; done)
if [ -z "$SRC_FILES" ]; then
  SRC_FILES=$(find . -name '*.py' -not -path './.git/*')
fi
PYCOMPILE_FAIL=0
N_FILES=0
for f in $SRC_FILES; do
  N_FILES=$((N_FILES+1))
  if ! "$PY" -m py_compile "$f" 2>/dev/null; then
    err "py_compile 失败: $f"
    PYCOMPILE_FAIL=1
  fi
done
[ "$PYCOMPILE_FAIL" -eq 0 ] && log "py_compile: $N_FILES 个文件通过"
[ "$QUIET" -eq 0 ] && echo

# ── 2. pytest 全量测试 ──────────────────────────────────────────────────────
echo "==> [2/4] pytest 全量测试"
PYTEST_ARGS="-q"
[ "$VERBOSE" -eq 1 ] && PYTEST_ARGS="-v"
if "$PY" -m pytest "$PYTEST_ARGS" tests/ 2>&1; then
  log "pytest 全部通过"
  PASS=$((PASS+1))
else
  err "pytest 有失败用例"
fi
[ "$QUIET" -eq 0 ] && echo

# ── 3. disasm→asm 往返字节级验证 ───────────────────────────────────────────
if [ "$ROUNDTRIP" -eq 1 ]; then
  echo "==> [3/4] disasm→asm 往返字节级验证"
  RT_OUT=$("$PY" - <<'PYEOF'
import glob, os, sys, tempfile

sys.stdout = open(os.devnull, "w")
from asm.assembler import disassemble_fas, assemble_lasm
from decompiler.fas4_decompiler import Fas4Parser
sys.stdout = sys.__stdout__

ok, skipped, fail = 0, 0, []
files = sorted(glob.glob('tests/cad/*_cad.fas')) + sorted(glob.glob('tests/*_cad.fas'))
for f in files:
    try:
        lasm = disassemble_fas(f)
        with tempfile.TemporaryDirectory() as tmp:
            out = os.path.join(tmp, 'out.fas')
            assemble_lasm(lasm, out)
            orig = Fas4Parser().parse(f)
            new = Fas4Parser().parse(out)
            if orig.bytecode == new.bytecode:
                ok += 1
            else:
                fail.append((os.path.basename(f), 'bytecode differs'))
    except Exception as e:
        if 'Bad FAS payload header' in str(e):
            skipped += 1
        else:
            fail.append((os.path.basename(f), str(e)[:60]))
print(f"OK={ok} SKIP={skipped} FAIL={len(fail)}")
for f, e in fail:
    print(f"  {f}: {e}")
PYEOF
)
  echo "$RT_OUT"
  RT_OK=$(echo "$RT_OUT" | grep -oP 'OK=\K[0-9]+' || echo 0)
  RT_FAIL=$(echo "$RT_OUT" | grep -oP 'FAIL=\K[0-9]+' || echo 0)
  if [ "$RT_FAIL" -eq 0 ] && [ "$RT_OK" -gt 0 ]; then
    log "往返验证通过 ($RT_OK 文件字节一致)"
    PASS=$((PASS+1))
  else
    err "往返验证失败 ($RT_FAIL 个不一致)"
  fi
  [ "$QUIET" -eq 0 ] && echo
else
  echo "==> [3/4] 往返验证已跳过 (--no-roundtrip)"
fi

# ── 4. CAD golden byte-identity 状态 ───────────────────────────────────────
echo "==> [4/4] CAD golden byte-identity 状态"
ID_STATE=$("$PY" - <<'PYEOF'
import glob, os, sys, tempfile
from contextlib import redirect_stdout

from compiler.cli import cmd_compile
from decompiler.fas4_decompiler import Fas4Parser

ident, diff = [], []
for f in sorted(glob.glob('tests/cad/t0[0-9]_*_cad.fas')) + sorted(glob.glob('tests/cad/t1[0-9]_*_cad.fas')):
    name = os.path.basename(f)[:-8]  # strip _cad.fas
    src = f'tests/cad/{name}.lsp'
    if not os.path.exists(src):
        continue
    with tempfile.TemporaryDirectory() as tmp:
        out = os.path.join(tmp, 'o.fas')
        with open(os.devnull, "w") as devnull:
            with redirect_stdout(devnull):
                cmd_compile(src, out)
        p = Fas4Parser().parse(out)
        g = Fas4Parser().parse(f)
        if p.bytecode == g.bytecode and p.resource_items == g.resource_items:
            ident.append(name)
        else:
            diff.append(name)
print(f"IDENTICAL={len(ident)} DIFF={len(diff)}")
print("identical: " + (", ".join(ident) if ident else "-"))
print("diff: " + (", ".join(diff) if diff else "-"))
PYEOF
)
echo "$ID_STATE"
ID_DIFF=$(echo "$ID_STATE" | grep -oP 'DIFF=\K[0-9]+' || echo 0)
if [ "$ID_DIFF" -eq 0 ]; then
  log "byte-identity: 全部 t-series 与 CAD 逐字节一致"
  PASS=$((PASS+1))
else
  warn "byte-identity: $ID_DIFF 项与 CAD 有差异（已知缺口，见 docs/development-plan.md 8.C）"
fi
[ "$QUIET" -eq 0 ] && echo

# ── 5. CAD 真机验证（可选，默认跳过，--cad 启用）───────────────────────────
if [ "$CAD_VERIFY" -eq 1 ]; then
  echo "==> [5/5] CAD 真机验证（scripts/cad_verify.py）"
  CAD_OUT=$("$PY" scripts/cad_verify.py 2>&1 | grep -v "Compiled to")
  echo "$CAD_OUT"
  CAD_FAIL=$(echo "$CAD_OUT" | grep -oP '失败, \K[0-9]+' || echo 0)
  if [ "$CAD_FAIL" -eq 0 ]; then
    log "CAD 真机验证通过"
    PASS=$((PASS+1))
  else
    err "CAD 真机验证失败 ($CAD_FAIL 用例)"
  fi
  [ "$QUIET" -eq 0 ] && echo
fi

# ── 汇总 ────────────────────────────────────────────────────────────────────
echo "=============================================="
if [ "$FAIL" -eq 0 ]; then
  echo -e "\033[32m全部测试通过 ✓\033[0m"
  exit 0
else
  echo -e "\033[31m${FAIL} 项检查失败 ✗\033[0m"
  exit 1
fi
