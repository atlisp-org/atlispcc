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

**测试文件在 `tests/` 目录下**（pytest 风格，共 356 用例：354 passed + 2 skipped）：
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
- **c: 命令 + 顶层混合模式**（`_build_cad_module_code` + `n_cmds`，large_synthetic CAD 实测 byte-identity）：命令与顶层表达式并存时，`56 vl-ACAD-defun 00 00` 块插在**源码序第一个命令之前**（模块注册共享 5b 块被 vl 块分割，如 `5b [LGF-TOP-* CMD-090 CMD-060 CMD-030] 00 56 vl-ACAD-defun 00 00 5b [CMD-000 LGF-119...]`）；命令**不**独立成块（t14 纯命令才每命令独立块）。模块注册 GVARINIT st_init = `module_entries_count + 2 + commands`。`_build_cad_module_code` 需 `n_cmds` 参数：vl 符号使 `module_reg_count = n_funcs + top_level_count + n_cmds`（占位 `PUSH_G module_reg_count+1`、b 槽 `2*n_funcs+1+top_level_count+n_cmds-i` 全局 +1）；c 槽在符号槽 ≥ 源码首个命令槽时再 +1（vl 符号占用其后一个槽）。命令注册用 CAD 24 字节模式 `JUMP 0; PUSH_G b; SETQ_G c; PUSH_G c; USUBR(1,<vl槽>); POP; PUSH_G c; POP`（vl 槽 = 源码首个命令符号槽 + 1），非命令仍 15 字节 `JUMP 0; PUSH_G b; SETQ_G c; PUSH_G c; POP`。`cli.py` 的 `_rb_commands` 对混合模式也传 `n_cmds`（不再仅纯命令）
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
    - **byte-identity 现状**（2026-08-19 对拍）：@lisp_u 与 CAD 真机产物
      `~/@lisp/@lisp_u_cad.fas` **非 byte-identical**（nsyms 2670 vs 2610、
      seg0 89437 vs 85008、res 105640 vs 113819），差异为历史遗留（改动前
      即存在）。来源：混合文件（defun+顶层+大量 kwote）的复杂场景——嵌套
      defun（CAD 原生内嵌 DEFUN，我们 `_lower_nested_defuns` 降级 setq-lambda）、
      引用数据内 lambda（`'(lambda ...)` CAD 提取内嵌函数 + EVAL 组装）、
      `-lambda-` SUBR 未实现（KNOWN_ISSUES）。**功能验证通过**（模块代码
      完整执行、核心函数可调用），byte-identity 未达成。含变参函数的文件
      同理无法整文件 byte-identity（CAD 不支持变参）。
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

- **`_al-bind-alist` 常量 PUSH_G 不再减 offset**（2026-08-23，package/lock
  byte-identical，33/67）：`(quote (loc1 ...))` locals 常量的 gvar 槽 =
  `_al-bind-alist` 槽（资源注册序，**不随 `-lambda-` 偏移**）。旧公式
  `new_idx = _al_slot - offset` 在 kwote 文件（offset=1，lock.lsp）会错成
  `_al_slot-1`（100，CAD 用 101）。t11/net-proxy offset=0 不受影响。
- **2026-08-23 更新**：**byte-identity 42/67**。新增 init/steps、config/migrate、
  config-sync-config、scheduler、ui/hotkey、package/lock、net/ax-request、
  net/probe、**command、log、voice、lifecycle、reactor、ui、i18n、
  help-system、cl-functions** 十九个 byte-identical。其中 net/ax-request/
  net/probe 是**旧 golden stale**（重新在 CAD 24.1s 编译后 nsyms 与 ours 一致），
  已用 `vlisp-compile` 重新生成 golden。剩余 25 DIFF：多数为符号槽序（ORDER，
  `_res_offset` 逐区不一致——base-function 各区偏移 68/70/72/85/92 不等）+
  `list` 内建符号收集位置（lifecycle LIST fg[12] vs CAD[38]）+ `(let ...)` EVAL
  模式 + 顶层/模块代码分组（ui.lsp 的 vlax-for、i18n seg1）。
- **2026-08-23（CAD 对拍）cl-functions.lsp byte-identical（42/67）**：两个通用
  修复，cl-functions **seg0+seg1+nsyms 完全一致**（`#-sbcl + progn` 展开模式，
  mid 别名 set 与注册交错 + gvar_map 重复符号首槽）：
  1. **mid 别名 set 与注册交错**（`cli.py` `_build_cad_module_code`）：mid 语句
     均为 `(set 'cl::xxx cl::xxx)`（Progn[1]set，或 Progn[N] 首 form 为 set，
     cl-functions 的 `#-sbcl + progn` 展开）时，CAD 把每条 mid 语句与对应函数
     注册**交错** `[reg i, mid[i]]`（START/TAIL 同样）。函数无 mid（@::eval/
     @::require，mids=-）跳过不消耗 mid_forms。`mid_counts`（cli.py 调用方计算，
     每个 defun 之后的非 defun/defpackage/in-package form 数，仅统计最后一个
     defun 之前）逐函数分配；普通 mid（i18n/platform setq/if）仍全部 mid 先、
     注册后。cl-functions 前导 `(in-package :@)`/`(use-package :autolisp)` 使
     n_globals=2、cl::stringp 为首个 defun 之后连续（n_pre=1 START 注册）。
  2. **gvar_map 重复符号取 symtab-consistent 槽**（`cli.py` gvar_map 构建）：
     模块代码二次生成时 gvar_map 对重复符号（`=` rg 三槽 @[50,51,52]）取
     **首槽** 50，`_offset_slots` 会把 pass1（symtab_idx+1=52，与 CAD 逐字节
     一致）的 PUSH_VALUE 重映射成 PV50 → 破坏。修复：先按 symtab 序自然映射
     （rg[symtab_idx+1+n_cmds] 持有该符号时 gvar_map[sym]=自然槽），再扫描 rg
     表补充顺序不一致（atlisp_u 函数名逆序）的符号。cl-functions `=` symtab
     idx 51 → 自然槽 52 ✓；`:use`/`:export` 不在 rg（CAD 不注册，module 代码
     SETQ_G 用 symtab_idx+1 fallback=51/50）不受影响。回归：@lisp-env/i18n/
     platform/cl-macros 保持 byte-identical，372 tests pass。
- **2026-08-23（CAD 对拍）command.lsp byte-identical（34/67）**：`_res_offset`
  编址的表外符号（不在 fg 表）**不再减 `-offset`**（`cli.py` `_patch_usubr_idx`
  SYMBOL 分支 `_fg_ext = _rs - _res_offset; new_idx = _fg_ext - 1`）。原因：
  command.lsp 的 `(boundp '@::internetp)`（line 46）把表外函数符号 `@::internetp`
  （res[191]）作值推送，offset=1（单 kwote `-lambda-` 偏移）被双重扣除——
  `_res_offset`（= 末 fg 符号 @::BROWSER res[190]-fg[149]=41）已含资源→fg 关系，
  再 `-offset` 把 gvar 槽压到 149（CAD 用 150）。此改动只影响 offset=1 且走
  `_res_offset` 路径的表外符号；fg 表内符号（gvar_map/str_map 命中）不受影响。
  回归：34/67 无既有文件回退（net/proxy/scheduler 等 kwote 文件保持 byte-identical）。
- **2026-08-23（CAD 对拍）help-system.lsp byte-identical（41/67）**：`_seen` +
  `_in_name_set` 字符串大小写敏感（`cad_symbols.py`），help-system **seg0+seg1+
  nsyms 完全一致**（`"cmdecho"`/`"CMDECHO"` 是两个独立槽）：`(setvar "CMDECHO" 0)`
  与 `(setvar "cmdecho" 1)` 在同一函数（@::browser/@::browser-pkg）。旧 `_seen`/
  `_in_name_set` 对字符串也走大小写不敏感路径（`"cmdecho"`.upper()=="CMDECHO"）→
  两个字符串合并一个 → "CMDECHO" 槽缺失、后续槽错位（@::OPEN-URL 提前）。
  修复：`_seen`/`_in_name_set` 对以 `"` 开头的字符串键用精确匹配（大小写敏感），
  仅普通符号走大小写不敏感。回归：voice/log/i18n/cl-macros 保持 byte-identical
  （符号合并不受影响）。
- **2026-08-23（CAD 对拍）net/module.lsp byte-identical（43/67）**：四个通用修复
  （`_res_offset` const 折叠补偿 + `_local_is_param_order` order="local" 共享
  符号 + `_patch_usubr_idx` cur_args 栈 + `_emit_nested_lambda` if 排除），
  net/module **seg0+seg1+nsyms 完全一致**（`/ 局部变量` + 共享参数 + 双 kwote
  lambda + `_al-bind-alist` 复杂组合）：
  1. **`_res_offset` const 折叠补偿**（`cli.py` `_res_to_fg`）：const（quoted
     数据）折叠多个 res 槽为一个 fg 槽（net/module `(quote (entry now))` 占
     res[110,111]、fg[98] 一槽），使 `_res_offset`（= 末 fg 符号差，12）在
     const 之后失效（MOD-SYM res[112]-12=100，CAD 用 fg[99]=112-13）。记录
     fg 表每个 const 的（res 位置, 叶子数），目标符号 res 槽在 const 之后时
     偏移 +（叶子数-1）。`gvar_slot_res`/表外符号/字符串 fallback 共用。
  2. **`_local_is_param_order` 的 order="local" 共享符号**（`cad_symbols.py`）：
     net/module `response-str`/`http-response` = cache-module-response/eval-module
     参数（shared）+ load-module/fetch-module 局部（order="local"，局部拥有者
     后处理）。三处协调：args 循环 order="local" 参数跳过（shared 检查之前）；
     函数体组仅 `i == _local_is_param_last` 的最后局部拥有者注册；locals 循环
     对 order="local" 局部即使 shared/kept 过滤也注册。`_collect_byteorder`
     Symbol/Setq target 对 shared 符号若在 cur_locals（当前函数局部）仍收集
     （局部拥有者函数体须在 body 位置注册，否则仅 locals 循环尾部错位）。
  3. **`_patch_usubr_idx` cur_args 栈**（`cli.py`）：kwote lambda 的 `-lambda-`
     DEFUN 不注册 name_by_offset，进入时把宿主函数 (cur_args, arg_i) 压栈，
     END_DEFUN 弹出恢复——否则 lambda 结束后宿主函数体的参数读取
     （`(vl-remove mod-sym ...)` 的 mod-sym PUSH_VALUE）仍用 lambda 的
     cur_args（net/module @::handle-module-failure 内嵌 0 参 lambda 后 mod-sym
     读取误走通用符号映射 → 99 错槽，CAD 用 98）。
  4. **`_emit_nested_lambda` 中间语句 POP 排除**（`codegen.py` line 1424）：
     kwote lambda 体非末语句的 if/cond 不追加 POP（if 语句上下文自平衡，
     与 generate_function line 1616 同规则；net/module cache-module-response
     的 kwote lambda `(if fp ...)` 后多 `0a` → seg0 +1）。
- **2026-08-23（CAD 对拍）config/store.lsp byte-identical（44/67）**：两个通用
  修复（`_all_params` 排除 + 非尾 foreach 体每句 POP），config/store
  **seg0+seg1+nsyms 完全一致**（base-function seg0 同步转正、TYPE fg[78] 对齐）：
  1. **`_all_params` 函数体收集排除**（`cad_symbols.py`）：全部函数参数名（含
     唯一参数）在 `_collect_byteorder` 的 Symbol/Call name/Setq target 三处
     排除——某函数参数名被**其它函数**作内建/全局引用（config/store `type` =
     define-config-typed 参数 + config-validate `(type value)` 调用）时，CAD
     注册在**参数拥有者**组（TYPE fg[78]），非引用函数组（fg[59]，旧实现
     config-validate 抢先注册）。当前函数局部（cur_locals，net/module
     `response-str` 局部拥有者）放行。
  2. **非尾 foreach 体每句 POP**（`codegen.py` `_emit_foreach_stub`）：非尾
     foreach（`_in_tail_context=False`）体多语句的值被丢弃（@::list-config
     `(princ ...)` 每句 CAD 实测 `USUBR; POP`），旧实现仅最后语句 POP、中间
     语句留值（seg0 -9）。setq/if/循环自平衡无 POP；尾 foreach 仍无 POP
     （t16 "体各式无 POP"——体值累积为 foreach 结果）。
