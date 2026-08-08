# atlispcc 编译过程说明（.lsp → .fas）

本文详细说明 atlispcc 如何把 AutoLISP 源码（`.lsp`）编译成与 AutoCAD 编译器
逐字节一致的 FAS4 二进制（`.fas`）。面向编译器开发与调试，对应代码路径为
`compiler/` 目录。

> 相关文档：`docs/development.md`（架构管线概览）、`docs/fas-format.md`
> （FAS4 二进制格式）、`docs/cad-stub-format.md`（紧凑 stub 布局）、
> `docs/lasm.md`（汇编语言参考）。

## 1. 管线总览

```
.lsp 源码
  │
  ├─ Parser（lexer + parser）            → AST（compiler/ast_nodes.py）
  │
  ├─ [可选] OptPipeline.optimize(-O1/2/3) → 优化后的 AST
  │
  ├─ derive_symbol_names（cad_symbols）   → 符号注册顺序
  │
  ├─ SymbolTable                          → entries / name_to_idx / 常量表
  │
  ├─ CodeGenerator（stub_format=True）    → seg0 函数字节码
  │      ├─ defun 函数体字节码（含 CLEAR_ARGS 19 <argc> 00）
  │      └─ 顶层表达式 → top_level_code（模块代码输入）
  │
  ├─ ResourceBuilder.build()  ← 两轮     → seg1 资源段（模块代码/常量/符号/函数索引）
  │      └─ build_mvar_tables 重建 gvar 表 → _patch_usubr_idx 修正 seg0
  │
  └─ FasWriter.write(compact=True)        → .fas 二进制
```

CLI 入口：`compiler/cli.py::cmd_compile`（`atlispcc compile`）。

## 2. 阶段一：解析（Parser）

- `Parser(source)` 对源码做词法+语法分析，产出 `Program`（`program.forms`）。
- `compiler/lexer.py` 处理转义、注释、UTF-8/dotted 形式。
- 解析错误抛 `ParseError`，CLI 打印后 `sys.exit(1)`。
- 包系统（`defpackage`/`in-package`）在解析期收集到 `parser_obj.packages`。

## 3. 阶段二：优化（可选）

`opt_level > 0` 时调用 `opt.optimize(program, level=opt_level)`：

| 级别 | 内容 |
|---|---|
| O1 | 常量折叠 + 死分支消除 + 窥孔优化 |
| O2 | O1 + 常量传播 + 死赋值消除 + 重复 O1 |
| O3 | O2 + 跨函数常量传播 + 死代码消除 + 小函数内联 |

## 4. 阶段三：符号注册（cad_symbols）

`derive_symbol_names(program)` 按 **CAD 顺序**收集符号并注册到 `SymbolTable`：

- 常量（`is_const_entry`）→ `add_constant`
- 实数（`__real_<n>__` 编码）→ `add_real`
- 字符串（`"..."` 引号形式）→ `add_string`
- 已存在符号 → `add_force`（CAD stub 允许符号重复槽：递归/跨函数引用）
- 否则 → `get_or_add`

**顶层表达式符号**（defun 之外）并入模块注册段：收集 `other_forms` 中的符号
与字符串节点，按"最高顶层符号槽号 + 1"计算 `top_level_count`
（`max(_top_slots) + 1 - len(defun_forms)`，i18n ap03 实测 syscodepage const
使 `@::*I18N*` 槽到 idx9，须取 max+1 而非去重符号数）。

## 5. 阶段四：字节码生成（CodeGenerator）

`CodeGenerator(symtab, stub_format=True, defined_funcs=..., nsyms=codegen_nsyms)`。

- `codegen_nsyms = len(symtab.entries) - len(defun_forms) - top_level_count + 1`
- `_module_mode = True` 时编译**顶层表达式**到 `top_level_code`（模块代码输入）；
  `setq` 后追加 `ENCODE_POP`。
- 每个 defun 经 `generate_function(form)` 生成函数字节码，`func_offsets[name] =
  offset`。**函数间分隔符 `16`（END_DEFUN）**：CLEAR_ARGS `19 <argc> 00` 已由
  generate_function 生成，仅需追加 `16`。
- 内嵌 `(function (lambda ...))`（kwote 机制）DEFUN：偏移相对所在函数缓冲，
  转换为 seg0 绝对偏移，独立登记为 `-lambda-` 目录项，供 func-ranges 与
  DEFCODE 注册。
- `all_bytecode.resolve()` → `seg0`。

## 6. 阶段五：资源段构建（ResourceBuilder，两轮）

关键：**两轮构建**，因为代码引用长度依赖 seg0 最终长度。

### 第一轮

`resource.build(func_offsets, module_code=..., total_size=len(seg0)+1,
stub_format=True, top_level_count=..., commands=..., nested_ends=...)`。

- `module_code` 分支：
  - 含顶层表达式 → `_build_cad_module_code(...)`
  - 否则含 c: 命令 → `build_command_module_code(n_funcs)`（插入
    `vl-ACAD-defun`，仅模块注册段，不进符号表）
  - 否则 → `build_module_code(n_funcs, nsyms=_pre_nsyms)`
