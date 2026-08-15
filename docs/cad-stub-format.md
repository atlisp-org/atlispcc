# FAS4 紧凑 stub 格式规范与 AutoCAD 兼容实现

> 本文档是 `atlispcc`（FAS4 编译器/反编译器）对 **AutoCAD 编译器输出格式**
> （紧凑 stub 格式）逆向与兼容实现的完整技术规范。所有结论均基于
> AutoCAD 24.1s 实测验证与 `tests/cad/t01_math_cad.fas`（紧凑 stub）等 t-series golden 与 `tests/cad/i18n-cad.fas` 等
> 参考文件逐字节对比。
>
> 实测成果：本项目编译的单函数 LSP 的 seg0 字节码与 AutoCAD 产物**逐字节一致**
> （t1–t11），且可在 CAD 中加载并正确执行（alert/if/setq/list/中文 全部通过）。

---

## 1. 总览

### 1.1 两种 FAS 布局

| 特性 | 自包含格式 | 紧凑 stub 格式（CAD） |
|------|-----------|----------------------|
| 生成 | `stub_format=False` | `stub_format=True`（CLI 默认） |
| seg0 含 END_DEFUN | 有 | 无（仅多函数分隔符） |
| DEFUN 头 | `14 <gvar_ref:2> <offset:2>` | `14 <argc>x3 00` |
| 符号寻址 | function_gvars 间接 | 符号槽直接（注册序） |
| USUBR/FUNC | 5/6 字节 | 3 字节 |
| 函数目录 | mvar 表重建 | 资源段 DEFCODE 序列 |
| 参考产物 | `tests/cad/i18n-cad.fas` / `tests/cad/i18n.fas` | `tests/cad/t01_math_cad.fas` 等 t-series golden |

### 1.2 文件总布局

```
┌──────────────────────────────────────────────┐
│ ① 文件头  FAS4_MAGIC + <total_size>\r\n       │
│    FAS4_MAGIC = "\r\n FAS4-FILE ; Do not change it!\r\n"
├──────────────────────────────────────────────┤
│ ② seg0（明文）                                │
│    <nsyms> $ + 函数字节码                      │
│    + 段分隔符 16 24 0d 0a                     │
├──────────────────────────────────────────────┤
│ ③ seg1（加密）                                │
│    <len> <items> $ + 滚动 XOR 加密资源流       │
├──────────────────────────────────────────────┤
│ ④ trailer  <key_len> + 密钥 + $; + 日期       │
└──────────────────────────────────────────────┘
```

**total_size（紧凑 stub 格式，CAD 实测恒等）**：`total_size = len(seg0) + 1`，
其中 `seg0 = <nsyms> $ 之后的纯字节码`（不含 `<nsyms> $` 头）。实测
`cross/m2/m3/multi/sh/lambda_test` 六份 AutoCAD 产物均恒等
（len(seg0)+1：55/56/91/168/70/29）。旧公式 `len(seg0_payload) - 2`
仅在 nsyms<10（`<nsyms> $` 头 3 字节）时碰巧相等，nsyms≥10 时错误。
`FasWriter.write(..., compact=True)` 按此规则写盘。

---

## 2. seg0 字节码（CAD stub 格式）

### 2.1 DEFUN 头

`0x14` 后跟 4 个操作数字节（**AutoCAD `vlisp-compile` 实测**）：

```
14 <b1> <b2> <b3> <b4>
```

| 字节 | 含义 |
|---|---|
| b1 | 参数个数（**不含** `/` 声明的局部变量） |
| b2 | 允许的最小参数数量 |
| b3 | 允许的最大参数个数 |
| b4 | 参数模式：`00` = 有限参数，`01` = 无限参数 |

实测（AutoCAD 编译器）：
- `(defun a (/ x y) ...)`（0 参 + 2 局部）→ `14 00 00 00 00`
- `(defun b (m / x y z) ...)`（1 参 + 3 局部）→ `14 01 01 01 00`
- `(defun c (p q) ...)`（2 参）→ `14 02 02 02 00`

即有限参数恒为 `b1 == b2 == b3`（均等于参数个数），`b4 = 00`。
> 注：曾有语义描述 b1 为「参数个数 + 局部变量数」；AutoCAD 实测表明
> `/` 声明的局部变量不计入 DEFUN 头。但 **含 foreach/repeat 的函数** `b1 =
> argc + 1`（t16/t17 实测 `14 02 01 01 00`，argc=1）；且 `/ 局部变量` 经
> `_al-bind-alist` 协议绑定（见 §2.2b），非 GET_LOCAL 动态分配。