- **2026-08-23（CAD 对拍）base-function.lsp byte-identical（45/67）**：一个通用
  修复（`_interleave_mid` 多数 set 判定），base-function **seg0+seg1+nsyms
  完全一致**（handle-keywords/leap-yearp/confirm/sleep 别名 set 与注册交错）：
  `_interleave_mid` 由 `all(_mid_lead_alias)` 放宽为 `sum(_mid_is_set)*2 >
  len(mid_forms)`（mid 语句**多数**为 `(set ...)` 调用时交错）。base-function
  的 mid[0] `(set '$platform (read (getvar "platform")))`（值非符号）与 mid[5]
  `(setq @::*mktime-epoch* 2208988800)` 非干净别名 set 但也交错（CAD 实测
  `[reg @::acadver, mid0, reg @::handle-keywords, mid1, ...]`）。i18n/platform
  的 setq/if 占多数（1/5 set）不交错。回归：i18n/platform/cl-functions/
  net/module/config/store 保持 byte-identical，372 tests pass。
- **2026-08-23（CAD 对拍）platform-api fg 对齐（未全转正）**：唯一参数名被
  **其它函数 quoted 引用**时排除（`cad_symbols.py` quoted 单符号分支）——
  platform-api `'str`（@::platform-http `(eq 'str (type url))`）= @::platform-path
  **唯一**参数，CAD 单槽 fg[120]（参数拥有者）；OURS 旧实现 quoted 分支收集 →
  提前到 fg[43]（http 组），使 NAME/KEY/VALUE 等参数槽整体 +1 错位。**共享**
  参数（cl-functions `str` = 4 函数参数）quoted 引用照常收集（CAD 双槽
  fg[64] body + fg[105] param）。修复后 platform-api fg 全对齐，仅 seg0 +2
  （尾 if `nil` else 的 `PUSH_NIL; POP` no-op，CAD 省略，待 codegen 修）。
- **2026-08-23（CAD 对拍）persist.lsp byte-identical（46/67）**：两个通用修复
  （多参数 kwote lambda 参数块尾逆序 + `_then_tail` 值上下文），persist
  **seg0+seg1+nsyms 完全一致**（`/ 局部变量` + 双 kwote lambda `(lambda (e1 e2))`）：
  1. **多参数 kwote lambda 参数块尾逆序**（`cad_symbols.py` kwote 分支）：参数
     数 >1 时在 kwote 块**末尾**逆序注册（persist `(lambda (e1 e2) ...)` CAD
     fg[109]=E2、fg[110]=E1 = forward 块开头、_rev 块末尾），body 收集排除
     （`arg_names | lambda_args`）；单参数（scheduler `task-item`、i18n `opt%`）
     仍内联（CAD `kwote = CAR TASK-ITEM`）。
  2. **`_then_tail` 值上下文**（`codegen.py` `_emit_if`）：`_then_tail =
     self._in_tail_context or self._module_mode or not self._in_stmt_ctx`——值
     上下文（setq RHS、外层 if 分支值）的 if 分支值被使用，`_then_tail=True`
     使分支末 progn 的 `nil` 值不被 `_last_nil_stmt`（`not saved_tail`）省略
     （persist @::get-local-pkg-info `(progn (vl-file-delete ...) nil)` 为 if
     then 值，CAD 发射 PUSH_NIL；旧实现省略 → seg0 -1）。  回归：i18n/
     cl-functions/net/module/base-function/scheduler/voice/config-store/lifecycle
     保持 byte-identical，372 tests pass。
- **2026-08-23（CAD 对拍）browse.lsp byte-identical（47/67）**：五个通用修复
  （kwote lambda 参数可收集判定 + `_param_lam_hosts` args 延迟 + 单对 setq
  值上下文 DUP + `_interleave_mid` 移除 n_funcs 限制 + `_all_params` 条件排除），
  browse **seg0+seg1+nsyms 完全一致**（LIBFILE/X 参数沉底 + 16 mids 与注册交错）：
  1. **kwote lambda 参数可收集判定**（`cad_symbols.py` kwote 分支）：`_multi`
     改为「存在非 `_all_params` 排除的可收集参数」——可收集参数（非函数参数
     或 kwote lambda 宿主逆序更晚处理）统一在 forward 块开头（块尾逆序注册，
     browse LIBFILE fg[28]、X fg[107]、string-utils X）。`_all_params` 排除仅
     当参数拥有者逆序**更晚**处理（`_param_first_source < _cur_source_idx`，
     base-function `x` = pair src12 vs getf src13 → pair 注册）。
  2. **`_param_lam_hosts` args 延迟**：参数同时是逆序更晚的 kwote lambda 宿主
     的参数（string-utils `x` = strbytelen 参数 + string-split lambda 参数，
     宿主 reversed 6 > 0）时，args 循环跳过，由 lambda 收集（CAD x 在
     string-split kwote 块 fg[44]）。
  3. **单对 setq 值上下文 DUP**（`codegen.py` `_emit_setq`）：嵌套表达式里值
     被使用的单对 setq（browse `(mapcar ... (setq allfunlst (fun::get-list)))`
     CAD 实测 `DUP; SETQ_G`）补 DUP；模块代码语句（`_module_mode`，
     test-cond if-then 单对无 `0b`）与语句上下文不 DUP。
  4. **`_interleave_mid` 移除 `len(mid) <= n_funcs` 限制**（`cli.py`）：browse
     16 mids / 10 funcs（`set 'require`/`set 'require-release` 等 15 个别名
     set + 1 setq）仍与注册交错；mid_counts 逐函数分配（部分函数 2 mids）。
     回归：i18n/platform/base-function/cl-functions/net/module/persist 保持
     byte-identical，372 tests pass。
- **2026-08-23（CAD 对拍）platform-api.lsp byte-identical（48/67）**：一个通用
  修复（语句上下文 if 的 `nil` else no-op 省略），platform-api **seg0+seg1+
  nsyms 完全一致**（fg 已对齐 + seg0 +2 no-op 消除）：`_emit_if` 对语句上下文
  （`_in_stmt_ctx=True`）且 else 为常量 `nil`/`T` 的 if，省略 else 的
  `PUSH_NIL; POP` no-op（platform-api @::platform-http-download `(if (boundp
  '@::wget) ... nil)` 语句，CAD 实测 `JUMP 0; PUSH_VALUE result` 无 `01 0a`）——
  与 then 常量 `nil`/`T` 的省略对称（init/steps）。值上下文不省略。回归：
  既有 47 个 byte-identical 全部保持，372 tests pass。
- **2026-08-23（CAD 对拍）裸 lambda 值 `-lambda-`（file-utils/update/menu/load/
  error-handler/config-dialog）**：函数体 `(setq *error* (lambda (msg) ...))` 的
  裸 LambdaNode 值，CAD 编译为内嵌 `-lambda-` DEFUN（`JUMP; DEFUN -lambda-;
  PUSH_G <-lambda-槽>; SETQ_G`）。旧 codegen（`_emit_expr` LambdaNode 分支）把
  裸 lambda 当 quoted lambda 数据 → 缺 `-lambda-` DEFUN、MSG 等参数/体符号未
  注册（file-utils nsyms 75→79、seg0 1273→1468 与 CAD 对齐）。修复：
  - `codegen.py` `_emit_setq_value`：setq 值 = 裸 LambdaNode 时走
    `_emit_nested_lambda` + `PUSH_G <-lambda-槽>`（`_emit_setq`/`_emit_setq_expr`
    共用）。
  - `cad_symbols.py` `_collect_byteorder` LambdaNode 分支：裸 lambda 参数注册
    符号槽 + 体符号收集。
- **2026-08-23（CAD 对拍）update.lsp byte-identical（49/67）**：两个通用修复
  （裸 lambda 参数收集 + cond 测试 setq DUP），update **seg0+seg1+nsyms 完全一致**
  （`/ 局部变量` + `*error*` 裸 lambda + cond setq 测试）：
  1. **裸 lambda 参数收集**（`cli.py` `_collect_kwote_lambda_args`）：加
     LambdaNode 分支——`(setq *error* (lambda (msg) ...))` 的 `-lambda-` 参数
     列表照常收集，`_patch_usubr_idx` 才能识别 `-lambda-` DEFUN 的参数绑定
     （update `(lambda (msg)` PUSH_G 用 gvar_slot_res(msg)-1=73）。
  2. **cond 测试 setq DUP**（`codegen.py` `_emit_cond_stub`）：测试值为 cond 的
     "值"（COND_OR 消费），`_tail=True` 使测试内值位置 setq 补 DUP 保留返回值
     （update `(cond ((setq str-Response (@::http-request ...)) ...) ...)` 实测
     `USUBR; DUP; SETQ_G; COND_OR`），与 if 条件同规则。
  回归：i18n/platform/base-function/cl-macros/voice/persist/config-store/browse/
  platform-api/net-module 保持 byte-identical，372 tests pass。
- **2026-08-23（CAD 对拍）file-utils.lsp byte-identical（50/67）**：两个通用修复
  （`_shared_last` 大小写不敏感 + quoted 唯一参数逆序收集），file-utils **seg0+seg1+
  nsyms 完全一致**（共享参数 `str` 的 `'STR` quoted 引用 + kwote/裸 lambda 混合）：
  1. **`_shared_last` kept 扫描大小写不敏感**（`cad_symbols.py`）：共享参数被
     **其它函数 quoted 引用**（file-utils `'STR` 在 parse-header、参数声明 str 在
     path-win/path-unix/path-os）时，CAD 按**逆序最后引用者**注册（parse-header
     组 slot 60，非 path-win args 组 slot 49）。旧 kept 扫描 `_n in self.shared`
     大小写敏感（'STR' ≠ 'str'）→ `_shared_last['str']` 漏掉 parse-header 的
     `'STR` → path-win args 抢先占槽。修复：kept 扫描按 `_shared_ci`（大写集）
     匹配并存入**规范键**（参数声明名）。
  2. **quoted 唯一参数逆序收集**（`cad_symbols.py` quoted 单符号分支 + args 循环）：
     唯一参数被**逆序更晚处理**的函数 quoted 引用（owner src > quoter src，CAD
     槽在引用函数组）时收集并记 `_quoted_param_collected`，owner args 循环跳过；
     owner 逆序更晚处理（platform-api `'str` = platform-path src0 参数 +
     platform-open-url src10 引用）时仍排除由 owner 注册（回归保持）。
     **注意**：`'STR`/`str` 大小写变体——`_all_params`/`self.shared` 为小写键，
     quoted 单符号 `_n` 大写，排除/记录判断须大小写不敏感。
  回归：platform-api/base-function/i18n/cl-macros/browse/net-module/update/persist/
  config-store 保持 byte-identical，372 tests pass。
- **2026-08-23（CAD 对拍）package/load.lsp byte-identical（51/67）**：一个通用修复
  （`_emit_expr` 裸 lambda 值走 `-lambda-` DEFUN + LambdaNode 分支 `/ 局部变量`
  协议），load **seg0+seg1+nsyms 完全一致**（`@::load-error-handler` 裸 lambda
  **函数返回** `(lambda (msg / fp) ...)`）：
  1. **`_emit_expr(LambdaNode)`**（`codegen.py`）：裸 lambda 值（函数返回/表达式
     值）走 `_emit_nested_lambda` + `PUSH_G <-lambda-槽>`（原 `_emit_setq_value`
     仅覆盖 setq 值；load `@::load-error-handler` 把 `(lambda (msg / fp) ...)`
     作**返回值**，旧 codegen 当 quoted const BUILD_LIST → 缺 `-lambda-` DEFUN）。
     quoted `'(lambda ...)` 仍走 `_emit_quoted`（数据 const）。
  2. **LambdaNode 分支 `/ 局部变量`**（`cad_symbols.py` line 1665）：裸 lambda
     forward 序 = 参数 → locals 常量 → locals → 体（load CAD 实测
     `[MSG, (FP), FP, body...]`，逆序注册 `[body, FP, (FP), MSG]`）。`_al-bind-alist`
     不在此注册（共享槽，由多函数 locals 循环统一注册）。删除旧的重复 LambdaNode
     分支（line 1815，死代码）。
  回归：base-function/file-utils/update/persist/browse/download/reload 保持
  byte-identical，372 tests pass。
