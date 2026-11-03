#!/usr/bin/env python3
"""ZWCAD LispConverter.exe GUI 自动化（样本生产）。

用 UIAutomation + Win32 ctypes 驱动 ZWCAD 2017 "FAS&VLX Converter"，
把 .fas 批量转换为 .zelx，供逆向/验证使用（需 Windows 桌面 + exe）。

用法：
  python -m tools.lisp_converter_auto <input.fas>...  [--exe E:/.../LispConverter.exe]
"""
import ctypes
import ctypes.wintypes as wt
import os
import sys
import time
import argparse
from typing import Optional

try:
    import uiautomation as auto
except ImportError:  # 非 Windows / 未装 uiautomation：模块仍可导入，仅运行时需要
    auto = None

u32: Optional[ctypes.WinDLL] = None  # type: ignore[name-defined]
try:
    u32 = ctypes.windll.user32  # type: ignore[attr-defined]
    u32.SendMessageW.argtypes = [wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM]
    u32.PostMessageW.argtypes = [wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM]
    u32.GetClassNameW.argtypes = [wt.HWND, wt.LPWSTR, ctypes.c_int]
except AttributeError:  # 非 Windows 平台无 ctypes.windll
    u32 = None
BM_CLICK = 0x00F5
WM_COMMAND = 0x0111


def _top_windows(pid):
    res = []

    @ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)
    def cb(h, l):
        p = wt.DWORD()
        u32.GetWindowThreadProcessId(h, ctypes.byref(p))
        if p.value == pid:
            c = ctypes.create_unicode_buffer(64)
            u32.GetClassNameW(h, c, 64)
            res.append((h, c.value))
        return True

    u32.EnumWindows(cb, 0)
    return res


def _children(hwnd):
    res = []

    @ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)
    def cb(h, l):
        res.append(h)
        return True

    u32.EnumChildWindows(hwnd, cb, 0)
    return res


def _cls(h):
    c = ctypes.create_unicode_buffer(64)
    u32.GetClassNameW(h, c, 64)
    return c.value


def _click_id(hwnd, cid):
    btns = [h for h in _children(hwnd) if u32.GetDlgCtrlID(h) == cid]
    if not btns:
        return False
    u32.PostMessageW(btns[0], BM_CLICK, 0, 0)
    return True


def _add_file(proc, main, path):
    _click_id(main, 204)                      # Select File
    time.sleep(2)
    dlg = None
    for h, c in _top_windows(proc.pid):
        if c == "#32770" and h != main:
            dlg = h
            break
    if not dlg:
        return False
    fd = auto.ControlFromHandle(dlg)
    fd.EditControl(AutomationId="1148").GetValuePattern().SetValue(os.path.abspath(path))
    time.sleep(0.4)
    fd.ButtonControl(AutomationId="1").Click(simulateMove=False)  # Open
    time.sleep(1)
    return True


def convert(exe, fas_path):
    """启动 LispConverter 把单个 .fas 转为 .zelx（输出到同目录）。"""
    proc = __import__("subprocess").Popen([exe])
    try:
        time.sleep(2)
        main = [h for h, c in _top_windows(proc.pid) if c == "#32770"][0]
        if not _add_file(proc, main, fas_path):
            return False
        _click_id(main, 208)                  # Original Directory
        time.sleep(0.5)
        _click_id(main, 207)                  # Convert All
        time.sleep(4)
        for h, c in _top_windows(proc.pid):   # dismiss Converted!/error box
            if c == "#32770" and h != main:
                u32.SendMessageW(h, WM_COMMAND, 1, 0)
        time.sleep(1)
        _click_id(main, 1)                    # Close
        time.sleep(0.5)
        return os.path.exists(os.path.splitext(fas_path)[0] + ".zelx")
    finally:
        proc.terminate()


def main():
    ap = argparse.ArgumentParser(description="Drive ZWCAD LispConverter.exe (fas→zelx)")
    ap.add_argument("inputs", nargs="+", help=".fas files to convert")
    ap.add_argument("--exe", default="E:/Users/vitalgg/atlisp/atlispcc/LispConverter.exe",
                    help="path to LispConverter.exe")
    a = ap.parse_args()
    if auto is None or u32 is None:
        print("error: 'uiautomation' or ctypes.windll not available "
              "(requires Windows + pip install uiautomation)", file=sys.stderr)
        return 1
    for f in a.inputs:
        if not os.path.exists(f):
            print(f"skip (missing): {f}")
            continue
        ok = convert(a.exe, f)
        print(f"{'OK  ' if ok else 'FAIL'} {f} -> {os.path.splitext(f)[0]}.zelx")
    return 0


if __name__ == "__main__":
    sys.exit(main())