**`&optional` / `&rest` 可变参数**（本项目编译器生成，CAD 运行时可加载执行）：

| 语法 | DEFUN 头 | 说明 |
|---|---|---|
| `(defun f (a b))` | `14 02 02 02 00` | 有限固定参数（b1==b2==b3=argc） |
| `(defun f (a &optional b c))` | `14 03 01 03 00` | 有限可选：b1=总参数(max)、b2=必填(min)、b3=max |
| `(defun f (a &rest r))` | `14 01 01 01 01` | 无限参数：b4=`01`，b1/b2/b3=必填数(min) |
| `(defun f (&rest n))` | `14 00 00 00 01` | 纯 &rest（min=0）；**CAD 实测运行时空**，建议至少一个必填参数 |
| `(defun f (a &optional b &rest r))` | `14 01 01 01 01` | optional + rest（b1/b2/b3=min） |

- 参数绑定：固定/可选/rest 使用 `PUSH_G <nsyms-argc+i>`（codegen 初始值），
  经 `_patch_usubr_idx` 修正为 `PUSH_G <gvar_slot(arg)-1>`（最终字节码）；
  `INIT_ARGS = 2*全部参数数 + 1`
- rest 参数在函数体内为列表（CAD 自动收集剩余实参）
- 反编译器按 DEFUN 头 b4/b2 重建 `&optional`/`&rest` 标记

### 2.2 参数绑定

每个参数先压符号槽字面量，再绑定 GET_LOCAL 槽位：

```
PUSH_G <idx:2>       # 参数绑定：codegen 用 nsyms-argc+i，
                      # _patch_usubr_idx 修正为 gvar_slot(arg)-1
GET_LOCAL_WIDE <i:2>  # 5c <slot:2>
...
INIT_ARGS <2*argc+1:2> # 18 05 00
```

参数读取（函数体内引用参数）用 `PUSH_VALUE <nsyms-argc+i:2>`（codegen），
经 `_patch_usubr_idx` 修正为 `PUSH_VALUE <gvar_slot(arg)-1:2>`（最终字节码）。

### 2.3 符号读取

所有符号读取统一用符号槽索引：

```
PUSH_VALUE <idx:2>     # 03 xx xx
PUSH_G <idx:2>         # 09 xx xx（字符串字面量）
```

**PUSH_VALUE[0] 编码为单字节 `03`**（调用后清理），idx>0 为 3 字节。CAD 实测必需。

### 2.4 调用（USUBR）

**USUBR 即 CAD 内部的 Xsubr 指令**（调用函数，见 `docs/opcodes.md`）。

3 字节短形式（nsyms ≤ 256，小文件）：

```
35 <argc:1> <idx:1>
```

**5 字节宽形式（nsyms > 256，大文件，atlisp_u.lsp 实测）**：

```
35 <argc:1> <idx:2> <flags=3>
```

FUNC 对应 3 字节 `51 <argc> <idx:1>` 与 6 字节宽形式
`51 <argc:1> <idx:2> <flags=1> 00`。宽形式 flags 内联了原 `00 03` 清理。

**索引规律（关键逆向）**：`idx = 符号的 gvar 槽 - 1`。即 USUBR 调用
gvar 槽 `idx+1` 处的符号。

- t01 `(add a b)`：`+` 在 gvar 槽 3 → `USUBR[2, 2]`
- t01 `(multiply a b)`：`*` 在 gvar 槽 2 → `USUBR[2, 1]`
- t07 `(car lst)`：`CAR` 在 gvar 槽 7 → `USUBR[1, 6]`

### 2.5 调用后清理

每个 USUBR/FUNC 调用后追加（**仅小文件 3 字节短形式**）：

```
00 03   # NIL + PUSH_VALUE[0]（结果清理/保留）
```

> 大文件宽形式（nsyms>256）flags=3 内联此清理，**无**额外 `00 03` 后缀。
> `command` 内建调用后为 `00 01 00`（NIL + PUSH_NIL + NIL，base-function 实测）。

### 2.5b `/ 局部变量` 绑定（`_al-bind-alist`，t11 实测）

含 `/ 局部变量` 的函数，CAD 用 `_al-bind-alist` 绑定而非 GET_LOCAL：

