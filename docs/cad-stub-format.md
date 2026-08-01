# FAS4 紧凑 stub 格式规范与 AutoCAD 兼容实现

> 本文档是 `atlispcc`（FAS4 编译器/反编译器）对 **AutoCAD 编译器输出格式**
> （紧凑 stub 格式）逆向与兼容实现的完整技术规范。所有结论均基于
> AutoCAD 24.1s 实测验证与 `tests/fun-cad.fas`、`PDI.fas`、`bib.fas` 等
> 参考文件逐字节对比。
>
> 实测成果：本项目编译的单函数与**多函数** LSP 均可在 AutoCAD 中加载并
> 正确执行（14/14 用例通过）。

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
| 参考产物 | `bib.fas` / `PDI.fas` | `tests/fun-cad.fas` |

### 1.2 文件总布局

```
┌──────────────────────────────────────────────┐
│ ① 文件头  FAS4_MAGIC + <total_size>\r\n       │
│    FAS4_MAGIC = "\r\n FAS4-FILE ; Do not change it!\r\n"
├──────────────────────────────────────────────┤
│ ② seg0（明文）                                │
│    <nsyms> $ + 函数字节码                      │
│    + seg0 尾部 2 字节                          │
│    + 段分隔符 16 24 0d 0a                     │
├──────────────────────────────────────────────┤
│ ③ seg1（加密）                                │
│    <len> <items> $ + 滚动 XOR 加密资源流       │
├──────────────────────────────────────────────┤
│ ④ trailer  <key_len> + 密钥 + $; + 日期       │
└──────────────────────────────────────────────┘
```

---

## 2. seg0 字节码（CAD stub 格式）

### 2.1 DEFUN 头

argc 编码，argc 重复 3 次：

```
14 <argc> <argc> <argc> 00
```

例：`(defun f2 (a b) ...)` → `14 02 02 02 00`；`(defun f () ...)` → `14 00 00 00 00`。

### 2.2 参数绑定

每个参数先压符号槽字面量，再绑定 GET_LOCAL 槽位：

```
PUSH_G <nsyms-1-i:2>   # 参数 i 用 gvar 槽（从后往前）
GET_LOCAL <i:2>        # 5c <slot:2>
...
INIT_ARGS <2*argc+1:2> # 18 05 00
```

参数读取（函数体内引用参数）也用 `PUSH_VALUE <nsyms-1-i:2>`。

### 2.3 符号读取

所有符号读取统一用符号槽索引：

```
PUSH_VALUE <idx:2>     # 03 xx xx
PUSH_G <idx:2>         # 09 xx xx（字符串字面量）
```

**PUSH_VALUE[0] 编码为单字节 `03`**（调用后清理），idx>0 为 3 字节。CAD 实测必需。

### 2.4 调用（USUBR）

3 字节短形式：

```
35 <argc:1> <idx:1>
```

**索引规律（关键逆向）**：`idx = 符号的 gvar 槽 - 1`。即 USUBR 调用
gvar 槽 `idx+1` 处的符号。

- t01 `(add a b)`：`+` 在 gvar 槽 3 → `USUBR[2, 2]`
- t01 `(multiply a b)`：`*` 在 gvar 槽 2 → `USUBR[2, 1]`
- t07 `(car lst)`：`CAR` 在 gvar 槽 7 → `USUBR[1, 6]`

### 2.5 调用后清理

每个 USUBR/FUNC 调用后追加：

```
00 03   # NIL + PUSH_VALUE[0]（结果清理/保留）
```

### 2.6 控制流

**if**（BR_IF_TRUE 语义为"栈顶为假则跳转"= IFNOT）：

```
cond 求值
BR_IF_TRUE <else 目标>   # 67 s4：假则跳 else
then 分支
JUMP <end>               # 57 s4
else 分支
```

**递归**：禁用尾递归循环优化（不用 JUMP 回跳），用 USUBR 递归调用自身；
递归引用使用符号槽中的**重复槽**（同一函数名出现多次）。

### 2.7 函数末尾与分隔符

- 有参函数末尾：`00 03 19`（NIL PUSH_VALUE[0] CLEAR_ARGS）
- 无参函数末尾：`00 03`
- **多函数间分隔符**：有参 `<argc> 00 16`；无参 `00 16`

### 2.8 seg0 尾部 2 字节

CAD 编码**源码最后一个函数**的参数数：

| 函数 argc | tail |
|-----------|------|
| argc > 0  | `<argc> 00` |
| argc = 0  | `00 03` |

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
5c 00 00          # GET_LOCAL 0
32 <offset:1>     # PUSH_INT8（offset>127 用 33 <i32>）
5b <name>\x00 00  # 函数名符号
3a                # DEFCODE（仅最后一个追加 01）
```

**DEFCODE 按源码逆序注册**（先最后一个函数）。

### 3.5 模块代码

对每个函数生成一段，`a_i = n+1-i, b_i = 2n+1-i, c_i = n-i`（n=函数数）：

```
14 01 00 00 00
对每个函数 i: 09 <a_i> 00 0a 57 00000000 09 <b_i> 00 06 <c_i> 00
09 01 00 16
```

### 3.6 nsyms

```
nsyms = len(entries) - 函数数 + 1
```

即函数注册 GVARINIT 的 st_init。多函数时**小于**符号槽去重数。

---

## 4. 符号槽顺序算法

`compiler/cad_symbols.py` 复刻 AutoCAD 从右到左收集：

1. **函数名源码逆序**（最后一个函数名在槽 0）
2. 从最后一个函数往前收集函数体符号（内建/字符串逆序）
3. **唯一参数紧跟其函数**（仅一个函数使用的参数）
4. **共享参数最后**（被多函数使用的参数）
5. **递归/跨函数引用产生重复函数名槽**

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

已验证：`fun-cad.fas`→stub，`PDI.fas`/`bib.fas`→自包含。

---

## 7. 已验证成果（AutoCAD 24.1s 实测 14/14）

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
| `compiler/codegen.py` | stub 字节码生成（DEFUN/参数/USUBR/if/递归） |
| `compiler/cad_symbols.py` | 符号槽顺序推导 |
| `compiler/resource_builder.py` | seg1 资源段（GVARINIT/DEFCODE/模块代码） |
| `compiler/fas_writer.py` | seg0 tail、文件头、加密、trailer |
| `compiler/cli.py` | 编译管线、`_patch_usubr_idx` |
| `compiler/symbol_table.py` | add_force（重复槽）、repeat_slots |
| `compiler/linker.py` | stub 链接适配 |
| `fas4_decompiler.py` | stub 反编译（函数名/DEFCODE/判定） |
| `validate.py` | 接受含 `:` 的合法 AutoLISP 符号 |

---

## 9. 遗留问题

- **多函数 stub 反编译符号槽映射**：参数绑定/读取槽（`nsyms-1-i`）与
  symbol_slots 的对应适配（需反编译器重建 gvar 表；影响 compile→decompile
  往返质量，不影响 CAD 兼容/编译输出）
- 链接器多函数合并后的反编译

## 实测结论

- **编译输出 CAD 兼容**：14/14 执行正确（含多函数 t01/t07、递归、while、
  cond、局部变量、嵌套 if）
- 参数绑定槽用 `nsyms-1-i`（CAD 执行正确；t07 等参数槽与 CAD 的
  `gvar 槽-1` 不完全逐字节一致，但功能等价）
- 代码测试 158/161（3 个多函数反编译测试待适配）

---

## 10. 相关文档

- `docs/fas-format.md` — FAS4 二进制文件格式详解
- `docs/opcodes.md` — 操作码参考
- `docs/development.md` — 架构与开发指南