- `fas_nsyms = len(symtab.entries) - module_reg_count + 1`
  （`module_reg_count = len(defun_forms) + top_level_count`）

### 修正索引

`_patch_usubr_idx(seg0, seg1, symtab, fas_nsyms, all_func_args, codegen_nsyms)`：

- CAD 用 **`gvar 槽 - 1`** 编址（gvar 表由资源段 GVARINIT 建立）。
- `func_args` 顺序 = 顶层 defun 参数 + 各函数内嵌 kwote `-lambda-` 参数。

### 第二轮

用 patch 后的 seg0 重建 seg1（`total_size=len(seg0)+1`）。

### sec2_items

`count_resource_records(seg1)`，并按 CAD 语义兜底：

- 含 defun：`2 * (defun 数 + 顶层 form 数) + 2`
  （实测 1 函数→4、2 函数→6、3 函数→8；mix 1+1→6；t10 2+2→10）
- 纯顶层：`len(symtab.entries) + 2`
- 若偏小会遗漏函数注册（CAD 按 items 处理 GVARINIT 记录）。

## 7. 阶段六：写出（FasWriter）

```python
writer = FasWriter(symtab)
writer.write(output, seg0, seg1, sec2_items=sec2_items, nsyms=fas_nsyms, compact=True)
```

- `compact=True` → **紧凑 stub 格式**：`total_size = len(seg0) + 1`（CAD 实测
  恒等：cross/m2/m3/multi/sh/lambda_test 六份产物）。
- 自包含格式 `total_size = len(seg0_payload)`（`FasWriter.write` 不带 compact）。
- seg1 使用滚动 XOR 加密（`find_key`/`decrypt_stream`），尾部含密钥长度字节 +
  密钥 + `;fas4 crunch` 标记。
- 段分隔符 `16 24 0d 0a`；`nsyms` 为符号槽数（资源注册顺序）。

## 8. 关键 CAD 兼容约定

| 约定 | 说明 |
|---|---|
| seg0 | 函数字节码（`<nsyms> $...`），纯字节码 |
| seg1 | 资源段：模块头(`14 01 01 01 00`) + 代码引用 + 符号/字符串注册 + GVARINIT + DEFCODE + INIT_DONE + 模块代码 |
| seg1 头 items | GVARINIT + INIT_DONE 计数 |
| 符号名 | **统一大写**（`ResourceBuilder._enc_sym`）；字符串字面量不变 |
| 符号槽顺序 | 按源码函数逆序，每函数内"字节码引用序"逆序收集函数体符号、参数紧跟其后；混合时顶层表达式符号排在函数体内建之前；递归函数名重复槽 |
| 顶层表达式 | 编译进 seg1 **模块代码**（非 seg0）：`DEFUN头 + [顶层表达式] + [函数注册尾] + END_DEFUN`；gvar 槽 = 符号槽 + 1；简单 `setq 变量 "字符串"` → `PUSH_G 值+1; DUP; SETQ_G 变量+1` |
| 紧凑 stub 规则 | 中间 setq 无 POP、尾 setq 先 DUP、无 else 的 `if` 补 PUSH_NIL、有参函数末尾 `19 <argc> 00`（CLEAR_ARGS） |
| foreach/repeat | 函数 DEFUN 头 `b1=argc+1`（`14 <argc+1> <argc> <argc> 00`） |
| vla-/vlax- | vla- 符号保留大小写（ActiveX 方法名大小写敏感），`vlax-` 保持小写 |
| 值位置 T/t | 均注册符号槽并用 `PUSH_VALUE` 引用（nil 仍内联） |

## 9. 反编译对应路径（供理解格式）

```
.fas 二进制 → Fas4Parser.parse() → Fas4File
            → Disassembler.disassemble()  → List[Instruction]
            → ControlFlowAnalyzer.find_functions() → List[FunctionDef]
            → LispGenerator.generate() → AutoLISP 源码
```

解码器问题一律在 `decompiler/fas4_decompiler.py` 修复，**从不修改生成的 `.lsp`**。

## 10. 调试建议

```sh
# 编译 + 反编译 + 验证
python -m compiler.cli compile -O2 tests/test_setq_while.lsp test.fas
python -m decompiler.fas4_decompiler test.fas test.lsp
python -m tools.validate test.lsp

# 逐字节比对 CAD golden
python -m pytest tests/test_compiler_output.py -k "byte_identity"

# 分析 FAS 结构
python -m tools.fas-analyzer test.fas --dump
```

- 编译产物与 CAD 不一致时：先比 `seg0` → 再比 `sec2`/`nsyms`（`tools.fas-analyzer`）。
- 符号槽偏移问题：检查 `derive_symbol_names` 顺序与 `top_level_count` 计算。
- USUBR/参数槽错位：检查 `_patch_usubr_idx` 的 gvar 槽 - 1 编址与
  `all_func_args` 顺序。
