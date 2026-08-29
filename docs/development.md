# atlispcc 开发者说明

> 面向开发者：架构、管线、测试、代码规范与调试指南。面向使用者的 CLI 用法见 `README.md`。

## 环境准备

```sh
pip install -e ".[dev]"
# 或
python -m pytest
```

Python >= 3.8。

## 项目结构

```
decompiler/
  fas4_decompiler.py 主反编译器（解析 + 反汇编 + 分析 + 生成）
core/
  fas_core.py        共享核心模块 — 加解密、解析、符号表重建

asm/
  assembler.py       反汇编/汇编（.fas ↔ .lasm）
  opcodes.py         操作码定义与编码函数（codegen/linker/汇编共用）

compiler/
  cli.py             CLI 入口（atlispcc），子命令：compile/decompile/info/analyze/roundtrip/validate/zelx/unzelx/disasm/asm/link/build-vlx
  parser.py          Lisp 源码解析器 → AST
  ast_nodes.py       AST 节点定义（含 Defpackage、InPackage）
  packages.py        包系统：PackageTable、名混淆/还原
  symbol_table.py    符号表构建与作用域分析（含包解析）
  cad_symbols.py     CAD 符号槽顺序推导（CadSymbolCollector）
  codegen.py         字节码生成器（AST → 指令流）
  resource_builder.py 常量/符号/函数索引 → 资源段
  fas_writer.py      指令流 → FAS4 二进制
  opt.py             优化器（-O）：9 个 pass 跨 O1-O3 级别
  analyzer.py        编译分析与统计
  dep_analysis.py    调用图/依赖分析（analyze 子命令）
  roundtrip.py       编译往返冒烟（roundtrip 子命令）
  _gvar_map.py       commands+顶层混合 gvar 槽重映射
  linker.py          多文件 FAS 链接器
  vlx_builder.py     VLX 容器构建器

engine/
  atlisp.asd         SBCL AutoLISP 运行时（ASDF 系统，实验性跨校验器）
  src/*.lisp         packages/values/reader/env/eval/builtins/main

tools/
  validate.py        LSP 语法验证器（+ 危险函数/危险命令/未使用局部变量）
  fas-analyzer.py    FAS4 分析工具
  fas-split.py       FAS 分割工具
  decrypt_fas4.py    解密工具
  crack_key.py       密钥破解工具
```

### 关键文件

| 文件 | 作用 |
|------|------|
| `decompiler/fas4_decompiler.py` | 主反编译器：解析 + 反汇编 + 分析 + 生成 |
| `core/fas_core.py` | 共享加密/解析/符号工具函数（`find_key`/`decrypt_stream`/`build_mvar_tables`/`build_function_catalog`） |
| `compiler/cli.py` | CLI 入口，子命令分发 |
| `compiler/parser.py` | Lisp 源码解析器 → AST |
| `compiler/ast_nodes.py` | AST 节点定义（含 Defpackage、InPackage） |
| `compiler/packages.py` | 包系统：PackageTable、名混淆/还原 |
| `compiler/symbol_table.py` | 符号表构建与作用域分析（含包解析） |
| `compiler/codegen.py` | 字节码生成器（AST → 指令流） |
| `compiler/resource_builder.py` | 常量/符号/函数索引 → 资源段 |
| `compiler/fas_writer.py` | 指令流 → FAS4 二进制 |
| `compiler/opt.py` | 优化器：9 个 pass 跨 O1-O3 级别 |
| `compiler/analyzer.py` | 编译分析与统计 |
| `compiler/dep_analysis.py` | 调用图/依赖分析（analyze 子命令） |
| `compiler/roundtrip.py` | 编译往返冒烟（roundtrip 子命令） |
| `compiler/_gvar_map.py` | commands+顶层混合 gvar 槽重映射 |
| `asm/assembler.py` | 反汇编/汇编（.fas ↔ .lasm） |
| `asm/opcodes.py` | 操作码定义与编码函数（codegen/linker/汇编共用） |
| `compiler/linker.py` | 多文件 FAS 链接器 |
| `compiler/vlx_builder.py` | VLX 容器构建器 |
| `validate.py` | 生成的 `.lsp` 语法验证器 |
| `engine/atlisp.asd` | SBCL AutoLISP 运行时（实验性，跨校验器） |

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
- **O3**：O2 + 跨函数常量传播 + 死代码消除 + 小函数内联 + 删除死函数

