"""``atlispcc info``：FAS/ZELX/VLX 快速概览（头/段/函数目录/符号/字符串）。

不触发完整反编译：``.fas`` 走 ``core.fas_core.parse_fas4``，``.zelx`` 走
``tools.zelx_info.parse_zelx``，``.vlx`` 走 ``compiler.vlx_builder.parse_vlx``。
"""

import os

def cmd_info(source: str, json_out: bool = False, encoding: str = "ansi") -> dict:
    """FAS/ZELX 快速概览 — 文件头/段规模/函数目录/符号/字符串，不触发完整反编译。

    实现复用 core/fas_core.parse_fas4（与 tools/fas-analyzer.py 同源），
    .zelx 输入走 tools.zelx_info.parse_zelx 解密载荷。
    """
    from core.fas_core import parse_fas4
    from core.fas_core import parse_resource_stream, build_mvar_tables, build_function_catalog

    if source.lower().endswith(".vlx"):
        from compiler.vlx_builder import decode_text, read_vlx

        archive = read_vlx(source)
        load = archive.load()
        info = {
            "file": source,
            "format": "vrtlib-1",
            "size": os.path.getsize(source),
            "marker": archive.marker,
            "load": {
                "tag": load.tag if load else None,
                "name": load.display_name(encoding) if load else None,
                "spec": decode_text(archive.load_spec(), encoding),
            },
            "members": [
                {
                    "name": rec.display_name(encoding),
                    "tag": rec.tag,
                    "size": len(rec.payload),
                    "offset": archive.member_offsets[i + 1],
                }
                for i, rec in enumerate(archive.members())
            ],
        }
        if not json_out:
            print(f"file size      : {info['size']}")
            print(f"marker         : {archive.marker}")
            print(f"load spec      : {info['load']['spec']}")
            for member in info["members"]:
                print(
                    f"member         : {member['name']}  tag={member['tag']}  "
                    f"size={member['size']}  offset={member['offset']}"
                )
        return info

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
