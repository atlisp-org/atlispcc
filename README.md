# atlispcc — Atlisp Compiler Collection（FAS4 编译器套件）

`atlispcc`（**A**uto**L**ISP **C**ompiler **C**ollection 的缩写）是一个统一的 CLI 编译器套件，用于将 AutoLISP (`.lsp`) 编译为 FAS4 字节码 (`.fas`)，反编译 FAS4 回 Lisp，链接多个 FAS 文件，以及验证 Lisp 语法。输出与 AutoCAD 编译器的紧凑 stub 格式兼容，可在 CAD 中加载执行。

## 特性

- **编译** `.lsp → .fas`，可选 `-O0`~`-O3` 优化级别
- **反编译** `.fas → .lsp`（支持自包含 / 紧凑 stub 两种布局）
- **反汇编 / 汇编** `.fas ↔ .lasm`（互为逆操作）
- **多文件链接** `.fas` 合并，自动重排符号/函数索引并修复交叉引用
- **VLX 容器** 打包 FAS 文件，支持独立命名空间隔离
- **语法验证** 括号平衡、defun 结构、符号合法性等检查
- **CL 风格包系统** 编译期名混淆（`pkg|name`），不改变 FAS4 格式

## 安装

```sh
pip install atlispcc
```

安装后提供 `atlispcc` 命令（`compiler.cli:main`），并可通过模块方式调用：

```sh
atlispcc compile input.lsp output.fas
python -m compiler.cli compile input.lsp output.fas   # 等价
python -m decompiler.fas4_decompiler input.fas output.lsp   # 反编译
python -m tools.validate output.lsp                          # 验证
```

> 在源码仓库中也可直接运行脚本：`python compiler/cli.py ...`、`python decompiler/fas4_decompiler.py ...`、`python tools/validate.py ...`。

## CLI 快速参考

```sh
atlispcc compile [-O {0,1,2,3}] <input.lsp> [output.fas]        # 编译
atlispcc decompile <input.fas> [output.lsp]                      # 反编译 FAS → Lisp
atlispcc disasm <input.fas> [output.lasm]                        # 反汇编 FAS → 字节码指令列表
atlispcc asm <input.lasm> [output.fas]                           # 汇编 .lasm → FAS
atlispcc validate <input.lsp>                                     # 验证
atlispcc link [-o OUTPUT] <input.fas> <input.fas> [...]          # 链接 FAS
atlispcc build-vlx <input.fas>... -o output.vlx [--export ...]   # 构建 VLX 容器
```

无子命令时默认为 compile：`atlispcc <input.lsp> [output.fas]`

## 快速开始

```sh
# 反编译
atlispcc decompile samples/bib.fas samples/bib_generic.lsp

# 验证语法
atlispcc validate samples/bib_generic.lsp

# 期望输出： [PASS] bib_generic.lsp
```

## 子命令详解

### compile — 编译 Lisp → FAS

```sh
# 基本编译
atlispcc compile input.lsp output.fas

# 优化级别：0=无（默认），1=基本，2=激进，3=极致
atlispcc compile -O2 input.lsp output.fas
atlispcc compile -O3 --analyze input.lsp output.fas
```

- `-O1` 优化：常量折叠、死分支消除、窥孔优化
- `-O2` 优化：增加常量传播、死赋值消除，并重复执行基础优化
- `-O3` 优化：增加跨函数常量替换、死代码消除、小函数内联

#### 分析（--analyze）

使用 `--analyze` 配合任何 `-O` 级别查看编译统计：

```sh
atlispcc compile --analyze -O3 input.lsp output.fas
```

输出包含：
- 函数数、指令数、常量估算数
- 尾递归函数检测
- 每个函数的参数数、局部变量、调用关系
- 开启优化时输出优化前后对比

### decompile — 反编译 FAS → Lisp

