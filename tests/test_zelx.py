"""Tests for ZWCAD ZELX build/parse (tools.zelx_build / tools.zelx_info)."""
import os
import struct

from tools.zelx_build import build_zelx
from tools.zelx_info import parse_zelx, rolling_xor

SAMPLES = os.path.join(os.path.dirname(__file__), "..", "samples", "zelx-reversing")


def _extract(path):
    z = open(path, "rb").read()
    X = struct.unpack_from("<I", z, 0x2C)[0]
    Y = struct.unpack_from("<I", z, 0x30)[0]
    seg2 = z[X + 12:Y]
    tail = z[Y:]
    cr = tail.find(b";fas4 crunch")
    key = tail[12:cr - 1] + b"\n;fas4 crunch\n;"
    return z[:64], z[64:X], rolling_xor(seg2, key)


def test_build_zelx_matches_sample():
    """对微型样本，生成的 zelx 与 LispConverter 官方产物逐字节一致。"""
    for name in ["t1", "tiny", "szero", "aif", "arec", "aor"]:
        fas = os.path.join(SAMPLES, f"{name}.fas")
        real = os.path.join(SAMPLES, f"{name}.zelx")
        out = os.path.join(SAMPLES, f"__{name}_gen.zelx")
        try:
            build_zelx(fas, out, key_prefix=b"\x01\x02\x03\x04\x05\x06\x07\x08")
            r = _extract(real)
            m = _extract(out)
            assert r[0] == m[0], f"{name}: header differs"
            assert r[1] == m[1], f"{name}: seg1dir differs"
            assert r[2] == m[2], f"{name}: payload differs"
        finally:
            if os.path.exists(out):
                os.unlink(out)


def test_build_zelx_from_lsp():
    """.lsp 直接生成 zelx，与 .fas 路径载荷一致。"""
    lsp = os.path.join(SAMPLES, "t1.lsp")
    fas = os.path.join(SAMPLES, "t1.fas")
    out_a = os.path.join(SAMPLES, "__t1a.zelx")
    out_b = os.path.join(SAMPLES, "__t1b.zelx")
    try:
        build_zelx(lsp, out_a)
        build_zelx(fas, out_b)
        a = _extract(out_a)[2]
        b = _extract(out_b)[2]
        assert a == b
    finally:
        for p in (out_a, out_b):
            if os.path.exists(p):
                os.unlink(p)


def test_zelx_structurally_consistent():
    """复杂文件生成的 zelx 结构自洽（X/Y/Z、code-ref 长度、可解密）。"""
    fas = os.path.join(SAMPLES, "..", "..", "@lisp.b", "packages", "base", "base-whole.fas")
    if not os.path.exists(fas):
        return  # 大样本不在仓库内
    out = os.path.join(SAMPLES, "__base_gen.zelx")
    try:
        r = build_zelx(fas, out)
        zr = parse_zelx(out)
        assert r["X"] == 64 + r["seg1dir_len"]
        assert r["Y"] == r["X"] + 12 + r["payload_len"]
        assert len(zr["payload"]) == r["payload_len"]
        # code-ref 长度 == 模块代码长度
        ref = struct.unpack_from("<I", zr["payload"], 8)[0]
        assert ref == r["payload_len"] - zr["payload"].find(b"\x2c\x01")
    finally:
        if os.path.exists(out):
            os.unlink(out)
