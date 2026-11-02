#!/usr/bin/env python3
"""lib .fas CAD 真机测试（共享盘 driver 方案）。

背景：MCP 长代码路径（withResult/>255 字符，文件交接）加载 .fas 会报
「函数错误: "<relpath>"」，短路径（<=255 字符，SendCommand 直达）正常。
因此把全部测试逻辑放进共享盘上的 driver.lsp，只用一条 45 字符的短 eval
触发，报告写回共享盘（Linux 直接读）。

阶段：
  B  CAD 内逐个 load 全部 902 个编译产物 .fas（vl-catch-all 逐文件）
  C  校验全部公开符号 bound 且为函数（atom/function 探测）
  D  加载测试框架 + 644 个测试文件（(load "src/ 改写为绝对路径），
     stub test:run-all/test:clear 后一次性运行全量测试，提取失败明细

用法：
  python3 -u scripts/lib_fas_cad_test.py            # 完整 B+C+D
  python3 -u scripts/lib_fas_cad_test.py --dry-run  # 只生成 driver.lsp
  python3 -u scripts/lib_fas_cad_test.py --no-run-d # 跳过阶段 D
"""
import json
import os
import socket
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LISP_ROOT = Path("/home/vitalgg/atlisp/lib")
FAS_DIR = Path("/home/vitalgg/atlisp/.lib-fas-test")
W_FAS = "w:/atlisp/.lib-fas-test"
W_LIB = "w:/atlisp/lib"
MCP_URL = "http://192.168.1.53:8110/mcp"
# T 链触发：(load file) 对已注册路径（含失败 load）是 no-op，必须 T 强制重载；
# trigger-test.lsp 内再 (load driver.lsp T)，并落 LOAD-START/LOAD-RESULT 标记
TRIGGER = '(load "w:/atlisp/.lib-fas-test/trigger-test.lsp" T)'
POLL_TIMEOUT = 90 * 60

# 阶段 D 排除：pickset（交互式选点）、ui/getdist（交互取点，会挂起 CAD）
EXCLUDE_TEST = {"pickset", "ui/test-ui-getdist.lsp"}