- **2026-08-23（CAD 对拍）立即应用 lambda `-lambda-` DEFUN + EVAL 模式**（52/67，
  config-sync/file 转正；dcl/audit/permission/user-manager/safe-eval 从远 DIFF
  收敛到 nsyms 对齐 + seg0 ≤4 字节）：`((lambda (a b) body...) args...)` 不再
  `_lower_immediate_lambda` 改写为 `(apply '(lambda ...) (list ...))`，保留
  ListExpr（head=LambdaNode）走 CAD 原生模式：
  1. **`_lower_immediate_lambda` 从管线移除**（`cli.py`）：`(let ...)` 降级
     仍保留 `_lower_let`。genuine `((lambda ...) args)` 由 codegen 处理。
  2. **codegen ListExpr-LambdaNode-head**（`codegen.py`）：实参先求值（留栈）→
     `_emit_nested_lambda`（JUMP + `-lambda-` DEFUN）→ `PUSH_G <-lambda->;
     EVAL argc, 7`。**不**发 CLEAR_ARGS（host 函数 CLEAR_ARGS 由 generate_function
     末尾发；user-manager if 语句上下文 CAD 实测 `EVAL 1,7` 后直接 `JUMP 1;
     PUSH_NIL` 无 CLEAR_ARGS）。
  3. **`_collect_byteorder` ListExpr 分支**：立即 lambda 先收集 args（字节码序，
     dcl CAD 实测 gensym 在 lambda 参数 dcl-str 之前）再收集 lambda 头。
  4. **`_iter_kwote_lambdas` ListExpr 分支**：立即 lambda 参数进 `_param_lam_hosts`
     （dcl `dcl-name` = dcl-run/dcl-run-with-setup 参数 + dcl-dialog lambda
     参数，CAD 槽在 dcl-dialog 组 idx6，owner args 循环跳过）。
  5. **LambdaNode 分支共享参数收集**：裸/立即 lambda 参数**共享**（dcl
     `dcl-name`）也收集（`_shared_last` 按 kept 逆序最后引用者注册，owner
     args 跳过）；移除 `_a not in self.shared` 守卫。
  6. **`_emit_expr(LambdaNode)` 裸 lambda 值走 `-lambda-`**（函数返回/表达式值，
     package/load `@::load-error-handler` 返回 `(lambda (msg / fp) ...)` 实测）。
  **注意**：`(let ...)` 文件（event-bus/error-handler/nlp）经 `_lower_let` 也走
  此 EVAL 模式，与 CAD 的 `LET + EVAL 0,const` 不同（let 任务另开）。
  回归：52/67 无回退，372 tests pass。
- **2026-08-23（CAD 对拍）audit.lsp byte-identical（53/67）**：四个通用修复
  （deferred const 首叶子编址 + `_al-bind-alist` 检测排除 `:keyword` + 嵌套
  lambda DEFUN 头 b1 循环深度 + `_emit_nested_lambda` next_slot/_loop_depth
  复位），audit **seg0+seg1+nsyms 完全一致**（`'(:package.install ...)` 事件
  列表 const + 立即 lambda `(foreach e ...)`）：
  1. **`_al-bind-alist` locals const 检测排除 `:keyword`**（`cli.py`）：quoted
     数据列表的 `:keyword` 叶子（audit `'(:package.install ...)` 截断为
     `:package`）**不是** locals const——旧检测 `all(x[0]=='SYMBOL')` 误匹配 →
     PUSH_G 落到 `_al-bind-alist` 槽（103，CAD 用 106）。加
     `not str(x[1]).startswith(':')`。
  2. **deferred const 首叶子编址**（`cli.py` CONST 分支）：多叶子 deferred
     const（audit 18 个 `:package` 占 res 128-145、fg 一槽）按**首叶子**资源
     位置 `_res_to_fg` 编址（`:PACKAGE` 首现 res 128 - 21 = fg 107 → 操作数
     106，CAD 实测；`nsyms-1` fallback 偏移 4）。仅未命中 const_map 且含多
     叶子时启用。
  3. **嵌套 lambda DEFUN 头 b1 循环深度**（`codegen.py` `_emit_nested_lambda`）：
     `b1 = argc + _direct_loop_depth(node.body)`（audit-query 立即 lambda
     `(foreach e ...)` 实测 `14 04 03 03 00`，与 generate_function 同规则）。
  4. **`_emit_nested_lambda` next_slot/_loop_depth 复位**：参数占局部槽
     0..argc-1，foreach/repeat 列表槽从 argc 起分配（audit SET_LOCAL 3 =
     argc；旧 host next_slot 复用 → SET_LOCAL 2 与参数冲突）；嵌套 lambda 独立
     函数作用域 `_loop_depth` 归零（与 generate_function line 229 一致）。
  回归：52/67 无回退，372 tests pass。
- **2026-08-23 语句上下文 progn 末 `T` no-op 省略**（`codegen.py`）：`_last_nil_stmt`
  扩展为 `_last_const_stmt` 覆盖 `T`——语句上下文（值被丢弃）progn 末 `T`/`nil`
  的 PUSH+POP 为纯 no-op，CAD 省略（permission `@::fetch-user-role` `(progn ...
  T)` 实测无 `T 槽;POP`，与 cl-functions `(progn ... nil)` 同规则）。尾/值上下文
  仍发射。回归：53/67 无回退，372 tests pass。
- **2026-08-23（CAD 对拍）permission.lsp byte-identical（54/67）**：一个通用修复
  （`_collect_byteorder` `_is_tail` 尾上下文跟踪），permission **seg0+seg1+nsyms
  完全一致**（`@::check-permission` 值位置 T + `@::fetch-user-role` 语句 progn
  尾 T 区分 + 立即 lambda）：
  `_collect_byteorder(self, node, out, arg_names, in_quote, cur_locals, _is_tail)`
  ——函数体**最后一个** form 传 `_is_tail=True`（其值为返回值），progn 末
  `T`/`nil` 仅**非尾**（值被丢弃）时跳过注册符号槽（permission fetch-user-role
  `(progn ... T)` 的 T 在语句 if 内、不注册；command kwote lambda 内 `t` 是
  lambda 返回值、注册——kwote/bare lambda 体末 form 也传 `_is_tail=True`）。
  IfNode then/else 分支传播 `_is_tail`（if 值为分支值）；`_collect_multi` 函数体
  循环、kwote lambda 体、裸 lambda 体末 form 均 `_is_tail=True`。回归：53/67
  无回退（command.lsp 恢复 byte-identical），372 tests pass。
- **2026-08-23 裸 lambda 参数拥有者排除**（`cad_symbols.py` 裸 LambdaNode 分支）：
  共享参数被**逆序更晚处理**的函数拥有者（`_param_first_source < 当前 source`，
  safe-eval `fn` = safe-fn-in-list-p src3 参数 + safe-form-p src4 lambda 参数，
  owner 更晚 idx3）时裸 lambda **排除**收集——由 owner（_shared_last）args 循环
  注册（CAD fn 在 safe-fn-in-list-p 组 fg[61]，非 safe-form-p 组）。dcl `dcl-name`
  （owner src9 < quoter src5）不受影响。safe-eval fg 表全对齐（seg0 仍 DIFF：
  deferred 大 const 编址）。回归：54/67 无回退，372 tests pass。
- **2026-08-23 deferred 大 const 叶子序列匹配**（`cli.py` CONST 分支）：多叶子
  deferred const 按 const 叶子**序列**在资源流中匹配起始位置 `_res_to_fg` 编址
  （safe-eval 白名单 `'(car cdr ...)` 的 CAR 体引用 res60 不匹配全序列 → 落在
  const 块 res70 → fg 62 → 操作数 61；audit `:PACKAGE` 首现 res 128 → 107 →
  106）。首叶子/`_res_slot_of` 单一匹配会误取普通符号引用（safe-eval CAR 体
  引用），须全序列匹配。回归：54/67 无回退（audit 保持 byte-identical），
  372 tests pass。
- **2026-08-23 内嵌 `-lambda-` DEFCODE 槽序 + 源码序覆盖**（`cli.py` +
  `resource_builder.py`，safe-eval byte-identical 55/67）：`-lambda-` 槽
  （lam_order，`new_idx = nsyms-1-_li`）与 DEFCODE 目录键顺序（nested_list →
  lam_offsets）按函数类型区分：
  1. **含立即 lambda 且单函数内 ≥2 个 `-lambda-`**（safe-eval safe-form-p 4 个）：
     lam_order 按**源码序逆序**（fn=_li 3 → 槽 62），nested_list 按**源码序正序**
     （DEFCODE item 顺序 fn/ok-tail/clause/b）。跨函数（audit/browse 每函数 1 个）
     不覆盖（symtab 顺序即正确）。
  2. **纯 kwote 文件**（log/browse 等）：nested_list 全局按 **offset 逆序**
     （CAD DEFCODE 逆序发射；跨函数拼接默认函数序递增须全局排序）。
  `resource_builder.lam_offsets` 由 offset 逆序排序改为 **func_offsets 键顺序**
  （nested_list 序）——nested_list 已在 cli 按正确顺序构建。
  回归：55/67 无回退（safe-eval/browse/log/module/persist/cn-commands 全恢复），
  372 tests pass。
- **2026-08-23（CAD 对拍）user-manager seg0 对齐（模块代码残余 DIFF）**：
  通用修复（立即 lambda if-then 无 POP + else 常量保留、repeat 多语句体中间
  POP + 尾 repeat PUSH_NIL 占位、str_map emoji `\U+XXXX` 转义匹配）使
  user-manager **seg0 完全一致**（`((lambda ...) args)` EVAL + `(if ... nil)`
  语句、anti-crack `(repeat 10 (prompt ...) (prompt "\n"))` 尾 repeat、
  `@::save-login-session` `"\n✅ "` emoji 字符串 fg 槽）：
  1. `_emit_if` then 立即 lambda（ListExpr head LambdaNode）不 POP 分支值；
     else 常量 nil/T 仅在 then 被 POP 时省略，否则保留 + 不 POP（user-manager
     `(if token-callback ((lambda ...) ...) nil)` 实测
     `EVAL; JUMP(1); 01; CLEAR_ARGS`）。
  2. `_emit_repeat_stub` 多语句体中间语句 POP（anti-crack 实测 `USUBR; POP`）；
     尾 repeat（函数返回值的 repeat）loop 头 PUSH_NIL 占位 + JMP32_IFNOT 后
     POP（同尾 while 协议）。
  3. `_patch_usubr_idx` str_map 查询用 `_enc_with_escape` 转义键——emoji 等
     GBK 无法编码字符在资源流注册为 `\U+XXXX`（`"\n✅ "` → fg `\n\U+2705 `），
     symtab 保留实际字符，旧查询失配 → fallback nsyms-1 错槽。
  回归：55/67 无回退，372 tests pass。
- **2026-08-23（CAD 对拍）user-manager + config-sync/file byte-identical（56/67）**：
  四个通用修复（模块代码 setq 函数值 PUSH_VALUE、`_interleave_mid` 放宽为
  `sum(mid_counts)>0`、mid_counts 跳过 `_top_lambda_names`、if then 立即 lambda
  语句上下文 POP）：
  1. **模块代码 setq 函数符号值 PUSH_VALUE**（`cli.py` `_stmt_bytes`）：顶层
     `(setq @::valid-user @::check-userinfo)` 的值（函数名）CAD 用
     `PUSH_VALUE`（实测 `03 19 00 0b 06 18 00`），旧实现按函数名发 PUSH_G
     （@lisp_u `(setq @::unschedule-task @::string-to-list)` 功能验证，
     字节与 CAD 不符）。PUSH_VALUE 压模块注册段槽的值（函数对象），SETQ_G 绑定。
  2. **`_interleave_mid` 放宽为 `sum(mid_counts) > 0`**（`cli.py`）：defun 注册
     与 mid 顶层语句**始终按源码位置交错**（`[reg i, mid[i]]`，mid_counts 分配）。
     user-manager 的 `anti-crack`（line 18）定义在 setq valid-user（line 16）与
     setq *userinfo*（line 26）之间 → CAD 注册插在中间。旧条件只对别名 set
     交错（i18n/platform 等 mid 全在 TAIL 注册前仍正确）。@lisp-env（mid_forms
     仅 InPackage、mid_counts 全 0）走非交错路径。
  3. **mid_counts 跳过 `_top_lambda_names`**（`cli.py`）：提升的 setq-lambda
     defun（platform @::fasext/@::vlx）不占 mid 槽——其后 mid 语句（`(set
     'fasext ...)`、@::vlx 绑定）归前一个真实 defun（分给 -lambda- 槽会丢失
     → 模块代码缺语句）。
  4. **if then 立即 lambda 语句上下文 POP**（`codegen.py` `_emit_if`）：then
     立即 lambda 的 POP 排除条件由 `not _then_imm` 放宽为
     `not (_then_imm and _then_tail)`——`_then_tail=True`（值保留，user-manager
     `(if token-callback ((lambda ...) ...) nil)` EVAL 后 JUMP 无 POP）不 POP；
     `_then_tail=False`（语句上下文，config-sync/file `(if content ((lambda
     ...) ...) nil)` 实测 `EVAL; POP; JUMP(0)`）丢弃 EVAL 结果。
  回归：55/67 无回退（audit/permission/event-bus 等保持），372 tests pass。
