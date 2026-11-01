import sys
import os
import json
import argparse
import struct
from typing import Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from compiler.parser import Parser, ParseError
from compiler.symbol_table import SymbolTable
from compiler.codegen import CodeGenerator, BytecodeBuffer
from asm.opcodes import encode_usubr
from compiler.ast_nodes import (
    Defun,
    Defpackage,
    InPackage,
    Setq,
    Progn,
    IfNode,
    WhileNode,
    ForeachNode,
    RepeatNode,
    Cond,
    Call,
    LambdaNode,
    ListExpr,
    QuotedExpr,
    Symbol,
    Program,
)
from compiler.opt import optimize
from compiler.resource_builder import (
    ResourceBuilder,
    build_module_code,
    build_command_module_code,
    build_mixed_command_module_code,
    count_resource_records,
    count_resource_items,
    resolve_encoding,
    _real_fmt,
)
from compiler.fas_writer import FasWriter
from compiler.analyzer import analyze
from compiler.linker import link_fas
from compiler.vlx_builder import build_vlx
from decompiler.fas4_decompiler import Fas4Parser, Disassembler, ControlFlowAnalyzer, LispGenerator, is_compact_stub, use_short_subr
from tools.validate import validate_file


from compiler.compile_cmd import ENCODE_POP, cmd_compile
from compiler.lowering import (
    _collect_builtins_for_stub,
    _count_kwote_lambdas,
    _flatten_top_level_forms,
    _hoist_conditional_defuns,
    _lower_immediate_lambda,
    _lower_let,
    _lower_multi_kwote,
    _lower_nested_defuns,
)
from compiler.module_code import _build_cad_module_code
from compiler.patch import _patch_usubr_idx, _subr_bytes
from compiler.slot_map import _collect_symbol_nodes, _is_empty_quote, _offset_slots, _slot_of
from compiler.top_lambda import (
    _collect_kwote_lambda_args,
    _collect_top_lambda_binds,
    _convert_top_lambda_to_defuns,
    _defun_from_lambda,
    _has_immediate_lambda,
    _insert_top_lambda_defuns,
    _is_top_lambda_bind,
    _lambda_real_args,
    _rewrite_top_lambda_binds,
    _tl_kwote_lambdas,
)



def cmd_decompile(source: str, output: str = "") -> str:
    parser_obj = Fas4Parser()
    fas = parser_obj.parse(source)
    disasm = Disassembler(short_subr=use_short_subr(fas.bytecode, fas.nsyms, fas.function_catalog))
    instructions = disasm.disassemble(fas.bytecode, fas.nsyms)
    cfa = ControlFlowAnalyzer(instructions, fas.function_catalog)
    functions = cfa.find_functions()
    gen = LispGenerator(fas)
    result = gen.generate(functions, source)

    output = output or source.replace(".fas", "_decomp.lsp")
    with open(output, "w", encoding="utf-8") as f:
        f.write(result)
    print(f"Decompiled to {output}")
    return output


def cmd_disassemble(source: str, output: str = "") -> str:
    """反汇编 .fas / .zelx → .lasm（字节码指令列表）。"""
    from asm.assembler import disassemble_fas

    tmp_fas = ""
    if source.lower().endswith(".zelx"):
        # zelx → fas → lasm：先用逆向恢复出 fas 再反汇编
        import os
        import tempfile
        from tools.zelx_to_fas import zelx_to_fas

        base = os.path.splitext(os.path.basename(source))[0]
        tmp_fas = os.path.join(tempfile.gettempdir(), f"{base}.fas")
        try:
            zelx_to_fas(source, tmp_fas)
            text = disassemble_fas(tmp_fas)
        finally:
            if os.path.exists(tmp_fas):
                os.unlink(tmp_fas)
    else:
        text = disassemble_fas(source)

    output = output or source.rsplit(".", 1)[0] + ".lasm"
    with open(output, "w", encoding="utf-8") as f:
        f.write(text)
    print(f"Disassembled to {output}")
    return output


