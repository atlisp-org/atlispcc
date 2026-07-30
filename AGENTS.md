# Fas2Lsp - Agent 指南

## 项目

FAS4 字节码编译器/反编译器：`.lsp` ↔ `.fas` (AutoCAD/BricsCAD)。

## 主入口

`atlispcc` — 统一 CLI 工具（`compiler/cli.py`），支持三个子命令：

```
atlispcc compile <input.lsp> [output.fas]    # 编译 Lisp → FAS
atlispcc decompile <input.fas> [output.lsp]  # 反编译 FAS → Lisp
atlispcc validate <input.lsp>                # 语法验证
```

无子命令时默认为 compile：`atlispcc <input.lsp> [output.fas]`

`fas4_decompiler.py` 亦可直接调用：`python fas4_decompiler.py <input.fas> [output.lsp]`

## 架构管线

```
Fas4Parser.parse() → Disassembler.disassemble() → ControlFlowAnalyzer.find_functions() → LispGenerator.generate()
```

## 关键文件

| 文件 | 作用 |
|---|---|
| `fas4_decompiler.py` (2136 行) | 主反编译器：解析 + 反汇编 + 分析 + 生成 |
| `fas_core.py` (690 行) | 共享加密/解析/符号 — 被工具脚本使用，主反编译器通过 import 复用其 `find_key`/`decrypt_stream`/`build_mvar_tables`/`build_function_catalog` |
| `validate.py` | 生成的 `.lsp` 语法验证器 |
| `server/` | 实验性 pygls LSP 服务器（较不成熟，独立代码路径） |

工具脚本（`decrypt_fas4.py`、`fas-split.py`、`fas-analyzer.py`、`crack_key.py` 等）使用 `fas_core.py` 中的函数。

## 命令

```sh
# 反编译
python fas4_decompiler.py bib.fas bib_generic.lsp

# 验证输出
python validate.py bib_generic.lsp

# 预期验证输出：[PASS] <file>.lsp
```

```sh
# setuptools 管理的项目（PEP 621）
pip install -e ".[dev]"                 # 安装依赖 + dev 工具（开发模式）
atlispcc compile <input.lsp>             # 编译 Lisp → FAS
atlispcc decompile <input.fas>           # 反编译 FAS → Lisp
atlispcc validate <input.lsp>            # 语法验证
atlispcc <input.lsp>                     # 简写=编译
python -m pytest                        # 运行测试
python -m py_compile fas4_decompiler.py # 快速语法检查
python -m build                         # 构建分发包
black .                                 # 格式化
mypy .                                  # 类型检查
```

## 测试

**测试文件在 `tests/` 目录下**（pytest 风格）。已有 `test_parser.py`（14 用例）、`test_compile_decompile.py`（11 用例）。手动测试文件 `tests/test_*.lsp` 也在该目录。

## BricsCAD 兼容性

生成器会发出包装辅助函数以避免内建冲突：
- `fas-polar1`、`fas-rtos1`、`fas-rtos3`、`fas-getvar2`、`fas-getvar3`
- 用于列表/关联列表/DXF 组码读取的 `IN_PARAM` 查找
- 缺少 `Projet/PA_Projet` 框架时的后备选择提示

解码器问题在 `fas4_decompiler.py` 中修复，永远不要修改生成的 `.lsp`。手工修补输出可用于实验，但解码器级别的修复才是可重复的。

## Git 状态

空仓库 — 没有提交、没有远程、没有 CI。已有 `.gitignore` 和 `tests/` 目录。

## 文档

- `docs/development.md` — 架构详解、代码规范、调试指南
- `docs/usage.md` — 用户安装、反编译工作流、工具参考