```
PUSH_G <locals 常量槽>; FUNC3 1 <_al-bind-alist>; NIL(00); PUSH_NIL(01); NIL(00); POP
```

- `_al-bind-alist` 符号与 `(quote (loc1 ...))` 常量在符号表独立注册
  （`_al-bind-alist` 以 `0x56` 保留大小写单符号块，不进 5b 合并块）。
- 符号收集：局部变量常量注入函数体符号之后、参数之前（t11 实测
  `+ <= I RESULT _al-bind-alist (RESULT I) N`）。
- 函数收尾 `CLEAR_ARGS = argc + len(locals)`（t11 实测 3）。

### 2.5c kwote 内嵌 `-lambda-`（`(function (lambda ...))`，v0.1.18+）

- 内嵌 DEFUN 字节：`JUMP <label:4>; 14 argc argc argc 00; 体; CLEAR_ARGS; 16;
  <label>`，随后 `PUSH_G <lam_idx>; FUNC3 1 <kwote>; NIL; PUSH_NIL; NIL`。
- 每个内嵌 `-lambda-` 独立符号槽（t3 槽 18、t4 槽 17、t5 槽 16，nsyms=19）。
- `-lambda-` 不进 `symtab.entries`，仅资源段 DEFCODE 区小写注册 → fas_nsyms
  比 codegen_nsyms 大 1，seg0 引用 `gvar 槽 - 2`。
- 顶层 `(set/setq 'sym (lambda ...))`（纯顶层文件，v0.1.22+，setq-lambda.lsp
  byte-identity）：内嵌 `-lambda-` 是**完整 compact stub**（`14 <argc>x3 00` +
  GET_LOCAL + INIT_ARGS + 体 + CLEAR_ARGS + END_DEFUN，函数间 `16` 分隔、最后无
  END），USUBR 用 5 字节宽格式（`35 <argc> <idx16> 03`）。模块代码用 setq 协议
  绑定 `JUMP 0; PUSH_G <-lambda-槽+1>; DUP; SETQ_G <sym>`。资源段布局见 §2.5d。

### 2.5d 纯顶层多 `-lambda-` 资源段布局（setq-lambda.lsp，v0.1.22+）

CAD 对纯顶层 `(set/setq 'sym (lambda ...))`（多 `-lambda-`）的 seg1 布局：

```
14 01 01 01 00                  DEFUN 头（模块注册段）
32 00 33 <mc> 2a 39 01 00       模块代码引用 ((0 . mc),)
5b <第一区符号>                  仅顶层表达式符号（不含 lambda 体符号）
01 01                           NIL NIL
43 <0> <第一区数+2>               GVARINIT(0, 第一区数+2) → rg 表
0a                              POP
32 <off> 33/32 <end> 2a ... 39 <n>   函数目录（每个 `-lambda-` 的 (offset . end)，
                                    offset 大的先压，末函数 end = total_size）
5b <第二区符号>                  lambda 体符号 + 参数 + 最后调用名（跨 lambda 去重）
5c 00 00 43 <0> <第二区数+1>     GET_LOCAL; GVARINIT(0, 第二区数+1) → fg 表
                                （module_id = 栈顶最后符号 → table1）
0a                              POP
5c 00 00 32 <off> 5b -lambda- 00 00 3a   DEFCODE ×N（offset 大的先注册）
01 43 <第一区数+2> <函数数>       GVARINIT(第一区数+2, 函数数) → `-lambda-` 超表槽
1c                              INIT_DONE
<模块代码>                        `JUMP 0; PUSH_G <lam槽+1>; DUP; SETQ_G <sym>` …
```

- **nsyms** = fg 表长度 = `1 + len(第二区符号)`（setq-lambda golden 12 = 1 + 11）。
- **fg 表**（`_patch_usubr_idx` 映射依据）= fg[1] 代码引用 + fg[2-11] 第二区符号；
  最后一个参数符号（如 FILE）作 GVARINIT module_id 弹出、不占 fg 槽。
- `-lambda-` gvar 槽 = `_lam_slot + 1` = `top_level_count + 2 - i + 1`（@::fasext 29、
  @::vlx 28），由 DEFCODE 后的 GVARINIT 注册为超表运行时槽（模块代码 PUSH_G 引用）。

### 2.6 控制流

**if**（JMP32_IFNOT 语义为"栈顶为假则跳转"= IFNOT）：

