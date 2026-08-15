import struct
from typing import List, Dict, Any, Tuple, Optional
from core.fas_core import get_ansi_encoding
from compiler.symbol_table import SymbolTable

# VLISP 内建/关键字符号：CAD 保留特定大小写（AutoCAD 实测 @lisp_u golden）。
# 这些符号在资源段不统一大写（AutoLISP 大小写不敏感规则对它们例外）。
_VLISP_CASE_PRESERVE = {
    ":vlax-false", ":vlax-true",
    ":VLR-beginDoubleClick", ":VLR-unknownCommand",
    "VLR-Add", "VLR-Command-Reactor", "VLR-Mouse-Reactor", "VLR-Remove",
    "VLAX-FOR", "vlax-3d-point",
    "end", "showhtmlmodalwindow", "sort", "startapp",
}


def resolve_encoding(enc: Optional[str]) -> str:
    """将 'ansi'/'auto'/'system' 解析为实际编码。"""
    if not enc or enc.lower() in ("ansi", "auto", "system"):
        return get_ansi_encoding()
    return enc


def res_u16(v: int) -> bytes:
    return struct.pack("<H", v)


def res_s32(v: int) -> bytes:
    return struct.pack("<i", v)


def res_int8(v: int) -> bytes:
    return bytes([0x32]) + struct.pack("<b", v)


def res_int32(v: int) -> bytes:
    return bytes([0x33]) + res_s32(v)


def res_real_str(s: str) -> bytes:
    return bytes([0x3B]) + s.encode("utf-8") + b"\x00"


def _real_fmt(v) -> str:
    """实数常量字符串：CAD 资源流 `3B <ascii>` 按实数解析。`.15g` 对整数值
    （如 2208988800.0）会输出 `2208988800`（无小数点），CAD 加载时当作整数
    fixnum 报"不适合 fixnum"——须补 `.0` 使其成为合法实数表示。"""
    s = f"{v:.15g}"
    if not any(c in s for c in ".eE"):
        s += ".0"
    return s


def res_gvar_init(var_pos: int, st_init: int) -> bytes:
    return bytes([0x43]) + res_u16(var_pos) + res_u16(st_init)


def res_func_triple() -> bytes:
    return bytes([0x3A])


def build_module_code(n_funcs: int = 1, top_level: bytes = b"", nsyms: int = 0) -> bytes:
    """生成 CAD 风格模块代码（seg1 尾部的模块入口）。

    CAD 把源码中的**顶层表达式**（defun 之外的 setq/set 等）编译进模块代码，
    seg0 只含 defun 函数。结构：

    ``DEFUN头 + [顶层表达式字节码] + 函数注册 + END_DEFUN``

    - 无 defun 时（n_funcs=0）：``DEFUN头 + 顶层表达式 + END_DEFUN``
    - 有 defun 时：``DEFUN头 + 顶层表达式 + JUMP + 函数注册 + END_DEFUN``

    多函数版本按每函数 ``PUSH_G <n+1-i> POP JUMP PUSH_G <b> SETQ_G <n-i>``
    生成。当 nsyms>0 时 b 上限为 nsyms-1，避免 PUSH_G 索引超出 gvar 表范围。
    """
    out = bytearray(b"\x14\x01\x00\x00\x00")
    out += top_level
    if n_funcs == 0:
        out += b"\x16"
        return bytes(out)
    if n_funcs <= 1:
        out += bytes.fromhex("0902000a570000000009030006010009010016")
        return bytes(out)
    b_start = 2 * n_funcs + 1
    for i in range(n_funcs):
        a = n_funcs + 1 - i
        b = b_start - i
        c = n_funcs - i
        out += b"\x09" + res_u16(a) + b"\x0a\x57\x00\x00\x00\x00"
        out += b"\x09" + res_u16(b) + b"\x06" + res_u16(c)
    out += b"\x09" + res_u16(1) + b"\x16"
    return bytes(out)


