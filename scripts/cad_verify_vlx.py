#!/usr/bin/env python3
"""CAD 真机验证：VRTLIB-1 VLX 容器与 `_VLX` 导出桩。

流程：
1. 在本机共享目录生成一个探针 FAS（`(defun vlx-probe () 42)` + 一个不导出的函数），
   打包成带 `--export vlx-probe` 的 VLX；
2. 通过 MCP（HTTP JSON-RPC）在 CAD 中新建文档 → `(load "<远程路径>")`；
3. 断言 `(type vlx-probe)` 为 SUBR、调用返回 42，且未导出的 `vlx-probe-hidden` 为 nil。

共享目录约定（与 atlisp-mcp 技能一致）：
  本机 ``~/atlisp/packages/<sub>`` ⇔ 远程 CAD 主机 ``w:/atlisp/packages/<sub>``。
用 ``--local-dir`` / ``--remote-dir`` 覆盖；``--host`` 覆盖 MCP 地址。

用法：
    python scripts/cad_verify_vlx.py
    python scripts/cad_verify_vlx.py --host http://192.168.1.51:8110
    VLX_LOCAL_DIR=~/atlisp/packages/_vlx_probe python scripts/cad_verify_vlx.py

退出码：0 通过 / 1 结果不符 / 2 CAD 未连接 / 3 共享目录里看不到文件 /
4 文件可见但 CAD 加载失败（共享缓存或 CAD 的 VLX 加载器状态异常）。

SMB 共享对**新建**目录项有缓存延迟，但对**已存在**文件的内容更新立即生效：
共享目录不稳定时用 ``--remote-file probe.vlx`` 复用已可见的文件名，
``--wait N`` 则在放弃前重试 N 秒。

注意：MCP 的沙箱拒绝 ``eval_lisp`` 里的文件写入（``open``/``write-char``），
所以只能通过共享目录传文件；共享目录对新建文件的可见性依赖 SMB 目录缓存，
必要时先等待刷新或手工复制一次。
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import uuid
import time
import urllib.error
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

DEFAULT_HOST = os.environ.get("VLX_MCP_HOST", "http://192.168.1.53:8110")
# 点号目录不会进入 `make packages-check` 的 `packages/*/` 扫描，也不会被
# 当成应用包；目录本身要长期保留（SMB 对新建目录项的缓存很慢）。
DEFAULT_LOCAL_DIR = os.environ.get(
    "VLX_LOCAL_DIR", os.path.expanduser("~/atlisp/packages/.atlispcc_vlx_probe")
)
DEFAULT_REMOTE_DIR = os.environ.get(
    "VLX_REMOTE_DIR", "w:/atlisp/packages/.atlispcc_vlx_probe"
)

PROBE_SOURCE = """(defun vlx-probe () 42)
(defun vlx-probe-hidden () 99)
"""


def _rpc(host: str, name: str, arguments: dict, timeout: int = 30) -> dict:
    payload = json.dumps(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": name, "arguments": arguments},
        }
    ).encode("utf-8")
    request = urllib.request.Request(
        host.rstrip("/") + "/mcp",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        data = json.loads(response.read().decode("utf-8"))
    if "error" in data:
        raise RuntimeError(f"{name}: {data['error']}")
    result = data.get("result", {})
    if result.get("isError"):
        texts = [item.get("text", "") for item in result.get("content", [])]
        raise RuntimeError(f"{name}: {' '.join(texts)}")
    return result


def _eval(host: str, code: str) -> str:
    result = _rpc(host, "eval_lisp_with_result", {"code": code, "encoding": "utf-8"})
    return "\n".join(item.get("text", "") for item in result.get("content", []))


_TRANSIENT_MARKERS = (
    "No open document",
    "SERVERCALL_RETRYLATER",
    "应用程序正在使用中",
    "call was rejected by callee",
)


def _eval_retry(host: str, code: str, attempts: int = 20) -> str:
    """新建文档 / CAD 忙（COM RPC_E_SERVERCALL_RETRYLATER）时重试。"""
    last = ""
    for _ in range(attempts):
        try:
            return _eval(host, code)
        except RuntimeError as exc:
            last = str(exc)
            if not any(marker in last for marker in _TRANSIENT_MARKERS):
                raise
            time.sleep(0.5)
    raise RuntimeError(last)


def _health(host: str) -> dict:
    with urllib.request.urlopen(host.rstrip("/") + "/health", timeout=10) as response:
        return json.loads(response.read().decode("utf-8"))


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify a VRTLIB-1 VLX in a live CAD")
    parser.add_argument("--host", default=DEFAULT_HOST, help="MCP base URL")
    parser.add_argument("--local-dir", default=DEFAULT_LOCAL_DIR, help="shared directory (local)")
    parser.add_argument("--remote-dir", default=DEFAULT_REMOTE_DIR, help="shared directory (CAD side)")
    parser.add_argument("--date", default="2/3/26", help="pinned build date")
    parser.add_argument("--salt", default="deterministic", help="pinned container salt")
    parser.add_argument(
        "--remote-file",
        default="",
        help="reuse this existing basename under --remote-dir (SMB caches new directory "
        "entries; overwriting a visible file propagates immediately)",
    )
    parser.add_argument(
        "--wait",
        type=float,
        default=0.0,
        help="seconds to retry before giving up when CAD cannot see the file",
    )
    args = parser.parse_args()

    from compiler.compile_cmd import cmd_compile
    from compiler.vlx_builder import build_vlx

    health = _health(args.host)
    if not health.get("cad", {}).get("connected"):
        print(f"CAD not connected on {args.host}: {health}", file=sys.stderr)
        return 2

    local_dir = os.path.abspath(os.path.expanduser(args.local_dir))
    os.makedirs(local_dir, exist_ok=True)
    source = os.path.join(local_dir, "probe.lsp")
    fas = os.path.join(local_dir, "probe.fas")
    if args.remote_file:
        # 复用共享目录里已可见的文件名（SMB 只对已存在文件的内容刷新即时可见）。
        vlx = os.path.join(local_dir, args.remote_file)
    else:
        # 每次用唯一文件名：独立命名空间的 VLX 以文件名标识其命名空间，重名重复加载
        # 在部分 AutoCAD 版本上会失败。
        vlx = os.path.join(local_dir, f"probe_{uuid.uuid4().hex[:8]}.vlx")
    with open(source, "w", encoding="utf-8") as handle:
        handle.write(PROBE_SOURCE)
    cmd_compile(source, fas, date=args.date, salt=args.salt)
    build_vlx([fas], vlx, exports=["vlx-probe"], date=args.date, salt=args.salt)
    print(f"[ok] built {vlx}")

    remote = args.remote_dir.rstrip("/") + "/" + os.path.basename(vlx)
    deadline = time.time() + max(0.0, args.wait)
    while True:
        visible = _eval(args.host, f'(findfile "{remote}")')
        if visible.strip() not in ("nil", ""):
            break
        if time.time() >= deadline:
            print(
                f"[skip] CAD cannot see {remote}. The shared directory may cache directory "
                f"listings; retry with --wait, or pass --remote-file with a name that is "
                f"already visible (overwrites propagate immediately).",
                file=sys.stderr,
            )
            return 3
        time.sleep(1.0)

    try:
        _rpc(args.host, "new_document", {})
    except RuntimeError as exc:
        # 已有未保存图形时 CAD 可能拒绝新建；在当前图形里先清掉同名变量同样可验证。
        print(f"[note] new_document failed ({exc}); verifying in the current document")

    app_name = os.path.splitext(os.path.basename(remote))[0]
    try:
        result = _eval_retry(
            args.host,
            # 同一文件名重复验证时先卸载旧的独立命名空间应用（AutoLISP 的
            # vl-unload-vlx 不存在于 atoms-family 时才值得怀疑；这里用
            # vl-catch-all-apply 忽略「未加载」错误）。
            f"(progn (vl-catch-all-apply 'vl-unload-vlx (list \"{app_name}\")) "
            f"(setq vlx-probe nil vlx-probe-hidden nil) (load \"{remote}\") "
            f"(list (type vlx-probe) (if vlx-probe (vlx-probe) nil) (type vlx-probe-hidden)))",
        )
    except RuntimeError as exc:
        if "LOAD" in str(exc):
            print(
                f"[fail] CAD failed to load {remote}: {exc}\n"
                f"       (shared-directory cache or an already-loaded namespace with the same name)",
                file=sys.stderr,
            )
            return 4
        raise
    print(f"CAD: {result.strip()}")

    expected = "(SUBR 42 nil)"
    if result.strip() == expected:
        print("[ok] VRTLIB-1 VLX loads; exported function works; unexported stays in its namespace")
        return 0
    print(f"[fail] expected {expected}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