def cmd_assemble(source: str, output: str = "") -> str:
    """汇编 .lasm → .fas。"""
    from asm.assembler import assemble_lasm

    with open(source, "rb") as f:
        from core.fas_core import decode_source_text
        text = decode_source_text(f.read())
    output = output or source.replace(".lasm", ".fas")
    assemble_lasm(text, output)
    print(f"Assembled to {output}")
    return output


def cmd_validate(source: str) -> int:
    import pathlib

    ok = validate_file(pathlib.Path(source))
    return 0 if ok else 1


def cmd_analyze(
    source: str,
    format: str = "text",
    output: str = "",
    no_cc: bool = False,
) -> int:
    """源码/FAS 调用图与依赖分析。

    format: text | dot | mermaid | json
    """
    from compiler.dep_analysis import build_from_lsp, build_from_fas
    from compiler.dep_analysis import format_text, format_dot, format_mermaid

    if source.lower().endswith(".fas") or source.lower().endswith(".zelx"):
        graph = build_from_fas(source)
    else:
        if os.path.exists(source):
            from core.fas_core import decode_source_text

            with open(source, "rb") as f:
                source_code = decode_source_text(f.read())
        else:
            source_code = source
        parser_obj = Parser(source_code)
        try:
            program = parser_obj.parse()
        except ParseError as e:
            print(f"Parse error: {e}", file=sys.stderr)
            return 1
        graph = build_from_lsp(program)

    # `--no-cc`：不把 c:*/*error* 显式提升为 root（仍保留顶层表达式 root）。
    if no_cc:
        roots = {r for r in graph["roots"] if r.startswith("c:") or r == "*error*"}
        for node in graph["nodes"]:
            if node["name"] in roots:
                node["root"] = False
        graph["roots"] = sorted(r for r in graph["roots"] if r not in roots)

    if format == "json":
        import json as _json

        text = _json.dumps(graph, indent=2, ensure_ascii=False)
    elif format == "dot":
        text = format_dot(graph)
    elif format == "mermaid":
        text = format_mermaid(graph)
    else:
        text = format_text(graph)

    if output:
        with open(output, "w", encoding="utf-8") as f:
            f.write(text)
    else:
        print(text)
    return 0


