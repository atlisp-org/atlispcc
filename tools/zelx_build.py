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
    0x57: 0x16, 0x5b: 0x57, 0x5c: 0x2f, 0x03: 0x03, 0x33: 0x42,
}

# 资源流 opcode 大小（与 resource_builder.count_resource_records 一致）
_RSRC_ONE = (0x00, 0x01, 0x02, 0x0a, 0x0b, 0x16, 0x20, 0x23, 0x24, 0x28, 0x29,
             0x2a, 0x3a, 0x62, 0x63)
_RSRC_TWO = (0x1e, 0x1f, 0x32, 0x18, 0x19)
_RSRC_THREE = (0x03, 0x05, 0x06, 0x07, 0x09, 0x0c, 0x0d, 0x0e, 0x1a, 0x1b, 0x34,
               0x37, 0x39, 0x3c, 0x3d, 0x5c, 0x5d, 0x5e)
_RSRC_FIVE = (0x14, 0x15, 0x33, 0x35, 0x51, 0x57, 0x67, 0x68, 0x69, 0x6a, 0x6b)


def find_init_done(b: bytes):
    """返回模块代码起始偏移（INIT_DONE(0x1c) 之后）。"""
    i = 0
    while i < len(b):
        op = b[i]
        if op == 0x5b:
            i += 1
            while i < len(b):
                if b[i] == 0:
                    i += 1; break
                e = b.find(b"\x00", i)
                if e < 0: return None
                i = e + 1
            continue
        if op == 0x55:
            if i + 1 >= len(b): return None
            cnt = struct.unpack_from("<H", b, i + 1)[0]; j = i + 3
            for _ in range(cnt):
                if j + 2 > len(b): return None
                ln = struct.unpack_from("<H", b, j)[0]; j += 2 + ln
            i = j; continue
        if op in (0x3b, 0x56):
            e = b.find(b"\x00", i + 1); i = e + 1 if e >= 0 else i + 1; continue
        if op == 0x1c: return i + 1
        if op == 0x43: i += 5; continue
        if op in _RSRC_ONE: i += 1
        elif op in _RSRC_TWO: i += 2
        elif op in _RSRC_THREE: i += 3
        elif op in _RSRC_FIVE: i += 5
        else: i += 1
    return None


def _remap_resource(b: bytes) -> bytes:
    out = bytearray(); i = 0
    while i < len(b):
        op = b[i]
        if op == 0x5b:
            out.append(REMAP.get(op, op)); i += 1
            while i < len(b):
                if b[i] == 0:
                    out.append(0); i += 1; break
                e = b.find(b"\x00", i)
                if e < 0: e = len(b)
                out.extend(b[i:e]); out.append(0); i = e + 1
            continue
        if op == 0x55:
            out.append(0x55); i += 1
            cnt = struct.unpack_from("<H", b, i)[0]; out.extend(b[i:i + 2]); i += 2
            for _ in range(cnt):
                ln = struct.unpack_from("<H", b, i)[0]; out.extend(b[i:i + 2]); i += 2
                out.extend(b[i:i + ln]); i += ln
            continue
        if op in (0x3b, 0x56):
            e = b.find(b"\x00", i + 1); e = e if e >= 0 else len(b)
            out.extend(b[i:e + 1]); i = e + 1; continue
        # 00 03 = NIL + PUSH_VALUE[0] (call cleanup) -> keep both
        if op == 0x00 and i + 1 < len(b) and b[i + 1] == 0x03:
            out.append(0x00); out.append(0x03); i += 2; continue
        # PUSH_VALUE 0x03: PUSH_VALUE[0] (1B) vs PUSH_VALUE+u16 (3B)
        if op == 0x03:
            if i + 2 < len(b) and b[i + 1] < 0x80:
                out.append(0x03); out.extend(b[i + 1:i + 3]); i += 3; continue
            out.append(0x03); i += 1; continue
        if op == 0x43:
            out.append(0x49); out.extend(b[i + 1:i + 5]); i += 5; continue
        if op in _RSRC_ONE:
            out.append(REMAP.get(op, op)); i += 1; continue
        if op in _RSRC_TWO:
            out.append(REMAP.get(op, op)); out.extend(b[i + 1:i + 2]); i += 2; continue
        if op in _RSRC_THREE:
            out.append(REMAP.get(op, op)); out.extend(b[i + 1:i + 3]); i += 3; continue
        if op in _RSRC_FIVE:
            out.append(REMAP.get(op, op)); out.extend(b[i + 1:i + 5]); i += 5; continue
        out.append(REMAP.get(op, op)); i += 1
    return bytes(out)


