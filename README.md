# atlispcc — FAS4 字节码编译器 & 反编译器

`atlispcc` 是一个统一的 CLI 工具链，用于将 AutoLISP (`.lsp`) 编译为 FAS4 字节码 (`.fas`)，反编译 FAS4 回 Lisp，链接多个 FAS 文件，以及验证 Lisp 语法。

## CLI

```sh
atlispcc compile [-O {0,1,2,3}] <input.lsp> [output.fas]        # 编译
atlispcc decompile <input.fas> [output.lsp]                      # 反编译
atlispcc validate <input.lsp>                                     # 验证
atlispcc link [-o OUTPUT] <input.fas> <input.fas> [...]          # 链接 FAS
atlispcc build-vlx <input.fas>... -o output.vlx [--export ...]   # 构建 VLX 容器
```

无子命令时默认为 compile：`atlispcc <input.lsp> [output.fas]`

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
Fas4Parser.parse() → Disassembler.disassemble()
→ ControlFlowAnalyzer.find_functions() → LispGenerator.generate()
```

## 链接器管线

```
FAS A + FAS B + ... → 合并符号表/函数目录 → 重排索引 → 修复交叉引用 → 合并 FAS
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

## VLX 容器

`atlispcc build-vlx` 将 FAS 文件打包为 VLX 容器，支持独立命名空间：

```sh
atlispcc build-vlx app.fas lib.fas -o app.vlx --export main setup
```

- 自动生成 `_VLX` 元数据条目（含 `vl-doc-export` 调用）
- 加载 VLX 时 CAD 运行时创建隔离命名空间
- 仅导出的函数可被外部访问
- VLX 格式基于逆向工程，标记为实验性

## 优化级别

| 级别 | Pass 列表 | 说明 |
|-------|--------|------|
| `-O0` | 无 | 原始编译，不做优化 |
| `-O1` | ConstantFold, DeadBranchElim, Peephole | 基本清理：`(+ 1 2)` → `3`、`(if T e1 e2)` → `e1`、`(progn x)` → `x` |
| `-O2` | O1 + ConstantPropagate, DeadAssignElim | 激进优化：`(setq x 3) (+ x 1)` → `(+ 3 1)`、移除未使用的 `setq` |
| `-O3` | O2 + CrossFuncConstPropagate, DeadCodeElim, InlineSmallFuncs | 极致优化：内联单次调用函数、跨函数常量替换、删除 `exit`/`quit` 后的死代码 |

### 分析

使用 `--analyze` 配合任何 `-O` 级别查看编译统计：

```sh
atlispcc compile --analyze -O3 input.lsp output.fas
```

输出包含：
- 函数数、指令数、常量估算数
- 尾递归函数检测
- 每个函数的参数数、局部变量、调用关系
- 开启优化时输出优化前后对比

## 关键文件

| 文件 | 作用 |
|------|------|
| `fas4_decompiler.py` | 主反编译器：解析 + 反汇编 + 分析 + 生成 |
| `fas_core.py` | 共享加密/解析/符号工具函数 |
| `compiler/cli.py` | CLI 入口，子命令分发 |
| `compiler/parser.py` | Lisp 源码解析器 → AST |
| `compiler/ast.py` | AST 节点定义（含 Defpackage、InPackage） |
| `compiler/packages.py` | 包系统：PackageTable、名混淆/还原 |
| `compiler/symbol_table.py` | 符号表构建与作用域分析（含包解析） |
| `compiler/codegen.py` | 字节码生成器（AST → 指令流） |
| `compiler/resource_builder.py` | 常量/符号/函数索引 → 资源段 |
| `compiler/fas_writer.py` | 指令流 → FAS4 二进制 |
| `compiler/opt.py` | 优化器：8 个 pass 跨 O1-O3 级别 |
| `compiler/analyzer.py` | 编译分析与统计 |
| `compiler/linker.py` | 多文件 FAS 链接器 |
| `compiler/vlx_builder.py` | VLX 容器构建器 |
| `validate.py` | 生成的 `.lsp` 语法验证器 |

## 安装

```sh
pip install -e ".[dev]"      # 开发模式（含 dev 工具）
```

## 测试

```sh
python -m pytest              # 运行所有测试（82+ 用例）
python -m pytest tests/ -v   # 详细输出
```

测试文件在 `tests/` 目录：
- `test_parser.py` — AST 解析器（14 用例）
- `test_compile_decompile.py` — 编译-反编译往返（15 用例）
- `test_compiler_output.py` — FAS 输出正确性（8 用例）
- `test_assembler.py` — 反汇编/汇编往返（4 用例）
- `test_linker.py` — 多文件链接（8 用例）
- `test_optimizer.py` — 所有优化 pass（26 用例）
- `test_packages.py` — 包系统（4 用例）
- `test_vlx_builder.py` — VLX 容器（3 用例）

## 文档

- `docs/development.md` — 架构详解、代码规范、调试指南
- `docs/usage.md` — 用户安装、编译/反编译工作流、工具参考

## 安全

反编译生成的 `.lsp` 应先审查再使用。先在空白图形中测试。某些命令可能会创建、修改或删除图形实体。