```sh
atlispcc decompile input.fas output.lsp
# 或模块调用
python -m decompiler.fas4_decompiler input.fas output.lsp
```

### validate — 语法验证

```sh
# 单文件或多文件
atlispcc validate output.lsp
# 或模块调用
python -m tools.validate output.lsp
```

验证器检查：括号平衡、顶层形式为 defun、C: 命令无必需参数、符号名合法性、常见结构问题（if 参数不足、setq 参数为奇数、空 progn 等）。

验证通过输出：`[PASS] <文件名>`。失败则列出每条错误。

### disasm — 反汇编 FAS → .lasm

将 `.fas` 的字节码反汇编为可读的汇编文本（`.lasm`），便于检查指令流：

```sh
atlispcc disasm input.fas output.lasm
# 或
atlispcc disassemble input.fas
```

输出包含格式指令、符号表（`.symbols`）和各函数的指令列表（`.function`），如：

```
.format compact
.nsyms 4

.symbols
  0: SYMBOL hello
  1: SYMBOL x
.end_symbols

.function c:fn0, 0
  0x0000: DEFUN hello, 0
  0x0005: PUSH_G x
  0x000a: INIT_ARGS 2
.end_function
```

### asm — 汇编 .lasm → FAS

将 `.lasm` 汇编文本重新汇编为 `.fas`：

```sh
atlispcc asm input.lasm output.fas
# 或
atlispcc assemble input.lasm
```

`disasm` / `asm` 互为逆操作，支持 `.fas → .lasm → .fas` 往返，**seg0 逐字节一致**。
汇编器依据 `.lasm` 头部的 `.format` 指令选择布局：`.format compact`（CAD 紧凑 stub）
产物可直接在 CAD 中加载执行，`.format selfcontained` 为自包含格式。
`.lasm` 汇编语言语法见 `docs/lasm.md`。

### link — 多文件链接

将多个 `.fas` 文件合并为一个，自动重排符号/函数索引并修复交叉引用：

```sh
atlispcc link lib1.fas lib2.fas main.fas -o combined.fas
```

至少需要 2 个输入文件。输出默认以最后一个输入为基础命名。

### build-vlx — 构建 VLX 容器

将 FAS 文件打包为 VLX 容器，支持独立命名空间隔离：

```sh
atlispcc build-vlx app.fas lib.fas -o app.vlx --export main setup
```

- 自动生成 `_VLX` 元数据条目（含 `vl-doc-export` 调用）
- 加载 VLX 时 CAD 运行时创建隔离命名空间，仅导出的函数可被外部访问
- VLX 格式基于逆向工程，标记为实验性

## 完整工作流

```sh
# 1. 编译 Lisp → FAS（带优化）
atlispcc compile -O2 source.lsp program.fas

# 2. 链接多个 FAS
atlispcc link lib.fas program.fas -o combined.fas

# 3. 反编译以验证
atlispcc decompile combined.fas combined.lsp
atlispcc validate combined.lsp
```

## 在 CAD 中测试

```lisp
;; 加载编译后的 FAS 文件
(load "D:/atlisp-test/add.fas")
(add 2 3)  ;; → 5

;; 批量测试
(load "D:/atlisp-test/test_all_final.lsp")
```

### CAD 兼容性已验证（AutoCAD 24.1s）

| 功能 | 状态 | 示例 |
|------|------|------|
| 简单函数 | ✅ | `(add 2 3)` → 5 |
| 递归 | ✅ | `(fact 5)` → 120 |
| if/while/cond | ✅ | `(sum-to 5)` → 15 |
| 局部变量 | ✅ | `(swap 1 2)` → (2 1) |
| 字符串拼接 | ✅ | `(greet "CAD")` → "Hello, CAD!" |
| 多函数交叉引用 | ✅ | `(sum-sq 3 4)` → 25 |
| 尾递归 | ✅ | `(sum-tail 5 0)` → 15 |
| &optional/&rest | ✅ | `(f 3 2)` → 5, `(g 1 2 3)` → (1 (2 3)) |
| 勾股定理 | ✅ | `(hypot 3 4)` → 5.0 |
| 顶层 setq/set | ✅ | setq 在 defun 前后均正确执行 |
| lambda/quote | ⚠️ | lambda 参数绑定待增强 |