def _remap_module_code(b: bytes) -> bytes:
    """模块代码区用函数字节码映射（与段1目录一致，但不追加尾 03）。"""
    out = bytearray(); i = 0
    while i < len(b):
        op = b[i]
        if op == 0x00:
            if i + 1 < len(b) and b[i + 1] == 0x03:
                out.append(0x00); out.append(0x03); i += 2; continue
            out.append(0x00); i += 1; continue
        if op == 0x03:
            if i + 2 < len(b) and b[i + 1] < 0x80:
                out.append(0x24); out.extend(b[i + 1:i + 3]); i += 3; continue
            out.append(0x03); i += 1; continue
        sz, zop = SEG0.get(op, (1, None))
        if zop is None:
            i += 1; continue
        out.append(zop); out.extend(b[i + 1:i + sz]); i += sz
    return bytes(out)


def _patch_code_ref(resource: bytes, mc_len: int) -> bytes:
    """把资源段开头（模块头后）的模块代码引用长度更新为 mc_len。

    引用形式：`41 00 42 <len:4> ... 40 45 01 00`（len>127）或
    `41 00 41 <len:1> 40 45 01 00`（len<=127）。
    """
    # 模块头 `01 01 01 01 00` 之后即代码引用
    if not resource.startswith(b"\x01\x01\x01\x01\x00"):
        return resource
    p = 5
    out = bytearray(resource[:p])
    if resource[p:p + 3] == b"\x41\x00\x42":        # u32 长度
        out += b"\x41\x00\x42" + struct.pack("<I", mc_len)
        out += resource[p + 7:]
    elif resource[p:p + 3] == b"\x41\x00\x41":      # u8 长度
        if mc_len <= 127:
            out += b"\x41\x00\x41" + bytes([mc_len]) + resource[p + 4:]
        else:
            # 长度超界需转 u32 形式
            out += b"\x41\x00\x42" + struct.pack("<I", mc_len) + resource[p + 4:]
    return bytes(out)


def remap_stream(b: bytes) -> bytes:
    """fas seg1 → zelx 载荷：资源段（资源映射）+ 模块代码段（函数映射）。"""
    mc_off = find_init_done(b)
    if mc_off is None:
        return _remap_resource(b)
    resource = _remap_resource(b[:mc_off])
    module_code = _remap_module_code(b[mc_off:])
    resource = _patch_code_ref(resource, len(module_code))
    return resource + module_code


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
    from core.fas_core import find_fas4_magic
    hpos, magic = find_fas4_magic(f)
    if hpos is None:
        raise ValueError("Not a valid FAS4 file")
    i = hpos + len(magic); j = f.find(b"\r\n", i); i = j + 2
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
    if not os.path.exists(src):
        print(f"Error: file not found: {src}", file=sys.stderr)
        return 1
    base = os.path.splitext(os.path.basename(src))[0]
    out = sys.argv[2] if len(sys.argv) > 2 else os.path.join(os.path.dirname(src) or ".", base + ".zelx")
    r = build_zelx(src, out)
    print(f"built {out}: payload={r['payload_len']} seg1dir={r['seg1dir_len']} "
          f"nsyms={r['nsyms']} items={r['items']} X={r['X']} Y={r['Y']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
