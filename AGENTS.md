# atlispcc - Agent 指南

## 项目

**atlispcc** = **A**uto**L**ISP **C**ompiler **C**ollection，FAS4 字节码编译器套件：`.lsp` ↔ `.fas`（兼容 AutoLISP 的 CAD 平台）。

`atlispcc` — 统一 CLI 工具（`compiler/cli.py`），支持九个子命令：

```
atlispcc compile [-O {0,1,2,3}] <input.lsp> [output.fas]    # 编译 Lisp → FAS
atlispcc decompile <input.fas> [output.lsp]                # 反编译 FAS → Lisp
atlispcc disasm <input.fas> [output.lasm]                  # 反汇编 FAS → 字节码指令列表
atlispcc asm <input.lasm> [output.fas]                     # 汇编 .lasm → FAS
atlispcc validate <input.lsp>                              # 语法验证
atlispcc link [-o OUTPUT] <input.fas> <input.fas> [...]    # 多文件链接
atlispcc build-vlx <input.fas>... -o output.vlx [--export ...]  # VLX 容器
atlispcc zelx <input.lsp|input.fas> [output.zelx]          # ZWCAD ZELX（逆向 LispConverter）
atlispcc unzelx <input.zelx> [output.fas]                  # 从 .zelx 恢复 .fas
```

子命令别名：`compile→c`、`decompile→d`、`validate→v`、`disasm→disassemble`、`asm→assemble`。

无子命令时默认为 compile：`atlispcc <input.lsp> [output.fas]`

`decompiler/fas4_decompiler.py` 亦可直接调用：`python -m decompiler.fas4_decompiler <input.fas> [output.lsp]`

## 编译器管线

```
Lisp 源码 → Parser.parse() → AST
         → SymbolTableBuilder.build() → SymbolTable
         → Codegen.generate() → List[FunctionDef]（指令流）
         → [OptPipeline.optimize()  # 可选：-O1/-O2/-O3]
         → ResourceBuilder.build() → 资源段
         → FasWriter.write() → FAS4 二进制
```

## 反编译器管线

```
Fas4Parser.parse() → Disassembler.disassemble() → ControlFlowAnalyzer.find_functions() → LispGenerator.generate()
```

## 链接器管线

```
FAS A + FAS B + ... → 合并符号表/函数目录 → 重排索引 → 修复交叉引用 → 合并 FAS
```

## 关键文件

| 文件 | 作用 |
|---|---|
| `decompiler/fas4_decompiler.py` (2665 行) | 主反编译器：解析 + 反汇编 + 分析 + 生成 |
| `core/fas_core.py` (707 行) | 共享加密/解析/符号 — 被工具脚本使用，主反编译器通过 import 复用其 `find_key`/`decrypt_stream`/`build_mvar_tables`/`build_function_catalog` |
| `compiler/cli.py` | CLI 入口，子命令 dispatch |
| `compiler/parser.py` | Lisp 源码解析器 → AST |
| `compiler/ast_nodes.py` | AST 节点定义 |
| `compiler/symbol_table.py` | 符号表构建与作用域分析 |
| `compiler/codegen.py` | 字节码生成器（AST → 指令流） |
| `compiler/resource_builder.py` | 常量/符号/函数索引 → 资源段 |
| `compiler/fas_writer.py` | 指令流 → FAS4 二进制 |
| `compiler/opt.py` | 优化器：9 个 pass 跨 O1-O3 级别 |
| `compiler/analyzer.py` | 编译分析与统计（--analyze） |
| `asm/assembler.py` | 反汇编/汇编（.fas ↔ .lasm） |
| `asm/opcodes.py` | 操作码定义与编码函数（codegen/linker/汇编共用） |
| `compiler/linker.py` | 多文件 FAS 链接器 |
| `compiler/vlx_builder.py` | VLX 容器构建器 |
| `tools/validate.py` | 生成的 `.lsp` 语法验证器 |