def build_command_module_code(n_funcs: int, vl_idx: int = 2) -> bytes:
    """生成 CAD 命令模块代码（c: 命令通过 vl-ACAD-defun 注册）。

    REF（t14_command，n=2）实测字节序：
    ``DEFUN | PUSH_G 4 POP JUMP0 | PUSH_G 6 SETQ_G 3 | PUSH_G 3 FUNC_REF 2
    PUSH_NIL POP | PUSH_G 3 POP JUMP0 | PUSH_G 5 SETQ_G 1 | PUSH_G 1 FUNC_REF 2
    PUSH_NIL POP | PUSH_G 1 END``

    每命令：``PUSH_G <a> POP JUMP0``（占位）+ ``PUSH_G <b> SETQ_G <c>``
    （把函数值放入目标槽）+ ``PUSH_G <c>; FUNC_REF <vl_idx>; PUSH_NIL; POP``
    （vl-ACAD-defun 注册）。

    槽位公式（n=2 与 golden 逐字节一致，n>2 按同一规律外推）：
    - ``var_pos = n_funcs + 3``（函数注册基址）
    - ``a = var_pos - 1 - i``，``b = var_pos + n_funcs - 1 - i``
    - ``c = n_funcs + 1 - i``（i < n-1），末个 ``c = 1``（对应尾部 PUSH_G 1）
    满足 a_i = c_{i-1}（i>=1）与末 c=1 的自我一致性。
    """
    var_pos = n_funcs + 3
    out = bytearray(b"\x14\x01\x00\x00\x00")
    for i in range(n_funcs):
        a = var_pos - 1 - i
        b = var_pos + n_funcs - 1 - i
        c = n_funcs + 1 - i if i < n_funcs - 1 else 1
        out += b"\x09" + res_u16(a) + b"\x0a\x57\x00\x00\x00\x00"
        out += b"\x09" + res_u16(b) + b"\x06" + res_u16(c)
        out += b"\x09" + res_u16(c) + b"\x35\x01" + res_u16(vl_idx) + b"\x01\x0a"
    out += b"\x09" + res_u16(c) + b"\x16"
    return bytes(out)


def count_resource_records(res_stream: bytes) -> int:
    """统计资源流中的 GVARINIT(0x43) 与 INIT_DONE(0x1c) 记录数。

    AutoCAD 的 seg1 头 ``<len> <items> $`` 中 items 即此计数。

    不简单地按字节扫描（0x43/0x1c 可能出现在 code_ref 长度、
    符号名等数据内部），而是按资源流操作码结构正确跳转。
    """
    count = 0
    pos = 0
    while pos < len(res_stream):
        op = res_stream[pos]
        if op == 0x43 and pos + 5 <= len(res_stream):
            count += 1
            pos += 5
        elif op == 0x1C:
            count += 1
            pos += 1
        elif op in (0x00, 0x01, 0x02, 0x0A, 0x0B, 0x16, 0x20, 0x23, 0x24, 0x28, 0x29, 0x2A, 0x3A, 0x62, 0x63):
            pos += 1
        elif op in (0x1E, 0x1F):
            pos += 2
        elif op in (
            0x03,
            0x05,
            0x06,
            0x07,
            0x09,
            0x0C,
            0x0D,
            0x0E,
            0x34,
            0x37,
            0x39,
            0x3C,
            0x3D,
            0x5C,
            0x5D,
            0x5E,
        ):
            pos += 3
        elif op in (0x14, 0x15, 0x33, 0x35, 0x51, 0x57, 0x67, 0x68, 0x69, 0x6A):
            pos += 5
        elif op == 0x32:
            pos += 2
        elif op in (0x56, 0x5B):
            pos += 1
            while pos < len(res_stream):
                while pos < len(res_stream) and res_stream[pos] != 0x00:
                    pos += 1
                pos += 1
                if pos >= len(res_stream) or res_stream[pos] == 0x00:
                    if pos < len(res_stream):
                        pos += 1
                    break
        elif op == 0x55:
            pos += 1
            if pos + 2 <= len(res_stream):
                import struct

                num = struct.unpack("<H", res_stream[pos : pos + 2])[0]
                pos += 2
                for _ in range(num):
                    if pos + 2 <= len(res_stream):
                        slen = struct.unpack("<H", res_stream[pos : pos + 2])[0]
                        pos += 2 + slen
        elif op == 0x3B:
            end = res_stream.find(b"\x00", pos + 1)
            pos = end + 1 if end >= 0 else pos + 1
        else:
            pos += 1
    return count


