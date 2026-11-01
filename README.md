# atlispcc — Atlisp Compiler Collection（FAS4 编译器套件）

**简体中文** | [English](README.en.md)

`atlispcc`（**A**uto**L**ISP **C**ompiler **C**ollection 的缩写）是一个 CLI 编译器套件，用于将 AutoLISP (`.lsp`) 编译为 FAS4 字节码 (`.fas`)，反编译 FAS4 回 Lisp，链接多个 FAS 文件，以及验证 Lisp 语法。输出与 AutoCAD 编译器的紧凑 stub 格式兼容，可在 CAD 中加载执行。

## 特性

- **编译** `.lsp → .fas`，可选 `-O0`~`-O3` 优化级别
- **反编译** `.fas → .lsp`（支持自包含 / 紧凑 stub 两种布局）
- **反汇编 / 汇编** `.fas ↔ .lasm`（互为逆操作）
- **多文件链接** `.fas` 合并，自动重排符号/函数索引并修复交叉引用
- **VLX 容器** 按 Autodesk 官方 **VRTLIB-1** 布局打包 `.fas` / `.dcl` / 文本成员
  （`LOAD` 记录 + 4 字节对齐记录表 + 16 字节文件尾），可解包、可 `info` 查看；
  `--export` 编译 `_VLX` 导出桩
- **语法验证** 括号平衡、defun 结构、符号合法性等检查
- **CL 风格包系统** 编译期名混淆（`pkg|name`），不改变 FAS4 格式
- **包级批量编译** `project` 子命令按 `pkg.lsp` 的 `:FILES` 或 Visual LISP
  `.prj` 的 `:OWN-LIST` 编译全部 Lisp 源，资源文件自动跳过，输出 JSON 报告
  （CI / Agent 可直接消费）；`:MERGED` 工程自动链接为单个模块
- **大型 @lisp 包支持** 顶层 `(progn ...)` 包裹、条件/嵌套 defun、
  多 kwote 回调（`(function (lambda ...))`）与 >256 符号大文件
  （5 字节 USUBR / 6 字节 FUNC 宽格式）均可编译，产物在 CAD 完整加载运行
- **kwote 机制** `(function (lambda ...))` 内嵌 `-lambda-` DEFUN、顶层
  `(set/setq 'sym (lambda ...))` 内嵌 `-lambda-` SUBR（与 CAD 逐字节一致）
- **`engine/` SBCL 运行时** 独立于 CAD/FAS 的 AutoLISP 求值环境
  （`al-eval-source`/`al-run-file`/`al-repl`），作为编译器语义的跨校验器

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
 atlispcc build-vlx <input...> -o output.vlx [--export ...]      # 构建 VRTLIB-1 VLX
 atlispcc unpack-vlx <input.vlx> [-o DIR] [--list]               # 解包 VLX 成员
 atlispcc zelx <input.lsp|input.fas> [output.zelx]                # 构建 ZWCAD ZELX
 atlispcc unzelx <input.zelx> [output.fas]                        # ZELX 恢复为 FAS
 atlispcc info <input.fas|input.zelx|input.vlx> [--json]          # 快速概览：头/段/函数目录
 atlispcc analyze [-f text|dot|mermaid|json] [-o OUT] [--no-cc] <lsp|fas>  # 调用图/依赖分析
 atlispcc roundtrip <input.lsp> [-O {0,1,2,3}] [--keep]           # 往返冒烟测试
 atlispcc project <pkg.lsp|包目录|file.prj> [-o OUTDIR] [-O 0..3] [--json]  # 批量编译
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

#### 可复现构建（--date / --salt）

FAS4 尾部密钥 = **盐（6~10 字节）+ 15 字节 `;fas4 crunch` 标记**，盐由 Autodesk 官方
ANSI-C LCG（`random&`）生成：字节域 `1..255`（永不出现 `0x00`）、相邻不重复、
输出为抽取顺序的逆序。默认用当前时间播种，因此两次构建的 crunched 字节不同；
需要逐字节一致的产物时：

```sh
atlispcc compile app.lsp app.fas --date 2/3/26 --salt deterministic
atlispcc compile app.lsp app.fas --date 2/3/26 --salt seed:12345
atlispcc compile app.lsp app.fas --salt hex:0102030405
```