每个优化是可组合的 Pass 类：

| Pass | 作用 |
|---|---|
| ConstantFold | `(+ 1 2)` → `3`, `(strcat "a" "b")` → `"ab"` |
| DeadBranchElim | `(if T e1 e2)` → `e1`, `(while nil ...)` → `nil` |
| PeepholeOpt | `(progn x)` → `x`, `(list)` → `nil`, `(+ x)` → `x` |
| ConstantPropagate | `(setq x 3) (+ x 1)` → `(setq x 3) (+ 3 1)` |
| DeadAssignElim | 移除未使用的 `(setq x ...)` |
| CrossFuncConstPropagate | 常量返回的 0 参函数替换为常量 |
| DeadCodeElim | 删除 `exit`/`quit` 后的死代码 |
| InlineSmallFuncs | 内联单次调用的小函数 |
| RemoveDeadFuncs | 删除未被引用且非命令的函数（仅当有入口点时，O3） |

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

链接输出与 CAD 编译器直接编译同源码**逐字节一致**（2026-08-08 修复，`§3.6`
development-plan）：

- **函数间分隔符**：单个 `16`（END_DEFUN，CAD stub 实测，非 `01 00 16`）
- **参数绑定/读取槽**：按合并 gvar 槽 - 1（`_pre_gvar` 表内）或参数序
  `nsyms-1-arg_rev`（表外）；单函数文件操作数 = 符号槽、多函数 = 符号槽 - 1
- **符号槽顺序**：单函数文件分离函数体符号/参数（共享参数最后注册），多函数
  文件参数穿插各函数体内不分离
- **sec2_items**：`2 * 函数数 + 2`（CAD 实测 2 函数→6、3 函数→8）
- **函数偏移**：`final_offset` 按分隔符长度 1 累计

回归：`test_link_byte_identity_with_cad_golden`（3 份 CAD golden：
`tests/cad/link/{addmul,sqsum,three}_cad.fas`）seg0+sec2+nsyms+items 逐字节一致；
CAD 真机 add/mul、square/sum-squares、f1/f2/f3、重名冲突场景全部可调用。

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
- **分支指令**（JMP32_IFNOT/JMP16_IFNOT 等）：尝试检测 if/while/foreach 结构
  - `_detect_if`：识别 if-then-else 模式
  - `_detect_loop`：识别 while/foreach 模式
  - 无法识别则输出注释标记
- **SETQ_G/SET_LOCAL**：生成 `(setq var expr)`

### _repair_call_target

处理函数引用错位问题——某些 FAS 的调用索引指向错误符号，通过附近符号试探纠正：

- `_is_bad_builtin_arity` 检测参数数量不匹配的内建函数
- 在 ±12 范围内寻找符号作为替代（有已知 arity 的加权重）
- `_skip_literal_zero_arg_call` 特殊处理：丢弃指向提示字符串的 0 参数伪造调用

## 测试

```sh
./scripts/run_tests.sh         # 一键全量检查（py_compile + pytest + disasm→asm 往返 + byte-identity 状态）
./scripts/run_tests.sh --cad   # 附加 CAD 真机验证（需 CAD 连接）
python scripts/cad_verify.py   # CAD 真机验证（逐个编译 t01-t24+i18n 加载断言，25 项）
python -m pytest               # 运行所有测试（380 用例：378 passed + 2 skipped）
python -m pytest tests/ -v     # 详细输出
python -m pytest tests/test_resource_stream.py  # 资源码专项测试
```