工具脚本（`tools/decrypt_fas4.py`、`tools/fas-split.py`、`tools/fas-analyzer.py`、`tools/crack_key.py`、`tools/validate.py` 等）使用 `core/fas_core.py` 中的函数。`tools/zelx_info.py`（解密/解析 ZWCAD `.zelx`）、`tools/zelx_diff.py`（`.fas`↔`.zelx` 结构 diff）、`tools/zelx_build.py`（`.fas`→`.zelx` 写入器，小型/简单文件逐字节一致）基于逆向 LispConverter.exe 的成果，格式见 `docs/zelx-format.md`。微型样本 `samples/zelx-reversing/` 由 GUI 自动化（UIA + ctypes）产出。

## 优化器（compiler/opt.py）

| Pass | 作用 | 级别 |
|---|---|---|
| ConstantFold | `(+ 1 2)` → `3`, `(strcat "a" "b")` → `"ab"` | O1+ |
| DeadBranchElim | `(if T e1 e2)` → `e1`, `(while nil ...)` → `nil` | O1+ |
| PeepholeOpt | `(progn x)` → `x`, `(list)` → `nil` | O1+ |
| ConstantPropagate | `(setq x 3) (+ x 1)` → `(setq x 3) (+ 3 1)` | O2 |
| DeadAssignElim | 移除未使用的 `(setq x ...)` | O2 |
| CrossFuncConstPropagate | 常量返回的 0 参函数替换为常量 | O3 |
| DeadCodeElim | 删除 `exit`/`quit` 后的死代码 | O3 |
| InlineSmallFuncs | 内联单次调用的小函数 | O3 |
| RemoveDeadFuncs | 删除未被引用且非命令的函数（仅当有入口点时） | O3 |

## 命令

```sh
# 编译 + 优化
atlispcc compile -O2 input.lsp output.fas

# 反编译（tests/cad/i18n-cad.fas 为仓库内 CAD 自包含样本）
python -m decompiler.fas4_decompiler tests/cad/i18n-cad.fas output.lsp

# 验证输出
python -m tools.validate tests/bib_generic.lsp

# 链接
atlispcc link lib.fas main.fas -o combined.fas
```

```sh
pip install -e ".[dev]"                 # 安装依赖 + dev 工具（开发模式）
python -m pytest                        # 运行测试
python -m py_compile decompiler/fas4_decompiler.py # 快速语法检查
python -m py_compile compiler/opt.py
python -m build                         # 构建分发包
black .                                 # 格式化
mypy .                                  # 类型检查
```

Makefile 快捷目标（`make help` 查看全部）：
```sh
make test        # pytest 全量测试
make check       # 一键全量检查（等价 ./scripts/run_tests.sh）
make lint        # black --check + mypy
make format      # black 格式化
make build       # 构建分发包
make clean       # 清理构建产物与缓存
```

## 测试

**测试文件在 `tests/` 目录下**（pytest 风格，共 307 用例 + 1 skip 占位）：
- `test_parser.py` — AST 解析器（19 用例）
- `test_lexer.py` — 词法分析（11 用例：转义、注释、UTF-8、dotted）
- `test_symbol_table.py` — 符号表/作用域（10 用例）
- `test_analyzer.py` — 编译分析/尾递归（9 用例）
- `test_cli.py` — CLI 路径（22 用例：compile/-O/--analyze/validate/link/vlx/dispatch + validate 补强规则 + 源码编码检测）
- `test_compile_decompile.py` — 编译-反编译往返（68 用例，含 AutoCAD `fun-cad.fas` 参考反编译回归、复杂 LSP O2/O3 往返、t01-t15 系列 roundtrip、i18n 混合模式、§3.5d/e 折叠回归、§10.4 golden 参数名/循环结构回归、C4 DCL 对话框）
- `test_compiler_output.py` — FAS 输出正确性（56 用例，含 7 对 CAD golden 逐字节比对 + t-series byte-identity + i18n 原文件/拆分件 byte-identity 回归）
- `test_optimizer.py` — 优化 pass（32 用例，含循环携带变量回归）
- `test_linker.py` — 多文件链接（10 用例，含重名冲突警告）
- `test_assembler.py` — 反汇编/汇编往返（8 用例）
- `test_disasm.py` — 反汇编健壮性（9 用例，含未处理操作码降级）
- `test_resource_stream.py` — 资源码解析/资源段构建（24 用例：符号/字符串块、GVARINIT、DEFCODE、build_mvar_tables、资源码 vs 操作码区分）
- `test_packages.py` — CL 风格包系统（4 用例）
- `test_vlx_builder.py` — VLX 容器（3 用例）
- `test_variadic_args.py` — &optional/&rest 编译（17 用例，含多函数参数名恢复）
- `test_zelx.py` — ZWCAD ZELX 构建/解析（5 用例）

  一键运行全部检查：`./scripts/run_tests.sh`（py_compile + pytest + disasm→asm 往返 + byte-identity 状态）。

 手动测试文件 `tests/test_*.lsp` 也在该目录；CAD 兼容矩阵源文件 `tests/cad/t01_math.lsp`…`t15_cad_funcs.lsp` 是 `test_t_series_roundtrip` 的 fixture（编译→反编译→validate），源码与 CAD golden `.fas` 自包含存放在 `tests/cad/`。真机用例源文件另含 `tests/cad/t16_foreach.lsp`、`t17_repeat.lsp`、`t19_variadic.lsp`（`&optional`/`&rest`）、`t20_kwote.lsp`（`(function (lambda ...))` kwote 机制），由 `scripts/cad_verify.py` 编译加载验证。`tools/validate.py` 的 `SYMBOL_RE` 允许 `&`/`@`/`%`（`&optional`/`&rest`、`@::pkg`、`opt%` 等合法 AutoLISP 符号）。