- **2026-08-23（CAD 对拍）dcl quoted `'STR` const 化（2558→2557）**：
  `_collect_byteorder` quoted 单符号分支——唯一参数被**其它函数** quoted 引用
  （dcl `'STR` = @::dcl-escape 参数 + @::dcl-attrs-to-str `(eq 'STR (type ...))`
  引用）时注册 const（`('SYMBOL','STR')` const 槽）而非排除——排除后 codegen
  `_emit_quoted` 的 `get_const_idx` 找不到会 get_or_add 注册独立 SYMBOL 槽
  → slot 错位（slot 205 应为 `=` 而非 STR）。共享参数（file-utils `'STR`）
  仍照常收集（SYMBOL 槽，_quoted_param_collected）。dcl 残余 DIFF（2557 vs
  2555）：`\\` 字符串（@::dcl-escape `"\\\\"`）注册在 symbol_slots 227 而非
  GVARINIT（CAD fg[150]）、STR const 位置（item 269 vs 292）——待后续对拍。
- **2026-08-23（CAD 对拍）`(let ...)` 原生 LET 模式（event-bus/error-handler/nlp
  结构对齐，nsyms 全对齐）**：
  1. **`_lower_let` bug 修复**（cli.py）：parser 把 `(let ((v e)...) body)` 的
     绑定对 `(v e)` 解析为 **Call(name=v, args=[e])**（首元素符号 → Call），
     旧 else 分支用 `str(b)` 当变量名 → `"CALL(NAME='ENTRY'...)"` 错误符号槽。
     修复：Call 绑定对取 `b.name` + `b.args[0]`。
  2. **移除 `_lower_let` 降级**（cli.py line 2559 注释）：let 保留为 Call，
     codegen 原生编译（CAD `LET + EVAL 0` 模式）。safe-eval 的 `'(let let*)`
     是 quoted 数据（非调用）不受影响。
  3. **codegen `_emit_let`**（codegen.py）：`<e求值>; USUBR(1, list);
     EVAL 0, 7; <body>`——绑定值求值后压成列表，`EVAL 0`（LET 内建）建立
     局部环境，body 直接执行（绑定变量为普通符号槽 PUSH_VALUE 读取，不生成
     `-lambda-`）。event-bus `(let ((entry (assoc ...))) (if entry ...))`
     实测 `USUBR; EVAL 0; PUSH_VALUE entry; JMP32_IFNOT`。
  4. **`_collect_byteorder` let 分支**（cad_symbols.py）：前向符号序 = 绑定值
     args → 绑定值 name → 绑定变量 → body → LIST → LET（fg 表
     `LET LIST SUBST CONS CDR ENTRY ASSOC *EVENTS*` = reversed）。
  效果：event-bus nsyms 35→31（=CAD）、fg 表逐槽一致。**残余 DIFF**：let 的
  `USUBR(1, list)` 操作数我们 22（build_mvar fg[23]-1）vs CAD 26——CAD 原始
  gvar/function 表与 build_mvar 重建有偏移，需 CAD 真机逆向。功能正确性待
  CAD 真机验证（`_emit_let` 无测试覆盖）。
- **2026-08-23（CAD 对拍）dcl byte-identical（57/67）**：三个通用修复
  （quoted `'STR` const 延迟到资源序末尾 + `_is_other_param` 大小写不敏感 +
  foreach 列表求值 `_value_ctx`），dcl **seg0+seg1+nsyms 完全一致**（`'STR`
  const、`\\` 字符串 GVARINIT、@::dcl-escape 组槽位全部对齐）：
  1. **`'STR` const 延迟到资源序末尾**（`cad_symbols.py`）：唯一参数被其它函数
     quoted 引用的 const（dcl `'STR` = @::dcl-escape 参数 + @::dcl-attrs-to-str
     `(eq 'STR (type ...))`）**不注册到引用函数组**（旧 slot 205 提前 22 槽），
     收集到 `self._deferred_consts`，collect_program 末尾追加到**第一个函数**
     的 kept 末尾（zip(reversed) 最后迭代 = 资源序末尾，CAD slot 227）。
     `_deferred_consts` 在 `__init__` 初始化（单函数路径也访问）。
  2. **`_is_other_param` 大小写不敏感**：`_all_params`/`self.shared`/
     `_param_first_source` 为参数声明名（小写 str），quoted 单符号可能大写
     `'STR`（dcl line 32）——排除判断用 `.upper()` 集——否则 dcl 的 `'STR`
     落普通分支注册 SYMBOL 槽（slot 205）而非 const。
  3. **foreach 列表求值 `_value_ctx`**（`codegen.py` `_emit_foreach_stub`）：
     列表是 foreach 的输入（值上下文），须清 `_in_stmt_ctx`——否则列表为 if
     时（dcl @::dcl-run-with-setup `(foreach line (if ... (list dcl-content))
     ...)`）else 分支 `(list ...)` 被 `_emit_if` 的语句 POP 误丢（CAD 实测
     `USUBR(1,list); SET_LOCAL` 无 POP）。
  回归：56/67 无回退（`_emit_foreach` 非 stub 路径同步加 `_value_ctx`），
  372 tests pass。
- **2026-08-23（CAD 对拍）setup 模块注册 kwote + defun-q（部分）**：
  setup 顶层 `(mapcar (function (lambda ...)) @::*uris*)` 的 kwote lambda 在
  模块注册段缺 `kwote` 符号（CAD slot[7]=kwote，我们 @::*URIS*）——通用
  `_form_read_target` 加 kwote 分支会破坏 platform（setq-lambda 绑定 kwote
  也注册）——改为 **Call 分支**（`_form_read_target`）：仅**调用参数**的
  kwote lambda 注册 `kwote`（setq 值绑定不注册，platform 保持）。`to_const
  (Defun)` 对 quoted defun 返回 `defun-q`；`_generate_quoted_defun` 与
  `_lower_nested_defuns._as_lambda` 对 defun-q 用 kwote（FUNCTION）；`to_const
  (QuotedExpr)` 对 quoted lambda 数据（expr 是 LambdaNode）返回
  `(FUNCTION (LAMBDA ...))`（CAD 区分 FUNCTION/QUOTE，setup slot[95]）。
  残余 DIFF：nsyms 164 vs 166 少 2、slot[272] 起函数体符号序 105 处（
  @::add-domain-in-trusteddomains 组 CADR/:// 等 kwote lambda 体符号序）
  ——待后续对拍。
- **2026-08-23（CAD 对拍）i18n.lsp byte-identical（40/67）**：n_pre START 注册
  跳过 globals（`cli.py` `_n_pre`），i18n **seg0+seg1+nsyms 完全一致**：CAD 把
  **globals 之后的第一个连续 defun 组**注册在 mid 顶层语句之前（i18n
  @::codepage2lang 在 SETQ[0]（模块全局，line 3）后立即注册、在 SETQ[2]（line 17
  mid 语句）前）。旧 `_n_pre` 循环在首个 defun 之前的顶层 form（SETQ[0]）处
  break → n_pre=0 → codepage2lang 落 TAIL 注册（mid 语句之后）。修复：循环跳过
  globals（首个 defun 之前的顶层语句），仅对首个 defun 之后的连续 defun 计数；
  无 mid 顶层语句（command.lsp 纯函数）仍 `_saw_top_stmt=False` → n_pre 归 0。
  回归：log.lsp/platform.lsp/command.lsp 保持 byte-identical（前导 in-package/
  use-package 仍跳过）。
- **2026-08-23（CAD 对拍）ui.lsp byte-identical（39/67）**：ForeachNode 记录
  `vlax-for` 名 + `_strip_list_markers` 大小写保留集优先，ui.lsp **seg0+seg1+nsyms
  完全一致**（quoted lambda 内 `(vlax-for n meth2 ...)`）：
  1. **ForeachNode.name 字段**（`ast_nodes.py` + `parser.py`）：`vlax-for` 展开为
     ForeachNode 时记录 `name='vlax-for'`。`_collect_forward`/`_to_const`/
     `_emit_quoted` 用 `node.name or 'foreach'`——quoted 数据 const 内嵌
     `(vlax-for ...)` 注册 `vlax-for`（CAD ui.lsp golden 实测 const 字节
     `5b VLAX-FOR`），`_collect_forward` 模块注册同理。测试
     `test_vlax_for_expanded_to_foreach` 更新：断言 VLAX-FOR 槽存在（旧断言
     "不应出现" 是展开前行为，CAD 实际注册）。
  2. **`_strip_list_markers` 大小写保留集优先**（`cli.py`）：`_VLISP_CASE_PRESERVE`
     检查移到 vla-/vlax- 分支**之前**——`vlax-for` 的 `_enc_sym` 规范化为
     `VLAX-FOR`（保留集），但 `_strip_list_markers` 旧顺序先命中 vla-/vlax-
     分支返回小写 `vlax-for` → const_map 失配 → PUSH_G 落 nsyms-1。重排后
     `VLAX-FOR` 匹配 fg 表 const。
- **2026-08-23（CAD 对拍）reactor.lsp byte-identical（38/67）**：两个通用修复 +
  cond else 键 T 去重，reactor.lsp **seg0+seg1+nsyms 完全一致**：
  1. **cond else 键 `t` 与值位置 `t` 去重**（`cad_symbols.py` `_collect_byteorder`
     Cond 分支）：`(t ...)` else 键强制 append（绕过 `_seen`），与值位置
     `(setq x t)`（reactor @::dbclicked 的 flag/flag2）共存 → _rev 两个 `t` 都过
     `i == t_last` 分支 → T 槽双发（nsyms +1、T 提前到测试组前）。修复：Cond
     分支 append 前查 `_seen`（值位置 t 已注册时跳过强制 t）+ `_t_added` 同函数
     只注册一次。CAD T 槽位置由**最后一个** `t` 引用决定（reactor CAD 实测
     `IS-BRICSCAD @::PLATFORM-IS-LINUX-P T`——T 在测试组后）。
  2. **顺序 foreach 复用局部槽**（`codegen.py`）：`_emit_foreach_stub`/`_emit_repeat_stub`
     局部槽 key 由 `buf.pos()`（每处唯一）改 `__foreach_list__{self._loop_depth}`/
     `__repeat__{self._loop_depth}`——同一直接体深度顺序循环复用同一槽
     （reactor 两个 foreach 都 SET_LOCAL 2），嵌套循环递增深度用独立槽
     （与 DEFUN 头 b1=argc+并发深度对应）。`self._loop_depth` 逐函数归零。
- **2026-08-23（CAD 对拍）lifecycle.lsp byte-identical（37/67）**：`_collect_multi`
  跨函数 `seen_refs` 去重改**大小写不敏感**（`cad_symbols.py` `_ci_ref_key`：
  普通符号 `.upper()`，vla-/vlax-/字符串/`__` 键保留原样）。原因：lifecycle 的
  `(eq 'LIST (type-of deps))`（quoted 'LIST，get-pkg-deps）与 `(list ...)`（内建
  调用，pkg-on-load 等）同键——旧 case-sensitive set 使两者并存（`list`/`LIST`
  各自 kept），逆序注册时 get-pkg-deps（i=1）先于 pkg-on-load（i=6）→ LIST 占
  fg[12] 提前 26 槽；CAD 大小写不敏感去重到**源码序首次**（pkg-on-load 的
  `(list ...)`）→ LIST fg[38]。回归：37/67 无回退（cl-macros 等共享参数/
  重复槽不受影响）。
- **2026-08-23（CAD 对拍）voice.lsp byte-identical（36/67）**：三个通用修复 +
  `get_or_add` 大小写合并，voice.lsp **seg0+seg1+nsyms 完全一致**（ui.lsp 的
  seg0 同步转正、lifecycle/cl-functions 的 nsyms 差异消除）：
  1. **cond 语句上下文 PUSH_NIL 默认值省略**（`codegen.py` `_emit_cond_stub`）：
     `_omit_default = self._in_stmt_ctx`（不再要求末子句为 `(t ...)`）——语句
     上下文（值被丢弃）的 cond，无 else（voice C:@VOICE `(cond ((= choice "1")
     ...) ((= choice "2") ...) ((= choice "3") ...))`）CAD 实测同样省略
     fall-through 的 `01` PUSH_NIL（cond 自平衡，值为纯 no-op）；模块代码
     （platform 顶层 cond）值上下文仍保留。旧逻辑仅对 `(t ...)` else 省略
     （cl-macros），voice 无 else 分支错发 `01` → 每处 +1 字节、后续
     COND_OR/JUMP 偏移全偏。
  2. **`symtab.get_or_add` 大小写合并**（`symbol_table.py`）：cad_symbols
     收集器 `_in_name_set` 大小写不敏感（'Status'/'status' 去重），但
     name_to_idx 大小写敏感——codegen `get_or_add('status')` 找不到 derive 的
     'Status' → 各占一槽 nsyms +2、后续槽错位（voice.lsp 的 `status`/`count`
     局部）。修复：get_or_add 精确未命中时做大小写不敏感回退（仅非
     vla-/vlax-/保留大小写符号，`_k.upper() == name.upper()` 且非 `__` 前缀
     key），命中返回既有槽不新增。**不能**全局 `_normalize_name` 转大写
      （cli.py `add_force` 检查用原始 `sym in name_to_idx`，转大写后重复函数
      名不再命中 → 递归/跨函数重复槽丢失 → 35→9/67 大回归）。
