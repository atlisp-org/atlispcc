# ZWCAD ZELX 格式与转换算法（逆向自 LispConverter.exe）

> 逆向来源：ZWCAD 2017 SDK 的 `LispConverter.exe`（"FAS&VLX Converter"，MFC GUI）
> 与 @lisp 样本对（`base-whole.fas` ↔ `base-whole.zelx` 等）。
> 工具：`python -m tools.zelx_info <x.zelx> [-s] [-o payload.bin]`。

## 1. 概述

`.zelx` 是 ZWCAD 的 Lisp 可执行应用容器（分发格式），内部为 **`!ZAS` 容器**，
装载一个 **滚动 XOR 加密** 的 ZWCAD 重编码 FAS 载荷。

```
┌─────────────────────────────────────────────────────────────┐
│ [0:64]   ZAS 头                                             │
│ [64:X]   段1 目录 (ZwStream 序列化, 明文)                    │
│ [X:Y]    段2 = [len:u32][field2:u32][1:u32] + XOR加密载荷    │
│ [Y:]     尾部 = [key_len:u32][0:u32][2:u32][密钥前缀]\n;fas4 crunch\n; │
└─────────────────────────────────────────────────────────────┘
```

## 2. ZAS 头（64 字节）

| 偏移 | 值 | 含义 |
|---|---|---|
| 0 | `!ZAS` | 魔数 |
| 4 | 0 | |
| 8 | 1 | |
| 0C | 4 | 子项数（推测） |
| 10-1C | 0×4 | |
| 20 | 1 | |
| 24 | 3 | |
| 28 | 52 | |
| 2C | **X** | 段2 偏移（绝对文件偏移） |
| 30 | **Y** | 段尾（≈文件尾） |
| 34 | **Z** | 段1 长度（= X − 64） |
| 38 | **W** | 未知 |
| 3C | 0 | |

## 3. 段1 目录（明文）

`ZwStream` 紧凑序列化，opcode 语言与段2 代码区相同。实测（base-whole）：

```
01 04 03 03 00
34 df 00 2f 00 00       # [34][idx u16][2f][val u16]
34 de 00 2f 01 00
34 dd 00 2f 02 00       # idx 递减 (df,de,dd...)
05 07 00
34 dc 00 13 01 db 00 01 00
2a 16 c1 00 00 00
01 01 01 01 00
...
```

opcode 集合：`34/13/2a/24/27/2f/1b/16/0d/03/05/07/22/01/04`。
`34 <u16> 2f <u16>` 的索引逐次减 1（df,de,dd → a3,a2,a1），
疑似 ZwStream 的**可变宽整数 + 回退引用**编码（索引宽随值变化）。
完整语义需微型受控样本逐 opcode 定位。

## 3.1 段2 载荷头字段

载荷明文头部（除加密外）恒定前缀：

```
01 01 01 01 00 41 00 42 <xx:2> 00 00 40 45 01 00 [57 符号...]
```

`xx` 随包变化：base=590, at-math=827, at-block=683, @lisp=6171
（暂未与符号数/代码长度直接对应，待样本确认）。

## 4. 段2 加密载荷

- 子头：`[载荷长:u32][field2:u32][1:u32]`（载荷长 = Y − X − 12）
- 载荷 = 明文 滚动 XOR(密钥)
- **密钥**：尾部 `[key_len:u32][0:u32][2:u32][随机前缀]\n;fas4 crunch\n;`
  - 密钥 = `随机前缀`（key_len − 15 字节）+ `\n;fas4 crunch\n;`（15 字节）
  - 实测 key_len ∈ {21,24,25}（与 AutoCAD FAS4 一致，21..26）

**滚动 XOR**（与 AutoCAD FAS4 相同，可逆）：

```
key_old = key[0]; kp = 1
for i in range(len(data)):
    if kp >= len(key): kp = 0
    key_new = key[kp]
    out[i] = data[i] ^ key_new ^ key_old
    key_old = key_new; kp += 1
```

## 5. 载荷内容（ZWCAD 重编码 FAS）

解密后为 ZWCAD 的符号/字符串表 + 代码区：

- **符号表**：空字符结尾的符号名，带类型标记前缀（`W`、`@` 等），
  与源 fas seg1 符号集高度重合（实测 base-whole 151/238 重合）
- **字符串块**：`55 <count:2>` + 每个 `55 <len:2> <bytes>`（与 AutoCAD 资源流同构）
- **代码区**：ZwStream 紧凑字节码（`34/24/2a/27/1b/22/16` opcode）

## 6. 转换算法（fas → zelx）

1. 解析 AutoCAD FAS4（seg0 字节码 + seg1 滚动 XOR 资源流）
2. 把符号/字符串/函数重编码为 ZWCAD 载荷（ZwStream 格式）
3. 生成随机密钥，对载荷做滚动 XOR 加密
4. 组装 ZAS：64B 头 + 段1 目录 + 段2 子头/加密载荷 + 密钥尾部

### 6.1 载荷 = fas seg1 的重编码（已确认）

解密后的载荷与 fas seg1（解密后）高度相似：

