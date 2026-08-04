# FAS4 操作码参考

> 本文档列出全部 FAS4 操作码、编码方式、使用场景及示例。
> 文本汇编表示（`.lasm`）见 [docs/lasm.md](lasm.md)。
> 文件格式详解见 [docs/fas-format.md](fas-format.md)。

## 概述

FAS4 字节码由单字节操作码及其可变长度操作数组成。每个操作码表示一个栈操作、控制流指令或函数调用。

存在**两种字节码布局**，操作码编码有差异：

| 特性 | 自包含格式 | 紧凑 stub 格式（CAD） |
|------|-----------|----------------------|
| 生成 | `stub_format=False` | `stub_format=True`（CLI 默认） |
| DEFUN 头 | `14 <gvar:2> <offset:2>` (4 字节) | `14 <argc>x3 00` (5 字节) |
| USUBR 调用 | `35 <argc> <idx:2> <flags>` (5 字节) | `35 <argc> <idx:1>` (3 字节) |
| FUNC 调用 | `51 <argc> <idx:2> <flags> 00` (6 字节) | `51 <argc> <idx:1>` (3 字节) |
| GET_LOCAL | `05 <slot:1>` (2 字节) | `5c <slot:2>` (3 字节) |
| 函数目录 | mvar 表重建 | seg1 DEFCODE 序列 |
| 参考产物 | `tests/cad/i18n-cad.fas` / `tests/cad/i18n.fas` | `tests/fun-cad.fas` |

操作数格式代码：

| 格式 | 字节数 | 说明 |
|------|--------|------|
| `''`  | 0 | 无操作数 |
| `'1'` | 1 | 单字节无符号整数 |
| `'2'` | 2 | 双字节无符号整数（LE） |
| `'4'` | 4 | 四字节无符号整数（LE） |
| `'s4'`| 4 | 四字节有符号整数（LE，相对跳转） |
| `'bb'`| 2 | 两个单字节操作数 |
| `'u'` | 4 | USUBR：`argc(1) idx(2) flags(1)`（自包含格式） |
| `'h'` | 4 | DEFUN 头：gvar(2) + offset(2)（自包含格式） |
| `'f'` | 5 | FUNC：`argc(1) idx(2) flags(1) zero(1)`（自包含格式） |
| `'e'` | 2 | EVAL：argc(1) + flag(1) |
| `'z'` | 可变 | NUL 结尾的 ASCII 字符串 |

> **紧凑 stub 格式的 USUBR/FUNC** 使用 3 字节编码（`encode_usubr3` / `encode_func3`），
> 操作数为 `argc:1 + slot:1`。调用后追加 `NIL`(`00`) + `PUSH_VALUE`(`03`) 清理。

---

## 完整指令表

### 栈操作

| 十六进制 | 名称 | 格式 | 描述 | 发射位置 |
|----------|------|------|------|----------|
| `00` | NIL | `''` | 空操作/占位。stub 格式中 USUBR/FUNC 调用后追加为清理标记 | `_emit_arith`、`_emit_unary`、`_emit_call_expr` (stub 调用后) |
| `01` | PUSH_NIL | `''` | 压入 `nil` | `_emit_expr`（`nil` 字面量、空 list 初始值）、`_emit_if`（stub 无 else 的隐式 nil）、`_emit_quoted`（`'nil`、None） |
| `02` | PUSH_T | `''` | 压入 `T`（布尔真） | `_emit_expr`（`T` 字面量）、`_emit_call_expr`（`(exit)`/`(quit)`/`(abort)`、空 `(and)`） |
| `03` | PUSH_VALUE | `2` | 由符号槽索引取值压栈。全局变量、参数、函数名引用均通过此指令 | `_emit_expr`（符号引用）、`_emit_arith` / `_emit_unary`（stub 结果取回） |
| `09` | PUSH_G | `2` | 压入全局符号字面量。"G" = Global。字符串字面量、quoted 符号用此指令 | `_emit_expr`（字符串）、`_emit_quoted`、`_emit_init_args`（参数名注册） |
| `0c` | PUSH_GLOBAL | `2` | 同 PUSH_G（备用编码，项目中未使用） | — |
| `32` | PUSH_INT8 | `1` | 压入单字节有符号整数（−128~127） | `_emit_expr`（小整数）、`_emit_quoted` |
| `33` | PUSH_INT32 | `4` | 压入四字节有符号整数（超出 `int8` 范围时） | `_emit_expr`（大整数）、`_emit_quoted` |
| `3b` | PUSH_REAL | `z` | 压入实数（ASCII 字符串后跟 NUL） | `_emit_expr`（实数）、`_emit_quoted` |
| `0a` | POP | `''` | 弹出栈顶并丢弃。表达式中非末尾结果由此清理 | `_emit_expr`（`progn` 非末尾表单）、`_emit_while`/`_emit_repeat`/`_emit_foreach`（循环中表单）、`generate_function`（非末尾体） |
| `0b` | DUP | `''` | 复制栈顶。stub 格式中尾 `setq` 用此保留返回值 | `_emit_setq_expr`（stub 尾 setq） |

