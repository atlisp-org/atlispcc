# atlispcc - Agent 指南

## 项目

**atlispcc** = **A**uto**L**ISP **C**ompiler **C**ollection，FAS4 字节码编译器套件：`.lsp` ↔ `.fas`（兼容 AutoLISP 的 CAD 平台）。

`atlispcc` — 统一 CLI 工具（`compiler/cli.py`），支持七个子命令：

```
atlispcc compile [-O {0,1,2,3}] <input.lsp> [output.fas]    # 编译 Lisp → FAS
atlispcc decompile <input.fas> [output.lsp]                # 反编译 FAS → Lisp
atlispcc disasm <input.fas> [output.lasm]                  # 反汇编 FAS → 字节码指令列表
atlispcc asm <input.lasm> [output.fas]                     # 汇编 .lasm → FAS
atlispcc validate <input.lsp>                              # 语法验证
atlispcc link [-o OUTPUT] <input.fas> <input.fas> [...]    # 多文件链接
atlispcc build-vlx <input.fas>... -o output.vlx [--export ...]  # VLX 容器
atlispcc zelx <input.lsp|input.fas> [output.zelx]          # ZWCAD ZELX（逆向 LispConverter）
```

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
| `decompiler/fas4_decompiler.py` (2540 行) | 主反编译器：解析 + 反汇编 + 分析 + 生成 |
| `core/fas_core.py` (707 行) | 共享加密/解析/符号 — 被工具脚本使用，主反编译器通过 import 复用其 `find_key`/`decrypt_stream`/`build_mvar_tables`/`build_function_catalog` |
| `compiler/cli.py` | CLI 入口，子命令 dispatch |
| `compiler/parser.py` | Lisp 源码解析器 → AST |
| `compiler/ast.py` | AST 节点定义 |
| `compiler/symbol_table.py` | 符号表构建与作用域分析 |
| `compiler/codegen.py` | 字节码生成器（AST → 指令流） |
| `compiler/resource_builder.py` | 常量/符号/函数索引 → 资源段 |
| `compiler/fas_writer.py` | 指令流 → FAS4 二进制 |
| `compiler/opt.py` | 优化器：8 个 pass 跨 O1-O3 级别 |
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

## 命令