- **2026-08-23（CAD 对拍）log.lsp byte-identical（35/67）**：两个通用修复 + 一个
  模块代码分组修复，log.lsp **seg0+seg1+nsyms 完全一致**（command.lsp 同步恢复）：
  1. **`_res_slot_of` 大小写回退**（`cli.py`）：先精确匹配（字符串大小写敏感），
     未命中再做不区分大小写匹配。`0x56` 保留大小写块 `_al-bind-alist`/`kwote`/
     `ads-cmd` 以源码大小写入 symbol_slots，而查询方 `_best[0]`/`str(name).upper()`
     传大写——log.lsp `_res_slot_of("_AL-BIND-ALIST")` 精确匹配 None →
     `_res_offset` 变 None → 表外符号回退 nsyms-1 错槽（`level` 参数 134 vs CAD 132）。
  2. **kwote 块锚点含字符串**（`cad_symbols.py` 多函数路径）：kwote lambda 是调用
     的**首参**时（log-cleanup `(vl-remove-if (function (lambda (f) ...))
     (vl-directory-files log-dir "*.log*" 1))`），调用表达式的符号序 =
     `[kwote 块, "*.log*", VL-DIRECTORY-FILES, VL-REMOVE-IF]`，CAD 把 kwote 块
     插到**字符串** `"*.log*"` 之后（fg[76]=*.log*、fg[77]=kwote），旧锚点检测
     `startswith('"')` 跳过字符串找到 VL-DIRECTORY-FILES → 块插到 *.log* 之前
     （fg[76]=kwote、fg[80]=*.log*）。修复：锚点不再跳过字符串（`"` 从
     `startswith(('"',"'","("))` 移除），仅跳过 quoted 数据/const/nil/T。回归：
     net/proxy/cache/reload/i18n 无回退。
  3. **n_pre 跳过包设置 + 无顶层语句时归零**（`cli.py`）：`_n_pre` 循环遇
     InPackage/Defpackage/use-package Call 应 `continue`（log.lsp 前导
     `(in-package :@)` + `(use-package :autolisp)` 使旧代码 n_pre=0 → 前 2 个
     函数（@::log-level/@::log-level-name，定义在首个顶层 if 之前）的 START
     注册缺失 → 模块代码顶层语句全在注册前）；**但**纯函数文件（command.lsp 无
     顶层语句）循环走完所有 defun 后 `_saw_top_stmt=False` → n_pre 归 0（全部
     TAIL 注册，与 CAD 一致）。log.lsp 顶层 ifs（line 39/41/43/45）由 globals/
     mid/post 分组正确分布到 START 注册前后。
- **2026-08-23（CAD 对拍）base-function 根因定位（符号槽序，非 build_mvar 解析 bug）**：
   逐字节扫描 base-function 的 seg0（`09/03/06` 操作数）与 CAD golden 对拍后确认，
  差异是**符号注册顺序**（`cad_symbols.py` 收集器），不是 build_mvar_tables 的
  GVARINIT 栈解析——两套解析（parse_resource_stream 与 build_mvar 复制）对
  SYMBOL/STRING/REAL 注册计数**完全一致**（284 = 250 SYM + 30 STR + 4 REAL），
  且 GVARINIT（pos 3500，var_pos=0，st_init=165，栈长 163）的右移填充本身正确。
  **getf 函数（base-function.lsp:166）的 kwote lambda 块序差异**：
  `(function (lambda (x) (= (vl-prin1-to-string x) (vl-prin1-to-string property))))`
  中 OUR fg 把 `kwote`@49、VL-PRIN1-TO-STRING@50、X@51、RESULT@52、PROPERTY@53、
  PLIST@54、CONS@55、PAIR@56、CDR@57、ATOM@58 连排；CAD 实测 X@50、RESULT@51、
  PROPERTY@52、…、ATOM@57、**VL-PRIN1-TO-STRING@58**——即 CAD 把 lambda 参数 X
  与捕获参数 PROPERTY 放 kwote 块前段（50/52），把体内 SUBR **VL-PRIN1-TO-STRING
  挪到函数体符号组末尾**（58，比 we 早 8 槽），且该区无 kwote 槽（-1 漂移）。
  这与既有「kwote lambda 参数统一注册符号槽」规则冲突——base-function 的 kwote
  体内 SUBR 应进**函数体符号组**而非 kwote 块，是新的 ORDER 语义（待逐文件判定）。
- **2026-08-18 更新**：修复表外字符串/常量 PUSH_G 越界、模块区 T 槽位置、
  顶层 progn 语句语义、纯顶层 REAL 槽引用、未使用 / 局部变量槽五类后，
  **67/67 全部通过编译产物验证**，**byte-identity 13/67**（新增 @lisp-env /
  constants / net-checksum / platform）。
- **2026-08-21 更新**：新增 net-uri / net-reload 两个 byte-identical（15/67），
  关键修复：
  1. **`_res_slot_of` 取末次出现**（net/uri）：符号同时注册于模块区与函数体区
     时（顶层变量 `@::*offline-mode*` symslot[3] 模块区 + [57] 函数体区），
     函数体 PUSH_VALUE 引用须取函数体区槽（≥ nsyms → nsyms-1）；此前取模块
     区槽（3）算出 2 的错误操作数。
  2. **`find_key` 多候选密钥判优**（log.fas）：密钥长度字节可被多个 rlen 满足
     （rlen=8 与 9 均成立），按「解密后是否以 `14 01 01 01 00` 模块头开头」
     判优选真密钥；此前取首个候选解出乱码资源。
  3. **模块注册 kwote 0x56 块**（setup.lsp）：模块注册段连续 SYMBOL 块中遇
     `kwote` 须独立 `56 kwote 00 00` 单块（与函数体符号区同规则）。
  4. **单函数 kwote 块体逆序 + `-lambda-` 槽重映射**（net/reload）：单函数
     双 kwote 的 lambda 体符号按收集序逆序注册、`kwote` 插到调用者之后；
     `-lambda-` 槽按 `nsyms-1-lam_idx` 编址（`_patch_usubr_idx` 对单函数
     kwote 文件仅重映射 PUSH_G `-lambda-` 引用）。
- **2026-08-21 增补**：新增 net/proxy 一个 byte-identical（19/67，累计含
  init/sequence / net/progress / net/http / net/registry / net/mid 等），关键修复：
  1. **多函数 kwote 块体逆序**（net/proxy，`cad_symbols.py`）：函数体符号逆序
     注册的路径（`_collect_single` 与多函数 `_collect_byteorder` 两处）对
     kwote 块统一按「kwote + 块体**逆序**」重构（`_kwote_blocks` 存
     `(kwote 项, 块体逆序, 调用者名)`，`reversed()` 迭代插入）；`kwote` 插到
     调用者之后、块体逆序随其后（net/proxy 双 kwote 实测 `VL-STRING-SEARCH
     @proxy.exe vlax-release-object RESULT ReadAll STDOUT vlax-get StdOut
     EXEC vlax-invoke tasklist Exec SHELL vlax-get-or-create-object
     WScript.Shell`）。
  2. **kwote lambda `/ locals` 常量与 `_al-bind-alist` 槽序**（net/proxy）：
     `_collect_byteorder` kwote 分支收集 locals 常量时，先收 `(quote (locals...))`
     常量、后收 `_al-bind-alist`——kwote 块逆序后 `_al-bind-alist` 落在
     locals 之前（CAD 槽 33 `_al-bind-alist`、34-37 locals，`56` 块在
     `39 04 00` const 之前）。
  3. **`_patch_usubr_idx` 的 `_al-bind-alist` locals 常量编址**（net/proxy）：
     `(quote (loc1 ...))` 常量未被 fg 表收录（内嵌 `-lambda-` DEFCODE 消耗
     常量作 module 参数，build_mvar_tables 无法映射）→ `const_map` 查不到，
     旧 fallback `nsyms-1` 偏移 2（34 vs CAD 32）。修复：常量结构为纯 SYMBOL
     列表且 `_AL-BIND-ALIST` 在 gvar_map 时，PUSH_G 操作数 = `_AL-BIND-ALIST`
     槽 - offset（CAD 常量 gvar 槽 = `_al-bind-alist` 槽 + 1，t11 实测
      fg[6]=_al-bind-alist、常量 PUSH_G=6）。注意 gvar_map 键统一大写
      （`"_AL-BIND-ALIST"`，小写 `.get()` 返回 None）。
- **2026-08-21 增补 2**：新增 net/cache 一个 byte-identical（20/67），关键修复：
  1. **kwote 块无调用者时 `kwote` 放在块体之前**（net/cache @::uri-safe，`cad_symbols.py`
     多函数路径）：kwote lambda 的调用者（vl-catch-all-apply）被跨函数去重后，
     `_caller=None` → 旧 `_rev = _body + _rev` 丢弃 `kwote` 符号本身（OURS kwote
     @[19] vs CAD @[3]）。修复：caller 为空时 `_rev = [_kw] + _body + _rev`
     （CAD 实测 `[kwote, @::URI]`）。
  2. **`claimed_in_body` 局部变量不重复注册**（net/cache `result`）：`result` 是
     3 个函数共用的 `/ 局部变量`，cache-store 体 `(setq result ...)` 已注册 body
     槽。旧 `if loc in claimed_in_body` 在逆序首个声明函数（uri-safe）提前注册 →
     OURS `result`@[5] vs CAD@[9]（cache-store 体组）。修复：仅当局部在**当前
     函数体**引用（`loc in 本函数 kept`）且未被函数体组注册时才 add——实际已由
     函数体组注册，为安全 no-op。注意**不能**直接 `not in claimed_in_body`
     （会把 net/checksum 未使用的 `checksum` 反向注册 → nsyms +1）；用「本函数
     kept」判定同时满足 net/cache（跨函数共享局部不提前注册）与 net/checksum
     （unused 局部不注册）。
  3. **`_patch_usubr_idx` offset 仅作用于表外符号**（net/cache params）：`-lambda-`
     额外槽的 offset=1 只应补偿**不在 gvar 表**的符号（参数/末尾常量按 gvar 槽
     = nsyms 编址）。命中的 gvar 表符号槽位已含偏移，不再减——旧代码对所有路径
     `gvar_map[sym] - 1 - offset` 统一减，致 body 符号（result fg[8]→SETQ_G 6 vs
     CAD 7）错 1。修复：`gvar_slot()` 返回 (槽位, 是否命中)，仅 `_hit=False`
     （表外 fallback `nsyms-1-offset`）时减 offset；命中的 `gvar_map/const_map/
     str_map/real_map` 均 `- 1` 不减。i18n（原 offset=1 对象）的 byte-identity
     测试已 2026-08-12 skip，此改动不影响现 regressions。
- **2026-08-21 增补 3**：新增 net/headers 一个 byte-identical（21/67），关键修复：
  1. **尾 while 多语句体的中间语句 POP + 尾语句 DUP**（net/headers @::set-headers-ext
     `(while ... (vlax-invoke ...) (setq i ...))`，`codegen.py` `_emit_while`）：
     尾 while 的体语句旧代码全按 `_in_tail_context` 跳过 POP，多语句体中间
     `(vlax-invoke ...)` 缺 POP（CAD 实测 `USUBR; NIL; PV0; POP`）、尾
     `(setq i ...)` 缺 DUP（CAD 实测 `DUP; SETQ_G`）。修复：体循环里仅**最后
     一个**语句在尾上下文发射（`_emit_expr(_tail=True)` 补 DUP 保留值），中间
     语句仍语句上下文（调用值 POP 丢弃）；单语句体（base-function @::sleep
     `(while ... (princ))`）不受影响。回归：test_compiler_output 全绿。
  2. **`_strip_list_markers` 的 NIL 归一化**（net/headers @::set-timeouts
     `'(lambda () ...)`，`cli.py`）：symtab 常量的 `('NIL',)` 是 1 元组，旧
     `len(v)==2` 分支不命中 → 结构匹配保留 `('NIL',)`，但 fg 表把 NIL 表示为
     None → const_map 失配 → PUSH_G 落 nsyms-1。修复：顶层单独处理
     `len(v)==1 and v[0]=='NIL'` → None。
  3. **`_strip_list_markers` 的 vla-/vlax- 大小写保留**（net/headers quoted lambda
     内 `vlax-invoke`，`cli.py`）：fg 表对 vla-/vlax- 符号保留源码大小写
     （`vlax-invoke` 小写），`_strip_list_markers` 一律 `.upper()` 致 const_map
     失配。修复：vla-/vlax- 前缀与 `_VLISP_CASE_PRESERVE` 符号保持原大小写
     （与 `resource_builder._enc_sym` 一致），其余大写。
