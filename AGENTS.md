# atlispcc - Agent 指南

## 项目

**atlispcc** = **A**uto**L**ISP **C**ompiler **C**ollection，FAS4 字节码编译器套件：`.lsp` ↔ `.fas`（兼容 AutoLISP 的 CAD 平台）。

`atlispcc` — 统一 CLI 工具（`compiler/cli.py`），支持十二个子命令：

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
atlispcc info <input.fas|input.zelx> [--json]              # 快速概览（头/段/函数目录）
atlispcc analyze [-f text|dot|mermaid|json] [-o OUT] [--no-cc] <lsp|fas>  # 调用图/依赖分析
atlispcc roundtrip <input.lsp> [-O {0,1,2,3}] [--keep]     # 编译往返冒烟自检
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
| `compiler/analyzer.py` | 编译分析与统计（--analyze/--report） |
| `compiler/dep_analysis.py` | 调用图/依赖分析图模型与 text/dot/mermaid 格式（analyze） |
| `compiler/roundtrip.py` | 编译往返冒烟（裸内存管线，roundtrip） |
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
python -m tools.validate tests/fun.lsp

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

**测试文件在 `tests/` 目录下**（pytest 风格，共 345 用例：343 passed + 2 skipped）：
- `test_parser.py` — AST 解析器（21 用例）
- `test_lexer.py` — 词法分析（11 用例：转义、注释、UTF-8、dotted）
- `test_symbol_table.py` — 符号表/作用域（10 用例）
- `test_analyzer.py` — 编译分析/尾递归（9 用例）
- `test_cli.py` — CLI 路径（28 用例：compile/-O/--analyze/--report/validate/link/vlx/info/analyze/dispatch + validate 补强规则 + 源码编码检测 + 顶层 progn/条件 defun/atlisp_u 综合包编译）
- `test_compile_decompile.py` — 编译-反编译往返（74 用例，含复杂 LSP O2/O3 往返、16 个 `tests/compile_src/` fixture 系列 roundtrip、i18n 混合模式、§3.5d/e 折叠回归、§10.4 golden 参数名/循环结构回归、C4 DCL 对话框）
- `test_compiler_output.py` — FAS 输出正确性（50 用例，含 4 对 CAD golden 逐字节比对 + 16 个 `tests/compile_src/` 结构断言 + i18n 拆分件 byte-identity 回归）
- `test_optimizer.py` — 优化 pass（32 用例，含循环携带变量回归）
- `test_linker.py` — 多文件链接（13 用例，含重名冲突警告 + 3 份 CAD golden byte-identity）
- `test_assembler.py` — 反汇编/汇编往返（8 用例）
- `test_disasm.py` — 反汇编健壮性（9 用例，含未处理操作码降级）
- `test_resource_stream.py` — 资源码解析/资源段构建（25 用例：符号/字符串块、GVARINIT、DEFCODE、build_mvar_tables、资源码 vs 操作码区分）
- `test_packages.py` — CL 风格包系统（4 用例）
- `test_vlx_builder.py` — VLX 容器（3 用例）
- `test_variadic_args.py` — &optional/&rest 编译（17 用例，含多函数参数名恢复）
- `test_zelx.py` — ZWCAD ZELX 构建/解析（5 用例）
- `test_diagnostics.py` — 诊断类新功能（20 用例：analyze 调用图 .lsp/.fas + dot/mermaid/text 输出 + roundtrip 往返冒烟 PASS/FAIL 与 CLI 退出码）

  一键运行全部检查：`./scripts/run_tests.sh`（py_compile + pytest + disasm→asm 往返 + byte-identity 状态）。

 手动测试文件 `tests/test_*.lsp` 也在该目录；CAD 兼容矩阵源文件 `tests/compile_src/01_math.lsp`…`16_i18n.lsp` 是编译/往返测试的 fixture（16 份，覆盖数学/字符串/递归/控制/列表/高阶/kwote/局部变量/循环/变参/命令/顶层/几何内建/ActiveX/command-s/*error*/i18n），源码与 CAD golden `.fas` 分开存放（`tests/compile_src/*.lsp` + `tests/cad/*_cad.fas`），由 `scripts/cad_verify.py` 编译加载验证。`tools/validate.py` 的 `SYMBOL_RE` 允许 `&`/`@`/`%`（`&optional`/`&rest`、`@::pkg`、`opt%` 等合法 AutoLISP 符号）。

