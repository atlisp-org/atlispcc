# FAS4 文件格式详解

本文档描述 FAS4（AutoLISP Fast-Load）二进制文件格式。它是对本项目编译器（`compiler/fas_writer.py`）、解析器（`core/fas_core.py` / `decompiler/fas4_decompiler.py`）实际实现的精确说明，并与 AutoCAD 编译器产物（`tests/cad/t01_math_cad.fas` 等 t-series golden）逐字节兼容。

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
`nsyms` 也决定字节码编址宽度：`nsyms > 256` 时大文件走 **5 字节 USUBR / 6 字节 FUNC**
（见 §5）。

**seg0 为空（纯顶层文件，无 defun）**：`FasWriter` 以空格占位
` $\r\n` 替代 `SEG_TERMINATOR`（CAD set5/setcmp 实测）。此时文件头
`total_size = len(seg0) + 1 = 1`，`<nsyms> $` 后无字节码。

**seg0 尾部 2 字节**：仅存在于紧凑 stub 格式。它们**不是独立的 argc 编码**，
而是最后一个函数指令序列末尾的 2 字节（随函数体变化，如 t9→`00 01`、t10→`01 00`、
t11→`01 00`），落在 `total_size` 统计之外、终止符之前。`FasWriter` 不再显式生成
「尾部 2 字节」——字节码本身自然以这些指令结尾，写盘时 `total_size = len(seg0) + 1`
少计 2 即可（CAD 实测恒等：cross/m2/m3/multi/sh/lambda_test 六份产物）。

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
| `35`/`51` | FUNC_REF | `35 <argc:1> <idx:2> 01` | 引用函数目录中 `idx` 处函数（命令模块代码调用 `vl-ACAD-defun` 注册命令，t14 实测 `35 01 <idx:2> 01`；大文件用 `51 <argc:1> <idx:2> <flags> 00` 宽格式） |
| `1c` | INIT_DONE | `1c` | 模块初始化完成标记 |
| `16` | END_DEFUN | `16` | 函数/模块代码结束 |
| `5c` | GET_LOCAL_WIDE | `5c 00 00` | DEFCODE 前的固定序列（压入局部槽 0） |

#### 3.2.5 其他（编码识别/跳转/计数）

| 字节 | 名称 | 编码 | 说明 |
|------|------|------|------|
| `1e`/`1f` | ALPHA/BETA | `1e <v>` | 编译器内部标记 |
| `0c`/`0d`/`0e`/`3c`/`3d`/`07` | 索引/短跳转 | `op <u16>` | 解析时按长度跳转，不产生资源项 |
| `1a`/`1b` | （伪指令） | — | 非真实资源码；「对齐」出现实为 `GVARINIT(0x43)` 的 st_init 操作数错位（见 opcodes.md「伪指令说明」） |
| `57`/`67`/`69`/`6a`/`68` | 长跳转 | `op <i32>` | 模块代码中控制流（4 字节偏移） |
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
- **函数注册**：`GVARINIT(0, 符号数)`（st_init = 注册符号数 + 1 = **nsyms**）
- **DEFCODE**：`GVARINIT(函数数 + 2, 函数数)`（`gv_var_pos = len(func_names) + top_level_count + 2 (+commands)`）

> **c: 命令模式偏移**（t14_command 实测）：含命令函数时，模块注册段额外注册
> `vl-ACAD-defun`（`56` 单符号块），使模块注册 GVARINIT st_init 与 DEFCODE
> 基址 `var_pos` 各 +1：
> - 模块注册：`GVARINIT(0, 函数数 + 3)`
> - DEFCODE：`GVARINIT(函数数 + 3, 函数数)`
>
> `vl-ACAD-defun` 仅注册于模块注册段（resource_gvars），**不进**符号表
> `symtab.entries`，因此函数注册 GVARINIT st_init（= nsyms）与 seg0 引用的
> function_gvars 槽位保持不变。
>
> **commands + 顶层表达式混合**（atlisp_u.lsp，502 函数）：函数名已单独注册
> （每个独立 `5b` 块，首命令后插入 `56 vl-ACAD-defun 00 00`），其余顶层符号/
> 常量仍需登记；模块注册 GVARINIT `st_init = module_entries_count + 2 + commands`，
> DEFCODE 基址 `var_pos` 同样 +commands。此时 `symtab_idx+1` 不再等于实际 gvar
> 槽，模块代码符号引用（USUBR/PUSH_G/FUNC）须经 `_gvar_map.py` 重建 gvar 表后
> `_offset_slots` 二次重映射。

