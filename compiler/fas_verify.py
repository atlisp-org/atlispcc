"""FAS4 编译产物验证 — 防止 CAD 加载时访问冲突 0xC0000005。

在 `cmd_compile` 生成最终 seg0/seg1 之后调用 `verify_fas`，检查：
1. **反汇编可解析性**：seg0 无 UNK_ 操作码（UNK 表示指令流被误解析，
   说明 short/wide USUBR 判定或指令边界错位——错位后的字节被当作
   USUBR/FUNC 的大索引，是 CAD 0xC0000005 的常见来源）。
2. **符号引用越界**：PUSH_G/PUSH_VALUE/SETQ_G/USUBR/FUNC 的操作数
   （gvar 槽 - 1）必须落在资源 gvar 表内（[0, nsyms)），越界即访问
   冲突。USUBR/FUNC 目标符号槽末尾（gvar 槽 = nsyms，操作数 =
   nsyms-1）是合法特例，其余越界一律报错。
3. **局部变量索引**：GET_LOCAL/GET_LOCAL_WIDE/SET_LOCAL/CLEAR_LOCAL
   索引须小于所在函数的局部槽数（DEFUN 头 argc 编码，含循环深度）。
4. **指令流完整性**：disasm 的累计大小 == len(seg0)（无尾随残留）。
5. **seg1 可重建**：解密后资源流能重建 mvar 表（gvar 表为符号引用
   提供依据；无法重建说明资源段损坏）。

验证不修改任何字节；发现问题返回 (ok: bool, issues: list[str])。
"""
from typing import List, Optional, Tuple

from decompiler.fas4_decompiler import Disassembler

# 携带符号索引操作数的指令（操作数 = gvar 槽 - 1；USUBR/FUNC 的
# 第二个操作数为符号索引，PUSH_G/PUSH_VALUE/SETQ_G 的第一个操作数）。
SYM_REF_OPS = {"PUSH_G", "PUSH_VALUE", "SETQ_G", "PUSH_G_ALT"}
SUBR_OPS = {"USUBR", "FUNC"}
# 局部变量引用指令（索引须 < 函数局部槽数）。
LOCAL_OPS = {"GET_LOCAL", "GET_LOCAL_WIDE", "SET_LOCAL", "CLEAR_LOCAL"}


def _defun_local_count(header: bytes) -> int | None:
    """从 DEFUN 头 4 字节推断局部槽数。

    CAD 紧凑 stub DEFUN 头为 `14 <a> <b> <c> <d>`，其中 a = argc +
    直接体并发循环深度，b = c = argc（d 恒 0）。局部槽数 = a（参数 +
    循环预载槽 + `/ 局部变量`）。无法判定时返回 None（跳过检查）。
    """
    if len(header) < 4:
        return None
    a, b, c = header[0], header[1], header[2]
    if not (b == c or a in (b + 1, b + 2, b + 3)):
        return None
    return a


def verify_fas(
    seg0: bytes,
    seg1: bytes,
    nsyms: int,
    label: str = "output",
) -> Tuple[bool, List[str]]:
    """验证编译产物。返回 (ok, issues)。

    ``seg1`` 应为**明文**资源流（`ResourceBuilder.build()` 返回值；
    加密发生在 FasWriter.write 阶段），内部直接重建 gvar 表。

    ``ok`` 为 False 表示**致命**问题（UNK 误解析 / 符号引用越界 /
    指令流覆盖不全 / 资源段损坏），这类问题会直接导致 CAD 加载访问
    冲突 0xC0000005，须阻断编译。局部变量索引越界仅记为 warning
    （CAD 帧分配含 `/ 局部变量`，DEFUN 头 argc 编码无法完整推断）。
    """
    issues: List[str] = []
    warnings: List[str] = []
    wide = nsyms > 256
    sym_count = max(nsyms, 1)

    try:
        dis = Disassembler(short_subr=not wide)
        insts = dis.disassemble(seg0, nsyms, sym_count=sym_count)
    except Exception as e:  # noqa: BLE001
        return False, [f"{label}: disasm failed: {e}"]

    # 1) UNK 操作码 & 指令流完整性
    unk = [i for i in insts if i.op_name.startswith("UNK_")]
    total = sum(i.size for i in insts)
    if unk:
        sample = ", ".join(f"@{i.offset:05x} {i.op_name}" for i in unk[:8])
        issues.append(
            f"{label}: {len(unk)} UNK opcodes (misparse risk → 0xC0000005): {sample}"
        )
    if total != len(seg0):
        issues.append(
            f"{label}: disasm covers {total} bytes but seg0 is {len(seg0)} "
            f"(leftover {len(seg0) - total} bytes)"
        )

    # 2) 符号引用越界
    for i in insts:
        ops = getattr(i, "operands", None) or []
        if i.op_name in SYM_REF_OPS and len(ops) >= 1:
            idx = ops[0]
            if not 0 <= idx < nsyms:
                issues.append(
                    f"{label}: {i.op_name} @{i.offset:05x} operand {idx} "
                    f"out of gvar range [0,{nsyms})"
                )
        elif i.op_name in SUBR_OPS and len(ops) >= 2:
            idx = ops[1]
            if not 0 <= idx < nsyms:
                issues.append(
                    f"{label}: {i.op_name} @{i.offset:05x} sym idx {idx} "
                    f"out of range [0,{nsyms})"
                )

    # 3) 局部变量索引（warning：DEFUN 头 argc 编码不含 `/ 局部变量` 槽，
    #    无法可靠推断帧大小，仅当明显超界时提示）
    cur_locals: Optional[int] = None
    for i in insts:
        if i.op_name in ("DEFUN", "DEFUN_ALT"):
            cur_locals = _defun_local_count(bytes(seg0[i.offset + 1 : i.offset + 5]))
        elif i.op_name in LOCAL_OPS and len(getattr(i, "operands", None) or []) >= 1:
            idx = i.operands[0]
            if cur_locals is not None and not 0 <= idx < cur_locals:
                warnings.append(
                    f"{label}: {i.op_name} @{i.offset:05x} local {idx} "
                    f"beyond DEFUN header argc {cur_locals} (may be /locals slot)"
                )

    # 4) seg1 可重建 gvar 表（符号引用依据；seg1 为明文资源流）
    try:
        from core.fas_core import build_mvar_tables

        rg, fg = build_mvar_tables(seg1, nsyms)
        # gvar 表全空说明资源段结构异常（正常应含 SYMBOL/STRING/FUNC 项）
        if not any(v is not None for v in rg) and not any(v is not None for v in fg):
            issues.append(f"{label}: seg1 gvar tables both empty (resource stream invalid)")
    except Exception as e:  # noqa: BLE001
        issues.append(f"{label}: seg1 gvar rebuild failed: {e}")

    return not issues, issues + [f"WARN {w}" for w in warnings]


def run_verify(seg0: bytes, seg1: bytes, nsyms: int, label: str = "output") -> bool:
    """CLI 便捷入口：打印验证结果，返回是否通过。"""
    ok, issues = verify_fas(seg0, seg1, nsyms, label=label)
    if ok:
        print(f"[verify] {label}: OK (nsyms={nsyms}, seg0={len(seg0)})")
    else:
        print(f"[verify] {label}: FAIL ({len(issues)} issues)")
        for msg in issues:
            print(f"  - {msg}")
    return ok