- **46 个 DIFF**：多数 nsyms ±1（符号槽序差异），少数大差异
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

- **变参 `&rest`/`&optional`：CAD 不支持，byte-identity 不适用**（2026-08-19
  澄清，large_synthetic 对拍）：CAD 编译器**不识别变参语义**，把 `&rest`/
  `&optional` 当**普通参数名**编译（`(a &optional opt &rest rest)` → DEFUN
  头 argc=5、参数绑定把 `&REST`/`&OPTIONAL` 当符号槽逐个 GET_LOCAL、
  资源段注册这两个标记符号 nsyms +2）——即 CAD 变参函数**不收集变参列表**，
  运行行为即错。atlispcc **正确支持**变参（`&optional` 缺省、`&rest` 收集，
  t19/t21 真机功能验证通过），故变参函数与 CAD 的 seg0/nsyms 差异是**预期
  且正确**的（每函数约 12 字节、nsyms 差 2），**不应追求 byte-identity**。
  含变参函数的文件（如 large_synthetic）无法整文件 byte-identity；纯命令/
  混合命令（无变参）不受影响。相关对拍记录：CAD lgf-var-000 `PUSH_G &OPTIONAL;
  GET_LOCAL 0; PUSH_G OPT; GET_LOCAL 1; PUSH_G &REST; GET_LOCAL 2; ...`。
- **纯顶层 set/setq-lambda 第二区符号槽序残余 diff**（2026-08-18，bootstrap
  fixture 重建对拍）：单 `-lambda-` 文件 CAD 用 **reversed-fwd（含 tail-call 与
  参数原位）** 编址（bs4 实测 `STRCAT = SUBSTR - STRLEN .fas FILE` = 逆序引用
  序），多 lambda 文件（无共享参数）按 `[体][参数][tail-call]`（setq-lambda.lsp
  byte-identical）；共享参数名跨 lambda 时 CAD 把共享参数移末尾、tail-call 前移
  （bs9 实测 `[体][STRCAT][体2][共享参数]`）。compiler 当前统一按
  `[体][参数][tail-call]`（单 lambda 亦如此），与 CAD 单 lambda/共享参数场景
  不符。重建 fixture `tests/bootstrap.lsp` + golden `tests/cad/bootstrap_cad.fas`
  保留作复现，byte-identity 测试暂从 CAD_GOLDEN_PAIRS 移除（优雅 skip）。
- **表外字符串 PUSH_G 越界回归**（2026-08-18，已修）：`_patch_usubr_idx` STRING
  分支此前一律用 `_res_slot_of`（真实 symbol_slots 索引），对索引 ≥ nsyms 的
  函数体字符串会越界（t14_command `"Hello from command!"` 槽 7 ≥ nsyms 6 →
  CAD 用 nsyms-1=5）。修复：仅 `_rslot < nsyms` 用真实索引，否则 nsyms-1。
  回归 `test_compile_src_byte_identity[10_commands/11_top_level]`。
- **CONST 未命中 fg 表 fallback 越界**（2026-08-18，已修）：quoted 数据常量
  （`_al-bind-alist '(locals)`、审计事件类型表等）在 fg 以 deferred 字节区间
  （CONS 偏移）注册时 const_map 结构匹配失败，旧 fallback `idx0-nfuncs+1` 越界
  （kernel 6 文件 PUSH_G ≥ nsyms，CAD 会 0xC0000005）。修复：未命中统一按
  符号槽末尾编址（操作数 = nsyms-1-offset，cache_cad.fas 实测）。kernel 67/67
  verify 全绿。
- **quoted 数据内 `(function ...)` 非 kwote**（2026-08-17，@lisp_u @::install 崩溃根因）：
  引用上下文内（`'(... (function (lambda ...)) ...)`）`(function ...)` 是数据
  （FUNCTION 符号 + lambda 列表），非 kwote 调用。parser 的 `parse_form` FUNCTION
  分支与 `parse_list` 的 `(function X)` 分支均需 `kwote=(not quoted)`，否则
  `to_const` 失败 → quoted 数据退化为 BUILD_LIST 逐元素构建。
- **kwote lambda `/ 局部变量` locals 常量需收集**（2026-08-17）：codegen
  `_emit_al_bind_alist_locals` 会 `add_constant((quote (locals...)))`，collector
  `_collect_byteorder` 的 kwote 分支也须收集（`@lisp_u (lambda (line / pos) ...)`
  的 `(quote (pos))` 常量），否则 symtab 在 codegen 阶段插入新常量导致后续
  符号索引漂移到 nsyms 外 → `_patch_usubr_idx` const_map 找不到 → PUSH_G 越界。
- **不在 fg 表的符号 PUSH_G 越界**（2026-08-17）：quoted 数据里的特殊形式
  （`setq`/`if`/`lambda` 等）逐元素构建时，codegen 用 symtab 索引，`_patch_usubr_idx`
  的 SYMBOL 分支对不在 `gvar_map` 的符号此前 `new_idx=None`（原样保留越界索引）。
  现 fallback 到资源 symbol_slots（`_res_slot_of`），无效则符号槽末尾
  （gvar 槽 = nsyms，操作数 = nsyms-1），消除 0xC0000005。
- **模块区 T 槽全局唯一**（2026-08-17，@lisp_u 对拍）：模块区所有 cond else 键
  `t`、值位置 `T`、孤立顶层 `T` 共享**一个** T 槽，位置由 **forward 序第一个
  引用 T 的 form**（force t 或值位置 t 均可）决定（tcond5 实测：孤立 `T` 在
  userinfo 之前 → T 槽在 userinfo 符号之后、函数名之前）。`_register_module`
  的 `_t_form` 记录该 form，仅它在 `_t_reg_idx`/值位置注册 T，其余 form 跳过。
  此前逐 form 独立注册 T 会多出 5 个 T 槽（@lisp_u OURS 7 vs CAD 2）。
- **含 `.` 的符号名截断**（2026-08-17）：CAD 词法级把含 `.` 的符号名截断到
  第一个 `.`（`x.y`→`X`、`:package.install`→`:PACKAGE`、`fun::e.g`→`fun::e`、
  `(defun foo.bar ...)` 定义 `foo`）。独立的 `.` token（dotted pair `(a . b)`）
  不受影响。lexer SYMBOL 分支对含 `.` 的值 `split('.',1)[0]`。
- **foreach 循环变量独立注册**（2026-08-17）：foreach 变量即使与共享参数同名
  （`@lisp_u` 的 `cmd` 同时是 `@::cmd2str` 等函数参数）也独立注册符号槽
  （CAD 模块区 510 CMD + 函数体区共享参数槽并存）。`_collect_byteorder` 的
  ForeachNode 分支对 var 绕过 `self.shared` 排除。
- **config 顶层调用的 REAL 默认值槽**（2026-08-17）：`(@::define-config-typed
  '@::x 2.5 "desc" '(range 0.1 100))` 的默认值 REAL `2.5` 需注册 REAL 槽
  （CAD slot 67）。`_form_read_target` 此前缺 Real 分支，REAL 默认值无归属
  → `_register_module` 跳过 → slot 错位。
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
- **`if` 语句上下文 else 分支末尾 POP**（2026-08-19，large_synthetic 实测）：
  语句上下文（值被丢弃）的裸语句 `if`，else 分支末尾同样发 `POP` 丢弃分支值
  （CAD lgf-000..119 实测 else `USUBR; POP`），与 then 分支对称；else 为
  setq 时 SETQ_G 已消费栈顶无需 POP，progn/if/循环由其自身管理栈。此前
  codegen 只处理 then 分支 POP，else 分支缺 `0a` → 每函数 1 字节 diff。
  修复：`_emit_if` else 分支加与 then 相同的 `_in_stmt_ctx` 排除列表判断。
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
  2026-08-16 登记，**2026-08-23 已修复**）：`unschedule-task` 的 `(function
  (lambda (task-item) (= (car task-item) name)))` 捕获外层函数参数 `name` 时，
  CAD 会把 kwote lambda 参数 `task-item` 注册为符号槽（scheduler golden slot
  77 `TASK-ITEM`，kwote 块 `kwote = CAR TASK-ITEM`），而 `_collect_byteorder`
  的 kwote 分支此前用 `arg_names | lambda_args` 排除 lambda 参数 → OURS nsyms
  少 1（72 vs 73）、后续槽偏移、`-lambda-` 运行时绑定报 `要绑定的对象不正确:
  #<SUBR -lambda->`。
  **修复**（2026-08-23，06_higher_order 全新 CAD golden 对拍确认）：
  kwote lambda **参数统一注册符号槽 + `-lambda-` 体 PUSH_VALUE 读取**（非
  GET_LOCAL）。CAD 实测 i18n 的 `opt%`、06_higher_order 的 `n` 均注册 fg 槽
  并经 `_patch_usubr_idx` 按 `gvar_slot(arg)-1` 编址。改动：`cad_symbols.py`
  `_collect_byteorder` kwote 分支体收集改 `arg_names`（lambda 参数照常收集，
  外层函数参数仍由 `arg_names` 排除）；`codegen.py` `_emit_nested_lambda`
  参数读取去掉 GET_LOCAL 分支、走 `get_or_add` + PUSH_VALUE。旧 t20_kwote
  真机"GET_LOCAL 才能运行"结论被新 golden 否定。i18n seg0+nsyms 现与
  `tests/cad/i18n-cad.fas` 逐字节一致（seg1 模块代码仍有 48 项 pre-existing
  diff，见下）。
- **`(setq lst '(a b c))` 表外 SETQ_G 目标错槽**（2026-08-23，05_lists 全新
  CAD golden 对拍）：纯函数文件（无顶层表达式）函数体符号不在 fg 表时
  （`lst` symslot[16] ≥ nsyms 11），`_patch_usubr_idx` 误走 `module_reg_count`
  减法分支（`_body_slot = 16 - 7 - 1 = 8` → 操作数 7，CAD 用 nsyms-1 = 10）。
  `module_reg_count` 减法仅适用于**混合文件**（defun+顶层）里同时注册于模块区
  与函数体区的顶层变量（net/probe）。修复：该分支加 `has_top_forms` 守卫。
 - **i18n 混合模式 seg1 模块代码残余 diff**（2026-08-23 登记）：`tests/cad/
   i18n-cad.fas` 对拍中 seg0+nsyms 已逐字节一致，seg1 模块代码仍有 48 个
   contiguous resource_items diff（item 236 起，CAD 多一条 `JUMP32 0; PUSH_G
   37; SETQ_G 22; PUSH_G 22; POP` 顶层语句），与 kwote lambda 编址无关（i18n
   的 kwote 在 defun 内）。`test_i18n_original_byte_identity` 保持 skip。
- **`(let ...)` 降级为 lambda-apply**（2026-08-23，`_lower_let`）：CAD 对
  `(let ((v e)...) body)` 用「EVAL 引用 lambda + 实参」编译（fg 有 LET 符号槽，
  event-bus `(let ((entry ...)) ...)` 实测 `... USUBR; EVAL 0, const`）；我们此前
  把它当普通 Call 编译（`(let bindings body)` → USUBR let，运行时
  "no function: LET"，解译产物 `(let (list ...) ...)` 可见绑定被破坏）。
  `_lower_let` 在 `_lower_immediate_lambda` 之前把 let 改写为
  `((lambda (v...) body...) e...)`，再由后者转为 `(apply '(lambda ...)
  (list args))`（成熟引用常量路径）。功能正确；byte-identity 需实现 CAD EVAL
  模式（4 个 let 文件：event-bus/error-handler/error-safe-eval/condition-nlp）。
- **`(if cond nil)` 语句上下文省略 then 代码**（2026-08-23，init/steps 恢复）：
  `_emit_if` 语句上下文（`_in_stmt_ctx=True`）且 then/else 为常量 `nil`/`T` 时
  （init/steps `(if (vl-catch-all-error-p ...) nil)` 语句）：分支值被 POP 丢弃，
  push+pop 是纯 no-op——CAD 省略整个分支代码（实测 `JMP32_IFNOT; JUMP 0` 无
  `01 0a`）。init/steps seg0 由 1262→1260 与 CAD 长度对齐（余 1 字节符号槽序
  diff）。值上下文（分支值被使用）不省略。