> **module_id 槽**（t12 修复，`build_module_id_slots`）：函数表 GVARINIT 的
> `module_id` 槽（`var_pos + st_init`）存放结构化 LIST/CONS 常量（如
> `'(a b c)`、`'(1 . 2)`、`'(1 2 3)`）；原子型 SYMBOL/STRING 是该符号的重复槽，
> 不登记。反编译器 `_gvar_item` 越界查询该槽以还原链式 quote 常量。

### 3.4 DEFCODE（函数定义）

每个函数一个，`<offset>` 为该函数在 seg0 中的字节偏移（相对 `<nsyms> $` 头之后）：

```
5c 00 00          # GET_LOCAL_WIDE 0
32 <offset:1>     # PUSH_INT8（offset>127 时用 33 <i32>）
5b <name>\x00 00  # 函数名符号
3a 01             # DEFCODE + 01
```

DEFCODE 把 `(module, start, name)` 三元组注册进函数目录；seg0 偏移即 start。

- **stub 格式按源码逆序注册**（`func_names = list(reversed(func_names))`）。
- 只有**最后一个** DEFCODE 追加 `01`（stub 格式），其余仅 `3a`。
- **函数名统一大写**（`_enc_sym`）；`-lambda-` 内嵌函数保留小写
  （`-LAMBDA-` 是错的），多 `-lambda-` 目录键为 `-lambda-#N`、编码仍为 `-lambda-`。
- 多函数文件在 DEFCODE 之前发 `_func_ranges_bytes`（函数代码引用范围表）：
  `32 <start> 32 <end> 2a ... 39 <count> 00`，从末尾逆序。

> **kwote 内嵌 `-lambda-`**（`(function (lambda ...))` / 立即应用机制，v0.1.18+）：
> 每个内嵌 lambda 独立 DEFCODE，在 GVARINIT(0, nsyms) 前置发射、按 seg0 偏移
> **逆序**（CAD 实测：先发射的 lambda 被 GVARINIT 后弹出，分配更高槽——t3 槽 18、
> t4 槽 17、t5 槽 16，nsyms=19）。字节：`5c 00 00 32 <off> 5b -lambda- 00 00 3a`。
> 宿主函数代码引用 end 用下一个**非内嵌**函数起始，内嵌项 end 用自身结束偏移
> （nested_ends）。`-lambda-` 不进 `symtab.entries`（无普通符号槽），仅 DEFCODE
> 区注册——故 fas_nsyms 比 codegen_nsyms 大 1，seg0 引用须 `gvar 槽 - 2`
> （`_patch_usubr_idx` 的 offset 修正）。

### 3.5 模块代码

CAD 把源码中的**顶层表达式**（defun 之外的 setq/set 等）编译进 seg1 模块代码，
seg0 只含 defun 函数。三种构建器：

- `build_module_code(n_funcs)`：纯函数文件（无顶层表达式、无命令）固定函数注册尾。
- `build_command_module_code(n_funcs)`：含 c: 命令（§3.5a）。
- `_build_cad_module_code(...)`：含顶层表达式（cli.py 逆向实现，最通用）。

**`build_module_code`**（纯函数文件）：

```
14 01 00 00 00    # DEFUN 头
09 02 00          # PUSH_G 槽2（模块符号）
0a                # POP
57 00 00 00 00    # JUMP
09 03 00 06 01 00 # PUSH_G + SETQ_G
09 01 00 16       # PUSH_G + END_DEFUN
```

- n_funcs=0（无函数）：`DEFUN头 + 顶层表达式 + END_DEFUN`。
- n_funcs>1：每函数 `PUSH_G <a>; POP; JUMP; PUSH_G <b>; SETQ_G <c>`
  （a=n_funcs+1-i、b=2n+1-i、c=n-i），末 `PUSH_G 1; END`。

**`_build_cad_module_code`**（含顶层表达式，逆向规则）：

- 符号引用使用 **gvar 槽 = 符号槽 + 1**；顶部 `PUSH_G <模块注册符号数+1>; POP` 占位。
- 顶层 setq → `PUSH_G <值槽+1>; DUP; SETQ_G <变量槽+1>`（中间 pair 无 DUP、
  最后一对 DUP；`'()`/`nil` → PUSH_NIL；整数字面量内联 `PUSH_INT8/INT32`；
  复杂值退回通用 codegen 路径后按真实 SETQ_G 指令定位补 DUP——不碰 USUBR
  的 0x06 索引字节）。