测试文件在 `tests/` 目录：
- `test_parser.py` — AST 解析器（21 用例）
- `test_lexer.py` — 词法分析（11 用例：转义、注释、UTF-8、dotted）
- `test_symbol_table.py` — 符号表/作用域（10 用例）
- `test_analyzer.py` — 编译分析/尾递归（9 用例）
- `test_cli.py` — CLI 路径（31 用例：compile/-O/--analyze/--report/validate/link/vlx/info/analyze/dispatch + validate 补强规则 + 源码编码检测 + 顶层 progn/条件 defun/atlisp_u 综合包编译）
- `test_compile_decompile.py` — 编译-反编译往返（74 用例，含复杂 LSP O2/O3 往返、16 个 `tests/compile_src/` fixture 系列 roundtrip、i18n 混合模式、§3.5d/e 折叠回归、§10.4 golden 参数名/循环结构回归、C4 DCL 对话框）
- `test_compiler_output.py` — FAS 输出正确性（70 用例，含 4 对 CAD golden 逐字节比对 + 16 个 `tests/compile_src/` 结构断言 + i18n 拆分件 byte-identity 回归）
- `test_fas_verify.py` — FAS 产物校验/加载（6 用例）
- `test_large_file.py` — 大文件/宽格式（10 用例，含 >256 符号 USUBR/FUNC 宽格式）
- `test_optimizer.py` — 所有优化 pass（32 用例，含循环携带变量回归）
- `test_linker.py` — 多文件链接（13 用例，含重名冲突警告 + 3 份 CAD golden byte-identity）
- `test_assembler.py` — 反汇编/汇编往返（11 用例）
- `test_disasm.py` — 反汇编健壮性（10 用例，含未处理操作码降级）
- `test_resource_stream.py` — 资源码解析/资源段构建（25 用例：符号/字符串块、GVARINIT、DEFCODE、build_mvar_tables、资源码 vs 操作码区分）
- `test_packages.py` — CL 风格包系统（4 用例）
- `test_vlx_builder.py` — VLX 容器（3 用例）
- `test_variadic_args.py` — &optional/&rest 编译（17 用例，含多函数参数名恢复）
- `test_zelx.py` — ZWCAD ZELX 构建/解析（5 用例）
- `test_diagnostics.py` — 诊断类新功能（20 用例：analyze 调用图 .lsp/.fas + dot/mermaid/text 输出 + roundtrip 往返冒烟 PASS/FAIL 与 CLI 退出码）

手动测试文件 `tests/test_*.lsp` 也在该目录。

## 兼容性