## 兼容性

FAS4 输出格式与 AutoCAD 编译器一致：
- seg0 = 函数字节码（`<nsyms> $...`），seg1 = 资源段（常量/符号/函数索引）
- 紧凑 stub 格式 `total_size = len(seg0) + 1`（CAD 实测恒等：cross/m2/m3/multi/sh/lambda_test 六份产物；seg0 = `<nsyms> $` 后的纯字节码）；自包含格式 `total_size = len(seg0_payload)`。`FasWriter.write(..., compact=True)` 走前者（CLI/链接器/紧凑汇编）
- **汇编器（`asm/assembler.py`）同时支持两种布局**：`.lasm` 头部 `.format compact|selfcontained` + `.nsyms N` 指令；紧凑 stub 用 CAD 编码（USUBR/FUNC 3 字节、`PUSH_VALUE[0]` 单字节、CLEAR_ARGS `19 <argc> 00`）。`disasm → asm` 往返 seg0 逐字节一致，紧凑产物可在 CAD 加载执行。重复符号槽在 `.lasm` 中输出 `[idx]` 保证字节可逆
- 紧凑 stub 生成规则（与 CAD 逐字节一致）：中间 setq 无 POP、尾 setq 先 DUP、无 else 的 `if` 补 PUSH_NIL、有参函数末尾 `19 <argc> 00`（CLEAR_ARGS）；含 foreach/repeat 的函数 DEFUN 头 `b1=argc+1`（`14 <argc+1> <argc> <argc> 00`，t16/t17 实测）
- **`foreach` stub 协议**（t16 实测）：列表求值存局部槽 → `PUSH_G <var>; PUSH_NIL; INIT_ARGS 3`（内建遍历预载）→ loop 头 `GET_LOCAL; JMP32_IFNOT` → 体 `GET_LOCAL; CAR; SETQ_G <var>; GET_LOCAL; CDR; SET_LOCAL` 推进 → 体各式无 POP → JUMP → 尾部 `CLEAR_ARGS 1` 清理预载（非 POP）
- **`repeat` stub 协议**（t17 实测）：次数求值存局部槽 → loop 头 `GET_LOCAL; PUSH_INT8 0; FIX_LEQ; JMP32_IFNOT`（n<=0 退出）→ 体前先 `GET_LOCAL; DEC; SET_LOCAL` 递减 → 体各式无 POP → JUMP；无预载，尾部无 CLEAR_ARGS
- seg1 使用滚动 XOR 加密（`find_key`/`decrypt_stream`），尾部含密钥长度字节 + 密钥 + `;fas4 crunch` 标记
- 段分隔符为 `16 24 0d 0a`，`nsyms` 为符号槽数（资源注册顺序）
- seg1 资源流 = 模块头(`14 01 01 01 00`) + 代码引用 + 符号/字符串注册 + GVARINIT + DEFCODE + INIT_DONE + 模块代码；`seg1` 头 `items` = GVARINIT + INIT_DONE 计数
- **符号名统一大写**（`ResourceBuilder._enc_sym`）：CAD 符号槽全大写（AutoLISP 大小写不敏感）；字符串字面量不变
- **顶层表达式**（defun 之外的 setq/set 等）编译进 seg1 **模块代码**（非 seg0）：模块代码 = `DEFUN头 + [顶层表达式] + [函数注册尾: JUMP + PUSH_G <模块注册+2>; SETQ_G 1; PUSH_G 1] + END_DEFUN`；gvar 槽 = 符号槽 + 1；简单 `setq 变量 "字符串"` → `PUSH_G 值+1; DUP; SETQ_G 变量+1`；顶部占位 `PUSH_G <模块注册符号数+1>; POP`；`FasWriter` 的代码引用长度 = `total_size`（`len(seg0) + 1`）
- **模块注册段**（混合 defun+顶层）：注册函数名 + 顶层表达式符号（连续 SYMBOL 合并 5b 块，遇 STRING 分块）；`nsyms = len(entries) - 模块注册符号数 + 1`；函数注册 GVARINIT st_init = nsyms；DEFCODE 后 GVARINIT var_pos = 模块注册符号数 + 2
- **c: 命令模块代码**（`build_command_module_code`，t14_command 实测）：命令函数在模块注册段每个独立 `5b` 块，首命令后插入 `56 vl-ACAD-defun 00 00`（`0x56` 编码、保留大小写 `Vl-ACAD-defun`）；模块注册 GVARINIT st_init +1、函数注册基址 gv_var_pos +1。`vl-ACAD-defun` **不进** `symtab.entries`（否则 seg0 引用的 function_gvars 槽位 +1）；`commands` 计数 = 1（vl 符号数）。模块代码每命令 `PUSH_G <c>; FUNC_REF 2; PUSH_NIL; POP`（`35 01 02 00 01`）注册；槽位 `var_pos=n_funcs+3`、`a=var_pos-1-i`、`b=var_pos+n_funcs-1-i`、`c=n_funcs+1-i`（末 `c=1`）
- **`/ 局部变量` `_al-bind-alist` 协议**（t11_localvars 实测）：含 `/ 局部变量` 的函数，CAD 用 `(_al-bind-alist '(loc1 ...))` 绑定而非 GET_LOCAL。符号收集在函数体符号后、参数前注入 `_al-bind-alist` + `(quote (locals...))` 常量（nsyms 6→8）；codegen 在 INIT_ARGS 后发 `PUSH_G <const>; FUNC 1, <_al-bind-alist>; NIL; PUSH_NIL; NIL; POP`；CLEAR_ARGS = argc + len(locals)；while 体中间 setq 无 POP。`_al-bind-alist` 以 `0x56` 保留大小写独立注册（不进 5b 合并块）
- **符号槽顺序** = 按源码函数逆序，每函数内"字节码引用序"逆序收集函数体符号、参数紧跟其后；混合（defun+顶层）时顶层表达式符号排在函数体内建之前；递归函数名重复槽（`compiler/cad_symbols.py`）
- 多函数函数间分隔符 `16`（END_DEFUN；CLEAR_ARGS `19 <argc> 00` 已由 codegen 生成）；多函数代码引用末函数 end = total_size
- 反编译回归参考：AutoCAD 产物 `tests/fun-cad.fas`（对应 `tests/fun.lsp`）

