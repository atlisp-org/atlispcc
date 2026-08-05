# AutoCAD 与 ZWCAD 字节码操作码对比

> 逆向来源：AutoCAD FAS4 格式（`asm/opcodes.py` / `decompiler/fas4_decompiler.py`）
> 与 ZWCAD `LispConverter.exe`（`tools/zelx_build.py` 的双 opcode 映射表）。
> 结论经 ZWCAD 实测验证：生成的 `.zelx` 加载成功。

## 核心结论

**语义等价，数值不通用。**

AutoCAD 与 ZWCAD 的字节码引擎源自同一 Lisp 字节码血统，指令集**架构相同**
（PUSH_G/USUBR/JUMP/GET_LOCAL 等操作一致、操作数字段格式一致），但**操作码
字节值编码完全不同**，且存在**字节值冲突**（同一字节含义不同）。因此：

- 不能把 AutoCAD `.fas` 的字节码直接放进 `.zelx` 载荷
- LispConverter（及 `atlispcc zelx`）必须**重映射操作码**
- 因操作数格式一致，重映射（仅换字节值）后语义完全保持 → 可成功执行

## 操作码对照表

### 函数代码（fas seg0 → zelx 段1目录）

| 语义 | AutoCAD | ZWCAD | 操作数 |
|---|---|---|---|
| DEFUN | 14 | 01 | argc×3 + mode |
| PUSH_G | 09 | 34 | u16 |
| GET_LOCAL | 5c | 2f | u16 |
| INIT_ARGS | 18 | 05 | u16 |
| PUSH_VALUE | 03 | 24 | u16 |
| PUSH_INT8 | 32 | 41 | u8 |
| PUSH_INT32 | 33 | 42 | i32 |
| USUBR | 35 | 0d | argc + idx |
| FUNC | 51 | 0d | argc + idx |
| BUILD_LIST | 39 | 45 | u16 |
| SETQ_G | 06 | 27 | u16 |
| POP | 0a | 2a | — |
| JMP16_IFNOT | 0d | 36 | s16 |
| JMP16_IF | 0e | 37 | s16 |
| JMP32_IFNOT | 67 | 1a | s32 |
| JUMP | 57 | 16 | s32 |
| CLEAR_ARGS | 19 | 06 | u16 |
| END_DEFUN | 16 | 03 | — |
| PUSH_NIL | 01 | 22 | — |

### 资源流（fas seg1 → zelx 载荷）

| 语义 | AutoCAD | ZWCAD | 操作数 |
|---|---|---|---|
| 模块头 / DEFUN | 14 | 01 | 4B |
| PUSH_NIL | 01 | 22 | — |
| PUSH_G | 09 | 34 | u16 |
| SETQ_G | 06 | 27 | u16 |
| POP | 0a | 2a | — |
| CONS | 2a | 40 | — |
| PUSH_INT8 | 32 | 41 | u8 |
| PUSH_INT32 | 33 | 42 | i32 |
| BUILD_LIST | 39 | 45 | u16 |
| DEFCODE | 3a | 46 | — |
| GVARINIT | 43 | 49 | var_pos + st_init |
| INIT_DONE | 1c | 2c | — |
| JUMP | 57 | 16 | s32 |
| 符号块 | 5b | 57 | names\0... |
| 单符号块（保留大小写） | 56 | — | name\0 00（`vl-ACAD-defun`） |
| FUNC_REF | 35/51 | — | argc + idx（命令模块代码） |
| 字符串块 | 55 | 55 | count + len + data |
| END_DEFUN | 16 | 03 | — |

### 未变 / 恒等的操作码

| 语义 | 两平台 |
|---|---|
| 字符串块 | 55（完全一致）|
| 符号块内部名字 | 原样保留（仅块标记 5b→57）|
| PUSH_VALUE 单字节[0] | 03（调用后清理，资源流）|
| PUSH_REAL | 3b（NUL 结尾 ASCII）|

## 字节值冲突表（关键风险）

同一字节在两套体系里含义不同，**直接混用会解码错乱**：

| 字节 | AutoCAD 含义 | ZWCAD 含义 |
|---|---|---|
| 03 | PUSH_VALUE | END_DEFUN |
| 16 | END_DEFUN | JUMP |
| 24 | ATOM | PUSH_VALUE |
| 2a | CONS | POP |
| 34 | EVAL | PUSH_G |
| 41 | （未定义）| PUSH_INT8 |
| 42 | （未定义）| PUSH_INT32 |
| 45 | （未定义）| BUILD_LIST |
| 46 | FIX_ADD | DEFCODE |
| 49 | FIX_DIV | GVARINIT |
| 57 | JUMP | 符号块 |
| 27 | （未定义）| SETQ_G |
| 2c | （未定义）| INIT_DONE |
| 1a | （未定义）| JMP32_IFNOT |
| 36 | （未定义）| JMP16_IFNOT |
| 37 | （未定义）| JMP16_IF |

> ZWCAD 把 0x22-0x49 区段重新分配给常用指令（PUSH_NIL/PUSH_G/SETQ_G 等），
> 并让 0x03/0x16/0x24/0x34/0x57 等字节承担与 AutoCAD 不同的角色。

## 语义等价性与操作数格式

- 两套字节码都含：压栈（PUSH_G/PUSH_VALUE/PUSH_INT8/PUSH_INT32）、
  局部变量（GET_LOCAL/SET_LOCAL）、赋值（SETQ_G）、调用（USUBR/FUNC）、
  控制流（JUMP/JMP32_IFNOT/JMP16）、函数边界（DEFUN/END_DEFUN/CLEAR_ARGS）、
  资源注册（GVARINIT/DEFCODE/INIT_DONE/符号块/字符串块）
- 对应指令的**操作数字段格式一致**（u8/u16/i32/s32/argc+idx）
- 因此重映射 = 仅替换操作码字节，操作数原样保留 → 语义不变

## 实测验证

- `atlispcc zelx` 按上表重映射，微型样本（15 个）与 LispConverter 官方产物
  **逐字节一致**
- 复杂文件（base-whole/at-math）生成的 `.zelx` 在 ZWCAD 中 **`_appload` 加载成功**

## 待确认

**ZWCAD 是否直接加载 AutoCAD 格式 `.fas`？**
- 若 @lisp 的 `.fas`（AutoCAD opcode）能被 ZWCAD `(load "...fas")` 直接执行，
  则 ZWCAD 引擎同时理解两套编码（.fas 用 AutoCAD opcode，.zelx 用 ZWCAD opcode）
- 若不能，则 `.fas` 也需先经 LispConverter 或 `atlispcc zelx` 转换

## 相关文件

- `asm/opcodes.py` — AutoCAD 操作码表
- `tools/zelx_build.py` — 双 opcode 映射（REMAP/SEG0 表）
- `docs/zelx-format.md` — ZELX 容器/加密/载荷格式