#### 示例：PUSH 序列

```
; (setq x 42)
32 2a          PUSH_INT8 42     ; 压入整数 42
06 02 00       SETQ_G 2         ; x→符号槽 2，设置全局变量

; (princ "Hello")
09 03 00       PUSH_G 3         ; "Hello"→符号槽 3，压入字符串字面量
35 01 04       USUBR argc=1 槽4 ; 调用 princ (符号槽 4)
```

---

### 局部变量

| 十六进制 | 名称 | 格式 | 描述 | 发射位置 |
|----------|------|------|------|----------|
| `05` | GET_LOCAL | `1` | 压入局部变量值（短编码，slot<256） | `_emit_expr`、`_emit_init_args`（自包含格式） |
| `5c` | GET_LOCAL | `2` | 压入局部变量值（长编码，slot≥256 或 stub 格式） | `_emit_expr`、`_emit_foreach`、`_emit_repeat`、`_emit_init_args`（stub 格式） |
| `5d` | SET_LOCAL | `2` | 设置局部变量（栈顶→slot）。不用于 stub 格式 | `_emit_setq_expr`（局部 setq）、`_emit_foreach`（循环变量）、`_emit_repeat`（计数器更新）、`_emit_tail_call`（参数重绑定） |
| `5e` | CLEAR_LOCAL | `2` | 清空局部变量为 nil（项目中未使用） | — |

> **stub 格式**不使用 `SET_LOCAL`——所有 setq 统一用 `SETQ_G`（`06`），
> 前加 `DUP`（`0b`，尾 setq）/不加 `DUP`（中间 setq）。

#### 示例：局部变量绑定

```
; (defun f (x / y) (setq y (+ x 1)) y)
; 自包含格式：
05 00          GET_LOCAL 0      ; x→局部槽 0
32 01          PUSH_INT8 1
46             FIX_ADD          ; (+ x 1)
5d 01 00       SET_LOCAL 1      ; y→局部槽 1, setq y
05 01          GET_LOCAL 1      ; y→返回值
```

---

### 全局变量赋值

| 十六进制 | 名称 | 格式 | 描述 | 发射位置 |
|----------|------|------|------|----------|
| `06` | SETQ_G | `2` | 弹出栈顶，写入全局符号槽 | `_emit_setq_expr`（全局 setq）、`_emit_foreach`（循环变量→全局） |

#### 示例：stub 格式 setq 规则

```
; 中间 setq: (setq x 1) (princ x) (setq y 2)
32 01          PUSH_INT8 1
06 00 00       SETQ_G 0         ; x=0, 无 POP
09 04 00       PUSH_G 4         ; princ
03 00 00       PUSH_VALUE 0     ; x
35 01 04       USUBR argc=1 4   ; (princ x)
00 03          NIL + PUSH_VALUE ; 调用后清理
0a             POP              ; princ 的返回值不需要, POP
32 02          PUSH_INT8 2
06 01 00       SETQ_G 1         ; y=1, 无 POP

; 尾 setq: ... (while ...) (setq z 3)
; setq 前加 DUP:
0b             DUP              ; 保留栈顶（上一个表达式的结果）
32 03          PUSH_INT8 3
06 02 00       SETQ_G 2         ; z=2, 无 POP
; 栈上仍保留 DUP 的值作为函数返回
```

