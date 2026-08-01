# FAS4 文件格式详解

本文档描述 FAS4（AutoLISP Fast-Load）二进制文件格式。它是对本项目编译器（`compiler/fas_writer.py`）、解析器（`fas_core.py` / `fas4_decompiler.py`）实际实现的精确说明，并与 AutoCAD 编译器产物（`tests/fun-cad.fas`）逐字节兼容。

参考源码：
- 写入：`compiler/fas_writer.py`
- 资源段构建：`compiler/resource_builder.py`
- 解析/解密：`fas_core.py`
- 反编译：`fas4_decompiler.py`
- 操作码：`docs/opcodes.md`

---

## 1. 文件总布局

```
┌─────────────────────────────────────────────┐
│ ① 文件头  FAS4_MAGIC + <total_size>\r\n      │
├─────────────────────────────────────────────┤
│ ② seg0     <nsyms> $ + 函数字节码            │
│            + seg0 尾部 2 字节                │
│            + 段分隔符 16 24 0d 0a            │
├─────────────────────────────────────────────┤
│ ③ seg1     <len> <items> $ + 加密资源流      │
├─────────────────────────────────────────────┤
│ ④ trailer  <key_len> + 密钥 + $; + 日期      │
└─────────────────────────────────────────────┘
```

### 1.1 文件头

```
\r\n FAS4-FILE ; Do not change it!\r\n     # FAS4_MAGIC，20 字节，恒定
<total_size>\r\n                            # ASCII 十进制：seg0 负载总长度
```

- `FAS4_MAGIC = b"\r\n FAS4-FILE ; Do not change it!\r\n"` —— 判断 FAS 文件的依据，任何编译器产物不变。
- `total_size` = `<nsyms> $` 头 + 字节码的长度（不含尾部与 seg1）。

### 1.2 seg0（代码段，明文）

```
<nsyms> $          # ASCII：符号槽数（resource 注册顺序）
<bytecode>         # 函数字节码（见 docs/opcodes.md）
<tail:2>           # 段尾 2 字节
16 24 0d 0a        # SEG_TERMINATOR = b"\x16\x24\r\n"
```

**nsyms**：符号槽总数。单函数 = 去重符号数；多函数由编译器内部符号表分配（与去重数可能不同）。

**seg0 尾部 2 字节**（CAD 编码首个函数参数数）：

| 首个函数 argc | tail 字节 |
|---------------|-----------|
| argc > 0      | `<argc> 00` |
| argc = 0      | `00 03`    |

例：`(defun f2 (a b))` → `02 00`；`(defun f ())` → `00 03`。

### 1.3 seg1（资源段，加密）

```
<len> <items> $   # ASCII：加密数据长度 + 记录数（GVARINIT + INIT_DONE 计数）
<encrypted>       # 滚动 XOR 加密的资源流
```

**items** = `count_resource_records()` 统计的资源流中 `GVARINIT`(0x43) 与 `INIT_DONE`(0x1c) 记录总数。

### 1.4 trailer（尾部）

```
<key_len:1>       # 密钥总长度（21~26）
<key>             # 随机前缀 + "\n;fas4 crunch\n;"（15 字节固定标记）
$;                # 分隔
A<M>/<D>/<YY>     # 编译日期，如 A8/1/26（无前导零）
```

- `CRUNCH_MARKER = b"\n;fas4 crunch\n;"`（15 字节）位于密钥**末尾**，是密钥定位锚点。
- 密钥总长默认 23（含标记），与 AutoCAD 一致。前 `23-15=8` 字节为随机前缀。
- `find_key()`：定位 `CRUNCH_MARKER`，向前 6~11 字节回溯，校验密钥长度字节（`key_start - 1` == 密钥长）。

---

## 2. 加解密算法（双字节滚动 XOR）

加密与解密使用同一函数（可逆）。`fas_core.py` 中 `decrypt_stream` 与 `fas_writer.py` 中 `_rolling_xor` 等价。

```
key_old = key[0];  kp = 1
for i in 0..len(data)-1:
    if kp >= len(key): kp = 0
    key_new = key[kp]
    result[i] = data[i] ^ key_new ^ key_old   # 两个字节异或
    key_old = key_new
    kp += 1
```

即每个明文字节与 key 中相邻两字节的 XOR 值异或。`mixor_decrypt`（`fas_core.py`）用 key 自复制展开，效果相同。

---

## 3. 资源流（seg1 明文）格式

解密后的资源流是一系列单字节操作码及其操作数。由 `ResourceBuilder.build()` 生成，解析见 `fas_core.parse_resource_stream`。

### 3.1 总体结构

```
┌──────────────────────────────────────────────┐
│ 模块头     14 01 01 01 00                    │
│ 代码引用   32 00 32 <len> 2a 39 01 00        │
│ 函数名符号 5b <name>\x00 ... 00              │
│ PUSH_NIL ×2 + GVARINIT(0, 函数数+2) + 0a     │
├──────────────────────────────────────────────┤
│ 函数代码引用 32 00 32 <len> 2a 39 01 00      │
│ 其余符号/字符串（5b/55 块）                  │
│ 5c 00 00 + GVARINIT(0, 符号数) + 0a          │
├──────────────────────────────────────────────┤
│ 每个函数一个 DEFCODE                         │
│ 5c 00 00 32 <offset> 5b <name> 00 00 3a 01   │
│ GVARINIT(函数数+2, 函数数) + 1c (INIT_DONE)  │
├──────────────────────────────────────────────┤
│ 模块代码（入口）                             │
└──────────────────────────────────────────────┘
```

