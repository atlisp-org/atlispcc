# FAS4 文件格式详解

本文档描述 FAS4（AutoLISP Fast-Load）二进制文件格式。它是对本项目编译器（`compiler/fas_writer.py`）、解析器（`core/fas_core.py` / `decompiler/fas4_decompiler.py`）实际实现的精确说明，并与 AutoCAD 编译器产物（`tests/fun-cad.fas`）逐字节兼容。

参考源码：
- 写入：`compiler/fas_writer.py`
- 资源段构建：`compiler/resource_builder.py`
- 解析/解密：`core/fas_core.py`
- 反编译：`decompiler/fas4_decompiler.py`
- 操作码：`docs/opcodes.md`

---

## 1. 文件总布局

```
┌─────────────────────────────────────────────┐
│ ① 文件头  FAS4_MAGIC + <total_size>\r\n      │
├─────────────────────────────────────────────┤
│ ② seg0     <nsyms> $ + 函数字节码            │
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
- `total_size` 表示 seg0 负载（`<nsyms> $` + 字节码）的**统计长度**，随布局而异：
  - **紧凑 stub 格式**（CAD 编译器输出，`compact=True`）：`total_size = len(seg0) + 1`。
    其中 `seg0` 为 `<nsyms> $` 后的纯字节码。CAD 实测恒等（cross/m2/m3/multi/sh/
    lambda_test 六份产物）。旧公式 `len(seg0_payload) - 2` 仅在 nsyms<10（头 3 字节）时碰巧相等。
  - **自包含格式**（`compact=False`）：`total_size = len(seg0_payload)`（完整覆盖）。
  - `Fas4Parser.parse` 目前按 total_size 切字节码，紧凑 stub 文件会因此丢掉末尾 2 字节
    （对 CAD 产物与 atlispcc 产物一致，不影响反编译结果；见 §6）。

### 1.2 seg0（代码段，明文）

```
<nsyms> $          # ASCII：符号槽数（resource 注册顺序）
<bytecode>         # 函数字节码（见 docs/opcodes.md）
16 24 0d 0a        # SEG_TERMINATOR = b"\x16\x24\r\n"
```

**nsyms**：符号槽总数。单函数 = 去重符号数；多函数由编译器内部符号表分配（与去重数可能不同）。

**seg0 尾部 2 字节**：仅存在于紧凑 stub 格式。它们**不是独立的 argc 编码**，
而是最后一个函数指令序列末尾的 2 字节（随函数体变化，如 t9→`00 01`、t10→`01 00`、
t11→`01 00`），落在 `total_size` 统计之外、终止符之前。`FasWriter` 不再显式生成
「尾部 2 字节」——字节码本身自然以这些指令结尾，写盘时 `total_size` 少计 2 即可。

> 历史版本曾把 seg0 尾部 2 字节描述为「首个函数 argc 编码」，经 AutoCAD 逐字节
> 对比证实为误判：尾部内容由末段指令决定，与函数参数个数无固定对应。

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

加密与解密使用同一函数（可逆）。`core/fas_core.py` 中 `decrypt_stream` 与 `fas_writer.py` 中 `_rolling_xor` 等价。

```
key_old = key[0];  kp = 1
for i in 0..len(data)-1:
    if kp >= len(key): kp = 0
    key_new = key[kp]
    result[i] = data[i] ^ key_new ^ key_old   # 两个字节异或
    key_old = key_new
    kp += 1