---

### 函数定义

| 十六进制 | 名称 | 格式 | 描述 | 发射位置 |
|----------|------|------|------|----------|
| `14` | DEFUN | `h` | 函数定义开始。自包含: `14 <gvar:2> <offset:2>`；stub: `14 <argc>x3 00` | `_emit_defun_header`、`generate_function` |
| `15` | DEFUN2 | `h` | DEFUN 变体（项目中未使用） | — |
| `16` | END_DEFUN | `''` | 函数体结束标记。自包含格式末尾用此；stub 格式不生成，多函数时分隔符追加 `16` | `FasWriter`（写入时追加） |
| `18` | INIT_ARGS | `2` | 初始化函数参数绑定。自包含: `2*argc`；stub: `2*argc+1` | `_emit_init_args`、`generate_function` |
| `19` | CLEAR_ARGS | `2` | 清除函数参数绑定（返回前） | `_emit_clear_args` |
| `1c` | INIT_DONE | `''` | 模块初始化完成标记（资源段中使用） | `ResourceBuilder`（seg1 尾部） |
| `21` | END_DEFUN_CLEANUP | `2` | 函数结束清理（项目中未使用） | — |

#### 示例：DEFUN 头对比

```
; (defun f2 (a b) (+ a b))

; 自包含格式：
14 01 00 00 00  DEFUN gvar=1 offset=0

; 紧凑 stub 格式（与 CAD 一致）：
14 02 02 02 00  DEFUN argc=2
```

#### 示例：完整 stub 格式函数

```
; (defun f2 (a b) (+ a b))
14 02 02 02 00   DEFUN argc=2
09 03 00         PUSH_G 槽3 (a)       ; 参数符号名
5c 00 00         GET_LOCAL 0          ;   →局部槽 0
09 02 00         PUSH_G 槽2 (b)       ; 参数符号名
5c 01 00         GET_LOCAL 1          ;   →局部槽 1
18 05 00         INIT_ARGS 5          ; 2*argc+1=5
03 03 00         PUSH_VALUE 槽3 (a)   ; 取 a 的值
03 02 00         PUSH_VALUE 槽2 (b)   ; 取 b 的值
35 02 01         USUBR argc=2 槽1 (+) ; 调用 +
00 03            NIL + PUSH_VALUE     ; 调用后清理
19 02 00         CLEAR_ARGS argc=2    ; 3 字节（CAD 实测）
; stub 格式末尾不追加 END_DEFUN
```

---

### 函数调用

| 十六进制 | 名称 | 格式 | 描述 | 发射位置 |
|----------|------|------|------|----------|
| `35` | USUBR | `u` | 调用用户函数（自包含: 5 字节；stub: 3 字节 `encode_usubr3`）| `_emit_call`、`_emit_call_expr`、`_emit_arith`/`_emit_unary`（非内置函数回退） |
| `51` | FUNC | `f` | 调用系统函数/子程序（自包含: 6 字节；stub: 3 字节 `encode_func3`）| `_emit_call`（内建函数）、`_emit_call_expr` |

USUBR 操作数（自包含格式）：
- `argc`（1 字节）：参数个数
- `idx`（2 字节）：符号表中函数名索引
- `flags`（1 字节）：标志位（通常 0）

USUBR 操作数（紧凑 stub 格式）：
- `argc`（1 字节）：参数个数
- `slot`（1 字节）：符号槽索引（0~255）

> **Xsubr** 是 AutoCAD 对 `USUBR`(0x35) 指令的内部称呼。
> CAD 报错「Xsubr(L) 指令 (偏移代码) 错误」即加载器对 USUBR 的校验失败
> （argc 不匹配、索引越界、符号槽错位）。

#### 示例：USUBR 调用对比

```
; (alert "abc")

; 自包含格式（5 字节）：
09 01 00       PUSH_G 1         ; "abc"→槽 1
35 01 02 00    USUBR argc=1 idx=2 flags=0  ; 调用 alert (槽 2)

; 紧凑 stub 格式（3 字节调用）：
09 01 00       PUSH_G 1         ; "abc"→槽 1
35 01 02       USUBR argc=1 槽2 ; 调用 alert (槽 2)
00 03          NIL + PUSH_VALUE ; 调用后清理
```