FAS4 输出格式与 AutoCAD 编译器一致：
- seg0 = 函数字节码（`<nsyms> $...`），seg1 = 资源段（常量/符号/函数索引）
- 紧凑 stub 格式 `total_size = len(seg0) + 1`（CAD 实测恒等：cross/m2/m3/multi/sh/lambda_test 六份产物；seg0 = `<nsyms> $` 后的纯字节码）；自包含格式 `total_size = len(seg0_payload)`。`FasWriter.write(..., compact=True)` 走前者（CLI/链接器/紧凑汇编）
- **汇编器（`asm/assembler.py`）同时支持两种布局**：`.lasm` 头部的 `.format compact|selfcontained` 指令选择布局与 stub 编码（USUBR/FUNC 3 字节、PUSH_VALUE[0] 单字节、CLEAR_ARGS `19 <argc> 00`）；缺省按指令特征自动判定。`disasm → asm` 往返 seg0 逐字节一致，紧凑产物可在 CAD 加载执行。**宽格式**（nsyms>256）：`_detect_compact` 自动用宽解析（5/6 字节 USUBR/FUNC），大文件 seg0+nsyms 往返逐字节一致（atlisp_u 回归）；seg1 资源段不随 `.lasm` 携带
- 紧凑 stub 生成规则（与 CAD 逐字节一致）：中间 setq 无 POP、尾 setq 先 DUP、无 else 的 `if` 补 PUSH_NIL、有参函数末尾 `19 <argc> 00`（CLEAR_ARGS）
- **大文件宽格式**（nsyms>256）：5 字节 USUBR `35 <argc> <idx16> <flags=3>`、6 字节 FUNC `51 <argc> <idx16> <flags=1> 00`（`asm/opcodes.py` `encode_usubr`/`encode_func`，flags 内联原 `00 03` 清理；atlisp_u.lsp 502 函数实测）
- seg1 使用滚动 XOR 加密（`find_key`/`decrypt_stream`），尾部含密钥长度字节 + 密钥 + `;fas4 crunch` 标记
- 段分隔符为 `16 24 0d 0a`，`nsyms` 为符号槽数（资源注册顺序）
- seg1 资源流 = 模块头(`14 01 01 01 00`) + 代码引用 + 符号/字符串注册 + GVARINIT + DEFCODE + INIT_DONE + 模块代码；`seg1` 头 `items` = GVARINIT + INIT_DONE 计数
- **符号名统一大写**（`ResourceBuilder._enc_sym`）：CAD 符号槽全大写（AutoLISP 大小写不敏感）；字符串字面量不变
- **符号槽顺序** = 按源码函数逆序，每函数内"字节码引用序"逆序收集函数体符号、参数紧跟其后（`compiler/cad_symbols.py`）；混合（defun+顶层）时顶层表达式符号排在函数体内建之前；递归函数名重复槽
- **顶层表达式**（defun 之外的 setq/set 等）编译进 seg1 **模块代码**（非 seg0）：模块代码 = `DEFUN头 + [顶层表达式] + [函数注册尾: JUMP + PUSH_G <模块注册+2>; SETQ_G 1; PUSH_G 1] + END_DEFUN`；gvar 槽 = 符号槽 + 1；简单 `setq 变量 "字符串"` → `PUSH_G 值+1; DUP; SETQ_G 变量+1`；顶部占位 `PUSH_G <模块注册符号数+1>; POP`；代码引用长度 = `total_size`（`len(seg0) + 1`）
- **模块注册段**（混合 defun+顶层）：注册函数名 + 顶层表达式符号（连续 SYMBOL 合并 5b 块，遇 STRING 分块）；`nsyms = len(entries) - 模块注册符号数 + 1`；函数注册 GVARINIT st_init = nsyms；DEFCODE 后 GVARINIT var_pos = 模块注册符号数 + 2
- 多函数函数间分隔符：`16`（END_DEFUN；CLEAR_ARGS `19 <argc> 00` 已由 codegen 生成，分隔符只追加 `16`）
- 反编译回归参考：`tests/fun.lsp`（`(defun a () (alert "abc"))`）经 CLI 编译往返；原 CAD 产物 golden `tests/fun-cad.fas` 已随 t-series 源清理移除

**kwote 机制**（`(function (lambda ...))`，v0.1.18+）：

- `_emit_nested_lambda` 发内嵌 `-lambda-` DEFUN（`JUMP <label:4>; 14 argc argc argc 00;
  体; CLEAR_ARGS; 16; <label>`），随后 `PUSH_G <lam_idx>; FUNC3 1 <kwote>; NIL;
  PUSH_NIL; NIL`。每个内嵌 `-lambda-` 独立符号槽（t3 槽 18、t4 槽 17、t5 槽 16）。
- 资源段：每个内嵌 lambda 独立 DEFCODE，在 GVARINIT(0, nsyms) 前置发射、按
  **codegen 发射序逆序**（`_fnl_raw` 序；兄弟 lambda 发射序 = offset 序，逆序 ==
  offset 逆序；嵌套 kwote lambda 用发射序，panel.lsp 实测）；`-lambda-` 保留小写、
  不进 `symtab.entries`（仅 DEFCODE 区注册）——
  fas_nsyms 比 codegen_nsyms 大 1，seg0 引用 `gvar 槽 - 2`（`_patch_usubr_idx`
  的 offset 修正）。
