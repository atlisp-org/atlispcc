"""解析 seg1 模块注册段，建立 {符号名大写: gvar槽} 映射。

模块注册段结构（ResourceBuilder 输出）：
  `14 01 01 01 00` 模块头 + 代码引用 + 模块注册符号（5b/56/55 记录）
  + `01 01`（2 个 PUSH_NIL）+ GVARINIT(0, N) + POP。

gvar 槽从 1 起算（槽 0 为模块头/代码引用）。commands 混合模式把函数名
逆序置前、顶层符号在后；`56 vl-ACAD-defun` 占 1 槽。
"""

import struct


def build_module_gvar_map(seg1_decrypted: bytes):
    """返回 {符号名大写: gvar槽} 与 {字符串值大写: gvar槽}。"""
    data = seg1_decrypted
    gvar = {}
    i = 5  # 跳过 `14 01 01 01 00` 模块头
    slot = 1
    # 代码引用（32/33 + 2a + 39）占据栈底 1 项，但 gvar 槽从 1 起（槽 0 是它）
    # ——模块注册符号实际从 gvar 槽 1 开始。直接按记录序计数。
    while i < len(data):
        b = data[i]
        if b == 0x5b:
            j = i + 1
            while True:
                z = data.index(0, j)
                if z == j:
                    break
                name = data[j:z].decode("latin1")
                gvar.setdefault(name.upper(), slot)
                slot += 1
                j = z + 1
                if data[j] == 0:
                    break
            i = j + 1
        elif b == 0x56:
            j = data.index(0, i + 1)
            gvar.setdefault(data[i + 1 : j].decode("latin1").upper(), slot)
            slot += 1
            i = j + 2
        elif b == 0x55:
            cnt = struct.unpack("<H", data[i + 1 : i + 3])[0]
            j = i + 3
            for _ in range(cnt):
                ln = struct.unpack("<H", data[j : j + 2])[0]
                j += 2
                gvar.setdefault(data[j : j + ln].decode("latin1").upper(), slot)
                slot += 1
                j += ln
            i = j
        elif b == 0x01 and i + 6 < len(data) and data[i + 2] == 0x43:
            vp = struct.unpack("<H", data[i + 3 : i + 5])[0]
            st = struct.unpack("<H", data[i + 5 : i + 7])[0]
            if vp == 0:
                break  # 模块 GVARINIT：模块注册结束
            i += 1
        else:
            i += 1
        if i > 100000:
            break
    return gvar