```
cond 求值
JMP32_IFNOT <else 目标>   # 67 s4：假则跳 else
then 分支
JUMP <end>               # 57 s4
else 分支
```

**无 else 的 if**（`(if cond then)`）：else 标签处补隐式 `PUSH_NIL`（cond 假返回 nil），
then 分支末尾的 `JUMP` 跳过它。例 t9 `(if (> 1 2) (alert "yes"))` 尾部：
`... 57 01 00 00 00 01`（JUMP +1 跳过 PUSH_NIL `01`）。

**setq（紧凑 stub，CAD 实测）**：

- 中间 setq：`SETQ_G <槽:2>` 后**不追加 POP**（SETQ_G 自身消费栈顶，与自包含格式不同）
- 尾 setq（函数体最后一句）：先 `DUP`（`0b`）再 `SETQ_G`，保留返回值
- 中间非 setq 调用表达式仍以 `POP`（`0a`）清理

例 t10 `(defun a () (setq x (alert "m")) x)` 尾部：
`... 00 03 06 01 00 03 01 00`（SETQ_G 1 后 PUSH_VALUE 1，无 POP）。

**递归**：禁用尾递归循环优化（不用 JUMP 回跳），用 USUBR 递归调用自身；
递归引用使用符号槽中的**重复槽**（同一函数名出现多次）。

### 2.7 函数末尾与分隔符

- 有参函数末尾：`00 03 19 <argc:2> 00`（NIL PUSH_VALUE[0] CLEAR_ARGS）
- 无参函数末尾：`00 03`
- **多函数间分隔符**：有参 `<argc> 00 16`；无参 `00 16`
- **CLEAR_ARGS 编码**：`19 <argc:2> 00`（3 字节，CAD 实测；如 `(defun f (n) ...)` → `19 01 00`）。
  反编译器按 3 字节解码，`disasm` 输出 `CLEAR_ARGS <argc>`，汇编可逐字节还原

### 2.8 seg0 末尾 2 字节（total_size 之外）

紧凑 stub 文件的 seg0 比 `total_size` 长 2 字节。这 2 字节是**最后一个函数指令序列
末尾的字节**（非独立 argc 编码），位于 `16 24 0d 0a` 终止符之前：

| 示例 | 末尾指令 | total_size 外 2 字节 |
|------|---------|---------------------|
| t9（无 else if） | `JUMP +1` + `PUSH_NIL` | `00 01` |
| t10（setq 尾） | `PUSH_VALUE [1]` | `01 00` |
| t11（有参 list） | `PUSH_NIL` + `NIL` | `01 00` |
| 有参函数尾 | `CLEAR_ARGS <argc> 00` | `<argc> 00` |

> 历史描述「尾部编码源码最后一个函数的参数数」为误判，已由 AutoCAD 逐字节对比纠正。

`Fas4Parser.parse` 按 `16 24 0d 0a` 终止符界定 seg0（而非 `total_size`），因此能完整
读到末尾 2 字节（最后一条 CLEAR_ARGS 的操作数），保证 `disasm → asm` 往返字节可逆。

---

## 3. seg1 资源段

### 3.1 总体结构

```
模块头 14 01 01 01 00
代码引用（模块代码长度）
函数名符号（源码逆序，5b 块）
PUSH_NIL ×2 + GVARINIT(0, 函数数+2) + 0a

函数代码引用（多函数：每函数 (start,end) 范围逆序）
其余符号/字符串（5b/55 块，跳过模块已注册函数名）
5c 00 00 + GVARINIT(0, 符号数+1) + 0a

每个函数一个 DEFCODE：5c 00 00 32 <off> 5b <name> 00 00 3a
  （仅最后一个追加 01）
GVARINIT(函数数+2, 函数数) + 1c (INIT_DONE)

模块代码
```

### 3.2 资源操作码

| 字节 | 名称 | 说明 |
|------|------|------|
| `5b` | 符号块 | `5b <name1>\x00 <name2>\x00 ... \x00` |
| `55` | 字符串块 | `55 <count:2>` + 每个 `55 <len:2> <bytes>` |
| `43` | GVARINIT | `43 <var_pos:2> <st_init:2>` |
| `3a` | DEFCODE | 用栈上 (module, start, name) 注册函数 |
| `32` | PUSH_INT8 | 代码引用/偏移 |
| `1c` | INIT_DONE | 初始化完成 |
| `0a` | POP | |

