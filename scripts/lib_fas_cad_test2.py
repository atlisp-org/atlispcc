#!/usr/bin/env python3
"""lib .fas CAD 真机测试（小 driver + 文本数据文件方案）。

2026-11-02 真机取证的两个硬约束（本脚本据此设计）：

1. **AutoLISP reader 无法加载 80KB 级 .lsp 源文件**：bisA.lsp（1KB，单个 progn）
   正常返回 "BIS-A-OK"；bisB-w250/w850（80KB，同一批内容）以及 driver.lsp（86KB）
   全部挂死（CAD 消息泵卡住，只能重启）。本地副本（TEMPPREFIX 下）同样挂死，
   排除 SMB 读取问题。→ driver 必须保持几 KB，大清单改为纯文本文件，运行时
   `read-line` 逐行读入（SMB 读 80KB 实测 127ms，正常）。

2. **共享盘新文件在 CAD 侧 SMB 目录缓存里延迟可见**（实测 20s 仍不可见，
   数分钟才出现），且 `(load "不存在文件" T)` **返回 T**（假阳性）。
   → 触发前必须用 `findfile` 逐个确认文件可见；文件名带时间戳唯一化，
   避免内容缓存；触发后先等 RUN-START 标记，空响应不得盲目重派
   （盲重派会把重复命令排队进文档命令队列，实测曾排队 14 份）。

阶段：
  B  CAD 内逐个 load 全部编译产物 .fas（vl-catch-all 逐文件）
  C  校验每个 .fas 的顶层 defun 符号已绑定且为函数
  D  加载测试框架 + 测试文件（改写 src/ 绝对路径）→ 一次性运行 → 失败明细

用法：
  python3 -u scripts/lib_fas_cad_test2.py --limit 3      # 冒烟：只加载 3 个 .fas
  python3 -u scripts/lib_fas_cad_test2.py                # 完整 B+C+D
  python3 -u scripts/lib_fas_cad_test2.py --dry-run      # 只生成文件
  python3 -u scripts/lib_fas_cad_test2.py --no-run-d     # 跳过阶段 D
"""
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LISP_ROOT = Path("/home/vitalgg/atlisp/lib")
FAS_DIR = Path("/home/vitalgg/atlisp/.lib-fas-test")
W_FAS = "w:/atlisp/.lib-fas-test"
MCP_URL = os.environ.get("MCP_URL", "http://192.168.1.53:8110/mcp")
POLL_TIMEOUT = 120 * 60

# 阶段 D 排除：pickset（交互式选点）、ui/getdist（交互取点）、
# test.lsp（内含 (alert ...) 模态对话框，会卡死 CAD 消息泵）
EXCLUDE_TEST = {"pickset", "ui/test-ui-getdist.lsp", "test.lsp"}

FW_FILES = ("suite add-case run-case run-suite run-all init clear summary "
            "assert-equal assert-nil assert-t assert-throw test-framework").split()


