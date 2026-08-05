#!/usr/bin/env python3
"""ZWCAD ZELX → AutoCAD FAS4 转换器（逆向 LispConverter 的 ENCODE）。

zelx 载荷 = 重映射的 fas seg1（资源段 + 模块代码段），
段1目录 = 重映射的 fas seg0（函数字节码）。逆向 opcode 映射即可恢复 fas。

用法：
  python -m tools.zelx_to_fas <input.zelx> [output.fas]
"""
import struct
import os
import sys

# ─── 反向 opcode 映射（ZWCAD → AutoCAD）───────────────────────────────────────
# 资源流
_REV_RES = {
    0x22: 0x01, 0x34: 0x09, 0x27: 0x06, 0x2a: 0x0a, 0x01: 0x14, 0x03: 0x16,
    0x2c: 0x1c, 0x40: 0x2a, 0x41: 0x32, 0x42: 0x33, 0x45: 0x39, 0x46: 0x3a,
    0x49: 0x43, 0x16: 0x57, 0x57: 0x5b, 0x2f: 0x5c,
}
# 函数代码
_REV_FN = {
    0x01: 0x14, 0x34: 0x09, 0x2f: 0x5c, 0x05: 0x18, 0x24: 0x03, 0x41: 0x32,
    0x0d: 0x35, 0x45: 0x39, 0x27: 0x06, 0x2a: 0x0a, 0x36: 0x0d, 0x37: 0x0e,
    0x1a: 0x67, 0x16: 0x57, 0x06: 0x19, 0x22: 0x01, 0x00: 0x00, 0x02: 0x03,
    0x1e: 0x1e, 0x1f: 0x1f, 0x23: 0x23, 0x28: 0x28, 0x29: 0x29,
    0x46: 0x46, 0x47: 0x47, 0x48: 0x48, 0x49: 0x49, 0x4a: 0x4a, 0x4b: 0x4b,
    0x4c: 0x4c, 0x4d: 0x4d, 0x4e: 0x4e, 0x4f: 0x4f, 0x50: 0x50, 0x42: 0x33,
    0x0b: 0x0b, 0x0f: 0x0f,
}
# ZWCAD 操作码大小（反向解析用）
_F1 = (0x00, 0x03, 0x22, 0x2a, 0x23, 0x28, 0x29, 0x0b, 0x0f, 0x1e, 0x1f,
       0x46, 0x47, 0x48, 0x49, 0x4a, 0x4b, 0x4c, 0x4d, 0x4e, 0x4f, 0x50)
_F2 = (0x41,)
_F3 = (0x05, 0x06, 0x0d, 0x24, 0x27, 0x2f, 0x34, 0x36, 0x37, 0x45)
_F5 = (0x01, 0x16, 0x1a, 0x42)


def _rolling_xor(data: bytes, key: bytes) -> bytes:
    out = bytearray(len(data)); key_old = key[0]; kp = 1
    for i in range(len(data)):
        if kp >= len(key):
            kp = 0
        key_new = key[kp]
        out[i] = data[i] ^ key_new ^ key_old
        key_old = key_new; kp += 1
    return bytes(out)


def _parse_zelx(path):
    from tools.zelx_info import parse_zelx
    return parse_zelx(path)


# ZWCAD 资源流操作码大小（定位 INIT_DONE 用）
_Z1 = (0x00, 0x03, 0x22, 0x2a, 0x40, 0x46, 0x23, 0x28, 0x29, 0x0b, 0x0f, 0x1e,
       0x1f, 0x47, 0x48, 0x4a, 0x4b, 0x4c, 0x4d, 0x4e, 0x4f, 0x50)
_Z2 = (0x41,)
_Z3 = (0x27, 0x2f, 0x34, 0x36, 0x37, 0x45, 0x0d)
_Z5 = (0x01, 0x16, 0x1a, 0x42, 0x49)


def _find_init_done_zw(payload: bytes):
    """在 ZWCAD 载荷中定位 INIT_DONE（0x2c）之后，即模块代码起始。"""
    i = 0
    while i < len(payload):
        op = payload[i]
        if op == 0x57:
            i += 1
            while i < len(payload):
                if payload[i] == 0:
                    i += 1; break
                e = payload.find(b"\x00", i)
                if e < 0: return None
                i = e + 1
            continue
        if op == 0x55:
            if i + 1 >= len(payload): return None
            cnt = struct.unpack_from("<H", payload, i + 1)[0]; j = i + 3
            for _ in range(cnt):
                if j + 2 > len(payload): return None
                ln = struct.unpack_from("<H", payload, j)[0]; j += 2 + ln
            i = j; continue
        if op == 0x2c:
            return i + 1
        if op in _Z1: i += 1
        elif op in _Z2: i += 2
        elif op in _Z3: i += 3
        elif op in _Z5: i += 5
        else: i += 1
    return None