- **表外符号/字符串 `_res_offset` 编址**（2026-08-23，init/steps/config-migrate/
  config-sync-config byte-identical，29/67）：`_patch_usubr_idx` 对**纯函数文件**
  （无顶层表达式）不在 fg GVARINIT 表的符号/字符串（资源 symbol_slots 索引
  ≥ nsyms），旧 fallback `nsyms-1` 错槽（init/steps `"flag-nomnl"`
  symbol_slots[113] fallback 111，CAD 操作数 106）。修复：按
  `fg_slot = _rslot - _res_offset` 编址（`_res_offset` = 末 fg 符号的
  `_res_slot_of - fg 槽`，init/steps FINDFILE 112-106=6、config/migrate
  STRCAT 偏移 12），操作数 = fg_slot - 1。STRENGTH：net/probe 的
  `module_reg_count` 减法仍限混合文件。
- **参数绑定/读取表外符号编址**（2026-08-23，scheduler/ui-hotkey byte-identical，
  30/67）：`gvar_slot_res` 把 `gvar_slot` 未命中的参数按 `_res_offset` 编址
  （scheduler `name` symbol_slots[93] - 23 = fg 70 → 操作数 69，CAD 实测；旧
  fallback nsyms-1=72 错槽）。`_res_offset` 定位的槽视为命中（返回 True），
  调用方不再减 offset（06_higher_order `lst` 13-1=12 实测）。同时 `module_reg_count`
  减法（顶层变量 net/probe 专用）加 `count(str)>1` 守卫：仅符号**双注册**
  （模块区 + 函数体区）时适用，纯函数体符号（scheduler kwote lambda 捕获外层
  参数 `name` 单注册）走 `_res_offset`。**已知 tradeoff**：count 守卫使
  command.lsp 的 `@::BROWSER`（函数符号作值推送，单注册）落到 `_res_offset`
  分支错 1 槽（seg0 1 字节 diff，30/67 从 29 中 -1 但仍净 +1）。
- **混合命令文件模块代码**（2026-08-23，config/migrate byte-identical）：
  `C:@PROFILE` 与普通函数并存（无顶层表达式）时，CAD 模块注册共享 5b 块 +
  `56 vl-ACAD-defun` 插在源码首个命令之前（非纯命令的每函数独立 5b 块）；
  模块代码仅命令函数用 `PUSH_G c; USUBR(1,<vl槽>); NIL; PUSH_NIL; POP;
  PUSH_G c`，普通函数用 plain `PUSH_G c; POP`（新 `build_mixed_command_module_code`；
  vl 槽 = 首个命令 symtab 槽 + 1）。纯命令文件（全函数 c:）仍走
  `build_command_module_code`（t14_command 不变）。
- **cond 语句上下文自平衡 + t-else 死代码 PUSH_NIL 省略**（2026-08-23，
  cl-macros byte-identical，26/67）：`_emit_cond_stub` 的末动作在**语句上下文**
  （`_in_stmt_ctx=True`，while 体内 cond，cl-macros `@::macro-subst` 实测 t 子句
  `USUBR; SETQ_G` 无 `0b`/`0a`）按语句发射（setq 由 SETQ_G 消费、调用补 POP）——
  cond 自平衡、外层不再 POP；值上下文（尾/模块代码/`(setq x (cond ...))` RHS，
  platform 顶层 cond `(setq is-gcad T)` 实测 `PUSH_G T; DUP; SETQ_G`）仍表达式
  发射（DUP 保留值）。同时：**末子句为 `(t ...)` else** 且语句上下文时省略死
  代码 `PUSH_NIL` 默认值（t 恒真 fall-through 不可达，CAD 实测 `COND_OR; JUMP`
  无 `01`）；模块代码顶层 cond 仍保留。`Cond` 加入 while/if/progn/generate_function
  的"自平衡"跳过列表（cond 不再留值）。
- **非尾 progn 末 form if 的值上下文 POP**（2026-08-23，@lisp-env 恢复）：
  `_emit_progn` 非尾时末 form 为 if（模块代码 `_in_stmt_ctx=False`，@lisp-env
  `(progn (setq ...) (if ...))` CAD 实测 `JUMP 1; PUSH_NIL; POP`）留 then/假路径
  值 → 追加 POP；if 在语句上下文自平衡（内部 POP/无假路径 PUSH_NIL）不 POP。
  这使非尾 progn 真正自平衡，`_emit_stmts` 对 progn/while/foreach/repeat 跳过
  POP 才安全（cl-macros 顶层 progn 语句、@lisp-env mid progn 均无外层 `0a`）。
- **模块注册尾 `PUSH_G c; POP` 的 gating**（2026-08-23，cl-macros/net/proxy
  byte-identical）：`_build_cad_module_code` 的非命令 TAIL 注册 `PUSH_G c; POP`
  no-op 仅当 `post_forms or (i < n_funcs-1 and (post_forms or n_pre>0 or
  not _last_global_progn))` 时发射。**末全局是 Progn**（顶层 `(progn ...)` 展开
  后 defun 提升、剩余表达式包回 Progn，cl-macros/cl-functions/init/compat 实测）
  且无 post、n_pre=0 时纯尾部注册省略 no-op，每组仅 `JUMP; PUSH_G b; SETQ_G c`
  （cl-macros golden 实测）；直接 setq/call 末全局（net/proxy/ax-request）
  和 post/n_pre>0（platform/event-bus）仍保留 15 字节模式。
- **cond 空体子句不发入口 POP**（init/sequence，2026-08-16）：`(cond (x) ...)`
   空体子句（无动作）CAD 不发 `POP` 弹测试值（测试值留栈顶作 cond 结果，
   init/sequence 的 `(@::*bootstrap-state*)` 实测无 `0a`）。`_emit_cond_stub`
  对空体分支跳过 `POP`。语句上下文多对 setq 不 DUP（cond 子句体 if-then 中间
  多对 setq CAD `SETQ_G` 无 `0b`，见 codegen `_emit_setq`）。init/sequence.fas
  重新编译后 CAD 加载 + 函数可解析 OK。
- **2026-08-21 增补 4（net/wget 分析）**：纯顶层 `(set '@::wget (lambda ...))`
  文件修复多类问题（模块区、`-lambda-` 第二区、command/字符串），net/wget 暂
  留 DIFF（null 尾调用歧义），其余 21 文件保持 byte-identical：
  1. **纯顶层 lambda 体不进模块注册段**（`_register_module` `_skip_lam_bodies`）：
     仅**纯顶层**（无 defun，`_has_top_lam and not defuns`）跳过 setq-lambda 体；
     混合文件（platform）体符号照常入模块区。`_has_top_lam` 检测需识别裸
     LambdaNode（`_is_top_lam`，net/wget `(set '@::wget (lambda ...))` 的 arg1
     是裸 LambdaNode 非 kwote QuotedExpr）。
  2. **`-lambda-` 体符号**：`/ locals` 照常注册为体符号（`_lam_real_params` 只
     跳过 `/` 前真参数）；注入 `_al-bind-alist` + `(quote (locals...))` 常量。
     `_top_lambda_body_syms`（cli.py）同步——`/` 后 locals、`_al-bind-alist`、
     const 计入 `1 + len(_top_lambda_body_syms)`（net/wget nsyms=31）。
  3. **`command` 收集序**：`(command a b ...)` 每参数独立 `FUNC 1 ads-cmd`，
     `_collect_byteorder` args[0] 后立即收 `ads-cmd`（逆序注册得
     `其余, ads-cmd, shell`）；codegen `command` 本身**不**注册 COMMAND 槽
     （仅 ads-cmd，`get_or_add(name)` 前特判）。
  4. **`ads-cmd` 0x56 块**：`ads-cmd` 同 `_al-bind-alist`/`kwote` 保留大小写、
     独立 `56` 单符号块（resource_builder 模块区/函数体区/`-lambda-` 第二区）。
  5. **第二区连续 STRING 合并**：`-lambda-` 第二区连续字符串合并为单个 `55`
     块（与符号区一致）。
  6. **`module_func_names` 过滤仅纯顶层**：`-lambda-` key 只在 `_only_lambda_keys`
     （全部 func_offsets 都是 `-lambda-`，纯顶层）时从模块函数名排除——混合
     文件（platform 有真实 defun 名 + `-lambda-`）排除会使 module_entries 少
     2、函数体段错位（GET-LOCALE 泄漏到 fg[2]）。
  7. **net/wget 尾调用歧义（未决）**：`_tail_call` 提取 pop-logic（兼容
     setq-lambda 的 strcat）vs last-form-based（net/wget 的 null 非尾值）冲突。
     setq-lambda（锁定测试）需 pop-logic，net/wget 需 last-form——保留 pop-logic，
     net/wget 的 `null` 被误当尾调用、从体符号剔除 → 暂 DIFF。待更细的
     "尾调用 = 最后 body form 的值（setq 值/末表达式）"语义判定。
- **2026-08-21 增补 5**：新增 sub-system/condition/cn-commands 一个 byte-identical
  （22/67），关键修复：
  1. **`_strip_list_markers` dotted 引用归一化**（cn-commands `'((:vlr-unknownCommand
     . parse-cmdunknown))`）：symtab 常量 `('LIST', (a, b), True)`（dotted）→ fg
     表的 `('CONS', a, b)`（build_mvar_tables `0x2A`），否则 const_map 失配 →
     PUSH_G 落 nsyms-1。`_strip_list_markers` 新增 len==3 dotted LIST 分支。
  2. **`_patch_usubr_idx` 顶层变量函数体引用编址**（`module_reg_count` 参数）：
     顶层 `(setq @::*x* ...)` 变量同时注册于模块区（低位）与函数体区（高位
     ≥ nsyms），函数体 PUSH_VALUE 引用用**函数体区槽** = 资源槽 - 模块注册数
     - 1（fg[0] 代码引用占位：net/probe `@::*network-failure-count*`
     res[108] - 11 - 1 = fg[96]，operand 95）。旧 fallback `nsyms-1` 偏移 2
     （build_mvar_tables 未把该符号放入 fg 表）。net/probe 其余 167 处 diff
     为 `/ 局部变量`（cached 等）在函数体组的槽位排序问题，暂留 DIFF。
- **2026-08-21 增补 6（sub-system/command 分析）**：`defpackage`/`in-package`
  模块注册段修复（res diff 2810→433），command 暂留 DIFF（kwote lambda
  `_al-bind-alist`/const 排序与 net/proxy 冲突）：
  1. **`defpackage` 关键字符号**（`_register_module`）：CAD 模块注册 =
     `DEFPACKAGE + :EXPORT + 逆序 export + :USE + use 包 + 包名`（command
     实测 `DEFPACKAGE :EXPORT :@DIAG :@AI :@@ ... :@@W :USE :CL :C`）。
     旧实现只登记 name/use/export 漏 `defpackage`/`:export`/`:use` → 后续
     export 符号槽位错位。`_owner_of` 需能查到这些关键字（加入 reads）。
  2. **kwote lambda `_al-bind-alist` 排序冲突（未决）**：command `@::F`
     （kwote lambda `/ req resp boot` 嵌套在 `/ ok req` 函数内）CAD 实测
     `const(req resp boot), VL-LOAD-COM, _al-bind-alist, const(ok req)`，
     net/proxy（kwote lambda locals == 函数 locals）需 kwote 分支早注册
     `_al-bind-alist`。两者冲突——去掉 kwote 分支 `_al-bind-alist` 破 net/
     proxy，保留则 command 的 `_al-bind-alist` 提前到 VL-LOAD-COM 之前。
     需"kwote lambda locals 与函数 locals 相同时才早注册"语义判定。