def cmd_info(source: str, json_out: bool = False) -> dict:
    """FAS/ZELX 快速概览 — 文件头/段规模/函数目录/符号/字符串，不触发完整反编译。

    实现复用 core/fas_core.parse_fas4（与 tools/fas-analyzer.py 同源），
    .zelx 输入走 tools.zelx_info.parse_zelx 解密载荷。
    """
    from core.fas_core import parse_fas4
    from core.fas_core import parse_resource_stream, build_mvar_tables, build_function_catalog

    if source.lower().endswith(".zelx"):
        from tools.zelx_info import parse_zelx

        z = parse_zelx(source)
        import collections
        import math

        entropy = sum(
            (-v / len(z["payload"])) * math.log2(v / len(z["payload"]))
            for v in collections.Counter(z["payload"]).values()
        )
        info = {
            "file": source,
            "format": "zelx",
            "size": z["size"],
            "zelx": {
                "X": z["X"],
                "Y": z["Y"],
                "Z": z["Z"],
                "sub": list(z["sub"]),
                "payload_size": z["seg2len"],
                "key_len": z["key_len"],
                "payload_entropy": round(entropy, 3),
            },
        }
        if not json_out:
            print(f"file size      : {z['size']}")
            print(f"ZAS header X   : {z['X']}  Y: {z['Y']}  Z(seg1 len): {z['Z']}")
            print(f"seg2 sub-hdr   : [len={z['sub'][0]}][{z['sub'][1]}][{z['sub'][2]}]")
            print(f"payload len    : {z['seg2len']}")
            print(f"key len        : {z['key_len']}")
            print(f"payload entropy: {entropy:.3f}")
        return info

    parsed = parse_fas4(source)
    nsyms = parsed["nsyms"]
    bytecode = parsed["bytecode"]
    seg0_total = len(bytecode)
    seg1_enc = parsed["res_data_encrypted"]
    seg1_dec = parsed["res_data_decrypted"]
    key = parsed["key"]
    res_items = parsed["res_items"]
    trailer = parsed["trailer"]

    # 格式类型：紧凑 stub / 自包含。沿用 fas-analyzer 的启发式。
    fmt = "compact-stub"
    if seg1_dec:
        resource_items, symbols, strings = parse_resource_stream(seg1_dec)
        resource_gvars, function_gvars = build_mvar_tables(seg1_dec, nsyms)
        catalog = build_function_catalog(resource_gvars, function_gvars)
    else:
        resource_items, symbols, strings = [], [], []
        catalog = []

    info = {
        "file": source,
        "size": os.path.getsize(source),
        "format": fmt,
        "nsyms": nsyms,
        "seg0_size": seg0_total,
        "seg1_size": len(seg1_enc),
        "seg1_decrypted_size": len(seg1_dec),
        "items": res_items,
        "key_size": len(key) if key else 0,
        "func_count": len(catalog),
        "catalog": catalog,
        "symbol_count": len(symbols),
        "string_count": len(strings),
        "trailer": trailer,
    }
    if not json_out:
        print(f"=== FAS4 概览 ===")
        print(f"文件      : {source}")
        print(f"大小      : {os.path.getsize(source)} bytes")
        print(f"格式      : {fmt}")
        print(f"nsyms     : {nsyms}")
        print(f"Seg0      : {seg0_total} bytes")
        print(f"Seg1      : {len(seg1_enc)} bytes (encrypted) / {len(seg1_dec)} bytes (decrypted)")
        print(f"items     : {res_items}")
        print(f"XOR key   : {len(key) if key else 0} bytes")
        if trailer:
            print(f"尾部      : {trailer[:60]}")
        if catalog:
            print(f"\n函数目录  : {len(catalog)} 条目")
            for name, off in catalog[:15]:
                print(f"  {name:30s} @ {off}")
            if len(catalog) > 15:
                print(f"  ... ({len(catalog) - 15} more)")
        if symbol_count := info["symbol_count"]:
            print(f"\n符号      : {symbol_count}")
            for s in symbols[:20]:
                print(f"  {s}")
            if symbol_count > 20:
                print(f"  ... ({symbol_count - 20} more)")
        if strings:
            print(f"\n字符串    : {len(strings)}")
            for s in strings[:10]:
                print(f"  {s!r}")
            if len(strings) > 10:
                print(f"  ... ({len(strings) - 10} more)")
    return info


def cmd_link(inputs: list, output: str, verbose: bool = False, encoding: str = "ansi") -> str:
    return link_fas(inputs, output, verbose, encoding=encoding)