## 兼容性

FAS4 输出格式与 AutoCAD 编译器一致：
- seg0 = 函数字节码（`<nsyms> $...`），seg1 = 资源段（常量/符号/函数索引）
- 紧凑 stub 格式 `total_size = len(seg0) + 1`（CAD 实测恒等：cross/m2/m3/multi/sh/lambda_test 六份产物；seg0 = `<nsyms> $` 后的纯字节码）；自包含格式 `total_size = len(seg0_payload)`。`FasWriter.write(..., compact=True)` 走前者（CLI/链接器/紧凑汇编）
- **汇编器（`asm/assembler.py`）同时支持两种布局**：`.lasm` 头部 `.format compact|selfcontained` + `.nsyms N` 指令；紧凑 stub 用 CAD 编码（USUBR/FUNC 3 字节、`PUSH_VALUE[0]` 单字节、CLEAR_ARGS `19 <argc> 00`）。`disasm → asm` 往返 seg0 逐字节一致，紧凑产物可在 CAD 加载执行。重复符号槽在 `.lasm` 中输出 `[idx]` 保证字节可逆
- 紧凑 stub 生成规则（与 CAD 逐字节一致）：中间 setq 无 POP、尾 setq 先 DUP、无 else 的 `if` 补 PUSH_NIL、有参函数末尾 `19 <argc> 00`（CLEAR_ARGS）；含 foreach/repeat 的函数 DEFUN 头 `b1=argc+直接体并发循环深度`（t16/t17 单层 `14 <argc+1> <argc> <argc> 00`；add-menus/remove-pkg-menu/cache-clear-all 嵌套 2 层 `14 <argc+2> ...`；嵌套 lambda/defun/quoted 内循环不计——@lisp_u 504 函数 DEFUN 头与 CAD 全对齐）
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
- 反编译回归参考：`tests/fun.lsp`（`(defun a () (alert "abc"))`）经 CLI 编译往返；原 CAD 产物 golden `tests/fun-cad.fas` 已随 t-series 源清理移除

反编译器同时支持两种布局：
- **自包含格式**（`tests/cad/i18n-cad.fas`、`tests/cad/i18n.fas`）：seg0 含完整函数体 + END_DEFUN，函数目录来自 mvar 表重建
- **紧凑 stub 格式**（AutoCAD 编译器输出，`tests/cad/*_cad.fas` t-series golden）：seg0 无 END_DEFUN，符号按资源注册顺序（`symbol_slots`）直接编址

生成器会发出包装辅助函数以避免内建冲突：
- `fas-polar1`、`fas-rtos1`、`fas-rtos3`、`fas-getvar2`、`fas-getvar3`
- 用于列表/关联列表/DXF 组码读取的 `IN_PARAM` 查找
- 缺少 `Projet/PA_Projet` 框架时的后备选择提示

解码器问题在 `decompiler/fas4_decompiler.py` 中修复，永远不要修改生成的 `.lsp`。

## 测试中的关键陷阱

- **CLI 与裸管线的顶层表达式差异**：`compiler.cli.cmd_compile`（CLI）把顶层表达式（defun 之外的 `setq`/`princ` 等）编译进 seg1 **模块代码**（CAD 标准），而 `tests/test_compile_decompile.py` 内的裸内存管线（`SymbolTable→Codegen→ResourceBuilder→FasWriter`）把它们留在 seg0 字节码。两者反编译结果不同——CLI 管线的顶层 `(princ "Loading...")` 反编译为 `nil`。写往返测试时二选一保持一致，**不要**把两个管线的 `compile_and_decompile` 混用。
- **黄金比对（golden）fixture 必须是 CAD 重新编译的产物**：`D:/atlisp-test/cad_t*.fas`（7月31）版本戳是 `;A7/31/26`，当前编译器输出 `;A8/4/26`，整文件比对必然失败（即使 seg0 字节一致）。`tests/cad/` 内 `*_cad.fas`（8月3-4 重新在 CAD 编译）可用作 byte-identity golden。
- **t-series golden 覆盖现状**：源文件已迁移至 `tests/compile_src/`（16 份，`01_math.lsp`…`16_i18n.lsp`），golden `.fas` 保留在 `tests/cad/`（`*_cad.fas`，2026-08-04/05 CAD `vlisp-compile` 生成，共 18 份）。**编译测试不再直接依赖 golden 文件**（`test_t_series_byte_identity` 改为对 6 份仍有效 golden 的逐字节比对 + 16 份 compile_src 结构断言；t16_foreach/t17_repeat 于 2026-08-06 转正——codegen 实现 CAD stub 的 foreach/repeat 协议；CAD 真机功能验证见 `scripts/cad_verify.py`）。**另含 `t22_activex_cad.fas`**（2026-08-08 CAD 生成，vla-/vlax- ActiveX，锁入同一回归）。

