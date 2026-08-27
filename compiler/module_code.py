"""CAD module-code builder (_build_cad_module_code, moved from cli.py)."""

import struct
from typing import Optional

from asm.opcodes import encode_usubr
from compiler.resource_builder import _real_fmt
from compiler.slot_map import _collect_symbol_nodes, _is_empty_quote, _offset_slots, _slot_of
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


def _build_cad_module_code(
    top_level_bc: bytes,
    symtab,
    other_forms,
    n_funcs: int = 0,
    top_level_count: int = 0,
    top_after_defun: bool = False,
    func_names: object = (),
    n_post_forms: int = 0,
    n_globals: int = 0,
    gvar_map: object = None,
    top_lambda_slots: Optional[dict] = None,
    real_map: Optional[dict] = None,
    n_pre: int = 0,
    skip_funcs: Optional[set] = None,
    n_cmds: int = 0,
    mid_counts: tuple = (),
    _tl_lam_count: int = 0,
    tl_funcobj_slot: Optional[int] = None,
) -> bytes:
    """把顶层表达式字节码转换为 CAD 风格的模块代码。

    CAD 模块代码规则（逆向，AutoCAD 24.1s 实测）：
    - 符号引用使用 gvar 槽 = 符号槽 + 1
    - 顶部 ``PUSH_G <模块注册符号数+1>; POP`` 占位
    - 顶层 setq → ``PUSH_G <值槽+1>; DUP; SETQ_G <变量槽+1>``
    - 每个顶层语句后 POP（最后一句除外）
    - 有 defun 时追加函数注册尾 ``JUMP + PUSH_G <模块注册+2>; SETQ_G 1; PUSH_G 1``

    对每个顶层 form：setq 用 CAD 的 DUP 模式；其余用 codegen 输出并统一
    符号槽 +1。
    """
    if not other_forms:
        return top_level_bc

    from compiler.codegen import CodeGenerator, BytecodeBuffer

    # 提升的条件 defun（`(if c (progn (defun f ...) ...))`）：defun 体已在顶层，
    # 运行时绑定留 if 守卫内（`_stmt_bytes` 的 CondDefunBind 分支发射），此处
    # 跳过它们的无条件函数注册（否则多余 `PUSH_G c; POP`，panel.lsp 实测）。
    from compiler.ast_nodes import CondDefunBind as _CDB_scan, Progn as _CDB_prog

    def _scan_cond_binds(node):
        _names = set()
        if isinstance(node, _CDB_scan):
            _names.add(node.name)
        elif isinstance(node, Progn):
            for _f in node.forms:
                _names |= _scan_cond_binds(_f)
        elif isinstance(node, IfNode):
            for _p in (node.cond, node.then, node.else_expr):
                if _p is not None:
                    _names |= _scan_cond_binds(_p)
        return _names

    _cond_defun_names = set()
    for _of in other_forms:
        _cond_defun_names |= _scan_cond_binds(_of)

    # c: 命令混合模式：vl-ACAD-defun 在模块注册段占一个符号（+1），使占位符/
    # b 槽/C 槽相对普通混合模式全局 +1（large_synthetic CAD 实测 placeholder
    # 147、reg0 b=277、c=146）。
    module_reg_count = n_funcs + top_level_count + n_cmds
    out = bytearray(b"\x14\x01\x00\x00\x00")  # DEFUN 模块头
    out += bytes([0x09]) + struct.pack("<H", module_reg_count + 1) + b"\x0a"  # 占位

    # 顶层语句按源码位置分组：最后一个 defun 之后的顶层语句（mix2 的
    # `(setq x 10)`、p04 的 `(setq *codepage* ...)` 与 `(if ...)`）排到函数
    # 注册尾之后；defun 之前的排在 JUMP 之前。n_post_forms 由调用方按最后
    # 一个 defun 在 program.forms 中的位置计算，支持多个 post-form（CAD
    # p04-p07 实测）。
    if top_after_defun and other_forms:
        n_post = n_post_forms
        if n_post:
            pre_forms = other_forms[:-n_post]
            post_forms = other_forms[-n_post:]
        else:
            pre_forms = other_forms[:-1]
            post_forms = [other_forms[-1]]
    else:
        pre_forms = other_forms
        post_forms = []

    def _stmt_bytes(form, tail: bool = False):
        """把单个顶层 form 编译为模块代码语句（setq 用 CAD 的 DUP 模式）。

        tail=True 表示该 form 是模块最终保留值（如最后一个 post-form），
        CAD 以其求值结果作为模块代码的返回值——此时 form 内部的尾 setq
        （如 if-then 分支最后一句）需按尾上下文编译（补 DUP，p04 实测）。
        """
        from compiler.ast_nodes import Symbol, String as _Str, Integer as _Int, Real as _Real

        # gvar_map（二次生成）时：模块代码符号引用按资源流实际 gvar 槽重映射。
        _gvar = gvar_map
        _symtab = symtab if _gvar else None

        cg = CodeGenerator(symtab, stub_format=True, nsyms=len(symtab.entries))
        # 模块代码上下文：顶层 if-then 的 setq 需 DUP、无 else if 补 PUSH_NIL
        # （CAD 模块代码实测 `0b 06` / `01 0a`，i18n-cad）。
        cg._module_mode = True
        cg._module_code_ctx = True
        handled = False

        # 首个 c: 命令的符号槽（vl-ACAD-defun 插入点前/后判定用）。const 引用
        # 是否 +n_cmds 移位取决于其注册在首个命令之前/之后（menu const 在后、
        # panel foreach 组 const 在前）。
        _fc_slot = None
        for _fn in (func_names or ()):
            if str(_fn).lower().startswith("c:"):
                _fc_slot = symtab.name_to_idx.get(_fn)
                break

        def _slot_gv(idx):
            """symtab idx → 实际 gvar 槽（gvar_map 可用时）；否则 idx+1+n_cmds。"""
            if _gvar and _symtab is not None and 0 <= idx < len(_symtab.entries):
                _t, _v = _symtab.entries[idx]
                if _t in ("SYMBOL", "STRING"):
                    _s = _gvar.get(str(_v).upper())
                    if _s is not None:
                        return _s
            return idx + 1 + n_cmds

        # 顶层 if 内提升的条件 defun（panel.lsp `(if is-gcad (progn (defun C:% ...)
        # (defun C:%% ...) (foreach ...)))` CAD 实测）：defun 体已提升进 seg0，
        # 运行时绑定留在 if 守卫内——``PUSH_VALUE <cond>; JMP32_IFNOT <else>;
        # JUMP +0; PUSH_G <func-obj>; SETQ_G <sym>; PUSH_G <sym>; USUBR(1,
        # vl-ACAD-defun); PUSH_NIL; POP; ...``。手动组装 if（绑定字节已是最终
        # gvar 槽，不再经 _offset_slots；cond/其余 then/else 走 codegen + offset）。
        from compiler.ast_nodes import CondDefunBind as _CDB2

        def _cond_binds_and_rest(node):
            """剥 Progn 收集 CondDefunBind 标记与剩余 then 语句。"""
            if isinstance(node, Progn):
                _ms = [f for f in node.forms if isinstance(f, _CDB2)]
                if _ms:
                    return _ms, [f for f in node.forms if not isinstance(f, _CDB2)]
                return None, None
            if isinstance(node, _CDB2):
                return [node], []
            return None, None

        if isinstance(form, IfNode) and n_funcs > 0:
            _markers, _rest_forms = _cond_binds_and_rest(form.then)
            if _markers is not None:
                # 条件 defun 的 func-obj/b/c 槽：与 `_reg` 同公式。
                _fc = None
                for _fn in (func_names or ()):
                    if str(_fn).lower().startswith("c:"):
                        _fc = symtab.name_to_idx.get(_fn)
                        break
                _vl = (_fc + 1) if _fc is not None else None
                _cb = bytearray()
                _fb = BytecodeBuffer()
                cg._emit_expr(_fb, form.cond or Symbol("nil"), _tail=True)
                _fb.resolve()
                _cb += _offset_slots(bytes(_fb.data), len(symtab.entries), gvar_map=_gvar,
                                     symtab=_symtab, real_map=real_map, n_cmds=n_cmds,
                                     tl_funcobj_slot=tl_funcobj_slot, first_cmd_slot=_fc_slot)
                _jmpnot_pos = len(_cb)
                _cb += b"\x67\x00\x00\x00\x00"  # JMP32_IFNOT 占位
                for _m in _markers:
                    _i = func_names.index(_m.name) if _m.name in func_names else -1
                    if _i < 0:
                        continue
                    _b = 2 * n_funcs + 1 + top_level_count + n_cmds + _tl_lam_count - _i
                    if _tl_lam_count and _i >= n_pre:
                        _b -= 1
                    _fs = symtab.name_to_idx.get(func_names[_i])
                    _c = (_fs + 1) if _fs is not None else (n_funcs - _i)
                    if _fs is not None and _fc is not None and _fs >= _fc:
                        _c += 1
                    _cb += b"\x57\x00\x00\x00\x00"  # JUMP +0
                    _cb += bytes([0x09]) + struct.pack("<H", _b)  # PUSH_G func-obj
                    _cb += bytes([0x06]) + struct.pack("<H", _c)  # SETQ_G sym
                    _cb += bytes([0x09]) + struct.pack("<H", _c)  # PUSH_G sym
                    if _vl is not None:
                        _cb += bytes([0x35, 0x01]) + struct.pack("<H", _vl)  # USUBR(1, vl-ACAD-defun)
                        _cb += bytes([0x01, 0x0a])  # PUSH_NIL; POP
                for _rf in _rest_forms:
                    _fb2 = BytecodeBuffer()
                    cg._emit_expr(_fb2, _rf, _tail=True)
                    _fb2.resolve()
                    _cb += _offset_slots(bytes(_fb2.data), len(symtab.entries), gvar_map=_gvar,
                                         symtab=_symtab, real_map=real_map, n_cmds=n_cmds,
                                         tl_funcobj_slot=tl_funcobj_slot, first_cmd_slot=_fc_slot)
                _jmp_pos = len(_cb)
                _cb += b"\x57\x00\x00\x00\x00"  # JUMP <end>
                _else_pos = len(_cb)
                if form.else_expr:
                    _fb3 = BytecodeBuffer()
                    cg._emit_expr(_fb3, form.else_expr, _tail=False)
                    _fb3.resolve()
                    _cb += _offset_slots(bytes(_fb3.data), len(symtab.entries), gvar_map=_gvar,
                                         symtab=_symtab, real_map=real_map, n_cmds=n_cmds,
                                         tl_funcobj_slot=tl_funcobj_slot, first_cmd_slot=_fc_slot)
                else:
                    _cb += b"\x01"  # PUSH_NIL（无 else）
                _end_pos = len(_cb)
                struct.pack_into("<i", _cb, _jmpnot_pos + 1, _else_pos - (_jmpnot_pos + 5))
                struct.pack_into("<i", _cb, _jmp_pos + 1, _end_pos - (_jmp_pos + 5))
                return bytes(_cb)

        if isinstance(form, Setq):
            # 多对 setq：CAD 输出全部 pair。中间 pair 用
            # `PUSH_<值>; SETQ_G`（无 DUP），最后一个 pair 用
            # `PUSH_<值>; DUP; SETQ_G`。值：`'()`/`nil` → PUSH_NIL，
            # 符号/字符串 → PUSH_G <gvar 槽>。任一对值非常量（INT/REAL/
            # 列表等，需 codegen）时整条退回通用 codegen 路径。
            pairs_bc = bytearray()
            n = len(form.pairs)
            for i, (target, value) in enumerate(form.pairs):
                t_idx = _slot_of(symtab, target)
                if t_idx is None:
                    break
                pre = bytearray()
                if _is_empty_quote(value):
                    pre += bytes([0x01])  # PUSH_NIL
                    v_ok = True
                elif isinstance(value, Symbol) and value.name == "nil":
                    pre += bytes([0x01])  # PUSH_NIL（CAD 用 PUSH_NIL 值 nil）
                    v_ok = True
                else:
                    if isinstance(value, _Int):
                        # 整数字面量：内联 PUSH_INT8 / PUSH_INT32（CAD 模块代码
                        # `setq x 10` 实测 `32 0a 0b 06 03 00`；与 codegen 编码一致），
                        # 无需走通用路径（避免 per-form 反汇编）。
                        val = value.value
                        if -128 <= val <= 127:
                            pre += bytes([0x32, val & 0xFF])  # PUSH_INT8
                        elif -2147483648 <= val <= 2147483647:
                            pre += bytes([0x33]) + struct.pack("<i", val)  # PUSH_INT32
                        else:
                            # 超出 int32 范围：codegen 会按 REAL 编码，退回通用路径
                            break
                        v_ok = True
                    elif isinstance(value, _Real):
                        # 实数常量：纯顶层文件（无 defun，无 fg 表）模块代码用
                        # PUSH_G 引用 REAL 槽（gvar 槽 = 符号槽+1，constants.lsp
                        # CAD golden 实测 `09 1b 00`）。混合文件（有 defun）实数
                        # 注册在 fg 表、模块代码(rg 上下文)读不到，内联
                        # PUSH_REAL `3b <ascii> 00` 保证值正确（@lisp_u
                        # `(setq @::*seconds-per-day* 86400.0)` 实测）。
                        if n_funcs == 0:
                            _rk = f"__real_{value.value}__"
                            _r_idx = symtab.name_to_idx.get(_rk)
                            if _r_idx is not None:
                                pre += bytes([0x09]) + struct.pack("<H", _slot_gv(_r_idx))  # PUSH_G
                                v_ok = True
                            else:
                                from compiler.resource_builder import _real_fmt as _rf

                                pre += b"\x3b" + _rf(float(value.value)).encode("ascii") + b"\x00"
                                v_ok = True
                        else:
                            from compiler.resource_builder import _real_fmt as _rf

                            pre += b"\x3b" + _rf(float(value.value)).encode("ascii") + b"\x00"
                            v_ok = True
                    else:
                        v_idx = _slot_of(symtab, value)
                        if v_idx is None:
                            break  # 复杂值 → 退回通用路径
                        if isinstance(value, Symbol):
                            # 非引号符号值：普通变量用 PUSH_VALUE（setcmp
                            # `(setq _ @::_)` 实测 `03 <槽+1>`）。函数符号
                            # 也用 PUSH_VALUE（user-manager CAD golden
                            # `(setq @::valid-user @::check-userinfo)` 实测
                            # `03 19 00 0b 06 18 00`）——PUSH_VALUE 压模块
                            # 注册段槽的值（函数对象），SETQ_G 绑定。旧实现
                            # 对函数名发 PUSH_G（@lisp_u `(setq @::unschedule
                            # -task @::string-to-list)` 功能验证），字节与 CAD
                            # 不符。
                            pre += bytes([0x03]) + struct.pack("<H", _slot_gv(v_idx))  # PUSH_VALUE
                        else:
                            pre += bytes([0x09]) + struct.pack("<H", _slot_gv(v_idx))  # PUSH_G
                        v_ok = True
                if not v_ok:
                    break
                if i == n - 1:
                    pre += b"\x0b"  # DUP（仅在最后一对）
                pre += bytes([0x06]) + struct.pack("<H", _slot_gv(t_idx))  # SETQ_G
                pairs_bc += pre
            else:
                return bytes(pairs_bc)
        if isinstance(form, InPackage):
            # `(in-package :@)`：CAD 发射真实调用 `PUSH_VALUE <:@>; USUBR(1,
            # IN-PACKAGE)`（base-function CAD golden 实测 `03 2f 00 35 01 2e 00
            # 03`；atlisp_u CAD golden 实测 12 次 `GVAR_PUSH 954(:@); FUNC_REF
            # 937,1`——AGENTS.md "模块代码不发射" 旧注释过时，2026-08-16 勘误）。
            # 包名取 form.name（command.lsp `(in-package :C)`，勿硬编码 :@）。
            # 符号 IN-PACKAGE/<包名> 经 _collect_symbol_nodes 注册。
            _pkg_idx = symtab.name_to_idx.get(form.name)
            _fn_idx = symtab.name_to_idx.get("in-package")
            if _pkg_idx is not None and _fn_idx is not None:
                return (
                    bytes([0x03]) + struct.pack("<H", _slot_gv(_pkg_idx))  # PUSH_VALUE :@
                    + encode_usubr(1, _slot_gv(_fn_idx), 3)  # USUBR(1, in-package)
                )
            return bytes([0x01])  # 兜底：槽缺失时退化为 PUSH_NIL 占位
        if isinstance(form, Defpackage):
            # `(defpackage :C (:use :cl) (:export ...))`：CAD 编译为（sub-system/
            # command CAD golden 实测）：
            #   PUSH_VALUE :C（包名）
            #   PUSH_VALUE :CL; USUBR 1, :USE        # 每个 (:use 包) 子句
            #   PUSH_VALUE <exports 正序>; USUBR <n>, :EXPORT
            #   USUBR 3, DEFPACKAGE
            # 各子调用结果都保留在栈上供 defpackage 取用，内部**无** `NIL;
            # PUSH_VALUE 0` 清理（CAD command 实测 raw：`03 26 00 03 25 00 35
            # 01 24 00 03 03 23 00 ... 35 0d 16 00 03 35 03 15 00 03 0a`——
            # 仅 _emit_stmts 在语句末尾补 POP）。USUBR argc=3 取包名、use 结果、
            # export 结果。`defpackage`/`:use`/`:export`/包名/包名列表符号经
            # _collect_symbol_nodes 的 Defpackage 分支注册。
            _fn_defpkg = symtab.name_to_idx.get("defpackage")
            _fn_use = symtab.name_to_idx.get(":use")
            _fn_export = symtab.name_to_idx.get(":export")
            if _fn_defpkg is not None and _fn_use is not None and _fn_export is not None:
                _name_idx = symtab.name_to_idx.get(form.name)
                if _name_idx is not None:
                    parts = [bytes([0x03]) + struct.pack("<H", _slot_gv(_name_idx))]
                    ok = True
                    for _u in form.use:
                        _u_idx = symtab.name_to_idx.get(_u)
                        if _u_idx is None:
                            ok = False
                            break
                        parts.append(bytes([0x03]) + struct.pack("<H", _slot_gv(_u_idx)))
                        parts.append(encode_usubr(1, _slot_gv(_fn_use), 3))
                    if ok:
                        for _e in form.export:
                            _e_idx = symtab.name_to_idx.get(_e)
                            if _e_idx is None:
                                ok = False
                                break
                            parts.append(bytes([0x03]) + struct.pack("<H", _slot_gv(_e_idx)))
                        if ok:
                            if form.export:
                                parts.append(encode_usubr(len(form.export), _slot_gv(_fn_export), 3))
                            parts.append(encode_usubr(3, _slot_gv(_fn_defpkg), 3))
                            return b"".join(parts)
            return bytes([0x01])  # 兜底：槽缺失时退化为 PUSH_NIL 占位
        if isinstance(form, Call) and str(form.name).lower() == "use-package":
            # `(use-package :autolisp)`：同 in-package，CAD 发射真实调用
            # `PUSH_VALUE <:autolisp>; USUBR(1, USE-PACKAGE)`（base-function CAD
            # golden 实测 `03 2d 00 35 01 2c 00 03`；atlisp_u CAD golden 实测 7 次）。
            _arg = form.args[0] if form.args else None
            _arg_idx = (
                symtab.name_to_idx.get(_arg.name)
                if isinstance(_arg, Symbol) else None
            )
            _fn_idx = symtab.name_to_idx.get("use-package")
            if _arg_idx is not None and _fn_idx is not None:
                return (
                    bytes([0x03]) + struct.pack("<H", _slot_gv(_arg_idx))  # PUSH_VALUE :autolisp
                    + encode_usubr(1, _slot_gv(_fn_idx), 3)  # USUBR(1, use-package)
                )
            return bytes([0x01])  # 兜底：槽缺失时退化为 PUSH_NIL 占位
        # 顶层 `(set/setq 'sym (lambda ...))`（纯顶层文件，CAD `-lambda-` SUBR）：
        # 模块代码 `PUSH_G <sym>; PUSH_G <-lambda-槽>; FUNC_REF set`，不经
        # kwote/引用常量（CAD 实测 bootstrap）。`-lambda-` 槽由 seg0 生成阶段
        # 经 top_lambda_slots 映射（DEFCODE 注册为可调用 SUBR）。
        if top_lambda_slots:
            from compiler.ast_nodes import LambdaNode as _LN

            _tgt = None
            _is_lam = False
            if isinstance(form, Call) and form.name == "set" and len(form.args) == 2:
                _t0 = form.args[0]
                if isinstance(_t0, QuotedExpr) and isinstance(_t0.expr, Symbol):
                    _tgt = _t0.expr.name
                _v1 = form.args[1]
                _is_lam = isinstance(_v1, _LN) or (
                    isinstance(_v1, QuotedExpr) and isinstance(_v1.expr, _LN)
                )
            elif isinstance(form, Setq):
                for _t, _v in form.pairs:
                    if isinstance(_t, Symbol):
                        _tgt = _t.name
                        _is_lam = isinstance(_v, _LN) or (
                            isinstance(_v, QuotedExpr) and isinstance(_v.expr, _LN)
                        )
                        break
            if _tgt is not None and _is_lam and _tgt in top_lambda_slots:
                _sym_idx = symtab.name_to_idx.get(_tgt)
                _lam_slot = top_lambda_slots[_tgt]
                _b = bytearray()
                # CAD `(set 'X (lambda ...))`（bootstrap CAD golden 实测）：
                # 模块代码 `PUSH_G <sym>; JUMP 0; PUSH_G <-lambda-槽>; USUBR(2,
                # SET)` ——用 `set` 函数调用绑定（不是 setq 协议）。`-lambda-`
                # 槽 = _lam_slot（不 +1），SET 为模块注册的 set 内建 gvar 槽。
                if isinstance(form, Call) and form.name == "set":
                    _set_idx = symtab.name_to_idx.get("set")
                    if _sym_idx is not None and _set_idx is not None:
                        _b += bytes([0x09]) + struct.pack(
                            "<H", _slot_gv(_sym_idx)
                        )  # PUSH_G <sym>
                        _b += bytes([0x57, 0x00, 0x00, 0x00, 0x00])  # JUMP 0
                        # `-lambda-` 槽是 DEFCODE 区注册的独立 gvar 槽（不在
                        # symtab/gvar_map），PUSH_G = _lam_slot。不能用 _slot_gv
                        # （会把槽当 symtab 索引查 entries → 错位到 gvar_map）。
                        _b += bytes([0x09]) + struct.pack("<H", _lam_slot)  # PUSH_G <-lambda->
                        _b += encode_usubr(
                            2, _slot_gv(_set_idx), 3
                        )  # USUBR(2, set)
                        return bytes(_b)
                # CAD 纯顶层 `(setq X (lambda ...))`（setq-lambda.lsp CAD golden
                # 实测）：模块代码 `JUMP 0; PUSH_G <-lambda-槽>; DUP; SETQ_G <sym>`
                # ——用 setq 协议绑定（不是 `set` 函数）。JUMP 0 为占位跳转。
                _b += bytes([0x57, 0x00, 0x00, 0x00, 0x00])  # JUMP 0
                # `-lambda-` 槽是 DEFCODE 区注册的独立 gvar 槽（不在 symtab/
                # gvar_map），PUSH_G = 符号槽 + 1（_lam_slot 28 → 29）。不能用
                # _slot_gv（会把槽当 symtab 索引查 entries → 错位到 gvar_map）。
                _b += bytes([0x09]) + struct.pack("<H", _lam_slot + 1)  # PUSH_G <-lambda->
                _b += bytes([0x0b])  # DUP
                if _sym_idx is not None:
                    _b += bytes([0x06]) + struct.pack("<H", _slot_gv(_sym_idx))  # SETQ_G <sym>
                return bytes(_b)
        fb = BytecodeBuffer()
        cg._emit_expr(fb, form, _tail=tail)
        fb.resolve()
        bc = bytes(fb.data)
        if isinstance(form, Setq) and not tail and len(form.pairs) == 1:
            # setq 值非常量（INT/REAL/列表等）：CAD 在 SETQ_G 前插入 DUP
            # 保留返回值（mix2 `(setq x 10)` 实测 `32 0a 0b 06 03 00`）。
            # 注意：多对 setq 的末对 DUP 已由 codegen 生成（n>1 末对），
            # 此处仅单对 setq 补 DUP（platform 实测多对末对无额外 `0b`）。
            # 不能简单正则找 `06 ..`——USUBR 的 idx 字节可能为 0x06，
            # 需定位真正的 SETQ_G 指令偏移。
            from decompiler.fas4_decompiler import Disassembler

            _dis = Disassembler(short_subr=not (len(symtab.entries) > 256))
            try:
                _insts = _dis.disassemble(bc, len(symtab.entries), sym_count=len(symtab.entries))
            except Exception:
                _insts = []
            _setq_off = None
            for _i in _insts:
                if _i.op_name == "SETQ_G":
                    _setq_off = _i.offset
            if _setq_off is not None:
                bc = bc[:_setq_off] + b"\x0b" + bc[_setq_off:]
        return _offset_slots(bc, len(symtab.entries), gvar_map=_gvar, symtab=_symtab, real_map=real_map,
                             n_cmds=n_cmds, tl_funcobj_slot=tl_funcobj_slot, first_cmd_slot=_fc_slot)

    def _emit_stmts(forms, last_no_pop: bool):
        """输出一组语句，每条后 POP；last_no_pop=True 时最后一条不跟 POP。

        自平衡语句（progn/while/foreach/repeat 自身管理栈，`_stmt_bytes` 返回
        已平衡代码）不再追加 POP——cl-macros 顶层 `(progn (setq ...) ...)` 的
        progn 是唯一顶层语句，CAD 模块代码实测 `USUBR; SETQ_G` 后直接 JUMP 注册、
        无 `0a`；@lisp-env 的 mid progn（setq 无 `0b`/`0a`）同规则。直接
        setq（DUP 保留值）/调用/符号仍留值 → 需 POP（event-bus 实测
        `setq ... DUP SETQ_G; POP`）。
        """
        nonlocal out
        _self_balancing = (Progn, WhileNode, ForeachNode, RepeatNode)
        for i, form in enumerate(forms):
            tail = last_no_pop and i == len(forms) - 1
            stmt = _stmt_bytes(form, tail=tail)
            out += stmt
            if (i < len(forms) - 1 or not last_no_pop) and not isinstance(form, _self_balancing):
                out += b"\x0a"  # POP

    # ── 顶层语句分组（CAD 实测）─────────────────────────────────────
    # globals_forms：首个 defun 之前的顶层 setq 语句（模块全局初始化）。
    # mid_forms：首个 defun 与最后一个 defun 之间的顶层语句。
    # post_forms：最后一个 defun 之后的顶层语句。
    # CAD 把**第一个**函数的 JUMP+注册放在 globals 之后（模块代码后续语句
    # 可调用它），把其余函数注册放在所有 mid 语句之后、post 语句之前
    # （i18n/p04 实测）。单函数文件 mid 为空、无尾部注册，等价于并列形式。
    n_globals = max(0, min(n_globals, len(pre_forms)))
    globals_forms = pre_forms[:n_globals]
    mid_forms = pre_forms[n_globals:]
    # 首个函数注册后是否还有后续内容（需 `PUSH_G c; POP` 清理）。
    has_follow = bool(n_funcs > 1 or mid_forms or post_forms)
    # 末全局是 Progn（顶层 `(progn ...)` 展开后 defun 提升、剩余表达式包回
    # Progn，cl-macros/cl-functions/init/compat 实测）：CAD 的纯尾部注册
    # （无 post、无 START 函数）省略 `PUSH_G c; POP` no-op，每组仅
    # `JUMP; PUSH_G b; SETQ_G c`（cl-macros golden 实测）；直接 setq/call
    # 末全局（net/proxy/ax-request）仍保留 no-op。
    _last_global_progn = bool(globals_forms) and isinstance(globals_forms[-1], Progn)
    # post 语句为自平衡块（progn/while/foreach/repeat/cond）时，注册尾
    # `PUSH_G c; POP` no-op 同样省略（cl-functions 末 post PROGN 实测
    # `(setq :@ ':@)` 后直接 END_DEFUN，无 `09 c 00 0a`）。
    _post_selfbal = bool(post_forms) and all(
        isinstance(_p, (Progn, WhileNode, ForeachNode, RepeatNode, Cond))
        for _p in post_forms
    )
    # 末全局是 Progn 且无 post/START（cl-macros）或 post 为自平衡块（cl-functions
    # 末 post PROGN）时，TAIL 注册省略 `PUSH_G c; POP` no-op（START 注册仍保留）。
    _skip_reg_pc = (
        (_last_global_progn and not post_forms and n_pre == 0)
        or _post_selfbal
    )

    _emit_stmts(globals_forms, last_no_pop=(n_funcs == 0 and not post_forms))

    _last_reg_cmd = False
    if n_funcs > 0:
        # c: 命令混合模式：vl-ACAD-defun 在模块注册段占一个符号（gvar 槽 =
        # 源码首个命令的符号槽 + 1，large_synthetic 实测槽 19），其后的
        # 函数 gvar 槽 +1（CMD-000 符号槽 18 → c=20；lgf-var-000 槽 144 →
        # c=146）。命令注册用 CAD 24 字节模式（含 USUBR 调用 vl-ACAD-defun）。
        _first_cmd_slot = None
        if n_cmds and func_names:
            for _fn in func_names:
                if str(_fn).lower().startswith("c:"):
                    _first_cmd_slot = symtab.name_to_idx.get(_fn)
                    break

        def _is_cmd(i):
            return bool(func_names) and i < len(func_names) and str(func_names[i]).lower().startswith("c:")

        def _reg(i):
            # 有 defun：追加函数注册尾（CAD 实测）。每函数一组
            # `PUSH_G <b>; SETQ_G <c>`，组间 `PUSH_G <c>; POP; JUMP`；
            # b = 2*n_funcs+1 + top_level_count + n_cmds - i（模块注册偏移，
            # vl-ACAD-defun 符号使占位符/b 槽全局 +1）。顶层 kwote lambda
            # func-obj（`-lambda-#TL`）再 +1（setup b0=37 = 29+7+1 实测）。
            # c 槽 = 源码注册序：函数占 c = 符号槽 + 1（p03 实测
            # @::codepage2lang 槽 4 → c=5）；符号槽 ≥ 源码首个命令槽时再 +1
            # （vl 符号占用其后一个槽）；未显式给定函数名时退化为相对编号
            # n_funcs - i。
            nonlocal out
            b = 2 * n_funcs + 1 + top_level_count + n_cmds + _tl_lam_count - i
            # 顶层 kwote lambda 的 func-obj 槽位于 START 注册之后（setup 槽 29，
            # START 37..30 / TAIL 28..23）：TAIL 注册（i >= n_pre）让出该槽 -1。
            if _tl_lam_count and i >= n_pre:
                b -= 1
            fn_slot = symtab.name_to_idx.get(func_names[i]) if i < len(func_names) and func_names else None
            c = (fn_slot + 1) if fn_slot is not None else (n_funcs - i)
            if fn_slot is not None and _first_cmd_slot is not None and fn_slot >= _first_cmd_slot:
                c += 1
            out += bytes([0x09]) + struct.pack("<H", b)  # PUSH_G b
            out += bytes([0x06]) + struct.pack("<H", c)  # SETQ_G c
            return c

        _skip = (skip_funcs or set()) | _cond_defun_names
        # 首个 defun 与最后一个 defun 之间的顶层语句（含 setq-lambda 绑定）。
        # mid 语句为**别名 set**（`(set 'cl::xxx cl::xxx)`，cl-functions 的
        # #-sbcl + progn 展开模式）时，CAD 把每条 mid 语句与对应函数的注册
        # **交错**（[reg i, mid[i], reg i+1, mid[i+1], ...]）；普通 mid 语句
        # （i18n/platform 的 setq/if）仍全部 mid 先、注册后。
        def _mid_lead_alias(_m):
            _first = _m.forms[0] if isinstance(_m, Progn) else _m
            return (
                isinstance(_first, Call)
                and str(_first.name).lower() == "set"
                and len(_first.args) == 2
                and isinstance(_first.args[0], QuotedExpr)
                and isinstance(_first.args[0].expr, Symbol)
                and isinstance(_first.args[1], Symbol)
            )

        def _mid_is_set(_m):
            _first = _m.forms[0] if isinstance(_m, Progn) else _m
            return isinstance(_first, Call) and str(_first.name).lower() == "set"

        # mid 语句**多数为 `set` 别名绑定**（`(set 'X @::X)`，cl-functions 的
        # #-sbcl + progn 展开、base-function 的 handle-keywords/leap-yearp 等
        # 全部）时，CAD 把每条 mid 语句与对应函数的注册**交错**
        # （[reg i, mid[i], reg i+1, mid[i+1], ...]）；普通 mid 语句
        # （i18n/platform 的 setq/if 占多数）仍全部 mid 先、注册后。
        # base-function 的 mid[0] `(set '$platform (read ...))`（值非符号）
        # 与 mid[5] `(setq @::*mktime-epoch* ...)` 非干净别名 set，但同样交错。
        _interleave_mid = sum(mid_counts) > 0
        # START 函数注册：前 n_pre 个函数（定义在首个顶层语句之前，CAD
        # platform 实测 set-locale/get-locale 在 globals 语句前注册）。
        # 每组 `JUMP; PUSH_G b; SETQ_G c; PUSH_G c; POP`；命令组为 CAD
        # 24 字节模式 `JUMP; PUSH_G b; SETQ_G c; PUSH_G c; USUBR(1,<vl槽>);
        # POP; PUSH_G c; POP`（vl-ACAD-defun 注册命令）。
        _vl_slot = (_first_cmd_slot + 1) if _first_cmd_slot is not None else None
        _mi = 0
        _mid_counts = mid_counts or ()

        def _emit_mid_for(i):
            # 交错模式下按 mid_counts 把函数 i 的 mid 语句分配给它（无 mid 的
            # 函数跳过）。mid_forms 顺序与源码 mid 顺序一致（cl-functions
            # @::eval/@::require 无 mid，不消耗 mid_forms）。
            nonlocal _mi
            if not _interleave_mid:
                return
            _cnt = _mid_counts[i] if i < len(_mid_counts) else 0
            if _cnt > 0 and _mi < len(mid_forms):
                _emit_stmts(mid_forms[_mi : _mi + _cnt], last_no_pop=False)
                _mi += _cnt

        for i in range(min(n_pre, n_funcs)):
            out += b"\x57\x00\x00\x00\x00"
            c = _reg(i)
            if _skip_reg_pc:
                # START 注册也省略 `PUSH_G c; POP` no-op（cl-functions 首个
                # defun cl::stringp 的 START 注册 CAD 实测无 no-op）。
                _emit_mid_for(i)
                continue
            out += bytes([0x09]) + struct.pack("<H", c)
            if _is_cmd(i) and _vl_slot is not None:
                out += bytes([0x35, 0x01]) + struct.pack("<H", _vl_slot) + bytes([0x01, 0x0a])
                out += bytes([0x09]) + struct.pack("<H", c)
            out += b"\x0a"
            _emit_mid_for(i)

        def _reg_emit(i):
            # 其余函数注册（最后一个 defun 之前、post 语句之前）。setq-lambda
            # 函数（skip_funcs）已由 mid_forms 的 setq 绑定，不在此 `_reg`。
            nonlocal out, _last_reg_cmd
            out += b"\x57\x00\x00\x00\x00"
            c = _reg(i)
            _last_reg_cmd = _is_cmd(i)
            if _is_cmd(i) and _vl_slot is not None:
                out += bytes([0x09]) + struct.pack("<H", c)
                out += bytes([0x35, 0x01]) + struct.pack("<H", _vl_slot) + bytes([0x01, 0x0a])
                out += bytes([0x09]) + struct.pack("<H", c)
                # 命令注册 `PUSH_G c; USUBR; POP; PUSH_G c` 对**末尾**命令也发射
                # （CAD command 实测末函数 C:@DIAG 有 vl-ACAD-defun USUBR），但
                # 末尾命令（无后续注册/post_forms）不再跟 `0a` POP（END_DEFUN 前
                # CAD 实测 `... 09 01 00 35 01 12 00 01 0a 09 01 00 16`）。
                if i < n_funcs - 1 or post_forms:
                    out += b"\x0a"
            elif (i < n_funcs - 1 and not _skip_reg_pc) or (post_forms and not _post_selfbal):
                # 非命令注册 `PUSH_G c; POP` no-op：仅当注册后有后续内容
                # （非末尾、post 语句、或非 Progn 末全局的纯尾部）时发射。
                out += bytes([0x09]) + struct.pack("<H", c)
                out += b"\x0a"

        if _interleave_mid:
            # mid 别名 set 与注册交错：每个注册（START/TAIL）后紧跟其对应
            # 函数的 mid set（cl-functions `(set 'cl::xxx cl::xxx)`，按
            # mid_counts 分配，无 mid 函数跳过）。
            for i in range(n_pre, n_funcs):
                if func_names and i < len(func_names) and func_names[i] in _skip:
                    continue
                _reg_emit(i)
                _emit_mid_for(i)
        else:
            _emit_stmts(mid_forms, last_no_pop=False)
            for i in range(n_pre, n_funcs):
                if func_names and i < len(func_names) and func_names[i] in _skip:
                    continue
                _reg_emit(i)
    else:
        _emit_stmts(mid_forms, last_no_pop=(not post_forms))
    if post_forms:
        _emit_stmts(post_forms, last_no_pop=True)
    elif not top_after_defun and not _last_reg_cmd:
        out += bytes([0x09]) + struct.pack("<H", 1)  # PUSH_G 1
    out += b"\x16"  # END_DEFUN
    return bytes(out)


