"""@lisp 综合包 + kernel 全量 byte-identity 回归（2026-08-29）。

锁住两项里程碑：

1. **atlisp_u.lsp 全量 byte-identity**（502 函数 + 221 顶层语句 + 80 kwote 回调）：
   seg0 + seg1 资源段 + nsyms 与 CAD golden `tests/atlisp_u_cad2.fas` 逐字节一致。
   这是编译器全管线的终极回归——覆盖 commands+顶层混合 gvar 槽重映射、顶层
   kwote lambda func-obj 让位、条件 defun mid 发射、`set` 协议槽、大文件宽格式
   USUBR/FUNC、`_mid_count_of` top-lambda-only 索引等（见 AGENTS.md「atlisp_u
   全量 byte-identity（2026-08-29）」）。

2. **kernel 67/67 byte-identity**：`../kernel/src/` 下全部 `.lsp` 与
   `tests/cad/kernel_golden/` 下 CAD 真机 golden 逐字节一致。此前仅由
   `scripts/kernel_compare_http.py`（MCP）验证，此处锁定为无 CAD 环境的回归。

   注意：kernel 文件须 `--encoding gbk`（源码含中文注释，CAD 用系统 ACP 写
   seg1 字符串）；golden 为 2026-08-26/27 真机产物。
"""
import glob
import os
import sys
import tempfile

import pytest

sys.path.insert(0, '.')

from compiler.cli import cmd_compile
from decompiler.fas4_decompiler import Fas4Parser


def _tmp(name):
    return os.path.join(tempfile.gettempdir(), name)


def _assert_byte_identity(label, ours_path, golden_path):
    ours = Fas4Parser().parse(ours_path)
    ref = Fas4Parser().parse(golden_path)
    assert ours.nsyms == ref.nsyms, (
        f'{label}: nsyms {ours.nsyms} != {ref.nsyms}'
    )
    assert ours.bytecode == ref.bytecode, (
        f'{label}: seg0 bytecode differs from CAD golden\n'
        f'  ours: {ours.bytecode.hex()}\n'
        f'  CAD : {ref.bytecode.hex()}'
    )
    assert ours.resource_items == ref.resource_items, (
        f'{label}: seg1 resource items differ from CAD golden'
    )


# ── 1. atlisp_u 全量 byte-identity ────────────────────────────────────────────

def test_atlisp_u_full_byte_identity():
    """atlisp_u.lsp（@lisp 综合包）seg0+seg1+nsyms 与 CAD golden 逐字节一致。

    此前 99.3%（seg0 622 + seg1 9630 字节 diff），2026-08-29 修到 100%。
    编译较慢（~13s，502 函数宽格式），故单独一个用例而非参数化。
    """
    src = os.path.join('tests', 'atlisp_u.lsp')
    golden = os.path.join('tests', 'atlisp_u_cad2.fas')
    if not (os.path.exists(src) and os.path.exists(golden)):
        pytest.skip('missing atlisp_u fixture / golden')
    out = _tmp('atlisp_u_id.fas')
    try:
        cmd_compile(src, out)
        _assert_byte_identity('atlisp_u', out, golden)
    finally:
        if os.path.exists(out):
            os.unlink(out)


def test_atlisp_u_roundtrip_validate():
    """atlisp_u 编译产物反编译输出结构完整（tokenize + parse 通过）。

    锁住大文件 disasm→asm / 反编译的普适不变量。不做严格 `validate_ast`
    （反编译的复杂顶层形式如裸 `T`/空 `(progn)` 是既有反编译器语义差异，
    与本次 byte-identity 无关）；只验证词法/语法可解析 + 函数目录还原。
    """
    from decompiler.fas4_decompiler import Fas4Decompiler
    from tools.validate import parse_tokens, tokenize

    src = os.path.join('tests', 'atlisp_u.lsp')
    if not os.path.exists(src):
        pytest.skip('missing atlisp_u.lsp fixture')
    fas = _tmp('atlisp_u_rt.fas')
    lsp = _tmp('atlisp_u_rt.lsp')
    try:
        cmd_compile(src, fas)
        Fas4Decompiler().decompile(fas, lsp)
        code = open(lsp, encoding='utf-8').read()
        # 大文件应还原出大量 defun（含死代码过滤后可达集；`@::init` 命令链）。
        defuns = code.count('(defun ')
        assert defuns >= 200, f'atlisp_u roundtrip recovered {defuns} defuns'
        tokens, errs = tokenize(code)
        assert not errs, f'tokenize errors: {errs[:3]}'
        forms, errs = parse_tokens(tokens)
        assert not errs, f'parse errors: {errs[:3]}'
        assert len(forms) > 0
    finally:
        for p in (fas, lsp):
            if os.path.exists(p):
                os.unlink(p)


# ── 2. kernel 67/67 byte-identity ────────────────────────────────────────────

def _kernel_pairs():
    """Discover (source, golden) pairs from tests/cad/kernel_golden/.

    Golden 目录镜像 kernel 源码树（base-function.lsp → base-function.fas，
    net/http.lsp → net/http.fas 等）。stray `platform-api_test.fas` 无对应源，
    跳过。
    """
    base = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'cad', 'kernel_golden')
    kernel_src = os.path.normpath(os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        '..', 'kernel', 'src'))
    pairs = []
    for g in sorted(glob.glob(os.path.join(base, '**', '*.fas'), recursive=True)):
        rel = os.path.relpath(g, base)[: -len('.fas')] + '.lsp'
        src = os.path.join(kernel_src, rel)
        if os.path.exists(src):
            pairs.append((rel, src, g))
    return pairs


_KERNEL_PAIRS = _kernel_pairs()


@pytest.mark.parametrize(
    'rel,src,golden',
    _KERNEL_PAIRS,
    ids=[r for r, _, _ in _KERNEL_PAIRS],
)
def test_kernel_golden_byte_identity(rel, src, golden):
    """kernel 每个 .lsp 与 CAD 真机 golden 逐字节一致（seg0+seg1+nsyms）。

    锁住 kernel 67/67 里程碑（2026-08-27 起）。golden 由 AutoCAD 24.1s
    `(vlisp-compile 'st ...)` 生成；须 `--encoding gbk`（源码含中文注释，
    CAD 用系统 ACP 写 seg1 字符串）。
    """
    out = _tmp('kernel_' + rel.replace('/', '_')[:-4] + '.fas')
    try:
        cmd_compile(src, out, encoding='gbk')
        _assert_byte_identity(rel, out, golden)
    finally:
        if os.path.exists(out):
            os.unlink(out)