## 文档

- `README.md` — 使用者文档（安装、CLI 用法、工作流、工具参考）
- `docs/lasm.md` — LASM 汇编语言参考（disasm/asm）
- `docs/compilation-process.md` — 编译过程说明（.lsp → .fas 各阶段详解）
- `docs/development.md` — 架构详解、代码规范、调试指南
- `docs/development-plan.md` — 开发计划、已验证兼容性矩阵

## CAD 测试

**自动化真机验证**（推荐，每用例独立 CAD 连接，避免会话失效）：
```sh
make cad-test        # 或: bash scripts/run_tests.sh --cad
# 等价直接运行: python scripts/cad_verify.py
```
`scripts/cad_verify.py` 编译 `tests/compile_src/` 的 16 个模块 → 逐项在 CAD 加载 → 断言返回值（16 项断言，对应原 t01-t24 系列功能）
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
- `fun.lsp` 解密后与 CAD 逐字节一致 ✅
- t-series 真机功能验证通过 t01-t15、t18（16 项，`scripts/cad_verify.py`；2026-08-06 复核）✅
- **真机验证清单扩展至 21 项**（`scripts/cad_verify.py`，2026-08-06）：新增
  t16_foreach/t17_repeat（循环 stub）、t19_variadic（`&optional`/`&rest`，
  现并入 `tests/compile_src/09_variadic.lsp`）、t20_kwote（`(function (lambda ...))` 内嵌
  `-lambda-` 运行链路，现并入 `tests/compile_src/06_higher_order.lsp`）、i18n（混合模式加载 +
  `@::codepage2lang` 纯函数断言）——待 CAD 复核确认
- **真机验证清单扩展至 22 项**（2026-08-07）：新增 t21_variadic_extra
  （并入 `tests/compile_src/09_variadic.lsp`：单函数 `&optional` 缺省、`&rest` 收集、
  optional+rest 组合、纯 `&optional`），与 t19 同属真机功能验证（无 CAD golden）。
- **真机验证清单扩展至 24 项**（2026-08-08）：新增 t22_activex（`vla-`/`vlax-`
  ActiveX 只读断言）、t23_command（`command-s` 画圆→断言→擦除），**CAD 真机
  24/24 全过**。