def mcp_eval(code: str, max_tries: int = 15, timeout: int = 300,
             done_marker: Path = None) -> str:
    """短路径 eval：No open document 重试（COM 假阴性），429 按 retryAfter 退避。

    done_marker：若该文件已出现，说明上一条命令已在 CAD 中执行（长阻塞调用
    超时或空响应的场景），不再重复派发，直接返回。
    """
    payload = {
        "jsonrpc": "2.0", "id": 1, "method": "tools/call",
        "params": {"name": "eval_lisp_with_result", "arguments": {"code": code}},
    }
    last = ""
    last_raw = ""
    for attempt in range(max_tries):
        if done_marker is not None and done_marker.exists():
            return "(已派发，marker 验证)"
        req = urllib.request.Request(
            MCP_URL, data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                obj = json.loads(r.read().decode())
        except (urllib.error.URLError, socket.timeout, TimeoutError) as e:
            # 超时：命令可能已在 CAD 中运行（driver 阻塞数分钟），
            # 先验证 marker，未出现才重试
            last_raw = f"网络/超时错误: {e}"
            if done_marker is not None and done_marker.exists():
                return "(已派发，调用超时但 marker 验证)"
            print(f"  调用超时（{timeout}s），{5}s 后重试 ...")
            time.sleep(5)
            continue
        except urllib.error.HTTPError as e:
            if e.code == 429:
                wait = float(e.headers.get("retryAfter", "5") or 5)
                print(f"  429，等待 {wait:.0f}s ...")
                time.sleep(max(wait, 3))
                continue
            raise
        last_raw = json.dumps(obj, ensure_ascii=False)
        res = obj.get("result") or {}
        last = "".join(c.get("text", "") for c in res.get("content", [])
                       if c.get("type") == "text")
        if "No open document" in last:
            time.sleep(3 + attempt)
            continue
        if not last.strip():
            # 空响应 = 命令可能根本没进 CAD，重试（marker 防重复派发）
            print(f"  空响应（raw: {last_raw[:150]}），{3 + attempt}s 后重试 ...")
            time.sleep(3 + attempt)
            continue
        return last
    raise RuntimeError(f"eval 失败（{max_tries} 次重试）: {last[:200] or last_raw[:200]}")


def collect_fas():
    """全部 .fas 相对路径（斜杠分隔），排序。"""
    out = []
    for dirpath, _dirs, files in os.walk(FAS_DIR):
        for fn in sorted(files):
            if fn.endswith(".fas"):
                out.append(os.path.relpath(os.path.join(dirpath, fn),
                                           FAS_DIR).replace(os.sep, "/"))
    return sorted(out)


def collect_syms(fas_list):
    """每个 .fas 对应的顶层 defun 符号（用 atlispcc parser 解析源文件）。"""
    sys.path.insert(0, str(ROOT))
    from compiler.parser import Parser
    syms = []  # (relpath, defun-name)
    for rel in fas_list:
        src = LISP_ROOT / "src" / (rel[:-4] + ".lsp")
        if not src.exists():
            continue
        ast = Parser(src.read_text(encoding="utf-8")).parse()
        for f in ast.forms:
            if type(f).__name__ == "Defun":
                syms.append((rel, f.name))
    return syms


def collect_testfiles():
    """lib/test 下全部 .lsp（排除 pickset 与交互式用例），相对 lib/test 的路径。"""
    out = []
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
            out.append(rel)
    return sorted(out)


def lisp_str_list(items, max_bytes=700):
    # 按字节换行防超长单行：CAD LISP 文件读取器对 >~832B 的单行会卡死
    # （2026-11-02 bis 实测：911B 行整文件 load 挂起，<=832B 正常）
    lines = []
    cur = ""
    for s in items:
        tok = f'"{s}"'
        if cur and len(cur) + 1 + len(tok) > max_bytes:
            lines.append(cur)
            cur = tok
        else:
            cur = f"{cur} {tok}" if cur else tok
    if cur:
        lines.append(cur)
    return "(\n  " + "\n  ".join(lines) + ")"


def lisp_sym_pairs(pairs, max_bytes=700):
    lines = []
    cur = ""
    for fp, sym in pairs:
        tok = f'("{fp}" . {sym})'
        if cur and len(cur) + 1 + len(tok) > max_bytes:
            lines.append(cur)
            cur = tok
        else:
            cur = f"{cur} {tok}" if cur else tok
    if cur:
        lines.append(cur)
    return "(\n  " + "\n  ".join(lines) + ")"


DRIVER_TPL = ''';;; driver.lsp - @lisp lib .fas CAD test driver (auto-generated, do not edit)
;;; Trigger: (load "w:/atlisp/.lib-fas-test/driver.lsp")
;;; Reports: w:/atlisp/.lib-fas-test/report-*.txt

(progn
  (defun @::d:log (name msg / f)
    (setq f (open (strcat "w:/atlisp/.lib-fas-test/" name) "a"))
    (princ msg f)
    (princ "\\n" f)
    (close f))
  (defun @::d:load (path)
    (vl-catch-all-apply 'load (list path)))
  (defun @::d:replace (s old new / i out)
    (progn
      (setq out "")
      (setq i (vl-string-search old s))
      (while i
        (setq out (strcat out (substr s 1 i) new))
        (setq s (substr s (+ i (strlen old) 1)))
        (setq i (vl-string-search old s)))
      (strcat out s)))
  (defun @::d:readall (path / f s out line)
    (progn
      (setq out "")
      (setq f (open path "r"))
      (while (setq line (read-line f))
        (setq out (strcat out line "\\n")))
      (close f)
      out))
  (defun @::d:ps (v / s)
    (progn
      (setq s (vl-catch-all-apply 'vl-prin1-to-string (list v)))
      (if (vl-catch-all-error-p s)
        (strcat "<unprintable: " (vl-catch-all-error-message s) ">")
        (if (> (strlen s) 300) (strcat (substr s 1 300) "...") s))))
  (defun @::d:main ()
    (progn
      ;; ---------- Phase B: load all .fas ----------
      (setq @::d:n 0)
      (setq @::d:fails '())
      (foreach _fp @::d:fas
        (setq @::d:n (1+ @::d:n))
        (if (zerop (rem @::d:n 100))
          (@::d:log "report-progress.txt"
            (strcat "LOAD " (itoa @::d:n) "/" (itoa (length @::d:fas)))))
        (setq _r (@::d:load (strcat "w:/atlisp/.lib-fas-test/" _fp)))
        (if (vl-catch-all-error-p _r)
          (progn
            (setq @::d:fails
              (cons (strcat _fp " :: " (vl-catch-all-error-message _r)) @::d:fails))
            (@::d:log "report-load.txt"
              (strcat "FAIL " _fp " :: " (vl-catch-all-error-message _r))))))
      (@::d:log "report-load.txt"
        (strcat "LOAD-DONE total=" (itoa (length @::d:fas)) " fails=" (itoa (length @::d:fails))))
      ;; ---------- Phase C: symbol check ----------
      (setq @::d:miss '())
      (foreach _pair @::d:syms
        (if (not (boundp (cadr _pair)))
          (setq @::d:miss
            (cons (strcat (car _pair) " :: unbound " (vl-symbol-name (cadr _pair)))
              @::d:miss))
        (progn
          (setq _c (vl-catch-all-apply 'function (list (cadr _pair))))
          (if (vl-catch-all-error-p _c)
            (setq @::d:miss
              (cons (strcat (car _pair) " :: not-a-function " (vl-symbol-name (cadr _pair)))
                @::d:miss))))))
      (@::d:log "report-sym.txt"
        (strcat "SYM-DONE total=" (itoa (length @::d:syms)) " missing=" (itoa (length @::d:miss))))
      (foreach _m @::d:miss
        (@::d:log "report-sym.txt" (strcat "MISS " _m)))
      (@::d:log "report-progress.txt" "PHASE-D")
      ;; ---------- Phase D: framework + test files + single run ----------
      (foreach _fw @::d:fw
        (setq _r (@::d:load (strcat "w:/atlisp/lib/src/test/" _fw)))
        (if (vl-catch-all-error-p _r)
          (@::d:log "report-test-load.txt"
            (strcat "FW-FAIL " _fw " :: " (vl-catch-all-error-message _r)))))
      (setq *test-suite* '())
      (setq *test-results* '())
      (setq *test-pass-count* 0)
      (setq *test-fail-count* 0)
      (setq @::d:orig-run (function test:run-all))
      (setq @::d:orig-clear (function test:clear))
      (defun test:run-all () nil)
      (defun test:clear () nil)
      (setq @::d:tn 0)
      (setq @::d:tfails '())
      (foreach _tf @::d:testfiles
        (setq @::d:tn (1+ @::d:tn))
        (if (zerop (rem @::d:tn 100))
          (@::d:log "report-progress.txt"
            (strcat "TEST " (itoa @::d:tn) "/" (itoa (length @::d:testfiles)))))
        (setq _src (@::d:readall (strcat "w:/atlisp/lib/test/" _tf)))
        ;; stale refs in test corpus: framework moved to src/test/,
        ;; and entity source file is named reference2definition.lsp
        (setq _src (@::d:replace _src "(load \\"src/fun/test-framework\\")" "(load \\"src/test/test-framework\\")"))
        (setq _src (@::d:replace _src "(load \\"src/entity/reference->definition\\")" "(load \\"src/entity/reference2definition\\")"))
        (setq _src (@::d:replace _src "(load \\"src/" "(load \\"w:/atlisp/lib/src/"))
        (setq _rw (strcat "w:/atlisp/.lib-fas-test/.rw/" (@::d:replace _tf "/" "_")))
        (setq _f (open _rw "w"))
        (write-string _src _f)
        (close _f)
        (setq _r (@::d:load _rw))
        (if (vl-catch-all-error-p _r)
          (progn
            (setq @::d:tfails
              (cons (strcat _tf " :: " (vl-catch-all-error-message _r)) @::d:tfails))
            (@::d:log "report-test-load.txt"
              (strcat "FAIL " _tf " :: " (vl-catch-all-error-message _r))))))
      (@::d:log "report-test-load.txt"
        (strcat "TESTLOAD-DONE total=" (itoa (length @::d:testfiles)) " fails=" (itoa (length @::d:tfails))))
      (set 'test:run-all @::d:orig-run)
      (set 'test:clear @::d:orig-clear)
      (setq _rr (vl-catch-all-apply 'test:run-all (list)))
      (if (vl-catch-all-error-p _rr)
        (@::d:log "report-test.txt" (strcat "RUN-ERROR: " (vl-catch-all-error-message _rr)))
        (progn
          (setq @::d:symap nil)
          (foreach _s *test-suite*
            (foreach _c (cdr _s)
              (setq @::d:symap (cons (cons (car _c) (car _s)) @::d:symap))))
          (@::d:log "report-test.txt"
            (strcat "RUN-DONE pass=" (itoa *test-pass-count*)
              " fail=" (itoa *test-fail-count*)
              " results=" (itoa (length *test-results*))
              " suites=" (itoa (length *test-suite*))))
          (foreach _res *test-results*
            (if (not (cadr _res))
              (progn
                (setq _nm (car _res))
                (setq _st (cdr (assoc _nm @::d:symap)))
                (@::d:log "report-test.txt"
                  (strcat "FAIL"
                    (if _st (strcat " [" (vl-prin1-to-string _st) "]") "")
                    " " (vl-prin1-to-string _nm)
                    " expected=" (@::d:ps (cadr (cddr _res)))
                    " actual=" (@::d:ps (caddr _res)))))))
          nil))
      (@::d:log "report-done.txt"
        (strcat "DONE load-fails=" (itoa (length @::d:fails))
          " sym-missing=" (itoa (length @::d:miss))
          " test-load-fails=" (itoa (length @::d:tfails))))
      nil))
  (@::d:log "report-progress.txt" "RUN-START")
  (setq @::d:catch (vl-catch-all-apply '@::d:main))
  (if (vl-catch-all-error-p @::d:catch)
    (@::d:log "report-err.txt"
      (strcat "DRIVER-ERROR: " (vl-catch-all-error-message @::d:catch))))
  nil)
'''


def gen_driver(fas_list, syms, testfiles):
    driver = DRIVER_TPL
    fw = ("(\"suite\" \"add-case\" \"run-case\" \"run-suite\" \"run-all\" \"init\" "
          "\"clear\" \"summary\" \"assert-equal\" \"assert-nil\" \"assert-t\" "
          "\"assert-throw\" \"test-framework\")")
    driver = driver.replace("(defun @::d:main ()",
                            f"(setq @::d:fas {lisp_str_list(fas_list)})\n"
                            f"(setq @::d:syms {lisp_sym_pairs(syms)})\n"
                            f"(setq @::d:testfiles {lisp_str_list(testfiles)})\n"
                            f"(setq @::d:fw {fw})\n"
                            "(defun @::d:main ()")
    return driver


def read_report(name):
    p = FAS_DIR / name
    if not p.exists():
        return []
    return p.read_text(encoding="gbk", errors="replace").splitlines()


def main():
    dry_run = "--dry-run" in sys.argv
    skip_d = "--no-run-d" in sys.argv

    print("== 收集清单 ==")
    fas_list = collect_fas()
    syms = collect_syms(fas_list)
    testfiles = [] if skip_d else collect_testfiles()
    print(f"  .fas: {len(fas_list)}   符号: {len(syms)}   测试文件: {len(testfiles)}")
    if not fas_list:
        sys.exit("没有 .fas 文件，先运行 batch_compare.py ours 编译")

    print("== 生成 driver.lsp ==")
    driver = gen_driver(fas_list, syms, testfiles)
    try:
        driver.encode("ascii")
    except UnicodeEncodeError as e:
        sys.exit(f"driver.lsp 含非 ASCII 字符: {e}")
    # 清理旧报告与旧改写文件
    for fn in os.listdir(FAS_DIR):
        if fn.startswith("report-") and fn.endswith(".txt"):
            os.remove(FAS_DIR / fn)
    rw = FAS_DIR / ".rw"
    if rw.exists():
        for fn in os.listdir(rw):
            os.remove(rw / fn)
    else:
        rw.mkdir()
    driver_path = FAS_DIR / "driver.lsp"
    driver_path.write_text(driver, encoding="ascii")
    print(f"  driver.lsp: {driver_path} ({len(driver)} bytes)")

    # 本地语法校验
    sys.path.insert(0, str(ROOT))
    from tools.validate import validate_file
    ok = validate_file(driver_path)
    if not ok:
        sys.exit("driver.lsp 本地语法校验失败")
    print("  本地语法校验: OK")

    if dry_run:
        print("--dry-run: 不触发 CAD")
        return

    print("== 触发 CAD ==")
    prog = FAS_DIR / "report-progress.txt"
    out = mcp_eval(TRIGGER, done_marker=prog)
    print(f"  触发响应: {out[:300]}")
    # 快速验证 dispatch：RUN-START 应在 load 开始数秒内出现
    t0 = time.time()
    while time.time() - t0 < 90 and not prog.exists():
        time.sleep(3)
    if not prog.exists():
        sys.exit(f"driver 未启动（90s 内无 report-progress.txt）\n触发响应: {out[:500]}")

    print("== 等待完成（轮询报告文件，最长 30 分钟）==")
    done = FAS_DIR / "report-done.txt"
    err = FAS_DIR / "report-err.txt"
    prog = FAS_DIR / "report-progress.txt"
    deadline = time.time() + POLL_TIMEOUT
    last_line = ""
    while time.time() < deadline:
        if done.exists() or err.exists():
            break
        if prog.exists():
            lines = read_report("report-progress.txt")
            if lines and lines[-1] != last_line:
                last_line = lines[-1]
                print(f"  进度: {last_line}")
        time.sleep(5)
    else:
        print("!! 超时：30 分钟内未完成")
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
