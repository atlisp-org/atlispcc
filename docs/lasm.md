# LASM 汇编语言参考

> LASM = **L**isp **ASM**embly，FAS4 字节码的文本汇编表示。
> `disasm`（`.fas → .lasm`）与 `asm`（`.lasm → .fas`）互为逆操作。
> 实现见 `asm/assembler.py`，指令编码见 `docs/opcodes.md`。

## 概览

```
.fas ── disasm ──> .lasm（文本） ── asm ──> .fas
```

`.lasm` 是纯文本，每行一条指令，`;` 起始为注释。结构由以下几部分组成：

1. 文件头注释（可选）
2. `.format` 指令 — FAS 布局格式（`compact` / `selfcontained`）
3. `.nsyms` 指令 — gvar 槽数（紧凑 stub 格式）
4. `.symbols` 段 — 符号表
5. `.function` 段 — 每个函数一条指令列表

## 文件结构

```
; FAS4 assembly                 ← 文件头（可选注释）
; Source: xxx.fas
; Crunch date: A7/31/26
.format compact                  ← 格式指令：compact（CAD 紧凑 stub）/ selfcontained
.nsyms 4                        ← gvar 槽数（紧凑 stub 必需，自包含可省略）

.symbols                          ← 符号表段
  0: SYMBOL f2
  1: SYMBOL +
  2: SYMBOL b
  3: SYMBOL a
.end_symbols

.function f2, 1                   ← 函数段：名 + 符号索引
  0x0000: DEFUN f2, 0
  0x0005: PUSH_G 3
  ...
.end_function
```

### 格式指令（.format / .nsyms）

`disasm` 生成的 `.lasm` 头部包含 `.format` 与 `.nsyms` 指令，`asm` 据此选择
**布局格式**与符号槽数：

- `.format compact` — 与 AutoCAD 编译器一致的**紧凑 stub** 布局
  （`total_size = len(seg0_payload) - 2`，符号按资源注册序直接编址）。
  汇编产物可在 CAD 中加载执行。
- `.format selfcontained` — 自包含布局（`total_size = len(seg0_payload)`）。
- `.nsyms N` — gvar 槽数；缺省时按 `len(entries) - 函数数 + 1` 推导。

手工编写的 `.lasm` 可省略这两条指令：汇编器按指令特征自动判定
（出现 `END_DEFUN`/`ALPHA`/`BETA` 视为自包含，否则视为紧凑 stub）。

## 符号表（.symbols）

每行 `序号: SYMBOL 符号名`，序号即符号槽索引（字节码中的寻址基准）。

```
.symbols
  0: SYMBOL __init__
  1: SYMBOL my-func
  2: SYMBOL v
.end_symbols
```

- 序号必须连续（汇编器按行填充空槽）
- 符号名与源码/反汇编输出一致，区分大小写
- `__init__` 是特殊函数名：其指令进入初始化代码段（模块入口），见下文

## 函数段（.function）

每行 `.function <名>, <符号索引>` 开始，`.end_function` 结束：

```
.function my-func, 1
  0x0000: DEFUN my-func, 0
  0x0005: INIT_ARGS 1
  0x0008: ALPHA 0
  0x000a: PUSH_G 2
  0x000c: GET_LOCAL 0
  0x000e: FIX_ADD
  0x000f: SET_LOCAL 0
  0x0011: BETA 0
  0x0013: END_DEFUN
  0x0014: NIL
.end_function
```

- `<名>`：函数名（与符号表一致）；`__init__` 为初始化代码段
- `<符号索引>`：函数名在符号表中的槽位
- 每条指令行格式：`0x<偏移>: <助记符> <操作数...>`
- 偏移前缀（`0x0000:`）在汇编时**忽略**，仅作可读性参考；指令按行序连续编码

### __init__（初始化代码段）

名为 `__init__` 的函数体指令被放置在所有函数字节码**之前**，作为模块入口/初始化代码：

```
.function __init__, 0
  0x0000: DEFUN test-add, 0
  ...
.end_function
```