- **真机验证清单扩展至 25 项**（2026-08-11）：新增 t24_star_error（`*error*`
  错误处理函数，直接调用编译产物模拟 CAD 错误分发，`tests/compile_src/15_error.lsp`）。
  `scripts/cad_verify.py` 覆盖 22→24→25 项（t24 真机待 CAD 复核）。
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
- **@lisp 综合包编译**（2026-08-11）：`tests/atlisp_u.lsp`（502 函数 + 221 顶层
  语句 + 80 kwote 回调）编译产物在 CAD 真机**模块代码完整执行、功能全部可用**
  （`@::safe-eval`/`define-config-typed`/`@::compat1` 等正常）。关键修复：
  - 顶层 `(progn ...)` 展开、条件/嵌套 defun → `(setq f '(lambda ...))`、
    多 kwote 改写（含 Cond 分支与嵌套递归）
  - **commands + 顶层混合** gvar 槽重映射（`compiler/_gvar_map.py` 解析 seg1
    模块注册段；`_offset_slots` 二次生成模块代码按实际槽位修正符号引用）
  - **大文件 USUBR/FUNC 宽格式**：符号槽 >255 用 5 字节 USUBR
    （`35 argc idx16 flags=3`）、6 字节 FUNC（`51 argc idx16 flags=1 00`），
    小文件保持 3 字节（golden 逐字节不变）
  - `top_level_count` 由收集器 `module_reg_count` 推导（避免顶层表达式引用
    函数体符号时的高估）
  - **@lisp_u 真机加载打通**（2026-08-14，对拍 CAD 编译 `~/@lisp/@lisp_u.lsp`，
    加载链逐层修复后**模块代码完整执行、核心函数可调用**）：
    - 模块注册**全部函数**（CAD 实测 1339 符号/544 函数，非"尾块 48"）；
      `module_func_count` 截断（7beeddf 引入）导致模块代码 USUBR 错槽
    - **模块代码槽引用 = 资源 gvar 表(rg)**：CAD 实测 `USUBR(0,1036)` →
      rg[1036]=VL-LOAD-COM，操作数 = rg 索引（`build_module_gvar_map` 的
      模块注册位 ≠ rg 槽，@lisp_u VL-LOAD-COM 注册位 1450 vs rg[1029]）
    - `in-package`/`use-package`：CAD 视为编译期指令，模块代码**不发射**
      函数调用（发射 USUBR 解析为 CL::IN-PACKAGE → 函数错误）；符号仍注册
    - **setq 值 = 函数符号 → PUSH_G**（`(setq @::unschedule-task
      @::string-to-list)` 实测）；**set 值 = 函数符号 → PUSH_VALUE**
      （`(set 'type-of cl::type-of)` 实测，PUSH_G 只压符号运行时报
      "函数错误: CL::TYPE-OF"）——setq/set 编码不同
    - 参数绑定按名解析（`symtab.function_offsets` offset→name），弃用全局
      func_iter 顺序对齐（大文件 kwote lambda 收集与 -lambda- 生成数不匹配
      致 iter 错位，@::load-locale 参数被错配为他函数参数）
    - **模块代码 REAL 常量内联 PUSH_REAL**（`(setq @::*seconds-per-day*
      86400.0)` 等）：atlispcc 实数注册在 fg 表，模块代码(rg 上下文)读不到，
      引用越界/空值错；setq 值 = REAL 时内联 `3b <_real_fmt> 00`（补 ".0"）。
      CAD 用 rg 槽引用，但内联保证值正确（@::timestamp 恢复正常）
    - **KNOWN_ISSUES**：混合文件顶层 `(setq X (lambda ...))` 的 `-lambda-`
      SUBR 未实现（复杂 lambda 体需完整参数/USUBR 槽修正）；@lisp_u 的
      @::fasext/@::vlx 绑定为引用数据 LIST（CAD 为可调用 SUBR），调用报
      "函数错误: (LAMBDA ...)"——不影响加载，纯顶层文件（bootstrap 等）正常
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

### kernel 真机编译逐文件对比（2026-08-16）

对 `../kernel/src/` 下全部 67 个 `.lsp` 逐个编译并与 CAD 真机
（`(vlisp-compile 'st ...)`，AutoCAD 24.1s）产物逐字节比对：

- **9 个 byte-identical**：platform / version / funlib-download / funlib-record /
  net-cache / net-http / net-mid / net-registry / sub-system-config-config
  （nsyms + seg0 + resource_items 全一致）
- **58 个 DIFF**：多数 nsyms ±1（符号槽序差异），少数大差异
  （setup 228→166、config-dialog 160→196、package-version 117→124 等）
- 主要差异类别：
  1. **模块区值位置 `t` 未注册 T 槽**（@lisp-env / event-bus / platform-api /
     init-sequence / net-uri）：混合文件模块注册区无 cond else 键（force t）时，
     值位置 `(setq x (if c t))` 的 `t` 也要注册 SYMBOL T（`_register_module`
     预扫描 `_has_force_t` 判定，2026-08-16 修复）
  2. **非 ASCII 字符串编码**：CAD 按系统 ACP（中文系统 GBK）写字符串，
     atlispcc 在 Cygwin/POSIX Python 下此前用 UTF-8（`get_ansi_encoding`
     现回退 `reg query` 注册表取 ACP，2026-08-16 修复）
  3. **命令模块缺 `vl-ACAD-defun` 注册**（voice / config-dialog /
     config-sync-config / package-version 等）
  4. **符号槽序 / nsyms ±1**：大量文件，待逐个对拍修复
  5. **共享参数在函数体引用泄漏**（cl-macros，2026-08-16 修复）：
     `_collect_forward`（模块代码）本就排除 `self.shared` 共享参数，但
     `_collect_byteorder`（函数体引用）未排除——`body` 被 set-macro/defmacro
     共享为参数，却泄漏进 expand-let 的函数体引用（slot 43 多余 `BODY`），
     使 set-macro 的共享参数注册（slot 67 应为 `BODY`）变成空操作（已在
     `_name_set`）。修复：在 `_collect_byteorder` 的 Symbol 值引用、Setq 目标、
     quoted 单符号三处 + locals 循环加 `name not in self.shared` 守卫。
     **cl-macros 现 symbol_slots 79/79 + nsyms 55/55 与 CAD 一致**（仅 seg0
     仍有独立 codegen 差异：`@::macro-subst` while 回跳 JUMP 前多余 `PUSH_NIL`、
     while 体尾 setq 多余 `DUP`，待 codegen 修复）。回归：全量
     test_compiler_output/test_compile_decompile/test_symbol_table 134 passed。
