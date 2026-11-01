"""USUBR/FUNC slot remapping (_subr_bytes + _patch_usubr_idx, moved from cli.py)."""

from typing import Optional

from compiler.resource_builder import _real_fmt
def _subr_bytes(opcode: int, argc: int, idx: int, flags: int = 3, wide: bool = False) -> bytes:
    """stub USUBR/FUNC 编码：小文件 3 字节 `op <argc> <idx8>`；
    大文件（idx>255）USUBR 5 字节 `35 <argc> <idx16> <flags=3>`、FUNC 6 字节
    `51 <argc> <idx16> <flags=1> 00`（CAD atlisp_u 实测 USUBR flags=3、
    FUNC flags=1 + 尾 0）。"""
    if wide or idx > 255:
        if opcode == 0x51:
            return bytes([opcode, argc & 0xFF, idx & 0xFF, (idx >> 8) & 0xFF, flags & 0xFF, 0])
        return bytes([opcode, argc & 0xFF, idx & 0xFF, (idx >> 8) & 0xFF, flags & 0xFF])
    return bytes([opcode, argc & 0xFF, idx & 0xFF])


def _patch_usubr_idx(seg0: bytes, seg1: bytes, symtab, nsyms: int, func_args=None, codegen_nsyms: Optional[int] = None,
                     params_by_name: Optional[dict] = None, lambda_args_by_func: Optional[dict] = None,
                     nested_lambda_args: Optional[dict] = None,
                     nested_lambda_order: Optional[dict] = None,
                     has_top_forms: bool = False, n_real_funcs: int = 1,
                     top_lambda_args: Optional[list] = None,
                     top_lambda_offsets: Optional[dict] = None,
                     module_reg_count: Optional[int] = None,
                     funcobj_map: Optional[dict] = None,
                     lambda_slot_map: Optional[dict] = None,
                     func_nested_lambdas_raw: Optional[dict] = None) -> bytes:
    """修正 stub 字节码的 USUBR 与参数槽索引为 CAD 的 gvar 槽 - 1。

    CAD 实测逆向：
    - USUBR 调用符号的 gvar 槽 = idx + 1（idx = gvar 槽 - 1）
    - 参数绑定/读取槽 = 参数符号的 gvar 槽 - 1（越界符号 gvar 槽假定 = nsyms）
    codegen 用占位生成，此处用资源段 GVARINIT 重建的 gvar 表修正。

    仅当文件含顶层表达式（has_top_forms=True，顶层符号占用模块注册槽导致
    codegen symtab 序 ≠ 资源注册序）时重映射。纯函数文件（无顶层表达式）
    codegen 槽已与资源 symbol_slots 一致，重映射反而破坏正确输出（多 kwote
    PUSH_G 字符串被 `nsyms-1` 回退改错槽、kwote FUNC 槽错位 → CAD 加载报
    `-lambda-` 类型错误，test-2kwote/platform-api 实测），直接原样返回。

    当 codegen 内嵌 `(function (lambda ...))`（kwote）时，codegen 会把 `-lambda-`
    追加进 symtab.entries，使 fas_nsyms（len(entries)-module_reg_count+1）比
    codegen 构造时的 nsyms 大 1；而 `-lambda-` 不参与资源段符号注册，导致
    seg0 引用（gvar 槽 - 1）整体再偏移 1。此时应使用 gvar 槽 - 2（i18n 实测
    PKG-NAME fg[88]→参数槽 86、ASSOC fg[90]→USUBR 88）。t01 等无 kwote 文件
    fas_nsyms==codegen_nsyms，保持 gvar 槽 - 1。

    注意：offset 仅当所有 `-lambda-` 槽都集中在 symtab.entries **末尾**时才
    生效（t20/i18n 单 kwote 实测 gvar 槽 - 2 真机通过）。多 kwote 文件
    （@lisp_u 89 槽）`-lambda-` 穿插在普通符号之间，无法用统一偏移补偿，
    此时 offset=0（CAD 实测 `nsyms-codegen_nsyms` 过大导致 USUBR/FUNC 索引
    整体错位、加载报参数太少）。
    """
    if not has_top_forms and n_real_funcs <= 1:
        # 单函数无 kwote（`-lambda-`）文件：codegen 槽已与资源 symbol_slots 一致，
        # 重映射反而破坏正确输出（多 kwote PUSH_G 字符串被 `nsyms-1` 回退改错槽、
        # kwote FUNC 槽错位 → CAD 加载报 `-lambda-` 类型错误），直接原样返回。
        # 函数体内嵌套 `(defun inner ...)` 的 func-obj PUSH_G 槽须先重映射
        # （codegen 发射序 ≠ DEFCODE offset 升序，n5 实测 mid/inner 互换）。
        if funcobj_map:
            from decompiler.fas4_decompiler import Disassembler

            _wide = nsyms > 256
            try:
                _insts = Disassembler(short_subr=not _wide).disassemble(
                    seg0, nsyms, sym_count=len(symtab.entries))
            except Exception:
                return seg0
            _out = bytearray()
            for _inst in _insts:
                if _inst.op_name == "PUSH_G" and _inst.operands and _inst.size == 3:
                    _i0 = _inst.operands[0]
                    if _i0 in funcobj_map:
                        _ni = funcobj_map[_i0]
                        if 0 <= _ni <= 0xFFFF:
                            _out += bytes([0x09, _ni & 0xFF, (_ni >> 8) & 0xFF])
                            continue
                _out += seg0[_inst.offset : _inst.offset + _inst.size]
            seg0 = bytes(_out)
        # 含内嵌 kwote `-lambda-` 的单函数文件（net/reload.lsp 双 kwote 实测）：
        # `-lambda-` 不参与资源符号注册，按其在所有 `-lambda-` 条目中的序号
        # 编址（lambda i 槽 = nsyms - i，操作数 = nsyms - 1 - i；与多函数
        # lam_order 同规则）。codegen 用 symtab 槽（首个 = codegen 末尾，
        # 与 nsyms-1 通常一致，但多 kwote 时首 lambda 槽 ≠ nsyms-1），须重映射
        # PUSH_G `-lambda-` 引用。仅重映射 `-lambda-`，不动其它符号。
        _lam_entries = [
            (_ei, _e[1]) for _ei, _e in enumerate(symtab.entries)
            if isinstance(_e, tuple) and len(_e) == 2
            and _e[0] == "SYMBOL" and str(_e[1]).upper() == "-LAMBDA-"
        ]
        if not _lam_entries:
            return seg0
        # symtab 中 `-lambda-` 槽 → CAD 槽（nsyms-1-lam_idx），lam_idx 按
        # symtab 出现序。
        _lam_slot_map = {_ei: (nsyms - 1 - _i) for _i, (_ei, _) in enumerate(_lam_entries)}
        from decompiler.fas4_decompiler import Disassembler

        _wide = nsyms > 256
        try:
            _insts = Disassembler(short_subr=not _wide).disassemble(
                seg0, nsyms, sym_count=len(symtab.entries))
        except Exception:
            return seg0
        _out = bytearray()
        for _inst in _insts:
            if _inst.op_name == "PUSH_G" and _inst.operands and _inst.size == 3:
                _i0 = _inst.operands[0]
                if _i0 in _lam_slot_map:
                    _ni = _lam_slot_map[_i0]
                    if 0 <= _ni <= 0xFFFF:
                        _out += bytes([0x09, _ni & 0xFF, (_ni >> 8) & 0xFF])
                        continue
            _out += seg0[_inst.offset : _inst.offset + _inst.size]
        return bytes(_out)
    offset = 0
    if codegen_nsyms is not None and nsyms > codegen_nsyms:
        _trailing_lam = 0
        for _e in reversed(symtab.entries):
            if isinstance(_e, tuple) and len(_e) == 2 and _e[0] == "SYMBOL" and str(_e[1]).upper() == "-LAMBDA-":
                _trailing_lam += 1
            else:
                break
        # 仅单 kwote（恰好 1 个末尾 `-lambda-`）用统一偏移补偿（i18n 实测
        # gvar 槽 - 2）。多 kwote（≥2）`-lambda-` 穿插/多槽时统一偏移会
        # 整体错位 → CAD 加载报"参数太少"/类型错误，此时 offset=0（gvar 槽 - 1，
        # platform-api 双 kwote 实测 GETVAR fg[131]→USUBR 130 正确）。
        if _trailing_lam == 1 and _trailing_lam == nsyms - codegen_nsyms:
            offset = 1
    try:
        from core.fas_core import build_mvar_tables

        rg, fg = build_mvar_tables(seg1, nsyms)
    except Exception:
        return seg0
    # 符号与字符串分表：`fg` 表里 SYMBOL `>` 与 STRING `">"` 可能同 key
    # （符号大写、字符串大小写敏感），单一 gvar_map 靠 setdefault 先到先得，
    # 若字符串先注册会占用符号槽，USUBR/FUNC 引用指向字符串 → CAD
    # `(">" 24.1 20.1)` ill-fun。符号用 gvar_map（优先于字符串），字符串用
    # str_map（符号 `>` 与字符串 `">"` 各自独立槽，互不抢占）。
    gvar_map: dict = {}
    str_map: dict = {}
    for idx, v in enumerate(fg):
        if isinstance(v, tuple) and len(v) == 2 and v[0] in ("SYMBOL", "STRING"):
            # 符号名统一大写（AutoLISP 大小写不敏感）；字符串大小写敏感
            # （base-function 实测 `"date"`（timestamp）与 `"DATE"`（sleep）
            # 是两个不同槽，`.upper()` 会错误合并）。
            key = str(v[1]).upper() if v[0] == "SYMBOL" else str(v[1])
            if v[0] == "SYMBOL":
                # 符号优先：仅当 key 空或已被字符串占用时才写入；符号之间
                # 保持先到先得（递归函数名有重复槽，语义与旧 setdefault 一致）。
                prev = gvar_map.get(key)
                if prev is None or not (
                    isinstance(prev, int)
                    and 0 <= prev < len(fg)
                    and isinstance(fg[prev], tuple)
                    and fg[prev][0] == "SYMBOL"
                ):
                    gvar_map[key] = idx
            else:
                str_map.setdefault(key, idx)
    # `command` 内建 SUBR 在资源段注册名为 `ads-cmd`（base-function CAD 实测），
    # symtab 收集的符号名是 `command`。别名对齐使 FUNC/USUBR 分支能命中。
    if "ADS-CMD" in gvar_map:
        gvar_map.setdefault("COMMAND", gvar_map["ADS-CMD"])
    # 实数常量：codegen 用 symtab REAL 槽（可能偏离资源段 GVARINIT 槽，
    # base-function 实测 0.001 在 symtab 174 而 fg[130]），按值匹配映射。
    real_map: dict = {}
    for idx, v in enumerate(fg):
        if isinstance(v, tuple) and len(v) == 2 and v[0] == "REAL":
            real_map.setdefault(_real_fmt(float(v[1])), idx)
    # 资源流注册序（symbol_slots）：PUSH_G 字符串/表外符号的操作数 = 其在
    # symbol_slots 中的索引（CAD 实测）。此前字符串回退用 `nsyms-1` 硬编码，
    # 对多 kwote 文件（`-lambda-` 参数混入 func_args 使 multi=True）会越界
    # 错槽（platform-api/test-2kwote 的 `"platform"` 在 slot 6 而非末尾，
    # 被改成 nsyms-1=8 → CAD 加载报 `-lambda-` 类型错误）。改用真实注册序。
    _res_symbol_slots: List[str] = []
    try:
        from core.fas_core import parse_resource_stream as _prs

        _ritems, _rsyms, _rstrs = _prs(seg1)
        for _rit in _ritems:
            # symbol_slots = SYMBOL/STRING/REAL 三类（与 decompiler 一致）；
            # 漏 REAL 会使后续索引整体偏 1（platform-api `0.5` REAL 项实测）。
            if isinstance(_rit, tuple) and len(_rit) == 2 and _rit[0] in ("SYMBOL", "STRING", "REAL"):
                _res_symbol_slots.append(str(_rit[1]))
    except Exception:
        _res_symbol_slots = []
    # 末次出现索引（精确 + 大小写不敏感）预计算：`_res_slot_of` 原来每次线性扫描。
    _res_last_exact: dict = {}
    _res_last_upper: dict = {}
    for _i, _v in enumerate(_res_symbol_slots):
        _res_last_exact[_v] = _i
        _res_last_upper[_v.upper()] = _i

    def _res_slot_of(value: str) -> Optional[int]:
        """字符串/符号在资源 symbol_slots 中的索引；未找到返回 None。

        返回**最后一个**出现位置：资源流先注册模块区符号（函数名 + 顶层
        表达式符号），后注册函数体符号（fg 表）。函数体 PUSH_G/PUSH_VALUE
        引用的是 fg 表槽，符号同时出现在模块区与函数体区时（如顶层变量
        `@::*offline-mode*` 在 net/uri.lsp 的 symslot[3] 模块区 + [57] 函数
        体区，nsyms=25）必须取函数体区槽（57 ≥ nsyms → CAD 用 nsyms-1）；
        取模块区槽（3）会算出 3-1=2 的错误操作数。仅出现在模块区（函数名
        等）的符号在函数体区无槽位，取末次=模块区槽，语义不变。

        大小写：先精确匹配（字符串大小写敏感，`"date"`/`"DATE"` 异槽），
        未命中再做不区分大小写匹配（`0x56` 保留大小写块 `_al-bind-alist`/
        `kwote`/`ads-cmd` 以源码大小写入 symbol_slots，而查询方 `_best[0]`/
        `str(name).upper()` 传大写——log.lsp 实测 `_res_slot_of("_AL-BIND-ALIST")`
        精确匹配 None → `_res_offset` 变 None → 表外符号回退 nsyms-1 错槽；
        符号查大小写不敏感，字符串精确命中不受影响）。
        """
        _found: Optional[int] = _res_last_exact.get(value)
        if _found is None:
            _found = _res_last_upper.get(value.upper())
        return _found

    # 表外符号（DEFCODE module 参数等，如 cmd.lsp C:@U 的 `@::upgrade`）：
    # 其在资源 symbol_slots 的索引含模块区偏移（cmd.lsp @::UPGRADE slot 104
    # vs 实际 fg 槽 94，偏移 10 = 模块注册区符号数）。用 gvar_map 中 **fg 槽
    # 最大**（函数体区末尾）符号的（_res_slot_of - fg 槽）差推出偏移，表外
    # 符号 fg 槽 = _res_slot_of - 偏移。模块区函数名（fg 低位）偏移小
    # （C:@M slot9-gvar2=7），不可用。
    _res_offset: Optional[int] = None
    _best = None
    for _gs, _gv in gvar_map.items():
        if _gs in ("T", "NIL"):
            continue
        if _best is None or _gv > _best[1]:
            _best = (_gs, _gv)
    _best_res = None
    if _best is not None:
        _ri = _res_slot_of(_best[0])
        if _ri is not None:
            _res_offset = _ri - _best[1]
            _best_res = _ri

    def _const_leaves(v):
        """fg 表 const 结构 → 叶子符号名列表（SYMBOL/STRING）。"""
        if isinstance(v, tuple) and len(v) == 2 and v[0] in ("SYMBOL", "STRING"):
            return [str(v[1])]
        if isinstance(v, tuple):
            _out = []
            for _sub in v:
                if isinstance(_sub, tuple):
                    _out.extend(_const_leaves(_sub))
            return _out
        return []

    # fg 表里的 const（quoted 数据）折叠多个 res 槽为一个 fg 槽（net/module
    # `_al-bind-alist '(entry now)` 的 ENTRY/NOW 占 res[110,111]、fg[98] 一个
    # 槽），使 `_res_offset` 在 const 之后失效（MOD-SYM res[112]-12=100，
    # CAD 用 fg[99]=112-13）。记录每个 const 的（res 位置, 叶子数），目标符号
    # res 槽在 const 之后时按叶子数-1 补偏移。
    _const_collapse = []
    for _i, _v in enumerate(fg):
        if isinstance(_v, tuple) and not (
            len(_v) == 2 and _v[0] in ("SYMBOL", "STRING", "REAL", "CONS", "FUNC")
        ):
            _leaves = _const_leaves(_v)
            if len(_leaves) > 1:
                _cpos = _res_slot_of(str(_leaves[0]).upper())
                if _cpos is not None:
                    _const_collapse.append((_cpos, len(_leaves)))

    def _res_to_fg(rs: int) -> int:
        """资源 symbol_slots 索引 → fg 槽（`_res_offset` + const 折叠补偿）。

        const（quoted 数据）折叠多个 res 槽为一个 fg 槽（net/module
        `(entry now)` 占 res[110,111]、fg[98] 一槽），目标 res 槽在 const 之后
        时偏移 +（叶子数-1）。`gvar_slot_res`/表外符号/字符串 fallback 共用。"""
        _off = _res_offset or 0
        if _best_res is not None:
            for _cpos, _lcount in _const_collapse:
                if _best_res < _cpos < rs:
                    _off += _lcount - 1
        return rs - _off

    def _strip_list_markers(v):
        """symtab 常量结构 → fg 表可比较形式（规范化大小写/INT/REAL/LIST）。

        fg 表里 BUILD_LIST 结果为裸内容元组（无 `'LIST'` 前缀），符号大写、
        整数为裸 int、实数裸 float；symtab CONST entry 保留 `('LIST', items)`、
        `('SYMBOL', name)`、`('INT', v)` 等标记。递归转换以便结构匹配。
        """
        if isinstance(v, tuple) and len(v) == 1 and v[0] == "NIL":
            # fg 表里 NIL（PUSH_NIL 内联）表示为 None（build_mvar_tables
            # `op 0x00/0x01` → stack.append(None)），symtab 常量保留
            # `('NIL',)` 标记——结构匹配须归一化为 None，否则 quoted lambda
            # 含 NIL 参数时 const_map 查不到 → PUSH_G 落 nsyms-1（net/headers
            # @::set-timeouts `'(lambda () ...)` 的 `('NIL',)` 实测）。
            return None
        if isinstance(v, tuple) and len(v) == 2:
            if v[0] == "LIST":
                if not v[1]:
                    # 空列表 `()`：CAD 编码为 nil（fg 表 None，build_mvar_tables
                    # `0x00/0x01` → None），结构匹配归一化为 None（setup 的
                    # quoted const `(setq s::startup nil)` 实测）。
                    return None
                return tuple(_strip_list_markers(i) for i in v[1])
        if isinstance(v, tuple) and len(v) == 3 and v[0] == "LIST" and v[2]:
            # dotted 引用 `'(a . b)`：symtab 常量 `('LIST', (a, b), True)`，fg 表
            # 用 `('CONS', a, b)` 表示（build_mvar_tables `0x2A` 操作）——结构匹配
            # 须归一化为 CONS，否则 const_map 失配 → PUSH_G 落 nsyms-1
            # （cn-commands `'((:vlr-unknownCommand . parse-cmdunknown))` 实测）。
            _items = list(v[1])
            if len(_items) == 2:
                return ("CONS", _strip_list_markers(_items[0]), _strip_list_markers(_items[1]))
            return tuple(_strip_list_markers(i) for i in _items)
        if isinstance(v, tuple) and len(v) == 2:
            if v[0] == "SYMBOL":
                # 符号名统一大写，但 vla-/vlax- 与 VLISP 大小写保留符号保持
                # 原大小写（与 resource_builder._enc_sym 一致）：fg 表里这些
                # 符号保留源码大小写（net/headers `(lambda ... vlax-invoke ...)`
                # 的 vlax-invoke fg 槽小写），结构匹配若大写则 const_map 失配
                # → PUSH_G 落 nsyms-1。
                _sn = str(v[1])
                _lower = _sn.lower()
                from compiler.resource_builder import _VLISP_CASE_PRESERVE as _vcp

                for _canon in _vcp:
                    if _lower == _canon.lower():
                        return ("SYMBOL", _canon)
                if _lower.startswith(("vla-", "vlax-", ":vlax-", ":vla-")):
                    return ("SYMBOL", _sn)
                return ("SYMBOL", _sn.upper())
            if v[0] in ("INT", "INT8", "INT32"):
                return int(v[1])
            if v[0] == "REAL":
                return float(v[1])
            if v[0] in ("STRING", "T"):
                return v
        if isinstance(v, (list, tuple)):
            return tuple(_strip_list_markers(i) for i in v)
        return v

    # CONST 常量（quoted lambda/list 等）在 fg 表里注册为嵌套结构；用结构匹配
    # 建立 结构 → gvar 槽 映射，供 CONST 引用编址（i18n 实测 ANSI 表 fg[98]、
    # loc-file 单元素列表 fg[94]）。排除原子（SYMBOL/STRING/REAL/CONS/FUNC）。
    const_map: dict = {}
    for idx, v in enumerate(fg):
        if isinstance(v, tuple) and not (len(v) == 2 and v[0] in ("SYMBOL", "STRING", "REAL", "CONS", "FUNC")):
            const_map.setdefault(v, idx)
    if not gvar_map:
        return seg0
    from decompiler.fas4_decompiler import Disassembler

    # 大文件（nsyms>256）：CAD 用 5 字节 USUBR/FUNC（idx16 + flags=3），
    # 反汇编须用 short_subr=False；小文件保持 3 字节（与 golden 逐字节一致）。
    wide = nsyms > 256
    try:
        insts = Disassembler(short_subr=not wide).disassemble(seg0, nsyms, sym_count=len(symtab.entries))
    except Exception:
        return seg0

    def gvar_slot(name: str) -> int:
        # 资源段符号名已大写（_enc_sym），参数名为小写，查找时统一大写。
        # 返回 (槽位, 是否命中 gvar 表)。未命中返回 (nsyms, False)——CAD 对
        # 表外符号（参数/末尾常量等）按 gvar 槽 = nsyms 编址，此时才需减
        # offset 补偿 `-lambda-` 额外槽；命中 gvar 表的符号其槽位已含
        # `-lambda-` 偏移，不再减（net/cache.lsp 实测 body 符号 gvar-1、
        # 表外参数 nsyms-1-offset 并存）。
        _key = str(name).upper()
        _v = gvar_map.get(_key)
        if _v is not None:
            return _v, True
        return nsyms, False

    def gvar_slot_res(name: str):
        """gvar_slot + 表外符号按 `_res_offset` 编址（scheduler `name`
        symbol_slots[93] - 23 = fg 70 → 操作数 69，CAD 实测；旧 gvar_slot
        未命中回 nsyms-1=72 错槽）。命中 gvar 表或经 `_res_offset` 定位的
        槽位都视为"命中"（返回 True），调用方不再减 offset（`_res_offset`
        定位的 fg 槽已含全部符号，06_higher_order `lst` 13-1=12 实测）。"""
        _gs, _hit = gvar_slot(name)
        if _hit:
            return _gs, True
        if _res_offset is not None:
            _rs = _res_slot_of(str(name).upper())
            if _rs is not None:
                _af = _res_to_fg(_rs)
                if 0 <= _af < nsyms:
                    return _af, True
        return _gs, False

    def sym_of(idx: int):
        if 0 <= idx < len(symtab.entries) and symtab.entries[idx][0] in ("SYMBOL", "STRING"):
            v = symtab.entries[idx][1]
            # 符号名统一大写；字符串大小写敏感（`"date"`/`"DATE"` 异槽）。
            return str(v).upper() if symtab.entries[idx][0] == "SYMBOL" else str(v)
        return None

    # 每个内嵌 `-lambda-` 条目 → 它在所有 `-lambda-` 条目中的序号（0 起）。
    # CAD 立即调用/多 kwote 每个嵌套 lambda 独立槽：lambda i 的 gvar 槽 =
    # nsyms - i（t3=nsyms-1、t4=nsyms-2、t5=nsyms-3），PUSH_G 操作数 =
    # gvar 槽 - 1 = nsyms - 1 - i。
    lam_order: dict = {}
    _li = 0
    for _ei, _e in enumerate(symtab.entries):
        if _e[0] == "SYMBOL" and str(_e[1]).upper() == "-LAMBDA-":
            lam_order[_ei] = _li
            _li += 1
    # 含立即 lambda 的函数：源码序逆序覆盖 lam_order（safe-eval fn=_li 3 → 槽 62）。
    if nested_lambda_order:
        lam_order.update(nested_lambda_order)

    out = bytearray()
    multi = bool(func_args) and len(func_args) > 1
    # 按函数名解析 DEFUN 参数（robust）：外层 defun 经 symtab.function_offsets
    # 的 offset→name 定位，-lambda- DEFUN 归其所在函数。此前用全局 func_iter
    # 顺序对齐，@lisp_u 508 函数 + 多 kwote 时 _collect_kwote_lambda_args 与
    # codegen -lambda- 生成数不匹配导致 iter 错位（@::load-locale 参数被错配为
    # 他函数参数 → 体内符号全乱、CAD 加载报"参数太少"）。
    params_by_name = params_by_name or {}
    lambda_args_by_func = lambda_args_by_func or {}
    nested_lambda_args = nested_lambda_args or {}
    name_by_offset = {}
    for _n, _o in (symtab.function_offsets.items() if hasattr(symtab, "function_offsets") else []):
        name_by_offset[_o] = str(_n).upper()
    cur_args = None
    cur_func = None
    lambda_idx = 0
    arg_i = 0
    # 预建 `-lambda-` DEFUN offset → (cur_args, host_func) 映射：
    # 避免全局 lambda_idx 计数器被命名 DEFUN 重置后错位（log @::log-cleanup
    # 的嵌套 defun @684 重置 lambda_idx=0 → 后续 -lambda-@751 误取 [f] 而非 [a,b]）。
    _lambda_offset_map: dict = {}
    if func_nested_lambdas_raw:
        for _fname, _fnl_raw in func_nested_lambdas_raw.items():
            _fstart = None
            for _n, _o in (symtab.function_offsets.items() if hasattr(symtab, "function_offsets") else []):
                if str(_n).upper() == _fname.upper():
                    _fstart = _o
                    break
            if _fstart is None:
                continue
            for _rel_start, _rel_end, _la_args, _la_idx in _fnl_raw:
                _abs = _fstart + _rel_start
                _lambda_offset_map[_abs] = (_la_args, _fname.upper())
    # kwote lambda 的 `-lambda-` DEFUN 不注册 name_by_offset：进入时把宿主
    # 函数参数压栈，END_DEFUN 时弹出恢复——否则 lambda 结束后宿主函数体的
    # 参数读取（PUSH_VALUE mod-sym 等）仍用 lambda 的 cur_args（net/module
    # @::handle-module-failure 内嵌 0 参 lambda 后 `(vl-remove mod-sym ...)`
    # 的 mod-sym 读取被误走通用符号映射 → 99 错槽，CAD 用 98）。
    _arg_stack: list = []
    for inst in insts:
        new_idx: Optional[int] = None
        # 嵌套 `(defun inner ...)` 注册 PUSH_G <func-obj>：funcobj_map 把
        # codegen 的 FUNCOBJ 占位槽重映射为资源流 func-obj 槽（前置 DEFCODE
        # 位置，`nsyms - n_pre + pos`）。先于 gvar_map 处理（func-obj 不是
        # 普通符号槽）。
        if funcobj_map and inst.op_name == "PUSH_G" and inst.size == 3 and inst.operands:
            _foi0 = inst.operands[0]
            if _foi0 in funcobj_map:
                _ni = funcobj_map[_foi0]
                if 0 <= _ni <= 0xFFFF:
                    out += bytes([0x09, _ni & 0xFF, (_ni >> 8) & 0xFF])
                    continue
        if inst.op_name == "DEFUN":
            # 顶层 setq-lambda（top_lambda_args）的 `-lambda-` DEFUN：lambda_idx
            # 是跨顶层 lambda 的全局计数器（第二个 lambda 用 top_lambda_args[1]），
            # END_DEFUN 时**不得**恢复（4aeeb2b 的 `_arg_stack` 保存/恢复 lambda_idx
            # 使第二个顶层 lambda 误取 top_lambda_args[0] → setq-lambda.lsp 参数
            # 绑定/读取槽错 3）。命名 defun / 宿主函数内嵌 lambda 仍恢复。
            _was_tl = bool(top_lambda_args and (cur_func is None or cur_func == "-LAMBDA-"))
            _arg_stack.append((cur_args, arg_i, cur_func, lambda_idx, _was_tl))
            fname = name_by_offset.get(inst.offset)
            if fname is not None:
                cur_func = fname
                cur_args = params_by_name.get(fname)
                lambda_idx = 0
            else:
                # 混合文件顶层 setq-lambda（提升为 defun，func_offsets 用
                # `-lambda-` 键）：按 seg0 offset 查原函数名解析参数。
                if top_lambda_offsets and inst.offset in top_lambda_offsets:
                    _orig = top_lambda_offsets[inst.offset]
                    cur_args = params_by_name.get(str(_orig).upper()) if params_by_name else None
                    cur_func = None
                    lambda_idx = 0
                else:
                    # 内嵌 `-lambda-` DEFUN：优先用预建 offset 映射（精确，
                    # 不受命名 DEFUN 重置 lambda_idx 影响），回退到
                    # nested_lambda_args/lambda_args_by_func 索引。
                    if inst.offset in _lambda_offset_map:
                        cur_args, cur_func = _lambda_offset_map[inst.offset]
                    elif top_lambda_args and (cur_func is None or cur_func == "-LAMBDA-"):
                        _la = top_lambda_args
                        cur_args = _la[lambda_idx] if lambda_idx < len(_la) else None
                    else:
                        _la = nested_lambda_args.get(cur_func, []) if cur_func else []
                        if not _la:
                            _la = lambda_args_by_func.get(cur_func, []) if cur_func else []
                        cur_args = _la[lambda_idx] if lambda_idx < len(_la) else None
                    lambda_idx += 1
            arg_i = 0
        elif inst.op_name == "END_DEFUN":
            if _arg_stack:
                _pushed_args, _pushed_arg_i, _pushed_func, _pushed_lam, _was_tl = _arg_stack.pop()
                cur_args, arg_i, cur_func = _pushed_args, _pushed_arg_i, _pushed_func
                if not _was_tl:
                    lambda_idx = _pushed_lam
        # 参数绑定 PUSH_G（DEFUN 后 argc 个，仅多函数）
        if (multi or top_lambda_args) and inst.op_name == "PUSH_G" and cur_args is not None and arg_i < len(cur_args):
            arg = cur_args[arg_i]
            _gs, _hit = gvar_slot_res(arg)
            new_idx = _gs - 1 - (0 if _hit else offset)
            if 0 <= new_idx <= 0xFFFF:
                out += bytes([0x09, new_idx & 0xFF, (new_idx >> 8) & 0xFF])
                arg_i += 1
                continue
        # 参数读取 PUSH_VALUE（仅多函数）
        elif multi and inst.op_name == "PUSH_VALUE" and inst.size == 3 and cur_args is not None and inst.operands:
            idx = inst.operands[0]
            # 多函数参数读取：codegen 用参数真实符号槽（get_or_add）发射，
            # 凭 sym_of(idx) 是否在 cur_args 识别（此前用 codegen_nsyms-argc+i
            # 占位，会与真实符号槽碰撞——lambda_body 实测 `t` 槽 == 占位值，
            # 被误判为参数 → "函数错误: nil"）。非参数（如 `t`）走常规符号映射。
            _sym = sym_of(idx)
            if _sym and cur_args and _sym in [a.upper() for a in cur_args]:
                i = [a.upper() for a in cur_args].index(_sym)
                if 0 <= i < len(cur_args):
                    arg = cur_args[i]
                    _gs, _hit = gvar_slot_res(arg)
                    new_idx = _gs - 1 - (0 if _hit else offset)
                    if 0 <= new_idx <= 0xFFFF:
                        out += bytes([0x03, new_idx & 0xFF, (new_idx >> 8) & 0xFF])
                        continue
        # 参数写入 SETQ_G（仅多函数）：与参数读取同规则。codegen 对参数
        # `(setq param ...)` 用 symtab.get_or_add(param) 发射（record.lsp
        # `(setq lib-name (read lib-name))` 实测 symtab 槽 32），但参数符号
        # 不注册于资源 fg 表（符号槽末尾，gvar 槽 = nsyms），须按
        # gvar_slot(arg) - 1 重映射（CAD 实测 `SETQ_G[30]` = nsyms-1）。
        elif multi and inst.op_name == "SETQ_G" and inst.size == 3 and cur_args is not None and inst.operands:
            idx = inst.operands[0]
            _sym = sym_of(idx)
            if _sym and cur_args and _sym in [a.upper() for a in cur_args]:
                i = [a.upper() for a in cur_args].index(_sym)
                if 0 <= i < len(cur_args):
                    arg = cur_args[i]
                    _gs, _hit = gvar_slot_res(arg)
                    new_idx = _gs - 1 - (0 if _hit else offset)
                    if 0 <= new_idx <= 0xFFFF:
                        out += bytes([0x06, new_idx & 0xFF, (new_idx >> 8) & 0xFF])
                        continue
        # 其余符号引用：统一用 gvar 槽 - 1。多函数的普通符号走 gvar_map；
        # CONST/STRING 常量引用（PUSH_G 操作数 = gvar 槽 - 1）在单函数
        # 也需修正（codegen 原始槽 = symtab idx，gvar 槽 = idx+1，
        # 操作数 = idx——i18n_v2 实测 ANSI 表 symtab idx 4 → 操作数 3）。
        # 注意：CAD stub 中调用后的占位 PUSH_VALUE[0] 是单字节 `03`（size=1），
        # 并非符号引用，必须跳过，否则被扩展成 3 字节破坏字节一致性。
        if inst.op_name in ("PUSH_VALUE", "PUSH_G", "SETQ_G") and inst.operands and inst.size == 3:
            # 参数绑定 PUSH_G（DEFUN 后 argc 个）：多函数由上方分支修正并
            # continue（不到此处）；单函数 codegen 已输出正确槽（nsyms-1）。
            # 此处跳过，避免被当作 CONST/STRING 误改。
            is_arg_bind = inst.op_name == "PUSH_G" and cur_args is not None and arg_i < len(cur_args)
            if is_arg_bind:
                arg_i += 1
                out += seg0[inst.offset : inst.offset + inst.size]
                continue
            if multi:
                # 字符串（如 `"OFFLINE"`）必须走 str_map（大小写敏感），不能
                # 经 gvar_map——否则与同名符号（net/probe `"OFFLINE"` vs
                # 符号 OFFLINE）冲突，映射到符号槽（fg[11] → 操作数 10）而非
                # 字符串槽（fg[9] → 操作数 8，CAD 实测）。
                if (
                    0 <= inst.operands[0] < len(symtab.entries)
                    and symtab.entries[inst.operands[0]][0] == "STRING"
                    and inst.op_name in ("PUSH_G", "PUSH_VALUE", "SETQ_G")
                ):
                    _sv = str(symtab.entries[inst.operands[0]][1])
                    if _sv in str_map:
                        new_idx = str_map[_sv] - 1
                        if 0 <= new_idx <= 0xFFFF:
                            if inst.op_name == "PUSH_VALUE" and new_idx == 0 and not wide:
                                out += bytes([0x03])
                            else:
                                opcode = {"PUSH_VALUE": 0x03, "PUSH_G": 0x09, "SETQ_G": 0x06}[inst.op_name]
                                out += bytes([opcode, new_idx & 0xFF, (new_idx >> 8) & 0xFF])
                            continue
                sym = sym_of(inst.operands[0])
                if sym and sym in gvar_map:
                    new_idx = gvar_map[sym] - 1

                    if 0 <= new_idx <= 0xFFFF:
                        if inst.op_name == "PUSH_VALUE" and new_idx == 0 and not wide:
                            out += bytes([0x03])
                        else:
                            opcode = {"PUSH_VALUE": 0x03, "PUSH_G": 0x09, "SETQ_G": 0x06}[inst.op_name]
                            out += bytes([opcode, new_idx & 0xFF, (new_idx >> 8) & 0xFF])
                        continue
                if sym == "-LAMBDA-":
                    # kwote/立即调用内嵌 `-lambda-`：不参与资源段符号注册，按
                    # 其在所有 `-lambda-` 条目中的序号编址（lambda i 槽 =
                    # nsyms - i，操作数 = nsyms - 1 - i；i18n-cad 单 kwote
                    # 实测 `PUSH_G[91]`，nsyms=92；lambda_body 多 lambda
                    # 实测 t3→18、t4→17、t5→16，nsyms=19）。
                    # 含嵌套 defun 时 func-obj 与 `-lambda-` 共享高位槽区，
                    # 须按 `_pre_all` 位置编址（lambda_slot_map，slot =
                    # nsyms - n_pre + pos；string-utils s2la=93 → lambda
                    # 92/91）。旧公式 `nsyms-1-_li` 未计入 func-obj 槽，
                    # lambda 与 func-obj 槽冲突错 1。
                    _ls = lambda_slot_map.get(inst.operands[0]) if lambda_slot_map else None
                    if _ls is not None:
                        # lambda_slot_map 存 gvar 槽（= `_fo_base + pos`，与 func-obj
                        # 槽同规则）；PUSH_G 操作数 = 槽本身（CAD string-utils 实测
                        # s2la=93、lambda=92/91 直接作操作数，funcobj_map 同）。
                        new_idx = _ls
                    else:
                        _li = lam_order.get(inst.operands[0], 0)
                        new_idx = nsyms - 1 - _li
                    if 0 <= new_idx <= 0xFFFF:
                        if inst.op_name == "PUSH_VALUE" and new_idx == 0 and not wide:
                            out += bytes([0x03])
                        else:
                            opcode = {"PUSH_VALUE": 0x03, "PUSH_G": 0x09, "SETQ_G": 0x06}[inst.op_name]
                            out += bytes([opcode, new_idx & 0xFF, (new_idx >> 8) & 0xFF])
                        continue
            # 常量引用（quoted lambda 等 CONST 条目）：sym_of 只认 SYMBOL/STRING，
            # CONST 在 fg 表里注册为嵌套结构（gvar 槽 = const_map 命中槽），
            # PUSH_G 操作数 = gvar 槽 - 1（i18n 实测 ANSI 表 fg[98] → 操作数 97）。
            # 字符串（不在 GVARINIT 表）：函数体字符串注册于符号槽末尾
            # （gvar 槽 = nsyms），PUSH_G 操作数 = gvar 槽 - 1 = nsyms - 1
            # （t15 实测 idx 8 → 槽 6、t10 混合模式 idx 8 → 槽 3，nsyms 分别为 7/4）。
            idx0 = inst.operands[0]
            # 参数读取 PUSH_VALUE 的槽（nsyms-argc .. nsyms-1）不是 entry 索引，
            # 单函数 codegen 已输出正确槽，跳过（i18n_v2 实测 offset14 参数读取）。
            # 顶层 `-lambda-`（top_lambda_args）：CAD 用 gvar 槽 - 1 编址
            # （@::vlx 参数 str-vlx fg[9] → 操作数 8），须重映射。
            if (
                inst.op_name == "PUSH_VALUE"
                and cur_args is not None
                and len(cur_args)
                and nsyms - len(cur_args) <= idx0 < nsyms
            ):
                if top_lambda_args:
                    # codegen `-lambda-` 参数读取约定：单 lambda（net/wget，1 个
                    # 顶层 lambda）用 `nsyms-1-slot`（源码第 i 个参数 → 槽
                    # nsyms-1-i，uri/outfile/extra-headers → 30/29/28，idx0 越大
                    # 参数越靠前）；多 lambda（setq-lambda，2 个）用真实符号槽
                    # `get_or_add`（idx0 - (nsyms-len) 直接索引 cur_args）。
                    if len(top_lambda_args) == 1:
                        _pi = (nsyms - 1) - idx0
                    else:
                        _pi = idx0 - (nsyms - len(cur_args))
                    _arg = cur_args[_pi] if 0 <= _pi < len(cur_args) else None
                    if _arg:
                        _gs, _hit = gvar_slot(_arg)
                        _ni = _gs - 1 - (0 if _hit else offset)
                        if 0 <= _ni <= 0xFFFF:
                            out += bytes([0x03] if (inst.op_name == "PUSH_VALUE" and _ni == 0 and not wide) else [0x03, _ni & 0xFF, (_ni >> 8) & 0xFF])
                            continue
                out += seg0[inst.offset : inst.offset + inst.size]
                continue
            if 0 <= idx0 < len(symtab.entries):
                etype = symtab.entries[idx0][0]
                if etype == "CONST":
                    const_structure = symtab.entries[idx0][1]
                    # quoted 单符号 `'sym`：作为符号引用，按 gvar 槽编址
                    # （i18n 实测 `'sym` → SYM 的 gvar 槽；CAD quoted symbol）。
                    if (
                        isinstance(const_structure, tuple)
                        and len(const_structure) == 2
                        and const_structure[0] == "SYMBOL"
                    ):
                        gslot = gvar_map.get(str(const_structure[1]).upper())
                        if gslot is not None:
                            new_idx = gslot - 1
                        else:
                            # 表外 quoted 单符号：注册于符号槽末尾（gvar 槽 =
                            # nsyms，操作数 = nsyms-1）。旧公式 idx0-nfuncs+1
                            # 对大文件（deferred const 区）越界（cache/audit 等
                            # kernel 文件实测 PUSH_G 69/105 ≥ nsyms）。
                            new_idx = nsyms - 1 - offset
                    else:
                        fgstruct = _strip_list_markers(const_structure)
                        gslot = const_map.get(fgstruct)

                        if gslot is not None:
                            new_idx = gslot - 1
                        else:
                            # `_al-bind-alist` 的 locals 常量 `(quote (loc1 ...))`：
                            # 常量 gvar 槽 = `_al-bind-alist` 槽 + 1（t11_localvars
                            # CAD 实测 fg[6]=_al-bind-alist、常量 PUSH_G=6；net/proxy
                            # fg[32]=_al-bind-alist、常量 PUSH_G=32），即 PUSH_G
                            # 操作数 = `_al-bind-alist` 槽。该常量仅在资源流注册
                            # 位置（紧随 `_al-bind-alist`）有意义；build_mvar_tables
                            # 对内嵌 `-lambda-` 的 DEFCODE 会消耗常量，const_map
                            # 查不到 → 需按此关系编址，否则 `nsyms-1` 回退偏移 2
                            # （net/proxy.lsp 实测 OURS 34 vs CAD 32）。
                            if (
                                isinstance(const_structure, tuple)
                                and len(const_structure) == 2
                                and const_structure[0] == "LIST"
                                and isinstance(const_structure[1], (list, tuple))
                                and all(
                                    isinstance(x, tuple)
                                    and len(x) == 2
                                    and x[0] == "SYMBOL"
                                    # locals 常量叶子是普通标识符；quoted 数据列表
                                    # 的 `:keyword` 叶子（audit `'(:package.install
                                    # ...)` 截断为 `:package`）**不**是 locals const。
                                    and not str(x[1]).startswith(":")
                                    for x in const_structure[1]
                                )
                            ):
                                _al_slot = gvar_map.get("_AL-BIND-ALIST")
                                if _al_slot is not None:
                                    # 常量 gvar 槽 = `_al-bind-alist` 槽（资源注册序，
                                    # 不随 `-lambda-` 偏移；t11 _al_slot=6 → PUSH_G 6、
                                    # net/proxy _al_slot=32 → 32）。锁 lock.lsp kwote
                                    # offset=1 时 `- offset` 会错成 100（CAD 用 101）。
                                    new_idx = _al_slot
                                    if 0 <= new_idx <= 0xFFFF:
                                        out += bytes(
                                            [0x09, new_idx & 0xFF, (new_idx >> 8) & 0xFF]
                                        )
                                        continue
                            # 未命中 fg 的常量结构（deferred 字节区间引用，
                            # kernel 大文件 `_al-bind-alist '(dir)` 等实测）：
                            # CAD 注册于符号槽末尾，操作数 = nsyms-1
                            # （cache_cad.fas 实测 PUSH_G[60] = nsyms-1）。
                            # 旧公式 idx0-len(func_args)+1 会越界。
                            # 含多叶子的 deferred const（audit `'(:package.install
                            # ...)` 18 个 `:package` 截断关键字占 res 128-145、
                            # fg 一槽；safe-eval 白名单 `'(car cdr ...)` const）：
                            # 按 const 叶子**序列**在资源流中匹配起始位置 `_res_to_fg`
                            # 编址（safe-eval CAR 体引用 res60 不匹配序列 → 落在
                            # const 块 res70 → fg 62 → 操作数 61；audit `:PACKAGE`
                            # 首现 res 128 - 21 = fg 107 → 106）。单叶子/首叶子
                            # 匹配会误取普通符号引用，须全序列匹配。
                            _cl = _const_leaves(const_structure)
                            _mapped = None
                            if _cl and _res_offset is not None and len(_cl) > 1:
                                _lens = [str(l).upper() for l in _cl]
                                _res_upper = [str(v).upper() for v in _res_symbol_slots]
                                for _p in range(len(_res_upper) - len(_lens) + 1):
                                    if _res_upper[_p : _p + len(_lens)] == _lens:
                                        _fg_c = _res_to_fg(_p)
                                        if 0 <= _fg_c < nsyms:
                                            _mapped = _fg_c - 1 - offset
                                        break
                            if _mapped is not None:
                                new_idx = _mapped
                            else:
                                new_idx = nsyms - 1 - offset
                elif etype == "STRING":
                    # 字符串 PUSH_G：多函数若字符串已在 GVARINIT 表（fg 含 STRING
                    # 项，i18n 实测 `""` fg[44] → 操作数 42 = gvar-1-offset）则按
                    # gvar 槽映射；否则（单函数/表外）注册于符号槽末尾
                    # （gvar 槽 = nsyms，操作数 = nsyms-1，t15 实测）。
                    strval = symtab.entries[idx0][1]
                    # 字符串大小写敏感（`"date"`/`"DATE"` 异槽）。emoji 等 GBK
                    # 无法编码字符在资源流注册为 `\U+XXXX` 转义（`_enc_with_escape`，
                    # user-manager `"\n✅ "` → fg `\n\U+2705 `），symtab 保留实际
                    # 字符——查询须同样转义才能命中 str_map（否则 fallback
                    # nsyms-1 错槽）。
                    from compiler.resource_builder import ResourceBuilder as _RB

                    gkey = _RB._enc_with_escape(str(strval))
                    if gkey in str_map:
                        new_idx = str_map[gkey] - 1
                    else:
                        # 表外字符串：优先用资源 symbol_slots 真实索引（platform-api
                        # `"platform"` 在 nsyms 内时 CAD 用真实槽），但该索引
                        # **必须在 gvar 范围内**（t14_command `"Hello from command!"`
                        # 槽 7 ≥ nsyms 6、t10_init `"Hello from lib!"` 槽 8 ≥ nsyms 4
                        # CAD 实测都用 nsyms-1）——越界的函数体字符串按符号槽末尾
                        # 编址（gvar 槽 = nsyms，操作数 = nsyms-1）。
                        _rslot = _res_slot_of(strval)
                        if _rslot is not None and _rslot < nsyms:
                            new_idx = _rslot - 1 - offset
                        elif _res_offset is not None and _rslot is not None:
                            # 表外字符串（init/steps `"flag-nomnl"` symbol_slots[113]
                            # 偏移 6 → fg 107 → 操作数 106，CAD 实测）：同表外符号
                            # 规则 `_rslot - _res_offset`。旧 fallback nsyms-1 偏移 5。
                            _fg_str = _res_to_fg(_rslot)
                            if 0 <= _fg_str < nsyms:
                                new_idx = _fg_str - 1 - offset
                            else:
                                new_idx = nsyms - 1 - offset
                        else:
                            new_idx = nsyms - 1 - offset
                else:
                    # 函数体符号（SYMBOL 且不在 GVARINIT 表——fg 表）：
                    # CAD 对 PUSH_G/PUSH_VALUE/SETQ_G 也用 `gvar 槽 - 1`
                    # （hkrepro 实测 item→1、sym→9 = fg[2]/fg[10] 的 gvar-1）。
                    # 此前仅 USUBR/FUNC 走此映射，单函数普通符号引用（foreach
                    # 循环变量、quoted 符号）保留 symtab 槽——有顶层 form 时
                    # symtab 槽与资源段 gvar 槽错位，CAD 报 `函数错误: :DIALOG`。
                    _sym = sym_of(idx0)
                    if _sym and _sym in gvar_map:
                        new_idx = gvar_map[_sym] - 1
                    elif (
                        inst.op_name == "SETQ_G"
                        and _sym
                        and cur_args
                        and any(str(a).lower() == _sym.lower() for a in cur_args)
                    ):
                        # net/wget 纯顶层 setq-lambda 参数（DEFCODE 第二区，
                        # gvar 槽 = nsyms 表外）：SETQ_G 目标操作数 = gvar_slot
                        # - 1（表外参数 = nsyms-1，uri → 30；与参数读取 PUSH_VALUE
                        # 同规则，line 973）。setq-lambda 参数（str-vlx fg[9]）
                        # 走 gvar_slot 命中分支结果相同（gvar-1）。
                        # **仅 SETQ_G**：PUSH_G 的同名符号是 quoted 值引用
                        # （string-utils @::to-type `(eq 'STR typep)` 的 'STR 与
                        # 参数 str 同名），不能当参数写槽（gvar_slot 未命中 →
                        # nsyms-1=93，CAD 用 deferred const 槽 90）。
                        _gs, _hit = gvar_slot(_sym)
                        new_idx = _gs - 1 - (0 if _hit else offset)
                    else:
                        # 不在 GVARINIT 表（fg）的符号（如 quoted 数据里的特殊
                        # 形式 `setq`/`if`/`lambda` 等，@lisp_u safe-form-p 立即
                        # 应用 lambda 逐元素构建实测）：这些符号注册于资源流
                        # symbol_slots 高位（可能 > nsyms）。CAD 对这些 quoted
                        # 数据用 CONST 整体引用（无独立 PUSH_G），我们逐元素
                        # 构建时须编址到符号槽末尾（gvar 槽 = nsyms，操作数 =
                        # nsyms-1），否则 PUSH_G 越界 → CAD 0xC0000005。
                        # 先查资源 symbol_slots 是否命中 < nsyms 的有效槽。
                        _rs = _res_slot_of(str(_sym)) if _sym else None
                        if _rs is not None and _rs < nsyms:
                            new_idx = _rs - 1 - offset
                        elif (
                            _rs is not None
                            and has_top_forms
                            and module_reg_count is not None
                            and _sym is not None
                            and _res_symbol_slots.count(str(_sym)) > 1
                            and 0 <= (_rs - module_reg_count - 1) < nsyms
                        ):
                            # 顶层变量在函数体引用（net/probe `@::*network-failure-count*`）：
                            # 符号同时注册于模块区（低位）与函数体区（高位 ≥ nsyms），
                            # 函数体引用用**函数体区槽** = 资源槽 - 模块注册数 - 1
                            # （fg[0] 为代码引用占位：res[108] - 11 - 1 = fg[96]，
                            # operand 95）；旧 fallback `nsyms-1` 偏移 2
                            # （build_mvar_tables 未把该符号放入 fg 表）。仅当
                            # 符号**双注册**（模块区 + 函数体区，count>1）时适用；
                            # 纯函数体符号（scheduler kwote lambda 捕获外层参数
                            # `name` 单注册 symbol_slots[93]）走下方 `_res_offset`
                            # 编址（93 - 23 = fg 70 → 操作数 69，CAD 实测）。
                            # 公式给出无效槽（≥ nsyms，如 panel.lsp BYTELEN 为
                            # /local 在 3 个函数体区各注册一次、非模块区双注册）
                            # 时落到 `_res_offset` 分支，否则 `nsyms-1` 错位 15。
                            _body_slot = _rs - module_reg_count - 1
                            new_idx = _body_slot - 1 - offset
                        else:
                            # 纯函数文件（无顶层表达式）表外符号：资源 symbol_slots
                            # 索引与 gvar 槽差固定偏移 `_res_offset`（= 末 fg 符号
                            # 的 _res_slot_of - fg 槽，init/steps FINDFILE
                            # symbol_slots[112] - fg[106] = 6；config/migrate
                            # STRCAT 偏移 12）。init/steps `"flag-nomnl"`
                            # symbol_slots[113] - 6 = fg 107 → 操作数 106、
                            # config/migrate `@::*prefix-config*` 118-12 = 106 →
                            # 105（CAD 实测）。旧 fallback `nsyms-1` 偏移 5/2。
                            if _res_offset is not None and _rs is not None:
                                _fg_ext = _res_to_fg(_rs)
                                if 0 <= _fg_ext < nsyms:
                                    new_idx = _fg_ext - 1
                                else:
                                    new_idx = nsyms - 1 - offset
                            else:
                                new_idx = nsyms - 1 - offset
                if etype == "REAL":
                    # 实数常量按值匹配资源段 REAL 槽（codegen symtab 槽可能
                    # 偏离 GVARINIT，base-function 实测 0.001 槽 174→fg[130]）。
                    # key 用 _real_fmt 规范化：资源流存 15 位（.15g），symtab
                    # 保留完整 float（`(/ 1.0 24.0)`=0.041666666666666664 vs
                    # 资源 `'0.0416666666666667'`），直接 float 比较会失配 → 越界。
                    _ridx = real_map.get(_real_fmt(float(symtab.entries[idx0][1])))
                    new_idx = (_ridx - 1) if _ridx is not None else None
                if new_idx is not None and 0 <= new_idx <= 0xFFFF:
                    if inst.op_name == "PUSH_VALUE" and new_idx == 0 and not wide:
                        out += bytes([0x03])
                    else:
                        opcode = {"PUSH_VALUE": 0x03, "PUSH_G": 0x09, "SETQ_G": 0x06}[inst.op_name]
                        out += bytes([opcode, new_idx & 0xFF, (new_idx >> 8) & 0xFF])
                    continue
        elif inst.op_name == "USUBR" and len(inst.operands) >= 2:
            argc, idx = inst.operands[0], inst.operands[1]
            flags = inst.operands[2] if len(inst.operands) >= 3 else 3
            sym = sym_of(idx)
            if sym and sym in gvar_map:
                new_idx = gvar_map[sym] - 1
                out += _subr_bytes(0x35, argc, new_idx, flags, wide=wide)
            elif sym and 0 <= idx < len(symtab.entries) and symtab.entries[idx][0] == "SYMBOL":
                # 符号槽末尾（超出 gvar 表，fg 仅 nsyms 项）的符号：CAD 按
                # gvar 槽 = nsyms 编址（t22 实测 vlax-get-acad-object 操作数 11 =
                # nsyms-1，符号槽末尾注册），USUBR 操作数 = nsyms - 1。但符号
                # 若在资源 symbol_slots 有真实索引（< nsyms，如 cmd.lsp C:@U 的
                # @::upgrade = symslot[94] 而 build_mvar_tables 把它当 DEFCODE
                # 模块参数解析为 None、gvar_map 查不到）则用真实槽
                # （操作数 = 94-1-offset = 93，CAD 实测）。
                _rslot = _res_slot_of(sym)
                if _rslot is not None:
                    _fg_slot = _rslot - (_res_offset or 0)
                    if 0 <= _fg_slot < nsyms:
                        # 表内符号（资源 5b 块注册、gvar 槽 < nsyms，但被
                        # DEFCODE 消费 → build_mvar_tables 解析为 None）：
                        # 操作数 = gvar 槽 - 1，**不含** offset（cmd.lsp
                        # @::upgrade fg 94→93、command @::internetp fg 150→149，
                        # 后者 gvar 槽恰 = nsyms-1）。
                        new_idx = _fg_slot - 1
                    else:
                        new_idx = nsyms - 1 - offset
                else:
                    new_idx = nsyms - 1 - offset
                if 0 <= new_idx <= 0xFFFF:
                    out += _subr_bytes(0x35, argc, new_idx, flags, wide=wide)
                else:
                    out += seg0[inst.offset : inst.offset + inst.size]
            else:
                out += seg0[inst.offset : inst.offset + inst.size]
            continue
        elif inst.op_name == "FUNC" and len(inst.operands) >= 2:
            # FUNC 第二个操作数为符号引用（gvar 槽 - 1，同 USUBR）。i18n 实测
            # `_al-bind-alist` 调用 FUNC[1,84]（gvar 槽 86 → 84，kwote offset=1）。
            argc, idx = inst.operands[0], inst.operands[1]
            flags = inst.operands[2] if len(inst.operands) >= 3 else 3
            sym = sym_of(idx)
            if sym and sym in gvar_map:
                new_idx = gvar_map[sym] - 1
                out += _subr_bytes(0x51, argc, new_idx, flags, wide=wide)
            elif sym and 0 <= idx < len(symtab.entries) and symtab.entries[idx][0] == "SYMBOL":
                # 同 USUBR：符号槽末尾（超出 gvar 表）的 FUNC 目标 gvar 槽 = nsyms。
                # 符号在资源 symbol_slots 有真实索引（< nsyms）时用真实槽（同
                # USUBR，cmd.lsp @::upgrade symslot[94] → 操作数 93）。
                _rslot = _res_slot_of(sym)
                if _rslot is not None:
                    _fg_slot = _rslot - (_res_offset or 0)
                    if 0 <= _fg_slot < nsyms:
                        # 同 USUBR：表内符号不含 offset。
                        new_idx = _fg_slot - 1
                    else:
                        new_idx = nsyms - 1 - offset
                else:
                    new_idx = nsyms - 1 - offset
                if 0 <= new_idx <= 0xFFFF:
                    out += _subr_bytes(0x51, argc, new_idx, flags, wide=wide)
                else:
                    out += seg0[inst.offset : inst.offset + inst.size]
            else:
                out += seg0[inst.offset : inst.offset + inst.size]
            continue
        out += seg0[inst.offset : inst.offset + inst.size]
    return bytes(out)


