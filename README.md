# atlispcc — Atlisp Compiler Collection（FAS4 编译器套件）

`atlispcc`（**A**uto**L**ISP **C**ompiler **C**ollection 的缩写）是一个 CLI 编译器套件，用于将 AutoLISP (`.lsp`) 编译为 FAS4 字节码 (`.fas`)，反编译 FAS4 回 Lisp，链接多个 FAS 文件，以及验证 Lisp 语法。输出与 AutoCAD 编译器的紧凑 stub 格式兼容，可在 CAD 中加载执行。

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

> 在源码仓库中也可用 `python -m` 形式直接运行：`python -m compiler.cli ...`、`python -m decompiler.fas4_decompiler ...`、`python -m tools.validate ...`（`python compiler/cli.py` 与 `python -m compiler.cli` 均可用——AST 模块已改名 `ast_nodes.py`，不再遮蔽 stdlib `ast`）。

## CLI 快速参考

```sh
atlispcc compile [-O {0,1,2,3}] <input.lsp> [output.fas]        # 编译
atlispcc decompile <input.fas> [output.lsp]                      # 反编译 FAS → Lisp
atlispcc disasm <input.fas> [output.lasm]                        # 反汇编 FAS → 字节码指令列表
 atlispcc asm <input.lasm> [output.fas]                           # 汇编 .lasm → FAS
 atlispcc validate <input.lsp>                                     # 验证
 atlispcc link [-o OUTPUT] <input.fas> <input.fas> [...]          # 链接 FAS
 atlispcc build-vlx <input.fas>... -o output.vlx [--export ...]   # 构建 VLX 容器
 atlispcc zelx <input.lsp|input.fas> [output.zelx]                # 构建 ZWCAD ZELX
 atlispcc unzelx <input.zelx> [output.fas]                        # ZELX 恢复为 FAS
 atlispcc info <input.fas|input.zelx> [--json]                    # 快速概览：头/段/函数目录
 atlispcc analyze [-f text|dot|mermaid|json] [-o OUT] [--no-cc] <lsp|fas>  # 调用图/依赖分析
 atlispcc roundtrip <input.lsp> [-O {0,1,2,3}] [--keep]           # 往返冒烟测试
```

无子命令时默认为 compile：`atlispcc <input.lsp> [output.fas]`

## 快速开始

