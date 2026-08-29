"""cmd_compile pipeline (moved from cli.py)."""

import json
import os
import sys
from typing import Optional

from compiler.analyzer import analyze
from compiler.ast_nodes import (
    Call,
    Cond,
    CondDefunBind,
    Defun,
    Defpackage,
    ForeachNode,
    IfNode,
    InPackage,
    LambdaNode,
    ListExpr,
    Progn,
    QuotedExpr,
    RepeatNode,
    Setq,
    Symbol,
    WhileNode,
)
from compiler.codegen import BytecodeBuffer, CodeGenerator
from compiler.fas_writer import FasWriter
from compiler.lowering import _flatten_top_level_forms, _hoist_conditional_defuns
from compiler.module_code import _build_cad_module_code
from compiler.opt import optimize
from compiler.patch import _patch_usubr_idx
from compiler.parser import ParseError, Parser
from compiler.resource_builder import (
    ResourceBuilder,
    _real_fmt,
    build_command_module_code,
    build_mixed_command_module_code,
    build_module_code,
    count_resource_items,
    count_resource_records,
)
from compiler.slot_map import _collect_symbol_nodes, _offset_slots
from compiler.symbol_table import SymbolTable
from compiler.top_lambda import (
    _collect_kwote_lambda_args,
    _collect_top_lambda_binds,
    _defun_from_lambda,
    _has_immediate_lambda,
    _insert_top_lambda_defuns,
    _is_top_lambda_bind,
    _lambda_real_args,
    _rewrite_top_lambda_binds,
    _tl_kwote_lambdas,
)

ENCODE_POP = bytes([0x0A])