### 3.3 GVARINIT 规则（CAD 实测）

- 模块注册：`GVARINIT(0, 函数数 + 2)`
- 函数注册：`GVARINIT(0, 符号数 + 1)`
- DEFCODE：`GVARINIT(函数数 + 2, 函数数)`

### 3.4 DEFCODE

每个函数一条，offset 为该函数在 seg0 的字节偏移：

```
5c 00 00          # GET_LOCAL_WIDE 0
32 <offset:1>     # PUSH_INT8（offset>127 用 33 <i32>）
5b <name>\x00 00  # 函数名符号
3a                # DEFCODE（仅最后一个追加 01）
```

**DEFCODE 按源码逆序注册**（先最后一个函数）。

### 3.5 模块代码

模块代码 = `DEFUN头 + [顶层表达式] + [函数注册尾] + END_DEFUN`：

- **纯 defun（无顶层表达式）**：固定函数注册结构，对每个函数：
  `a_i = n+1-i, b_i = 2n+1-i, c_i = n-i`（n=函数数）：
  ```
  14 01 00 00 00
  对每个函数 i: 09 <a_i> 00 0a 57 00000000 09 <b_i> 00 06 <c_i> 00
  09 01 00 16
  ```
- **含顶层表达式**（`compiler/cli.py` 的 `_build_cad_module_code` 生成）：
  ```
  14 01 00 00 00                # DEFUN 模块头
  09 <模块注册+1> 00 0a          # 顶部占位
  <顶层表达式字节码>             # setq: 09 <值+1> 00 0b 06 <变量+1> 00
  57 00000000                   # JUMP（有 defun 时）
  09 <模块注册+2> 00 06 01 00    # 函数注册尾
  09 01 00                      # PUSH_G 1
  16                            # END_DEFUN
  ```
  顶层表达式的符号引用用 **gvar 槽 = 符号槽 + 1**；简单 `setq 变量 "字符串"` →
  `PUSH_G <值槽+1>; DUP; SETQ_G <变量槽+1>`。

### 3.6 nsyms

```
nsyms = len(entries) - 模块注册符号数 + 1
```

- **无顶层表达式**：模块注册符号数 = 函数数 → `nsyms = len(entries) - 函数数 + 1`
- **含顶层表达式**：模块注册符号数 = 函数数 + 顶层表达式符号数
  （`top_level_count`）

即函数注册 GVARINIT 的 st_init。多函数时**小于**符号槽去重数。

---

## 4. 符号槽顺序算法

`compiler/cad_symbols.py` 复刻 AutoCAD 的收集顺序：

1. 函数名按**源码逆序**（最后一个函数名在槽 0）
2. 顶层表达式符号（defun 之外）——排在函数体内建之前（混合时）
3. 按函数逆序，每函数内按"字节码引用序"**逆序**收集函数体符号（调用中参数
   先于函数名压栈，逆序后函数名/外层调用在前）
4. 每函数参数紧跟其函数体符号之后
5. 递归/跨函数调用产生**重复函数名槽**（CAD 行为）

例 t01：`[multiply, add, *, +, b, a]`；t07：`[pair, build-list, get-rest, get-first, cons, b, a, list, cdr, car, lst]`。

---

## 5. 加解密

双字节滚动 XOR（加密与解密同一函数，可逆）：

```
key_old = key[0]; kp = 1
for i in 0..len(data)-1:
    if kp >= len(key): kp = 0
    key_new = key[kp]
    result[i] = data[i] ^ key_new ^ key_old
    key_old = key_new; kp += 1
```

密钥以 `\n;fas4 crunch\n;`（15 字节）结尾，随机前缀默认 8 字节（总长 23）。

---

## 6. stub/自包含判定（is_compact_stub）

用 3 字节解析（sym_count 阈值）与 6 字节解析的 UNK 计数比较，平局时：

1. 检查 DEFUN 头编码：stub 为 argc 编码 `14 <argc>x3 00`，
   自包含为 gvar 编码 `14 <gv:2> <off:2>`
2. 检查资源段 DEFCODE 序列（`5c 00 00 32 <off> 5b <name> 00 00 3a`）
3. 平局且无 gvar DEFUN → 用函数目录判定

已验证：`tests/cad/*_cad.fas`（t-series golden）→stub，`tests/cad/i18n-cad.fas`/`tests/cad/i18n.fas`→自包含。