```sh
# 反编译（tests/cad/i18n-cad.fas 为仓库内 CAD 自包含样本）
atlispcc decompile tests/cad/i18n-cad.fas output.lsp

# 验证语法
atlispcc validate output.lsp

# 期望输出： [PASS] output.lsp
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

#### 编译报告（--report）

把编译统计与产物信息导出为 JSON（供 CI / 工具链消费）：

```sh
atlispcc compile -O2 input.lsp output.fas --report report.json
```

报告字段：`source`/`output`/`opt_level`/`encoding`、`analysis`（同 `--analyze`
统计）、开启优化时的 `optimized` 快照、`product`（`nsyms`、`codegen_nsyms`、
模块注册数、顶层表达式数、seg0/seg1 大小、seg1 items 数）。

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

### roundtrip — 往返冒烟测试

对单个 `.lsp` 一键自检：`compile → decompile → validate → compare`。

```sh
# 默认 O0
atlispcc roundtrip app.lsp
# 指定优化级别
atlispcc roundtrip app.lsp -O2
# 保留中间 .fas 与反编译 .lsp（打印路径）
atlispcc roundtrip app.lsp -O2 --keep
```

- **管线**：有意使用「裸内存管线」（与测试套件 `compile_and_decompile` 同款）——顶层
  表达式（defun 外的 `setq`/`princ`）保留在 seg0 字节码，反编译可还原字符串；CLI
  compile 管线把它们编进 seg1 模块代码，顶层 `princ` 反编译会退化为 `nil`。
- 输出报告 defuns/strings 原始与反编译数量及缺失/多余项，字符串逐条列出。
- 退出码：0=PASS，1=FAIL（比对差异、校验失败或编译/反编译异常均归 1）。
- 注意 `-O3` 的 `RemoveDeadFuncs` 会删除未被引用且非命令的函数，这类函数
  反编译后自然消失（属于有意的死代码消除，非 bug）。追求逐函数完整还原时
  用 `-O0`/`-O2`。

### info — 快速概览

不触发完整反编译，直接读取 `.fas`/`.zelx` 头部与资源段规模：

```sh
atlispcc info tests/cad/t01_math_cad.fas
atlispcc info tests/cad/i18n-cad.fas --json
```

FAS 输出：格式（`named-fas4`/compact）、`nsyms`、seg0/seg1 大小、资源段
解密大小与条目数、XOR 密钥长度、函数目录（catalog）、符号/字符串数、尾部标记。
ZELX 输出：`.zelx` 四段（X/Y/Z/sub）大小、payload 大小与密钥长度、payload 熵。

### analyze — 调用图 / 依赖分析

统一分析 `.lsp` 源码或 `.fas` 字节码的调用依赖，输出四种格式：

```sh
atlispcc analyze app.lsp                      # text 摘要
atlispcc analyze app.lsp -f dot  -o app.dot   # Graphviz
atlispcc analyze app.lsp -f mermaid
atlispcc analyze app.fas  -f json             # 结构化图数据
atlispcc analyze app.lsp --no-cc              # 不把 c:*/*error* 当入口
```

输出模型：**nodes**（函数 + 出/入度 + root/unused）、**edges**（程序内调用边）、
**roots**（`c:*`/`*error*` 或顶层表达式调用的函数）、**externals**（内建/外部引用）、
**unused**（无入边且非 root）。`.fas` 通过字节码扫描 USUBR/FUNC 操作数解析被调名，
DEFCODE 注册的公开函数自动提升为 root 避免误报 unused。

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

链接输出与 CAD 编译器直接编译同源码**逐字节一致**（seg0 + seg1 + nsyms + items，
`tests/cad/link/*_cad.fas` golden 回归）。CAD 真机可加载并调用全部函数：
- 简单多函数（`add`/`mul`）、跨文件交叉引用（`square`/`sum-squares`）
- 多文件多参数（`f1`/`f2`/`f3`）、重名函数首次定义优先（碰撞场景）

```sh
# 链接后立即在 CAD 中验证
atlispcc link lib.fas program.fas -o combined.fas
# 在 CAD: (load "combined.fas") 后调用 lib/program 中的全部函数
```

### build-vlx — 构建 VLX 容器

将 FAS 文件打包为 VLX 容器，支持独立命名空间隔离：

```sh
atlispcc build-vlx app.fas lib.fas -o app.vlx --export main setup
```

- 自动生成 `_VLX` 元数据条目（含 `vl-doc-export` 调用）
- 加载 VLX 时 CAD 运行时创建隔离命名空间，仅导出的函数可被外部访问
- VLX 格式基于逆向工程，标记为实验性

### zelx — 构建 ZWCAD ZELX

将 `.lsp` 或 `.fas` 直接构建为 ZWCAD 的 `.zelx` 分发格式（无需 LispConverter GUI）：

```sh
atlispcc zelx app.lsp app.zelx      # .lsp 自动先编译成 FAS4 再转换
atlispcc zelx app.fas app.zelx      # 直接转换 .fas
```

- `.zelx` = `!ZAS` 容器：载荷（资源）+ 段1目录（函数字节码）+ 滚动 XOR 加密
- 算法逆向自 ZWCAD `LispConverter.exe`；小型/简单文件与官方产物**逐字节一致**（15/15 样本）
- 复杂文件（大量符号/顶层表达式）仍需 ZWCAD 的压缩重编码（模块代码重编码 + 符号重排），见 `docs/zelx-format.md`

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

**自动化真机验证**（推荐）：
```sh
make cad-test    # 或: python scripts/cad_verify.py
```
`scripts/cad_verify.py` 逐个编译 t01-t15 → 在 CAD 加载 → 断言返回值（24 项通过）。

> **CAD 模态对话框自动关闭**：CAD 偶发弹出模态对话框（`alert` 错误框、命令中断框）
> 会阻塞 `atlisp-mcp` 的 eval 调用。可用 `tools.cad_dialog_killer` 自动关闭：
> ```sh
> # 在 CAD 测试前启动后台监听（自动点击确定/取消关闭任何 #32770 对话框）
> python -m tools.cad_dialog_killer <cad-pid> --watch --timeout-s 3600 &
> python -m tools.cad_dialog_killer all --watch --timeout-s 3600   # 或扫描全部 CAD 进程
> # 单次扫描：
> python -m tools.cad_dialog_killer <cad-pid>
> ```
> 工具用 C#（`tools/src/cad_dialog_killer.cs`）编译为 exe，首次运行自动编译，
> 枚举 CAD 窗口检测可见 `#32770` 对话框并模拟点击按钮关闭。已实测自动关闭
> `alert` 对话框并解除 MCP 阻塞（2026-08-08）。需 Windows + .NET Framework。

手动测试：
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
| lambda/quote | ✅ | `(map-inc '(1 2 3))` → (2 3 4)；lambda 参数局部化正确 |
| vla-/vlax- ActiveX | ✅ | `(t22-acad-doc)` 返回文档对象；编译产物与 CAD golden 逐字节一致 |
| command 交互调用 | ✅ | `(t23-created-circle-p)` → T（画圆→断言→自清理） |
| **多文件链接** | ✅ | `atlispcc link` 输出与 CAD 直接编译逐字节一致，CAD 真机全部函数可调用（含跨文件交叉引用、多参数、重名冲突） |

> 单函数文件（`fun.lsp`、`fact.lsp`）与 CAD 编译器输出解密后逐字节一致。
> t-series（t01-t18）与 `tests/cad/t01_math_cad.fas` 等 **19 份 CAD golden**
> 编译产物 byte-identity（含 t22 ActiveX）；链接输出与 `tests/cad/link/*_cad.fas`
> **3 份 CAD golden** 逐字节一致。CAD 真机验证 24/24（`scripts/cad_verify.py`）。

## 完整示例

```sh
# 编译 → 反编译 → 验证
atlispcc compile input.lsp input.fas
atlispcc decompile input.fas recovered.lsp
atlispcc validate recovered.lsp

# 反编译仓库内 CAD 样本
atlispcc decompile tests/cad/i18n-cad.fas output.lsp
atlispcc validate output.lsp
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

源码仓库内的辅助分析工具（`tools/`，随 pip 包一起分发，可用 `python -m` 形式调用）：

- `tools.fas-analyzer` — FAS4 文件分析（`--dump`/`--json`）
- `tools.fas-split` — 函数分割（`--trim`/`--outdir`）
- `tools.decrypt_fas4` / `tools.crack_key` — 解密/密钥破解
- `tools.find_key` — 在 FAS 中定位 XOR 加密密钥
- `tools.validate` — 生成的 `.lsp` 语法/危险函数（quit/exit/startapp）/危险命令（command-s 调 shell/del 等）/未使用局部变量检查
- `tools.compare_lsp` — `.lsp` 对比分析
- `tools.zelx_info` / `tools.zelx_diff` / `tools.zelx_build` / `tools.zelx_to_fas` — ZWCAD `.zelx` 解析/对比/构建/恢复（逆向 LispConverter）
- `tools.lisp_converter_auto` — ZWCAD LispConverter.exe GUI 自动化（样本生产）
- `tools.cad_probe` — MCP CAD 交互辅助（开发调试）
- `tools.cad_dialog_killer` — 自动关闭 CAD 模态对话框（alert 等，避免阻塞 MCP 会话）；`python -m tools.cad_dialog_killer <pid> [--watch]`
- `tools.analyze_rosetta` — Rosetta 代码分析

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

## 开发者

仓库提供 Makefile 快捷目标（`make help` 查看全部）：

```sh
make test        # pytest 全量测试
make check       # 一键全量检查（py_compile + pytest + disasm→asm 往返 + byte-identity）
make lint        # black --check + mypy
make format      # black 格式化
make build       # 构建分发包
make clean       # 清理构建产物与缓存
```

## 文档

- `docs/cad-stub-format.md` — AutoCAD 紧凑 stub 格式规范与兼容实现（核心）
- `docs/fas-format.md` — FAS4 二进制文件格式详解
- `docs/opcodes.md` — 操作码参考
- `docs/lasm.md` — LASM 汇编语言参考（disasm/asm 文本格式）
- `docs/compilation-process.md` — 编译过程说明（.lsp → .fas 各阶段详解）
- `docs/development.md` — 开发者说明（架构、管线、测试、代码规范）
- `docs/development-plan.md` — 开发计划、遗留问题与功能完善路线图

## 安全

反编译生成的 `.lsp` 应先审查再使用。先在空白图形中测试。某些命令可能会创建、修改或删除图形实体。