```

即每个明文字节与 key 中相邻两字节的 XOR 值异或。`mixor_decrypt`（`core/fas_core.py`）用 key 自复制展开，效果相同。

---

## 3. 资源流（seg1 明文）格式

解密后的资源流是一系列单字节操作码及其操作数。由 `ResourceBuilder.build()` 生成，解析见 `core.fas_core.parse_resource_stream`。

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

### 3.2 资源操作码（resource opcodes）

资源流是一套**独立于字节码操作码**的指令集。它与 seg0 操作码共享部分字节值（如 `14`/`32`/
`33`/`5c`/`09`/`06`），但语义不同——资源码在**加载期**构建符号/字符串/常量表和函数目录，
由 `core.fas_core.build_mvar_tables` 的栈模拟解析，**不参与函数执行**。

#### 3.2.1 数据常量

| 字节 | 名称 | 编码 | 栈效果（加载期） |
|------|------|------|------------------|
| `32` | PUSH_INT8 | `32 <b:1>` | 压入有符号整数（−128~127） |
| `33` | PUSH_INT32 | `33 <i32:4>` | 压入四字节整数 |
| `3b` | PUSH_REAL | `3b <ascii>\x00` | 压入 NUL 结尾实数 |
| `01` | PUSH_NIL | `01` | 压入 nil |
| `02` | PUSH_T | `02` | 压入 T |
| `00` | NIL（占位） | `00` | 同 PUSH_NIL（压入 nil） |

#### 3.2.2 符号/字符串注册

| 字节 | 名称 | 编码 | 说明 |
|------|------|------|------|
| `5b` | 符号块 | `5b <name1>\x00 <name2>\x00 ... \x00` | 连续符号合并为一块，末尾额外 `\x00`；遇字符串/常量/`5c` 分块；符号名**统一大写**（`_enc_sym`） |
| `56` | 单符号块 | `56 <name>\x00 00` | 单个符号，**保留原始大小写**（不经过 `_enc_sym` 大写化）；用于命令模块注册的 `vl-ACAD-defun`（t14 实测：`Vl-ACAD-defun`） |
| `55` | 字符串块 | `55 <count:2>` + 每个 `55 <len:2> <bytes>` | 字符串字面量注册；`count`=串数 |

> 符号名统一大写（`ResourceBuilder._enc_sym`），字符串字面量保持原样。
> **例外**：`56` 单符号块保留原始大小写——命令模块注册的 `vl-ACAD-defun`
> 在资源流中是 `Vl-ACAD-defun`（CAD 原样编码，t14_command 实测）。

#### 3.2.3 栈操作

| 字节 | 名称 | 编码 | 栈效果 |
|------|------|------|--------|
| `09` | PUSH_G | `09 <idx:2>` | 压入 gvar 槽 `idx` 的值（引用已注册符号） |
| `03` | PUSH_VALUE | `03 <idx:2>` | 同 PUSH_G（模块代码中引用常量槽） |
| `06` | SETQ_G | `06 <idx:2>` | 弹出栈顶写入 gvar 槽 `idx` |
| `0a` | POP | `0a` | 弹出丢弃 |
| `0b` | DUP | `0b` | 复制栈顶 |
| `2a` | CONS | `2a` | 弹出两值构造点对（代码引用：`start . end`） |
| `28` | CAR | `28` | 弹出点对取左部 |
| `29` | CDR | `29` | 弹出点对取右部 |
| `39` | BUILD_LIST | `39 <n:2>` | 弹出 n 值构造列表（常量列表/代码引用范围表收尾） |
| `23` | NOT | `23` | 逻辑取反 |
| `24` | ATOM | `24` | 原子判断 |

> **列表常量收尾规则**（t12_quote 实测）：
> - **普通列表** `'(a b c)` → 逐项注册后 `39 <count>`（BUILD_LIST），count=项数
> - **dotted 点对** `'(1 . 2)` → 逐项注册后**单字节 `2a`**（CONS）收尾，无 `39 <count>`
> - `ResourceBuilder._emit_const` 对 dotted 常量（`('LIST', items, True)`）输出 `2a`，
>   普通列表输出 `39 <count>`，与 CAD 逐字节一致。

#### 3.2.4 函数/模块注册

| 字节 | 名称 | 编码 | 说明 |
|------|------|------|------|
| `14` | 模块头 | `14 01 01 01 00` | 资源流/模块代码开头标记 |
| `15` | 模块头（备用） | 同 `14` | — |
| `3a` | DEFCODE | `3a` | 弹出栈上 `(name, start, module)` 三元组注册函数目录；stub 最后一个追加 `3a 01` |
| `43` | GVARINIT | `43 <var_pos:2> <st_init:2>` | 弹出栈顶 `st_init` 个值，倒序填入 `var_pos..var_pos+st_init-1` 槽；`module_id` 非空时写入函数 gvar 表 |
| `35`/`51` | FUNC_REF | `35 <argc> <idx:2> 01` | 引用函数目录中 `idx` 处函数（命令模块代码调用 `vl-ACAD-defun` 注册命令，t14 实测） |
| `1c` | INIT_DONE | `1c` | 模块初始化完成标记 |
| `16` | END_DEFUN | `16` | 函数/模块代码结束 |
| `5c` | GET_LOCAL_WIDE | `5c 00 00` | DEFCODE 前的固定序列（压入局部槽 0） |

