"""Merge several AutoLISP sources into a single ``.fas`` (source-level merge).

Why source-level: the compiler writes top-level (non-``defun``) expressions into
seg1 module code, interleaved with function registration.  Reconstructing that
interleaving from bytecode is lossy and error-prone.  Concatenating the sources
first and compiling once keeps every top-level expression in source order, and
lets the compiler handle symbol slots, jumps, encodings and builds.

Inputs
------
``.lsp``
    Read and concatenated verbatim (Route A).
``.fas``
    Decompiled first (Route B).  NOTE: the decompiler does not reproduce
    top-level expressions, so a ``.fas`` input can only contribute its
    ``defun`` bodies.  This is refused by default; pass ``--allow-lossy-fas``
    to opt in explicitly.
"""

from __future__ import annotations

import contextlib
import io
import os
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Iterable, List, Tuple

from core.fas_core import decode_source_text


def _read_lsp(path: str) -> str:
    return decode_source_text(Path(path).read_bytes())


def _decompile_to_text(path: str) -> str:
    from decompiler.fas4_decompiler import (
        ControlFlowAnalyzer,
        Disassembler,
        Fas4Parser,
        LispGenerator,
        detect_layout,
        extract_stub_function_names,
        use_short_subr,
    )

    fas = Fas4Parser().parse(path)
    stub = detect_layout(fas) == "compact"
    disasm = Disassembler(
        short_subr=use_short_subr(
            fas.bytecode, fas.nsyms, fas.function_catalog, len(fas.symbol_slots)
        )
    )
    instructions = disasm.disassemble(
        fas.bytecode, fas.nsyms, sym_count=len(fas.symbol_slots) if stub else None
    )
    cf = ControlFlowAnalyzer(
        instructions, fas.function_catalog,
        function_names=extract_stub_function_names(fas),
    )
    return LispGenerator(fas).generate(cf.find_functions(), path)


def merge_text(
    inputs: Iterable[str], allow_lossy_fas: bool = False
) -> Tuple[str, List[Tuple[str, str]]]:
    """Return ``(merged_source, [(path, kind), ...])``.

    ``.lsp`` inputs are preserved verbatim; ``.fas`` inputs are decompiled (and
    therefore lose top-level expressions unless the caller opted in).
    """
    chunks: List[Tuple[str, str, str]] = []
    for path in inputs:
        low = path.lower()
        if low.endswith(".lsp"):
            kind = "lsp"
            text = _read_lsp(path)
        elif low.endswith(".fas"):
            if not allow_lossy_fas:
                raise ValueError(
                    f"{path}: .fas input is decompiled and does NOT preserve "
                    "top-level expressions. Provide the .lsp source, or pass "
                    "--allow-lossy-fas to merge the defun bodies only."
                )
            kind = "fas"
            text = _decompile_to_text(path)
            print(
                f"WARNING: {path}: .fas input is decompiled; top-level "
                f"expressions are not preserved (--allow-lossy-fas)",
                file=sys.stderr,
            )
        elif low.endswith(".zelx"):
            raise ValueError(
                f"{path}: .zelx input is not supported; run `atlispcc unzelx` "
                "first, or provide the .lsp source."
            )
        else:
            raise ValueError(f"{path}: unsupported input (need .lsp or .fas)")
        if text and not text.endswith("\n"):
            text += "\n"
        chunks.append((path, kind, text))

    if not chunks:
        raise ValueError("merge needs at least one input")

    merged = "".join(
        f";;; ---- merged from: {os.path.basename(p)} ({kind}) ----\n{text}\n"
        for p, kind, text in chunks
    )
    return merged, [(p, kind) for p, kind, _ in chunks]


def cmd_merge(
    inputs: List[str],
    output: str = "",
    opt_level: int = 0,
    encoding: str = "ansi",
    date=None,
    salt=None,
    keep_source: str = "",
    report_json: str = "",
    verify: bool = True,
    show_analysis: bool = False,
    allow_lossy_fas: bool = False,
) -> int:
    """Merge inputs, compile once, and return a process exit code."""
    for path in inputs:
        if not os.path.exists(path):
            print(f"Error: input not found: {path}", file=sys.stderr)
            return 1

    try:
        merged, used = merge_text(inputs, allow_lossy_fas=allow_lossy_fas)
    except (ValueError, OSError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    if not output:
        stem = os.path.splitext(os.path.abspath(inputs[0]))[0]
        output = stem + "_merged.fas"

    tmpdir = None
    try:
        if keep_source:
            merged_path = keep_source
        else:
            tmpdir = tempfile.mkdtemp(prefix="atlispcc-merge-")
            merged_path = os.path.join(tmpdir, "merged.lsp")

        Path(merged_path).write_text(merged, encoding="utf-8")

        # Validate the merged text before compiling, so syntax errors are
        # reported with the merged file on disk (kept with --keep-source).
        from tools.validate import validate_file

        captured = io.StringIO()
        with contextlib.redirect_stdout(captured):
            ok = validate_file(Path(merged_path))
        if not ok:
            sys.stdout.write(captured.getvalue())
            print(
                f"Error: merged source failed validation ({merged_path})",
                file=sys.stderr,
            )
            if not keep_source:
                print(
                    "Hint: rerun with --keep-source merged.lsp to inspect it.",
                    file=sys.stderr,
                )
            return 1

        from compiler.compile_cmd import cmd_compile

        cmd_compile(
            merged_path,
            output,
            opt_level=opt_level,
            show_analysis=show_analysis,
            encoding=encoding,
            report_json=report_json,
            verify=verify,
            date=date,
            salt=salt,
        )

        kinds = ", ".join(f"{os.path.basename(p)}={k}" for p, k in used)
        print(f"Merged {len(used)} input(s) [{kinds}] -> {output}")
        return 0
    finally:
        if tmpdir:
            shutil.rmtree(tmpdir, ignore_errors=True)