> **汇编器独立判定**（`asm/assembler.py` 的 `_detect_compact`）：
> 反编译共享的 `is_compact_stub` 对多函数紧凑 stub（UNK 平局且函数目录非空）会误判为
> 自包含。`disasm/asm` 往返使用独立判定：UNK 计数 + DEFUN 头 argc 编码，
> 对多函数紧凑 stub（`tests/multi_cad.fas`）也能正确标记 `.format compact`。

---

## 7. 已验证成果（AutoCAD 24.1s 实测）

> **当前（v0.1.22）**：`CAD_T_SERIES_IDENTICAL` 锁入 **6 项** byte-identity
> （andor/and2/or2/andval + chinese + qsingle，`tests/test_compiler_output.py`；
> 原 t0X 源已迁移至 `tests/compile_src/`，其 golden 由结构断言覆盖）；i18n 拆分件 byte-identity 回归；
> 链接输出与 `tests/cad/link/*_cad.fas` 3 份 golden 逐字节一致。CAD 真机
> **25 项**全过（`scripts/cad_verify.py`：t01-t24 + i18n，含 foreach/repeat/
> 变参/kwote/vla-/command/*error*）。

> 早期历史：四类编译产物（seg0 + seg1 + total_size）与 AutoCAD **逐字节一致**，
> CAD 运行结果全部正确：纯函数（t1-t11）、多个纯函数（m1/m2）、无函数纯顶层
> （tops/version）、混合（mix）、单函数递归（fact）。此前与 CAD 的 DIFF
> （多余 POP、writer 尾字节、total_size、无 else if、符号名大小写、顶层表达式
> 放 seg0、多函数符号收集顺序、多函数分隔符、CLEAR_ARGS 操作数）已全部修复。

下表为更早一轮（多函数/递归/while/cond，14/14）的历史记录：

| 测试 | 调用 | 结果 |
|------|------|------|
| t01 多函数 | `(add 3 4)` | 7 |
| t01 多函数 | `(multiply 3 4)` | 12 |
| t02 递归 | `(factorial 5)` | 120 |
| t03 递归 | `(fib 10)` | 55 |
| t04 while | `(count-down 3)` | Done! |
| t05 cond | `(classify -1)` | "negative" |
| t06 strcat | `(greet "Bob")` | "Hello, Bob!" |
| t07 多函数 | `(get-first '(1 2 3))` | 1 |
| t07 多函数 | `(get-rest '(1 2 3))` | (2 3) |
| t07 多函数 | `(build-list)` | (1 2 3) |
| t07 多函数 | `(pair 5 6)` | (5 . 6) |
| t11 局部变量 | `(sum-to-n 5)` | 15 |
| t13 嵌套 if | `(max3 3 7 5)` | 7 |
| m2 算术 | `(f2 2 3)` | 5 |

---

## 8. 实现文件对照

| 文件 | 职责 |
|------|------|
| `compiler/codegen.py` | stub 字节码生成（DEFUN/参数/USUBR/if/递归/kwote `-lambda-`） |
| `compiler/cad_symbols.py` | 符号槽顺序推导 |
| `compiler/resource_builder.py` | seg1 资源段（GVARINIT/DEFCODE/模块代码） |
| `compiler/fas_writer.py` | total_size（stub 减 2）、文件头、加密、trailer |
| `compiler/cli.py` | 编译管线、`_patch_usubr_idx`、`_build_cad_module_code`、改写层 |
| `compiler/_gvar_map.py` | commands+顶层混合 gvar 槽重映射 |
| `compiler/symbol_table.py` | add_force（重复槽）、repeat_slots |
| `compiler/linker.py` | stub 链接适配 |
| `asm/assembler.py` | 反汇编/汇编（.fas ↔ .lasm，`_detect_compact` 独立判定） |
| `asm/opcodes.py` | 操作码定义与编码函数（stub 3 字节/宽格式 5-6 字节/自包含长编码） |
| `decompiler/fas4_decompiler.py` | stub 反编译（函数名/DEFCODE/判定） |
| `tools/validate.py` | 接受含 `:` 的合法 AutoLISP 符号 |
| `engine/atlisp.asd` | SBCL AutoLISP 运行时（实验性跨校验器） |

---

## 9. 遗留问题

- **链接器多函数合并后的反编译**（参数名非源码名，cosmetic；字节码功能正确）。
  §3.6 的「字节码功能正确」已由 2026-08-08 根治（链接输出与 CAD golden 逐字节
  一致）。

> 已解决项（历史）：
> - **复杂顶层表达式**（i18n.lsp 等含 `if`/`cond`/嵌套调用/非字符串 setq）：
>   已由 `_build_cad_module_code`（2026-08-06）完整对齐 CAD——i18n 原文件
>   seg0+sec2+nsyms 逐字节一致（`test_i18n_original_byte_identity`），拆件
>   p01-p07 全对齐。
> - **多函数 stub 反编译符号槽映射**：已由 `_gvar_item`/`build_mvar_tables`
>   重建 gvar 表解决（参数名恢复，§3.5c/d/e、§10 系列修复）。
> - **链式 quote 常量**（t12）：函数表 GVARINIT 的 **module_id 槽**存结构化
>   LIST/CONS 常量（`build_module_id_slots`，`core/fas_core.py`；原子型
>   SYMBOL/STRING 是符号槽重复不登记），反编译器 `_gvar_item` 越界查询还原
>   `'(a b c)`/`'(1 . 2)`/`'(1 2 3)`。
> - **`Fas4Parser.parse` 的 total_size 截断**：已修复——解析器改用 `16 24 0d 0a`
>   终止符界定 seg0，可读全末尾 2 字节（CLEAR_ARGS 操作数）。

## 实测结论

- **编译输出 CAD 兼容**：四类产物（纯函数 t1–t11、多纯函数 m1/m2、纯顶层
  tops/version、混合 mix、单函数递归 fact）与 AutoCAD 逐字节一致，CAD 运行
  结果全部正确（t7→(1 2 3)、t8→5、t11→(5)、m1→(6 6)、version→1.23.8、
  mix→(1.0 6)、fact→120）
- **disasm/asm 往返字节可逆**：`atlispcc disasm x.fas x.lasm && atlispcc asm x.lasm y.fas`
  对纯函数/递归/多函数/顶层/strcat/while 产物，seg0 **逐字节一致**
  （total_size/nsyms/items 全等）；重新汇编产物可在 CAD 加载执行
  （`min`、多函数、init 文件均验证通过）
- `total_size = len(seg0) + 1`（紧凑 stub，CAD 实测恒等；六份 CAD 产物验证）；seg0 为 `<nsyms> $` 后的纯字节码
- 中间 setq 无 POP、尾 setq 用 DUP、无 else if 补 PUSH_NIL（与 CAD 一致）
- 代码测试 167/167（含链接器多函数 gvar-1 适配）

## 链接器多函数适配（本轮）

- **stub 判定**：`_extract_functions`/patch 改用 `_fas_is_stub`
  （is_compact_stub + DEFCODE/argc 检测），避免跨函数调用文件误判
- **索引重映射**：stub_sym_map 还原 file 符号 → 合并 gvar 槽-1
  （symbol_slots 含 STRING；fg 外符号用 symtab.entries 槽）
- **函数分隔符**：多文件合并时函数间插入 `01 00 16`（DEFCODE 尾 + 分隔符）
- **参数槽平移**：参数绑定/读取 PUSH_G/PUSH_VALUE 按 `nsyms-1-i` 平移
  `(merged_nsyms - file_nsyms)`
- **跨文件引用重复槽**：被其他文件调用的函数名 `add_force`
  加重复槽（进入 GVARINIT），使模块代码可引用、CAD 加载后函数已定义
- 链接输出通过 161/161 测试；CAD 执行验证：square 可用，sum-squares 待 CAD 恢复后复核

## 反编译修复（本轮）

- **USUBR/参数/符号索引用 gvar 表**：stub 反编译 `_gvar_item` 用
  `build_mvar_tables` 的 gvar 槽 `idx+1`（编译端索引 = gvar 槽-1），
  目录（CONS）排除，fallback 到 symbol_slots
- `_call_name`/`_extract_signature` 参数绑定用 gvar 表恢复参数名
- `_patch_usubr_idx` 对多函数统一修正 PUSH_VALUE/PUSH_G/SETQ_G/USUBR
  为 gvar 槽-1（单函数保持 nsyms-1-i，避免破坏递归重复槽）
- test_complex_lsp（O0-O3 复杂多函数）往返通过

---

## 10. 相关文档

- `docs/fas-format.md` — FAS4 二进制文件格式详解
- `docs/opcodes.md` — 操作码参考
- `docs/development.md` — 架构与开发指南
