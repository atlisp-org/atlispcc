#!/usr/bin/env python3
"""Lisp/FAS4 → ZWCAD ZELX 写入器（逆向 LispConverter.exe 的 ENCODE）。

流程：
  0. （可选）.lsp 先用 atlispcc 编译器编译成 FAS4
  1. 解析 AutoCAD FAS4（seg0 字节码 + seg1 资源流 + nsyms + items）
  2. 载荷 = remap_stream(seg1)：上下文感知 opcode 重映射（byte-identical）
  3. 段1目录 = enc_seg1dir(seg0)：函数字节码重映射（byte-identical）
  4. 滚动 XOR 加密（随机密钥）
  5. 组装 !ZAS 容器：头 + 段1 + 子头 + 加密载荷 + 密钥尾部

用法：
  python -m tools.zelx_build <input.lsp|input.fas> [output.zelx]
"""
import struct, os, sys, tempfile


# ─── fas seg1 资源流 → zelx 载荷（opcode 重映射）─────────────────────────────
FAS_OP = {
    0x14: 5, 0x43: 5, 0x3a: 1, 0x1c: 1, 0x01: 1, 0x02: 1, 0x0a: 1,
    0x5b: None, 0x55: None, 0x32: 2, 0x33: 5, 0x5c: 3, 0x2a: 1, 0x39: 3,
    0x16: 1, 0x0d: 3, 0x1e: 2, 0x1f: 2,
    0x09: 3, 0x06: 3, 0x57: 5, 0x67: 5, 0x18: 3, 0x19: 3, 0x35: 3, 0x51: 3,
    0x07: 3, 0x0e: 3, 0x3c: 3, 0x3d: 3, 0x34: 3, 0x68: 5, 0x6a: 5, 0x00: 1, 0x0b: 1,
    0x4a: 1, 0x4b: 1, 0x4c: 1, 0x4d: 1, 0x4e: 1, 0x4f: 1, 0x50: 1,
    0x23: 1, 0x24: 1, 0x28: 1, 0x29: 1, 0x46: 1, 0x47: 1, 0x48: 1, 0x49: 1,
    0x20: 1, 0x0f: 1, 0x03: 3,
}
REMAP = {
    0x01: 0x22, 0x06: 0x27, 0x09: 0x34, 0x0a: 0x2a, 0x14: 0x01, 0x16: 0x03,
    0x1c: 0x2c, 0x2a: 0x40, 0x32: 0x41, 0x39: 0x45, 0x3a: 0x46, 0x43: 0x49,
    0x57: 0x16, 0x5b: 0x57, 0x5c: 0x2f, 0x03: 0x03,
}


def remap_stream(b: bytes) -> bytes:
    out = bytearray(); i = 0
    while i < len(b):
        op = b[i]
        if op == 0x5b:
            out.append(REMAP.get(op, op)); i += 1
            while i < len(b):
                if b[i] == 0:
                    out.append(0); i += 1
                    if i < len(b) and b[i] == 0:
                        break
                else:
                    e = b.find(b"\x00", i)
                    if e < 0: e = len(b)
                    out.extend(b[i:e]); i = e
            continue
        if op == 0x55:
            out.append(0x55); i += 1
            cnt = struct.unpack_from("<H", b, i)[0]; out.extend(b[i:i + 2]); i += 2
            for _ in range(cnt):
                ln = struct.unpack_from("<H", b, i)[0]; out.extend(b[i:i + 2]); i += 2
                out.extend(b[i:i + ln]); i += ln
            continue
        # 00 03 = NIL + PUSH_VALUE[0] (call cleanup) -> keep both
        if op == 0x00 and i + 1 < len(b) and b[i + 1] == 0x03:
            out.append(0x00); out.append(0x03); i += 2; continue
        # PUSH_VALUE 0x03: PUSH_VALUE[0] (1B, after call cleanup) vs PUSH_VALUE+u16 (3B)
        if op == 0x03:
            if i + 2 < len(b) and b[i + 1] < 0x80:
                out.append(0x03); out.extend(b[i + 1:i + 3]); i += 3; continue
            out.append(0x03); i += 1; continue
        n = FAS_OP.get(op)
        if n is not None:
            out.append(REMAP.get(op, op))
            if n > 1: out.extend(b[i + 1:i + n])
            i += n
            continue
        out.append(REMAP.get(op, op)); i += 1
    return bytes(out)


# ─── fas seg0 函数字节码 → 段1目录（ZWCAD 函数代码）──────────────────────────
SEG0 = {
    0x14: (5, 0x01), 0x09: (3, 0x34), 0x5c: (3, 0x2f), 0x18: (3, 0x05),
    0x03: (3, 0x24), 0x32: (2, 0x41), 0x35: (3, 0x0d), 0x39: (3, 0x45),
    0x06: (3, 0x27), 0x0a: (1, 0x2a), 0x0d: (3, 0x36), 0x0e: (3, 0x37),
    0x67: (5, 0x1a), 0x57: (5, 0x16), 0x19: (3, 0x06),
    0x00: (1, 0x00), 0x01: (1, 0x22), 0x02: (1, 0x03), 0x0b: (1, 0x0b),
    0x16: (1, 0x03), 0x46: (1, 0x46), 0x47: (1, 0x47), 0x48: (1, 0x48),
    0x49: (1, 0x49), 0x4a: (1, 0x4a), 0x4b: (1, 0x4b), 0x4c: (1, 0x4c),
    0x4d: (1, 0x4d), 0x4e: (1, 0x4e), 0x4f: (1, 0x4f), 0x50: (1, 0x50),
    0x23: (1, 0x23), 0x24: (1, 0x24), 0x28: (1, 0x28), 0x29: (1, 0x29),
    0x33: (5, 0x42), 0x05: (2, 0x05), 0x51: (3, 0x0d), 0x34: (3, 0x42),
    0x0f: (1, 0x0f), 0x1e: (2, 0x1e), 0x1f: (2, 0x1f),
}