- 每个顶层语句后 POP（最后一句除外）。
- `(in-package :@)` → `PUSH_VALUE <pkg槽>; FUNC_REF in-package`。
- **函数注册尾**：`JUMP + PUSH_G <b>; SETQ_G <c>`（b = `2*n_funcs+1 +
  top_level_count - i`，c = 函数符号槽 + 1），组间 `PUSH_G <c>; POP; JUMP`。
- **post-form 分组**：最后一个 defun 之后的顶层语句排到函数注册尾之后
  （`n_post_forms`，支持多个）；首个 defun 之前的顶层语句（globals）排在最前。
- **顶层 lambda 绑定**（纯顶层 `(set/setq 'sym (lambda ...))`，`-lambda-` SUBR）：
  setq 协议 `JUMP 0; PUSH_G <-lambda-槽+1>; DUP; SETQ_G <sym>`（`-lambda-` gvar
  槽 = `_lam_slot + 1` = `top_level_count + 2 - i + 1`，setq-lambda.lsp 实测）。
- commands+顶层混合时经 `_gvar_map.py` 重建 gvar 表后二次生成（§3.3）。

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
| seg0 END_DEFUN | 有（`16`） | 无（函数间 `16` 分隔，CLEAR_ARGS 由 codegen 生成） |
| DEFUN 头 | `14 <gvar_ref:2> <offset:2>` | `14 <argc>x3 00`（变参 b4=01；循环函数 b1=argc+直接体并发循环深度） |
| 符号寻址 | function_gvars 间接 | 符号槽直接（gvar 槽 = 符号槽 + 1，操作数 = gvar 槽 - 1） |
| USUBR/FUNC | 5/6 字节 | 3 字节（小文件）；**nsyms>256 时 5/6 字节宽格式** |
| GET_LOCAL | `05 <slot:1>` | `5c <slot:2>`（GET_LOCAL_WIDE） |
| 函数目录 | mvar 表重建 | DEFCODE 序列 |
| 参考产物 | `tests/cad/i18n-cad.fas` / `tests/cad/i18n.fas` | `tests/cad/t01_math_cad.fas` 等 t-series golden |

> **大文件宽格式**（v0.1.19+，atlisp_u.lsp 502 函数实测）：符号槽 >255 时
> USUBR 用 5 字节 `35 <argc> <idx16> <flags=3>`、FUNC 用 6 字节
> `51 <argc> <idx16> <flags=1> 00`（`asm/opcodes.py` `encode_usubr`/`encode_func`，
> flags 内联了原 `00 03` 清理）。`_patch_usubr_idx`/`_offset_slots` 用
> `short_subr=False` 反汇编并按宽格式重编码（patch delta=0，函数偏移不再错位）。

---

## 6. 快速解析流程（core.fas_core.parse_fas4）

1. 定位 `FAS4_MAGIC`，读 `<total_size>`，提取 payload
2. 匹配 `(\d+) \$` 得 nsyms，其余为 bytecode（seg0）
3. 在文件尾找 `CRUNCH_MARKER` 定位密钥，回溯校验得 key
4. 匹配 `(\d+) (\d+) \$` 得 seg1 长度与 items，切出加密数据
5. 用 `decrypt_stream(seg1, key)` 解密得到资源流明文

---

## 7. 探索文档索引（v0.1.18+）

> 说明：本节是文档索引，指向各探索/设计文档，不重复内容。下表列出的
> 文档与 FAS4 格式/工具链直接相关，详细结论见原文。

| 文档 | 主题 | 状态 |
|------|------|------|
| `docs/compilation-process.md` | 编译流程（lexer/parser/analyzer/codegen/reference/优化） | [实现] |
| `docs/cad-stub-format.md` | CAD 紧凑 stub 格式（DEFUN 头/符号槽/资源段） | [规范] |
| `docs/zelx-format.md` | ZELX/`!ZAS` 容器与 W4LZ 压缩（逆向 LispConverter.exe） | [推断] |
| `docs/lasm.md` | Lisp Assembly 语言（反汇编输出/汇编输入） | [实现] |
| `docs/opcodes.md` | FAS4 操作码表 | [规范] |
| `docs/opcode-comparison.md` | AutoCAD vs ZWCAD 操作码对照（重编译而非重映射） | [推断] |
| `docs/cad-testing.md` | CAD 真机测试方法（cad_verify.py / 快照 / 对话框 killer） | [实现] |
| `docs/feature-plan.md` | 语言特性补全计划（P0 set/eval/apply/cond-T …） | [实现] |
| `docs/development-plan.md` | 主开发计划：§3.x 根因、§9-§12 各阶段探索结论 | [实现] |
| `docs/progress-report.md` | 滚动进度报告（每周期指标/成果/遗留） | [实现] |

