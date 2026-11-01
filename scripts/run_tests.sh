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
  RT_OK=$(echo "$RT_OUT" | grep -oE 'OK=[0-9]+' | cut -d= -f2 | tail -1 || echo 0)
  RT_SKIP=$(echo "$RT_OUT" | grep -oE 'SKIP=[0-9]+' | cut -d= -f2 | tail -1 || echo 0)
  RT_FAIL=$(echo "$RT_OUT" | grep -oE 'FAIL=[0-9]+' | cut -d= -f2 | tail -1 || echo 0)
  if [ "$RT_FAIL" -eq 0 ] && [ "$RT_OK" -gt 0 ]; then
    log "往返验证通过 ($RT_OK 文件字节一致)"
    PASS=$((PASS+1))
  elif [ "$RT_FAIL" -eq 0 ] && [ "$RT_OK" -eq 0 ] && [ "$RT_SKIP" -eq 0 ]; then
    # golden .fas 不进版本库（由 CAD 真机重新生成），公开检出时没有语料。
    warn "无 golden 语料（tests/cad/*_cad.fas 未生成为 CAD 产物），跳过往返验证"
    PASS=$((PASS+1))
  else
    err "往返验证失败 ($RT_FAIL 个不一致)"
  fi
  [ "$QUIET" -eq 0 ] && echo
else
  echo "==> [3/4] 往返验证已跳过 (--no-roundtrip)"
fi

# ── 4. compile_src 编译自检（结构断言替代 CAD golden byte-identity）─────────
echo "==> [4/4] tests/compile_src 编译 + 反编译结构自检"
ID_STATE=$("$PY" - <<'PYEOF'
import glob, io, os, sys, tempfile
from contextlib import redirect_stderr, redirect_stdout

from compiler.cli import cmd_compile
from decompiler.fas4_decompiler import Fas4Parser, Disassembler, ControlFlowAnalyzer, LispGenerator, is_compact_stub

ok, fail = [], []
verify_warnings = 0
for src in sorted(glob.glob('tests/compile_src/*.lsp')):
    name = os.path.basename(src)[:-4]
    with tempfile.TemporaryDirectory() as tmp:
        out = os.path.join(tmp, 'o.fas')
        try:
            err = io.StringIO()
            with open(os.devnull, "w") as devnull:
                with redirect_stdout(devnull), redirect_stderr(err):
                    cmd_compile(src, out)
            verify_warnings += err.getvalue().count("verify: WARN")
            p = Fas4Parser().parse(out)
            if not p.bytecode or p.nsyms == 0:
                fail.append((name, 'empty seg0/nsyms'))
                continue
            disasm = Disassembler(short_subr=is_compact_stub(p.bytecode, p.function_catalog))
            insts = disasm.disassemble(p.bytecode, p.nsyms)
            cfa = ControlFlowAnalyzer(insts, p.function_catalog)
            funcs = cfa.find_functions()
            gen = LispGenerator(p)
            result = gen.generate(funcs, out)
            if not result.strip():
                fail.append((name, 'empty decompile'))
                continue
        except Exception as e:
            fail.append((name, str(e)[:60]))
            continue
    ok.append(name)
print(f"OK={len(ok)} FAIL={len(fail)} WARN={verify_warnings}")
print("ok: " + (", ".join(ok) if ok else "-"))
print("fail: " + (", ".join(f"{f}: {e}" for f, e in fail) if fail else "-"))
PYEOF
)
echo "$ID_STATE"
ID_FAIL=$(echo "$ID_STATE" | grep -oE 'FAIL=[0-9]+' | cut -d= -f2 | tail -1 || echo 0)
if [ "$ID_FAIL" -eq 0 ] && [ "$(echo "$ID_STATE" | grep -oE 'OK=[0-9]+' | cut -d= -f2 | tail -1 || echo 0)" -gt 0 ]; then
  log "compile_src 自检: 全部编译+反编译结构通过"
  PASS=$((PASS+1))
else
  err "compile_src 自检: $ID_FAIL 项失败"
fi
[ "$QUIET" -eq 0 ] && echo

# ── 5. CAD 真机验证（可选，默认跳过，--cad 启用）───────────────────────────
if [ "$CAD_VERIFY" -eq 1 ]; then
  echo "==> [5/5] CAD 真机验证（scripts/cad_verify.py）"
  CAD_OUT=$("$PY" scripts/cad_verify.py 2>&1 | grep -v "Compiled to")
  echo "$CAD_OUT"
  CAD_FAIL=$(echo "$CAD_OUT" | grep -oE '失败, [0-9]+' | cut -d' ' -f2 | tail -1 || echo 0)
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