#### 3.2.5 其他（编码识别/跳转/计数）

| 字节 | 名称 | 编码 | 说明 |
|------|------|------|------|
| `1e`/`1f` | ALPHA/BETA | `1e <v>` | 编译器内部标记 |
| `1a`/`1b`/`0c`/`0d`/`0e`/`3c`/`3d`/`07` | 索引/短跳转 | `op <u16>` | 解析时按长度跳转，不产生资源项 |
| `57`/`67`/`69`/`6a`/`6b`/`68` | 长跳转 | `op <i32>` | 模块代码中控制流（4 字节偏移） |
| `37` | BUILD_LIST_ALT | `37 <n:2>` | 同 BUILD_LIST（备用） |
| `20`/`62`/`63`/`3e`/`3f`/`38`/`40`/`21` | 空操作 | `op` | 单字节，无操作数 |

> `build_mvar_tables`（`core/fas_core.py`）逐操作码模拟栈，`GVARINIT(0x43)` 将栈顶值
> 写入资源 gvar 表（`table0`）或函数 gvar 表（`table1`，当 `module_id` 非空时）。
> `parse_resource_stream` 仅按长度切分以枚举符号/字符串/引用项。

### 3.2a 操作码 vs 资源码

| 维度 | 字节码操作码（seg0） | 资源码（seg1） |
|------|---------------------|----------------|
| 位置 | seg0（函数字节码） | seg1（加密资源流明文） |
| 作用 | **运行时执行**（压栈/调用/跳转/算术） | **加载期建表**（注册符号/字符串/常量/函数目录） |
| 定义 | `asm/opcodes.py`（`OPCODES` 表） | `ResourceBuilder` 生成 / `core.fas_core` 解析 |
| 引用方式 | 函数体按符号槽编址（`PUSH_G`/`PUSH_VALUE`/`USUBR`） | 符号槽顺序即 seg1 注册顺序 |
| 共享字节 | 与资源码共用 `14`/`32`/`33`/`5c`/`09`/`06` 等字节值 | 同上 |
| 典型指令 | `PUSH_G`、`USUBR`、`JUMP`、`JMP32_IFNOT`、`FIX_ADD` | `5b`、`55`、`43`、`3a`、`39`、`1c` |

关键区分：同一字节 `32` 在 seg0 是运行时压整数，在 seg1 是加载期压整数值供 GVARINIT
建表；`5c` 在 seg0 是 `GET_LOCAL_WIDE`（读局部变量），在 seg1 是 DEFCODE 前的固定标记。

### 3.3 GVARINIT 规则（CAD 实测逆向）

模块部分与 DEFCODE 部分使用固定的 st_init / var_pos：

- **模块注册**：`GVARINIT(0, 函数数 + 2)`
- **函数注册**：`GVARINIT(0, 符号数)`
- **DEFCODE**：`GVARINIT(函数数 + 2, 函数数)`

> **c: 命令模式偏移**（t14_command 实测）：含命令函数时，模块注册段额外注册
> `vl-ACAD-defun`（`56` 单符号块），使模块注册 GVARINIT st_init 与 DEFCODE
> 基址 `var_pos` 各 +1：
> - 模块注册：`GVARINIT(0, 函数数 + 3)`
> - DEFCODE：`GVARINIT(函数数 + 3, 函数数)`
>
> `vl-ACAD-defun` 仅注册于模块注册段（resource_gvars），**不进**符号表
> `symtab.entries`，因此函数注册 GVARINIT st_init（= nsyms）与 seg0 引用的
> function_gvars 槽位保持不变。

### 3.4 DEFCODE（函数定义）

每个函数一个，`<offset>` 为该函数在 seg0 中的字节偏移（相对 `<nsyms> $` 头之后）：