### 关键格式结论（v0.1.18–v0.1.21）

- 实数常量编译为资源段 REAL 槽（CAD byte-identity 逐字节一致）。
- 超范围整数字面量按截断实数处理（`PUSH_INT32` 有符号解码一致）。
- 链式 quote 常量解码：函数表 GVARINIT `module_id` 槽 + dotted 对渲染（t12）。
- 紧凑 stub DEFUN 反汇编显示 argc 原始字节（`14 argc argc argc 00`）。
- 大小写：vla-/vlax- 前缀保留原大小写，方法名首字母大写；值位置 `T`/`t` 注册符号槽。
- 大文件宽格式：符号槽 >255 用 5 字节 USUBR（`35 argc idx16 flags=3`）、
  6 字节 FUNC（`51 argc idx16 flags=1 00`）；小文件保持 3 字节。
- commands+顶层混合：`compiler/_gvar_map.py` 解析 seg1 模块注册段，`_offset_slots`
  二次生成模块代码按实际槽位修正 USUBR/PUSH_G/FUNC（atlisp_u.lsp 502 函数）。
- `top_level_count` 由收集器 `module_reg_count` 推导（避免高估）。
- 链接器输出与 CAD golden 逐字节一致。
- 反汇编每行前显示指令原始十六进制字节列。

### 关键格式结论（v0.1.21–v0.1.22）

- **顶层 `(set/setq 'sym (lambda ...))`**（纯顶层文件）：CAD 用内嵌 `-lambda-`
  SUBR（seg0 完整紧凑 stub `14 <argc>x3 00` + GET_LOCAL + INIT_ARGS + 体 +
  CLEAR_ARGS + END_DEFUN，函数间 `16` 分隔、最后无 END），模块代码 setq 协议
  `JUMP 0; PUSH_G <-lambda-槽+1>; DUP; SETQ_G <sym>`；`-lambda-` 槽 = 顶层
  符号数 + 2 - i（gvar = +1，setq-lambda 实测 @::fasext 29、@::vlx 28），DEFCODE
  区小写注册。资源段布局（第一区/函数目录/第二区/fg 表/多 DEFCODE）见
  `cad-stub-format.md §2.5d`（setq-lambda.lsp byte-identity，v0.1.22+）。
- **`command` 内建**：资源段注册名为 `ads-cmd`（非 `COMMAND`）；调用字节
  `FUNC3 + NIL + PUSH_NIL + NIL`（base-function 真机实测）。
- **字符串大小写敏感**：`"date"` 与 `"DATE"` 是两个不同槽（`.upper()` 会错误
  合并）；REAL 常量按值匹配资源段槽（codegen symtab 槽可能偏离 GVARINIT）。
- **值位置 `T`/`t`**：均注册符号槽并用 `PUSH_VALUE` 引用（cond else `(t expr)`
  键与值位置 `T` 共享槽，SymbolTable 归一化到 `T`）；nil 恒内联 PUSH_NIL。
- **`/ 局部变量`**：`_al-bind-alist` 符号 + `(quote (locals...))` 常量独立注册
  （0x56 保留大小写，不进 5b 合并块）；绑定字节
  `PUSH_G <const>; FUNC 1; NIL; PUSH_NIL; NIL; POP`；CLEAR_ARGS = argc + locals。
- **module_id 槽**：函数表 GVARINIT 的 `module_id` 槽存结构化 LIST/CONS 常量
  （t12 链式 quote 解码，`build_module_id_slots`）。

### engine/（SBCL AutoLISP 运行时，v0.1.21+ 开始）

`engine/` 是一个实验性 SBCL/ASDF 运行库（`atlisp.asd`，`src/{packages,values,
reader,env,eval,builtins,main}.lisp`），用于脱离 CAD 环境执行 AutoLISP 源码。

- 值模型：AutoLISP 数据映射到 CL 原生值（nil/t/int/double-float/string/AL 包符号/cons）。
- `al-eval-source` / `al-run-file` / `al-repl` 为公共 API（`:atlisp` 包导出）。
- 与 FAS4 关系：作为跨校验器（同一源码：编译器产物 vs 引擎求值结果），
  不参与 FAS 字节码编解码。