class ResourceBuilder:
    def __init__(self, symtab: SymbolTable, encoding: Optional[str] = None):
        self.symtab = symtab
        self.encoding = resolve_encoding(encoding)
        self.data = bytearray()

    def _enc(self, s: str) -> bytes:
        return self._enc_with_escape(s).encode(self.encoding, errors="replace")

    @staticmethod
    def _enc_with_escape(s: str) -> str:
        """把源字符串中当前编码无法表示的字符（如 emoji）转义为 CAD 形式。

        CAD 编译器在 Windows（系统 ANSI/GBK 代码页）上编译时，把源码里无法
        用 ANSI 表示的字符（如 `✅` U+2705、`❌` U+274C）转义为 AutoLISP
        ``\\U+XXXX`` 转义序列存入资源段（CAD 产物实测 `\n\\U+2705 `）。而
        中文等 GBK 可表示字符保持原样。这里用 GBK 作为参照编码模拟 CAD 行为：
        对 GBK 无法编码的字符输出 ``\\U+XXXX``，保证 Linux(UTF-8) 下编译产物
        与 CAD(Windows/GBK) 的字符串字节一致。已含 ``\\`` 转义前缀的字符
        （如 ``\\n`` 字面）不受影响。
        """
        out = []
        i = 0
        n = len(s)
        while i < n:
            ch = s[i]
            if ch == "\\" and i + 1 < n:
                # 已是转义序列（`\n`/`\"`/`\\`/`\U+` 等）：原样保留
                out.append(ch)
                out.append(s[i + 1])
                i += 2
                continue
            try:
                ch.encode("gbk")
                out.append(ch)
            except UnicodeEncodeError:
                out.append("\\U+%04X" % ord(ch))
            i += 1
        return "".join(out)

    def _enc_sym(self, s: str) -> bytes:
        """编码符号名：CAD 符号统一大写（AutoLISP 大小写不敏感）。

        例外：vla-/vlax- 前缀的 ActiveX 方法符号保留原始大小写（方法名
        大小写敏感，t22_activex golden 实测 `vla-get-Count`/`vlax-get-acad-object`
        保留源码大小写）。vla- 方法名首字母大写已由 cad_symbols/codegen
        统一规范化，此处仅需保留当前大小写（不再 .upper()）。
        """
        s = str(s)
        # `command` 内建 SUBR 的**调用目标**在 CAD FAS 资源段注册名为 `ads-cmd`
        # （base-function CAD 实测 `(command ...)` → 符号槽 `ads-cmd`），由
        # codegen 调用处单独注册 `ads-cmd` 符号；此处仅需保留其小写编码。
        # 普通**值引用** `command`（`(boundp 'command)`/`(type command)` 等）
        # 走下方默认大写路径 → `COMMAND`（platform CAD 实测值位置符号槽）。
        if s == "ads-cmd":
            return b"ads-cmd"
        # VLISP 内建/关键字符号保留 CAD 特定大小写（:vlax-false/:VLR-*/VLAX-FOR/
        # vlax-3d-point/startapp 等，@lisp_u golden 实测）。按小写匹配，用 CAD
        # 规范形式。优先于 vla-/vlax- 分支（VLAX-FOR 需大写、vlax-3d-point
        # 需小写，均与源码大小写不同）。
        for _canon in _VLISP_CASE_PRESERVE:
            if s.lower() == _canon.lower():
                return _canon.encode(self.encoding, errors="replace")
        if s.lower().startswith(("vla-", "vlax-")):
            return s.encode(self.encoding, errors="replace")
        return s.upper().encode(self.encoding, errors="replace")

    def _push_single_symbol(self, name: str):
        self.data.append(0x5B)
        self.data.extend(self._enc_sym(name))
        self.data.append(0)
        self.data.append(0)

    def _push_int(self, v: int):
        if -128 <= v <= 127:
            self.data.extend(res_int8(v))
        else:
            self.data.extend(res_int32(v))

    def _push_nil(self):
        self.data.append(0x01)

    def _push_t(self):
        self.data.append(0x02)

    def build(
        self,
        func_offsets: Dict[str, int],
        module_code: bytes = b"",
        total_size: int = 0,
        stub_format: bool = False,
        top_level_count: int = 0,
        commands: int = 0,
        nested_ends: Optional[Dict[int, int]] = None,
        top_lambda_body_syms: Optional[list] = None,
        module_func_count: int = 0,
    ) -> bytes:
        """构建与 AutoCAD 编译器一致的 seg1 资源流。

        结构：
        - 模块头 + 模块代码引用 + 全部函数名符号 + GVARINIT + POP
        - 函数代码引用 + 其余符号/字符串 + GET_LOCAL + GVARINIT + POP
        - 每个函数一个 DEFCODE（GET_LOCAL + PUSH_INT8 <offset> + SYMBOL + DEFCODE）
        - GVARINIT + INIT_DONE
        - 模块代码
        """
        entries = self.symtab.entries
        if not entries:
            return bytes(self.data)

        out = bytearray()
        entry_count = len(entries)

        # ── 无函数模式（CAD：纯顶层表达式）────────────────────────────────
        # CAD 对无 defun 的文件生成：模块头 + 单代码引用 + 符号/字符串
        # （源码逆序，字符串紧跟其符号）+ PUSH_NIL + GVARINIT(0,n+2) + POP
        # + NIL/LOCAL + GVARINIT(0,1) + POP + NIL + GVARINIT(n+2,0) + INIT_DONE
        # + 模块代码。不生成 DEFCODE。
        # 含顶层 `(set/setq 'sym (lambda ...))` 时（func_offsets 仅 `-lambda-`
        # 键，seg0 为内嵌 `-lambda-` 紧凑 stub），CAD 在末尾追加
        # `-lambda-` DEFCODE 区：lambda 体常量 + `-lambda-` DEFCODE + 末尾槽
        # GVARINIT，使 `-lambda-` 注册为可调用 SUBR（bootstrap/tlrep 实测）。
        _only_lambda_keys = func_offsets and all(
            ResourceBuilder._is_lambda_key(k) for k in func_offsets
        )
        if stub_format and (not func_offsets or _only_lambda_keys):
            out += b"\x14\x01\x01\x01\x00"
            mc_len = len(module_code)
            out += self._code_ref_bytes(mc_len)
            # 符号/字符串：按 symtab.entries 顺序（已由 cad_symbols 排为源码逆序）。
            # CAD 合并连续 SYMBOL 为单个 5b 块，遇 STRING 分块。
            # 含顶层 `-lambda-`（top_lambda_body_syms）时，entries 末尾为第二区
            # 体符号（CAD 把它们放函数目录之后 → fg 表），不在此注册（否则
            # 符号表重复）。第一区符号数 = len(entries) - len(第二区)。
            _first_n = len(entries)
            if _only_lambda_keys and top_lambda_body_syms:
                _first_n = len(entries) - len(top_lambda_body_syms)
            sym_buf = bytearray()
            for entry_type, entry_val in entries[:_first_n]:
                if entry_type == "SYMBOL":
                    sym_buf += self._enc_sym(entry_val) + b"\x00"
                elif entry_type == "STRING":
                    if sym_buf:
                        out += b"\x5b" + bytes(sym_buf) + b"\x00"
                        sym_buf = bytearray()
                    encoded = self._enc(entry_val)
                    out += b"\x55\x01\x00" + res_u16(len(encoded)) + encoded
                else:
                    if sym_buf:
                        out += b"\x5b" + bytes(sym_buf) + b"\x00"
                        sym_buf = bytearray()
                    self._push_entry(out, (entry_type, entry_val))
            if sym_buf:
                out += b"\x5b" + bytes(sym_buf) + b"\x00"
            out += b"\x01" * 2
            out += res_gvar_init(0, _first_n + 2) + b"\x0a"
            if _only_lambda_keys:
                # CAD 纯顶层 + `-lambda-`（setq-lambda.lsp golden 实测布局）：
                #   函数目录：每个 `-lambda-` 的 (offset . end) 范围，offset 大的
                #     先压（`32 <off>; 33/32 <end>; CONS ... 39 <n>`）
                #   第二区符号（lambda 体符号 + 参数，top_lambda_body_syms）——
                #     连续 SYMBOL 合并 5b 块，遇 STRING 分块
                #   GET_LOCAL; GVARINIT(0, 第二区数+1) → fg 表（module_id = 栈顶
                #     最后符号，build_mvar_tables 判 table1）
                #   GET_LOCAL; INT8 <seg0-offset>; SYMBOL -lambda-; DEFCODE
                #     （offset 大的先注册，func_offsets 值大的在前）
                #   NIL; GVARINIT(第一区数+2, 函数数) → `-lambda-` gvar 槽
                #     （超出 nsyms 表的运行时槽，模块代码 PUSH_G 引用）
                out += self._func_ranges_bytes(func_offsets, total_size or 1)
                _lam_syms = list(top_lambda_body_syms or [])
                _sym_buf = bytearray()
                for _bs in _lam_syms:
                    if isinstance(_bs, str) and _bs.startswith('"'):
                        if _sym_buf:
                            out += b"\x5b" + bytes(_sym_buf) + b"\x00"
                            _sym_buf = bytearray()
                        out += b"\x55\x01\x00" + res_u16(len(_bs) - 2) + self._enc(_bs[1:-1])
                    else:
                        _sym_buf += self._enc_sym(_bs) + b"\x00"
                if _sym_buf:
                    out += b"\x5b" + bytes(_sym_buf) + b"\x00"
                out += b"\x5c\x00\x00" + res_gvar_init(0, len(_lam_syms) + 1) + b"\x0a"
                # 多个 `-lambda-` DEFCODE：每个 `GET_LOCAL 0; INT8 <seg0-offset>;
                # SYMBOL -lambda-; DEFCODE`（setq-lambda.lsp CAD golden 实测
                # 两个 `-lambda-`，offset 大的先注册）。CAD 顺序 = seg0 中后出现
                # 的 `-lambda-` 先 DEFCODE（func_offsets 值大的在前）。
                _lam_offs = sorted(func_offsets.values(), reverse=True)
                for _lo in _lam_offs:
                    out += b"\x5c\x00\x00"
                    if -128 <= _lo <= 127:
                        out += b"\x32" + bytes([_lo & 0xFF])
                    else:
                        out += res_int32(_lo)
                    out += b"\x5b" + self._enc("-lambda-") + b"\x00\x00" + b"\x3a"
                # `-lambda-` 注册到末尾 gvar 槽 = 第一区数+2（CAD 实测
                # GVARINIT(28, 2)，28 = 26 第一区符号 + 2）。
                out += b"\x01" + res_gvar_init(_first_n + 2, len(_lam_offs))
                out += b"\x1c"
                out += module_code
                return bytes(out)
            out += b"\x01\x5c\x00\x00"
            out += res_gvar_init(0, 1) + b"\x0a"
            out += b"\x01" + res_gvar_init(entry_count + 2, 0)
            out += b"\x1c"
            out += module_code
            return bytes(out)

        # ── 模块注册 ────────────────────────────────────────────────────
        out += b"\x14\x01\x01\x01\x00"
        out += self._code_ref_bytes(len(module_code))
        nested_offs = set(nested_ends) if nested_ends else set()
        func_names_all = list(func_offsets.keys()) if func_offsets else [self._entry_name(entries[0])]
        if stub_format:
            # kwote 内嵌 `-lambda-`：不作为模块注册函数名，仅参与函数目录。
            module_func_names = [k for k in func_names_all if func_offsets.get(k) not in nested_offs]
            func_names_all = module_func_names
            # 模块注册：全部 defun 名 + 顶层表达式符号（CAD @lisp_u 实测
            # 模块注册 1339 个名字/544 函数，非"尾块 48"）。module_func_count
            # 截断（7beeddf 引入）据错误的"CAD 只注册 48 个"假设，导致其余
            # 函数不在模块注册段、模块代码 USUBR 引用错槽位 → CAD 加载报
            # "no function definition: nil"。已移除。
            # CAD 模块注册：函数名（源码逆序）+ 顶层表达式符号，连续 SYMBOL 合并，
            # 遇 STRING 分块；PUSH_NIL + GVARINIT。
            module_entries = entries[: len(func_names_all) + top_level_count]
            module_entries_count = len(module_entries)
            fn_bytes = bytearray()
            # 函数名（逆序）在前，其后是顶层符号（entries 顺序）。
            # 注意：cad_symbols 已把 entries 排为"源码逆序逐 form"（顶层与
            # 函数名交错，mix2=setq 末→`X,B,A`，mix3=setq 首→`B,A,X`），
            # 因此这里直接按 entries 自然序输出即可，勿再单独逆序函数名。
            if commands and func_names_all:
                # CAD 命令模块注册：每个命令函数独立 5b 块，首命令后插入
                # `56 vl-ACAD-defun 00 00`（t14_command 实测）。该符号保留
                # 原始大小写（`Vl-ACAD-defun`），不同于普通符号的大写编码。
                names = list(reversed(func_names_all))
                for i, fname in enumerate(names):
                    out += b"\x5b" + self._enc_sym(fname) + b"\x00\x00"
                    if i == 0:
                        out += b"\x56" + self._enc("vl-ACAD-defun") + b"\x00\x00"
                # 命令 + 顶层表达式混合：函数名已单独注册，跳过；其余顶层
                # 符号/常量仍需登记（atlisp_u 实测），否则模块代码引用的
                # gvar 槽无符号记录。GVARINIT 计数仍按完整 module_entries。
                _cmd_names = {str(f).upper() for f in names}
                module_entries = [e for e in module_entries
                                  if not (e[0] == "SYMBOL" and str(e[1]).upper() in _cmd_names)]
            for entry_type, entry_val in module_entries:
                if entry_type == "SYMBOL":
                    fn_bytes += self._enc_sym(entry_val) + b"\x00"
                elif entry_type == "STRING":
                    if fn_bytes:
                        out += b"\x5b" + bytes(fn_bytes) + b"\x00"
                        fn_bytes = bytearray()
                    encoded = self._enc(entry_val)
                    out += b"\x55\x01\x00" + res_u16(len(encoded)) + encoded
                else:
                    if fn_bytes:
                        out += b"\x5b" + bytes(fn_bytes) + b"\x00"
                        fn_bytes = bytearray()
                    self._push_entry(out, (entry_type, entry_val))
            if fn_bytes:
                out += b"\x5b" + bytes(fn_bytes) + b"\x00"
            out += b"\x01" * 2
            out += res_gvar_init(0, module_entries_count + 2 + commands) + b"\x0a"
        else:
            self._push_entry(out, entries[0])
            out += b"\x01" * (entry_count - 1)
            out += res_gvar_init(0, entry_count) + b"\x0a"

        # ── 函数注册 ────────────────────────────────────────────────────
        if stub_format and func_offsets and len(func_offsets) > 1:
            # 最后一个函数 end 用 total_size = len(seg0 字节码) + 1（CAD f4*/f5 实测）。
            out += self._func_ranges_bytes(func_offsets, total_size, nested_ends=nested_ends)
        else:
            # CAD 代码引用长度 = total_size = len(seg0 字节码) + 1。
            ref_len = total_size if total_size else self._first_function_len(module_code)
            out += self._code_ref_bytes(ref_len)
        if stub_format:
            # CAD 符号格式: 连续 SYMBOL 合并为单个 5b 块，遇 STRING 分块；
            # 连续 STRING 合并为单个 55 块（i18n-cad 实测 `55 02 00
            # <len> <str> <len> <str>`，`.en.lang`/`.zh.lang`）。
            # 跳过模块已注册的符号（函数名 + 顶层表达式符号，含字符串）。
            skip_first = len(func_names_all) + top_level_count
            symbol_bytes = bytearray()
            sub = entries[1:]
            i = 0
            while i < len(sub):
                entry_type, entry_val = sub[i]
                if i < skip_first - 1:
                    i += 1
                    continue
                if entry_type == "SYMBOL":
                    if nested_offs and func_offsets.get(str(entry_val)) in nested_offs:
                        # kwote 内嵌 `-lambda-`：仅经资源流前置 DEFCODE 注册
                        # （ref i18n-cad 实测），不进符号块。
                        i += 1
                        continue
                    if str(entry_val) in ("_al-bind-alist", "kwote"):
                        # CAD `/ 局部变量` 助手与 kwote 机制符号：保留大小写、
                        # 独立 0x56 单符号块（t11_localvars / i18n-cad 实测）。
                        if symbol_bytes:
                            out += b"\x5b" + bytes(symbol_bytes) + b"\x00"
                            symbol_bytes = bytearray()
                        out += b"\x56" + self._enc(entry_val) + b"\x00\x00"
                    else:
                        symbol_bytes += self._enc_sym(entry_val) + b"\x00"
                    i += 1
                elif entry_type == "CONST":
                    if symbol_bytes:
                        out += b"\x5b" + bytes(symbol_bytes) + b"\x00"
                        symbol_bytes = bytearray()
                    out += self._const_bytes(entry_val)
                    i += 1
                elif entry_type == "STRING":
                    if symbol_bytes:
                        out += b"\x5b" + bytes(symbol_bytes) + b"\x00"
                        symbol_bytes = bytearray()
                    # 合并连续 STRING 为单个 55 块
                    strs = [entry_val]
                    j = i + 1
                    while j < len(sub) and j >= skip_first - 1 and sub[j][0] == "STRING":
                        strs.append(sub[j][1])
                        j += 1
                    out += b"\x55" + res_u16(len(strs))
                    for sv in strs:
                        enc = self._enc(sv)
                        out += res_u16(len(enc)) + enc
                    i = j
                else:
                    if symbol_bytes:
                        out += b"\x5b" + bytes(symbol_bytes) + b"\x00"
                        symbol_bytes = bytearray()
                    self._push_entry(out, (entry_type, entry_val))
                    i += 1
            if symbol_bytes:
                out += b"\x5b" + bytes(symbol_bytes) + b"\x00"
        else:
            for entry_type, entry_val in entries[1:]:
                self._push_entry(out, (entry_type, entry_val))
        if stub_format and nested_offs:
            # kwote/立即应用内嵌 `-lambda-`：在 GVARINIT(0, nsyms) 前置 DEFCODE，
            # 使大 GVARINIT 的 module_id 解出 FUNC 而非裸符号
            # （ref i18n-cad 实测）：GET_LOCAL 0 + INT32 offset +
            # SYMBOL -lambda- + DEFCODE。每个内嵌 lambda 独立 DEFCODE，
            # 按 seg0 偏移**逆序**发射（CAD 实测：先发射的 lambda 被 GVARINIT
            # 后弹出，分配更高槽——t3 槽 18、t4 槽 17、t5 槽 16，nsyms=19）。
            lam_offsets = sorted(
                (off for k, off in func_offsets.items() if ResourceBuilder._is_lambda_key(k)),
                reverse=True,
            )
            for off in lam_offsets:
                if -128 <= off <= 127:
                    out += b"\x5c\x00\x00\x32" + bytes([off & 0xFF])
                else:
                    out += b"\x5c\x00\x00" + res_int32(off)
                out += b"\x5b" + self._enc("-lambda-") + b"\x00\x00"
                out += b"\x3a"
        out += b"\x5c\x00\x00"
        if stub_format:
            # CAD: 函数注册 GVARINIT st_init = 注册符号数 + 1 = len(entries) - skip_first + 1。
            # 该 st_init 亦等于 nsyms。
            reg_count = len(entries) - skip_first + 1
            out += res_gvar_init(0, reg_count) + b"\x0a"
        else:
            out += res_gvar_init(0, entry_count) + b"\x0a"

        # ── 函数定义（每个函数一个 DEFCODE）──────────────────────────────
        # CAD 为每个函数生成: GET_LOCAL 0, PUSH_INT8 <seg0-offset>,
        # SYMBOL <name>, DEFCODE(3a), 01。stub 格式按源码逆序注册。
        func_names = list(func_offsets.keys()) if func_offsets else []
        if not func_names:
            name0 = self._entry_name(entries[0])
            func_names = [name0]
        # kwote 内嵌 `-lambda-` 已前置 DEFCODE 注册，此处剔除避免重复。
        if nested_offs:
            func_names = [k for k in func_names if func_offsets.get(k) not in nested_offs]
        if stub_format:
            func_names = list(reversed(func_names))
        for fi, fname in enumerate(func_names):
            off = func_offsets.get(fname, 0)
            if stub_format:
                if -128 <= off <= 127:
                    out += b"\x5c\x00\x00\x32" + bytes([off & 0xFF])
                else:
                    out += b"\x5c\x00\x00" + res_int32(off)
                # CAD `-lambda-`（内嵌函数）保留小写（`-LAMBDA-` 是错的）；
                # 其余函数名统一大写。多 `-lambda-` 用 `-lambda-#N` 目录键，
                # 编码仍为 `-lambda-`。
                name_enc = (
                    self._enc("-lambda-")
                    if ResourceBuilder._is_lambda_key(fname)
                    else self._enc_sym(fname)
                )
                out += b"\x5b" + name_enc + b"\x00\x00"
                # CAD 只有最后一个 DEFCODE 追加 01（stub 格式）。
                out += b"\x3a\x01" if fi == len(func_names) - 1 else b"\x3a"
            else:
                if -128 <= off <= 127:
                    out += b"\x5c\x00\x00\x32" + bytes([off & 0xFF])
                else:
                    out += b"\x5c\x00\x00" + res_int32(off)
                out += b"\x5b" + self._enc_sym(fname) + b"\x00\x00"
                out += b"\x3a\x01"
        # DEFCODE 后 GVARINIT：var_pos = 模块注册符号数 + 2（函数名 + 顶层符号 + 2）。
        _nsyms = entry_count - len(func_names) - top_level_count + 1
        gv_var_pos = len(func_names) + top_level_count + 2 + commands if stub_format else max(0, entry_count - 1)
        gv_st_init = len(func_names) if stub_format else len(func_names)
        out += res_gvar_init(gv_var_pos, gv_st_init)
        out += b"\x1c"

        # ── 模块代码 ────────────────────────────────────────────────────
        out += module_code

        return bytes(out)

    def _push_entry(self, out: bytearray, entry: Tuple[str, Any]):
        entry_type, entry_val = entry
        if entry_type == "SYMBOL":
            out += b"\x5b" + self._enc_sym(entry_val) + b"\x00\x00"
        elif entry_type == "CONST":
            out += self._const_bytes(entry_val)
        elif entry_type == "STRING":
            encoded = self._enc(entry_val)
            out += b"\x55\x01\x00" + res_u16(len(encoded)) + encoded
        elif entry_type == "INT":
            val = int(entry_val)
            out += res_int8(val) if -128 <= val <= 127 else res_int32(val)
        elif entry_type == "REAL":
            out += res_real_str(_real_fmt(entry_val))

    def _const_bytes(self, structure) -> bytes:
        """把 CAD 常量结构序列化为资源流记录（CAD '(lambda ...) 实测）。

        结构与 build_mvar_tables 的栈模拟一一对应：原子记录 + 列表以
        ``39 <count>`` 收尾。每个 SYMBOL 独立成块（5b name 00 00）。
        """
        out = bytearray()
        self._emit_const(out, structure)
        return bytes(out)

    def _emit_const(self, out: bytearray, structure):
        kind = structure[0]
        if kind == "NIL":
            out.append(0x01)
        elif kind == "T":
            out.append(0x02)
        elif kind == "SYMBOL":
            out += b"\x5b" + self._enc_sym(structure[1]) + b"\x00\x00"
        elif kind == "INT":
            val = int(structure[1])
            out += res_int8(val) if -128 <= val <= 127 else res_int32(val)
        elif kind == "REAL":
            out += res_real_str(_real_fmt(structure[1]))
        elif kind == "STRING":
            encoded = self._enc(structure[1])
            out += b"\x55\x01\x00" + res_u16(len(encoded)) + encoded
        elif kind == "LIST":
            dotted = len(structure) > 2 and structure[2]
            for item in structure[1]:
                self._emit_const(out, item)
            # dotted 引用 `'(1 . 2)`：CAD 用单字节 `2a`(LIST_END) 收尾
            # （t12_quote 实测）；普通列表用 `39 <count>`。
            out += b"\x2a" if dotted else (b"\x39" + res_u16(len(structure[1])))
        else:
            raise ValueError(f"Unknown constant kind: {kind}")

    @staticmethod
    def _entry_name(entry: Tuple[str, Any]) -> str:
        return str(entry[1])

    @staticmethod
    def _is_lambda_key(name) -> bool:
        """判断目录键是否为内嵌 `-lambda-`（含多 `-lambda-` 键 `-lambda-#N`）。"""
        s = str(name)
        return s == "-lambda-" or s.startswith("-lambda-#")

    @staticmethod
    def _code_ref_bytes(length: int) -> bytes:
        """``32 00 32 <len> 2a 39 01 00`` — CAD 代码引用字节（单函数）。"""
        if -128 <= length <= 127:
            return bytes([0x32, 0x00, 0x32, length & 0xFF, 0x2A, 0x39, 0x01, 0x00])
        return bytes([0x32, 0x00]) + res_int32(length) + bytes([0x2A, 0x39, 0x01, 0x00])

    @staticmethod
    def _func_ranges_bytes(
        func_offsets: Dict[str, int], total_len: int, nested_ends: Optional[Dict[int, int]] = None
    ) -> bytes:
        """多函数代码引用：每个函数的 (start, end) 范围，从末尾逆序。

        ``32 <start> 32 <end> 2a ... 39 <count> 00``。

        kwote 内嵌 `-lambda-` 目录项（i18n-cad 实测）：内嵌函数范围 end 用
        其自身结束偏移（nested_ends），宿主函数 end 用下一个**非内嵌**函数的
        起始（跳过内嵌项）。ref：`@::LOAD-MT (944, 1081)`、`-lambda- (984, 1044)`。
        """
        nested_offsets = set(nested_ends) if nested_ends else set()
        offsets = sorted((v, k) for k, v in func_offsets.items())
        out = bytearray()
        ranges = []
        for i, (off, name) in enumerate(offsets):
            if off in nested_offsets and nested_ends is not None:
                end = nested_ends[off]
            else:
                end = total_len
                for j in range(i + 1, len(offsets)):
                    if offsets[j][0] not in nested_offsets:
                        end = offsets[j][0]
                        break
            ranges.append((off, end))
        for start, end in reversed(ranges):
            out += bytes([0x32, start & 0xFF]) if -128 <= start <= 127 else bytes([0x33]) + res_s32(start)
            out += bytes([0x32, end & 0xFF]) if end <= 127 else bytes([0x33]) + res_s32(end)
            out += b"\x2a"
        out += bytes([0x39]) + res_u16(len(ranges))
        return bytes(out)

    @staticmethod
    def _first_function_len(module_code: bytes) -> int:
        """模块代码中第一个函数（到首个 JUMP 指令为止）的长度。"""
        pos = 0
        while pos < len(module_code):
            if module_code[pos] == 0x57 and pos + 5 <= len(module_code):
                return pos + 5
            if module_code[pos] == 0x16:
                return pos + 1
            pos += 1
        return len(module_code)