- 顶层 `(set/setq 'sym (lambda ...))`（纯顶层文件，v0.1.22+，setq-lambda.lsp
  byte-identity）：内嵌 `-lambda-` 是完整 compact stub（`14 <argc>x3 00` +
  GET_LOCAL + INIT_ARGS + 体 + CLEAR_ARGS + END_DEFUN，函数间 `16` 分隔、最后无
  END；USUBR 用 5 字节宽格式 `35 <argc> <idx16> 03`），模块代码 setq 协议绑定
  `JUMP 0; PUSH_G <-lambda-槽+1>; DUP; SETQ_G <sym>`。资源段布局：第一区（仅顶层
  表达式符号）→ GVARINIT(0, 第一区数+2) → 函数目录（`_func_ranges_bytes`）→ 第二区
  （lambda 体符号+参数+最后调用名，跨 lambda 去重）→ `GET_LOCAL; GVARINIT(0,
  第二区数+1)` 建 fg 表（module_id=最后符号判 table1）→ 多 DEFCODE → `GVARINIT
  (第一区数+2, 函数数)`。nsyms = fg 表长度 = `1 + len(第二区符号)`。

**`command` 内建**：资源段注册名为 `ads-cmd`（非 `COMMAND`）；调用字节
`FUNC3 + NIL + PUSH_NIL + NIL`（base-function 真机实测）。

**`/ 局部变量`**（t11）：`_al-bind-alist` 符号 + `(quote (locals...))` 常量独立
注册（0x56 保留大小写）；绑定字节 `PUSH_G <const>; FUNC 1; NIL; PUSH_NIL; NIL; POP`；
CLEAR_ARGS = argc + locals。

**commands + 顶层混合**（atlisp_u.lsp）：`compiler/_gvar_map.py` 解析 seg1 模块
注册段得到 `{符号名: gvar槽}` 映射，`_offset_slots` 二次生成模块代码时按实际
槽位重映射 USUBR/PUSH_G/FUNC（`symtab_idx+1` 不再等于实际 gvar 槽）。

**模块代码 `_reg` b 槽让位**（v0.1.30+，`i >= base - tl_funcobj_slot`）：顶层
kwote lambda 的 func-obj 槽（`tl_funcobj_slot` = base - tl_pos，DEFCODE 区注册）
占用 b 序列一槽，源码位置在 tl 之后的函数 b 值 -1。setup tl_pos=8 = n_pre
（START 边界）；atlisp_u tl_pos=239 ≠ n_pre=1（tl 在 TAIL 中段），统一用
`i >= base - tl_funcobj_slot` 判定（旧 `i >= n_pre` 对 atlisp_u 不生效）。

**`_mid_count_of` top-lambda-only 索引**（v0.1.30+）：`_mid_counts` 构建时跳过
top-lambda 提升 defun（fasext/vlx/wget），索引比 `func_names` 少 3。`_emit_mid_for`/
`_has_mid` 按 `func_names` 前导 **skip_funcs**（非 `_skip`，后者含 `_cond_defun_names`
条件 defun）偏移映射；`_skip` 函数跳过 `_reg_emit` 但**仍发射 mid 语句**
（CondDefunBind 块在跳过位置发射，panel C:%/C:%% 实测）。

**`set` 协议纯顶层/混合不同槽**（v0.1.30+）：`(set 'X (lambda ...))` 纯顶层
（net/wget）PUSH_G = `_lam_slot`；混合文件（atlisp_u @::wget）PUSH_G =
`_lam_slot + 1`（`n_funcs > 0` 时 +1，`_lam_slot` 混合公式已含 n_cmds+_tl_lam_count）。

**`_offset_slots` fallback 编址**（v0.1.30+，`first_cmd_slot` 判定）：
- SYMBOL/STRING 表外符号 fallback = `symtab_idx + 1 + n_cmds`（vl-ACAD-defun 插入
  使模块注册其后的符号 gvar 槽整体 +1，atlisp_u `(set 'e2o ...)` 实测）。
- **CONST（引用字面量）**：仅当 const 注册在首个 `c:` 命令槽之后（`idx >
  first_cmd_slot`）才 `+n_cmds`——menu/voice const 在 vl-ACAD-defun 之后加
  （`idx+1+n_cmds`）；panel foreach 组 const（`'("1" "AI" ...)`、`'(princ)`）在
  C:% 之前不加（`idx+1`），否则错位 1。

