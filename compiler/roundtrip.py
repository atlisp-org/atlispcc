"""往返冒烟测试 — `atlispcc roundtrip <lsp> [-O N]`。

compile → decompile → validate → compare 一键自检。

管线说明: 有意使用「裸内存管线」（与 tests/test_compile_decompile.py
`compile_and_decompile` 同款），而非顶层表达式进入 seg1 模块代码的 CLI 管线。
后者会把 defun 外的 ``(princ "...")`` 等顶层表达式编译进 seg1 模块代码，
反编译后退化为 nil，导致字符串比对误报。roundtrip 定位是代码生成回归自检，
产物直接用 `atlispcc compile` 构建。
"""
import os
import shutil
import sys
import tempfile
import traceback
import pathlib
from typing import Optional, Tuple

ENCODE_POP = bytes([0x0A])


def _compile_to_fas(src: str, opt_level: int = 0):
    """裸内存管线编译 .lsp → (seg0, seg1, symtab)。参考 tests 的 compile_and_decompile。"""
    from compiler.parser import Parser
    from compiler.symbol_table import SymbolTable
    from compiler.codegen import CodeGenerator, BytecodeBuffer
    from compiler.resource_builder import ResourceBuilder
    from compiler.opt import optimize
    from compiler.ast_nodes import Defun

    parser = Parser(src)
    program = parser.parse()

    if opt_level:
        program = optimize(program, level=opt_level)

    symtab = SymbolTable()
    symtab.collect_symbols(program)

    codegen = CodeGenerator(symtab)
    all_bc = BytecodeBuffer()
    func_offsets = {}

    other_forms = [f for f in program.forms if not isinstance(f, Defun)]
    for form in other_forms:
        codegen._emit_expr(all_bc, form)
        all_bc.emit(ENCODE_POP)

    for form in program.forms:
        if isinstance(form, Defun):
            offset = len(all_bc.data)
            fb, _ = codegen.generate_function(form)
            func_offsets[form.name] = offset
            all_bc.emit(fb)

    for name, offset in func_offsets.items():
        symtab.add_func_ref(name, offset)

    all_bc.resolve()
    seg0 = bytes(all_bc.data)
    resource = ResourceBuilder(symtab)
    seg1 = resource.build(func_offsets)
    return seg0, seg1, symtab


def decompile_bytes(seg0, seg1, symtab) -> str:
    """写临时 .fas → 反编译回 Lisp 文本。"""
    from compiler.fas_writer import FasWriter
    from decompiler.fas4_decompiler import (
        Fas4Parser,
        Disassembler,
        ControlFlowAnalyzer,
        LispGenerator,
        is_compact_stub,
    )

    fas_path = os.path.join(
        tempfile.mkdtemp(prefix="atlispcc_roundtrip_"), "roundtrip.fas"
    )
    writer = FasWriter(symtab)
    writer.write(fas_path, seg0, seg1)

    try:
        decomp_parser = Fas4Parser()
        fas = decomp_parser.parse(fas_path)
        disasm = Disassembler(
            short_subr=is_compact_stub(fas.bytecode, fas.function_catalog)
        )
        instructions = disasm.disassemble(fas.bytecode, fas.nsyms)
        cfa = ControlFlowAnalyzer(instructions, fas.function_catalog)
        functions = cfa.find_functions()
        gen = LispGenerator(fas)
        return gen.generate(functions, fas_path)
    finally:
        shutil.rmtree(os.path.dirname(fas_path), ignore_errors=True)


def roundtrip(src: str, opt_level: int = 0) -> tuple:
    """完整往返链路。返回 (decompiled_lsp_text, compare_report, error_or_none)。"""
    from tools.compare_lsp import compare_texts

    try:
        seg0, seg1, symtab = _compile_to_fas(src, opt_level=opt_level)
        decompiled = decompile_bytes(seg0, seg1, symtab)
    except Exception as e:  # noqa: BLE001
        return "", {"ok": False, "error": f"{type(e).__name__}: {e}"}, str(e)

    report = compare_texts(src, decompiled)
    return decompiled, report, None


def _read_source(source: str) -> str:
    from core.fas_core import decode_source_text

    if os.path.exists(source):
        with open(source, "rb") as f:
            return decode_source_text(f.read())
    return source


def run_roundtrip(source: str, opt_level: int = 0, keep: bool = False) -> int:
    """CLI 入口: 编译 → 反编译 → 校验 → 比对。返回 0 通过 / 1 存在差异。

    keep 为 True 时把 .fas 与反编译 .lsp 写到系统临时目录并打印路径。
    """
    from tools.validate import validate_file

    src = _read_source(source)
    decompiled, report, err = roundtrip(src, opt_level=opt_level)
    if err:
        print(f"Roundtrip error: {err}", file=sys.stderr)
        traceback.print_exc(file=sys.stderr)
        return 1

    validate_ok = True
    if os.path.exists(source):
        try:
            validate_ok = validate_file(pathlib.Path(source))
        except Exception as e:  # noqa: BLE001
            print(f"  validate error: {e}")
            validate_ok = False

    print(f"Roundtrip: {source}")
    print("  compile → decompile: OK")
    print(f"  validate source:     {'OK' if validate_ok else 'FAIL'}")
    print(
        f"  defuns:  {len(report['original_defuns'])} → {len(report['decompiled_defuns'])}"
        f"  (missing={len(report['missing_defuns'])}, extra={len(report['extra_defuns'])})"
    )
    print(
        f"  strings: {len(report['original_strings'])} → {len(report['decompiled_strings'])}"
        f"  (missing={len(report['missing_strings'])}, extra={len(report['extra_strings'])})"
    )
    for s in report["missing_strings"]:
        print(f"    missing string: {s!r}")
    for s in report["missing_defuns"]:
        print(f"    missing defun: {s}")

    ok = bool(report.get("ok") and validate_ok)
    print(f"Result: {'PASS' if ok else 'FAIL'}")

    if keep:
        tmpdir = tempfile.mkdtemp(prefix="atlispcc_roundtrip_")
        fas_path = os.path.join(tmpdir, "roundtrip.fas")
        decomp_path = os.path.join(tmpdir, "decompiled.lsp")
        from compiler.fas_writer import FasWriter

        seg0, seg1, symtab = _compile_to_fas(src, opt_level=opt_level)
        writer = FasWriter(symtab)
        writer.write(fas_path, seg0, seg1)
        with open(decomp_path, "w", encoding="utf-8") as f:
            f.write(decompiled)
        print(f"artifacts: {decomp_path}")
        print(f"           {fas_path}")
    return 0 if ok else 1


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser(description="FAS4 往返冒烟测试")
    ap.add_argument("source", help=".lsp 源文件")
    ap.add_argument("-O", "--opt", type=int, default=0, choices=[0, 1, 2, 3])
    ap.add_argument("--keep", action="store_true", help="保留中间 .fas 与反编译 .lsp")
    args = ap.parse_args()
    sys.exit(run_roundtrip(args.source, opt_level=args.opt, keep=args.keep))