---

### 控制流

| 十六进制 | 名称 | 格式 | 描述 | 发射位置 |
|----------|------|------|------|----------|
| `57` | JUMP | `s4` | 无条件跳转，4 字节有符号相对偏移 | `_emit_if`（跳过 else/到 end）、`_emit_while`/`_emit_foreach`/`_emit_repeat`（循环回跳）、`_emit_cond`（跳过剩余子句）、`_emit_tail_call`（尾递归跳转） |
| `69` | JUMP32 | `s4` | 无条件跳转（备用编码，项目中未使用） | — |
| `67` | BR_IF_TRUE | `s4` | 条件跳转。**CAD stub 格式中语义为"栈顶为假则跳转"(IFNOT)**，4 字节有符号偏移 | `_emit_if`（stub if 分支）、`_emit_while`（stub 循环退出） |
| `0d` | JMP16_IFNOT | `2` | 条件假跳转（短），2 字节有符号偏移 | `_emit_if`（自包含 if 分支）、`_emit_while`（自包含循环退出）、`_emit_short_circuit`（`and`）、`_emit_foreach`（空列表检测）、`_emit_repeat`（零计数检测）、`_emit_cond`（子句条件为假） |
| `0e` | JMP16_IF | `2` | 条件真跳转（短），2 字节有符号偏移 | `_emit_short_circuit`（`or`） |
| `3c` | JMP16_IFNOT_2 | `2` | 同 JMP16_IFNOT（备用编码，项目中未使用） | — |
| `3d` | JMP16_IF_2 | `2` | 同 JMP16_IF（备用编码，项目中未使用） | — |
| `3e` | EXIT_IF_NOT_ZERO | `''` | 栈顶非零则退出执行 | `_emit_call_expr`（`(exit)`/`(quit)`/`(abort)`） |
| `3f` | EXIT_IF_ZERO | `''` | 栈顶为零则退出（项目中未使用） | — |
| `68` | COND_OR | `s4` | 短路 OR（项目中未使用） | — |
| `6a` | AND | `s4` | 短路 AND（项目中未使用） | — |
| `6b` | AND2 | `s4` | AND 变体（项目中未使用） | — |

#### 控制流结构

**if-then-else（自包含格式）：**
```
cond → JMP16_IFNOT else_target → then_body → JUMP after → else_body → after
```

**if-then-else（紧凑 stub 格式）：**
```
cond → BR_IF_TRUE else_target → then_body → JUMP after → else_body → after
```

**while 循环（自包含格式）：**
```
loop: → cond → JMP16_IFNOT exit → body → JUMP loop → exit
```

**while 循环（紧凑 stub 格式）：**
```
loop: → cond → BR_IF_TRUE exit → body → JUMP loop → exit
```

#### 示例：if-then-else

```
; (if (> x 0) "positive" "negative")

; 自包含格式：
03 02 00       PUSH_VALUE 槽2 (x)       ; cond
32 00          PUSH_INT8 0
4e             FIX_GT                   ; (> x 0)
0d 05 00       JMP16_IFNOT +5           ; 假→跳至 else
; then branch:
09 03 00       PUSH_G 3 ("positive")
57 03 00 00 00 JUMP +3                  ; 跳过 else
; else branch:
09 04 00       PUSH_G 4 ("negative")
; after:

; 紧凑 stub 格式：
03 02 00       PUSH_VALUE 槽2 (x)       ; cond
32 00          PUSH_INT8 0
4e             FIX_GT
67 0a 00 00 00 BR_IF_TRUE +10          ; 假→跳至 else
; then:
09 03 00       PUSH_G 3 ("positive")
57 03 00 00 00 JUMP +3                  ; 跳过 else
; else:
09 04 00       PUSH_G 4 ("negative")
; after:
```

#### 示例：while 循环