**`_patch_usubr_idx` 双注册分支守卫**（v0.1.30+）：模块区 + 函数体区双注册顶层
变量（net/probe `@::*network-failure-count*`）用 `_body_slot = _rs - module_reg_count
- 1` 编址；该公式须满足 `0 <= _body_slot < nsyms`，否则落到 `_res_offset` 分支
（`_rs - _res_offset`）。BYTELEN 这类 `/ local` 在多个函数体区各注册一次、非模块区
双注册（panel `351-35-1=315 ≥ nsyms`）走 `_res_offset`（`351-100=251` → 操作数 250），
旧 `nsyms-1` fallback 错位 15。

反编译器同时支持两种布局：
- **自包含格式**（`tests/cad/i18n-cad.fas`、`tests/cad/i18n.fas`）：seg0 含完整函数体 + END_DEFUN，函数目录来自 mvar 表重建
- **紧凑 stub 格式**（AutoCAD 编译器输出，`tests/cad/*_cad.fas` t-series golden）：seg0 无 END_DEFUN，符号按资源注册顺序（`symbol_slots`）直接编址

生成器会发出包装辅助函数以避免内建冲突：
- `fas-polar1`、`fas-rtos1`、`fas-rtos3`、`fas-getvar2`、`fas-getvar3`
- 用于列表/关联列表/DXF 组码读取的 `IN_PARAM` 查找
- 缺少 `Projet/PA_Projet` 框架时的后备选择提示

解码器问题在 `decompiler/fas4_decompiler.py` 中修复，永远不要修改生成的 `.lsp`。

### 编译管线关键实现（与 CAD 逐字节一致）

`compiler/cli.py` 的 `cmd_compile` 完整流程：

0. **源码改写**（@lisp 综合包支持，v0.1.21+）：`_flatten_top_level_forms`（顶层
   `(progn ...)` 展开）、`_hoist_conditional_defuns`（条件/嵌套 defun → 提升为
   顶层独立函数，if 内留 `CondDefunBind` 绑定标记，见「条件 defun 绑定」）、
   `_lower_nested_defuns`（函数体内嵌套 defun → 原生内嵌 DEFUN）、
   `_rewrite_top_lambda_binds`（纯顶层 lambda → `-lambda-` SUBR）、
   `_lower_multi_kwote`（多 kwote → 引用数据）、`_lower_immediate_lambda`
1. **符号注册**：`derive_symbol_names`（`compiler/cad_symbols.py`）按 CAD 顺序收集符号，注册到 `SymbolTable`
2. **codegen**：`CodeGenerator(stub_format=True)` 生成 seg0 函数字节码（含 CLEAR_ARGS `19 <argc> 00`）；nsyms>256 时 `wide_subr=True`（5/6 字节宽格式）
3. **顶层表达式**：`_build_cad_module_code` 生成 CAD 风格模块代码（setq 用 `PUSH_G 值+1; DUP; SETQ_G 变量+1`，非 setq 用 codegen + 槽偏移 `_offset_slots`）
4. **seg1 构建**：`ResourceBuilder.build(..., top_level_count=...)` — 模块注册含顶层符号；多函数用 `_func_ranges_bytes`（末函数 end = total_size）
5. **nsyms**：`len(entries) - 模块注册符号数 + 1`（模块注册 = 函数名 + 顶层符号数）
6. **索引修正**：`_patch_usubr_idx` 用 `build_mvar_tables` 重建的 gvar 表，把 USUBR/参数槽改为 `gvar槽-1`
7. **两轮构建**：先建 seg1（获取 gvar 表）→ patch seg0 → 重建 seg1（代码引用长度依赖最终 seg0）

`_build_cad_module_code` 生成的模块代码（`_slot_of` 查符号/字符串槽，字符串 key 为 `__str_<值>__`）：

