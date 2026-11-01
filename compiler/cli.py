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
from compiler.info_cmd import cmd_info
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


def cmd_assemble(source: str, output: str = "", date=None, salt=None) -> str:
    """汇编 .lasm → .fas。"""
    from asm.assembler import assemble_lasm

    with open(source, "rb") as f:
        from core.fas_core import decode_source_text
        text = decode_source_text(f.read())
    output = output or source.replace(".lasm", ".fas")
    assemble_lasm(text, output, date=date, salt=salt)
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


def cmd_link(inputs: list, output: str, verbose: bool = False, encoding: str = "ansi",
             date=None, salt=None) -> str:
    return link_fas(inputs, output, verbose, encoding=encoding, date=date, salt=salt)


def _validate_build_options(parser_obj, args) -> None:
    """校验 ``--date`` / ``--salt``，非法值走 argparse 的干净报错（退出码 2）。"""
    date = getattr(args, "date", "")
    salt = getattr(args, "salt", "")
    if not date and not salt:
        return
    from compiler.fas_writer import normalize_date, parse_salt_spec

    if salt:
        try:
            parse_salt_spec(salt)
        except ValueError as exc:
            parser_obj.error(str(exc))
    if date:
        try:
            normalize_date(date)
        except ValueError as exc:
            parser_obj.error(str(exc))


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
    p_compile.add_argument(
        "--date",
        default="",
        help="pin the FAS trailer build stamp (M/D/YY) for reproducible builds "
        "(default: today)",
    )
    p_compile.add_argument(
        "--salt",
        default="",
        help="container salt: 'deterministic' (fixed 01..08), 'seed:<n>', "
        "'hex:<bytes>', or a plain integer seed; default: Autodesk-style random",
    )

    # decompile
    p_decompile = sub.add_parser("decompile", aliases=["d"], help="Decompile .fas → .lsp")
    p_decompile.add_argument("source", help="input .fas file")
    p_decompile.add_argument("output", nargs="?", default="", help="output .lsp file (optional)")

    # info: quick overview without full decompile
    p_info = sub.add_parser("info", help="Quick overview of a .fas/.zelx file (header, segments, function catalog)")
    p_info.add_argument("source", help="input .fas / .zelx / .vlx file")
    p_info.add_argument("--json", action="store_true", help="print machine-readable JSON instead of text")
    p_info.add_argument(
        "--encoding", default="ansi",
        help="encoding for VLX member names / LOAD spec (default: ansi=system codepage)",
    )

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
    p_asm.add_argument(
        "--date", default="", help="pin the FAS build stamp (M/D/YY) for reproducible builds"
    )
    p_asm.add_argument(
        "--salt", default="",
        help="container salt: 'deterministic', 'seed:<n>', 'hex:<bytes>', or an integer seed",
    )

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
    p_link.add_argument(
        "--date", default="", help="pin the FAS build stamp (M/D/YY) for reproducible builds"
    )
    p_link.add_argument(
        "--salt", default="",
        help="container salt: 'deterministic', 'seed:<n>', 'hex:<bytes>', or an integer seed",
    )

    # build-vlx
    p_vlx = sub.add_parser("build-vlx", help="Build a VRTLIB-1 .vlx from .fas/.dcl members or a .prv")
    p_vlx.add_argument("inputs", nargs="*", help="input .fas/.dcl/.txt members")
    p_vlx.add_argument("--prv", default="", help="Visual LISP application file (.prv) instead of inputs")
    p_vlx.add_argument("-o", "--output", default="", help="output .vlx file")
    p_vlx.add_argument("--export", nargs="*", default=[], help="functions exported to the host namespace (vl-doc-export)")
    p_vlx.add_argument(
        "--encoding",
        default="ansi",
        help="encoding for the LOAD spec text and member names (default: ansi=system codepage)",
    )
    p_vlx.add_argument(
        "--no-protected", dest="protected", action="store_false",
        help="write (:protected) instead of (:protected . T) in the LOAD spec",
    )
    p_vlx.add_argument(
        "--no-active-x", dest="active_x", action="store_false",
        help="write (:active-x) instead of (:active-x . T) in the LOAD spec",
    )
    p_vlx.add_argument(
        "--no-separate-namespace", dest="separate_namespace", action="store_false",
        help="write (:separate-namespace) instead of the dotted T form",
    )
    p_vlx.add_argument(
        "--workdir", default="", help="directory for compiled intermediates (default: temp dir)"
    )
    p_vlx.add_argument(
        "--date", default="", help="pin the FAS build stamp (M/D/YY) for reproducible builds"
    )
    p_vlx.add_argument(
        "--salt", default="",
        help="container salt: 'deterministic', 'seed:<n>', 'hex:<bytes>', or an integer seed",
    )

    # unpack-vlx: extract VRTLIB-1 members
    p_unvlx = sub.add_parser("unpack-vlx", help="Extract the members of a VRTLIB-1 .vlx")
    p_unvlx.add_argument("source", help="input .vlx file")
    p_unvlx.add_argument("-o", "--outdir", default="", help="output directory (default: next to the .vlx)")
    p_unvlx.add_argument("--encoding", default="ansi", help="encoding used for member names (default: ansi)")
    p_unvlx.add_argument("--list", action="store_true", help="list members without writing files")
    p_unvlx.add_argument(
        "--no-verify", dest="verify", action="store_false",
        help="skip the structural check (LOAD record / alignment / duplicate names)",
    )
    p_unvlx.add_argument(
        "--stub", default="",
        help="write a Lisp loader ((load \"NAME\") ...) to this path",
    )

    # project: compile every :FILES source listed in pkg.lsp (or a VLISP .prj)
    p_project = sub.add_parser(
        "project",
        help="Compile all sources of a pkg.lsp package or a Visual LISP .prj project",
    )
    p_project.add_argument("source", help="pkg.lsp / package directory / .prj project file")
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
    p_project.add_argument(
        "--date", default="", help="pin the FAS build stamp (M/D/YY) for reproducible builds"
    )
    p_project.add_argument(
        "--salt", default="",
        help="container salt: 'deterministic', 'seed:<n>', 'hex:<bytes>', or an integer seed",
    )

    args = parser.parse_args()

    if args.command is None:
        parser.print_help()
        return 0

    if args.command in ("compile", "c"):
        _validate_build_options(p_compile, args)
        cmd_compile(
            args.source,
            args.output,
            opt_level=args.O,
            show_analysis=args.analyze,
            encoding=args.encoding,
            report_json=args.report,
            verify=args.verify,
            date=args.date or None,
            salt=args.salt or None,
        )
        return 0

    if args.command in ("decompile", "d"):
        cmd_decompile(args.source, args.output)
        return 0

    if args.command == "info":
        info = cmd_info(args.source, json_out=args.json, encoding=args.encoding)
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
            cmd_assemble(
                args.source,
                args.output,
                date=args.date or None,
                salt=args.salt or None,
            )
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
        _validate_build_options(p_link, args)
        cmd_link(args.inputs, output, args.verbose, args.encoding,
                 date=args.date or None, salt=args.salt or None)
        return 0

    if args.command == "build-vlx":
        _validate_build_options(p_vlx, args)
        if args.prv:
            from compiler.prv import run_prv

            return run_prv(
                args.prv,
                output=args.output,
                workdir=args.workdir,
                encoding=args.encoding,
                date=args.date or None,
                salt=args.salt or None,
            )
        if not args.inputs:
            p_vlx.error("either input files or --prv is required")
        output = args.output
        if not output:
            base = args.inputs[-1].rsplit(".", 1)[0]
            output = f"{base}.vlx"
        result = build_vlx(
            args.inputs,
            output,
            exports=args.export,
            protected=args.protected,
            active_x=args.active_x,
            separate_namespace=args.separate_namespace,
            encoding=args.encoding,
            date=args.date or None,
            salt=args.salt or None,
        )
        print(f"Built {result}")
        return 0

    if args.command == "unpack-vlx":
        from compiler.vlx_builder import make_load_stub, read_vlx, unpack_vlx, verify_vlx

        archive = read_vlx(args.source)
        if args.verify:
            issues = verify_vlx(archive)
            if issues:
                for issue in issues:
                    print(f"verify: {issue}", file=sys.stderr)
                print("VLX verification FAILED", file=sys.stderr)
                return 1
        if args.stub:
            stub = make_load_stub(archive, args.encoding)
            with open(args.stub, "w", encoding="utf-8") as handle:
                handle.write(stub)
            print(f"Wrote load stub {args.stub}")
        if args.list:
            for index, member in enumerate(archive.members()):
                print(
                    f"{index}: {member.display_name(args.encoding)}  tag={member.tag}  "
                    f"size={len(member.payload)}"
                )
            return 0
        outdir = args.outdir or os.path.join(
            os.path.dirname(os.path.abspath(args.source)),
            os.path.splitext(os.path.basename(args.source))[0] + '_members',
        )
        written = unpack_vlx(args.source, outdir, encoding=args.encoding)
        for path in written:
            print(f"Extracted {path}")
        return 0

    if args.command == "project":
        from compiler.project_cmd import run_project

        _validate_build_options(p_project, args)
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
            date=args.date or None,
            salt=args.salt or None,
        )

    parser.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main() or 0)