def cmd_compile(
    source: str,
    output: str = "",
    opt_level: int = 0,
    show_analysis: bool = False,
    encoding: str = "ansi",
    report_json: str = "",
    verify: bool = True,
) -> str:
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
        sys.exit(1)

    # 顶层 `(progn ...)`（@lisp 包整体包裹模式）展开后再提取 defun/顶层表达式
    program.forms = _flatten_top_level_forms(program.forms)
    # 条件/嵌套 defun（`(if c (defun f () ...))`）：先按 CAD 方式把顶层 if 内的
    # defun 提升为独立函数（无条件编译，if 只保留非 defun 表达式）。函数体内
    # 嵌套 defun（`(defun f () (defun g () ...))`）**不再降级**为 setq lambda——
    # CAD 原生内嵌 DEFUN（n1-n6 实测 `JUMP; DEFUN g; ...; END_DEFUN;
    # PUSH_G <g-obj>; SETQ_G g`），由 codegen `_emit_nested_defun` 发射。
    program.forms = _hoist_conditional_defuns(program.forms)
    # 顶层 `(setq X (lambda ...))`：CAD 编译为可调用 SUBR。
    # - 纯顶层文件（无 defun）：走 CAD `-lambda-` 机制（seg0 紧凑 stub +
    #   DEFCODE 注册 + 模块代码 ``PUSH_G <sym>; PUSH_G <-lambda-槽>;
    #   FUNC_REF set``）。
    # - 混合文件（含 defun）：提升为同名 defun（@lisp_u 实测 CAD `@::fasext`/
    #   `@::vlx`/`@::acadver` 为可调用 SUBR，`(type @::fasext)` → SUBR）。
    #   此前改写成 kwote 但混合文件无 seg0 `-lambda-` 生成/DEFCODE 注册，
    #   模块代码 `FUNC kwote` 无定义 → CAD 加载报 `函数错误: (LAMBDA ...)`
    #   /访问冲突，见 KNOWN_ISSUES。
    _defuns_now = [f for f in program.forms if isinstance(f, Defun)]
    top_lambda_binds = _collect_top_lambda_binds(program.forms)
    # 记录顶层 `(set/setq 'sym (lambda ...))` 的目标符号名（混合文件转为 defun
    # 后用于 func_offsets 以 `-lambda-` 键登记，CAD DEFCODE 尾注册为 `-lambda-`）。
    _top_lambda_names = {s for s, _ in top_lambda_binds}
    if top_lambda_binds:
        program.forms = _rewrite_top_lambda_binds(program.forms)
        if _defuns_now:
            program.forms = _insert_top_lambda_defuns(program.forms, top_lambda_binds)
    # 多 `(function (lambda ...))`（>1）走 CAD kwote 原生路径：每个 kwote 编译为
    # 独立 `-lambda-` 内嵌 DEFUN（`-lambda-#N` 目录键 + DEFCODE 注册，见
    # codegen._emit_nested_lambda / resource_builder）。`_lower_multi_kwote` 仅作为
    # 后备保留（单 kwote 文件不受影响，多 kwote 走原生）。
    # program.forms = _lower_multi_kwote(program.forms)
    # `(let ...)` 先降级为 lambda-apply。`((lambda ...) args)` 立即调用保留
    # ListExpr（head=LambdaNode），codegen 走 CAD「内嵌 -lambda- DEFUN + EVAL」
    # 模式（dcl/permission/audit/user-manager/config-sync/file 实测 `EVAL argc, 7`）。
    # `(let ...)` 由 codegen 原生编译（CAD `LET + EVAL 0` 模式，不降级 lambda）。
    # program.forms = _lower_let(program.forms)

    package_table = parser_obj.packages

    need_stats = show_analysis or bool(report_json)
    stats: Optional[dict] = None
    stats2: Optional[dict] = None

    if need_stats:
        stats = analyze(program)
        if show_analysis:
            print("=== Compilation Analysis ===")
            print(f'  Functions:               {stats["functions"]}')
            print(f'  Top-level forms:         {stats["top_level_forms"]}')
            print(f'  Total instructions:      {stats["total_instructions"]}')
            print(f'  Constants (estimate):    {stats["constants_estimate"]}')
            print(f'  Symbol table entries:    {stats["symbol_table_entries"]}')
            print(f'  Function offsets:        {stats["function_offsets"]}')
            print(f'  Locals (total):          {stats["locals"]}')
            print(f'  Tail-recursive:          {stats["tail_recursive_functions"]}')
            print(f'  External/builtin calls:  {len(stats["builtin_calls"])}')
            for fd in stats["functions_detail"]:
                tr = " [tail-recursive]" if fd["tail_recursive"] else ""
            print(
                f'    {fd["name"]}: {fd["instructions"]} instr, '
                f'{fd["args"]} args, {fd["locals"]} locals, '
                f'calls {fd["calls"]}{tr}'
            )
            print()

    if opt_level:
        program = optimize(program, level=opt_level)
        if need_stats:
            assert stats is not None
            stats2 = analyze(program)
            assert stats2 is not None
            if show_analysis:
                print(f"=== After O{opt_level} Optimization ===")
                print(f'  Functions:          {stats2["functions"]} (was {stats["functions"]})')
                print(f'  Instructions:       {stats2["total_instructions"]} (was {stats["total_instructions"]})')
                print(f'  Tail-recursive:     {stats2["tail_recursive_functions"]}')
                print()

    symtab = SymbolTable(package_table=package_table)
    defun_forms = [f for f in program.forms if isinstance(f, Defun)]
    # 纯 &rest（min=0）：CAD 实测不收集 rest（b4=01 需至少一个必填参数）
    for _defun in defun_forms:
        if _defun.rest and not _defun.args and not _defun.optional:
            print(
                f"Warning: function '{_defun.name}' uses bare &rest (min args = 0); "
                f"CAD does not collect rest args for min=0 — consider adding "
                f"a required param, e.g. (defun {_defun.name} (x &rest {_defun.rest}))",
                file=sys.stderr,
            )
    from compiler.cad_symbols import derive_symbol_names, is_const_entry

    for sym in derive_symbol_names(program):
        if not defun_forms and top_lambda_binds and sym == "kwote":
            # 纯顶层含顶层 `(set/setq 'sym (lambda ...))`（CAD `-lambda-` 机制）：
            # 收集器对 kwote 标记误收 `kwote` 符号（CAD 无此槽，顶层 lambda
            # 不经 kwote 调用）。跳过；`-lambda-` 由 seg0 阶段经 top_lambda_slots
            # 注册，不进 symtab。
            # 仅纯顶层文件跳过：混合文件（含 defun，atlisp_u）的 kwote lambda
            # （顶层 `(function (lambda ...))` 调用）**需要** kwote 符号槽——
            # 跳过 → 模块注册缺 kwote 0x56 块 → build_mvar_tables fg 缺 KWOTE →
            # `_patch_usubr_idx` fallback 错槽 → seg0 嵌套函数 FUNC kwote 调用
            # 指向字符串 → CAD 加载报 "函数错误: \"\\\""。
            continue
        if is_const_entry(sym):
            symtab.add_constant(sym[1])
        elif isinstance(sym, str) and sym.startswith('__real_') and sym.endswith('__'):
            _rv = float(sym[len('__real_'):-len('__')])
            if f'__real_{_rv}__' in symtab.name_to_idx:
                # CAD 实数跨区重复注册：模块区与函数体区各自独立 gvar 槽
                # （atlisp_u `(* 0.707 (getvar "viewsize") 0.1)` 的 0.1 在模块
                # 顶层常量与函数体 @::dbclicked 各注册一次，fg 表两处都有）。
                # 首次 add_real 登记 name_to_idx，二次（重复）直接追加重复
                # REAL 槽——否则 `add_real` 去重复用模块槽 → fg 缺函数体
                # REAL、nsyms 少 1、后续符号槽位错位。
                symtab.add_real(_rv, force=True)
            else:
                symtab.add_real(_rv)
        elif sym.startswith('"') and sym.endswith('"'):
            _sv = sym[1:-1]
            if f"__str_{_sv}__" in symtab.name_to_idx:
                # CAD 字符串跨区重复注册：模块区与函数体区各自独立 gvar 槽
                # （platform.lsp `(setq @::*locale* "chs")` 的 "chs" 在模块
                # cond 与函数体各注册一次，fg 表两处都有）。首次 add_string
                # 登记 name_to_idx，二次（重复）直接追加重复 STRING 槽。
                symtab.add_string(_sv, force=True)
            else:
                symtab.add_string(_sv)
        elif sym in symtab.name_to_idx:
            # CAD stub：允许符号重复（递归/跨函数引用产生重复槽）
            symtab.add_force(sym)
        else:
            # 大小写变体引用（C:@H 调用 `@::showCopyRight`，defun 名
            # `@::showCopyright`）：模块注册已登记 `@::showCopyright`（name_to_idx
            # 大小写敏感键），函数体调用变体 `@::showCopyRight` 查不到精确键。
            # `get_or_add` 的大小写不敏感回退会复用模块槽 → fg 表缺函数体重复
            # 槽（CAD fg[128] 有 @::SHOWCOPYRIGHT；atlisp_u 实测 @::SHOWCOPYRIGHT
            # rg[446] + fg[128] 双槽）。须按 CAD stub 语义 `add_force` 追加重复槽。
            _ci_hit = any(
                not k.startswith("__")
                and not SymbolTable._is_case_sensitive(k)
                and k.upper() == sym.upper()
                for k in symtab.name_to_idx
            )
            if _ci_hit:
                symtab.add_force(sym)
            else:
                symtab.get_or_add(sym)

    # 顶层表达式符号（defun 之外）：CAD 把它们的符号并入模块注册段。
    # InPackage/Defpackage 也编译进模块代码（InPackage `PUSH_VALUE :@; FUNC_REF
    # in-package`，Defpackage `PUSH_VALUE :C; (:use ...); (:export ...);
    # USUBR 3, DEFPACKAGE`，CAD 实测），故保留在 other_forms 中。
    other_forms = [f for f in program.forms if not isinstance(f, Defun)]
    # 顶层 form 数（CAD seg1 头 items 公式用），区别于符号数 top_level_count。
    top_form_count = len(other_forms)
    from compiler.ast_nodes import Symbol as _Sym
    from compiler.ast_nodes import String as _StrNode

    _top_syms = []
    for form in other_forms:
        for _n in _collect_symbol_nodes(form):
            if isinstance(_n, _Sym) and _n.name not in _top_syms:
                _top_syms.append(_n.name)
            elif isinstance(_n, _StrNode) and _n.value not in _top_syms:
                _top_syms.append(_n.value)
    # 顶层符号在 entries 中的槽索引（字符串 key 特殊）
    _top_slots = []
    for s in _top_syms:
        if s in symtab.name_to_idx:
            _top_slots.append(symtab.name_to_idx[s])
        elif f"__str_{s}__" in symtab.name_to_idx:
            _top_slots.append(symtab.name_to_idx[f"__str_{s}__"])
    # CAD 模块注册区宽 = 函数名数 + 顶层表达式符号数。由收集器 _register_module
    # 实际注册数推导（module_reg_count = n_funcs + top_level_count）。
    # 不能用 `max(顶层符号槽)+1-n_funcs`：顶层表达式若引用**函数体**符号
    # （高槽位）会严重高估（atlisp_u 实测 3036 vs 实际 342），导致模块代码
    # 函数注册 `PUSH_G b` 槽超出 gvar 表、CAD 不执行模块代码。
    from compiler.cad_symbols import module_reg_count as _mrc
    from compiler.cad_symbols import module_reg_func_count as _mrfc

    if defun_forms:
        # 模块注册区 = n_funcs + top_level_count。由收集器 _register_module
        # 实际注册数推导。不能用 `max(顶层符号槽)+1-n_funcs`：顶层表达式若
        # 引用**函数体**符号（高槽位）会严重高估（atlisp_u 实测 3036 vs
        # 实际 342），导致模块代码函数注册 `PUSH_G b` 槽超出 gvar 表、
        # CAD 不执行模块代码。
        top_level_count = max(0, _mrc(program) - len(defun_forms))
    else:
        # 纯顶层文件：无函数体符号污染，`max(顶层槽)+1` 与 golden 一致
        # （setqa/setcmp/p01 实测）。含顶层 `(set/setq 'sym (lambda ...))`
        # 的文件（setq-lambda.lsp）用模块注册段符号数（`_mrc`）——`max(_top_slots)`
        # 会被 `-lambda-` 第二区体符号膨胀，`-lambda-` 槽位偏移。CAD 的
        # `-lambda-` 槽 = 模块注册段符号数 + 3（fasext）、+2（vlx）。
        if top_lambda_binds:
            top_level_count = max(0, _mrc(program))
        elif _top_slots:
            top_level_count = max(_top_slots) + 1
        else:
            top_level_count = 0

    codegen_nsyms = len(symtab.entries) - len(defun_forms) - top_level_count + 1
    codegen = CodeGenerator(symtab, stub_format=True, defined_funcs=[f.name for f in defun_forms], nsyms=codegen_nsyms)

    func_offsets = {}

    # CAD：顶层表达式（defun 之外的 setq/set 等）编译进 seg1 模块代码，
    # seg0 只含 defun 函数。
    #
    # CAD 模块代码规则（逆向）：
    #   - 模块代码引用 gvar 槽（= 符号槽 + 1）
    #   - 顶层 setq → `PUSH_G <值槽+1>; DUP; SETQ_G <变量槽+1>; POP(非最后)`
    #   - 顶部 `PUSH_G <符号总数+1>; POP` 占位
    #   - 无 defun 时无函数注册尾，以 END_DEFUN 结束
    top_level_bc = BytecodeBuffer()
    codegen._module_mode = True
    codegen._module_code_ctx = True
    for form in other_forms:
        if isinstance(form, (InPackage, Defpackage)):
            # `(in-package :@)`/`(defpackage ...)` 由 _build_cad_module_code 单独
            # 发射（in-package `PUSH_VALUE :@; FUNC_REF in-package`、defpackage
            # `PUSH_VALUE :C; (:use ...); (:export ...); USUBR 3, DEFPACKAGE`），
            # 此处跳过占位生成。
            continue
        # 顶层 if 内提升的条件 defun（`CondDefunBind` 标记）：由
        # _build_cad_module_code 的 `_stmt_bytes` 特判发射（绑定留 if 守卫内），
        # 此处跳过（marker 无法经 codegen 编译；top_level_code 仅无 other_forms
        # 时被使用，panel.lsp 混合文件不走此代码）。
        from compiler.ast_nodes import CondDefunBind as _CDB_skip, Progn as _CDB_skip_prog

        def _has_cond_bind(node):
            if isinstance(node, _CDB_skip):
                return True
            if isinstance(node, _CDB_skip_prog):
                return any(_has_cond_bind(f) for f in node.forms)
            if isinstance(node, IfNode):
                return any(_has_cond_bind(p) for p in (node.cond, node.then, node.else_expr) if p is not None)
            return False

        if _has_cond_bind(form):
            continue
        # 顶层 `(set/setq 'sym (lambda ...))`（纯顶层文件）：由
        # _build_cad_module_code 按 top_lambda_slots 特判发射 `-lambda-` 绑定，
        # 这里跳过（避免 codegen _emit_kwote 注册多余 `-LAMBDA-` 槽）。
        if top_lambda_binds:
            from compiler.ast_nodes import LambdaNode as _LN

            _is_tl = False
            _tl_names = {s for s, _ in top_lambda_binds}
            if isinstance(form, Call) and form.name == "set" and len(form.args) == 2:
                _t0 = form.args[0]
                _v1 = form.args[1]
                _is_tl = (
                    isinstance(_t0, QuotedExpr) and isinstance(_t0.expr, Symbol)
                    and _t0.expr.name in _tl_names
                    and (isinstance(_v1, _LN) or (isinstance(_v1, QuotedExpr) and isinstance(_v1.expr, _LN)))
                )
            elif isinstance(form, Setq):
                for _t, _v in form.pairs:
                    if isinstance(_t, Symbol) and _t.name in _tl_names and (
                        isinstance(_v, _LN) or (isinstance(_v, QuotedExpr) and isinstance(_v.expr, _LN))
                    ):
                        _is_tl = True
                        break
            if _is_tl:
                continue
        codegen._emit_expr(top_level_bc, form)
        if isinstance(form, Setq):
            top_level_bc.emit(ENCODE_POP)
    codegen._module_mode = False
    top_level_bc.resolve()
    top_level_code = bytes(top_level_bc.data)

    all_bytecode = BytecodeBuffer()
    _top_lam_count = 0
    _top_lambda_key_names: dict = {}
    _top_lambda_offsets: dict = {}
    _tl_kwote_args: dict = {}
    _prev_emitted = False
    _tl_kwote_offsets: list = []
    _tl_kwote_count = 0
    _tl_kwote_pos: dict = {}
    _nfuncs_seen = 0
    for form in program.forms:
        if not isinstance(form, Defun):
            # 顶层 setq-lambda 绑定（`(set/setq 'X (function (lambda ...)))`，
            # `_rewrite_top_lambda_binds` 改写后为 kwote）由 top_lambda_binds
            # 路径处理，这里跳过（避免重复发射 `-lambda-` DEFUN）。
            if top_lambda_binds and _is_top_lambda_bind(form, _top_lambda_names):
                continue
            for _lam in _tl_kwote_lambdas(form):
                if _prev_emitted:
                    all_bytecode.emit(bytes([0x16]))
                _fdef = _defun_from_lambda("-lambda-", _lam)
                _fb, _ = codegen.generate_function(_fdef)
                _off = len(all_bytecode.data)
                # 唯一键（高序号避免与 nested_list 的 `-lambda-#N` 冲突），
                # 在源码位置写入 func_offsets（CAD 主 DEFCODE 区源码序交错）。
                _tl_kwote_count += 1
                _tl_key = f"-lambda-#TL{_tl_kwote_count}"
                func_offsets[_tl_key] = _off
                # 顶层 kwote lambda 的 DEFUN 参数登记（`_patch_usubr_idx` 按
                # seg0 offset 解析参数槽）：DEFUN 头后 argc 个 PUSH_G 参数绑定
                # 须映射到 fg 槽（setup `x` → PUSH_G 120），否则落 fallback 错槽。
                _top_lambda_offsets[_off] = _tl_key
                _top_lambda_key_names[_tl_key] = _tl_key
                _tl_kwote_args[_tl_key] = _lambda_real_args(_lam)
                _tl_kwote_pos[_tl_key] = _nfuncs_seen
                all_bytecode.emit(_fb)
                _prev_emitted = True
            continue
        if _prev_emitted:
            all_bytecode.emit(bytes([0x16]))
        offset = len(all_bytecode.data)
        func_bytecode, _ = codegen.generate_function(form)
        _nfuncs_seen += 1
        from compiler.cad_symbols import normalize_vla_name

        if form.name in _top_lambda_names:
            # 混合文件顶层 setq-lambda（已提升为 defun）：CAD 在 DEFCODE 尾
            # 注册为 `-lambda-`（platform.lsp 实测两处 `-lambda-`，offset 大的
            # 先 DEFCODE）。func_offsets 键用 `-lambda-`，使 resource_builder
            # 按 `-lambda-` 编码 DEFCODE（`_is_lambda_key`）。顺序按 seg0 offset
            # 自然排序（源码序 = 定义序），与 CAD 逆序 DEFCODE 一致。
            _lkey = f"-lambda-{'' if _top_lam_count == 0 else '#' + str(_top_lam_count + 1)}"
            func_offsets[_lkey] = offset
            _top_lambda_key_names[_lkey] = form.name
            _top_lambda_offsets[offset] = form.name
            _top_lam_count += 1
        else:
            func_offsets[normalize_vla_name(form.name)] = offset
        all_bytecode.emit(func_bytecode)
        _prev_emitted = True

    # 顶层 `(set/setq 'sym (lambda ...))`（纯顶层文件）：CAD 把内嵌
    # `-lambda-` DEFUN 放 seg0（完整紧凑 stub：`14 <argc><argc><argc> 00` +
    # GET_LOCAL + INIT_ARGS + 体 + CLEAR_ARGS + END_DEFUN，函数间 `16` 分隔），
    # 由 DEFCODE 注册为可调用 SUBR。模块代码用 setq 协议绑定
    # `JUMP 0; PUSH_G <-lambda-槽>; DUP; SETQ_G <sym>`。这里生成 stub 进
    # seg0，登记 `-lambda-` 槽供模块代码引用；有 defun 的混合文件（platform）
    # CAD 用引用数据。
    top_lambda_slots: dict = {}
    if top_lambda_binds and not defun_forms:
        for _ti, (_sym, _lam) in enumerate(top_lambda_binds):
            # 纯顶层 `-lambda-` 是完整 compact stub 函数（CAD 实测 seg0：
            # `14 <argc><argc><argc> 00` + GET_LOCAL_WIDE + INIT_ARGS + 体 +
            # CLEAR_ARGS + END_DEFUN，与普通 defun 一致），由 DEFCODE 注册为
            # 可调用 SUBR。复用 generate_function 生成（_defun_from_lambda 把
            # LambdaNode 转 Defun），避免手动拼 stub 缺 GET_LOCAL/INIT_ARGS/
            # CLEAR_ARGS/END。
            _fdef = _defun_from_lambda(_sym, _lam)
            _fb, _ = codegen.generate_function(_fdef)
            _off = len(all_bytecode.data)
            _key = f"-lambda-#{_ti + 1}" if _ti else "-lambda-"
            func_offsets[_key] = _off
            all_bytecode.emit(_fb)
            # CAD 纯顶层 `-lambda-` 函数间以 END_DEFUN(`16`) 分隔（同 defun，
            # setq-lambda.lsp CAD golden 实测第一个 `-lambda-` 后 `16`）；最后
            # 一个 `-lambda-` 无 END（以 CLEAR_ARGS 结束）。
            if _ti < len(top_lambda_binds) - 1:
                all_bytecode.emit(bytes([0x16]))
            # `-lambda-` 槽 = 顶层符号数 + 2（setq-lambda.lsp golden 实测：
            # 模块代码 `PUSH_G 29`（@::fasext）、`PUSH_G 28`（@::vlx）——gvar 槽 =
            # 符号槽 + 1，符号槽 = top_level_count + 2 - _ti。CAD 的 GVARINIT
            # (top_level_count+2, N) 注册这些超表运行时槽。不能用全部
            # symtab.entries（第二区 `-lambda-` 体符号会膨胀）。多 lambda 逆序
            # 递减。不进 symtab（CAD 无 `-lambda-` 普通符号槽，仅 DEFCODE
            # 区小写注册）。
            _lam_slot = top_level_count + 2 - _ti
            top_lambda_slots[_sym] = _lam_slot
    # 混合文件（platform）：`-lambda-` 运行时槽 = `_reg` 的 b 槽 - 1（模块代码
    # setq-lambda 绑定 `PUSH_G <-lambda->` 复用该函数的 `_reg` b 槽：b =
    # 2*n_funcs+1 + top_level_count - i，`_lam_slot = b - 1`。platform 实测
    # @::fasext i=2 → PUSH_G 69、@::vlx i=3 → PUSH_G 68）。
    elif top_lambda_binds and defun_forms:
        _tl_names_set = set(s for s, _ in top_lambda_binds)
        _tl_index = {
            f.name: idx
            for idx, f in enumerate(defun_forms)
            if f.name in _tl_names_set
        }
        for _sym, _lam in top_lambda_binds:
            _i = _tl_index.get(_sym)
            if _i is None:
                continue
            _lam_slot = 2 * len(defun_forms) + top_level_count - _i
            top_lambda_slots[_sym] = _lam_slot

    # 内嵌 `(function (lambda ...))` / `((lambda ...) args)` DEFUN（kwote/
    # 立即应用机制）：偏移相对所在函数字节码缓冲，需转换为 seg0 绝对偏移。
    # 每个内嵌 DEFUN 用独立 `-lambda-` 目录键（`-lambda-`、`-lambda-#2`、…，
    # CAD 实测每个嵌套 lambda 独立槽 + DEFCODE，逆序弹出分配末尾槽）。
    # 这些键仅用于函数目录（func-ranges）与 DEFCODE 注册，不参与模块注册。
    nested_ends = {}
    nested_list = []
    # codegen 内嵌 `-lambda-` DEFUN 的**发射序**参数列表（`_emit_nested_lambda`
    # 记录 `(start, end, args, lam_idx)`；发射序 = seg0 DEFUN 出现序，与源码收集
    # 序 `_collect_kwote_lambda_args` 在复杂 cond（safe-eval）下不一致——参数绑定
    # 须按发射序解析，否则 cur_args 错配。
    # **`-lambda-` 槽（lam_order）**：含**立即 lambda**（`((lambda ...) args)`
    # 即时发射 DEFUN+EVAL）的函数按**源码序逆序**（CAD safe-eval fn/ok-tail
    # 实测：源码序 [fn, ok-tail, clause, b] → 逆序 [b, clause, ok-tail, fn] →
    # _li fn=3/ok-tail=2 → 槽 fn=62/ok-tail=63）；纯 kwote 函数（log，延迟发射）
    # 用 symtab 顺序即正确。symtab `-lambda-` 顺序 = codegen 调用序，须按
    # `_collect_kwote_lambda_args` 源码序匹配重排。
    nested_lambda_args: dict = {}
    nested_lambda_order: dict = {}
    _src_lam_args = {}
    _has_imm = {}
    for _df in defun_forms:
        _dfn = normalize_vla_name(_df.name)
        _src_lam_args[_dfn.upper()] = [list(la) for la in _collect_kwote_lambda_args(_df)]
        _has_imm[_dfn.upper()] = _has_immediate_lambda(_df)
    # 内嵌 `-lambda-` DEFCODE 顺序（nested_list → lam_offsets 键顺序）：
    # - 含立即 lambda（`((lambda ...) args)`）且单函数 ≥2 的函数按**源码序**
    #   （safe-eval fn/ok-tail/clause/b 实测），其余函数按 offset 逆序，
    #   func_offsets 源码序拼接、不全局排序（`nested_lambda_order` 置位）。
    # - 纯 kwote 函数（无立即 lambda）：DEFCODE = **全局发射序逆序**
    #   （`_fnl_raw` = codegen 内嵌 `-lambda-` 发射序）。@::panel-calc-layout
    #   3 个 kwote lambda 发射序 [inner@88, outer@69, bt-man@180] → DEFCODE
    #   [bt-man@180, outer@69, inner@88] = [2961, 2850, 2869] CAD 实测。log 的
    #   兄弟 lambda 发射序 = offset 序，发射序逆序 == offset 逆序，二者一致；
    #   嵌套 kwote lambda（inner 嵌 outer 体）offset 序 ≠ 发射序，须用发射序。
    _lambda_batches = []
    _has_imm_any = False
    for name, off in list(func_offsets.items()):
        _fnl_raw = list(codegen._func_nested_lambdas.get(name, []))
        if not _fnl_raw:
            continue
        _fnl = sorted(_fnl_raw)  # seg0 序（参数绑定按 seg0 DEFUN 序解析）
        nested_lambda_args[name.upper()] = [list(a) for _, _, a, _ in _fnl]
        _ordered = None
        if _has_imm.get(name.upper()) and len(_fnl_raw) >= 2:
            _total = len(_fnl_raw)
            _src_pos = {}
            for _pos, _sa in enumerate(_src_lam_args.get(name.upper(), [])):
                for _t in _fnl_raw:
                    if list(_t[2]) == _sa:
                        _src_pos[_t[3]] = _pos
                        break
            if len(_src_pos) == _total:
                _has_imm_any = True
                for _lam_idx, _pos in _src_pos.items():
                    nested_lambda_order[_lam_idx] = _total - 1 - _pos
                # nested_list 按**源码序正序**（DEFCODE item 顺序 = 源码序）。
                _by_src = {}
                for _sa in _src_lam_args.get(name.upper(), []):
                    for _t in _fnl_raw:
                        if list(_t[2]) == _sa:
                            _by_src[_sa[0]] = _t
                            break
                _ordered = [_by_src[list(sa)[0]] for sa in _src_lam_args.get(name.upper(), [])]
        _lambda_batches.append((off, _fnl_raw, _ordered))
    if _has_imm_any:
        # 含立即 lambda 的文件：func_offsets 源码序拼接，逐函数
        # `_ordered`（立即 → 源码序；纯 kwote → offset 逆序）。
        for off, _fnl_raw, _ordered in _lambda_batches:
            _b = _ordered if _ordered is not None else sorted(_fnl_raw, reverse=True)
            for rel_start, rel_end, _, _ in _b:
                nested_list.append((off + rel_start, off + rel_end))
    else:
        # 纯 kwote 文件：全局发射序逆序（函数逆序 + 各函数发射逆序）。
        for off, _fnl_raw, _ordered in reversed(_lambda_batches):
            for rel_start, rel_end, _, _ in reversed(_fnl_raw):
                nested_list.append((off + rel_start, off + rel_end))
    for i, (n_start, n_end) in enumerate(nested_list):
        # **`-lambda-#N` 键冲突**（atlisp_u 实测）：顶层 setq-lambda 已用
        # `-lambda-`/`-lambda-#N` 键（emit 循环 line 394），嵌套 kwote lambda
        # 若也从 `-lambda-#1` 起编 → 顶层 `-lambda-#2`（@::vlx）被嵌套 `-lambda-#2`
        # 覆盖，顶层 lambda 丢失（CAD 目录 3 个 `-lambda-` 缺 3）。用 `_base =
        # max 现有 #N` 避让，嵌套键从 base+1 起（CAD 顶层 setq-lambda 与其后
        # kwote 嵌套 lambda 均独立 DEFCODE，键不冲突）。
        _base = 0
        for _k in func_offsets:
            if str(_k) == "-lambda-":
                _base = max(_base, 0)
            elif str(_k).startswith("-lambda-#"):
                _tail = str(_k)[len("-lambda-#"):]
                if _tail.isdigit():
                    _base = max(_base, int(_tail))
        _nkey = f"-lambda-#{_base + i + 1}"
        if _base + i == 0 and "-lambda-" not in func_offsets:
            _nkey = "-lambda-"
        func_offsets[_nkey] = n_start
        nested_ends[n_start] = n_end

    # 函数体内嵌套 `(defun inner ...)`（CAD 原生内嵌 DEFUN）：登记进 func_offsets
    # 使 resource_builder 为嵌套函数发射 DEFCODE（函数目录 + func-obj 槽）。
    # 偏移相对所在函数字节码缓冲，需转换为 seg0 绝对偏移。嵌套 defun 名用真实
    # 名字（非 `-lambda-`）。
    # **func_offsets 键序**：顶层函数在前（源码序），嵌套 defun 按 seg0 offset
    # **降序**（n5 实测 func_offsets = [OUTER, INNER, MID]：嵌套按 offset 降序
    # [inner@20, mid@10] → 逆序 DEFCODE 发射 [mid, inner, outer]，与 codegen
    # 内嵌发射序（mid→inner）一致，func-obj 占位槽才能对齐最终槽）。
    # 嵌套 defun 可再含嵌套（n5 mid→inner）：用 worklist 传递收集。
    _fnd_seen = set()
    _fnd_work = list(func_offsets.items())
    _nested_defun_names: dict = {}
    while _fnd_work:
        _name, _off = _fnd_work.pop(0)
        _fnd_raw = list(codegen._func_nested_defuns.get(_name, []))
        for rel_start, rel_end, nd_name, _nd_args, _sym_idx, _fo_idx in sorted(_fnd_raw):
            n_start = _off + rel_start
            n_end = _off + rel_end
            _nkey = normalize_vla_name(nd_name)
            if _nkey in func_offsets:
                # 嵌套 defun 与已注册函数同名（atlisp_u @::panel-dialog-core 内嵌
                # `*error*` 与顶层 `*error*` 冲突）。func_offsets 键需唯一：
                # 追加 `#dupN` 后缀；DEFCODE 目录名仍用原名（nested_defun_names
                # 映射回 `*ERROR*`，CAD 顶层与嵌套 `*ERROR*` 同名共存）。
                _nkey = f"{_nkey}#dup"
                _dup = 1
                while _nkey in func_offsets:
                    _dup += 1
                    _nkey = f"{normalize_vla_name(nd_name)}#dup{_dup}"
            _nested_defun_names[_nkey] = normalize_vla_name(nd_name)
            func_offsets[_nkey] = n_start
            nested_ends[n_start] = n_end
            _fnd_seen.add((_nkey, n_start))
            _fnd_work.append((_nkey, n_start))
    if _fnd_seen:
        # **func_offsets 键序（嵌套 defun）**：整体移到顶层函数之后，按
        # **FUNCOBJ 添加序（codegen 发射序）逆序**排列——CAD 前置 DEFCODE
        # 发射序 = func_offsets 键序 = 逆 codegen 发射序。n5（codegen 发射序
        # inner→mid，逆序 = [mid, inner] → 前置 DEFCODE MID 先 INNER 后）；
        # version（@::pkg-deps-tree 先于 @::pkg-reverse-deps-tree 发射 →
        # 逆序 = [rev, deps] → REV 先 DEPS 后）。不能用 offset 降序（n5 与
        # version 方向相反）。
        _top_keys = [k for k in func_offsets if func_offsets[k] not in dict(_fnd_seen).values()]
        _fo_add_order = [
            e[1] for e in symtab.entries
            if isinstance(e, tuple) and len(e) == 2 and e[0] == "FUNCOBJ"
        ]
        _fo_by_name = {}
        for _name, _off in func_offsets.items():
            for _fr in codegen._func_nested_defuns.get(_name, []):
                _fo_by_name.setdefault(_fr[2], _fr[5])
        # 逆 FUNCOBJ 添加序的嵌套键（只取 _fnd_seen 中出现的名字）。
        _nested_order = [
            n for n in reversed(_fo_add_order)
            if any(k == n for k, _ in _fnd_seen)
        ]
        for _nk in list(dict(_fnd_seen)):
            if _nk not in _nested_order:
                _nested_order.append(_nk)
        func_offsets = {k: func_offsets[k] for k in _top_keys}
        for _nk in _nested_order:
            for _ok, _oo in _fnd_seen:
                if _ok == _nk:
                    func_offsets[_nk] = _oo
                    break
        # **func-obj 槽重映射**：codegen 的 FUNCOBJ 占位槽（按发射序分配）→
        # 资源流 func-obj 槽。前置 DEFCODE（嵌套 defun + `-lambda-`）按 seg0
        # offset **降序**发射（父-子链父在前），先发射者被 GVARINIT 弹出分配
        # 更高槽——func-obj 槽 = `nsyms - n_pre + pos`（pos = 降序排名，
        # string-utils s2la 在 [lambda, lambda, s2la] pos=2）。
        _n_funcobj = sum(1 for _e in symtab.entries if isinstance(_e, tuple) and _e and _e[0] == "FUNCOBJ")
        _nsyms_now = len(symtab.entries) - (len(defun_forms) + top_level_count) + 1
        _pre_all = [
            (off, k) for k, off in func_offsets.items()
            if off in nested_ends
        ]
        _pre_all.sort(key=lambda x: x[0], reverse=True)
        _has_real_nested = any(
            not (str(k) == "-lambda-" or str(k).startswith("-lambda-#")) for _o, k in _pre_all
        )
        if not _has_real_nested:
            # 仅 `-lambda-`：func_offsets 键序
            _key_order = {k: i for i, (k, _o) in enumerate(
                (k, off) for k, off in func_offsets.items() if off in nested_ends
            )}
            _pre_all.sort(key=lambda x: _key_order.get(x[1], 10**9))
        else:
            # 父-子链修正（同 resource_builder，含 `-lambda-` 父——嵌套 kwote
            # lambda panel @::panel-calc-layout 外层@2850 含内层@2869 须父在前，
            # 否则 func-obj 槽错位，PUSH_G 交换）。
            for _pi, (_poff, _pname) in enumerate(list(_pre_all)):
                if (str(_pname) == "-lambda-" or str(_pname).startswith("-lambda-#")) and not nested_ends.get(_poff):
                    continue
                _children = [
                    j for j in range(len(_pre_all))
                    if j != _pi and _pre_all[j][0] > _poff
                    and nested_ends.get(_poff) and _poff < _pre_all[j][0] < nested_ends[_poff]
                ]
                if not _children:
                    continue
                _first = min(_children)
                if _first < _pi:
                    _item = _pre_all.pop(_pi)
                    _pre_all.insert(_first, _item)
        _fo_pos = {k: i for i, (_off, k) in enumerate(_pre_all)}
        _n_pre = len(_pre_all)
        _fo_base = _nsyms_now - _n_pre
        funcobj_map = {}
        for _nk, _no in _fnd_seen:
            _foi = _fo_by_name.get(_nk)
            if _foi is not None and _nk in _fo_pos:
                funcobj_map[_foi] = _fo_base + _fo_pos[_nk]
        # **`-lambda-` 槽（lambda_slot_map）**：与 func-obj 槽同规则，按 `_pre_all`
        # 位置编址（slot = `_fo_base + pos`）。嵌套 defun func-obj 与 `-lambda-`
        # 共享高位槽区，顺序由 `_pre_all`（offset 降序 + 父-子链修正）决定：
        # string-utils `_pre_all=[lambda@1740, lambda@816, s2la@638]` → s2la
        # func-obj=93、lambda=92/91；version `[rec, rev-rec, lambda...]` →
        # func-obj=120/119、lambda=121/122/123。旧公式 `nsyms-1-_li` 未计入
        # func-obj 槽 → string-utils 的 lambda 与 s2la 冲突（93/92 vs CAD 92/91，
        # seg0 3 处 PUSH_G 差 1）。
        _pre_pos = {_off: _i for _i, (_off, _k) in enumerate(_pre_all)}
        lambda_slot_map: dict = {}
        for _fname, _fnl_raw2 in codegen._func_nested_lambdas.items():
            _fstart = func_offsets.get(_fname)
            if _fstart is None:
                continue
            for _rel_start, _rel_end, _la_args, _la_idx in _fnl_raw2:
                _abs = _fstart + _rel_start
                if _abs in _pre_pos:
                    lambda_slot_map[_la_idx] = _fo_base + _pre_pos[_abs]
    else:
        funcobj_map = {}
        lambda_slot_map = {}

    for name, offset in func_offsets.items():
        # `-lambda-`/`-lambda-#N`（内嵌 DEFUN）不进符号表（仅 DEFCODE 区注册，
        # 顶层 lambda 的 `-lambda-` 槽由 top_lambda_slots 计算）。其余函数名
        # 注册符号槽。**嵌套 defun 同名 `#dup` 键**（`*error*#dup`）同样不进
        # 符号表——嵌套 defun 仅经前置 DEFCODE 区注册（resource_builder
        # nested_defun_names 映射回原名），注册进 symtab 会多一个 `*ERROR*#DUP`
        # 符号槽（atlisp_u 资源流 `5b *ERROR*#DUP 00` → CAD 无此槽、fg/seg0 错位）。
        if isinstance(name, str) and (
            name == "-lambda-" or name.startswith("-lambda-#") or "#dup" in name
        ):
            continue
        from compiler.cad_symbols import normalize_vla_name

        symtab.add_func_ref(normalize_vla_name(name), offset)

    all_bytecode.resolve()
    seg0 = bytes(all_bytecode.data)

    # 模块代码：含顶层表达式时用 CAD 风格完整模块代码；否则固定函数注册尾。
    # c: 命令函数：CAD 在模块注册段插入 vl-ACAD-defun 符号并生成命令模块代码。
    # vl-ACAD-defun 仅在模块注册段（resource_gvars）注册，不进符号表（不参与
    # 函数符号槽编址），故 seg0 的 PUSH_VALUE 索引保持不变。
    n_cmds = 1 if any(getattr(f, "is_command", False) or str(f.name).startswith("c:") for f in defun_forms) else 0
    resource = ResourceBuilder(symtab, encoding=encoding)
    # 模块注册函数数 = 模块尾块 defun 数（CAD 只把模块代码引用的尾块函数名
    # 注册进模块注册段；atlisp_u 48，其余 416 个库函数名经函数体符号区注册）。
    _mr_func_count = _mrfc(program)
    # 顶层 kwote lambda（setup `(if @::*uris* (mapcar (function (lambda ...))
    # ...))` 的 `-lambda-#TL` DEFUN）：作为 func-obj 在 DEFCODE 区注册，占用
    # 模块 rg 空间一个额外槽。nsyms（len(entries)-module_reg_count+1）与 b 槽
    # 公式须计入（CAD 实测 nsyms=166、b0=37 = 2*14+1+7+1）。模块注册段
    # (module_entries) 不含它（resource_builder 已排除），两者差 1。
    _tl_lam_count = sum(1 for k in func_offsets if str(k).startswith("-lambda-#TL"))
    # 顶层 kwote lambda 不作为 symtab `-lambda-` 条目（module-mode `_emit_kwote`
    # 不再 get_or_add），entries 计数不含它；module_reg_count 不加 _tl_lam_count
    #（否则 nsyms 少 1）。b 槽公式 / gv_var_pos 仍单独计入 func-obj。
    module_reg_count = len(defun_forms) + top_level_count
    # 顶层 kwote lambda 的 func-obj 槽（模块代码 PUSH_G 引用，DEFCODE 区注册
    # 的模块 rg 槽）：CAD setup 实测 func-obj=29 = 2*n_funcs+1+tlc+_tl_lam_count
    # - n_funcs_before（lambda 源码位置前的 defun 数）。
    _tl_funcobj_slots = {}
    for _tlk, _pos in _tl_kwote_pos.items():
        _tl_funcobj_slots[_tlk] = (
            2 * len(defun_forms) + 1 + top_level_count + _tl_lam_count - _pos
        )
    # 纯顶层含顶层 `(set/setq 'sym (lambda ...))` 时，收集第二区符号
    # （lambda 体符号 + 参数，CAD DEFCODE 区前置注册，fg 表用）。顺序：源码
    # 逆序（@::vlx 在前、@::fasext 在后），各 lambda 体符号 + 参数。与
    # cad_symbols 的 3b 块收集顺序一致。
    _top_lambda_body_syms = None
    if top_lambda_binds:
        from compiler.cad_symbols import CadSymbolCollector, _SeenList

        _syms = []
        _lam_seen = set()  # 跨 lambda 去重（strcat 出现在两个 lambda 体只注册一次）
        for _sym, _lam in reversed(top_lambda_binds):
            from compiler.ast_nodes import Call as _TLCall

            _lam_col = _SeenList()
            for _be in _lam.body:
                CadSymbolCollector()._collect_byteorder(_be, _lam_col, set())
            _fwd = [n for n, _ in _lam_col if n != "__kwote_end__" and n != "kwote"]
            # 最后调用名 = 最后一个 body form 的值（setq 值/末表达式函数名）。
            # setq-lambda vlx/fasext 尾 form 得 strcat；net/wget 尾 form
            # `outfile`（Symbol）→ 无尾调用（null 是中间 if 条件，不剔除）。
            _tc = CadSymbolCollector()._lam_tail_value(_lam.body[-1] if _lam.body else None)
            if _tc is not None:
                _fwd = [n for n in _fwd if n != _tc]
            # 真参数 = `/` 之前；`/` 后的局部变量照常注册为体符号。
            _lam_params = _lam.args
            if "/" in _lam_params:
                _lam_params = _lam_params[:_lam_params.index("/")]
            for _n in reversed(_fwd):
                if isinstance(_n, str) and _n in _lam_params:
                    continue
                if isinstance(_n, str) and _n in _lam_seen:
                    continue
                _lam_seen.add(_n)
                _syms.append(_n)
            # `/ 局部变量`：注入 `_al-bind-alist` 助手 + locals 常量
            # （net/wget CAD 实测 `_al-bind-alist` 在 body 后、参数前）。
            _lam_locals = []
            if "/" in _lam.args:
                _lam_locals = _lam.args[_lam.args.index("/") + 1 :]
            if _lam_locals:
                if "_al-bind-alist" not in _lam_seen:
                    _lam_seen.add("_al-bind-alist")
                    _syms.append("_al-bind-alist")
                _lc = tuple(("SYMBOL", l) for l in _lam_locals)
                if _lc not in _lam_seen:
                    _lam_seen.add(_lc)
                    _syms.append(("__const__", ("LIST", _lc)))
            for _a in reversed(_lam_params):
                if _a not in _lam_seen:
                    _lam_seen.add(_a)
                    _syms.append(_a)
            if _tc is not None and _tc not in _lam_seen:
                _lam_seen.add(_tc)
                _syms.append(_tc)
        _top_lambda_body_syms = _syms
    fas_nsyms = len(symtab.entries) - module_reg_count + 1
    # 纯顶层文件含顶层 `-lambda-`：CAD nsyms = fg 表长度 = 1 + 第二区符号数
    # （setq-lambda.lsp golden nsyms=12 = 1 + 11 个体符号/参数；bootstrap 单
    # lambda 时 = 1 + 1 = 2）。不能再用 `1 + len(top_lambda_binds)`（=3），
    # 否则参数绑定 PUSH_G 的 `gvar_slot(arg)-1` 越界错槽。
    if top_lambda_binds and not defun_forms and _top_lambda_body_syms:
        fas_nsyms = 1 + len(_top_lambda_body_syms)
    _pre_nsyms = fas_nsyms
    if other_forms:
        # 顶层语句在源码中位于最后一个 defun 之后（如 `(set '_ @::_)`、
        # p04 的 `(setq *codepage* ...)` 与 `(if ...)`）时，排到函数注册尾
        # 之后（mix2 实测：`(setq x 10)` 在 defun b 后）。可能多个 post-form。
        from compiler.ast_nodes import Defun as _Defun
        from compiler.ast_nodes import Defpackage as _Defpackage
        from compiler.ast_nodes import InPackage as _InPackage
        from compiler.ast_nodes import Call as _Call

        _last_overall = program.forms[-1] if program.forms else None
        _top_after_defun = _last_overall is not None and not isinstance(
            _last_overall, (_Defun, _Defpackage, _InPackage)
        )
        _last_defun_pos = -1
        _first_defun_pos = -1
        for _i, _f in enumerate(program.forms):
            if isinstance(_f, _Defun):
                if _first_defun_pos < 0:
                    _first_defun_pos = _i
                _last_defun_pos = _i
        # 首个 defun 之前的顶层语句数（模块全局初始化，CAD 在其后立即注册
        # 第一个函数，i18n/p04 实测）。InPackage/Defpackage 均已并入
        # other_forms（模块代码发射调用），计入 globals 组，使其排在函数注册
        # JUMP 之前（CAD base-function/platform-api/command 实测 use-package/
        # in-package/defpackage 均在函数注册前）。
        _n_globals = (
            sum(1 for _f in program.forms[:_first_defun_pos] if not isinstance(_f, _Defun))
            if _first_defun_pos >= 0
            else len(other_forms)
        )
        # 统计最后一个 defun 之后、且非 defun/defpackage 的顶层 form 数。
        # other_forms 与 program.forms 同序（仅过滤 defun/defpackage），
        # 故末尾 n 个 other_forms 即为 post-form。
        _n_post_forms = (
            sum(
                1
                for _f in program.forms[_last_defun_pos + 1 :]
                if not isinstance(_f, (_Defun, _Defpackage, _InPackage))
            )
            if _last_defun_pos >= 0
            else 0
        )
        # START `_reg` 函数数 = globals 之后、首个 mid 顶层语句之前的连续 defun
        # 数（CAD i18n 实测 @::codepage2lang 在 SETQ[0]（模块全局）后立即注册、
        # 在 SETQ[2]（mid 语句）之前；log.lsp 前导 in-package/use-package 跳过
        # 后 log-level/log-level-name 同样 START 注册）。globals（首个 defun
        # 之前的顶层 setq 等）**跳过不 break**——CAD 把 globals 后的函数注册放
        # 在 mid 语句之前。纯函数文件（command.lsp，无 mid 顶层语句）循环走完
        # 所有 defun 后 `_saw_top_stmt=False` → n_pre 归 0（全部 TAIL 注册）。
        _n_pre = 0
        _first_defun_seen = False
        _saw_top_stmt = False
        for _f in program.forms:
            if isinstance(_f, _Defun):
                _first_defun_seen = True
                _n_pre += 1
            elif isinstance(_f, (_Defpackage, _InPackage)) or (
                isinstance(_f, _Call)
                and str(_f.name).lower() in ("use-package", "defpackage")
            ):
                continue
            else:
                if _first_defun_seen:
                    _saw_top_stmt = True
                    break
                # globals（首个 defun 之前的顶层语句）：跳过，START 注册照常
                continue
        if not _first_defun_seen or not _saw_top_stmt:
            _n_pre = 0
        # 每个 defun 之后的 mid 顶层 form 数（仅统计最后一个 defun 之前）。
        # 交错（cl-functions 别名 set）时按此把 mid_forms 分配给对应函数。
        # 提升的顶层 setq-lambda defun（`_top_lambda_names`，platform @::fasext/
        # @::vlx）不占 mid 槽——其后的 mid 语句（`(set 'fasext ...)`、@::vlx
        # 绑定）归前一个真实 defun（`_emit_mid_for` 从 TAIL 循环对 skip 函数
        # continue，分给 -lambda- 槽会丢失 → 模块代码缺 mid 语句）。
        _mid_counts = []
        _cur_fn = None
        for _i, _f in enumerate(program.forms):
            if isinstance(_f, _Defun):
                if getattr(_f, "name", None) in _top_lambda_names:
                    continue
                _mid_counts.append(0)
                _cur_fn = len(_mid_counts) - 1
            elif _cur_fn is not None:
                # InPackage 即使位于最后一个 defun 之后也计入 mid（`_n_post_forms`
                # 已排除 InPackage，post 不含它，故它必在 mid_forms 中且须被
                # `_emit_mid_for` 发射——合并文件第二个 in-package 实测 CAD 发射
                # `PUSH_VALUE :@; USUBR(1, IN-PACKAGE)`，旧 `< _last_defun_pos`
                # 条件把它排除 → 模块代码丢语句、seg1 错位）。use-package/
                # defpackage（Call）/Defpackage 同样被 CAD 发射（`_stmt_bytes`
                # Defpackage 分支发射 `PUSH_VALUE :C; ...; USUBR 3, DEFPACKAGE`，
                # merged_8 init/sequence `(defpackage :theme ...)` 实测在
                # defmacro 注册后发射），计入 mid——否则模块代码丢语句、seg1
                # 错位。
                if isinstance(_f, _InPackage) or isinstance(_f, _Defpackage) or (
                    isinstance(_f, _Call)
                    and str(_f.name).lower() in ("use-package", "defpackage")
                ):
                    _mid_counts[_cur_fn] += 1
                elif _i < _last_defun_pos:
                    _mid_counts[_cur_fn] += 1
        module_code = _build_cad_module_code(
            top_level_code,
            symtab,
            other_forms,
            n_funcs=len(defun_forms),
            top_level_count=top_level_count,
            top_after_defun=_top_after_defun,
            func_names=[f.name for f in defun_forms],
            n_post_forms=_n_post_forms,
            n_globals=_n_globals,
            top_lambda_slots=top_lambda_slots,
            n_pre=_n_pre,
            skip_funcs=_top_lambda_names,
            n_cmds=n_cmds,
            mid_counts=tuple(_mid_counts),
            _tl_lam_count=_tl_lam_count,
            tl_funcobj_slot=_tl_funcobj_slots.get("-lambda-#TL1") if _tl_funcobj_slots else None,
        )
    elif n_cmds:
        # 纯命令文件（全部函数都是命令，无顶层表达式，t14_command）走
        # build_command_module_code（全命令 vl-ACAD-defun 注册）；混合命令文件
        # （config/migrate `C:@PROFILE` + 普通函数）仅命令函数用 vl-ACAD-defun
        # 注册，普通函数用 plain 模式。
        _fn_names = [f.name for f in defun_forms]
        if all(str(n).lower().startswith("c:") for n in _fn_names):
            module_code = build_command_module_code(len(defun_forms))
        else:
            _first_cmd_slot = None
            for _fn in _fn_names:
                if str(_fn).lower().startswith("c:"):
                    _first_cmd_slot = symtab.name_to_idx.get(_fn)
                    break
            # vl-ACAD-defun 的 rg 槽 = 源码首个命令 symtab 槽 + 1（vl 符号占用
            # 其后一槽；config/migrate C:@PROFILE symtab 3 → USUBR 操作数 4）。
            _vl_slot = (_first_cmd_slot + 1) if _first_cmd_slot is not None else 1
            module_code = build_mixed_command_module_code(
                len(defun_forms), vl_idx=_vl_slot, func_names=_fn_names,
                symtab=symtab, first_cmd_slot=_first_cmd_slot,
            )
    else:
        module_code = build_module_code(len(defun_forms), nsyms=_pre_nsyms)

    # 修正 USUBR/参数槽索引：CAD 用 `gvar 槽 - 1`（gvar 表由资源段 GVARINIT 建立）。
    def _all_params(f):
        return f.args + f.optional + ([f.rest] if f.rest else [])

    # func_args 顺序须与 seg0 DEFUN 顺序一致：顶层 defun 参数 + 各函数内嵌
    # kwote `-lambda-` 参数（紧随所在函数之后，i18n-cad 实测）。
    # 参数槽修正采用按名解析（params_by_name / lambda_args_by_func），
    # 不再依赖扁平列表顺序对齐（@lisp_u 大文件 iter 会错位）。
    all_func_args = []
    params_by_name: dict = {}
    lambda_args_by_func: dict = {}
    for _defun in defun_forms:
        _fn = normalize_vla_name(_defun.name)
        _pa = _all_params(_defun)
        all_func_args.append(_pa)
        params_by_name[_fn.upper()] = _pa
        _las = [list(la) for la in _collect_kwote_lambda_args(_defun)]
        lambda_args_by_func[_fn.upper()] = _las
        for la in _las:
            all_func_args.append(la)
    # 混合文件顶层 setq-lambda 以 `-lambda-` 键登记 func_offsets（DEFCODE 尾
    # 注册为 `-lambda-`）：参数修正按原函数名解析（params_by_name 用原名键）。
    for _lkey, _oname in _top_lambda_key_names.items():
        if _lkey in _tl_kwote_args:
            # 顶层 kwote lambda（setup `(if @::*uris* (mapcar (function (lambda
            # (x) ...)) ...))` 的 `-lambda-#TL`）：参数 = lambda 真参数。
            params_by_name[_lkey.upper()] = _tl_kwote_args[_lkey]
        else:
            params_by_name[_lkey.upper()] = params_by_name.get(normalize_vla_name(_oname).upper())

    # 第一轮：先用未 patch 的 seg0 建 seg1 以获取 gvar 表。
    # commands 标志：纯命令文件（无顶层表达式，走 build_command_module_code）
    # 与 commands+顶层混合模式均需启用——混合文件 CAD 在模块注册段插入
    # `56 vl-ACAD-defun 00 00` 块（large_synthetic CAD 实测），且 GVARINIT
    # st_init 计入 `+commands`。
    _rb_commands = n_cmds
    seg1 = resource.build(
        func_offsets,
        module_code=module_code,
        total_size=len(seg0) + 1,
        stub_format=True,
        top_level_count=top_level_count,
        commands=_rb_commands,
        nested_ends=nested_ends,
        top_lambda_body_syms=_top_lambda_body_syms,
        module_func_count=_mr_func_count,
        module_reg_count=module_reg_count,
        nested_defun_names=_nested_defun_names,
    )
    # commands + 顶层混合模式：模块注册把函数名逆序置前、顶层符号在后，
    # 模块代码符号引用（USUBR/PUSH_G）的 `symtab_idx+1` 不再等于实际 gvar 槽，
    # 顶层函数调用会引用错误槽位（atlisp_u 实测 @::poll-wxid 应为 114 而非
    # 248）。用第一轮 seg1 重建 gvar 表，重映射符号引用后二次生成模块代码。
    # 凡含顶层表达式（defun+顶层混合或纯顶层）均需重映射——symtab_idx+1 只在
    # 无顶层表达式时等于实际 gvar 槽（@lisp_u 无 c: 命令，n_cmds=0，此前被
    # `n_cmds and other_forms` 跳过导致 in-package/函数槽错位，2026-08-14）。
    if other_forms:
        # 模块代码符号引用须用资源 gvar 表（table0/rg）的索引——CAD 实测
        # 模块代码 `USUBR(0, 1036)` → rg[1036]=VL-LOAD-COM，操作数 = rg 索引。
        # build_module_gvar_map 的"模块注册段记录序"与此不一致（@lisp_u 实测
        # VL-LOAD-COM 模块注册位 1450 vs rg[1029]），会导致模块代码调用错槽 →
        # CAD 加载报"参数太少"。函数体用 fg（table1），模块代码用 rg（table0），
        # 两表独立（2026-08-14 对拍确认）。
        gvar_map = None
        real_map = None
        try:
            from core.fas_core import build_mvar_tables as _bmt

            _rg, _fg = _bmt(seg1, fas_nsyms)
            gvar_map = {}
            # 先按 symtab 序建立自然映射：模块符号的 gvar 槽 =
            # symtab_idx + 1 + n_cmds（模块注册顺序 = symtab 顺序时）。仅当
            # rg 槽确实持有该符号时采用——重复符号（cl-functions `=` 三槽
            # @[50,51,52]，模块代码引用 52 = symtab idx 51 + 1）若取首槽 50，
            # `_offset_slots` 会把正确的 PV52 重映射成 PV50（pass1 模块代码
            # 与 CAD 逐字节一致，gvar_map 首槽破坏之）。
            string_map = {}
            for _i in range(len(symtab.entries)):
                _t, _v = symtab.entries[_i]
                if _t not in ("SYMBOL", "STRING"):
                    continue
                _rk = str(_v).upper() if _t == "SYMBOL" else str(_v)
                _natural = _i + 1 + n_cmds
                if 0 <= _natural < len(_rg):
                    _rv = _rg[_natural]
                    if isinstance(_rv, tuple) and len(_rv) == 2 and _rv[0] in ("SYMBOL", "STRING"):
                        _rv_key = str(_rv[1]).upper() if _rv[0] == "SYMBOL" else str(_rv[1])
                        if _rv_key == _rk:
                            gvar_map[_rk] = _natural
                            if _t == "STRING":
                                string_map[_rk] = _natural
            # 补充：模块注册顺序不一致（atlisp_u 函数名逆序）时按 rg 表修正。
            # string_map：STRING 专属 gvar 槽——SYMBOL 与 STRING 同名时
            # （panel `C:%` = 函数名 SYMBOL rg[14] + 字符串 "C:%" rg[7]）gvar_map
            # 被 SYMBOL 覆盖，模块代码对字符串的 PUSH_G 须用 STRING 槽（rg[7]，
            # CAD 实测）。仅当 SYMBOL 槽与 STRING 槽共存时才区分。
            for _idx, _v in enumerate(_rg):
                if isinstance(_v, tuple) and len(_v) == 2 and _v[0] in ("SYMBOL", "STRING"):
                    _key = str(_v[1]).upper() if _v[0] == "SYMBOL" else str(_v[1])
                    if _v[0] == "SYMBOL":
                        _prev = gvar_map.get(_key)
                        if _prev is None or not (
                            isinstance(_prev, int) and 0 <= _prev < len(_rg)
                            and isinstance(_rg[_prev], tuple) and _rg[_prev][0] == "SYMBOL"
                        ):
                            gvar_map[_key] = _idx
                    else:
                        gvar_map.setdefault(_key, _idx)
                        string_map.setdefault(_key, _idx)
            # 实数常量：模块代码顶层 setq 的 REAL 值按值匹配 **rg 表**（table0，
            # 模块代码 GVARINIT）的 REAL 槽——CAD 模块代码对 REAL 常量用
            # `PUSH_G <rg REAL 槽>`（merged 文件 constants.lsp `(setq
            # @::*seconds-per-day* 86400.0)` CAD 实测 `09 1b 00` = rg[27]），
            # 而非内联 PUSH_REAL。fg 表（函数体区）REAL 槽**不**适用模块代码
            #（@lisp_u 顶层 `(setq @::*seconds-per-day* 86400.0)` 实测 rg 有槽、
            # 模块代码 PUSH_G 引用它；旧实现按 fg 匹配 → 找不到 → 内联
            # PUSH_REAL → merged_2 seg1 差异 6 字节）。
            real_map = {}
            for _idx, _v in enumerate(_rg):
                if isinstance(_v, tuple) and len(_v) == 2 and _v[0] == "REAL":
                    real_map.setdefault(_real_fmt(float(_v[1])), _idx)
            if not gvar_map:
                gvar_map = None
        except Exception:
            gvar_map = None
        if gvar_map:
            # rg 未覆盖的符号（常量、函数体符号等）按 symtab_idx+1 编址回退。
            module_code = _build_cad_module_code(
                top_level_code,
                symtab,
                other_forms,
                n_funcs=len(defun_forms),
                top_level_count=top_level_count,
                top_after_defun=_top_after_defun,
                func_names=[f.name for f in defun_forms],
                n_post_forms=_n_post_forms,
                n_globals=_n_globals,
                gvar_map=gvar_map,
                top_lambda_slots=top_lambda_slots,
                real_map=real_map,
                string_map=string_map if gvar_map else None,
                n_pre=_n_pre,
                skip_funcs=_top_lambda_names,
                n_cmds=n_cmds,
                mid_counts=tuple(_mid_counts),
                _tl_lam_count=_tl_lam_count,
                tl_funcobj_slot=_tl_funcobj_slots.get("-lambda-#TL1") if _tl_funcobj_slots else None,
            )
    seg0 = _patch_usubr_idx(seg0, seg1, symtab, fas_nsyms, all_func_args,
                            codegen_nsyms=codegen_nsyms,
                            params_by_name=params_by_name,
                            lambda_args_by_func=lambda_args_by_func,
                            nested_lambda_args=nested_lambda_args,
                            nested_lambda_order=nested_lambda_order,
                            has_top_forms=bool(other_forms),
                            n_real_funcs=len(defun_forms),
                            top_lambda_args=[_lambda_real_args(la) for _, la in top_lambda_binds]
                            if top_lambda_binds and not defun_forms else None,
                            top_lambda_offsets=_top_lambda_offsets,
                            module_reg_count=module_reg_count,
                            funcobj_map=funcobj_map,
                            lambda_slot_map=lambda_slot_map,
                            func_nested_lambdas_raw=codegen._func_nested_lambdas)
    # 第二轮：用 patch 后的 seg0 重建 seg1（代码引用长度依赖 seg0 最终长度）。
    seg1 = resource.build(
        func_offsets,
        module_code=module_code,
        total_size=len(seg0) + 1,
        stub_format=True,
        top_level_count=top_level_count,
        commands=_rb_commands,
        nested_ends=nested_ends,
        top_lambda_body_syms=_top_lambda_body_syms,
        module_func_count=_mr_func_count,
        module_reg_count=module_reg_count,
        nested_defun_names=_nested_defun_names,
    )
    sec2_items = count_resource_items(seg1)
    # 确保 items 与 CAD 编译器一致。CAD 的 items 语义：
    # - 含 defun：2 * 模块注册数 + 2（模块注册数 = defun 数 + 顶层 form 数）。
    #   实测：1 函数→4、2 函数→6、3 函数→8、4 函数→10；mix(1 defun+1
    #   顶层)→6、topsetq(2 顶层)→6、t10(2 defun+2 顶层)→10。
    # - 纯顶层（无 defun）：items = 符号槽数 + 2（setcmp 4 form→5，
    #   符号 SET/_/@::_ 3 个 + 2 = 5）。CAD 加载时按 items 处理
    #   GVARINIT 记录，若偏小会遗漏函数注册。
    # 对拍 CAD 实测：items = 模块注册 GVARINIT st_init + 函数注册 GVARINIT
    # st_init（count_resource_items），混合文件（platform 66+6=72）亦吻合。
    min_items = count_resource_records(seg1)
    if sec2_items < min_items:
        sec2_items = min_items

    output = output or source.replace(".lsp", ".fas")
    # 编译产物验证：防止 CAD 加载时访问冲突 0xC0000005（越界符号引用/
    # 误解析/资源段损坏）。致命问题时报错退出（不写 .fas）；warning 仅提示。
    if verify:
        try:
            from compiler.fas_verify import verify_fas

            ok, _vissues = verify_fas(
                seg0, seg1, fas_nsyms, label=os.path.basename(output) or "output"
            )
            _vwarns = [v for v in _vissues if v.startswith("WARN ")]
            _verrs = [v for v in _vissues if not v.startswith("WARN ")]
            for _vi in _vwarns:
                print(f"verify: {_vi}", file=sys.stderr)
            if _verrs:
                print("Compile verification FAILED:", file=sys.stderr)
                for _vi in _verrs:
                    print(f"  - {_vi}", file=sys.stderr)
                print(
                    "FAS not written (would crash CAD with access violation 0xC0000005). "
                    "Fix the source or report the issue.",
                    file=sys.stderr,
                )
                sys.exit(2)
        except ImportError:
            pass  # 模块缺失时不阻断（验证是增强项）
    writer = FasWriter(symtab)
    writer.write(output, seg0, seg1, sec2_items=sec2_items, nsyms=fas_nsyms, compact=True)
    print(f"Compiled to {output}")

    if report_json:
        assert stats is not None
        report = {
            "tool": "atlispcc",
            "command": "compile",
            "source": source,
            "output": output,
            "opt_level": opt_level,
            "encoding": encoding,
            "analysis": {
                "functions": stats["functions"],
                "top_level_forms": stats["top_level_forms"],
                "total_instructions": stats["total_instructions"],
                "constants_estimate": stats["constants_estimate"],
                "symbol_table_entries": stats["symbol_table_entries"],
                "symbol_slots": stats["symbol_slots"],
                "function_offsets": stats["function_offsets"],
                "locals": stats["locals"],
                "tail_recursive_functions": stats["tail_recursive_functions"],
                "builtin_calls": sorted(stats["builtin_calls"]),
                "functions_detail": stats["functions_detail"],
            },
            "optimized": None,
            "product": {
                "nsyms": fas_nsyms,
                "codegen_nsyms": codegen_nsyms,
                "module_reg_count": module_reg_count,
                "top_level_count": top_level_count,
                "sec2_items": sec2_items,
                "seg0_size": len(seg0),
                "seg1_size": len(seg1),
            },
        }
        if stats2 is not None:
            report["optimized"] = {
                "functions": stats2["functions"],
                "total_instructions": stats2["total_instructions"],
                "tail_recursive_functions": stats2["tail_recursive_functions"],
                "symbol_table_entries": stats2["symbol_table_entries"],
                "functions_detail": stats2["functions_detail"],
            }
        with open(report_json, "w", encoding="utf-8") as fh:
            json.dump(report, fh, indent=2, ensure_ascii=False)
        print(f"Report written to {report_json}")

    return output
