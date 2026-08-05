#!/usr/bin/env python3
"""
FAS4 分割器 — 从双段加密 FAS 中提取每个函数，生成独立可加载的单函数 FAS 文件。

使用 core/fas_core.py 核心模块进行解析和符号表重建。

用法:
  python -m tools.fas-split <input.fas> [--outdir <dir>] [--trim] [--verbose]

选项:
  --outdir <dir>  输出目录（默认 <文件名>.split/）
  --trim          自包含桩输出 single-segment FAS（省略 seg1），减小文件体积
  --verbose       详细输出（含完整函数目录）
"""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.fas_core import (
    parse_fas4, extract_stubs,
    parse_resource_stream, build_mvar_tables, build_function_catalog,
    infer_code_ref_bias, resolve_symbol_name,
    extract_symbol_names, build_single_function_fas, find_fas4_magic,
)


def make_filename(stub, idx, fpath, catalog_name='', tag=''):
    """生成输出文件名。"""
    base = os.path.splitext(os.path.basename(fpath))[0]
    if catalog_name:
        name = catalog_name.lower().replace(':', '-')
        name = name.replace('/', '_').replace('\\', '_').replace(' ', '_')
        name = ''.join(c for c in name if c.isalnum() or c in '_-.')
        name = name.strip('_.')
    else:
        name = f'sym_{stub["sym_idx"]}' if stub['sym_idx'] is not None else f'func_{idx}'
    sel = stub['selector']
    sel_tag = f'_sel{sel:03d}' if sel is not None else ''
    return f'{base}_f{idx:03d}_{name}{sel_tag}{tag}.fas'


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    fpath = sys.argv[1]
    outdir = None
    trim = '--trim' in sys.argv
    verbose = '--verbose' in sys.argv

    for i, arg in enumerate(sys.argv):
        if arg == '--outdir' and i + 1 < len(sys.argv):
            outdir = sys.argv[i + 1]

    if not os.path.exists(fpath):
        print(f'error: file not found: {fpath}')
        sys.exit(1)

    if outdir:
        os.makedirs(outdir, exist_ok=True)
    else:
        base = os.path.splitext(os.path.basename(fpath))[0]
        outdir = os.path.join(os.path.dirname(fpath) or '.', f'{base}.split')
        os.makedirs(outdir, exist_ok=True)

    # ── 解析 ──────────────────────────────────────────────────────────────────
    info = parse_fas4(fpath)
    bytecode = info['bytecode']
    nsyms = info['nsyms']
    seg0_sub = info['segments'][0]['sub_count']
    seg1_dec = info['res_data_decrypted']
    seg1_enc = info['res_data_encrypted']
    key = info['key']
    trailer = info['trailer']

    print(f'File: {fpath}')
    print(f'  nsyms: {nsyms}')
    print(f'  bytecode: {len(bytecode)} B')
    print(f'  seg1 encrypted: {len(seg1_enc)} B')
    print(f'  seg1 decrypted: {len(seg1_dec)} B')
    if key:
        print(f'  XOR key: {key.hex()} ({len(key)} B)')
    else:
        print(f'  XOR key: (not found)')

    # ── 符号表 → 函数目录 ──────────────────────────────────────────────────────
    catalog = []
    catalog_offset_map = {}
    symbol_map = {}  # sym_idx → name (fallback)
    if seg1_dec:
        resource_items, sym_list, string_list = parse_resource_stream(seg1_dec)
        resource_gvars, function_gvars = build_mvar_tables(seg1_dec, nsyms)
        catalog = build_function_catalog(resource_gvars, function_gvars)
        for name, offset in catalog:
            catalog_offset_map[offset] = name

        # 构建符号索引 → 名称映射（fallback，从 extract_symbol_names）
        str_list = extract_symbol_names(seg1_dec)
        for s in sym_list:
            _ = s
        for sym_idx in range(nsyms):
            name = resolve_symbol_name(sym_idx, str_list, seg0_sub)
            if name:
                symbol_map[sym_idx] = name

        # 也尝试从 gvar 提取名称
        for idx in range(min(nsyms, len(function_gvars))):
            val = function_gvars[idx]
            if isinstance(val, tuple) and len(val) == 2 and val[0] == 'SYMBOL':
                name = str(val[1])
                if idx not in symbol_map or symbol_map[idx] != name:
                    symbol_map[idx] = name

        if verbose:
            bias = infer_code_ref_bias(function_gvars)
            print(f'  resource items: {len(resource_items)}')
            print(f'  symbols: {len(sym_list)}')
            print(f'  strings: {len(string_list)}')
            print(f'  function catalog: {len(catalog)} entries (bias={bias})')
            for name, off in catalog[:10]:
                print(f'    {name:30s} @ {off}')
            if len(catalog) > 10:
                print(f'    ... ({len(catalog) - 10} more)')
                for name, off in catalog[-3:]:
                    print(f'    {name:30s} @ {off}')

    # ── 提取桩 ────────────────────────────────────────────────────────────────
    stubs = extract_stubs(bytecode)
    if not stubs:
        print('error: no function stubs found')
        sys.exit(1)

    dispatch_count = sum(1 for s in stubs if s['is_dispatch'])
    self_count = len(stubs) - dispatch_count
    print(f'  stubs: {len(stubs)} total ({self_count} self-contained, {dispatch_count} dispatch)')

    # ── 构建 magic header ──────────────────────────────────────────────────────
    with open(fpath, 'rb') as f:
        raw = f.read()
    moff, magic = find_fas4_magic(raw)
    if moff is None:
        raise ValueError('Not a valid FAS4 file')
    after = moff + len(magic)
    magic_header = raw[:after]

    # seg0 total_size = raw number after magic
    size_end = raw.find(b'\r\n', after)
    total_size = int(raw[after:size_end])
    magic_header += f'{total_size}\r\n'.encode('ascii')

    if not trailer:
        trailer = '\n;@lisp https://atlisp.cn'

    # ── 输出每个桩 ──────────────────────────────────────────────────────────────
    written = 0
    for i, stub in enumerate(stubs):
        # 优先级: 1) catalog name  2) gvar name  3) symbol_map  4) sym_XXXX
        cat_name = catalog_offset_map.get(stub['offset'], '')
        if not cat_name and stub['sym_idx'] is not None:
            cat_name = symbol_map.get(stub['sym_idx'], '')

        tag = ''
        if trim and not stub['is_dispatch']:
            seg1_for_func = None
            sub_cnt = 0
            tag = '_trim'
        else:
            seg1_for_func = seg1_dec
            sub_cnt = info['res_items']

        out_bytes = build_single_function_fas(
            magic_header, stub['data'],
            seg1_for_func, sub_cnt,
            trailer,
        )

        fname = make_filename(stub, i, fpath, cat_name, tag)
        out_path = os.path.join(outdir, fname)
        with open(out_path, 'wb') as f:
            f.write(out_bytes)

        sizes = f'{len(stub["data"]):5d} B stub'
        if seg1_for_func is None:
            sizes += ' (trimmed)'
        else:
            sizes += f' + {len(seg1_for_func)} B seg1'

        info_str = ''
        if stub['is_dispatch']:
            info_str = f' [dispatch sel={stub["selector"]}]'
        if cat_name:
            info_str += f' [{cat_name}]'
        print(f'  [{i:3d}] {fname} ({sizes}){info_str}')
        written += 1

    print(f'\nDone: {written} files → {outdir}')


if __name__ == '__main__':
    main()