```
; (while (> n 0) (princ n) (setq n (1- n)))

; 紧凑 stub 格式：
; loop_cond:
03 02 00       PUSH_VALUE 槽2 (n)       ; 取 n
32 00          PUSH_INT8 0
4e             FIX_GT                   ; (> n 0)
67 0e 00 00 00 BR_IF_TRUE +14          ; 假→exit
; body:
09 03 00       PUSH_G 3 (princ)         ; (princ n)
03 02 00       PUSH_VALUE 槽2 (n)
35 01 03       USUBR argc=1 槽3
00 03          NIL + PUSH_VALUE
0a             POP                      ; 丢弃 princ 返回值
03 02 00       PUSH_VALUE 槽2 (n)
50             DEC                      ; (1- n)
0b             DUP                      ; 尾 setq: 保留返回值
06 02 00       SETQ_G 槽2               ; n = 新值
57 ec ff ff ff JUMP -20                 ; 回跳至 loop_cond
; exit:
```

#### 示例：cond

```
; (cond ((< x 0) "negative") ((= x 0) "zero") ((> x 0) "positive"))

03 02 00       PUSH_VALUE 槽2 (x)       ; 子句 0: (< x 0)
32 00          PUSH_INT8 0
4d             FIX_LT
0d 05 00       JMP16_IFNOT +5           ; 假→子句 1
09 03 00       PUSH_G 3 ("negative")    ; then: 返回 "negative"
57 10 00 00 00 JUMP +16                 ; 跳到 after

03 02 00       PUSH_VALUE 槽2 (x)       ; 子句 1: (= x 0)
32 00          PUSH_INT8 0
4b             FIX_LEQ                  ; <= 实现
03 02 00       PUSH_VALUE 槽2 (x)
32 00          PUSH_INT8 0
4c             FIX_GEQ                  ; ...(= x 0)→(and (<= x 0) (>= x 0))
0d 05 00       JMP16_IFNOT +5
09 04 00       PUSH_G 4 ("zero")
57 03 00 00 00 JUMP +3

03 02 00       PUSH_VALUE 槽2 (x)       ; 子句 2: (> x 0)
32 00          PUSH_INT8 0
4e             FIX_GT
0d 00 00       JMP16_IFNOT +0           ; 最后子句→不跳转(无 else)
09 05 00       PUSH_G 5 ("positive")
; after:
```

---

### 算术

| 十六进制 | 名称 | 格式 | 描述 | Lisp 构造 |
|----------|------|------|------|-----------|
| `46` | FIX_ADD | `''` | 弹出两个整数，相加，结果压栈 | `(+ a b ...)` |
| `47` | FIX_SUB | `''` | 弹出两个整数，相减；单参数时 `0-arg` | `(- a b)` / `(- x)` |
| `48` | FIX_MUL | `''` | 弹出两个整数，相乘 | `(* a b ...)` |
| `49` | FIX_DIV | `''` | 弹出两个整数，相除；单参数时 `1/arg` | `(/ a b)` / `(/ x)` |
| `4a` | FIX_MOD | `''` | 弹出两个整数，取余 | `(rem a b)` |
| `4b` | FIX_LEQ | `''` | 小于等于比较，弹出两个整数，比较结果压栈 | `(<= a b ...)` |
| `4c` | FIX_GEQ | `''` | 大于等于比较 | `(>= a b ...)` |
| `4d` | FIX_LT | `''` | 小于比较 | `(< a b ...)` |
| `4e` | FIX_GT | `''` | 大于比较 | `(> a b ...)` |
| `4f` | INC | `''` | 栈顶整数自增 1 | `(1+ x)` |
| `50` | DEC | `''` | 栈顶整数自减 1 | `(1- x)` |

> 多参数算术（如 `(+ a b c)`）通过连续单指令完成：
> `push a ; push b ; FIX_ADD ; push c ; FIX_ADD`。

#### 示例

