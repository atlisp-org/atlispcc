#!/usr/bin/env python3
"""ZELX (.zelx) 解析/解密工具 — ZWCAD "!ZAS" 容器.

逆向自 LispConverter.exe (ZWCAD 2017 "FAS&VLX Converter") 与 @lisp 样本对。

结构:
  [0:64]  ZAS 头: "!ZAS" + 字段 [0,1,4,0x4,1,3,52, X, Y, Z, W, 0]
          X = 段2 偏移, Y = 段尾(≈文件尾), Z = 段1 长度 (= X-64)
  [64:X]  段1 目录 (ZwStream 序列化, 明文)
  [X:Y]   段2 = [载荷长:u32][field2:u32][1:u32] + 滚动XOR加密载荷
  [Y:]    尾部 = [key_len:u32][0:u32][2:u32][密钥前缀]\n;fas4 crunch\n;

加密: 载荷 = 明文 XOR滚动(密钥), 密钥 = 前缀(随机) + "\n;fas4 crunch\n;"
滚动 XOR: out[i] = in[i] ^ key[kp] ^ key_old
"""
import struct, re, sys, argparse


def rolling_xor(data: bytes, key: bytes) -> bytes:
    out = bytearray(len(data))
    key_old = key[0]
    kp = 1
    for i in range(len(data)):
        if kp >= len(key):
            kp = 0
        key_new = key[kp]
        out[i] = data[i] ^ key_new ^ key_old
        key_old = key_new
        kp += 1
    return bytes(out)


def parse_zelx(path: str):
    z = open(path, "rb").read()
    if z[:4] != b"!ZAS":
        raise ValueError("Not a !ZAS container")
    X = struct.unpack_from("<I", z, 0x2C)[0]
    Y = struct.unpack_from("<I", z, 0x30)[0]
    Z = struct.unpack_from("<I", z, 0x34)[0]
    sub = struct.unpack_from("<III", z, X)
    seg2 = z[X + 12:Y]
    tail = z[Y:]
    cr = tail.find(b";fas4 crunch")
    if cr < 0:
        raise ValueError("No fas4 crunch key marker")
    key = tail[12:cr - 1] + b"\n;fas4 crunch\n;"
    payload = rolling_xor(seg2, key)
    return dict(
        size=len(z), X=X, Y=Y, Z=Z, sub=sub,
        seg2len=len(seg2), key_len=len(key), key=key.hex(),
        payload=payload, tail=tail,
    )


def main():
    ap = argparse.ArgumentParser(description="Parse/decrypt .zelx (ZWCAD !ZAS container)")
    ap.add_argument("zelx", help="input .zelx file")
    ap.add_argument("-o", "--output", help="write decrypted payload to file")
    ap.add_argument("-s", "--strings", action="store_true", help="dump payload strings")
    args = ap.parse_args()
    r = parse_zelx(args.zelx)
    print(f"file size      : {r['size']}")
    print(f"ZAS header X   : {r['X']}  Y: {r['Y']}  Z(seg1 len): {r['Z']}")
    print(f"seg2 sub-hdr   : [len={r['sub'][0]}][{r['sub'][1]}][{r['sub'][2]}]")
    print(f"payload len    : {r['seg2len']}")
    print(f"key len        : {r['key_len']}  key: {r['key']}")
    print(f"payload entropy: {sum((-v/len(r['payload']))*__import__('math').log2(v/len(r['payload'])) for v in __import__('collections').Counter(r['payload']).values()):.3f}")
    if args.strings:
        for m in re.finditer(rb"[\x20-\x7e]{4,}", r["payload"]):
            print("  " + m.group().decode("ascii", "replace")[:80])
    if args.output:
        open(args.output, "wb").write(r["payload"])
        print(f"payload -> {args.output}")


if __name__ == "__main__":
    main()