- 顶部 `PUSH_G <模块注册符号数+1>; POP` 占位；setq → `PUSH_G 值+1; DUP; SETQ_G 变量+1`
- `(in-package :@)` → `PUSH_VALUE <pkg槽>; FUNC_REF in-package`
- 函数注册尾 `JUMP + PUSH_G <b>; SETQ_G <c>`（b = `2n+1+top_level_count-i`，c = 函数符号槽+1）
- **post-form 分组**：最后一个 defun 之后的顶层语句排到函数注册尾之后（`n_post_forms`）
- **`c:` 命令混合模式**：模块注册段插入 `56 vl-ACAD-defun 00 00` 块，命令注册用
  CAD 24 字节模式 `JUMP; PUSH_G b; SETQ_G c; PUSH_G c; USUBR(1, <vl槽>); PUSH_NIL;
  POP; PUSH_G c; POP`

#### 条件 defun 绑定（`(if c (progn (defun f ...) ...))`，v0.1.30+，panel.lsp 实测）

顶层 `(if is-gcad (progn (defun C:% ...) (defun C:%% ...) (foreach ...)))`：

- **`_hoist_conditional_defuns`**（cli.py）：defun 体提升为顶层独立函数（进 seg0 +
  DEFCODE 注册，运行时被模块加载器预定义），if 内以 `CondDefunBind(name)` 标记
  替换（`compiler/ast_nodes.py`）。**运行时绑定留在 if 守卫内**，非无条件注册。
- **模块代码 `_stmt_bytes`**：检测 then 分支含 `CondDefunBind` 时手动组装 if：
  `PUSH_VALUE <cond>; JMP32_IFNOT <else>; JUMP +0; [每个绑定: PUSH_G <func-obj>;
  SETQ_G <sym>; PUSH_G <sym>; USUBR(1, vl-ACAD-defun) 4字节; PUSH_NIL; POP];
  [foreach]; JUMP +1; PUSH_NIL`。func-obj/b/c/vl 槽按 `_reg(i)` 公式预计算
  （panel C:% b=39/c=14、C:%% b=38/c=12、vl=13）。绑定字节已是最终 gvar 槽，
  **不再经 `_offset_slots`**；cond/foreach/else 单独 `_offset_slots` 后拼接、
  手动 patch JMP32_IFNOT/JUMP 偏移。
- **跳过无条件注册**：`_cond_defun_names`（扫描 `other_forms` 的标记）并入 `_skip`，
  TAIL `_reg_emit` 跳过提升函数（b/c/vl 槽仍按公式保留给其他函数）。
- **`-lambda-` DEFCODE 顺序 = 全局发射序逆序**（cli.py `_lambda_batches`）：纯 kwote
  文件按函数逆序 + 各函数 `reversed(_fnl_raw)`（`_fnl_raw` = codegen `_nested_lambdas`
  发射序）。@::panel-calc-layout 3 个 kwote lambda 发射序 `[inner, outer, bt-man]`
  → DEFCODE `[bt-man, outer, inner]`。log 兄弟 lambda 发射序 = offset 序，逆序 ==
  offset 逆序，二者一致；**嵌套 kwote lambda** offset 序 ≠ 发射序，须用发射序。
  含立即 lambda 的文件（safe-eval，`nested_lambda_order` 置位）保持源码序覆盖。
- **前置 DEFCODE 父-子链修正允许 `-lambda-` 父**（resource_builder.py `nd_offsets`
  + cli.py `_pre_all`）：外层 kwote lambda（outer 体内嵌 inner）须父在前，否则
  offset 降序错位。此前 `_is_lambda_key` 跳过 lambda 父，仅真实嵌套 defun 参与。

## 调试与验证

```sh
# 开发模式安装（含 dev 工具）
pip install -e ".[dev]"

# 语法检查
python -m py_compile decompiler/fas4_decompiler.py
python -m py_compile compiler/opt.py

# 编译 + 反编译 + 验证
python -m compiler.cli compile -O2 tests/fun.lsp test.fas
python -m decompiler.fas4_decompiler test.fas test.lsp
python -m tools.validate test.lsp

# 完整测试套件
python -m pytest -v

# 格式化 / 类型检查
black .
mypy .
```

## 工具脚本