```
; (+ x 1)
03 02 00       PUSH_VALUE 槽2 (x)       ; 左操作数
32 01          PUSH_INT8 1              ; 右操作数
46             FIX_ADD                  ; x+1→栈顶

; (<= i limit)
03 03 00       PUSH_VALUE 槽3 (i)       ; 左操作数
03 04 00       PUSH_VALUE 槽4 (limit)   ; 右操作数
4b             FIX_LEQ                  ; (<= i limit)→T/nil

; (= x 0) — 实现为 (and (<= x 0) (>= x 0))
03 02 00       PUSH_VALUE 2 (x)
32 00          PUSH_INT8 0
4b             FIX_LEQ                  ; (<= x 0)
03 02 00       PUSH_VALUE 2 (x)
32 00          PUSH_INT8 0
4c             FIX_GEQ                  ; (>= x 0)
; 然后通过 and 短路组合: JMP16_IFNOT 若 (<= x 0) 为假则跳
```

---

### 列表/逻辑/原子操作

| 十六进制 | 名称 | 格式 | 描述 | Lisp 构造 |
|----------|------|------|------|-----------|
| `28` | CAR | `''` | 弹出列表，取其第一个元素压栈 | `(car list)` |
| `29` | CDR | `''` | 弹出列表，取其剩余部分压栈 | `(cdr list)` |
| `2a` | CONS | `''` | 弹出两个值，构造点对 | `(cons a b)` / 点对字面量 `'(a . b)` |
| `39` | BUILD_LIST | `2` | 弹出 n 个值，构造列表，结果压栈 | `(list a b c ...)` |
| `37` | LIST_OBJ | `2` | 同 BUILD_LIST（备用编码，项目中未使用） | — |
| `23` | NOT | `''` | 弹出栈顶，逻辑取反后压栈 | `(not x)` |
| `24` | ATOM | `''` | 弹出栈顶，判断是否为原子 | `(atom x)` |
| `07` | COPY_ELEM | `bb` | 编译器内部元素复制（项目中未使用） | — |

#### 示例

```
; (list a b c)
; 参数逆序压栈（自包含格式）：
PUSH b                         ; 先压 c
PUSH a                         ;   再压 b
39 03 00       BUILD_LIST 3    ;   再压 a，然后构造列表

; (car lst)
03 02 00       PUSH_VALUE 槽2 (lst)
28             CAR

; (not x)
03 02 00       PUSH_VALUE 槽2 (x)
23             NOT
```

---

### 保留/未使用操作码

以下操作码定义于 `OPCODES` dict 中，但 `CodeGenerator` 未直接发射。它们可能由 `ResourceBuilder`、`FasWriter` 生成，或存在于 CAD 原生 FAS 文件中：

| 十六进制 | 名称 | 格式 | 说明 |
|----------|------|------|------|
| `10` | OP_10 | `''` | 未知，未观察到使用 |
| `15` | DEFUN2 | `h` | DEFUN 备用变体 |
| `1a` | OP_1A | `2` | 未知 |
| `1b` | OP_1B | `2` | 未知 |
| `1e` | ALPHA | `1` | 字母前缀标记（编译器内部） |
| `1f` | BETA | `1` | 字母尾缀标记（编译器内部） |
| `20` | NOP | `''` | 空操作 |
| `38` | OP_38 | `''` | 未知 |
| `3a` | DEFCODE | `''` | 代码定义标记（seg1 资源段使用） |
| `40` | OP_40 | `''` | 未知 |
| `62` | NOP_62 | `''` | 空操作备用 |
| `63` | NOP_63 | `''` | 空操作备用 |

---

## 常见模式参考

### foreach 循环

`_emit_foreach` 将 `(foreach var list body...)` 编译为 while + car/cdr 模式：

```
; 初始化：list→局部槽，计数器设 0
PUSH list_val
SET_LOCAL list_slot
; loop:
GET_LOCAL list_slot              ; 取列表
JMP16_IFNOT +N                   ; 列表为空→exit
GET_LOCAL list_slot              ; (car list)
CAR
SETQ_G var_slot                  ; var = (car list)
; body:
...
POP                              ; 丢弃 body 结果
GET_LOCAL list_slot              ; (cdr list)
CDR
SET_LOCAL list_slot              ; list = (cdr list)
JUMP loop                        ; 回跳
; exit:
```

### repeat 循环

`_emit_repeat` 将 `(repeat n body...)` 编译为递减计数器模式：

