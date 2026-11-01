"""批量编译：逐文件编译 + 结构化记录（``project`` / ``.prj`` / ``.prv`` 共用）。

单个文件失败不抛出，记录到返回的文件列表与汇总计数里，由调用方决定退出码。
"""

from __future__ import annotations

import contextlib
import io
import os
import time
from typing import Dict, List, Sequence, Tuple

__all__ = ["compile_batch", "compile_one"]


def compile_one(
    label: str,
    src: str,
    target_dir: str = "",
    opt_level: int = 0,
    encoding: str = "ansi",
    verify: bool = True,
    dry_run: bool = False,
    date=None,
    salt=None,
) -> Dict[str, object]:
    """编译单个源文件，返回记录（缺失/失败都记录在 ``status`` 里，不抛异常）。"""
    from compiler.compile_cmd import cmd_compile

    name = os.path.splitext(os.path.basename(src))[0]
    outdir = target_dir or os.path.dirname(src)
    target = os.path.join(outdir, name + ".fas")
    record: Dict[str, object] = {
        "entry": label,
        "source": src,
        "output": target,
        "status": "pending",
        "bytes": 0,
        "elapsed_ms": 0,
    }

    if not os.path.isfile(src):
        record["status"] = "missing"
        return record
    if dry_run:
        record["status"] = "would-compile"
        return record

    started = time.time()
    stdout_buf, stderr_buf = io.StringIO(), io.StringIO()
    try:
        with contextlib.redirect_stdout(stdout_buf), contextlib.redirect_stderr(stderr_buf):
            cmd_compile(
                src,
                target,
                opt_level=opt_level,
                encoding=encoding,
                verify=verify,
                date=date,
                salt=salt,
            )
        if not os.path.isfile(target):
            raise RuntimeError("compiler reported success but output file is missing")
        record["status"] = "ok"
        record["bytes"] = os.path.getsize(target)
    except SystemExit as exc:
        record["status"] = "error"
        record["error"] = f"compiler exited with code {exc.code}"
    except Exception as exc:  # noqa: BLE001 - per-file failure must not abort
        record["status"] = "error"
        record["error"] = str(exc)
    finally:
        record["elapsed_ms"] = int((time.time() - started) * 1000)
        log = (stdout_buf.getvalue() + stderr_buf.getvalue()).strip()
        if log:
            record["log"] = log[-4000:]
    return record


def compile_batch(
    entries: Sequence[Tuple[str, str]],
    target_dir: str = "",
    opt_level: int = 0,
    encoding: str = "ansi",
    verify: bool = True,
    dry_run: bool = False,
    stop_on_error: bool = False,
    date=None,
    salt=None,
) -> Tuple[List[Dict[str, object]], Dict[str, int]]:
    """编译 ``(label, source_path)`` 列表到 ``target_dir``。

    返回 ``(files, summary)``：``files`` 每项含 ``entry/source/output/status/
    bytes/elapsed_ms``（失败时另有 ``error`` / ``log``），``summary`` 为
    ``total/ok/error/missing/skipped``。
    """
    files: List[Dict[str, object]] = []
    summary = {"total": 0, "ok": 0, "error": 0, "missing": 0, "skipped": 0}
    if not dry_run and target_dir:
        os.makedirs(target_dir, exist_ok=True)

    for label, src in entries:
        record = compile_one(
            label,
            src,
            target_dir,
            opt_level=opt_level,
            encoding=encoding,
            verify=verify,
            dry_run=dry_run,
            date=date,
            salt=salt,
        )
        summary["total"] += 1
        status = str(record["status"])
        if status == "would-compile":
            summary["skipped"] += 1
        elif status in summary:
            summary[status] += 1
        files.append(record)
        if status == "error" and stop_on_error:
            break

    return files, summary