反编译器同时支持两种布局：
- **自包含格式**（`tests/cad/i18n-cad.fas`、`tests/cad/i18n.fas`）：seg0 含完整函数体 + END_DEFUN，函数目录来自 mvar 表重建
- **紧凑 stub 格式**（AutoCAD 编译器输出，`tests/fun-cad.fas`）：seg0 无 END_DEFUN，符号按资源注册顺序（`symbol_slots`）直接编址

生成器会发出包装辅助函数以避免内建冲突：
- `fas-polar1`、`fas-rtos1`、`fas-rtos3`、`fas-getvar2`、`fas-getvar3`
- 用于列表/关联列表/DXF 组码读取的 `IN_PARAM` 查找
- 缺少 `Projet/PA_Projet` 框架时的后备选择提示

解码器问题在 `decompiler/fas4_decompiler.py` 中修复，永远不要修改生成的 `.lsp`。

## 测试中的关键陷阱

- **CLI 与裸管线的顶层表达式差异**：`compiler.cli.cmd_compile`（CLI）把顶层表达式（defun 之外的 `setq`/`princ` 等）编译进 seg1 **模块代码**（CAD 标准），而 `tests/test_compile_decompile.py` 内的裸内存管线（`SymbolTable→Codegen→ResourceBuilder→FasWriter`）把它们留在 seg0 字节码。两者反编译结果不同——CLI 管线的顶层 `(princ "Loading...")` 反编译为 `nil`。写往返测试时二选一保持一致，**不要**把两个管线的 `compile_and_decompile` 混用。
- **黄金比对（golden）fixture 必须是 CAD 重新编译的产物**：`D:/atlisp-test/cad_t*.fas`（7月31）版本戳是 `;A7/31/26`，当前编译器输出 `;A8/4/26`，整文件比对必然失败（即使 seg0 字节一致）。`tests/cad/` 内 `*_cad.fas`（8月3-4 重新在 CAD 编译）可用作 byte-identity golden。
- **t-series golden 覆盖现状**：源文件与 golden 均自包含于 `tests/cad/`（`t0X_xxx.lsp` + `t0X_xxx_cad.fas`，2026-08-04/05 CAD `vlisp-compile` 生成，共 18 份）。**18/18 已 byte-identity**（`test_t_series_byte_identity`；t16_foreach/t17_repeat 于 2026-08-06 转正——codegen 实现 CAD stub 的 foreach/repeat 协议；CAD 真机功能验证见 `scripts/cad_verify.py`）。**另含 `t22_activex_cad.fas`**（2026-08-08 CAD 生成，vla-/vlax- ActiveX，锁入同一回归）。