```
5c 00 00          # GET_LOCAL_WIDE 0
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

### 3.5a 命令模块代码（`build_command_module_code`，t14_command 实测）

含 `c:` 命令函数时，模块代码对每个命令用 `FUNC_REF`（`35`）调用 `vl-ACAD-defun`
注册为 CAD 命令。n=2 实测字节序：

```
14 01 00 00 00            # DEFUN 头
09 04 00 0a 57 00 00 00 00  # PUSH_G 4; POP; JUMP 0        （占位）
09 06 00 06 03 00         # PUSH_G 6; SETQ_G 3            （函数值入目标槽）
09 03 00 35 01 02 00 01 0a # PUSH_G 3; FUNC_REF 2; PUSH_NIL; POP（vl-ACAD-defun 注册）
09 03 00 0a 57 00 00 00 00  # PUSH_G 3; POP; JUMP 0
09 05 00 06 01 00         # PUSH_G 5; SETQ_G 1
09 01 00 35 01 02 00 01 0a # PUSH_G 1; FUNC_REF 2; PUSH_NIL; POP
09 01 00 16               # PUSH_G 1; END_DEFUN
```

槽位公式（n=2 与 golden 逐字节一致，n>2 按同一规律外推，`var_pos = 函数数 + 3`）：
- `a = var_pos - 1 - i`（占位）、`b = var_pos + 函数数 - 1 - i`（函数值槽）
- `c = 函数数 + 1 - i`（i < n-1），末个 `c = 1`（对应尾部 `PUSH_G 1`）
- 满足 `a_i = c_{i-1}`（i>=1）与末 `c=1` 的自我一致性

每个命令函数：`PUSH_G <a>; POP; JUMP 0` + `PUSH_G <b>; SETQ_G <c>` +
`PUSH_G <c>; FUNC_REF <vl_idx>; PUSH_NIL; POP`。`FUNC_REF` 的 `35 <argc> <idx:2> 01`
中 `idx` 为 `vl-ACAD-defun` 在函数目录中的索引（t14 实测为 2）。

---

## 4. 符号槽（symbol_slots）

符号槽 = 资源流中符号/字符串的注册顺序。字节码中的 `PUSH_VALUE <idx>` 等按此编址。

### 4.1 收集算法（CAD：函数逆序 + 每函数字节码引用序逆序）

本项目 `compiler/cad_symbols.py` 复刻 CAD 顺序：

1. 函数名按**源码逆序**（最后一个函数名在槽 0）
2. 顶层表达式符号（defun 之外）——排在函数体内建之前（混合时）
3. 按函数逆序，每函数内按"字节码引用序"**逆序**收集函数体符号
   （调用中参数先于函数名压栈，逆序后函数名/外层调用在前）
4. 每函数参数紧跟其函数体符号之后
5. 递归/跨函数引用产生**重复函数名槽**（CAD 行为）
6. **符号名统一大写**（CAD 符号槽全大写，AutoLISP 大小写不敏感）

示例 `(defun f2 (a b) (+ a b))`：`['f2', '+', 'b', 'a', 'f2']`（`f2` 递归出现两次）。

### 4.2 nsyms

```
nsyms = len(entries) - 模块注册符号数 + 1
```

- **无顶层表达式**：模块注册符号数 = 函数数 → `nsyms = len(entries) - 函数数 + 1`
- **含顶层表达式**：模块注册符号数 = 函数数 + 顶层表达式符号数（`top_level_count`）

即函数注册 GVARINIT 的 st_init。多函数时**小于**符号槽去重数。

---

## 5. 两种布局对比

| 特性 | 自包含格式 | 紧凑 stub 格式（CAD） |
|------|-----------|----------------------|
| 生成 | `stub_format=False` | `stub_format=True`（默认 CLI） |
| seg0 END_DEFUN | 有（`16`） | 无 |
| DEFUN 头 | `14 <gvar_ref:2> <offset:2>` | `14 <argc>x3 00` |
| 符号寻址 | function_gvars 间接 | 符号槽直接 |
| USUBR/FUNC | 5/6 字节 | 3 字节 |
| GET_LOCAL | `05 <slot:1>` | `5c <slot:2>`（GET_LOCAL_WIDE） |
| 函数目录 | mvar 表重建 | DEFCODE 序列 |
| 参考产物 | `tests/cad/i18n-cad.fas` / `tests/cad/i18n.fas` | `tests/fun-cad.fas` |

---

## 6. 快速解析流程（core.fas_core.parse_fas4）

1. 定位 `FAS4_MAGIC`，读 `<total_size>`，提取 payload
2. 匹配 `(\d+) \$` 得 nsyms，其余为 bytecode（seg0）
3. 在文件尾找 `CRUNCH_MARKER` 定位密钥，回溯校验得 key
4. 匹配 `(\d+) (\d+) \$` 得 seg1 长度与 items，切出加密数据
5. 用 `decrypt_stream(seg1, key)` 解密得到资源流明文
