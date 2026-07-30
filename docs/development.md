# Fas2Lsp 开发说明

## 环境准备

```sh
# 安装 Poetry（如未安装）
pip install poetry

# 安装依赖
poetry install

# 激活虚拟环境
poetry shell

# 或直接通过 Poetry 运行
poetry run python fas4_decompiler.py ...
```

Python 版本要求：>= 3.8。当前虚拟环境使用 Python 3.10.11。

## 项目结构

```
fas4_decompiler.py   主反编译器（2136 行）— 解析 → 反汇编 → 分析 → 生成
fas_core.py          共享核心模块（690 行）— 加解密、解析、符号表重建
validate.py          LSP 语法验证器
decompile.py         简易包装入口（带统计输出）
decrypt_fas4.py      FAS4 解密工具
fas-split.py         函数分割器（将多函数 FAS 拆为单函数）
fas-analyzer.py      FAS4 分析器
crack_key.py         密钥暴力破解工具
server/              实验性 LSP 服务器（pygls），独立代码路径，不参与反编译管线
```

## 架构管线

反编译流程分四个阶段，**不可跳过**：

```
Fas4Parser.parse()           → Fas4File（含符号表、函数目录）
  → Disassembler.disassemble()  → List[Instruction]（字节码→指令列表）
  → ControlFlowAnalyzer.find_functions()  → List[FunctionDef]（指令→函数边界）
  → LispGenerator.generate()    → str（AutoLISP 源码）
```

### Fas4Parser

解析 FAS4 二进制文件：

1. 定位 `FAS4-FILE` 魔数标记，读取 payload 大小
2. 解析 nsyms（符号数）和字节码段（seg0）
3. 查找 XOR 密钥（通过 `;fas4 crunch` 标记向前定位）
4. 解密资源段（seg1）
5. 解析资源流提取符号、字符串、函数定义
6. 重建两个 GVar 表（resource_gvars / function_gvars）
7. 生成函数目录（名称 → 字节码偏移）

关键概念：

- **resource_gvars**：模块级别全局变量表（table 0）
- **function_gvars**：函数级别符号表（table 1），带 code_ref_bias 偏移
- **code_ref_bias**：某些 FAS 在 function_gvars 开头留空槽，代码操作数对此偏移

### Disassembler

将字节码流转换为 `Instruction` 对象列表：

- 每个指令由 (offset, opcode, name, operands, size) 组成
- 操作数格式通过 OPCODES 字典定义：`'2'`=2字节, `'s4'`=有符号4字节, `'u'`=USUBR 5字节, `'f'`=FUNC 6字节 等
- 未知操作码标记为 `UNK_{opcode:02x}`，size=1

**添加新操作码**：在 `Disassembler.OPCODES` 字典中增加条目即可，主解析逻辑自动适配。

### ControlFlowAnalyzer

从指令流中划分函数边界：

1. 优先使用 function_catalog（已知函数偏移）
2. 回退：通过 DEFUN 指令定位函数头
3. 再回退：通过 END_DEFUN / CLEAR_ARGS 定位
4. 函数之间的指令归入 `c:init`（初始化代码）
5. 尾部未归属指令归入 `c:init_tail`

每个 `FunctionDef` 包含：name、args、locals、body_start/end、instructions。

### LispGenerator

最复杂的模块，将指令转换为 AutoLISP 源码：

1. 分析每条指令，提取签名（参数/局部变量）
2. 从符号表推测函数名
3. 遍历指令，用栈式求值将字节码转为 Lisp 表达式
4. 结构重建：识别 `if`/`while`/`foreach` 控制流
5. 兼容性包装：
   - `fas-polar1`（1 参数 POLAR）
   - `fas-rtos1`/`fas-rtos3`（Project 风格 RTOS）
   - `fas-getvar2`/`fas-getvar3`（GETVAR 包装）
   - `IN_PARAM` 关联列表/DXF 读取
   - `Projet/PA_Projet` 后备选择提示
6. 后处理：清理死 setq、推断局部变量重命名、调整 C: 函数签名

#### _render_block 核心方法

主生成方法，逐条处理指令：

- **栈指令**（PUSH_*）：将值压栈
- **运算符**（FIX_ADD/CAR/CDR/NOT 等）：弹栈计算后压栈
- **调用指令**（USUBR/FUNC）：弹参数 → 解析函数名 → 生成 `(name args)`
- **POP**：弹出作为独立语句输出
- **分支指令**（BR_IF_TRUE/JMP16_IFNOT 等）：尝试检测 if/while/foreach 结构
  - `_detect_if`：识别 if-then-else 模式
  - `_detect_loop`：识别 while/foreach 模式
  - 无法识别则输出注释标记
- **SETQ_G/SET_LOCAL**：生成 `(setq var expr)`

### _repair_call_target

处理函数引用错位问题——某些 FAS 的调用索引指向错误符号，通过附近符号试探纠正：

- `_is_bad_builtin_arity` 检测参数数量不匹配的内建函数
- 在 ±12 范围内寻找符号作为替代（有已知 arity 的加权重）
- `_skip_literal_zero_arg_call` 特殊处理：丢弃指向提示字符串的 0 参数伪造调用

## 调试与验证

```sh
# 语法检查
python -m py_compile fas4_decompiler.py

# 反编译 + 验证
python fas4_decompiler.py PDI.fas PDI_test.lsp
python validate.py PDI_test.lsp

# 对比已有输出确认无退化
diff PDI_generic.lsp PDI_test.lsp

# 完整批量检查
python fas4_decompiler.py bib.fas bib_test.lsp && python validate.py bib_test.lsp
python fas4_decompiler.py PDI.fas PDI_test.lsp && python validate.py PDI_test.lsp
```

## 代码规范

- PEP 8 遵循（通过 `poetry run black .` 格式化）
- 类型注解使用 `typing` 模块风格（`Optional[str]` 而非 `str | None`，保持 Python 3.8 兼容）
- 新增函数/类需加文档字符串
- `fas_core.py` 是共享模块：所有工具脚本共用的函数放这里
- 解码器修复始终在 `fas4_decompiler.py`，从不修改生成的 `.lsp`

## 常见问题

**FAS 加载失败**：确认 XOR key 是否正确 → 检查 `find_key` 逻辑

**输出语法错误**：验证是未知操作码还是参数数量问题 → 检查 `_render_block` 的 `NotImplementedError`

**函数名丢失**：检查 `_choose_function_name` 的回退逻辑 → 符号表或 function_catalog 可能不完整

**BricsCAD 运行时错误**：收集精确错误信息（命令名、错误文本、堆栈），判断是语法恢复、参数数量还是依赖缺失问题
