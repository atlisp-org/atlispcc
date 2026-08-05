#!/usr/bin/env python3
"""Compare a .fas ↔ .zelx pair to reverse ZWCAD's re-encoding.

用法:
  python -m tools.zelx_diff <x.fas> <x.zelx> [--full]

解密两端（AutoCAD FAS4 seg1 与 ZWCAD !ZAS 载荷），输出：
- 符号/字符串序列对比
- 55 字符串块对齐
- 载荷代码区（ZwStream opcode）直方图
"""
import struct, re, sys, argparse, collections, math
from tools.zelx_info import parse_zelx, rolling_xor


def fas_parts(path):
    f = open(path, "rb").read()
    from core.fas_core import find_fas4_magic
    hpos, magic = find_fas4_magic(f)
    if hpos is None:
        raise ValueError("Not a valid FAS4 file")
    i = hpos + len(magic); j = f.find(b"\r\n", i); total = int(f[i:j]); i = j + 2
    j = f.find(b" $", i); nsyms = int(f[i:j]); i = j + 2
    term = f.find(b"\x16\x24\r\n", i); seg0 = f[i:term]
    s1s = term + 4; j = f.find(b" $", s1s)
    seg1len = int(f[s1s:j].split()[0]); seg1 = f[j + 2:j + 2 + seg1len]
    pos = f.find(b"\n;fas4 crunch\n;")
    fkey = None
    for rl in range(6, 12):
        ks = pos - rl; ke = pos + 15
        if f[ks - 1] == (ke - ks):
            fkey = f[ks:ke]; break
    return dict(seg0=seg0, seg1=rolling_xor(seg1, fkey), nsyms=nsyms)


def entropy(b):
    if not b: return 0.0
    c = collections.Counter(b)
    n = len(b)
    return -sum((v / n) * math.log2(v / n) for v in c.values())


def u55_blocks(b):
    blocks = []; i = 0
    while i < len(b):
        if b[i] == 0x55 and i + 1 < len(b):
            cnt = struct.unpack_from("<H", b, i + 1)[0]
            j = i + 3; vals = []
            ok = True
            for _ in range(cnt):
                if j + 2 > len(b): ok = False; break
                ln = struct.unpack_from("<H", b, j)[0]; j += 2
                if j + ln > len(b): ok = False; break
                vals.append(b[j:j + ln]); j += ln
            if ok: blocks.append((i, vals))
            i = j if ok else i + 1
        else:
            i += 1
    return blocks


def main():
    ap = argparse.ArgumentParser(description="Diff .fas ↔ .zelx to reverse ZWCAD re-encode")
    ap.add_argument("fas")
    ap.add_argument("zelx")
    ap.add_argument("--full", action="store_true", help="dump payload hex")
    a = ap.parse_args()
    fp = fas_parts(a.fas)
    zr = parse_zelx(a.zelx)
    payload = zr["payload"]
    print("=== fas ===")
    print(f"  seg0 len {len(fp['seg0'])}  entropy {entropy(fp['seg0']):.3f}")
    print(f"  seg1 len {len(fp['seg1'])}  entropy {entropy(fp['seg1']):.3f}  nsyms {fp['nsyms']}")
    print("=== zelx ===")
    print(f"  payload len {len(payload)}  entropy {entropy(payload):.3f}")
    print(f"  X={zr['X']} Y={zr['Y']} Z={zr['Z']} seg2_sub={zr['sub']} key_len={zr['key_len']}")
    print()
    # symbol/string comparison
    def strings(b):
        return [s[:-1] for s in re.findall(rb"[\x20-\x7e]{3,}\x00", b)]
    fs = strings(fp["seg1"]); zs = strings(payload)
    fs57 = [s.replace(b"[", b"W") if s.startswith(b"[") else s for s in fs]
    common = [x for x in fs57 if x in zs]
    print(f"symbols: fas={len(fs)} zelx={len(zs)} common(after [->W)={len(common)}")
    print(f"  fas-only: {[s[:40] for s in fs if s not in zs][:6]}")
    print(f"  zelx-only: {[s[:40] for s in zs if s not in fs][:6]}")
    print()
    # 55 blocks alignment
    bf = u55_blocks(fp["seg1"]); bz = u55_blocks(payload)
    print(f"55-blocks: fas={len(bf)} zelx={len(bz)}")
    same = sum(1 for a, b in zip(bf, bz) if a[1] == b[1])
    print(f"  blocks with identical content (aligned): {same}")
    print()
    # payload code region (after last string)
    last = max((m.end() for m in re.finditer(rb"[\x20-\x7e]{3,}", payload)), default=0)
    code = payload[last:]
    print(f"payload code region: offset {last}, len {len(code)}, entropy {entropy(code):.3f}")
    print("  opcode hist:", [(hex(o), n) for o, n in collections.Counter(code).most_common(10)])
    print("  fas seg0 hist:", [(hex(o), n) for o, n in collections.Counter(fp['seg0']).most_common(10)])
    if a.full:
        print()
        print("=== payload hex ===")
        for i in range(0, len(payload), 16):
            row = payload[i:i + 16]
            print(f"  {i:04x} {row.hex()}  {''.join(chr(b) if 32 <= b < 127 else '.' for b in row)}")


if __name__ == "__main__":
    main()