def _rev_resource(b: bytes) -> bytes:
    out = bytearray(); i = 0
    while i < len(b):
        op = b[i]
        if op == 0x57:                      # ZWCAD 符号块 -> 5b
            out.append(0x5b); i += 1
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
        if op == 0x49:                      # GVARINIT（5 字节）
            out.append(0x43); out.extend(b[i + 1:i + 5]); i += 5; continue
        if op in _F1:
            out.append(_REV_RES.get(op, op)); i += 1; continue
        if op in _F2:
            out.append(_REV_RES.get(op, op)); out.extend(b[i + 1:i + 2]); i += 2; continue
        if op in _F3:
            out.append(_REV_RES.get(op, op)); out.extend(b[i + 1:i + 3]); i += 3; continue
        if op in _F5:
            out.append(_REV_RES.get(op, op)); out.extend(b[i + 1:i + 5]); i += 5; continue
        out.append(_REV_RES.get(op, op)); i += 1
    return bytes(out)


def _rev_function(b: bytes) -> bytes:
    """反向函数代码（ZWCAD → AutoCAD）。保留 00 03 清理，03 按上下文。"""
    out = bytearray(); i = 0
    while i < len(b):
        op = b[i]
        if op == 0x00:
            if i + 1 < len(b) and b[i + 1] == 0x03:
                out.append(0x00); out.append(0x03); i += 2; continue
            out.append(0x00); i += 1; continue
        if op == 0x03:
            # END_DEFUN 或 PUSH_VALUE[0]（前有 00 已处理）
            out.append(0x16); i += 1; continue
        if op == 0x01:                      # DEFUN（5 字节，参数不映射）
            out.append(0x14); out.extend(b[i + 1:i + 5]); i += 5; continue
        if op in _F1:
            out.append(_REV_FN.get(op, op)); i += 1; continue
        if op in _F2:
            out.append(_REV_FN.get(op, op)); out.extend(b[i + 1:i + 2]); i += 2; continue
        if op in _F3:
            out.append(_REV_FN.get(op, op)); out.extend(b[i + 1:i + 3]); i += 3; continue
        if op in _F5:
            out.append(_REV_FN.get(op, op)); out.extend(b[i + 1:i + 5]); i += 5; continue
        out.append(_REV_FN.get(op, op)); i += 1
    return bytes(out)


def zelx_to_fas(zelx_path: str, fas_path: str) -> dict:
    from tools.zelx_info import parse_zelx
    zr = parse_zelx(zelx_path)
    z = open(zelx_path, "rb").read()
    X = zr["X"]
    seg1dir = z[64:X]
    payload = zr["payload"]
    nsyms = struct.unpack_from("<I", z, 0x38)[0]
    items = zr["sub"][1]

    # 载荷 -> fas seg1：按 INIT_DONE 的 ZWCAD 形式（2c）拆分
    mc_off = _find_init_done_zw(payload)
    if mc_off is None:
        mc_off = len(payload)
    seg1 = _rev_resource(payload[:mc_off])
    seg1 += _rev_function(payload[mc_off:])

    # 段1目录 -> fas seg0（函数代码，去尾部追加的 03）
    seg0 = _rev_function(seg1dir)
    # 去掉末尾的 END_DEFUN 追加标记（紧凑 stub seg0 无尾 END_DEFUN）
    if seg0.endswith(b"\x16"):
        seg0 = seg0[:-1]

    # 组装 fas
    nsyms_hdr = f"{nsyms} $".encode("ascii")
    seg0_payload = nsyms_hdr + seg0
    total_size = len(seg0_payload) - 2
    prefix = os.urandom(8)
    key = prefix + b"\n;fas4 crunch\n;"
    enc_seg1 = _rolling_xor(seg1, key)
    seg1_hdr = f"{len(enc_seg1)} {items} $".encode("ascii")
    # zelx 不携带 crunch 日期，恢复的 fas 不伪造日期（保持确定性输出）。
    trailer = bytes([len(key)]) + key + b"$;"

    magic = b"\r\n FAS4-FILE ; Built by atlispcc!\r\n"
    data = magic + f"{total_size}\r\n".encode("ascii") + seg0_payload + \
           b"\x16\x24\r\n" + seg1_hdr + enc_seg1 + trailer
    with open(fas_path, "wb") as fh:
        fh.write(data)
    return dict(seg0_len=len(seg0), seg1_len=len(seg1), nsyms=nsyms, items=items,
                size=len(data))


def main():
    if len(sys.argv) < 2:
        print("Usage: python -m tools.zelx_to_fas <input.zelx> [output.fas]")
        return 1
    src = sys.argv[1]
    if not os.path.exists(src):
        print(f"Error: file not found: {src}", file=sys.stderr)
        return 1
    out = sys.argv[2] if len(sys.argv) > 2 else os.path.splitext(src)[0] + ".fas"
    r = zelx_to_fas(src, out)
    print(f"built {out}: seg0={r['seg0_len']} seg1={r['seg1_len']} "
          f"nsyms={r['nsyms']} items={r['items']} size={r['size']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
