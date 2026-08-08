#!/usr/bin/env python3
"""CAD 模态对话框自动关闭（避免阻塞 MCP 会话）。

AutoCAD/天正等 CAD 偶尔弹出模态对话框（错误框、提示框、命令中断框），
会阻塞 `atlisp-mcp` 的 eval 调用。本工具枚举指定 CAD 进程的顶层窗口，
检测可见的 `#32770` 标准对话框并模拟点击 OK/取消 / 发送 WM_CLOSE 关闭。

实现：编译 `tools/src/cad_dialog_killer.cs` 为 exe（用 Windows csc），
Python 封装提供 `kill_once(pid)` 单次扫描与 `watch(pid)` 持续监听。

用法：
    python -m tools.cad_dialog_killer <pid> [--watch] [--timeout-s 60]
    python -m tools.cad_dialog_killer all --watch        # 扫描所有 CAD 进程

依赖：Windows + .NET Framework（csc.exe 编译 C#）。非 Windows 平台报错提示。
"""
import argparse
import os
import subprocess
import sys
import tempfile

_CS_SOURCE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "src", "cad_dialog_killer.cs")
_EXE_CACHE = os.path.join(tempfile.gettempdir(), "atlispcc_cad_dialog_killer.exe")


def _find_csc():
    """定位 Windows C# 编译器（csc.exe）。"""
    import shutil
    candidates = [
        # Windows 原生 python：expandvars 展开 %WINDIR%
        os.path.expandvars(r"%WINDIR%\Microsoft.NET\Framework64\v4.0.30319\csc.exe"),
        os.path.expandvars(r"%WINDIR%\Microsoft.NET\Framework\v4.0.30319\csc.exe"),
        # cygwin python：%WINDIR% 不展开时手动拼
        "C:\\Windows\\Microsoft.NET\\Framework64\\v4.0.30319\\csc.exe",
        "C:\\Windows\\Microsoft.NET\\Framework\\v4.0.30319\\csc.exe",
    ]
    for c in candidates:
        if os.path.exists(c):
            return c
    # 经 PATH（cygwin /usr/bin/csc → Windows Framework csc）
    w = shutil.which("csc")
    if w and os.path.exists(os.path.realpath(w)):
        return os.path.realpath(w)
    return None


def _win_path(p):
    """把 cygwin 路径转为 Windows 绝对路径（经 cygpath -w）。"""
    import shutil
    if p.startswith("/cygdrive/") or (p.startswith("/") and not p.startswith("//")):
        w = shutil.which("cygpath")
        if w:
            r = subprocess.run([w, "-w", p], capture_output=True, text=True)
            if r.returncode == 0 and r.stdout.strip():
                return r.stdout.strip()
    return os.path.abspath(p)


def _build_exe():
    """把 C# 源编译为 exe（缓存于临时目录）。"""
    if os.path.exists(_EXE_CACHE):
        return _EXE_CACHE
    csc = _find_csc()
    if not csc:
        raise RuntimeError("csc.exe 未找到（需要 Windows .NET Framework）")
    if not os.path.exists(_CS_SOURCE):
        raise RuntimeError(f"C# 源缺失: {_CS_SOURCE}")
    # cygwin python：csc 是 /usr/bin/csc（符号链接 → /cygdrive/c/.../csc.exe）。
    # 优先用 cygdrive 路径（subprocess 可直接执行）；源/输出转 Windows 路径。
    import shutil
    cyg = shutil.which("csc")
    exe = os.path.realpath(cyg) if cyg else csc
    src = _win_path(_CS_SOURCE)
    out = _win_path(_EXE_CACHE)
    r = subprocess.run([exe, f"/out:{out}", src],
                       capture_output=True, text=True, errors="replace")
    if not os.path.exists(_EXE_CACHE):
        # Windows 原生 python：_EXE_CACHE 已是 Windows 路径
        if os.path.exists(_EXE_CACHE.replace("/", os.sep)):
            return _EXE_CACHE.replace("/", os.sep)
        raise RuntimeError(f"编译失败: {r.stdout[-400:]}{r.stderr[-400:]}")
    return _EXE_CACHE


def _cad_pids():
    """列出所有 CAD 进程 PID（acad.exe / zwcad.exe）。"""
    out = subprocess.run(["tasklist"], capture_output=True, text=True).stdout
    pids = []
    for line in out.splitlines():
        low = line.lower()
        if ("acad.exe" in low or "zwcad" in low) and "image" not in low:
            parts = line.split()
            if len(parts) >= 2 and parts[1].isdigit():
                pids.append(int(parts[1]))
    return pids


def kill_once(pid=None, strategy="click"):
    """单次扫描并关闭 CAD 对话框。pid=None 时扫描所有 CAD 进程。

    返回已关闭的对话框数量。
    """
    exe = _build_exe()
    targets = [pid] if pid else _cad_pids()
    total = 0
    for p in targets:
        try:
            r = subprocess.run([exe, str(p), "--strategy", strategy],
                               capture_output=True, text=True, timeout=15)
            # stdout 形如 "closed dialog: ..." 或 "scanned: closed=N"
            if r.stdout:
                total += 1 if "closed dialog" in r.stdout else 0
        except subprocess.TimeoutExpired:
            pass
    return total


def watch(pid=None, timeout_s=120, interval_ms=1000, strategy="click"):
    """持续监听并关闭 CAD 对话框（阻塞直到 timeout_s 结束）。

    适合在 cad_verify 等真机测试前启动一个后台进程。
    """
    exe = _build_exe()
    targets = [pid] if pid else _cad_pids()
    procs = []
    for p in targets:
        procs.append(subprocess.Popen(
            [exe, str(p), "--watch", "--timeout-s", str(timeout_s),
             "--interval-ms", str(interval_ms), "--strategy", strategy],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))
    return procs


def main():
    ap = argparse.ArgumentParser(description="关闭 CAD 模态对话框（避免阻塞 MCP）")
    ap.add_argument("pid", nargs="?", default=None,
                    help="CAD 进程 PID；省略或 'all' 时扫描全部 CAD 进程")
    ap.add_argument("--watch", action="store_true", help="持续监听（直到 --timeout-s）")
    ap.add_argument("--timeout-s", type=int, default=120)
    ap.add_argument("--interval-ms", type=int, default=1000)
    ap.add_argument("--strategy", default="click",
                    choices=["click", "close", "destroy"])
    a = ap.parse_args()

    try:
        if a.watch:
            procs = watch(a.pid, a.timeout_s, a.interval_ms, a.strategy)
            for p in procs:
                p.wait()
            return 0
        n = kill_once(a.pid, a.strategy)
        print(f"closed dialogs: {n}")
        return 0
    except RuntimeError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