- 工作流：`python scripts/mcp_cad.py eval "(vlisp-compile 'st <in> <out>)"`
  （模式 `'st`，CAD 文档打开时才可编译；路径用正斜杠）

### 已知限制

- **cond else 键 `t` 的 T 槽位置**（2026-08-15）：CAD 中 T 槽由**外层 cond 的
  else 键**（forward 序第一个 force t，纯顶层 reversed 注册序最后一个）位置
  决定（test-cond 实测 `"chs" ... T "autocad"`——T 在结果体后、测试符号前），
  内层 else 键 t 与值位置 `T` 复用该槽。`_collect_single` 纯顶层路径仅保留
  reversed 序最后一个 force t 注册，其余 t/T 跳过；`add()` 对 t/T 统一为 `T`
  槽（纯顶层 force 也不重复）。**混合文件例外**（2026-08-16）：模块注册区
  （顶层 cond else 键）与函数体区（函数 cond else 键）各注册一次 T 槽，见
  下方"T 槽双注册"。回归 `test_byte_identity_with_cad_golden
  [test-cond.lsp]`。
- **cond 子句体 / 语句上下文的 if**（2026-08-15）：`_emit_stmt` 清 `_module_mode`，
  使 cond 子句体内的 if 不按模块代码顶层 if 编译——then 分支 setq 不 DUP、
  无 else 不补 PUSH_NIL（test-cond CAD 实测 `PUSH_G; SETQ_G` 无 `0b`/`01`）。
  模块代码独立顶层 if 仍经 `_emit_expr` 保留 `_module_mode`（then DUP、无 else
  补 NIL，p05/i18n 实测）。多对 setq 最后对总是 DUP（p05 实测，与 tail 无关）。
- **`if` 值/语句上下文**（2026-08-07）：`(setq r (if c e1 e2))` 的值位置 `if`
  不编译 then 分支 POP（值须流到 SETQ_G/算术/函数实参，与 CAD a4 golden 一致）；
  仅**裸语句** `if` 才在 then 末尾、JUMP 前发 `POP` 丢弃值。判别标志 `_in_stmt_ctx`
  （`_emit_stmt` 置位；`setq`/算术/实参等值位置经 `_value_ctx` 清位）。回归
  `test_value_position_if_no_then_pop`。
- **`if` then 分支为 while/foreach/repeat 时无 POP**（2026-08-15）：then 为循环
  节点（自带栈平衡：JUMP 回跳 + CLEAR_ARGS/尾协议）时，`_emit_if` 的语句上下文
  POP 排除列表须含 WhileNode/ForeachNode/RepeatNode，否则循环退出前多 POP
  （platform-api `@::platform-path` 双 while 分支 CAD 实测 `57 JUMP` 直接退出）。
- **`cond` 分支中间 while/repeat 无 POP**（2026-08-15）：`_emit_cond_stub` 的
  分支 actions 中间语句 POP 排除列表同样须含 WhileNode/RepeatNode（自带栈平衡，
  platform-api `@::platform-http-head` `(while ...)` 后接 `(if ...)` CAD 实测
  无额外 `0a` POP）。
- **`command` 每参数独立 `FUNC 1` 调用**（2026-08-15）：CAD 把 `(command a b ...)`
  编译为每个参数一次 `FUNC 1 <ads-cmd>`（`PUSH_G <arg>; FUNC 1; NIL PUSH_NIL
  NIL; POP` 间隔），非单次 `FUNC <argc>`——后者 CAD 加载报"参数太多"
  （platform-api `(command "shell" (strcat ...))` 实测）。`command` 内建在
  资源段注册名为 `ads-cmd`。