## 指令格式

指令行 = `0x<偏移>: <助记符> [, 操作数...]`，操作数用逗号分隔。

### 操作数解析

汇编器按以下规则把操作数文本转为数值/符号索引（`_parse_ops`）：

| 写法 | 含义 |
|------|------|
| `符号名` | 符号槽索引（查符号表，如 `PUSH_G x` → `PUSH_G 2`） |
| `[N]` | 显式数字索引（超出符号表范围时用，如 `[5]`） |
| `123` | 十进制整数 |
| `1.5` | 十进制浮点数 |

### 符号操作数特例

某些指令的操作数在 .lasm 中**显示为符号名**（反汇编输出），汇编时解析回索引：

| 指令 | 操作数 1 | 操作数 2 |
|------|---------|---------|
| `DEFUN` | 符号（gvar 引用） | 偏移 |
| `FUNC` / `USUBR` | argc | 符号索引 |
| `PUSH_VALUE` / `PUSH_G` / `PUSH_GLOBAL` / `SETQ_G` | 符号索引 | 附加字节 |

```
0x0005: PUSH_VALUE f2, 0      ; f2 = 符号槽 0
0x000a: USUBR 2, 1            ; argc=2, 符号槽 1（如 +）
0x000e: SETQ_G x, 0           ; x = 符号槽 2
```

> **重复符号槽**：递归/跨函数调用会使同一函数名占多个符号槽。反汇编器对
> 重复名字输出显式数字索引 `[N]`（而非符号名），避免汇编时解析回首个槽。
> 例 `PUSH_VALUE [0]`（min 的递归函数名槽）。

## 紧凑 stub 编码（.format compact）

紧凑 stub 格式的部分指令编码与自包含不同（`_asm_instr` 在 `compact=True` 时）：

| 指令 | 紧凑 stub | 自包含 |
|------|----------|--------|
| `USUBR` / `FUNC` | `35/51 <argc> <idx:1>`（3 字节） | `35/51 <argc> <idx:2> <flags> ...`（5/6 字节） |
| `PUSH_VALUE [0]` | `03`（单字节） | `03 <idx:2>`（3 字节） |
| `PUSH_VALUE [i>0]` | `03 <idx:2>`（3 字节） | 同左 |
| `CLEAR_ARGS` | `19 <argc:2> 00`（3 字节） | `19 <argc:2>`（3 字节） |
| `DEFUN` | `14 <argc>x3 <mode>`（argc 编码） | `14 <gv:2> <off:2>`（gvar 编码） |

汇编器依据 `.format` 指令选择编码；缺省按指令特征自动判定。

### GET_LOCAL_WIDE（长编码局部变量）

`GET_LOCAL` 存在两种字节编码：短形式 `05 <slot:1>` 与长形式 `5c <slot:2>`。
反汇编器对长形式输出助记符 `GET_LOCAL_WIDE` 以区分；汇编 `GET_LOCAL_WIDE N` 强制编码为 `5c <u16>`。

```
0x000a: GET_LOCAL_WIDE 0      ; = 5c 00 00（3 字节）
0x000a: GET_LOCAL 0           ; = 05 00（2 字节，自包含格式）
```

## 操作数格式（对应 docs/opcodes.md）

| 格式 | 编码 | .lasm 操作数示例 |
|------|------|-----------------|
| 无操作数 | `POP`、`DUP`、`FIX_ADD` 等 | — |
| `'1'` | 单字节 | `PUSH_INT8 5` |
| `'2'` | 双字节 | `PUSH_G 3`、`SETQ_G x`、`INIT_ARGS 5` |
| `'4'` | 四字节 | `PUSH_INT32 65536` |
| `'s4'` | 有符号四字节 | `JUMP -12`、`BR_IF_TRUE 13` |
| `'bb'` | 两单字节 | `COPY_ELEM 1, 2` |
| `'u'` | USUBR（argc, idx, flags） | `USUBR 2, 1, 0` |
| `'f'` | FUNC（argc, idx, flags, zero） | `FUNC 1, 3, 0, 0` |
| `'h'` | DEFUN（gvar, offset） | `DEFUN f2, 0` |
| `'e'` | EVAL（argc, flag） | `EVAL 1, 0` |
| `'z'` | NUL 结尾实数 | `PUSH_REAL 3.14` |

