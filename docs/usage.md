# Fas2Lsp 使用说明

Fas2Lsp 将 AutoCAD/BricsCAD 的 FAS4 加密字节码反编译为可读的 AutoLISP 源码。

**这不是完美的源码恢复工具**——FAS 格式不保留原始结构、变量名、注释和外部依赖。输出作为可编辑的起点，需人工复核后再使用。

## atlispcc CLI

统一命令行工具 `atlispcc`（`compiler/cli.py`），支持四个子命令：

```
atlispcc compile [-O {0,1,2}] <input.lsp> [output.fas]
atlispcc decompile <input.fas> [output.lsp]
atlispcc validate <input.lsp>
atlispcc link [-o OUTPUT] <input.fas> <input.fas> [...]
```

### compile — 编译 Lisp → FAS

```sh
# 基本编译
atlispcc compile input.lsp output.fas

# 优化级别：0=无（默认），1=基本，2=激进
atlispcc compile -O2 input.lsp output.fas
```

-O1 优化：常量折叠、死分支消除、窥孔优化
-O2 优化：增加常量传播、死赋值消除，并重复执行基础优化

### decompile — 反编译 FAS → Lisp

```sh
atlispcc decompile input.fas output.lsp
# 或直接调用
python fas4_decompiler.py bib.fas bib_generic.lsp
```

### validate — 语法验证

```sh
# 单文件或多文件
atlispcc validate output.lsp
python validate.py output.lsp
```

验证器检查：括号平衡、顶层形式为 defun、C: 命令无必需参数、符号名合法性、
常见结构问题（if 参数不足、setq 参数为奇数、空 progn 等）、无残留调试注释。

验证通过输出：`[PASS] <文件名>`。失败则列出每条错误。

### link — 多文件链接

将多个 `.fas` 文件合并为一个，自动重排符号/函数索引并修复交叉引用：

```sh
atlispcc link lib1.fas lib2.fas main.fas -o combined.fas
```

至少需要 2 个输入文件。输出默认以最后一个输入为基础命名。

## 快速开始

```sh
# 反编译
python fas4_decompiler.py bib.fas bib_generic.lsp

# 验证语法
python validate.py bib_generic.lsp

# 期望输出： [PASS] bib_generic.lsp
```

## 安装

### 直接运行（无需安装）

```sh
python fas4_decompiler.py <input.fas> [output.lsp]
python compiler/cli.py compile <input.lsp> [output.fas]
```

需要 Python 3.8+，无需第三方依赖。

## 完整工作流

```sh
# 1. 编译 Lisp → FAS（带优化）
python compiler/cli.py compile -O2 source.lsp program.fas

# 2. 链接多个 FAS
python compiler/cli.py link lib.fas program.fas -o combined.fas

# 3. 反编译以验证
python fas4_decompiler.py combined.fas combined.lsp
python validate.py combined.lsp
```

## 在 CAD 中测试

```lisp
;; 加载反编译后的文件
(load "C:/projects/bib_generic.lsp")

;; 调用命令
POLYCC
```

## 完整示例

```sh
python fas4_decompiler.py bib.fas bib_generic.lsp
python validate.py bib_generic.lsp
python fas4_decompiler.py PDI.fas PDI_generic.lsp
python validate.py PDI_generic.lsp
```

## 工具脚本参考

### 分析工具

```sh
# FAS4 文件分析
python fas-analyzer.py bib.fas
python fas-analyzer.py bib.fas --dump
python fas-analyzer.py bib.fas --json
```

### 函数分割

```sh
python fas-split.py bib.fas
python fas-split.py bib.fas --trim
python fas-split.py bib.fas --outdir ./split_output
```

### 解密/破解

```sh
python decrypt_fas4.py bib.fas
python crack_key.py encrypted.fas
```

## BricsCAD 兼容性

反编译器自动加入包装函数以避免内建函数冲突：

- `fas-polar1` / `fas-rtos1` / `fas-rtos3`
- `fas-getvar2` / `fas-getvar3`
- `fas-1-`
- `in_param` / `fas-assoc-value`
- `fas-select-entity` / `projet_pa_projet_ar_projet`

BricsCAD 无法直接加载 AutoCAD 的 `.fas` 文件，因此本项目输出纯 `.lsp` 文本。

## 限制

- 外部依赖（其他 `.fas`、`.vlx`、`.arx`、`.dcl`、`.odcl`、`.lsp`）不会自动打包
- 部分行为从字节码推断，非原始源码恢复
- 输出可能需要手动清理