- **`if` 条件为值位置 setq 需 DUP**（2026-08-15）：`_emit_if` 的条件用
  `_tail=True` 求值，使条件内值位置 `(setq ...)` 发 `DUP; SETQ_G` 保留返回值
  （platform-api `(if (not (vl-catch-all-error-p (setq status ...))) ...)`
  CAD 实测 `0b 06`）。与 while 条件同规则。
- **0 参 `-lambda-` 无 CLEAR_ARGS 0**（2026-08-15）：`_emit_nested_lambda` 在
  argc=0 且无 `/ locals` 时直接 END_DEFUN（`16`），不发 `19 00 00`（与顶层
  0 参 defun 同规则；platform-api 内嵌 0 参 kwote lambda CAD 实测）。
- **`_patch_usubr_idx` 仅混合/多函数文件启用**（2026-08-15）：纯单函数文件
  （无顶层表达式且 ≤1 真实 defun）直接返回原 seg0——codegen 槽已与资源
  symbol_slots 一致，重映射会把多 kwote 的 PUSH_G 字符串按 `nsyms-1` 回退
  改错槽（`-lambda-` 类型错误）。表外字符串操作数 = 资源 symbol_slots 真实索引
  （含 REAL 项，漏 REAL 会使索引偏 1）。回归：2-kwote 最小复现 `(test-a)` → T。
- **`__kwote_end__` 标记不注册**（2026-08-15）：`_collect_single` 收集 refs 中的
  `__kwote_end__` 分隔标记须过滤，否则泄漏为符号槽（多 kwote 文件 nsyms 多 1、
  后续槽偏移，CAD 加载报 `-lambda-` 类型错误）。
- **纯顶层 `(set/setq 'sym (lambda ...))` 多 `-lambda-`**（2026-08-15，byte-identity，
  回归 `test_byte_identity_with_cad_golden[setq-lambda.lsp]`，CAD 真机验证
  `(@::fasext "abc")`→`"abc.fas"`、`(@::vlx "a.vlx")`→`"a.vls"`）：
  - **seg0**：`-lambda-` 是完整 compact stub（`14 <argc>x3 00` + GET_LOCAL + INIT_ARGS +
    体 + CLEAR_ARGS + END_DEFUN，函数间 `16` 分隔、最后无 END），复用
    `generate_function`（`_defun_from_lambda` 转 Defun）。**CAD 的 USUBR 用 5 字节宽格式**
    （`35 <argc> <idx16> 03`，flags=3，非小文件 3 字节）。
  - **nsyms** = fg 表长度 = `1 + len(top_lambda_body_syms)`（setq-lambda golden 12 =
    1 + 11 第二区符号），非 `1 + len(top_lambda_binds)`。
  - **符号表布局**：第一区（模块注册段，仅顶层表达式符号）→ GVARINIT(0, 第一区数+2)
    → 函数目录（`_func_ranges_bytes`：每个 `-lambda-` 的 (offset . end)）→ 第二区
    （lambda 体符号 + 参数 + 最后调用名，跨 lambda 去重 strcat）→ `GET_LOCAL;
    GVARINIT(0, 第二区数+1)`（module_id=最后符号 FILE → build_mvar_tables 判 table1
    = fg 表）→ 多 DEFCODE（offset 大的先）→ `GVARINIT(第一区数+2, 函数数)`（`-lambda-`
    超表运行时槽）。
  - **fg 表**（`_patch_usubr_idx` 映射依据）= 代码引用（fg[1]）+ 第二区符号（fg[2-11]），
    FILE 作 module_id 不占槽。`gvar_slot` 未命中返回 nsyms（参数 file→11）。
  - **模块代码绑定**用 setq 协议 `JUMP 0; PUSH_G <lam槽+1>; DUP; SETQ_G <sym>`；
    `-lambda-` 槽不在 symtab/gvar_map，PUSH_G 直接用 `_lam_slot + 1`（不能用 `_slot_gv`，
    会把槽当 symtab 索引查 entries 错位到 gvar_map）。
  - **`_patch_usubr_idx`**：`top_lambda_args` 按 seg0 出现序传参；参数绑定 PUSH_G 与
    参数读取 PUSH_VALUE 用 `gvar_slot(arg) - 1`（str-vlx fg[9]→8）；参数读取槽识别
    `nsyms - len(cur_args) <= idx < nsyms`。
  - `_collect_single` 的 `_has_top_lam` 分支走 `_register_module`（第一区）+ 3b 块
    （第二区）；普通纯顶层仍全局逆序（test-cond/setcmp/set5/setqa 不变）。
  - `_owner_of` 用 min(form 序)（command-s 在 form2 首次读取、form4 才 setq，槽排
    VL-CMDF 后）。
  - seg1 尾部 8 字节（密钥边界截取乱码）非 byte-identity 目标；`resource_items`
    已全对齐。