`tools/` 下的辅助分析工具随 pip 包分发（`pyproject.toml` 的
`include = ["compiler*", "asm*", "core*", "decompiler*", "tools*"]`）。
其中 `tools/validate.py` 被 CLI 的 `validate` 子命令依赖，其余为独立脚本：

### 分析工具

```sh
# FAS4 文件分析
python -m tools.fas-analyzer tests/cad/i18n-cad.fas
python -m tools.fas-analyzer tests/cad/i18n-cad.fas --dump
python -m tools.fas-analyzer tests/cad/i18n-cad.fas --json
```

### 函数分割

```sh
python -m tools.fas-split tests/cad/i18n-cad.fas
python -m tools.fas-split tests/cad/i18n-cad.fas --trim
python -m tools.fas-split tests/cad/i18n-cad.fas --outdir ./split_output
```

### 解密/破解

```sh
python -m tools.decrypt_fas4 tests/cad/i18n-cad.fas
python -m tools.crack_key encrypted.fas
python -m tools.find_key encrypted.fas    # 在 FAS 中定位 XOR 加密密钥
```

### 生成文件验证

```sh
python -m tools.validate output.lsp       # 语法 + 危险函数 + 危险命令（validate_command）+ 未使用局部变量
```

### ZWCAD ZELX（逆向 LispConverter）

```sh
python -m tools.zelx_info file.zelx       # 解析/解密 .zelx 容器
python -m tools.zelx_diff file.fas file.zelx  # .fas ↔ .zelx 结构 diff
python -m tools.zelx_build input.fas out.zelx  # .fas → .zelx 写入器
python -m tools.zelx_to_fas input.zelx out.fas # .zelx → .fas 恢复
```

### 其他

```sh
python -m tools.compare_lsp a.lsp b.lsp       # .lsp 对比
python -m tools.analyze_rosetta ...           # Rosetta 代码分析
python -m tools.cad_probe ...                 # MCP CAD 交互辅助（开发调试）
```

`tools.lisp_converter_auto`（ZWCAD LispConverter.exe GUI 自动化，样本生产）与
`tools.cad_probe` 依赖桌面环境，通常不用于 CI。

### engine/（SBCL AutoLISP 运行时）

`engine/` 是一个实验性 SBCL/ASDF 运行库（`engine/atlisp.asd`），用于脱离 CAD
环境执行 AutoLISP 源码，作为编译器语义的跨校验器：

```sh
cd engine
sbcl --noinform --non-interactive --load atlisp.asd \
     --eval '(asdf:load-system "atlisp")' \
     --eval '(in-package :atlisp)' \
     --eval '(format t "~a~%" (al-eval-source "(+ 1 2)"))'
```

- 值模型：AutoLISP 数据映射到 CL 原生值（nil/t/int/double-float/string/AL 包符号/cons）。
- 公共 API（`:atlisp` 导出）：`al-eval-source` / `al-run-file` / `al-repl`。
- 冒烟基线：算术/defun/apply/list/dotted pair/if/while/cond/foreach/strcat/
  动态作用域/function-lambda/length/logand/fix 全部通过。
- 与 FAS4 关系：不参与字节码编解码，仅对照同一源码的编译产物与引擎求值结果。

## 代码规范

- PEP 8（通过 `black .` 格式化）
- 类型注解使用 `typing` 模块风格（`Optional[str]`，保持 Python 3.8 兼容）
- `core/fas_core.py` 是共享模块：所有工具脚本共用的函数放这里
- 解码器修复始终在 `decompiler/fas4_decompiler.py`，从不修改生成的 `.lsp`

## 常见问题

**FAS 加载失败**：确认 XOR key 是否正确 → 检查 `find_key` 逻辑

**输出语法错误**：验证是未知操作码还是参数数量问题 → 检查 `_render_block` 的 `NotImplementedError`

**函数名丢失**：检查 `_choose_function_name` 的回退逻辑 → 符号表或 function_catalog 可能不完整

**目标平台运行时错误**：收集精确错误信息（命令名、错误文本、堆栈），判断是语法恢复、参数数量还是依赖缺失问题