## 支持的操作码

`.lasm` 可编码 `docs/opcodes.md` 中列出的全部指令。常见助记符：

- 栈：`NIL` `PUSH_NIL` `PUSH_T` `PUSH_VALUE` `PUSH_G` `PUSH_GLOBAL` `PUSH_INT8` `PUSH_INT32` `PUSH_REAL` `POP` `DUP`
- 局部变量：`GET_LOCAL` `GET_LOCAL_WIDE` `SET_LOCAL` `CLEAR_LOCAL`
- 赋值：`SETQ_G`
- 调用：`USUBR` `FUNC` `EVAL`（`USUBR` 即 CAD 内部所称的 **Xsubr**，调用函数）
- 算术/逻辑：`FIX_ADD` `FIX_SUB` `FIX_MUL` `FIX_DIV` `FIX_MOD` `FIX_LEQ` `FIX_GEQ` `FIX_LT` `FIX_GT` `INC` `DEC` `NOT` `ATOM` `CAR` `CDR` `CONS`
- 控制流：`JUMP` `JUMP32` `BR_IF_TRUE` `JMP16_IFNOT` `JMP16_IF` `COND_OR` `AND` `AND2` `EXIT_IF_ZERO` `EXIT_IF_NOT_ZERO`
- 函数定义：`DEFUN` `DEFUN2` `END_DEFUN` `END_DEFUN_CLEANUP` `INIT_ARGS` `CLEAR_ARGS` `ALPHA` `BETA` `INIT_DONE` `DEFCODE` `NOP`
- 其他：`LIST_OBJ` `BUILD_LIST` `COPY_ELEM` `EVAL`

## 示例

### 编译后反汇编

```sh
atlispcc compile test.lsp test.fas
atlispcc disasm test.fas test.lasm
```

### 手工编写最小函数

```sh
cat > min.lasm <<'EOF'
; 最小加法函数
.symbols
  0: SYMBOL __init__
  1: SYMBOL add
  2: SYMBOL a
  3: SYMBOL b
  4: SYMBOL +
.end_symbols

.function __init__, 0
  0x0000: DEFUN add, 0
  0x0005: INIT_ARGS 5
  0x0008: PUSH_G 4
  0x000a: GET_LOCAL_WIDE 0
  0x000d: GET_LOCAL_WIDE 1
  0x0010: FIX_ADD
  0x0011: END_DEFUN
.end_function

.function add, 1
  0x0000: ALPHA 1
  0x0002: PUSH_G 4
  0x0004: PUSH_VALUE a
  0x0006: PUSH_VALUE b
  0x0008: USUBR 2, 4
  0x000b: BETA 0
  0x000d: NIL
.end_function
EOF
atlispcc asm min.lasm min.fas
```

### 往返验证

```sh
atlispcc asm test.lasm test.fas
atlispcc disasm test.fas roundtrip.lasm
diff test.lasm roundtrip.lasm   # 应无差异
```

## 注意事项

- 汇编器**忽略**偏移前缀，按行序编码；手工编写时偏移可随意填写或省略
- 符号索引超出符号表范围会编码为原数字（或 `[N]` 形式）
- 缺省格式为自包含；紧凑 stub（`.format compact`）产物与 CAD 布局一致，
  可在 CAD 中加载执行。`disasm` 默认按紧凑 stub 输出（AutoCAD 编译器产物）
- `disasm` 输出的 `.lasm` 可通过 `asm` **逐字节还原**原始 `.fas`
  （seg0 完全一致；含顶层表达式的文件其 seg1 模块代码不随 `.lasm` 携带，见 `docs/cad-stub-format.md`）
- 反汇编器对未知操作码输出 `UNK_<hex>`，汇编时不支持（编码会失败）