- `--date M/D/YY` 钉住尾部 `$;A<M>/<D>/<YY>` 时间戳（默认当天）
- `--salt deterministic` 使用固定盐 `01 02 … 08`
- `--salt seed:<n>` 用该种子生成 Autodesk 官方形状的盐（可复现）
- `--salt hex:<bytes>` 直接指定盐字节（6~10 字节，超出范围读取端无法定位密钥）
- 同一源码 + 同一 `--date`/`--salt` ⇒ **逐字节相同的 `.fas`**（`tests/test_fas_trailer.py` 锁定）

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

FAS 输出：格式（`compact` / `selfcontained`）、`nsyms`、seg0/seg1 大小、资源段
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

### build-vlx — 构建 VRTLIB-1 VLX 容器

把 `.fas` / `.dcl` / 文本成员打包为 Autodesk 官方 **VRTLIB-1** 容器：

```sh
atlispcc build-vlx app.fas -o app.vlx
atlispcc build-vlx app.fas res/dlg.dcl readme.txt -o app.vlx --export main setup
atlispcc build-vlx app.fas -o app.vlx --no-separate-namespace --no-protected
atlispcc build-vlx --prv app.prv              # 按 VLIDE 的 .prv 规范打包
atlispcc build-vlx --prv app.prv --json       # 打包报告（成员/开关/错误）
atlispcc unpack-vlx app.vlx -o dist/app       # 解包成员（默认结构校验）
atlispcc unpack-vlx app.vlx --stub load.lsp   # 生成 (load "…") 加载桩
atlispcc info app.vlx                         # 查看 LOAD 规格与成员表
```

容器布局（与 AutoCAD `PRV`/`KLB` 产物逐字节一致）：

```
"VRTLIB-1" + u32 文件尾偏移
记录 #0  u32 total, u16 tag=1240, u8 len, "LOAD", LOAD 规格文本
记录 #n  u32 total, u16 tag,    u8 len, NAME,  payload   （各自 4 字节对齐）
u32 0 + "VRTLIB-1" + u32 0                               （16 字节文件尾）
```

- 记录 tag：`1330` = `.fas`，`1350` = `.dcl`，`1335` = 文本，`1340` = `.dvb`
- 成员名 = `basename` 大写化（DBCS 双字节整体保留）；payload 与独立文件逐字节相同
- LOAD 规格 = `((:protected . T) (:active-x . T) (:separate-namespace . T) (:load-file-list (:fas "app.fas") …))`
- `--export` 额外编译 `_VLX` 导出桩（`(vl-doc-export 'main)`）并排进 LOAD 清单
- 文本/`.dvb` 成员只作为随包资源携带，不进 LOAD 清单
- `--prv <file>`：读 Visual LISP 应用规范，`:lsp` 现场编译、`:prj` 先编译工程、
  `:require-file-list` 作为随包资源；`:target` 决定默认输出（`-o` 优先）
- `--date` / `--salt` 同样适用于打包（`--prv` 时传给内部编译/链接）
- `--prv --json` / `--report <path>`：输出结构化打包报告（`target`/`members`/
  `compiled`/`switches`/`errors`/`diagnostics`），退出码 1 表示有错误

### project — 包级 / 工程级批量编译（CI / Agent）

读取 `pkg.lsp` 里的 `:FILES`，或 Visual LISP 工程文件 `.prj` 的 `:OWN-LIST`，
把其中的 Lisp 源文件逐个编译，资源文件（`.pat` / `.dwg` / `.txt` …）自动跳过：

```sh
atlispcc project packages/at-landscape
atlispcc project packages/at-landscape -o dist/at-landscape -O2
atlispcc project packages/at-landscape --json --report build-report.json
atlispcc project packages/at-landscape --dry-run     # 只列文件
atlispcc project myapp.prj                           # Visual LISP 工程
```

`.prj` 支持：

```lisp
(VLISP-PROJECT-LIST
  :NAME "demo"
  :OWN-LIST ("src/a.lsp" "src/b" "src")     ; 目录递归收集 *.lsp，无扩展名补 .lsp
  :PROJECT-KEYS (:BUILD (:OPTIMIZE :LINK) :SAFE-MODE T :MERGED T :MSGLEVEL 1)
  :FAS-DIRECTORY "./build")                  ; -o 优先
```