- **混合文件（defun+顶层）顶层 `(set/setq 'sym (lambda ...))` 的 `-lambda-` 命名**
  （2026-08-16，platform.lsp 对拍 CAD，seg0 字节码完全一致）：混合文件顶层
  setq-lambda 不再提升为同名 defun（旧 workaround），func_offsets 键改用
  `-lambda-`/`-lambda-#N`，使 resource_builder 的 DEFCODE 尾注册为 `-lambda-`
  （CAD platform.lsp 实测两处 `-lambda-`，offset 大的先 DEFCODE）。相关：
  - `_top_lambda_names` 在转换前捕获顶层 lambda 目标符号名；func_offsets 循环
    对它们用 `-lambda-` 键登记，`_top_lambda_offsets[offset] = 原名` 供
    `_patch_usubr_idx` 按 seg0 offset 解析参数（`params_by_name` 也按
    `-lambda-` 键注入原名参数，`gvar_slot(arg)-1` 修正绑定槽）。
  - `-lambda-` 键**不进** `symtab.function_offsets`/entries（`add_func_ref` 会
    `get_or_add` 建符号槽，纯顶层 setq-lambda byte-identity 会破）。
  - 纯顶层与混合文件统一走 `_rewrite_top_lambda_binds`（kwote 标记）入口；
    `_convert_top_lambda_to_defuns` 保留为混合文件 seg0 stub 生成用（提升为
    defun 后其 stub 字节与 CAD `-lambda-` stub 一致）。
- **跨区字符串重复注册**（2026-08-16，platform.lsp）：字符串同时出现在模块区
  （顶层表达式）与函数体区时，CAD 在两区各注册一个独立 gvar 槽（platform
  `(setq @::*locale* "chs")` 的 `"chs"`：模块区 + `fg[20]`）。symtab 构建
  （cli.py）对重复字符串 `add_string(force=True)` 追加重复 STRING 槽（不覆盖
  `name_to_idx`）。
- **`add_string` 数字字符串**（2026-08-16）：移除 `isdigit()` 特判——`(= choice
  "1")` 的 `"1"` 是 STRING 槽（CAD 实测 `(setq x "1")` → STRING），此前误注册
  为 SYMBOL 致 voice 等文件符号表错位。
- **T 槽双注册**（2026-08-16，platform.lsp）：混合文件模块注册区（顶层 cond
  else 键 `(t ...)`）与函数体区（函数 cond else 键）各注册一次 `T` 槽——CAD
  platform.lsp 实测模块 [27] + 函数体 [43]，后者喂 fg 表 `fg[5]=T`。
  `_register_module` 保留 reversed 序最后一个 force t 注册（其余 t/T 跳过）；
  多函数路径按 `t_last` 在 `_name_set` 已含 T 时直接 `names.append("T")`。
- **模块注册区连续 STRING 合并**（2026-08-16，platform.lsp）：resource_builder
  模块注册（module_entries 循环）连续 STRING 合并为单个 55 块（CAD
  `55 02 00 acad.pgp chs` 实测），此前每个字符串独立 `55 01` 块。