### 3.2 资源操作码

| 字节 | 名称 | 说明 |
|------|------|------|
| `14` | 模块/函数头 | `14 01 01 01 00` 模块头；`14 01 00 00 00` 模块入口 DEFUN |
| `32` | PUSH_INT8 | `32 <b>` 单字节有符号整数 |
| `33` | PUSH_INT32 | `33 <i32>` 四字节整数 |
| `3b` | PUSH_REAL | `3b <ascii>\x00` NUL 结尾实数 |
| `5b` | 符号块 | `5b <name1>\x00 <name2>\x00 ... \x00`（连续符号，末尾额外 `\x00`） |
| `56` | 符号块（备用） | 同 5b |
| `55` | 字符串块 | `55 <count:2>` + 每个 `55 <len:2> <bytes>` |
| `43` | GVARINIT | `43 <var_pos:2> <st_init:2>` 用栈顶 st_init 个值填充符号表 |
| `3a` | DEFCODE | `3a` 用栈上 (name, start, module) 注册函数 |
| `5c` | GET_LOCAL | `5c 00 00`（DEFCODE 前固定序列） |
| `01` | PUSH_NIL | 压入 nil |
| `0a` | POP | 弹出 |
| `1c` | INIT_DONE | 初始化完成 |

### 3.3 GVARINIT 规则（CAD 实测逆向）

模块部分与 DEFCODE 部分使用固定的 st_init / var_pos：

- **模块注册**：`GVARINIT(0, 函数数 + 2)`
- **函数注册**：`GVARINIT(0, 符号数)`
- **DEFCODE**：`GVARINIT(函数数 + 2, 函数数)`

### 3.4 DEFCODE（函数定义）

每个函数一个，`<offset>` 为该函数在 seg0 中的字节偏移（相对 `<nsyms> $` 头之后）：

```
5c 00 00          # GET_LOCAL 0
32 <offset:1>     # PUSH_INT8（offset>127 时用 33 <i32>）
5b <name>\x00 00  # 函数名符号
3a 01             # DEFCODE + 01
```

DEFCODE 把 `(module, start, name)` 三元组注册进函数目录；seg0 偏移即 start。

### 3.5 模块代码

CAD 风格模块入口（`build_module_code`），引用 seg0 中注册的符号：

```
14 01 00 00 00    # DEFUN 头
09 02 00          # PUSH_G 槽2（模块符号）
0a                # POP
57 00 00 00 00    # JUMP
09 03 00 06 01 00 # PUSH_G + SETQ_G
09 01 00 16       # PUSH_G + END_DEFUN
```

---

## 4. 符号槽（symbol_slots）

符号槽 = 资源流中符号/字符串的注册顺序。字节码中的 `PUSH_VALUE <idx>` 等按此编址。

### 4.1 收集算法（CAD 从右到左）

本项目 `compiler/cad_symbols.py` 复刻 CAD 顺序：

1. 所有函数名**源码逆序**（最后一个函数名在槽 0）
2. 从最后一个函数往前收集函数体符号（内建/字符串逆序，参数最后）
3. 递归/跨函数引用产生**重复函数名槽**（CAD 行为）
4. DEFCODE 部分追加函数名重复（末尾）

示例 `(defun f2 (a b) (+ a b))`：`['f2', '+', 'b', 'a', 'f2']`

### 4.2 nsyms

- 单函数：nsyms = 去重符号数（如 f2 → 4）
- 多函数：由编译器内部符号表分配，**可能小于去重数**（CAD 实测逆向尚未完全还原）

---

## 5. 两种布局对比

| 特性 | 自包含格式 | 紧凑 stub 格式（CAD） |
|------|-----------|----------------------|
| 生成 | `stub_format=False` | `stub_format=True`（默认 CLI） |
| seg0 END_DEFUN | 有（`16`） | 无 |
| DEFUN 头 | `14 <gvar_ref:2> <offset:2>` | `14 <argc>x3 00` |
| 符号寻址 | function_gvars 间接 | 符号槽直接 |
| USUBR/FUNC | 5/6 字节 | 3 字节 |
| GET_LOCAL | `05 <slot:1>` | `5c <slot:2>` |
| 函数目录 | mvar 表重建 | DEFCODE 序列 |
| 参考产物 | `bib.fas` / `PDI.fas` | `tests/fun-cad.fas` |

---

## 6. 快速解析流程（fas_core.parse_fas4）

1. 定位 `FAS4_MAGIC`，读 `<total_size>`，提取 payload
2. 匹配 `(\d+) \$` 得 nsyms，其余为 bytecode（seg0）
3. 在文件尾找 `CRUNCH_MARKER` 定位密钥，回溯校验得 key
4. 匹配 `(\d+) (\d+) \$` 得 seg1 长度与 items，切出加密数据
5. 用 `decrypt_stream(seg1, key)` 解密得到资源流明文