# ---------------------------------------------------------------- MCP
def mcp_call(code, tries=12, timeout=180):
    """eval_lisp_with_result。仅对 "No open document"（ROT 假阴性，未派发）重试。"""
    payload = {
        "jsonrpc": "2.0", "id": 1, "method": "tools/call",
        "params": {"name": "eval_lisp_with_result", "arguments": {"code": code}},
    }
    last = ""
    for i in range(tries):
        req = urllib.request.Request(
            MCP_URL, data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                obj = json.loads(r.read().decode())
        except urllib.error.HTTPError as e:
            if e.code == 429:
                wait = float(e.headers.get("retryAfter", "5") or 5)
                print(f"  429，等待 {wait:.0f}s ...")
                time.sleep(max(wait, 3))
                continue
            raise
        except Exception as e:                      # 超时/网络：可能已派发
            return f"<timeout: {e}>"
        res = obj.get("result") or {}
        last = "".join(c.get("text", "") for c in res.get("content", [])
                       if c.get("type") == "text")
        if "No open document" in last:
            time.sleep(2 + i)
            continue
        return last
    return last


def wait_visible(name, timeout=600, step=10):
    """等共享盘新文件在 CAD 侧可见（findfile 非 nil）。"""
    code = f'(findfile "{W_FAS}/{name}")'
    t0 = time.time()
    while time.time() - t0 < timeout:
        out = mcp_call(code, tries=6)
        if out and "No open document" not in out and out.strip() not in ("", "nil"):
            print(f"  可见: {name}  ({time.time() - t0:.0f}s)")
            return True
        time.sleep(step)
    print(f"  !! 超时不可见: {name}")
    return False


# ---------------------------------------------------------------- 清单
# 顶层（defun 之外）的交互式调用在 load .fas 时会真的执行并等用户输入，
# 实测 block/ssget.lsp 末尾 6 个示例调用（(block:ssget nil "块名" nil) …）
# 让 ZWCAD 卡在 ssget 提示上。这类 .fas 一律跳过加载。
RISKY_TOP_HEADS = {
    "ssget", "getpoint", "getcorner", "entsel", "nentsel", "getstring",
    "getint", "getreal", "getdist", "getkword", "command", "vl-cmdf",
    "alert", "initget",
}


def _risky_top_level(rel):
    """源文件顶层是否有会阻塞的交互式调用。"""
    src = LISP_ROOT / "src" / (rel[:-4] + ".lsp")
    if not src.exists():
        return False
    sys.path.insert(0, str(ROOT))
    from compiler.parser import Parser
    try:
        ast = Parser(src.read_text(encoding="utf-8", errors="replace")).parse()
    except Exception:
        return False
    for f in ast.forms:
        if type(f).__name__ != "Call":
            continue
        # 命名空间前缀也要剥掉：block:ssget 内部就是 ssget
        head = getattr(f, "name", "").lower().split(":")[-1]
        if head in RISKY_TOP_HEADS:
            return True
    return False


def collect_fas():
    out, skipped = [], []
    for dirpath, _dirs, files in os.walk(FAS_DIR):
        for fn in sorted(files):
            if fn.endswith(".fas"):
                out.append(os.path.relpath(os.path.join(dirpath, fn),
                                           FAS_DIR).replace(os.sep, "/"))
    out.sort()
    keep = []
    for rel in out:
        if _risky_top_level(rel):
            skipped.append(rel)
        else:
            keep.append(rel)
    if skipped:
        print(f"  跳过（顶层交互式调用，load 时会卡住 CAD）: {len(skipped)} 个")
        for s in skipped:
            print(f"    - {s}")
    return keep


def collect_syms(fas_list):
    sys.path.insert(0, str(ROOT))
    from compiler.parser import Parser
    syms = []
    for rel in fas_list:
        src = LISP_ROOT / "src" / (rel[:-4] + ".lsp")
        if not src.exists():
            continue
        ast = Parser(src.read_text(encoding="utf-8")).parse()
        for f in ast.forms:
            if type(f).__name__ == "Defun":
                syms.append((rel, f.name))
    return syms


# 一定弹交互提示的函数（带命名空间前缀也算）；`(ssget)`/`(block:ssget)` 无参
# 形式会提示「选择对象」，带 "X" 等过滤参数的 ssget 不会，故只匹配空参形式。
# xyp 命名空间整体是「用户输入」封装（xyp:ustr/ureal/upoint/ukword/uinit/udist/
# uangle 都会停在命令行等输入），整族排除。
RISKY_TEST_RE = re.compile(
    r"[:(](getpoint|getcorner|entsel|nentsel|getstring|getint|getreal"
    r"|getdist|getkword|getangle|initget|getfiled|vl-file-dialog)\b"
    r"|\((?:[\w-]+:)?ssget\)|\bxyp:",
    re.IGNORECASE)


def paren_balance(text):
    """AutoLISP 读取器视角的括号净深度（0 = 完整可读）。"""
    depth = 0
    in_str = esc = in_comment = False
    for ch in text:
        if ch == "\n":
            in_comment = False
            continue
        if in_comment:
            continue
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == ";":
            in_comment = True
        elif ch == '"':
            in_str = True
        elif ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
    return depth


def collect_testfiles():
    out = []
    broken = []
    base = LISP_ROOT / "test"
    for dirpath, _dirs, files in os.walk(base):
        rel_dir = os.path.relpath(dirpath, base).replace(os.sep, "/")
        if rel_dir.startswith("pickset"):
            continue
        for fn in sorted(files):
            if not fn.endswith(".lsp"):
                continue
            rel = fn if rel_dir == "." else f"{rel_dir}/{fn}"
            if rel in EXCLUDE_TEST:
                continue
            # 模态对话框/交互输入会卡死 CAD 消息泵（实测 lib/test/test.lsp 的
            # (alert ...) 让 ZWCAD 完全无响应），整文件跳过。
            text = (base / rel).read_text(encoding="utf-8", errors="replace")
            if "(alert" in text:
                print(f"  跳过（含 alert 模态框）: {rel}")
                continue
            # 用例运行时才执行（不是 load 时），会停在「选择对象/输入」提示上把
            # CAD 卡死：block/test-block-ssget.lsp 的 (block:ssget)、
            # ui/test-ui-getstring.lsp 的 (ui:getstring)。
            if RISKY_TEST_RE.search(text):
                print(f"  跳过（用例会等待交互输入）: {rel}")
                continue
            # 语料自身括号不平衡：CAD 读取到 EOF 报「输入的列表有缺陷」，
            # 与编译产物无关，本地就筛掉（126 个，多为自动生成时漏右括号）。
            bal = paren_balance(text)
            if bal != 0:
                broken.append((rel, bal))
                continue
            out.append(rel)
    if broken:
        print(f"  跳过（源文件括号不平衡，CAD 无法读取）: {len(broken)} 个")
    return sorted(out), broken


# ---------------------------------------------------------------- driver
DRIVER_TPL = r''';;; lib .fas CAD test driver (small; data read from text files)
(defun @::d:log (nm msg / f)
  (setq f (open (strcat "w:/atlisp/.lib-fas-test/" nm) "a"))
  (princ msg f)
  (princ "\n" f)
  (close f))
(defun @::d:load (path) (vl-catch-all-apply 'load (list path)))
(defun @::d:ps (v / s)
  (setq s (vl-catch-all-apply 'vl-prin1-to-string (list v)))
  (if (vl-catch-all-error-p s)
    "<unprintable>"
    (if (> (strlen s) 300) (strcat (substr s 1 300) "...") s)))
(defun @::d:replace (s old new / i out)
  (setq out "")
  (setq i (vl-string-search old s))
  (while i
    (setq out (strcat out (substr s 1 i) new))
    (setq s (substr s (+ i (strlen old) 1)))
    (setq i (vl-string-search old s)))
  (strcat out s))
(defun @::d:head (lst k / acc)
  (setq acc nil)
  (while (and lst (> k 0))
    (setq acc (cons (car lst) acc))
    (setq lst (cdr lst))
    (setq k (1- k)))
  (reverse acc))
(defun @::d:run-case (nm fn expected / r pass msg)
  (setq fn (if (and (listp fn) (listp (car fn))) (car fn) fn))
  (setq r (vl-catch-all-apply fn (list)))
  (if (vl-catch-all-error-p r)
    (progn
      (setq msg (strcat "ERR: " (vl-catch-all-error-message r)))
      (setq pass nil))
    (progn
      (setq pass (vl-catch-all-apply 'test:assert-equal (list expected r 0.000001)))
      (if (vl-catch-all-error-p pass)
        (progn
          (setq msg (strcat "ASSERT-ERR: " (vl-catch-all-error-message pass)))
          (setq pass nil))
        (setq msg r))))
  (if pass
    (setq *test-pass-count* (1+ *test-pass-count*))
    (setq *test-fail-count* (1+ *test-fail-count*)))
  (setq *test-results* (cons (list nm pass msg expected) *test-results*)))
(defun @::d:main ( / fas syms tests fw lim n r fp nm st miss fails tfails tn rw i)
  (setq @::d:fas nil @::d:syms nil @::d:tests nil @::d:fw nil @::d:lim 0)
  (setq r (@::d:load "w:/atlisp/.lib-fas-test/@DATA@"))
  (if (vl-catch-all-error-p r)
    (@::d:log "report-err.txt"
      (strcat "DATA-LOAD-ERROR: " (vl-catch-all-error-message r)))
    (setq fas @::d:fas syms @::d:syms tests @::d:tests fw @::d:fw lim @::d:lim))
  (@::d:log "report-progress.txt"
    (strcat "DATA fas=" (itoa (length fas)) " syms=" (itoa (length syms))
            " tests=" (itoa (length tests)) " fw=" (itoa (length fw))
            " lim=" (itoa (if lim lim 0))))
  (if (and lim (> lim 0))
    (setq fas (@::d:head fas lim)))
  ;; ---------- Phase B: load .fas ----------
  (setq n 0)
  (setq fails nil)
  (foreach fp fas
    (setq n (1+ n))
    (if (zerop (rem n 100))
      (@::d:log "report-progress.txt"
        (strcat "LOAD " (itoa n) "/" (itoa (length fas)))))
    (setq r (@::d:load (strcat "w:/atlisp/.lib-fas-test/" fp)))
    (if (vl-catch-all-error-p r)
      (progn
        (setq fails (cons fp fails))
        (@::d:log "report-load.txt"
          (strcat "FAIL " fp " :: " (vl-catch-all-error-message r))))))
  (@::d:log "report-load.txt"
    (strcat "LOAD-DONE total=" (itoa (length fas)) " fails=" (itoa (length fails))))
  (@::d:log "report-progress.txt" "PHASE-C")
  ;; ---------- Phase C: symbol check ----------
  (setq miss nil)
  (foreach ln syms
    (setq i (vl-string-search "|" ln))
    (if i
      (progn
        (setq fp (substr ln 1 i))
        (setq nm (substr ln (+ i 2)))
        (setq st (vl-catch-all-apply 'boundp (list (read nm))))
        (if (or (vl-catch-all-error-p st) (not st))
          (setq miss (cons (strcat fp " :: " nm) miss))
          (progn
            (setq st (vl-catch-all-apply 'eval (list (read nm))))
            (if (vl-catch-all-error-p st)
              (setq miss (cons (strcat fp " :: " nm " eval-err") miss))
              (if (not (member (type st) '(SUBR USUBR EXRXSUBR SUBRFUN)))
                (setq miss (cons (strcat fp " :: " nm " type=" (vl-prin1-to-string (type st))) miss)))))))))
  (@::d:log "report-sym.txt"
    (strcat "SYM-DONE total=" (itoa (length syms)) " missing=" (itoa (length miss))))
  (foreach nm miss
    (@::d:log "report-sym.txt" (strcat "MISS " nm)))
  (@::d:log "report-progress.txt" "PHASE-D")
  ;; ---------- Phase D: framework + test files + one run ----------
  (foreach nm fw
    (setq r (@::d:load (strcat "w:/atlisp/.lib-fas-test/test/" nm ".fas")))
    (if (vl-catch-all-error-p r)
      (@::d:log "report-test-load.txt"
        (strcat "FW-FAIL " nm " :: " (vl-catch-all-error-message r)))))
  (setq *test-suite* '())
  (setq *test-results* '())
  (setq *test-pass-count* 0)
  (setq *test-fail-count* 0)
  (setq @::d:orig-run (eval 'test:run-all))
  (setq @::d:orig-clear (eval 'test:clear))
  (defun test:run-all () nil)
  (defun test:clear () nil)
  (setq tn 0)
  (setq tfails nil)
  (foreach fp tests
    (setq tn (1+ tn))
    (if (zerop (rem tn 100))
      (@::d:log "report-progress.txt"
        (strcat "TEST " (itoa tn) "/" (itoa (length tests)))))
    (setq rw (strcat "w:/atlisp/.lib-fas-test/@RWDIR@/"
                     (@::d:replace fp "/" "_")))
    (setq r (@::d:load rw))
    (if (vl-catch-all-error-p r)
      (progn
        (setq tfails (cons fp tfails))
        (@::d:log "report-test-load.txt"
          (strcat "FAIL " fp " :: " (vl-catch-all-error-message r))))))
  (@::d:log "report-test-load.txt"
    (strcat "TESTLOAD-DONE total=" (itoa (length tests))
            " fails=" (itoa (length tfails))))
  ;; Cannot call test:run-all: lib/src/test/run-all.lsp passes 3 extra printf
  ;; style args to string:format, whose signature is (str formatlist) -- CAD
  ;; answers "too many arguments". Run every registered case directly instead.
  (setq *test-pass-count* 0)
  (setq *test-fail-count* 0)
  (setq *test-results* nil)
  (setq tn 0)
  (foreach st *test-suite*
    (foreach fp (cdr st)
      (setq tn (1+ tn))
      (if (zerop (rem tn 200))
        (@::d:log "report-progress.txt" (strcat "RUN " (itoa tn))))
      (@::d:run-case (car fp) (cadr fp) (caddr fp))))
  (setq @::d:symap nil)
  (foreach st *test-suite*
    (foreach fp (cdr st)
      (setq @::d:symap (cons (cons (car fp) (car st)) @::d:symap))))
  (@::d:log "report-test.txt"
    (strcat "RUN-DONE pass=" (itoa *test-pass-count*)
            " fail=" (itoa *test-fail-count*)
            " results=" (itoa (length *test-results*))))
  (foreach r *test-results*
    (if (not (cadr r))
      (progn
        (setq nm (car r))
        (setq st (cdr (assoc nm @::d:symap)))
        (@::d:log "report-test.txt"
          (strcat "FAIL"
            (if st (strcat " [" (vl-prin1-to-string st) "]") "")
            " " (vl-prin1-to-string nm)
            " expected=" (@::d:ps (cadr (cddr r)))
            " actual=" (@::d:ps (caddr r)))))))
  (@::d:log "report-done.txt"
    (strcat "DONE load-fails=" (itoa (length fails))
            " sym-missing=" (itoa (length miss))
            " test-load-fails=" (itoa (length tfails))))
  nil)
(@::d:log "report-progress.txt" "RUN-START")
(setq @::d:catch (vl-catch-all-apply '@::d:main (list)))
(if (vl-catch-all-error-p @::d:catch)
  (@::d:log "report-err.txt"
    (strcat "DRIVER-ERROR: " (vl-catch-all-error-message @::d:catch))))
(@::d:log "report-progress.txt" "ALL-DONE")
'''


def lisp_quote_list(items):
    """["a", "b"] -> '("a" "b")，转义反斜杠与双引号。"""
    esc = [s.replace("\\", "\\\\").replace('"', '\\"') for s in items]
    return "'(" + " ".join(f'"{s}"' for s in esc) + ")"


def gen_files(tag, fas_list, syms, testfiles, limit):
    """清单写成一个 data-<tag>.lsp（load 一次拿全部）。

    ZWCAD 2026 的 read-line 在循环里会随机抛 `undefined function - nil`
    （同一文件 42/70/2/73 行不等，本地磁盘副本同样复现），不能用来读清单；
    而 71 KB 的数据 .lsp 直接 load 实测正常（902/909/517 全部到位）。
    """
    names = {
        "data": f"data-{tag}.lsp",
        "rwdir": f".rw-{tag}",
        "drv": f"driver-{tag}.lsp",
    }
    lines = [
        f"(setq @::d:fas {lisp_quote_list(fas_list)})",
        f"(setq @::d:syms {lisp_quote_list([f'{p}|{s}' for p, s in syms])})",
        f"(setq @::d:tests {lisp_quote_list(testfiles)})",
        f"(setq @::d:fw {lisp_quote_list(FW_FILES)})",
        f"(setq @::d:lim {limit})",
    ]
    (FAS_DIR / names["data"]).write_text("\n".join(lines) + "\n", encoding="ascii")

    # 预生成改写后的测试文件：源文件里的 (load "src/...") 会把 .lsp 源码
    # 重新载入并覆盖本驱动已加载的 .fas，所以整行注释掉；每个文件末尾的
    # (test:run-all) 也置空，留到最后一次性执行。
    rw_path = FAS_DIR / names["rwdir"]
    rw_path.mkdir(exist_ok=True)
    for rel in testfiles:
        text = (LISP_ROOT / "test" / rel).read_text(encoding="utf-8", errors="replace")
        out = []
        for ln in text.splitlines():
            if ln.lstrip().startswith('(load "src/'):
                ln = "(princ) ;" + ln
            out.append(ln.replace("(test:run-all)", "(princ)"))
        (rw_path / rel.replace("/", "_")).write_text(
            "\n".join(out) + "\n", encoding="gbk", errors="replace")
    (rw_path / "_ready.txt").write_text("ready\n", encoding="ascii")

    drv = (DRIVER_TPL
           .replace("@DATA@", names["data"])
           .replace("@RWDIR@", names["rwdir"]))
    drv.encode("ascii")          # 非 ASCII 直接抛错
    (FAS_DIR / names["drv"]).write_text(drv, encoding="ascii")
    return names


def read_report(name):
    p = FAS_DIR / name
    if not p.exists():
        return []
    return p.read_text(encoding="gbk", errors="replace").splitlines()


def main():
    global MCP_URL
    dry_run = "--dry-run" in sys.argv
    skip_d = "--no-run-d" in sys.argv
    limit = 0
    if "--limit" in sys.argv:
        limit = int(sys.argv[sys.argv.index("--limit") + 1])
    if "--url" in sys.argv:
        MCP_URL = sys.argv[sys.argv.index("--url") + 1]
    print(f"MCP: {MCP_URL}")

    tag = datetime.now().strftime("%H%M%S")
    print("== 收集清单 ==")
    fas_list = collect_fas()
    syms = collect_syms(fas_list)
    testfiles, broken = ([], []) if skip_d else collect_testfiles()
    print(f"  .fas: {len(fas_list)}   符号: {len(syms)}   测试文件: {len(testfiles)}")
    if not fas_list:
        sys.exit("没有 .fas 文件，先运行 batch_compare.py ours 编译")

    print(f"== 生成 driver-{tag}.lsp + 数据文件 ==")
    for fn in os.listdir(FAS_DIR):
        if fn.startswith("report-") and fn.endswith(".txt"):
            os.remove(FAS_DIR / fn)
    # 清掉上一轮的改写目录（每轮用新的 .rw-<tag>/，避免 SMB 目录缓存）
    for d in FAS_DIR.glob(".rw-*"):
        if d.is_dir():
            for fn in d.iterdir():
                fn.unlink()
            d.rmdir()

    if broken:
        (FAS_DIR / "broken-tests.txt").write_text(
            "\n".join(f"{p}  depth={d}" for p, d in broken) + "\n",
            encoding="utf-8")
        print(f"  括号不平衡清单: {FAS_DIR / 'broken-tests.txt'}")

    names = gen_files(tag, fas_list, syms, testfiles, limit)
    drv_path = FAS_DIR / names["drv"]
    print(f"  {names['drv']}: {drv_path.stat().st_size} bytes  (limit={limit})")
    print(f"  {names['data']}: {(FAS_DIR / names['data']).stat().st_size} bytes")
    print(f"  {names['rwdir']}/: {len(testfiles)} 个改写测试文件")

    sys.path.insert(0, str(ROOT))
    from tools.validate import validate_file
    if not validate_file(drv_path):
        sys.exit("driver 本地语法校验失败")
    print("  本地语法校验: OK")
    if dry_run:
        print("--dry-run: 不触发 CAD")
        return

    print("== 等 CAD 侧可见（SMB 目录缓存）==")
    for rel in (names["drv"], names["data"], f"{names['rwdir']}/_ready.txt"):
        if not wait_visible(rel):
            sys.exit(f"文件在 CAD 侧不可见: {rel}")

    print("== 触发 CAD ==")
    prog = FAS_DIR / "report-progress.txt"
    trigger = f'(load "{W_FAS}/{names["drv"]}" T)'
    for attempt in range(3):
        out = mcp_call(trigger, tries=12)
        print(f"  第 {attempt + 1} 次触发响应: {out[:120]!r}")
        if "No open document" in out or out.startswith("<timeout"):
            continue
        # 空响应 = 已派发（长 load），等标记
        t0 = time.time()
        while time.time() - t0 < 180:
            if prog.exists() and "RUN-START" in "\n".join(read_report("report-progress.txt")):
                break
            time.sleep(5)
        if prog.exists():
            break
        print("  180s 无 RUN-START，重新确认可见性后再触发")
        for k in ("drv", "fas"):
            wait_visible(names[k], timeout=180)
    if not prog.exists():
        sys.exit("driver 未启动（无 report-progress.txt）")

    print("== 等待完成（轮询报告文件）==")
    done = FAS_DIR / "report-done.txt"
    err = FAS_DIR / "report-err.txt"
    deadline = time.time() + POLL_TIMEOUT
    last = ""
    while time.time() < deadline:
        if done.exists() or err.exists():
            break
        lines = read_report("report-progress.txt")
        if lines and lines[-1] != last:
            last = lines[-1]
            print(f"  进度: {last}")
        time.sleep(5)
    else:
        print("!! 超时未完成")
        sys.exit(2)

    print("\n== 结果 ==")
    if err.exists():
        print("DRIVER 崩溃:")
        for ln in read_report("report-err.txt"):
            print(" ", ln)
    for name, label in [
        ("report-load.txt", "阶段 B .fas 加载"),
        ("report-sym.txt", "阶段 C 符号校验"),
        ("report-test-load.txt", "阶段 D 测试文件加载"),
        ("report-test.txt", "阶段 D 测试运行"),
    ]:
        lines = read_report(name)
        if not lines:
            print(f"\n[{label}] (无报告)")
            continue
        print(f"\n[{label}]")
        for ln in lines:
            print(" ", ln)
    if done.exists():
        print("\n完成标记:", read_report("report-done.txt"))


if __name__ == "__main__":
    main()