## 文档

- `README.md` — 使用者文档（安装、CLI 用法、工作流、工具参考）
- `docs/lasm.md` — LASM 汇编语言参考（disasm/asm）
- `docs/development.md` — 架构详解、代码规范、调试指南
- `docs/development-plan.md` — 开发计划、已验证兼容性矩阵

## CAD 测试

**自动化真机验证**（推荐，每用例独立 CAD 连接，避免会话失效）：
```sh
make cad-test        # 或: bash scripts/run_tests.sh --cad
# 等价直接运行: python scripts/cad_verify.py
```
`scripts/cad_verify.py` 编译 t01-t15 → 逐项在 CAD 加载 → 断言返回值，15 项全部通过
（2026-08-05：t10_init 随 byte-identity 转正，KNOW_ISSUES 标记已除；t12_quote 断言
曾误用 proper list 比对 dotted pair `'(1 . 2)`，已改为 car/cdr 校验）。

测试文件编译到 `D:/atlisp-test/`，在 CAD 中加载测试脚本：

```lisp
(load "D:/atlisp-test/test_all_final.lsp")
```

### 已验证（AutoCAD 24.1s）

- 简单函数、递归、if/while/cond、局部变量、字符串拼接 ✅
- 2-3 函数交叉引用 ✅
- 尾递归、&optional/&rest ✅
- 顶层 setq/set（defun 前后混合）✅
- `fun.lsp`/`fact.lsp` 解密后与 CAD 逐字节一致 ✅
- t-series 真机功能验证通过 t01-t15、t18（16 项，`scripts/cad_verify.py`；2026-08-06 复核）✅
- **真机验证清单扩展至 21 项**（`scripts/cad_verify.py`，2026-08-06）：新增
  t16_foreach/t17_repeat（循环 stub）、t19_variadic（`&optional`/`&rest`，
  `tests/cad/t19_variadic.lsp`）、t20_kwote（`(function (lambda ...))` 内嵌
  `-lambda-` 运行链路，`tests/cad/t20_kwote.lsp`）、i18n（混合模式加载 +
  `@::codepage2lang` 纯函数断言）——待 CAD 复核确认
