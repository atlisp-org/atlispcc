# Fas2Lsp 使用说明

Fas2Lsp 将 AutoCAD/BricsCAD 的 FAS4 加密字节码反编译为可读的 AutoLISP 源码。

**这不是完美的源码恢复工具**——FAS 格式不保留原始结构、变量名、注释和外部依赖。输出作为可编辑的起点，需人工复核后再使用。

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
```

需要 Python 3.8+，无需第三方依赖。

### Poetry 安装（推荐用于开发）

```sh
pip install poetry
poetry install
poetry run python fas4_decompiler.py bib.fas bib_generic.lsp
```

## 完整工作流

```sh
# 1. 反编译
python fas4_decompiler.py input.fas output.lsp

# 2. 验证语法
python validate.py output.lsp

# 3. 打开 CAD 测试
# 在 AutoCAD/BricsCAD 中：
(load "完整路径/output.lsp")
# 调用命令，例如：
POLYCC
```

## 验证输出

验证器检查：

- 括号平衡
- 所有顶层形式为 `defun`
- C: 命令函数无必需参数
- 符号名合法性
- 常见结构问题（if 参数不足、setq 参数非 2、空 progn 等）
- 无残留调试注释或逻辑占位符

```sh
python validate.py output.lsp              # 单文件
python validate.py output1.lsp output2.lsp  # 多文件
```

验证通过输出：`[PASS] <文件名>`。失败则列出每条错误。

## 在 CAD 中测试

```lisp
;; 加载反编译后的文件
(load "C:/projects/bib_generic.lsp")

;; 调用命令
POLYCC

;; 如果失败，收集以下信息：
;; - 调用的命令名
;; - CAD 的错误信息
;; - 错误附近的表达式
;; - 调用栈（如有）
```

## 完整示例

处理项目自带的两个样本文件：

```sh
# 反编译 + 验证
python fas4_decompiler.py bib.fas bib_generic.lsp
python validate.py bib_generic.lsp
python fas4_decompiler.py PDI.fas PDI_generic.lsp
python validate.py PDI_generic.lsp

# 简易包装版（带摘要统计）
python decompile.py bib.fas bib.lsp
```

## 工具脚本参考

### 分析工具

```sh
# FAS4 文件分析 — 识别格式、提取符号和函数目录
python fas-analyzer.py bib.fas

# 分析 + 十六进制 dump
python fas-analyzer.py bib.fas --dump

# 分析 + JSON 报告
python fas-analyzer.py bib.fas --json
```

### 函数分割

```sh
# 将多函数 FAS 拆为独立单函数 FAS 文件
python fas-split.py bib.fas

# 修剪模式（生成自包含单段 FAS，不含资源段）
python fas-split.py bib.fas --trim

# 指定输出目录
python fas-split.py bib.fas --outdir ./split_output
```

### 解密/破解

```sh
# 解密 FAS4 文件并提取资源流
python decrypt_fas4.py bib.fas

# 密钥暴力破解（用于未知密钥文件）
python crack_key.py encrypted.fas
```

### 输出对比

```sh
# 比较反编译输出与参考实现
python compare_lsp.py PDI_generic.lsp "PDI(test).lsp"
```

## BricsCAD 兼容性

反编译器自动加入包装函数以避免内建函数冲突：

- `fas-polar1` — 单参数 POLAR 调用包装
- `fas-rtos1` / `fas-rtos3` — Project 风格 RTOS 包装
- `fas-getvar2` / `fas-getvar3` — GETVAR 包装
- `fas-1-` — 安全的 1- 包装
- `in_param` / `fas-assoc-value` — 关联列表/DXF 组码查询
- `fas-select-entity` / `projet_pa_projet_ar_projet` — 缺失 Projet 框架的后备

BricsCAD 无法直接加载 AutoCAD 的 `.fas` 文件，因此本项目输出纯 `.lsp` 文本。

## 安全注意事项

- 始终在**测试图纸**中验证反编译输出的行为
- 部分解码命令可能创建、修改或删除图元
- 使用前审查输出中的可疑调用

## 限制

- 外部依赖（其他 `.fas`、`.vlx`、`.arx`、`.dcl`、`.odcl`、`.lsp`）不会自动打包
- 部分行为从字节码推断，非原始源码恢复
- 输出可能需要手动清理