```
; 初始化计数器
PUSH n
SET_LOCAL counter_slot
; loop:
GET_LOCAL counter_slot           ; 取计数
JMP16_IFNOT +N                   ; 计数为 0→exit
; body:
...
POP                              ; 丢弃 body 结果
GET_LOCAL counter_slot           ; (1- counter)
DEC
SET_LOCAL counter_slot           ; counter--
JUMP loop                        ; 回跳
; exit:
```

### and/or 短路求值

`_emit_short_circuit` 将 `(and a b c)` 编译为逐项假跳转：

```
; (and a b c) — 自包含格式
push a                           ; 先求值 a
JMP16_IFNOT +end                 ; 若 a 为假→跳 end，返回 nil
push b                           ; 求值 b
JMP16_IFNOT +end                 ; 若 b 为假→跳 end
push c                           ; 最后一个：c 的值即结果
; end:
```

```
; (or a b c) — 自包含格式
push a
JMP16_IF +end                    ; 若 a 为真→跳 end，返回 a
push b
JMP16_IF +end                    ; 若 b 为真→跳 end
push c                           ; 最后一个：c 的值即结果
; end:
```

### tail call（尾递归优化）

`_emit_tail_call` 将尾位置的 `(self args...)` 编译为循环（而非调用自身）：

```
; (defun fact (n acc) (if ... (fact (1- n) (* n acc))))
; 尾位置调用 (fact (1- n) (* n acc)):
; 1. 求值所有参数，压栈（新值）
; 2. 将参数值写回局部槽
SET_LOCAL param_slot_n           ; n = 新值
SET_LOCAL param_slot_acc         ; acc = 新值
; 3. 跳转回函数入口（不压新栈帧）
JUMP func_entry
```

> **stub 格式**禁用尾递归循环优化（与 CAD 一致），改用 `USUBR` 递归调用自身。

---

## 编码函数参考

`asm/opcodes.py` 提供的编码辅助函数：

| 函数 | 输出格式 | 示例 |
|------|---------|------|
| `encode_op_noarg(op)` | 1 字节 | `encode_op_noarg(0x46)` → `46` |
| `encode_op_u16(op, val)` | 3 字节 `op val:2` | `encode_op_u16(0x03, 2)` → `03 02 00` |
| `encode_op_u8(op, val)` | 2 字节 `op val:1` | `encode_op_u8(0x05, 1)` → `05 01` |
| `encode_op_s32(op, val)` | 5 字节 `op val:4` | `encode_op_s32(0x57, 10)` → `57 0a 00 00 00` |
| `encode_bb(op, a, b)` | 3 字节 `op a b` | `encode_bb(0x07, 1, 2)` → `07 01 02` |
| `encode_usubr(argc, idx, flags)` | 5 字节 | `encode_usubr(1, 2, 0)` → `35 01 02 00 00` |
| `encode_usubr3(argc, idx)` | 3 字节 | `encode_usubr3(1, 2)` → `35 01 02` |
| `encode_func(argc, idx, flags)` | 6 字节 | `encode_func(1, 3, 0)` → `51 01 03 00 00 00` |
| `encode_func3(argc, idx)` | 3 字节 | `encode_func3(1, 3)` → `51 01 03` |
| `encode_defun(gvar, offset)` | 5 字节 | `encode_defun(1, 0)` → `14 01 00 00 00` |
| `encode_eval(argc, flag)` | 3 字节 | `encode_eval(1, 0)` → `34 01 00` |
| `encode_real(value)` | 可变 | `encode_real(3.14)` → `3b 33 2e 31 34 00` |

---

## 交叉引用

| 文档 | 说明 |
|------|------|
| [lasm.md](lasm.md) | 文本汇编表示（`.lasm`），`disasm`/`asm` 子命令 |
| [fas-format.md](fas-format.md) | FAS4 文件格式详解（布局、加密、资源段） |
| [cad-stub-format.md](cad-stub-format.md) | 紧凑 stub 格式与 CAD 兼容性细节 |
| [development.md](development.md) | 编译器架构与开发指南 |
| `asm/opcodes.py` | 操作码定义与编码函数 |
| `compiler/codegen.py` | 字节码生成器（发射各操作码） |