- **真机验证清单扩展至 22 项**（2026-08-07）：新增 t21_variadic_extra
  （`tests/cad/t21_variadic_extra.lsp`：单函数 `&optional` 缺省、`&rest` 收集、
  optional+rest 组合、纯 `&optional`），与 t19 同属真机功能验证（无 CAD golden）。
- **真机验证清单扩展至 24 项**（2026-08-08）：新增 t22_activex（`vla-`/`vlax-`
  ActiveX 只读断言）、t23_command（`command-s` 画圆→断言→擦除），**CAD 真机
  24/24 全过**。
  - **t22 修复**（2026-08-08，真机暴露的编译 bug）：
    - vla- 符号名**保留大小写**（`vla-get-count`→符号槽 `vla-get-Count`，
      ActiveX 方法名大小写敏感；`vlax-` 保持小写）。`cad_symbols.normalize_vla_name`
      + codegen 同名 + `resource_builder._enc_sym` 对 vla-/vlax- 前缀不 `.upper()`。
    - 值位置 `T`/`t` 符号槽（`(if c T nil)` 的大写 T 此前被过滤+内联 PUSH_T，
      缺 T 槽致 nsyms 少 1、后续符号槽偏移）。`add()` 对 t/T 大小写不敏感注册，
      codegen stub 下 `T` 走 `PUSH_VALUE` 引用（nil 仍内联）。
    - `_patch_usubr_idx`：USUBR/FUNC 目标符号槽末尾（超出 gvar 表，fg 仅 nsyms
      项）时按 `gvar 槽 = nsyms` 编址（操作数 = nsyms-1，t22 实测
      vlax-get-acad-object 操作数 11）。
    - **byte-identity**：t22 编译产物与 CAD golden `tests/cad/t22_activex_cad.fas`
      seg0+sec2+nsyms 逐字节一致（锁入 `test_t_series_byte_identity`）。
  - **t21 修正**（2026-08-08）：`t21-product` 原为 `(&optional factor &rest rest)`
    （min=0），触发 §3.5 CAD 硬性不收集 rest 限制。改为 `(factor &rest rest)`
    （min=1），CAD 真机 `(t21-product 2 3 4)` → 24。
- i18n 混合模式拆件 p01-p07 全部 byte-identity（`tests/cad/i18n_split/`，seg0+seg1+nsyms
  对齐 CAD golden，2026-08-06）✅
  - p04-p07 关键修复：DUP 插入按真实 SETQ_G 指令定位（不碰 USUBR 的 0x06 索引字节）；
    stub 下 if-then 分支尾 setq 补 DUP 保留返回值；`_register_module` 符号归属 setq 目标优先
- **`i18n.lsp` 原文件（混合 defun+顶层+kwote）seg0+sec2 逐字节一致**（2026-08-06）✅
  （锁入 `test_i18n_original_byte_identity`：compile → Fas4Parser 比对 seg0+nsyms+seg1）
  - 关键修复：kwote 使 `fas_nsyms` 比 codegen_nsyms 大 1，seg0 引用需 `gvar 槽 - 1 - (fas_nsyms-codegen_nsyms)`；
    `-lambda-` 参数/引用槽修正（kwote 参数进 `func_args`、`-LAMBDA-` 引用槽 = nsyms-1）；
    Disassembler `03` 单字节占位前总跟 `00`（NIL）判定；连续 STRING 合并 `55` 块；
    中间 if 的 then 值 POP 位于 JUMP 前、模块代码顶层 if-then-setq 补 DUP/无 else 补 PUSH_NIL

### 已知限制

- **`if` 值/语句上下文**（2026-08-07）：`(setq r (if c e1 e2))` 的值位置 `if`
  不编译 then 分支 POP（值须流到 SETQ_G/算术/函数实参，与 CAD a4 golden 一致）；
  仅**裸语句** `if` 才在 then 末尾、JUMP 前发 `POP` 丢弃值。判别标志 `_in_stmt_ctx`
  （`_emit_stmt` 置位；`setq`/算术/实参等值位置经 `_value_ctx` 清位）。回归
  `test_value_position_if_no_then_pop`。
- 文件头注释/版本戳（`;A<日期>`）随日期变化，非字节一致性目标；seg0+sec2 已全对齐
- MCP CAD 连接不稳定，建议手动测试
