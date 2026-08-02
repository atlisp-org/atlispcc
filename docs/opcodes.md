# FAS4 操作码参考

> 本文档列出全部 FAS4 操作码及字节编码。其文本汇编表示（`.lasm`，`disasm`/`asm` 用）
> 见 [docs/lasm.md](lasm.md)。

## 概述

FAS4 字节码由一系列操作码（opcode，单字节）及其可变长度操作数组成。反编译器逐字节读取，将每个指令映射为 `Instruction` 对象。

存在**两种字节码布局**，操作码编码差异见 [紧凑 stub 格式](#紧凑-stub-格式-cad)：

- **自包含格式**（本项目 `stub_format=False` 生成，与 `samples/bib.fas`/`samples/PDI.fas` 一致）：seg0 含完整函数体 + `END_DEFUN`，函数目录来自 mvar 表重建；调用用 5 字节 `USUBR`/6 字节 `FUNC`。
- **紧凑 stub 格式**（CAD 编译器输出，本项目 `stub_format=True` 生成）：seg0 无 `END_DEFUN`，符号按资源注册顺序（`symbol_slots`）直接编址；调用用 3 字节 `USUBR`/`FUNC`，`DEFUN` 头为 argc 编码。

操作数格式代码：

| 格式 | 长度 | 说明 |
|------|------|------|
| `''`  | 0 | 无操作数 |
| `'1'` | 1 | 单字节无符号整数（索引/偏移） |
| `'2'` | 2 | 双字节无符号整数（little-endian） |
| `'4'` | 4 | 四字节无符号整数（little-endian） |
| `'s4'`| 4 | 四字节有符号整数（little-endian） |
| `'bb'`| 2 | 两个单字节值 |
| `'u'` | 4 | USUBR 调用：argc(1) + index(2) + flags(1) |
| `'f'` | 5 | FUNC 调用：argc(1) + index(2) + flags(1) + zero(1) |
| `'h'` | 4 | DEFUN 头：4 个单字节字段 |
| `'e'` | 2 | EVAL：argc(1) + flag(1) |
| `'z'` | 可变 | 以 NUL 结尾的 ASCII 字符串 |

---

## 完整指令表

### 栈操作

| 十六进制 | 名称 | 操作数 | 描述 | 伪代码 |
|----------|------|--------|------|--------|
| 0x00 | NIL | — | 空操作（NOP） | — |
| 0x01 | PUSH_NIL | — | 压入 nil | `stack.push(nil)` |
| 0x02 | PUSH_T | — | 压入 T | `stack.push(T)` |
| 0x03 | PUSH_VALUE | '2' | 压入全局变量值（按索引查 resource_gvars） | `stack.push(gvars[idx])` |
| 0x09 | PUSH_G | '2' | 压入全局变量字面量（符号/字符串） | `stack.push(literal_of(gvars[idx]))` |
| 0x0c | PUSH_GLOBAL | '2' | 同 PUSH_G（备用编码） | `stack.push(literal_of(gvars[idx]))` |
| 0x32 | PUSH_INT8 | '1' | 压入单字节整数 | `stack.push(value)` |
| 0x33 | PUSH_INT32 | '4' | 压入 4 字节整数 | `stack.push(value)` |
| 0x3b | PUSH_REAL | 'z' | 压入实数（ASCII 字符串解析） | `stack.push(float(text))` |
| 0x0a | POP | — | 弹出栈顶作为独立语句输出 | `emit(stack.pop())` |
| 0x0b | DUP | — | 复制栈顶 | `stack.push(stack[-1])` |

### 局部变量

| 十六进制 | 名称 | 操作数 | 描述 | 伪代码 |
|----------|------|--------|------|--------|
| 0x05 | GET_LOCAL | '1' | 压入局部变量值（短编码） | `stack.push(local[slot])` |
| 0x5c | GET_LOCAL | '2' | 压入局部变量值（长编码） | `stack.push(local[slot])` |
| 0x5d | SET_LOCAL | '2' | 设置局部变量 | `emit((setq local[slot] stack.pop()))` |
| 0x5e | CLEAR_LOCAL | '2' | 清空局部变量为 nil | `emit((setq local[slot] nil))` |

### 全局变量赋值

| 十六进制 | 名称 | 操作数 | 描述 | 伪代码 |
|----------|------|--------|------|--------|
| 0x06 | SETQ_G | '2' | 设置全局变量 | `emit((setq gvar[idx] stack.pop()))` |

### 函数定义

| 十六进制 | 名称 | 操作数 | 描述 | 伪代码 |
|----------|------|--------|------|--------|
| 0x14 | DEFUN | 'h' | 函数定义开始（4 字节: arg/系统标志） | 标记函数起始 |
| 0x16 | END_DEFUN | — | 函数体结束 | 标记函数结束 |
| 0x18 | INIT_ARGS | '2' | 初始化函数参数 | `pop_many(args_count)` |
| 0x19 | CLEAR_ARGS | '2' | 清除函数参数 | — |
| 0x1c | INIT_DONE | — | 初始化完成 | `flush_stack()` |
| 0x21 | END_DEFUN_CLEANUP | '2' | 函数结束清理 | `pop_many(count)` |

### 调用

| 十六进制 | 名称 | 操作数 | 描述 | 伪代码 |
|----------|------|--------|------|--------|
| 0x35 | USUBR | 'u' | 用户函数调用 | `stack.push(call(name, pop_many(argc)))` |
| 0x51 | FUNC | 'f' | 系统函数/子程序调用 | `stack.push(call(name, pop_many(argc)))` |
| 0x34 | EVAL | 'e' | 动态求值调用 | `stack.push((eval ...))` |

USUBR/FUNC 的操作数字段：

- `argc`（1 字节）：参数个数
- `index`（2 字节）：在 function_gvars 中的索引，指向函数名
- `flags`（1 字节）：标志位
- `zero`（仅 FUNC，1 字节）：保留（始终 0）

### Xsubr 与 SUBR（CAD 术语）

**Xsubr = AutoCAD 对 `USUBR`（0x35）指令的内部称呼**，即「调用函数」指令。

- `SUBR` = AutoLISP 系统内建函数（如 `+`、`car`），`(type +)` → `SUBR`
- `XSUBR` = 外部子程序（FAS 编译产物 / ARX 注册的扩展函数）
- 字节码 `USUBR`(0x35) 指令执行这类调用；CAD 加载器据此校验
  （argc / 符号索引 / 参数绑定数）

CAD 报错 **「Xsubr(L) 指令 (偏移代码) 错误」** 即加载器对 `0x35`
指令的校验失败（如 argc 不匹配、索引越界、符号槽错位）。
本项目 `encode_usubr3` 的 docstring 也沿用此称呼（`compiler/opcodes.py:79`）。

紧凑 stub 格式的 USUBR 索引规律见 [docs/cad-stub-format.md §2.4](../docs/cad-stub-format.md)；
`&rest` 参数绑定数不匹配触发该报错的实测案例见 [docs/development-plan.md §3.5](../docs/development-plan.md)。

### 控制流

| 十六进制 | 名称 | 操作数 | 描述 | 伪代码 |
|----------|------|--------|------|--------|
| 0x57 | JUMP | 's4' | 无条件跳转 | `jump_to(offset)` |
| 0x69 | JUMP32 | 's4' | 无条件跳转（长距离） | `jump_to(offset)` |
| 0x67 | BR_IF_TRUE | 's4' | 条件跳转。**注意**：CAD 紧凑 stub 格式中实际语义为"栈顶为假则跳转"（等效 IFNOT）；自包含格式为真跳转 | stub: `if not pop(): jump_to(offset)` |
| 0x0d | JMP16_IFNOT | '2' | 条件假跳转（短） | `if not pop(): jump_to(offset)` |
| 0x0e | JMP16_IF | '2' | 条件真跳转（短） | `if pop(): jump_to(offset)` |
| 0x3c | JMP16_IFNOT_2 | '2' | 同 JMP16_IFNOT（备用） | `if not pop(): jump_to(offset)` |
| 0x3d | JMP16_IF_2 | '2' | 同 JMP16_IF（备用） | `if pop(): jump_to(offset)` |
| 0x3e | EXIT_IF_NOT_ZERO | — | 栈顶非零则退出 | `if stack.pop() != 0: return` |
| 0x3f | EXIT_IF_ZERO | — | 栈顶为零则退出 | `if stack.pop() == 0: return` |
| 0x68 | COND_OR | 's4' | 短路 OR 连接 | `pending_logic.append(OR, pop())` |
| 0x6a | AND | 's4' | 短路 AND 连接 | `pending_logic.append(AND, pop())` |
| 0x6b | AND2 | 's4' | 同 AND（备用） | `pending_logic.append(AND, pop())` |

### 符号操作

| 十六进制 | 名称 | 操作数 | 描述 | 伪代码 |
|----------|------|--------|------|--------|
| 0x1e | ALPHA | '1' | 字母前缀标记 | (编译器内部) |
| 0x1f | BETA | '1' | 字母尾缀标记 | (编译器内部) |
| 0x07 | COPY_ELEM | 'bb' | 复制元素（编译器内部） | — |

### 逻辑/算术

| 十六进制 | 名称 | 操作数 | 描述 | 伪代码 |
|----------|------|--------|------|--------|
| 0x23 | NOT | — | 逻辑取反 | `stack.push((not pop()))` |
| 0x24 | ATOM | — | 原子判断 | `stack.push((atom pop()))` |
| 0x28 | CAR | — | 取第一个 | `stack.push((car pop()))` |
| 0x29 | CDR | — | 取剩余 | `stack.push((cdr pop()))` |
| 0x46 | FIX_ADD | — | 整数相加 | `stack.push((+ pop() pop()))` |
| 0x47 | FIX_SUB | — | 整数相减 | `stack.push((- pop() pop()))` |
| 0x48 | FIX_MUL | — | 整数相乘 | `stack.push((* pop() pop()))` |
| 0x49 | FIX_DIV | — | 整数相除 | `stack.push((/ pop() pop()))` |
| 0x4a | FIX_MOD | — | 整数取余 | `stack.push((rem pop() pop()))` |
| 0x4b | FIX_LEQ | — | 小于等于比较 | `stack.push((<= pop() pop()))` |
| 0x4c | FIX_GEQ | — | 大于等于比较 | `stack.push((>= pop() pop()))` |
| 0x4d | FIX_LT | — | 小于比较 | `stack.push((< pop() pop()))` |
| 0x4e | FIX_GT | — | 大于比较 | `stack.push((> pop() pop()))` |
| 0x4f | INC | — | 自增 1 | `stack.push((1+ pop()))` |
| 0x50 | DEC | — | 自减 1 | `stack.push((1- pop()))` |

### 列表构造

| 十六进制 | 名称 | 操作数 | 描述 | 伪代码 |
|----------|------|--------|------|--------|
| 0x37 | LIST_OBJ | '2' | 构造列表（n 个元素） | `stack.push((list pop_many(n)...))` |
| 0x39 | BUILD_LIST | '2' | 同 LIST_OBJ（备用） | `stack.push((list pop_many(n)...))` |

### 保留/未定义

| 十六进制 | 名称 | 操作数 | 描述 |
|----------|------|--------|------|
| 0x20 | NOP | — | 空操作 |
| 0x3a | DEFCODE | — | 代码定义标记 |
| 0x40 | UNK_40 | — | 未知（未观察到使用） |
| 0x62 | NOP_62 | — | 空操作 |
| 0x63 | NOP_63 | — | 空操作 |

---

## 控制流结构重建

反编译器检测字节码模式并重建高级结构：

### if-then-else

检测 `JMP16_IFNOT/JMP16_IF/BR_IF_TRUE` 后跟跳转和可选的 else 分支：

```
cond → (JMP16_IFNOT else_target) → then_body → (JUMP after) → else_body → after
```

### while

检测向后跳转（循环）：

```
loop_cond: → (JMP16_IFNOT exit) → body → (JUMP loop_cond) → exit
```

### foreach

检测 while 内部的 car/cdr 解构模式：

```
(GET_LOCAL slot) → (CAR) → (SETQ_G item) → (GET_LOCAL slot) → (CDR) → (SET_LOCAL slot)
```

---

## 紧凑 stub 格式（CAD）

AutoCAD 编译器输出（本项目 `stub_format=True`）的字节码编码差异。符号不通过 `function_gvars` 间接寻址，而是直接按**符号槽索引**（seg1 资源注册顺序）编址。

### DEFUN 头

自包含格式为 `14 <gvar_ref:2> <offset:2>`（`encode_defun`）；stub 格式为 **argc 编码**，与 CAD 逐字节一致：

```
14 <argc> <argc> <argc> 00
```

argc = 函数参数个数。例如 `(defun f2 (a b) ...)` → `14 02 02 02 00`。

### 参数绑定

```
PUSH_G <槽:2>         # 每个参数：把符号槽字面量压栈
GET_LOCAL <n:2>       # 槽位 n = 参数序号
...
INIT_ARGS <2*argc+1:2>  # 参数初始化计数 = 2*argc + 1
```

`GET_LOCAL` 用 3 字节形式 `5c <slot:2>`（`GET_LOCAL_16`），而非自包含格式的 `05 <slot:1>`。

### 符号读取

所有符号读取统一用 `PUSH_VALUE <槽:2>`（`03 <u16>`），从符号槽取字面量/值：
- 全局变量、参数、函数名引用均通过符号槽索引
- 字符串字面量用 `PUSH_G <槽:2>`（`09 <u16>`）

### 调用（USUBR / FUNC）

自包含格式为 5/6 字节长形式；stub 格式为 **3 字节短形式**：

```
35 <argc:1> <槽:1>     # USUBR（用户函数/内建）— encode_usubr3
51 <argc:1> <槽:1>     # FUNC（系统子程序）— encode_func3
```

每次调用后追加结果清理序列 `NIL PUSH_VALUE`（`00 03`），保持栈状态与 CAD 一致。

### setq

`setq` 对符号变量统一用 `SETQ_G <槽:2>`（`06 <u16>`），不使用局部变量槽指令（stub 中无 `SET_LOCAL`）。

紧凑 stub 格式（CAD 实测）的特殊规则：
- **中间 setq**：`SETQ_G` 后**不追加 POP**（SETQ_G 自身消费栈顶；自包含格式才有 `POP`）
- **尾 setq**（函数体最后一句）：先 `DUP`（`0b`）再 `SETQ_G`，保留返回值供函数返回
- 中间非 setq 调用表达式仍以 `POP`（`0a`）清理

### 控制流

- `if` 布局：`cond → BR_IF_TRUE <else> → then → JUMP <end> → else`。
  **BR_IF_TRUE 语义为假跳转**（栈顶为假则跳转到 else），配合 `JUMP` 实现分支。
- **无 else 的 if**：else 标签处补隐式 `PUSH_NIL`（cond 假返回 nil），then 分支的
  `JUMP` 跳过它。例 `(if (> 1 2) (alert "yes"))` 尾部：`... 57 01 00 00 00 01`。
- 递归/跨函数调用**禁用尾递归循环优化**（不用 `JUMP` 回跳），改用 `USUBR` 递归调用自身；
  递归引用使用符号槽中的**重复槽**（同一函数名在符号槽中出现多次）。
 - 函数末尾：有参函数以 `CLEAR_ARGS`（`19 <argc> 00`，带 2 字节参数计数）结尾；
   无参函数无清理。调用序列已含 `00 03`。
 - 多函数函数间分隔符：`16`（END_DEFUN；CLEAR_ARGS `19 <argc> 00` 已由 codegen 生成，
   分隔符只追加 `16`）。

### 示例

`(defun f2 (a b) (+ a b))` 的 stub 字节码（与 CAD 逐字节一致）：

```
14 02 02 02 00   DEFUN argc=2
09 03 00         PUSH_G 槽3 (a)
5c 00 00         GET_LOCAL 0
09 02 00         PUSH_G 槽2 (b)
5c 01 00         GET_LOCAL 1
18 05 00         INIT_ARGS 5
03 03 00         PUSH_VALUE 槽3 (a)
03 02 00         PUSH_VALUE 槽2 (b)
35 02 01         USUBR argc=2 槽1 (+)
00 03            NIL + PUSH_VALUE（调用后清理）
19               CLEAR_ARGS
```

符号槽：`['f2', '+', 'b', 'a', 'f2']` → `+`=槽1，`b`=槽2，`a`=槽3。
