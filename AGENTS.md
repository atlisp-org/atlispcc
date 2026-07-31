# Fas2Lsp - Agent 指南

## 项目

FAS4 字节码编译器/反编译器：`.lsp` ↔ `.fas`（兼容 AutoLISP 的 CAD 平台）。

`atlispcc` — 统一 CLI 工具（`compiler/cli.py`），支持四个子命令：

```
atlispcc compile [-O {0,1,2}] <input.lsp> [output.fas]    # 编译 Lisp → FAS
atlispcc decompile <input.fas> [output.lsp]                # 反编译 FAS → Lisp
atlispcc validate <input.lsp>                              # 语法验证
atlispcc link [-o OUTPUT] <input.fas> <input.fas> [...]    # 多文件链接
```

无子命令时默认为 compile：`atlispcc <input.lsp> [output.fas]`

`fas4_decompiler.py` 亦可直接调用：`python fas4_decompiler.py <input.fas> [output.lsp]`

## 编译器管线

```
Lisp 源码 → Parser.parse() → AST
         → SymbolTableBuilder.build() → SymbolTable
         → Codegen.generate() → List[FunctionDef]（指令流）
         → [OptPipeline.optimize()  # 可选：-O1/-O2]
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
| `fas4_decompiler.py` (2136 行) | 主反编译器：解析 + 反汇编 + 分析 + 生成 |
| `fas_core.py` (690 行) | 共享加密/解析/符号 — 被工具脚本使用，主反编译器通过 import 复用其 `find_key`/`decrypt_stream`/`build_mvar_tables`/`build_function_catalog` |
| `compiler/cli.py` | CLI 入口，子命令 dispatch |
| `compiler/parser.py` | Lisp 源码解析器 → AST |
| `compiler/ast.py` | AST 节点定义 |
| `compiler/symbol_table.py` | 符号表构建与作用域分析 |
| `compiler/codegen.py` | 字节码生成器（AST → 指令流） |
| `compiler/resource_builder.py` | 常量/符号/函数索引 → 资源段 |
| `compiler/fas_writer.py` | 指令流 → FAS4 二进制 |
| `compiler/opt.py` | 优化器：常量折叠、死分支消除、窥孔优化、常量传播、死赋值消除 |
| `validate.py` | 生成的 `.lsp` 语法验证器 |
| `server/` | 实验性 pygls LSP 服务器（较不成熟，独立代码路径） |

工具脚本（`decrypt_fas4.py`、`fas-split.py`、`fas-analyzer.py`、`crack_key.py` 等）使用 `fas_core.py` 中的函数。

## 优化器（compiler/opt.py）

| Pass | 作用 | 级别 |
|---|---|---|
| ConstantFold | `(+ 1 2)` → `3`, `(strcat "a" "b")` → `"ab"` | O1+ |
| DeadBranchElim | `(if T e1 e2)` → `e1`, `(while nil ...)` → `nil` | O1+ |
| PeepholeOpt | `(progn x)` → `x`, `(list)` → `nil` | O1+ |
| ConstantPropagate | `(setq x 3) (+ x 1)` → `(setq x 3) (+ 3 1)` | O2 |
| DeadAssignElim | 移除未使用的 `(setq x ...)` | O2 |

## 命令

```sh
# 编译 + 优化
atlispcc compile -O2 input.lsp output.fas

# 反编译
python fas4_decompiler.py bib.fas bib_generic.lsp

# 验证输出
python validate.py bib_generic.lsp

# 链接
atlispcc link lib.fas main.fas -o combined.fas
```

```sh
pip install -e ".[dev]"                 # 安装依赖 + dev 工具（开发模式）
python -m pytest                        # 运行测试
python -m py_compile fas4_decompiler.py # 快速语法检查
python -m py_compile compiler/opt.py
python -m build                         # 构建分发包
black .                                 # 格式化
mypy .                                  # 类型检查
```

## 测试

**测试文件在 `tests/` 目录下**（pytest 风格）：
- `test_parser.py` — AST 解析器（14 用例）
- `test_compile_decompile.py` — 编译-反编译往返（含 AutoCAD `fun.fas` 参考反编译回归）
- `test_compiler_output.py` — FAS 输出正确性（8 用例）
- `test_assembler.py` — 反汇编/汇编往返（4 用例）
- `test_linker.py` — 多文件链接（8 用例）

手动测试文件 `tests/test_*.lsp` 也在该目录。

## 兼容性

FAS4 输出格式与 AutoCAD 编译器一致：
- seg0 = 函数字节码（`<nsyms> $...`），seg1 = 资源段（常量/符号/函数索引）
- seg1 使用滚动 XOR 加密（`find_key`/`decrypt_stream`），尾部含密钥长度字节 + 密钥 + `;fas4 crunch` 标记
- 段分隔符为 `16 24 0d 0a`，`nsyms` 为符号槽数（资源注册顺序）
- seg1 资源流 = 模块头(`14 01 01 01 00`) + 代码引用 + 符号/字符串注册 + GVARINIT + DEFCODE + INIT_DONE + 模块代码；`seg1` 头 `items` = GVARINIT + INIT_DONE 计数
- 反编译回归参考：AutoCAD 产物 `tests/fun-cad.fas`（对应 `tests/fun.lsp`）

反编译器同时支持两种布局：
- **自包含格式**（`bib.fas`/`PDI.fas`）：seg0 含完整函数体 + END_DEFUN，函数目录来自 mvar 表重建
- **紧凑 stub 格式**（AutoCAD 编译器输出）：seg0 无 END_DEFUN，符号按资源注册顺序（`symbol_slots`）直接编址

生成器会发出包装辅助函数以避免内建冲突：
- `fas-polar1`、`fas-rtos1`、`fas-rtos3`、`fas-getvar2`、`fas-getvar3`
- 用于列表/关联列表/DXF 组码读取的 `IN_PARAM` 查找
- 缺少 `Projet/PA_Projet` 框架时的后备选择提示

解码器问题在 `fas4_decompiler.py` 中修复，永远不要修改生成的 `.lsp`。

## 文档

- `docs/development.md` — 架构详解、代码规范、调试指南
- `docs/usage.md` — 用户安装、编译/反编译工作流、工具参考