def enc_seg1dir(seg0: bytes) -> bytes:
    out = bytearray(); i = 0
    while i < len(seg0):
        op = seg0[i]
        if op == 0x00:
            if i + 1 < len(seg0) and seg0[i + 1] == 0x03:
                out.append(0x00); out.append(0x03); i += 2; continue
            out.append(0x00); i += 1; continue
        if op == 0x03:
            if i + 2 < len(seg0) and seg0[i + 1] < 0x80:
                out.append(0x24); out.extend(seg0[i + 1:i + 3]); i += 3; continue
            out.append(0x03); i += 1; continue
        sz, zop = SEG0.get(op, (1, None))
        if zop is None:
            i += 1; continue
        out.append(zop); out.extend(seg0[i + 1:i + sz]); i += sz
    out.append(0x03)
    return bytes(out)


# ─── 加密与容器 ────────────────────────────────────────────────────────────────
def rolling_xor(data: bytes, key: bytes) -> bytes:
    out = bytearray(len(data)); key_old = key[0]; kp = 1
    for i in range(len(data)):
        if kp >= len(key): kp = 0
        key_new = key[kp]
        out[i] = data[i] ^ key_new ^ key_old
        key_old = key_new; kp += 1
    return bytes(out)


def parse_fas(path: str):
    f = open(path, "rb").read()
    magic = b"\r\n FAS4-FILE ; Do not change it!\r\n"
    i = len(magic); j = f.find(b"\r\n", i); i = j + 2
    j = f.find(b" $", i); nsyms = int(f[i:j]); i = j + 2
    term = f.find(b"\x16\x24\r\n", i); seg0 = f[i:term]
    s1s = term + 4; j = f.find(b" $", s1s)
    parts = f[s1s:j].split(); seg1len = int(parts[0]); items = int(parts[1])
    seg1_enc = f[j + 2:j + 2 + seg1len]
    pos = f.find(b"\n;fas4 crunch\n;")
    fkey = None
    for rl in range(6, 12):
        ks = pos - rl; ke = pos + 15
        if f[ks - 1] == (ke - ks):
            fkey = f[ks:ke]; break
    seg1 = rolling_xor(seg1_enc, fkey)
    return dict(seg0=seg0, seg1=seg1, nsyms=nsyms, items=items)


def compile_lsp_to_fas(lsp_path: str) -> str:
    """用 atlispcc 编译器把 .lsp 编译成临时 .fas，返回临时路径。"""
    import contextlib, io
    from compiler.cli import cmd_compile
    tmp = tempfile.NamedTemporaryFile(suffix=".fas", delete=False)
    tmp.close()
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        cmd_compile(lsp_path, tmp.name)
    return tmp.name


def build_zelx(src_path: str, out_path: str, key_prefix: bytes = b"") -> dict:
    if str(src_path).lower().endswith(".lsp"):
        tmp = compile_lsp_to_fas(src_path)
        try:
            return _build_zelx_fas(tmp, out_path, key_prefix)
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)
    return _build_zelx_fas(src_path, out_path, key_prefix)


def _build_zelx_fas(fas_path: str, out_path: str, key_prefix: bytes = b"") -> dict:
    fa = parse_fas(fas_path)
    payload = remap_stream(fa["seg1"])
    seg1dir = enc_seg1dir(fa["seg0"])
    nsyms = fa["nsyms"]
    items = fa["items"]
    if not key_prefix:
        key_prefix = os.urandom(8)
    key = key_prefix + b"\n;fas4 crunch\n;"
    enc = rolling_xor(payload, key)
    Z = len(seg1dir)
    X = 64 + Z
    Y = X + 12 + len(enc)
    header = struct.pack("<IIII", 0x53415A21, 0, 1, 4) + b"\x00" * 16 + \
             struct.pack("<IIIIII", 1, 3, 52, X, Y, Z) + struct.pack("<II", nsyms, 0)
    sub = struct.pack("<III", len(enc), items, 1)
    tail = struct.pack("<III", len(key), 0, 2) + key
    data = header + seg1dir + sub + enc + tail
    with open(out_path, "wb") as fh:
        fh.write(data)
    return dict(payload_len=len(payload), seg1dir_len=len(seg1dir), nsyms=nsyms,
                items=items, X=X, Y=Y, size=len(data))


def main():
    if len(sys.argv) < 2:
        print("Usage: python -m tools.zelx_build <input.lsp|input.fas> [output.zelx]")
        return 1
    src = sys.argv[1]
    base = os.path.splitext(os.path.basename(src))[0]
    out = sys.argv[2] if len(sys.argv) > 2 else os.path.join(os.path.dirname(src) or ".", base + ".zelx")
    r = build_zelx(src, out)
    print(f"built {out}: payload={r['payload_len']} seg1dir={r['seg1dir_len']} "
          f"nsyms={r['nsyms']} items={r['items']} X={r['X']} Y={r['Y']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
