# Fas2Lsp 开发说明

## 环境准备

```sh
pip install poetry
poetry install
poetry shell
# 或
poetry run python fas4_decompiler.py ...
```

Python >= 3.8。当前使用 Python 3.10.11。

## 项目结构

```
fas4_decompiler.py   主反编译器（2136 行）
fas_core.py          共享核心模块（690 行）— 加解密、解析、符号表重建
validate.py          LSP 语法验证器
decompile.py         简易包装入口

compiler/
  cli.py             CLI 入口（atlispcc），子命令：compile/decompile/validate/link
  parser.py           Lisp 源码解析器 → AST
  symbol_table.py     符号表构建与作用域分析
  codegen.py          字节码生成器（AST → 指令流）
  resource_builder.py 常量/符号/函数索引 → 资源段
  fas_writer.py       指令流 → FAS4 二进制
  opt.py              优化器（-O）：常量折叠、死分支消除、窥孔优化、常量传播、死赋值消除
  ast.py              AST 节点定义

debug/               FAS 调试工具

server/              实验性 LSP 服务器，独立代码路径
```

## 架构管线

### 编译器管线（compile）

```
Lisp 源码 → Parser.parse() → AST
         → SymbolTableBuilder.build() → SymbolTable
         → Codegen.generate() → FunctionDefs（指令流）
         → [OptPipeline.optimize()  # -O 时可选]
         → ResourceBuilder.build() → 资源段
         → FasWriter.write() → FAS4 二进制
```

### 优化器（compiler/opt.py）

优化级别通过 `-O` 标志控制：

- **O0**：无优化
- **O1**：常量折叠 + 死分支消除 + 窥孔优化
- **O2**：O1 + 常量传播 + 死赋值消除 + 重复 O1

每个优化是可组合的 Pass 类：

| Pass | 作用 |
|---|---|
| ConstantFold | `(+ 1 2)` → `3`, `(strcat "a" "b")` → `"ab"` |
| DeadBranchElim | `(if T e1 e2)` → `e1`, `(while nil ...)` → `nil` |
| PeepholeOpt | `(progn x)` → `x`, `(list)` → `nil`, `(+ x)` → `x` |
| ConstantPropagate | `(setq x 3) (+ x 1)` → `(setq x 3) (+ 3 1)` |
| DeadAssignElim | 移除未使用的 `(setq x ...)` |

### 反编译器管线（decompile）

```
FAS4 二进制 → Fas4Parser.parse() → Fas4File
            → Disassembler.disassemble()  → List[Instruction]
            → ControlFlowAnalyzer.find_functions() → List[FunctionDef]
            → LispGenerator.generate() → AutoLISP 源码
```

### 链接器管线（link）

```
FAS A + FAS B + ... → 合并符号表/函数目录
                    → 重排函数索引
                    → 修复交叉引用
                    → 写入合并 FAS
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
5. 兼容性包装（平台适配）
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
python -m py_compile compiler/opt.py

# 编译 + 反编译 + 验证
python compiler/cli.py compile -O2 tests/test_while.lsp test.fas
python fas4_decompiler.py test.fas test.lsp
python validate.py test.lsp

# 完整测试套件
python -m pytest -v

# 格式化
black .
```

## 代码规范

- PEP 8（通过 `black .` 格式化）
- 类型注解使用 `typing` 模块风格（`Optional[str]`，保持 Python 3.8 兼容）
- `fas_core.py` 是共享模块：所有工具脚本共用的函数放这里
- 解码器修复始终在 `fas4_decompiler.py`，从不修改生成的 `.lsp`

## 常见问题

**FAS 加载失败**：确认 XOR key 是否正确 → 检查 `find_key` 逻辑

**输出语法错误**：验证是未知操作码还是参数数量问题 → 检查 `_render_block` 的 `NotImplementedError`

**函数名丢失**：检查 `_choose_function_name` 的回退逻辑 → 符号表或 function_catalog 可能不完整

**目标平台运行时错误**：收集精确错误信息（命令名、错误文本、堆栈），判断是语法恢复、参数数量还是依赖缺失问题