def main():
    parser = argparse.ArgumentParser(
        prog="atlispcc",
        description="FAS4 bytecode compiler/decompiler toolchain for AutoLISP-compatible CAD platforms",
    )
    sub = parser.add_subparsers(dest="command", metavar="<command>")

    # compile
    p_compile = sub.add_parser("compile", aliases=["c"], help="Compile .lsp → .fas")
    p_compile.add_argument("source", help="input .lsp file")
    p_compile.add_argument("output", nargs="?", default="", help="output .fas file (optional)")
    p_compile.add_argument(
        "-O",
        type=int,
        default=0,
        choices=[0, 1, 2, 3],
        help="optimization level (0=none, 1=basic, 2=aggressive, 3=extreme)",
    )
    p_compile.add_argument("--analyze", action="store_true", help="show compilation analysis report")
    p_compile.add_argument(
        "--report",
        default="",
        help="write a structured compilation report (JSON) to the given path",
    )
    p_compile.add_argument(
        "--encoding",
        default="ansi",
        help="string/symbol encoding for FAS output "
        "(ansi=system codepage on Windows, default; or utf-8, gbk, cp936, ...)",
    )
    p_compile.add_argument(
        "--no-verify",
        dest="verify",
        action="store_false",
        help="skip post-compile verification (checks for bytecode that could "
        "crash CAD with access violation 0xC0000005)",
    )

    # decompile
    p_decompile = sub.add_parser("decompile", aliases=["d"], help="Decompile .fas → .lsp")
    p_decompile.add_argument("source", help="input .fas file")
    p_decompile.add_argument("output", nargs="?", default="", help="output .lsp file (optional)")

    # info: quick overview without full decompile
    p_info = sub.add_parser("info", help="Quick overview of a .fas/.zelx file (header, segments, function catalog)")
    p_info.add_argument("source", help="input .fas or .zelx file")
    p_info.add_argument("--json", action="store_true", help="print machine-readable JSON instead of text")

    # analyze: call-graph / dependency analysis (.lsp or .fas)
    p_analyze = sub.add_parser("analyze", help="Call graph / dependency analysis of a .lsp or .fas file")
    p_analyze.add_argument("source", help="input .lsp or .fas file")
    p_analyze.add_argument(
        "--format",
        "-f",
        choices=["text", "dot", "mermaid", "json"],
        default="text",
        help="output format (default: text)",
    )
    p_analyze.add_argument("-o", "--output", default="", help="write result to file instead of stdout")
    p_analyze.add_argument("--no-cc", action="store_true", help="do not treat c:* / *error* as entry roots")

    # roundtrip: compile → decompile → validate → compare smoke test
    p_roundtrip = sub.add_parser(
        "roundtrip",
        help="Smoke-test: compile .lsp → FAS → decompile → validate → compare",
    )
    p_roundtrip.add_argument("source", help="input .lsp file")
    p_roundtrip.add_argument(
        "-O",
        "--opt",
        type=int,
        default=0,
        choices=[0, 1, 2, 3],
        help="optimization level for the compile step (default: 0)",
    )
    p_roundtrip.add_argument(
        "--keep",
        action="store_true",
        help="keep intermediate .fas and decompiled .lsp in a temp dir and print their paths",
    )

    # validate
    p_validate = sub.add_parser("validate", aliases=["v"], help="Validate .lsp syntax")
    p_validate.add_argument("source", help="input .lsp file")

    # build zelx: .lsp/.fas → .zelx (ZWCAD)
    p_zelx = sub.add_parser("zelx", help="Build .zelx from .lsp/.fas (ZWCAD)")
    p_zelx.add_argument("source", help="input .lsp or .fas file")
    p_zelx.add_argument("output", nargs="?", default="", help="output .zelx file (optional)")

    # unzelx: .zelx → .fas
    p_unzelx = sub.add_parser("unzelx", help="Recover .fas from .zelx (ZWCAD)")
    p_unzelx.add_argument("source", help="input .zelx file")
    p_unzelx.add_argument("output", nargs="?", default="", help="output .fas file (optional)")

    # disassemble: .fas → .lasm
    p_disasm = sub.add_parser(
        "disasm", aliases=["disassemble"], help="Disassemble .fas/.zelx → .lasm (bytecode instructions)"
    )
    p_disasm.add_argument("source", help="input .fas or .zelx file")
    p_disasm.add_argument("output", nargs="?", default="", help="output .lasm file (optional)")

    # assemble: .lasm → .fas
    p_asm = sub.add_parser("asm", aliases=["assemble"], help="Assemble .lasm → .fas (or .zelx with --zelx)")
    p_asm.add_argument("source", help="input .lasm file")
    p_asm.add_argument("output", nargs="?", default="", help="output file (optional)")
    p_asm.add_argument("--zelx", action="store_true", help="assemble to ZWCAD .zelx")

    # link
    p_link = sub.add_parser("link", help="Link multiple .fas files into one")
    p_link.add_argument("inputs", nargs="+", help="input .fas files (2 or more)")
    p_link.add_argument("-o", "--output", default="", help="output .fas file")
    p_link.add_argument("--verbose", "-v", action="store_true", help="verbose output")
    p_link.add_argument(
        "--encoding",
        default="ansi",
        help="string/symbol encoding for linked FAS output (default: ansi=system codepage)",
    )

    # build-vlx
    p_vlx = sub.add_parser("build-vlx", help="Build VLX container from .fas files")
    p_vlx.add_argument("inputs", nargs="+", help="input .fas files")
    p_vlx.add_argument("-o", "--output", default="", help="output .vlx file")
    p_vlx.add_argument("--export", nargs="*", default=[], help="exported function names for namespace isolation")
    p_vlx.add_argument("--package", default="", help="VLX package/application name")

    # project: compile every :FILES source listed in pkg.lsp
    p_project = sub.add_parser(
        "project",
        help="Compile all Lisp sources listed in a package's pkg.lsp (CI friendly)",
    )
    p_project.add_argument("source", help="pkg.lsp path or package directory")
    p_project.add_argument("-o", "--outdir", default="", help="output directory (default: next to each source)")
    p_project.add_argument(
        "-O",
        "--opt",
        type=int,
        default=0,
        choices=[0, 1, 2, 3],
        help="optimization level (default: 0)",
    )
    p_project.add_argument(
        "--encoding",
        default="ansi",
        help="string/symbol encoding for FAS output (default: ansi=system codepage)",
    )
    p_project.add_argument(
        "--no-verify",
        dest="verify",
        action="store_false",
        help="skip post-compile verification",
    )
    p_project.add_argument("--dry-run", action="store_true", help="list files without compiling")
    p_project.add_argument("--stop-on-error", action="store_true", help="stop at the first failure")
    p_project.add_argument("--json", action="store_true", help="print the report as JSON")
    p_project.add_argument("--report", default="", help="write the JSON report to this path")

    args = parser.parse_args()

    if args.command is None:
        parser.print_help()
        return 0

    if args.command in ("compile", "c"):
        cmd_compile(
            args.source,
            args.output,
            opt_level=args.O,
            show_analysis=args.analyze,
            encoding=args.encoding,
            report_json=args.report,
            verify=args.verify,
        )
        return 0

    if args.command in ("decompile", "d"):
        cmd_decompile(args.source, args.output)
        return 0

    if args.command == "info":
        info = cmd_info(args.source, json_out=args.json)
        if args.json:
            print(json.dumps(info, indent=2, ensure_ascii=False))
        return 0

    if args.command == "analyze":
        return cmd_analyze(args.source, format=args.format, output=args.output, no_cc=args.no_cc)

    if args.command == "roundtrip":
        from compiler.roundtrip import run_roundtrip

        return run_roundtrip(args.source, opt_level=args.opt, keep=args.keep)

    if args.command in ("disasm", "disassemble"):
        cmd_disassemble(args.source, args.output)
        return 0

    if args.command in ("asm", "assemble"):
        if args.zelx:
            from asm.assembler import assemble_lasm_zelx

            with open(args.source, "rb") as f:
                from core.fas_core import decode_source_text
                text = decode_source_text(f.read())
            output = args.output or args.source.replace(".lasm", ".zelx")
            assemble_lasm_zelx(text, output)
            print(f"Assembled to {output}")
        else:
            cmd_assemble(args.source, args.output)
        return 0

    if args.command in ("validate", "v"):
        return cmd_validate(args.source)

    if args.command == "zelx":
        from tools.zelx_build import build_zelx

        output = args.output or args.source.rsplit(".", 1)[0] + ".zelx"
        build_zelx(args.source, output)
        print(f"Built {output}")
        return 0

    if args.command == "unzelx":
        from tools.zelx_to_fas import zelx_to_fas

        output = args.output or args.source.rsplit(".", 1)[0] + ".fas"
        zelx_to_fas(args.source, output)
        print(f"Built {output}")
        return 0

    if args.command == "link":
        if len(args.inputs) < 2:
            print("Error: need at least 2 input .fas files to link", file=sys.stderr)
            return 1
        output = args.output
        if not output:
            base = args.inputs[-1].rsplit(".", 1)[0]
            output = f"{base}_linked.fas"
        cmd_link(args.inputs, output, args.verbose, args.encoding)
        return 0

    if args.command == "build-vlx":
        output = args.output
        if not output:
            base = args.inputs[-1].rsplit(".", 1)[0]
            output = f"{base}.vlx"
        result = build_vlx(args.inputs, output, exports=args.export, package_name=args.package)
        print(f"Built {result}")
        return 0

    if args.command == "project":
        from compiler.project_cmd import run_project

        return run_project(
            args.source,
            outdir=args.outdir,
            opt_level=args.opt,
            encoding=args.encoding,
            verify=args.verify,
            dry_run=args.dry_run,
            stop_on_error=args.stop_on_error,
            json_out=args.json,
            report_path=args.report,
        )

    parser.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main() or 0)