- **platform.lsp byte-identity**（2026-08-16，**seg0+nsyms+seg1 完全一致**）：
  混合文件（defun+顶层 setq-lambda）对拍 CAD 真机编译，全文件 byte-identical
  （仅头部横幅 `Do not change it!` vs `Built by atlispcc!` 差异）。相关修复：
  - `_module_code_ctx` 标志——模块代码（顶层表达式）里的跨函数调用用模块注册
    槽、不分配重复符号槽（否则顶层 cond 调 `@::set-locale` 在 fg 区泄漏
    `@::SET-LOCALE` 重复槽、VAL 与函数名合并进同一 5b 块、nsyms 多 1）。
  - `_build_cad_module_code` 的 `_reg` 分组：START 注册前 n_pre 个函数（首个
    顶层语句之前定义，platform 实测 set-locale/get-locale），TAIL 注册其余
    （跳过顶层 setq-lambda，其绑定由 mid_forms setq 语句发射）。
  - 混合文件顶层 set/setq-lambda：保留原 form（kwote 改写）到 other_forms +
    其后插入提升 defun（`_insert_top_lambda_defuns`，seg0 `-lambda-` stub 源码
    位置交错）。
  - `top_lambda_slots`（混合）= `_reg` b 槽 - 1 = 2*n_funcs+top_level_count-i。
  - **cond 子句末动作尾上下文**（`_emit_cond_stub` `_tail=True`）：末动作是子句
    的"值"，setq 需 DUP 保留返回值（platform `(setq is-gcad T)` 实测
    `PUSH_G T; DUP; SETQ_G`）。
  - **`_stmt_bytes` setq DUP 仅单对**：多对 setq 末对 DUP 已由 codegen 生成
    （n>1 末对），`_stmt_bytes` 再插 DUP 会双发（platform 多对 setq 实测）。
  - **`count_resource_items`**：CAD seg1 头 `<items>` = 模块注册 GVARINIT
    st_init + 函数注册 GVARINIT st_init（platform 66+6=72、mid 3+1=4），
    中间函数体 fg GVARINIT(0,nsyms) 不计数。
- 文件头注释/版本戳（`;A<日期>`）随日期变化，非字节一致性目标；seg0+sec2 已全对齐
- **CAD 模态对话框阻塞 MCP**：CAD 偶发弹出 `alert`/错误框（`#32770`）会阻塞
  `atlisp-mcp` eval。用 `python -m tools.cad_dialog_killer <pid> --watch` 自动关闭
  （C# 实现，`tools/src/cad_dialog_killer.cs`，实测关闭 alert 解除阻塞）。
- **多 kwote + 捕获外层参数的 `-lambda-` 参数槽缺失**（sub-system/scheduler，
  2026-08-16 登记）：`unschedule-task` 的 `(function (lambda (task-item)
  (= (car task-item) name)))` 捕获外层函数参数 `name` 时，CAD 会把 kwote
  lambda 参数 `task-item` 注册为符号槽（scheduler golden slot 77 `TASK-ITEM`，
  kwote 块 `kwote = CAR TASK-ITEM`），而 `_collect_byteorder` 的 kwote 分支
  用 `arg_names | lambda_args` 排除 lambda 参数 → OURS nsyms 少 1（72 vs 73）、
  后续槽偏移、`-lambda-` 运行时绑定报 `要绑定的对象不正确: #<SUBR -lambda->`。
  i18n/06_higher_order 单 kwote（lambda 不捕获外层参数，`(lambda (n) (* n 2))`）
  用 GET_LOCAL 读取参数、不注册参数槽，byte-identity 正常。区别待确认（可能
  是"kwote lambda 是否引用外层函数符号"触发 CAD 符号槽注册）。当前编译产物
  **加载正常**（`(load ...)` OK），仅运行时功能受影响；scheduler 已记录于
  kernel-fas-load 3 FAIL 修复清单（init/sequence、net/checksum、scheduler
  重新编译后加载全部 OK）。待修复：kwote lambda 捕获外层参数时参数槽注册 +
  codegen `-lambda-` 参数读取方式。
- **cond 空体子句不发入口 POP**（init/sequence，2026-08-16）：`(cond (x) ...)`
  空体子句（无动作）CAD 不发 `POP` 弹测试值（测试值留栈顶作 cond 结果，
  init/sequence 的 `(@::*bootstrap-state*)` 实测无 `0a`）。`_emit_cond_stub`
  对空体分支跳过 `POP`。语句上下文多对 setq 不 DUP（cond 子句体 if-then 中间
  多对 setq CAD `SETQ_G` 无 `0b`，见 codegen `_emit_setq`）。init/sequence.fas
  重新编译后 CAD 加载 + 函数可解析 OK。
- MCP CAD 连接不稳定，建议手动测试