- **符号块**：相同符号序列，标记 `5b` → `57`（ZWCAD 符号 opcode）
- **字符串块**：`55 <count:2> <len:2> <bytes>` 完全相同（偏移几乎一致）
- **模块头**：`14 01 01 01 00` → `01 01 01 01 00`
- **代码引用区**：`32 00 32 03 02 03 00 00 2a 39 01 00` → `41 00 42 <XX:2> 00 00 40 45 01 00`
- **DEFCODE**：`3a 5c 00 00 33 <off>` → `46 2f 00 00 42 <off>`（opcode 重映射）

### 6.2 ZWCAD 使用独立字节码（重新编译）

fas seg0（AutoCAD 字节码，5523B）与载荷代码区（594B）的 opcode 分布完全不同：
AutoCAD 用 `03/35/09/0a/06/32/51/57/67/5c`，ZWCAD 用 `34/2a/16/24/1b/27`。
**不是操作码重映射，而是 ZWCAD 编译器重新生成代码**。

代码区过小（594B vs 函数体 5523B）→ 推测 zelx 载荷主要含符号/字符串/注册代码，
函数体可能由 ZWCAD 在加载时与 .fas 结合，或 zelx 非自包含（待验证）。

## 7. 已破解 / 待破解

**已破解（可验证）：**
- 容器结构（ZAS 头字段、三段布局、密钥尾部）
- 加密/解密算法（滚动 XOR，密钥定位）→ `tools/zelx_info.py` 已验证 4 样本
- **载荷 ENCODE（fas seg1 → zelx 载荷）**：上下文感知 opcode 重映射，
  `tools/zelx_build.py` 对微型样本 **逐字节一致**（15/15）
- **段1目录 ENCODE（fas seg0 → 函数字节码）**：opcode 重映射，同样 15/15
- **混合重映射**：资源段用资源映射，模块代码段（INIT_DONE 之后）用函数映射；
  模块代码引用长度（`41 00 42 <len>`）更新为自身长度。复杂文件
  （base-whole/at-math/@lisp）结构自洽、可解密（非逐字节一致）
- **头部 W = nsyms**；**子头 field2 = fas seg1 items（GVARINIT+INIT_DONE 计数）**
- ZWCAD opcode 表（资源流 & 函数代码两套）：

  | fas | 资源流→载荷 | 函数→段1目录 | 语义 |
  |---|---|---|---|
  | 01 | 22 | 22 | PUSH_NIL |
  | 03 | 03 | 24 | PUSH_VALUE |
  | 06 | 27 | 27 | SETQ_G |
  | 09 | 34 | 34 | PUSH_G |
  | 0a | 2a | 2a | POP |
  | 0d | - | 36 | JMP16_IFNOT |
  | 0e | - | 37 | JMP16_IF |
  | 14 | 01 | 01 | DEFUN/模块头 |
  | 16 | 03 | 03 | END_DEFUN |
  | 18 | - | 05 | INIT_ARGS |
  | 19 | - | 06 | CLEAR_ARGS |
  | 1c | 2c | - | INIT_DONE |
  | 32 | 41 | 41 | PUSH_INT8 |
  | 35 | - | 0d | USUBR |
  | 39 | 45 | 45 | BUILD_LIST |
  | 3a | 46 | - | DEFCODE |
  | 43 | 49 | - | GVARINIT |
  | 57 | 16 | 16 | JUMP |
  | 5b | 57 | - | 符号块 |
  | 5c | 2f | 2f | GET_LOCAL |
  | 67 | - | 1a | BR_IF_TRUE |
  | 2a | 40 | - | CONS |

**待破解：**
- **复杂文件压缩重编码**：ZWCAD 压缩载荷（模块代码重编码 + 符号重排）。
  当前 `tools/zelx_build.py` 已产出自洽结构（保持 fas 符号顺序、混合映射、
  长度更新），但未复刻 ZWCAD 的压缩；**ZWCAD 能否加载需真实验证**

> 微型样本（`samples/zelx-reversing/`）由 GUI 自动化（`tools/lisp_converter_auto.py`，
> UIA + ctypes）产出。样本矩阵：t1(1函数/1参/算术)、tiny(2函数)、s3f(3函数)、
> sstr(字符串)、szero(0参)、snest(嵌套调用)、aif/awhile/arec/asetq/astrcat/
> aarith/acons/aand/aor（if/while/递归/setq/strcat/多参/cons/and/or）。

## 8. zelx → fas（逆向恢复）

`tools/zelx_to_fas.py` / `atlispcc unzelx` 从 `.zelx` 恢复 `.fas`（LispConverter 的逆向）：

```
zelx → 解密载荷 → 逆向重映射资源段/模块代码段 → fas seg1
     → 逆向重映射段1目录 → fas seg0
     → 组装 fas（magic/total_size/加密 seg1/密钥尾）
```

- 微型样本 15/15 恢复的 fas 与原始**逐字节一致**（seg0+seg1）
- `fas → zelx → fas` 往返一致
- 官方 zelx（含 ZWCAD 压缩）恢复的 fas 可正常反编译（base-whole → 802 行 Lisp）
- 使用：`python -m tools.zelx_to_fas <x.zelx> <x.fas>` 或 `atlispcc unzelx`