- **2026-08-21 增补 7（sub-system/command byte-identical，23/67）**：
  `_al-bind-alist` 排序冲突解决 + defpackage 模块代码发射，command **seg0+nsyms+seg1
  完全一致**（与 net/proxy 一样 byte-identical）：
  1. **`_al-bind-alist` 条件早注册**（`cad_symbols.py` `_collect_byteorder`）：
     kwote lambda locals **== 外层函数 locals**（net/proxy）时 kwote 分支早注册
     `_al-bind-alist`；kwote lambda locals ≠ 函数 locals（command `@::F`
     `/ req resp boot` ≠ `/ ok req`）时不早注册（`_al-bind-alist` 由外层
     函数 locals 统一注册）。`cur_locals` 经 `_collect_byteorder` 新参数传入，
     多函数路径（defun 体调用）传 `set(f.locals)`，递归调用经
     `self._cur_locals` 持久（`cur_locals=None` 时读取）。
  2. **Defpackage 模块代码**（`cli.py` `_stmt_bytes` + `other_forms` 纳入 +
     `_collect_symbol_nodes` 分支）：`(defpackage :C (:use :cl) (:export ...))`
     编译为 `PUSH_VALUE :C; PUSH_VALUE :CL; USUBR 1, :USE; PUSH_VALUE <exports
     正序>; USUBR <n>, :EXPORT; USUBR 3, DEFPACKAGE`——各子调用结果留在栈上
     **内部无** `NIL; PUSH_VALUE 0` 清理，仅 `_emit_stmts` 语句末尾 POP（CAD
     command 实测 raw `03 26 00 03 25 00 35 01 24 00 03 03 23 00 ... 35 0d 16
     00 03 35 03 15 00 03 0a`）。`defpackage`/`:use`/`:export`/包名/use 包/
     export 符号经 `_collect_symbol_nodes` Defpackage 分支注册。
  3. **InPackage 包名用 `form.name`**（原硬编码 `:@`，command `(in-package :C)`
     错发 `:@`）。
  4. **`n_globals` 含 Defpackage**（`_n_globals` 只排除 Defun；`_n_pre` 只计
     Defun 不计 Defpackage）——defpackage/in-package 进 globals 组、排函数注册
     JUMP 之前（CAD 实测在函数注册前）。`top_level_code` 循环（seg0）跳过
     Defpackage（与 InPackage 同，由 `_build_cad_module_code` 发射）。
  5. **末命令函数注册**（`_reg` rest 循环）：命令注册 `PUSH_G c; USUBR; POP;
     PUSH_G c` 对**末尾**命令也发射（CAD 实测末函数 C:@DIAG 有 vl-ACAD-defun
     USUBR），但末尾命令不再跟 `0a` POP（END_DEFUN 前 CAD 实测 `... 09 01 00
     35 01 12 00 01 0a 09 01 00 16`）；`_last_reg_cmd` 标志使尾部 `PUSH_G 1`
     不重复（命令块已留 `PUSH_G c`）。
  compat.lsp（另一 defpackage 文件）仍 DIFF（`#-sbcl` 条件符号、use-package、
  Progn 等复杂顶层形式未对齐），非本次引入的回归。
- **2026-08-21 增补 8（net/probe 分析，seg0 diff 167→9）**：net/probe 仍 DIFF
  （双 kwote 块序残余），但 `_local_is_param` 语义已修复、其余 23 文件不受影响：
  1. **局部变量同时是其它函数参数**（net/probe `cached` = internetp 的
     `/ cached` 局部 + check-cached-online 的参数）：CAD 把该槽注册在参数函数
     args 循环（fg[75]），不在声明它的函数（internetp）函数体组（fg[5]）。
     `_collect_multi` 新增 `_local_is_param` 集合，函数体组收集循环与 locals
     循环都跳过它，由参数函数 args 循环注册（该参数经 arg_names 排除、不参与
     body 收集）。net/cache `result` 仅是局部（非参数）不受影响。
  2. **kwote 调用者跳过嵌套 kwote 块**（`_kwote_blocks` 调用者检测）：多 kwote
     时前一 kwote 的调用者在后续 kwote 块之后（probe-network-uris 双 kwote
     实测 kwote1 调用者 = `@::network-circuit-trip`，在 kwote2 块之后；不跳过
     则误判为 `kwote` 标记）。net/proxy 单 kwote 不受影响。
  3. **net/probe 残余 DIFF（未决）**：probe-network-uris 双 kwote（两 lambda
     均由 vl-catch-all-apply 调用、调用者同为 @::network-circuit-trip）的 kwote
     块序。CAD 实测 `[OFFLINE, kwote, @::EVENT-EMIT, NETWORK-STATUS-CHANGED]`
     （kwote2 的 body OFFLINE 在 kwote 前、kwote2 块在 kwote1 块前）；OURS 为
     `[kwote, @::EVENT-EMIT, NETWORK-STATUS-CHANGED, OFFLINE]`（reversed 插入
     kwote1 在前、kwote 在 body 前）。待"双 kwote 同调用者时块序/体内符号序"
     语义判定。
- **2026-08-21 增补 9（net/probe byte-identical，24/67）**：双 kwote 同调用者
  块序 + 字符串/符号名冲突修复，net/probe **seg0+nsyms+seg1 完全一致**：
  1. **多 kwote 同调用者链式插入**（`cad_symbols.py`）：≥2 kwote 块且调用者全
     相同时，合并为「逆序块体 + kwote」链（每块 `[body_rev, kwote]` 按块逆序
     拼接，kwote 去重）插入调用者后。probe-network-uris 双 kwote 实测
     `[OFFLINE, kwote, @::EVENT-EMIT, NETWORK-STATUS-CHANGED]` = reversed
     (`[kwote, NETWORK-STATUS-CHANGED, @::EVENT-EMIT, kwote, OFFLINE]`)。
     单 kwote（net/proxy/cache/reload）保持 `[kwote, body_rev]`。
  2. **STRING 与同名符号冲突**（`cli.py` `_patch_usubr_idx` `multi` 路径）：
     `"OFFLINE"` 字符串若与符号 `OFFLINE` 同名，`sym_of` 返回字符串值后经
     `gvar_map`（符号优先）映射到**符号槽**（fg[11] → 操作数 10），CAD 用
     **字符串槽**（fg[9] → 操作数 8）。修复：`multi` 路径先判 STRING 条目，
     走 `str_map`（大小写敏感）；表外字符串落回原 STRING 分支。
- **2026-08-21 增补 10（_local_is_param 顺序感知）**：局部同时是其它函数参数
  时，槽注册在**后处理**的拥有者处（net/probe `cached` = internetp 局部 +
  check-cached-online 参数，参数拥有者 reversed idx 2 > 局部 idx 0 → 参数 args
  循环注册 fg[75]；cmd.lsp `pkg-name` = C:@DEP/C:@R 局部 + @::package-remove
  参数，局部拥有者 reversed idx 1 > 参数 idx 0 → 局部函数体组注册 fg[75]）。
  `_local_is_param_order` 判定：`local`（局部拥有者后处理）时函数体组/局部循环
  不跳过、参数 args 循环跳过；`param`（参数拥有者后处理）时函数体组/局部循环
  跳过、参数 args 循环注册。先处理者若抢先 add 会占用低位槽（`_name_set` 去重）。
  net/probe 保持 byte-identical，cmd.lsp seg0 diff 70→12（kwote 块序残余）。
- **2026-08-21 增补 11（cmd.lsp byte-identical，25/67）**：`(function 符号)`
  kwote + 多 kwote 不同调用者 marker 位置 + DEFCODE module 参数编址，cmd.lsp
  **seg0+nsyms+seg1 完全一致**（command 同步恢复）：
  1. **`(function 符号)` 不生成 kwote 标记**（`_collect_byteorder`）：`(function
     car)`/`(function @::pkg-fas-file)`（cmd.lsp line 37/54 实测）CAD **不**生成
     `kwote` 块——符号本身作为普通 SUBR 槽注册（CAD fg `@::*LOCAL-PKGS* CAR`
     无 marker）；仅 `(function (lambda ...))` 生成 `kwote`/`__kwote_end__`。
     原实现无条件生成 kwote 标记，功能符号 kwote 块多占 marker 槽位。
  2. **多 kwote 不同调用者：只给源码序第一个 lambda kwote 插 marker**
     （`_collect_multi` else 分支）：cmd.lsp @::package-remove 的 kwote3
     （vl-catch-all-apply）/kwote4（config-sync-packages-push）不同调用者，
     CAD 的 kwote 槽在**源码序第一个** lambda kwote 块（fg[21]=kwote3 marker
     位置，kwote4 块 body 无 marker）。`_first_block = _kwote_blocks[0]`，仅该
     块 `_pre=[_kw]`，其余块只插 body。net/proxy 的 proxy 函数 kwote 块被
     跨函数 seen_refs 去重（kept 无 kwote）不在此。
  3. **DEFCODE module 参数符号编址**（`_patch_usubr_idx` USUBR/FUNC elif）：
     cmd.lsp C:@U 的 `@::upgrade`、command 的 `@::internetp` 等被 DEFCODE 消费
     （`0x33`=PUSH_INT32 压 offset、`0x3A`=DEFCODE 消费 name/start/module），
     build_mvar_tables 解析为 None、gvar_map 查不到。符号实际 gvar 槽 =
     `_res_slot_of - _res_offset`（`_res_offset` = gvar_map 中 **fg 槽最大**
     符号的 `_res_slot_of - gvar` 差，cmd.lsp @::UPGRADE slot104-10=fg94→操作数
     93、command @::internetp slot191-41=fg150→149）；**表内符号（_fg_slot <
     nsyms）不含 offset**（操作数 = _fg_slot-1）。模块区函数名（fg 低位）偏移
     小不可用。  net/proxy 等已通过文件表外符号仍走 `nsyms-1-offset`。
- **2026-08-21 增补 12（net/wget byte-identical，26/67）**：纯顶层 setq-lambda
  尾调用改 last-form 值判定 + SETQ_G 参数编址，net/wget **seg0+nsyms+seg1 完全
  一致**（null 尾调用歧义解决，AGENTS "待判定" 解除）：
  1. **`_lam_tail_value`（cad_symbols）**：纯顶层 `(set/setq 'sym (lambda ...))`
     的尾调用 = **最后一个 body form 的值**（setq 值/末表达式函数名）。简单
     符号（net/wget 末 form `outfile`）→ None（无尾调用）；`(strcat ...)` →
     strcat（fasext）；`(if ... (setq str-vlx (strcat ...)) str-vlx)` → then
     分支 setq 值 strcat（vlx）。旧 pop 策略把 net/wget 中间 `(if (null ...))`
     的条件 `null` 误当尾调用剔除 → nsyms 少 1。cli.py `_top_lambda_body_syms`
     收集（line 2482+）同步改用 `_lam_tail_value`。
  2. **SETQ_G 目标参数编址**（`_patch_usubr_idx` multi=False 分支）：纯顶层
     setq-lambda 参数（DEFCODE 第二区，gvar 槽 = nsyms 表外）SETQ_G 目标操作数
      = gvar_slot - 1（net/wget uri → 30、outfile → 29、extra-headers → 28；
      gvar_slot("URI")=(31,False) → 31-1-offset；与参数读取 PUSH_VALUE line 973
      同规则）。旧 `_rs - module_reg_count - 1`（33-3-1=29）算出 28 错。setq-lambda
      参数（str-vlx fg[9] 命中）结果相同（gvar-1），锁定测试不受影响。
- **2026-08-21 增补 13（sub-system/cache byte-identical，27/67）**：foreach
  变量槽注册 + quoted 数据 const 去重 + 尾 foreach 体末语句上下文，cache
  **seg0+nsyms+seg1 完全一致**（cmd.lsp 同步保持）：
  1. **foreach 变量与参数同名**（`cad_symbols.py`）：CAD 复用参数拥有者槽、
     foreach 处无独立槽。cache.lsp `subdir` = cache-store/cache-load/
     cache-invalidate 的**共享参数** + cache-clear-all 的 foreach 变量 → CAD
     共享 fg[46]（共享参数槽）。`_collect_byteorder` ForeachNode 分支加
     `_v not in self.shared` 排除（函数体 foreach）；@lisp_u `cmd`（模块区
     foreach + 共享参数）不同区仍独立注册。唯一参数（_unique_params 集合）
     仅加在 foreach 分支；Symbol/Setq 分支**不加**（会误剔 C:@DEP 的
     pkg-name → locals loop 不注册 → nsyms 少 1，cmd.lsp 回归）。
  2. **quoted 数据 const 去重**（`_collect_byteorder`）：`'("." "..")` 两处
     （member subdir / member f）只注册一个槽、位置在**正序第一次**出现
     （member 后）。逆序处理会保留 refs 最后一个，const 收集加 `_seen` 去重。
  3. **尾 foreach 体最后语句值上下文**（`codegen.py` `_emit_foreach_stub`）：
     尾 foreach（PUSH_NIL 占位 + POP 协议）体最后语句 = foreach 的"值"，if
     无 else 补 PUSH_NIL（cache.lsp 体末 `(if (and ...) (vl-file-delete ...))`
     CAD 实测 `JMP32_IFNOT; then; JUMP; PUSH_NIL`）。`_emit_stmt` 清
     `_in_tail_context` 使 if 按语句上下文（无 else 不补 nil、then POP），故
     尾 foreach 体最后语句走 `_emit_expr`（值上下文）。i18n 尾 foreach 体末
     调用（princ）值上下文效果相同。
- MCP CAD 连接不稳定，建议手动测试