- `:MERGED T` 且产出 ≥2 个模块时，自动用链接器合成 `<NAME>.fas`
- `:BUILD (:OPTIMIZE …)` 且未显式给 `-O` 时按 `-O1` 编译
- `:REQUIRE` / `:LOAD` 的顺序依赖会追加到 `:OWN-LIST` 之后编译
- 单文件失败不会中断整批（`--stop-on-error` 可改为遇到错误即停）
- 退出码：全部成功 0；有编译错误/缺文件 1
- `--json` 输出 `summary`（ok/error/missing/skipped）与逐文件 `status/bytes/elapsed_ms/log`


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
`scripts/cad_verify.py` 逐个编译 t01-t24 + i18n → 在 CAD 加载 → 断言返回值（25 项通过）。

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
| `*error*` 错误处理 | ✅ | `(t24-handler-test)` → "handler-ran"（t24_star_error 真机用例） |
| **多文件链接** | ✅ | `atlispcc link` 输出与 CAD 直接编译逐字节一致，CAD 真机全部函数可调用（含跨文件交叉引用、多参数、重名冲突） |
| **VLX（VRTLIB-1）** | ✅ | `atlispcc build-vlx` 产物在 CAD `(load "app.vlx")` 成功；`--export` 的函数在宿主命名空间可用（`(SUBR 42)`），未导出函数保持隔离 |

> 单函数文件（`fun.lsp`）与 CAD 编译器输出解密后逐字节一致。
> `CAD_T_SERIES_IDENTICAL` 锁入 **6 项** byte-identity（andor/and2/or2/andval + chinese + qsingle，
> 原 t0X 源已迁移至 `tests/compile_src/`，其 golden 由结构断言覆盖）；i18n 拆分件 byte-identity 回归。
> 链接输出与 `tests/cad/link/*_cad.fas` **3 份 CAD golden** 逐字节一致。
> CAD 真机验证 **25/25**（`scripts/cad_verify.py`，t01-t24 + i18n）。
> **VLX 容器真机验证**（2026-11，AutoCAD 24.1s）：`python scripts/cad_verify_vlx.py`
> 生成探针 VLX → `(load "…/probe.vlx")` → 断言 `(type vlx-probe)`=SUBR、调用返回 42、
> 未导出函数为 nil（独立命名空间隔离生效）。
>
> **@lisp kernel 全量对拍**（2026-08-27）：`../kernel/src/` 下全部 **67 个 `.lsp`**
> 与 AutoCAD 24.1s 真机产物（`(vlisp-compile 'st ...)`）**逐字节一致**（seg0 + seg1 +
> nsyms），含条件 defun 绑定、LET 原生、vlax-for 枚举、嵌套 defun、`&optional`/`&rest`
> 变参等复杂结构。状态用 `scripts/kernel_compare_http.py`（ours→compare）复核。
>
> **@lisp 综合包 atlisp_u 全量对拍**（2026-08-29）：`tests/atlisp_u.lsp`（502 函数 +
> 221 顶层语句）seg0+seg1+nsyms 与 CAD golden `tests/atlisp_u_cad2.fas` **逐字节一致**，
> 覆盖 commands+顶层混合 gvar 槽重映射、顶层 kwote lambda func-obj 让位、条件 defun
> mid 发射、`set` 协议槽等复杂混合场景。

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
- `scripts/cad_verify.py` / `scripts/cad_verify_vlx.py` — CAD 真机验证（编译产物断言 / VRTLIB-1 VLX 加载与命名空间导出；共享目录缓存导致看不到新文件时用 `--remote-file probe.vlx --wait 5`）
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
- `docs/vlx-format.md` — VLX（VRTLIB-1）容器格式、LOAD 规格与校验规则
- `docs/lasm.md` — LASM 汇编语言参考（disasm/asm 文本格式）
- `docs/compilation-process.md` — 编译过程说明（.lsp → .fas 各阶段详解）
- `docs/development.md` — 开发者说明（架构、管线、测试、代码规范）
- `docs/development-plan.md` — 开发计划、遗留问题与功能完善路线图
- `engine/` — SBCL AutoLISP 运行时（`engine/atlisp.asd`），实验性跨校验器

## 安全

反编译生成的 `.lsp` 应先审查再使用。先在空白图形中测试。某些命令可能会创建、修改或删除图形实体。
