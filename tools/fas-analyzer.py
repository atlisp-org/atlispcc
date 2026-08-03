#!/usr/bin/env python3
"""
FAS4 分析器 — 识别格式类型，提取函数边界和分析报告。

使用 core/fas_core.py 核心模块。

用法:
  python -m tools.fas-analyzer <input.fas> [--dump] [--json]
"""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import sys
import os
import json

from core.fas_core import (
    parse_fas4, extract_stubs,
    parse_resource_stream, build_mvar_tables, build_function_catalog,
    extract_symbol_names,
)


def print_hex(data, start=0, length=None):
    if length is None:
        length = len(data)
    end = min(start + length, len(data))
    for i in range(start, end, 16):
        chunk = data[i:i + 16]
        hex_str = ' '.join(f'{b:02x}' for b in chunk)
        ascii_str = ''.join(chr(b) if 32 <= b < 127 else '.' for b in chunk)
        print(f"  0x{i:06x}: {hex_str:<48s} {ascii_str}")


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    fpath = sys.argv[1]
    dump = '--dump' in sys.argv
    json_out = '--json' in sys.argv

    if not os.path.exists(fpath):
        print(f'error: file not found: {fpath}')
        sys.exit(1)

    info = parse_fas4(fpath)
    bytecode = info['bytecode']
    seg0_total = len(bytecode)
    seg1_dec = info['res_data_decrypted']
    seg1_enc = info['res_data_encrypted']
    key = info['key']

    # ── 格式分类 ──────────────────────────────────────────────────────────────
    has_func_defs = False
    seg0_enc = False
    # 判断 seg0 是否含函数定义
    from core.fas_core import FUNC_DEF_OPCODE
    if FUNC_DEF_OPCODE in bytecode:
        has_func_defs = True

    # 熵检测
    sample_bc = bytecode[:min(len(bytecode), 256)]
    if len(sample_bc) >= 32:
        unique = len(set(sample_bc))
        zero_ratio = sample_bc.count(0) / len(sample_bc)
        seg0_encrypted = unique > 110 and zero_ratio < 0.01
    else:
        seg0_encrypted = False

    seg1_has_data = len(seg1_enc) > 0
    seg1_is_encrypted = False
    if seg1_has_data:
        sample = seg1_enc[:min(len(seg1_enc), 256)]
        if len(sample) >= 32:
            unique = len(set(sample))
            zero_ratio = sample.count(0) / len(sample)
            seg1_is_encrypted = unique > 110 and zero_ratio < 0.01

    if not seg1_has_data:
        fmt = 'single-segment'
    elif seg1_is_encrypted and key:
        fmt = 'dual-segment-encrypted'
    elif seg1_has_data and not seg1_is_encrypted:
        fmt = 'dual-segment-plain'
    else:
        fmt = 'unknown'

    # ── 提取桩 ────────────────────────────────────────────────────────────────
    stubs = extract_stubs(bytecode)

    # ── 符号目录 ──────────────────────────────────────────────────────────────
    catalog = []
    symbols = []
    strings = []
    if seg1_dec:
        resource_items, symbols, strings = parse_resource_stream(seg1_dec)
        resource_gvars, function_gvars = build_mvar_tables(seg1_dec, info['nsyms'])
        catalog = build_function_catalog(resource_gvars, function_gvars)
    else:
        # 尝试从 seg1 加密数据中提取符号
        strings = extract_symbol_names(seg1_enc) if seg1_enc else []

    # ── 输出报告 ──────────────────────────────────────────────────────────────
    print(f'=== FAS4 分析报告 ===')
    print(f'文件: {fpath}')
    print(f'大小: {os.path.getsize(fpath)} bytes')
    print(f'格式: {fmt}')
    print(f'nsyms: {info["nsyms"]}')
    print(f'Seg0: {seg0_total} bytes')
    print(f'Seg1: {len(seg1_enc)} bytes (encrypted) / {len(seg1_dec)} bytes (decrypted)')
    if key:
        print(f'XOR key: {key.hex()} ({len(key)} bytes)')
    if info['trailer']:
        print(f'尾部: {info["trailer"][:60]}')

    if stubs:
        dispatch_count = sum(1 for s in stubs if s['is_dispatch'])
        print(f'\n函数桩: {len(stubs)}')
        print(f'  自包含: {len(stubs) - dispatch_count}')
        print(f'  派发:   {dispatch_count}')

        for i, s in enumerate(stubs[:20]):
            cat_name = ''
            for n, off in catalog:
                if off == s['offset']:
                    cat_name = n
                    break
            name_tag = f' [{cat_name}]' if cat_name else ''
            sel_tag = f' sel={s["selector"]}' if s['is_dispatch'] else ''
            sym_tag = f' sym={s["sym_idx"]}' if s['sym_idx'] is not None else ''
            print(f'  [{i:3d}] 0x{s["offset"]:06x} ({len(s["data"]):4d} B)'
                  f'{sym_tag}{sel_tag}{name_tag}')
        if len(stubs) > 20:
            print(f'  ... ({len(stubs) - 20} more)')

    if catalog:
        print(f'\n函数目录: {len(catalog)} 条目')
        for name, off in catalog[:15]:
            print(f'  {name:30s} @ {off}')
        if len(catalog) > 15:
            print(f'  ... ({len(catalog) - 15} more)')

    if symbols:
        print(f'\n符号: {len(symbols)}')
        if len(symbols) <= 40:
            for s in symbols[:20]:
                print(f'  {s}')
        else:
            for s in symbols[:20]:
                print(f'  {s}')
            print(f'  ... ({len(symbols) - 20} more)')

    if strings:
        print(f'\n字符串字面量: {len(strings)}')
        for s in strings[:10]:
            print(f'  {s!r}')
        if len(strings) > 10:
            print(f'  ... ({len(strings) - 10} more)')

    if dump and stubs:
        print(f'\n=== 关键区域 Dump ===')
        for stub in stubs[:5]:
            print(f'\n--- Function @ 0x{stub["offset"]:x} ({len(stub["data"])} B) ---')
            print_hex(stub['data'], length=min(len(stub['data']), 48))

    # ── JSON 输出 ─────────────────────────────────────────────────────────────
    if json_out:
        safe_stubs = [{
            'index': i, 'offset': s['offset'], 'size': len(s['data']),
            'sym_idx': s['sym_idx'], 'selector': s['selector'],
            'type': 'dispatch' if s['is_dispatch'] else 'self-contained',
        } for i, s in enumerate(stubs)]
        j = {
            'file': fpath, 'size': os.path.getsize(fpath), 'format': fmt,
            'nsyms': info['nsyms'],
            'seg0_size': seg0_total,
            'seg1_size': len(seg1_enc),
            'func_count': len(stubs),
            'func_dispatch': dispatch_count,
            'func_self_contained': len(stubs) - dispatch_count,
            'catalog_count': len(catalog),
            'catalog': [(n, off) for n, off in catalog],
            'stubs': safe_stubs,
        }
        jpath = fpath + '.analysis.json'
        with open(jpath, 'w') as f:
            json.dump(j, f, indent=2)
        print(f'\nJSON 报告: {jpath}')


if __name__ == '__main__':
    main()