> 单函数文件（`fun.lsp`、`fact.lsp`）与 CAD 编译器输出解密后逐字节一致。

## 完整示例

```sh
atlispcc decompile samples/bib.fas samples/bib_generic.lsp
atlispcc validate samples/bib_generic.lsp
atlispcc decompile samples/PDI.fas samples/PDI_generic.lsp
atlispcc validate samples/PDI_generic.lsp
```

## 包系统 (CL-style Namespace)

### 语法

```lisp
(defpackage vec
  (:use)
  (:export vec2 vec3))

(in-package vec)

(defun vec2 (x) (+ x 1))   ; 内部名混淆为 vec|vec2

;; 跨包调用：
(in-package app)
(defun foo (x) (vec:vec2 x))  ; 编译时解析为 vec|vec2
```

### 原理

- CL 风格的包系统在**编译期**工作，不影响 FAS4 格式
- 包限定的函数名通过名混淆（`pkg|name`）编码为平展符号名
- FAS4 二进制格式完全不变，兼容所有 CAD
- 反编译器自动还原 `pkg|name` → `pkg:name`
- 只对 `defun` 名和 `pkg:name` 语法的引用生效，不干扰局部变量

## 优化级别

| 级别 | 说明 |
|-------|------|
| `-O0` | 原始编译，不做优化 |
| `-O1` | 基本清理：`(+ 1 2)` → `3`、`(if T e1 e2)` → `e1`、`(progn x)` → `x` |
| `-O2` | 激进优化：`(setq x 3) (+ x 1)` → `(+ 3 1)`、移除未使用的 `setq` |
| `-O3` | 极致优化：内联单次调用函数、跨函数常量替换、删除 `exit`/`quit` 后的死代码 |

## 工具脚本

源码仓库内的辅助分析工具（`tools/`，**不随 pip 包分发**，仅仓库内可用）：

- `tools.fas-analyzer` — FAS4 文件分析（`--dump`/`--json`）
- `tools.fas-split` — 函数分割（`--trim`/`--outdir`）
- `tools.decrypt_fas4` / `tools.crack_key` — 解密/密钥破解

用法与输出说明见 `docs/development.md`。

## 兼容性

反编译器自动加入包装函数以避免内建函数冲突：

- `fas-polar1` / `fas-rtos1` / `fas-rtos3`
- `fas-getvar2` / `fas-getvar3`
- `fas-1-`
- `in_param` / `fas-assoc-value`
- `fas-select-entity` / `projet_pa_projet_ar_projet`

不同 CAD 平台可能无法直接加载其他平台的 `.fas` 文件，因此本项目输出纯 `.lsp` 文本。

## 限制

- 外部依赖（其他 `.fas`、`.vlx`、`.arx`、`.dcl`、`.odcl`、`.lsp`）不会自动打包
- 部分行为从字节码推断，非原始源码恢复
- 输出可能需要手动清理

## 文档

- `docs/cad-stub-format.md` — AutoCAD 紧凑 stub 格式规范与兼容实现（核心）
- `docs/fas-format.md` — FAS4 二进制文件格式详解
- `docs/opcodes.md` — 操作码参考
- `docs/lasm.md` — LASM 汇编语言参考（disasm/asm 文本格式）
- `docs/development.md` — 开发者说明（架构、管线、测试、代码规范）
- `docs/development-plan.md` — 开发计划、遗留问题与路线图

## 安全

反编译生成的 `.lsp` 应先审查再使用。先在空白图形中测试。某些命令可能会创建、修改或删除图形实体。