```sh
# 编译 + 优化
atlispcc compile -O2 input.lsp output.fas

# 反编译
python -m decompiler.fas4_decompiler samples/bib.fas samples/bib_generic.lsp

# 验证输出
python -m tools.validate samples/bib_generic.lsp

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

## 测试

**测试文件在 `tests/` 目录下**（pytest 风格，共 167 用例）：
- `test_parser.py` — AST 解析器（19 用例）
- `test_lexer.py` — 词法分析（11 用例：转义、注释、UTF-8、dotted）
- `test_symbol_table.py` — 符号表/作用域（10 用例）
- `test_analyzer.py` — 编译分析/尾递归（9 用例）
- `test_cli.py` — CLI 路径（10 用例：compile/-O/--analyze/validate/link/vlx/dispatch）
- `test_compile_decompile.py` — 编译-反编译往返（29 用例，含 AutoCAD `fun-cad.fas` 参考反编译回归、复杂 LSP O2/O3 往返）
- `test_compiler_output.py` — FAS 输出正确性（12 用例）
- `test_optimizer.py` — 优化 pass（32 用例，含循环携带变量回归）
- `test_linker.py` — 多文件链接（10 用例，含重名冲突警告）
- `test_assembler.py` — 反汇编/汇编往返（5 用例）
- `test_disasm.py` — 反汇编健壮性（8 用例，含未处理操作码降级）
- `test_packages.py` — CL 风格包系统（4 用例）
- `test_vlx_builder.py` — VLX 容器（3 用例）
- `test_variadic_args.py` — &optional/&rest 编译（5 用例）

手动测试文件 `tests/test_*.lsp` 也在该目录。

## 兼容性

FAS4 输出格式与 AutoCAD 编译器一致：
- seg0 = 函数字节码（`<nsyms> $...`），seg1 = 资源段（常量/符号/函数索引）
- 紧凑 stub 格式 `total_size = len(seg0) + 1`（CAD 实测恒等：cross/m2/m3/multi/sh/lambda_test 六份产物；seg0 = `<nsyms> $` 后的纯字节码）；自包含格式 `total_size = len(seg0_payload)`。`FasWriter.write(..., compact=True)` 走前者（CLI/链接器/紧凑汇编）
- **汇编器（`asm/assembler.py`）同时支持两种布局**：`.lasm` 头部 `.format compact|selfcontained` + `.nsyms N` 指令；紧凑 stub 用 CAD 编码（USUBR/FUNC 3 字节、`PUSH_VALUE[0]` 单字节、CLEAR_ARGS `19 <argc> 00`）。`disasm → asm` 往返 seg0 逐字节一致，紧凑产物可在 CAD 加载执行。重复符号槽在 `.lasm` 中输出 `[idx]` 保证字节可逆
- 紧凑 stub 生成规则（与 CAD 逐字节一致）：中间 setq 无 POP、尾 setq 先 DUP、无 else 的 `if` 补 PUSH_NIL、有参函数末尾 `19 <argc> 00`（CLEAR_ARGS）
- seg1 使用滚动 XOR 加密（`find_key`/`decrypt_stream`），尾部含密钥长度字节 + 密钥 + `;fas4 crunch` 标记
- 段分隔符为 `16 24 0d 0a`，`nsyms` 为符号槽数（资源注册顺序）
- seg1 资源流 = 模块头(`14 01 01 01 00`) + 代码引用 + 符号/字符串注册 + GVARINIT + DEFCODE + INIT_DONE + 模块代码；`seg1` 头 `items` = GVARINIT + INIT_DONE 计数
- **符号名统一大写**（`ResourceBuilder._enc_sym`）：CAD 符号槽全大写（AutoLISP 大小写不敏感）；字符串字面量不变
- **顶层表达式**（defun 之外的 setq/set 等）编译进 seg1 **模块代码**（非 seg0）：模块代码 = `DEFUN头 + [顶层表达式] + [函数注册尾: JUMP + PUSH_G <模块注册+2>; SETQ_G 1; PUSH_G 1] + END_DEFUN`；gvar 槽 = 符号槽 + 1；简单 `setq 变量 "字符串"` → `PUSH_G 值+1; DUP; SETQ_G 变量+1`；顶部占位 `PUSH_G <模块注册符号数+1>; POP`；`FasWriter` 的代码引用长度 = `total_size`（`len(seg0) + 1`）
- **模块注册段**（混合 defun+顶层）：注册函数名 + 顶层表达式符号（连续 SYMBOL 合并 5b 块，遇 STRING 分块）；`nsyms = len(entries) - 模块注册符号数 + 1`；函数注册 GVARINIT st_init = nsyms；DEFCODE 后 GVARINIT var_pos = 模块注册符号数 + 2
- **符号槽顺序** = 按源码函数逆序，每函数内"字节码引用序"逆序收集函数体符号、参数紧跟其后；混合（defun+顶层）时顶层表达式符号排在函数体内建之前；递归函数名重复槽（`compiler/cad_symbols.py`）
- 多函数函数间分隔符 `16`（END_DEFUN；CLEAR_ARGS `19 <argc> 00` 已由 codegen 生成）；多函数代码引用末函数 end = total_size
- 反编译回归参考：AutoCAD 产物 `tests/fun-cad.fas`（对应 `tests/fun.lsp`）

反编译器同时支持两种布局：
- **自包含格式**（`samples/bib.fas`/`samples/PDI.fas`）：seg0 含完整函数体 + END_DEFUN，函数目录来自 mvar 表重建
- **紧凑 stub 格式**（AutoCAD 编译器输出）：seg0 无 END_DEFUN，符号按资源注册顺序（`symbol_slots`）直接编址

生成器会发出包装辅助函数以避免内建冲突：
- `fas-polar1`、`fas-rtos1`、`fas-rtos3`、`fas-getvar2`、`fas-getvar3`
- 用于列表/关联列表/DXF 组码读取的 `IN_PARAM` 查找
- 缺少 `Projet/PA_Projet` 框架时的后备选择提示

解码器问题在 `decompiler/fas4_decompiler.py` 中修复，永远不要修改生成的 `.lsp`。

## 文档

- `README.md` — 使用者文档（安装、CLI 用法、工作流、工具参考）
- `docs/lasm.md` — LASM 汇编语言参考（disasm/asm）
- `docs/development.md` — 架构详解、代码规范、调试指南
- `docs/development-plan.md` — 开发计划、已验证兼容性矩阵

## CAD 测试

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

### 已知限制

- 4+函数交叉引用：`build_module_code` PUSH_G 越界 → `count_resource_records` 修复后 `items` 计数正确，但模块代码布局仍需调整
- `i18n.lsp` 混合模式：defun+顶层表达式混杂，`cad_symbols.py` 需支持持续块规则
- lambda：`(mapcar '(lambda (x) ...) list)` 中 x 未正确局部化
- MCP CAD 连接不稳定，建议手动测试
