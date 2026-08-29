# atlispcc - Agent 指南

## 项目

**atlispcc** = **A**uto**LISP** **C**ompiler **C**ollection，FAS4 字节码编译器套件：`.lsp` ↔ `.fas`（兼容 AutoLISP 的 CAD 平台）。

`atlispcc` — 统一 CLI 工具（`compiler/cli.py`），支持十二个子命令：

```
atlispcc compile [-O {0,1,2,3}] <input.lsp> [output.fas]    # 编译 Lisp → FAS
atlispcc decompile <input.fas> [output.lsp]                # 反编译 FAS → Lisp
atlispcc disasm <input.fas> [output.lasm]                  # 反汇编 FAS → 字节码指令列表
atlispcc asm <input.lasm> [output.fas]                     # 汇编 .lasm → FAS
atlispcc validate <input.lsp>                              # 语法验证
atlispcc link [-o OUTPUT] <input.fas> <input.fas> [...]    # 多文件链接
atlispcc build-vlx <input.fas>... -o output.vlx [--export ...]  # VLX 容器
atlispcc zelx <input.lsp|input.fas> [output.zelx]          # ZWCAD ZELX（逆向 LispConverter）
atlispcc unzelx <input.zelx> [output.fas]                  # 从 .zelx 恢复 .fas
atlispcc info <input.fas|input.zelx> [--json]              # 快速概览（头/段/函数目录）
atlispcc analyze [-f text|dot|mermaid|json] [-o OUT] [--no-cc] <lsp|fas>  # 调用图/依赖分析
atlispcc roundtrip <input.lsp> [-O {0,1,2,3}] [--keep]     # 编译往返冒烟自检
```

子命令别名：`compile→c`、`decompile→d`、`validate→v`、`disasm→disassemble`、`asm→assemble`。无子命令时默认为 compile。

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
| `decompiler/fas4_decompiler.py` | 主反编译器：解析 + 反汇编 + 分析 + 生成 |
| `core/fas_core.py` | 共享加密/解析/符号 — `find_key`/`decrypt_stream`/`build_mvar_tables`/`build_function_catalog` |
| `compiler/cli.py` | CLI 入口，子命令 dispatch；`_patch_usubr_idx` 槽重映射 |
| `compiler/parser.py` | Lisp 源码解析器 → AST |
| `compiler/ast_nodes.py` | AST 节点定义 |
| `compiler/symbol_table.py` | 符号表构建与作用域分析 |
| `compiler/codegen.py` | 字节码生成器（AST → 指令流） |
| `compiler/cad_symbols.py` | 符号槽收集器（`CadSymbolCollector`，与 CAD 符号序对齐） |
| `compiler/resource_builder.py` | 常量/符号/函数索引 → 资源段 |
| `compiler/fas_writer.py` | 指令流 → FAS4 二进制 |
| `compiler/opt.py` | 优化器：9 个 pass 跨 O1-O3 级别 |
| `compiler/analyzer.py` | 编译分析与统计（--analyze/--report） |
| `compiler/dep_analysis.py` | 调用图/依赖分析图模型与 text/dot/mermaid 格式（analyze） |
| `compiler/roundtrip.py` | 编译往返冒烟（裸内存管线，roundtrip） |
| `asm/assembler.py` | 反汇编/汇编（.fas ↔ .lasm） |
| `asm/opcodes.py` | 操作码定义与编码函数（codegen/linker/汇编共用） |
| `compiler/linker.py` | 多文件 FAS 链接器 |
| `compiler/vlx_builder.py` | VLX 容器构建器 |
| `tools/validate.py` | 生成的 `.lsp` 语法验证器 |

工具脚本（`tools/decrypt_fas4.py`、`tools/fas-split.py`、`tools/fas-analyzer.py`、`tools/crack_key.py` 等）使用 `core/fas_core.py`。ZELX 工具（`tools/zelx_info.py`/`zelx_diff.py`/`zelx_build.py`）基于逆向 LispConverter.exe，格式见 `docs/zelx-format.md`。

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
| RemoveDeadFuncs | 删除未被引用且非命令的函数（仅当有入口点时） | O3 |

## 命令

```sh
# 编译 + 优化
atlispcc compile -O2 input.lsp output.fas
# 反编译（tests/cad/i18n-cad.fas 为仓库内 CAD 自包含样本）
python -m decompiler.fas4_decompiler tests/cad/i18n-cad.fas output.lsp
# 验证输出
python -m tools.validate tests/fun.lsp
# 链接
atlispcc link lib.fas main.fas -o combined.fas
```

```sh
pip install -e ".[dev]"                 # 安装依赖 + dev 工具（开发模式）
python -m pytest                        # 运行测试
python -m py_compile decompiler/fas4_decompiler.py # 快速语法检查
python -m build                         # 构建分发包
black .                                 # 格式化
mypy .                                  # 类型检查
```

Makefile 快捷目标：`make test`（pytest）、`make check`（一键全量检查，等价 `./scripts/run_tests.sh`）、`make lint`、`make format`、`make build`、`make clean`。

## 测试

**测试文件在 `tests/` 目录下**（pytest 风格，456 用例：454 passed + 2 skipped）：
- `test_parser.py`（21）、`test_lexer.py`（11）、`test_symbol_table.py`（10）、`test_analyzer.py`（9）、`test_cli.py`（28）、`test_compile_decompile.py`（74）、`test_compiler_output.py`（75）、`test_optimizer.py`（32）、`test_linker.py`（13）、`test_assembler.py`（8）、`test_disasm.py`（9）、`test_resource_stream.py`（25）、`test_packages.py`（4）、`test_vlx_builder.py`（3）、`test_variadic_args.py`（17）、`test_zelx.py`（5）、`test_diagnostics.py`（20）、`test_atlisp_u_byte_identity.py`（70：atlisp_u 全量 byte-identity + roundtrip + **kernel 67 文件 × CAD golden 参数化**）。

一键运行全部检查：`./scripts/run_tests.sh`（py_compile + pytest + disasm→asm 往返 + byte-identity 状态）。

手动测试文件 `tests/test_*.lsp` 也在该目录；CAD 兼容矩阵源文件 `tests/compile_src/01_math.lsp`…`16_i18n.lsp` 是编译/往返测试的 fixture（16 份），源码与 CAD golden `.fas` 分开存放（`tests/compile_src/*.lsp` + `tests/cad/*_cad.fas`），由 `scripts/cad_verify.py` 编译加载验证。`tools/validate.py` 的 `SYMBOL_RE` 允许 `&`/`@`/`%`（`&optional`/`&rest`、`@::pkg`、`opt%` 等合法 AutoLISP 符号）。

## 兼容性（FAS4 字节码格式，与 AutoCAD 编译器一致）

- seg0 = 函数字节码（`<nsyms> $...`），seg1 = 资源段（常量/符号/函数索引）
- 紧凑 stub 格式 `total_size = len(seg0) + 1`（CAD 实测恒等）；自包含格式 `total_size = len(seg0_payload)`。`FasWriter.write(..., compact=True)` 走前者（CLI/链接器/紧凑汇编）
- **汇编器（`asm/assembler.py`）同时支持两种布局**：`.lasm` 头部 `.format compact|selfcontained` + `.nsyms N` 指令；紧凑 stub 用 CAD 编码（USUBR/FUNC 3 字节、`PUSH_VALUE[0]` 单字节、CLEAR_ARGS `19 <argc> 00`）。`disasm → asm` 往返 seg0 逐字节一致，紧凑产物可在 CAD 加载执行。重复符号槽在 `.lasm` 中输出 `[idx]` 保证字节可逆
- 紧凑 stub 生成规则：中间 setq 无 POP、尾 setq 先 DUP、无 else 的 `if` 补 PUSH_NIL、有参函数末尾 `19 <argc> 00`；含 foreach/repeat 的函数 DEFUN 头 `b1=argc+直接体并发循环深度`（嵌套 lambda/defun/quoted 内循环不计）
- **`foreach` stub 协议**（t16）：列表求值存局部槽 → `PUSH_G <var>; PUSH_NIL; INIT_ARGS 3`（内建遍历预载）→ loop 头 `GET_LOCAL; JMP32_IFNOT` → 体 `GET_LOCAL; CAR; SETQ_G <var>; GET_LOCAL; CDR; SET_LOCAL` 推进 → 体各式无 POP → JUMP → 尾部 `CLEAR_ARGS 1`
- **`repeat` stub 协议**（t17）：次数求值存局部槽 → loop 头 `GET_LOCAL; PUSH_INT8 0; FIX_LEQ; JMP32_IFNOT`（n<=0 退出）→ 体前 `GET_LOCAL; DEC; SET_LOCAL` → 体各式无 POP → JUMP；无预载，尾部无 CLEAR_ARGS
- seg1 滚动 XOR 加密（`find_key`/`decrypt_stream`），尾部含密钥长度字节 + 密钥 + `;fas4 crunch` 标记；段分隔符 `16 24 0d 0a`；`nsyms` = 符号槽数（资源注册顺序）
- seg1 资源流 = 模块头(`14 01 01 01 00`) + 代码引用 + 符号/字符串注册 + GVARINIT + DEFCODE + INIT_DONE + 模块代码；`seg1` 头 `items` = GVARINIT + INIT_DONE 计数
- **符号名统一大写**（`ResourceBuilder._enc_sym`）；字符串字面量不变；vla-/vlax- 前缀保留源码大小写（ActiveX 大小写敏感）
- **顶层表达式**（defun 之外）编译进 seg1 **模块代码**（非 seg0）：模块代码 = `DEFUN头 + [顶层表达式] + [函数注册尾: JUMP + PUSH_G <模块注册+2>; SETQ_G 1; PUSH_G 1] + END_DEFUN`；gvar 槽 = 符号槽 + 1；`FasWriter` 代码引用长度 = `total_size`
- **模块注册段**（混合 defun+顶层）：注册函数名 + 顶层表达式符号（连续 SYMBOL 合并 5b 块，遇 STRING 分块）；`nsyms = len(entries) - 模块注册符号数 + 1`；函数注册 GVARINIT st_init = nsyms
- **c: 命令模块代码**（`build_command_module_code`，t14）：命令函数在模块注册段每个独立 `5b` 块，首命令后插入 `56 vl-ACAD-defun 00 00`（`0x56` 编码、保留大小写）；`vl-ACAD-defun` **不进** `symtab.entries`；模块代码每命令 `PUSH_G <c>; FUNC_REF 2; PUSH_NIL; POP` 注册
- **c: 命令 + 顶层混合模式**（`_build_cad_module_code` + `n_cmds`）：`56 vl-ACAD-defun 00 00` 块插在源码序第一个命令之前；命令不独立成块（t14 纯命令才每命令独立块）；命令注册用 CAD 24 字节模式 `JUMP 0; PUSH_G b; SETQ_G c; PUSH_G c; USUBR(1,<vl槽>); POP; PUSH_G c; POP`，非命令仍 15 字节
- **`/ 局部变量` `_al-bind-alist` 协议**（t11）：含 `/ 局部变量` 的函数，CAD 用 `(_al-bind-alist '(loc1 ...))` 绑定而非 GET_LOCAL。符号收集在函数体符号后、参数前注入 `_al-bind-alist` + `(quote (locals...))` 常量；codegen 在 INIT_ARGS 后发 `PUSH_G <const>; FUNC 1, <_al-bind-alist>; NIL; PUSH_NIL; NIL; POP`；CLEAR_ARGS = argc + len(locals)。`_al-bind-alist` 以 `0x56` 保留大小写独立注册
- **符号槽顺序** = 按源码函数逆序，每函数内"字节码引用序"逆序收集函数体符号、参数紧跟其后；混合时顶层表达式符号排在函数体内建之前；递归函数名重复槽（`compiler/cad_symbols.py`）
- 多函数函数间分隔符 `16`（END_DEFUN）；多函数代码引用末函数 end = total_size
- 反编译回归参考：`tests/fun.lsp` 经 CLI 编译往返

反编译器同时支持两种布局：
- **自包含格式**（`tests/cad/i18n-cad.fas`）：seg0 含完整函数体 + END_DEFUN，函数目录来自 mvar 表重建
- **紧凑 stub 格式**（AutoCAD 编译器输出，`tests/cad/*_cad.fas`）：seg0 无 END_DEFUN，符号按资源注册顺序（`symbol_slots`）直接编址

**反编译关键解码规则**（`decompiler/fas4_decompiler.py`）：
- stub 中 `PUSH_VALUE[0]` 编码为单字节 `03`（非 3 字节），用有效符号上限 + 前导 `00`（NIL）/kwote 尾 `00 01 00` 启发式区分；调用协议占位 `03` 前总跟 `00`（NIL）
- 紧凑 stub 的 CLEAR_ARGS（0x19）为 `19 <argc u16> <00>`（3 字节）；USUBR/FUNC 3 字节 `35/51 <argc> <idx>`
- 反汇编歧义操作码：`03`（PUSH_VALUE）在 stub 中可能单字节或 3 字节，`0x03` 后跟有效符号槽时按 3 字节

生成器会发出包装辅助函数以避免内建冲突：`fas-polar1`、`fas-rtos1`、`fas-rtos3`、`fas-getvar2`、`fas-getvar3`，以及列表/关联列表/DXF 组码读取的 `IN_PARAM` 查找。

解码器问题在 `decompiler/fas4_decompiler.py` 中修复，永远不要修改生成的 `.lsp`。

## 测试中的关键陷阱

- **CLI 与裸管线的顶层表达式差异**：`compiler.cli.cmd_compile`（CLI）把顶层表达式编译进 seg1 **模块代码**（CAD 标准），而 `tests/test_compile_decompile.py` 内的裸内存管线把它们留在 seg0 字节码。两者反编译结果不同。写往返测试时二选一保持一致，**不要**混用两个管线的 `compile_and_decompile`。
- **黄金比对（golden）fixture 必须是 CAD 重新编译的产物**：`D:/atlisp-test/cad_t*.fas`（7月31）版本戳 `;A7/31/26` 与当前输出 `;A8/4/26` 不同，整文件比对必然失败。`tests/cad/` 内 `*_cad.fas`（8月3-4 重新编译）可用作 byte-identity golden。
- **t-series golden 覆盖现状**：源文件已迁移至 `tests/compile_src/`（16 份），golden `.fas` 保留在 `tests/cad/`（18 份）。`test_t_series_byte_identity` 对 6 份仍有效 golden 逐字节比对 + 16 份 compile_src 结构断言。另含 `t22_activex_cad.fas`（vla-/vlax- ActiveX）锁入同一回归。

## 文档

- `README.md` — 使用者文档（安装、CLI 用法、工作流、工具参考）
- `docs/lasm.md` — LASM 汇编语言参考（disasm/asm）
- `docs/compilation-process.md` — 编译过程说明（.lsp → .fas 各阶段详解）
- `docs/development.md` — 架构详解、代码规范、调试指南
- `docs/development-plan.md` — 开发计划、已验证兼容性矩阵

## CAD 测试与真机验证

**自动化真机验证**（推荐，每用例独立 CAD 连接，避免会话失效）：
```sh
make cad-test        # 或: bash scripts/run_tests.sh --cad
# 等价直接运行: python scripts/cad_verify.py
```
`scripts/cad_verify.py` 编译 `tests/compile_src/` 的 16 个模块 → 逐项在 CAD 加载 → 断言返回值（16 项断言，对应原 t01-t24 系列功能）。测试文件编译到 `D:/atlisp-test/`，CAD 中加载 `(load "D:/atlisp-test/test_all_final.lsp")`。

### 已验证功能（AutoCAD 24.1s）

- 简单函数、递归、if/while/cond、局部变量、字符串拼接、2-3 函数交叉引用、尾递归、`&optional`/`&rest`、顶层 setq/set（defun 前后混合）、`fun.lsp` 逐字节一致 ✅
- t-series 真机功能验证 25 项（`scripts/cad_verify.py`）：t01-t15、t18 基础 + t16_foreach/t17_repeat（循环 stub）+ t19/t21_variadic（并入 `09_variadic.lsp`）+ t20_kwote（并入 `06_higher_order.lsp`）+ t22_activex（vla-/vlax-）+ t23_command（command-s）+ t24_star_error（`15_error.lsp`）✅
- **t22 关键修复**（真机暴露）：vla- 符号名保留大小写（`vla-get-count`→`vla-get-Count`）；值位置 `T`/`t` 注册符号槽（`PUSH_VALUE` 引用，nil 仍内联）；`_patch_usubr_idx` 对超出 gvar 表的 USUBR/FUNC 目标按 `gvar 槽 = nsyms` 编址
- **t21 修正**：`(&optional factor &rest rest)`（min=0）触发 §3.5 CAD 不收集 rest 限制，改为 `(factor &rest rest)`（min=1）

### @lisp 综合包编译（atlisp_u）

`tests/atlisp_u.lsp`（502 函数 + 221 顶层语句 + 80 kwote 回调）编译产物在 CAD 真机**模块代码完整执行、功能全部可用**。关键机制：
- 顶层 `(progn ...)` 展开、条件/嵌套 defun、多 kwote 改写
- **commands + 顶层混合** gvar 槽重映射（`compiler/_gvar_map.py` 解析 seg1 模块注册段；`_offset_slots` 二次生成模块代码）
- **大文件 USUBR/FUNC 宽格式**：符号槽 >255 用 5 字节 USUBR（`35 argc idx16 flags=3`）、6 字节 FUNC（`51 argc idx16 flags=1 00`），小文件保持 3 字节
- 模块代码槽引用 = 资源 gvar 表(rg)（操作数 = rg 索引）；`in-package`/`use-package` 是编译期指令（模块代码不发射调用）；setq 值 = 函数符号 → `PUSH_G`、set 值 = 函数符号 → `PUSH_VALUE`；模块代码 REAL 常量内联 `PUSH_REAL`
- **KNOWN_ISSUES**：混合文件顶层 `(setq X (lambda ...))` 的 `-lambda-` SUBR 未实现；@::fasext/@::vlx 绑定为引用数据 LIST（调用报 "函数错误: (LAMBDA ...)"）——不影响加载
- **byte-identity**：**@lisp_u 全量 byte-identical（seg0+seg1+nsyms 与 CAD golden `tests/atlisp_u_cad2.fas` 逐字节一致，2026-08-29）**。最终修复见「atlisp_u 全量 byte-identity（2026-08-29）」。

### atlisp_u 全量 byte-identity（2026-08-29）

atlisp_u 从 99.3%（seg0 622 字节 diff + seg1 9630 字节 diff）修到 **100% byte-identical**，涉及 4 个文件 8 项根因：

1. **cad_symbols.py 共享参数裸 lambda 归属**：移除 `_shared_last` 对裸 lambda 参数的 `_excluded` 拦截（atlisp_u `msg` = cleanup-dcl 等 6 函数参数 + @::voice-test 局部）。旧逻辑误排除使 msg 落 cleanup-dcl 组（fg[2132]），CAD 实际注册在 @::cleanup-dcl 组（fg[2235]，msg 由参数拥有者 args 循环注册）→ fg/seg0 错位 103 槽。
2. **patch.py wide SETQ_G fallback 移除**：rg 表列表常量冲突检查（`ITEM fg[905] vs :DIALOG rg[905]`）对所有 CAD golden 均不触发——REVERSE-DEPS/PKG-TO-INS/@::*COMPAT1-DONE* 的 SETQ_G 操作数落 `nsyms-1` 错槽。改为一律用 fg 槽（`gvar_map[sym]-1`）。
3. **compile_cmd.py 嵌套 defun `#dup` FUNCOBJ 反查**：嵌套 `*error*`（与顶层同名 → `*error*#dup` 键）不在 `_fo_by_name`（按原名索引），funcobj_map 缺失 → PUSH_G 错槽。按 `_nested_defun_names` 反查。
4. **compile_cmd.py 混合文件 `_lam_slot` 补 `+n_cmds+_tl_lam_count`**：`top_lambda_slots` 对混合文件（含 defun）的 setq-lambda 槽公式旧为 `2*len+tlc-i`，缺 `n_cmds`+`_tl_lam_count` → 模块代码 setq-lambda 绑定 PUSH_G 错 2。
5. **compile_cmd.py `_tl_funcobj_slots` 补 `+n_cmds`**：顶层 kwote lambda func-obj 槽公式缺 `n_cmds`（atlisp_u 1303 = 1542-239，旧公式 1302）。
6. **module_code.py `_reg` b 槽让位规则统一**：顶层 kwote lambda func-obj 占用 b 序列一槽（`tl_funcobj_slot` = base - tl_pos）。旧规则仅 `i >= n_pre` 时 -1（setup tl_pos=8 = n_pre 恰好成立），atlisp_u tl_pos=239 ≠ n_pre=1 → TAIL 中段函数 b 值差 1。统一为 `i >= base - tl_funcobj_slot` 时 -1。
7. **module_code.py `_mid_count_of` top-lambda-only 索引**：`_mid_counts` 构建时跳过 top-lambda 提升 defun（fasext/vlx/wget），索引比 func_names 少 3。旧 `_emit_mid_for`/`_has_mid` 直接用 `_mid_counts[i]` 错位；且用 `_skip`（含 `_cond_defun_names` C:%/C:%%）偏移会过度减。改为仅按 `skip_funcs` 偏移；`_skip` 函数跳过 `_reg_emit` 但**仍发射 mid 语句**（CondDefunBind 块在跳过位置发射）。
8. **module_code.py `set` 协议纯顶层/混合不同槽**：`(set 'X (lambda ...))` 纯顶层（net/wget）PUSH_G = `_lam_slot`，混合文件（atlisp_u @::wget）PUSH_G = `_lam_slot + 1`（`n_funcs > 0` 时 +1）。

验证：atlisp_u 100% byte-identical + kernel 67/67 + merged_2/4/8/16 IDENTICAL + pytest 456 passed + 2 skipped。

### i18n 混合模式拆件

- p01-p07 全部 byte-identity（`tests/cad/i18n_split/`，seg0+seg1+nsyms 对齐 CAD golden）✅
- `i18n.lsp` 原文件（混合 defun+顶层+kwote）seg0+sec2 逐字节一致 ✅（锁入 `test_i18n_original_byte_identity`；seg1 模块代码仍有 48 项 pre-existing diff，`test_i18n_original_byte_identity` 保持 skip）

## kernel 真机 byte-identity 状态

对 `../kernel/src/` 下全部 67 个 `.lsp` 逐个编译并与 CAD 真机（`(vlisp-compile 'st ...)`，AutoCAD 24.1s）产物逐字节比对。工作流：`python scripts/mcp_cad.py eval "(vlisp-compile 'st <in> <out>)"`（模式 `'st`，CAD 文档打开时才可编译；路径用正斜杠）。

### 当前状态：67/67 byte-identical（全部一致）

67/67 全部通过编译产物验证（CAD 加载无访问冲突）+ 逐字节比对（seg0+seg1+nsyms）。
逐文件状态用 `scripts/kernel_compare_http.py`（ours→compare）复核。

> 注：2026-08-27 远程恢复 4 份被误覆盖的 golden（platform-api/ax-request/module/probe，
> CAD 真机 2026-08-26 产物，见 036c63e）。

**已修复（2026-08-27）**：

- **`sub-system/ui/panel.lsp`**：顶层 `(if is-gcad (progn (defun C:% ...) (defun C:%% ...) (foreach ...)))` 条件 defun 模块代码 + `-lambda-` DEFCODE 顺序 + const 编址。详见「条件 defun 绑定（panel.lsp）」。
- **`sub-system/condition/nlp.lsp`**：LET 带裸变量结构（`PUSH_VALUE <bare-var>...; EVAL <n_bare>,7`）+ let body 非末 form 按值/尾上下文 + `USUBR(<n_form+1>, LET)` argc。详见「LET 原生编译」。
- **`sub-system/config/dialog.lsp`**：progn 语句双 POP（progn 自 POP 后外层循环再 POP）、值上下文 progn 末 form 误 POP、尾 repeat 末 form 丢 DUP。详见「progn/repeat 栈平衡」。
- **`sub-system/ui/menu.lsp`**：`vlax-for` ActiveX 枚举协议 + 局部槽序修正（详见「vlax-for 枚举协议」）。seg0+seg1+nsyms 全对齐 `tests/cad/kernel_golden/sub-system/ui/menu.fas`（`--encoding gbk` 编译比对）。同时恢复 `init/compat.lsp`、`net/reload.lsp` byte-identity（回退一处不必要的 kwote 插入位置改动 `_rev[: _j]`，恢复 `[: _j + 1]`）。

### 条件 defun 绑定（panel.lsp golden 实测，2026-08-27）

顶层 `(if is-gcad (progn (defun C:% ...) (defun C:%% ...) (foreach ...)))`：
- **`_hoist_conditional_defuns`**（cli.py）：defun 体提升为顶层独立函数（进 seg0 + DEFCODE），if 内以 `CondDefunBind(name)` 标记替换（ast_nodes.py 新增节点）——运行时绑定留在 if 守卫内，非无条件注册。
- **模块代码 `_stmt_bytes`**：检测 then 分支含 `CondDefunBind` 时手动组装 if：`PUSH_VALUE <cond>; JMP32_IFNOT <else>; JUMP +0; [每个绑定: PUSH_G <func-obj>; SETQ_G <sym>; PUSH_G <sym>; USUBR(1, vl-ACAD-defun) 4字节; PUSH_NIL; POP]; [foreach]; JUMP +1; PUSH_NIL`。func-obj/b/c/vl 槽按 `_reg(i)` 公式预计算（panel C:% b=39/c=14、C:%% b=38/c=12、vl=13）。绑定字节已是最终 gvar 槽，**不再经 `_offset_slots`**；cond/foreach 单独 `_offset_slots` 后拼接、手动 patch JMP32_IFNOT/JUMP 偏移。
- **跳过无条件注册**：`_cond_defun_names`（扫描 other_forms 的标记）并入 `_skip`，TAIL `_reg_emit` 跳过 C:%/C:%%（b/c/vl 槽仍按公式保留给其他函数）。
- **`-lambda-` DEFCODE 顺序 = 全局发射序逆序**（cli.py `_lambda_batches`）：纯 kwote 文件按函数逆序 + 各函数 `reversed(_fnl_raw)`（`_fnl_raw` = codegen `_nested_lambdas` 发射序）。@::panel-calc-layout 3 个 kwote lambda 发射序 [inner@88, outer@69, bt-man@180] → DEFCODE [bt-man, outer, inner] = [2961, 2850, 2869]。log 兄弟 lambda 发射序 = offset 序，逆序 == offset 逆序，二者一致；嵌套 kwote lambda offset 序 ≠ 发射序，须用发射序。含立即 lambda 的文件（safe-eval，`nested_lambda_order` 置位）保持 func_offsets 源码序 + 源码序覆盖。
- **前置 DEFCODE 父-子链修正允许 `-lambda-` 父**（resource_builder.py + cli.py `_pre_all`）：外层 kwote lambda（@::panel-calc-layout outer@2850 体内嵌 inner@2869）须父在前，否则 offset 降序 [2961, 2869, 2850] 错位。此前 `_is_lambda_key` 跳过 lambda 父，仅真实嵌套 defun 参与。
- **`_offset_slots` const 编址**：CONST fallback `idx+1`，仅当 const 注册在首个 c: 命令槽之后（`first_cmd_slot` 传入）才 +n_cmds——panel foreach 组 const（`'("1" "AI"...)`、`'(princ)`）在 C:% 之前不加（gvar 槽 = idx+1）；menu/voice const 在 vl-ACAD-defun 之后加（idx+1+n_cmds）。
- **`_patch_usubr_idx` 双注册分支守卫**：`_rs - module_reg_count - 1` 须 `0 <= _body_slot < nsyms`，否则落到 `_res_offset` 分支——BYTELEN（/local 在 3 个函数体区各注册一次、非模块区双注册）`351-35-1=315 ≥ nsyms` → 用 `_rs - _res_offset` 编址（351-100=251 → 操作数 250），旧 `nsyms-1` 错位 15。

### LET 原生编译（nlp.lsp golden 实测，2026-08-27）

- **裸变量绑定**（`(let ((v e) bare1 bare2...) body...)`）：CAD 先把裸变量符号 `PUSH_VALUE <slot>` 推入（在绑定值之前），再对每个有值绑定 `value; USUBR(1, <var>)`，最后 `EVAL <n_bare>, 7`（argc = 裸变量数，CMD-MATCH-WEB 实测 `EVAL 2,7`）。无裸变量走 event-bus 结构 `value; USUBR(1, var); EVAL 0,7`。
- **let body 值累积**：let body 的**非末 form** 也按值/尾上下文编译（`_emit_expr(_tail=True)`）——else-less if 补 PUSH_NIL、表达式不 POP、foreach/repeat 走尾协议（nlp cmd-ai-fallback 4 form 实测 forms 0-2 值均保留）。
- **let 尾 USUBR argc**：let body 最后 form 为 if 时，end 后 `USUBR(<n_body_form+1>, LET)`（nlp 4 form → argc 5，event-bus 1 form → argc 2），由 `_emit_let` 经 `_in_let_tail` 传 argc。

### progn/repeat 栈平衡（dialog.lsp golden 实测，2026-08-27）

- **progn 语句双 POP**：语句上下文 progn 自 POP 末 form 值后，外层循环（progn/repeat/while/lambda 体/函数体）不再补 POP——排除元组补 `Progn`。
- **值上下文 progn 不 POP**：`(set_tile ... (progn ... (if ... rd%)))` 的嵌套 progn 是实参（值被消费），末 form 值保留——progn 分支末 form POP 仅限 `_in_stmt_ctx or _module_mode`。
- **尾 repeat 末 form**：同尾 while/foreach，用 `_emit_expr(_tail=True)`（dialog save-config `(repeat ... (setq i (1+ i)))` 实测 `DUP SETQ_G`）。

### vlax-for 枚举协议（menu.lsp golden 实测，2026-08-27）

- **parser**（parser.py:145）：`(vlax-for var collection body...)` → `ForeachNode(name='vlax-for')`。
- **codegen**（`_emit_vlax_for_stub`，codegen.py）：`<coll> 求值 → FUNC 1 <collect-init>; NIL; PUSH_NIL; NIL → SET_LOCAL（iterator 状态）→ PUSH_G <var>; PUSH_NIL; INIT_ARGS 3（预载）→ loop: GET_LOCAL; FUNC 1 <collect-next>; NIL; PUSH_NIL; NIL; DUP; SETQ_G <var>; JMP32_IFNOT end; body(无 POP); JUMP loop; end: GET_LOCAL; FUNC 1 <collect-release>; NIL; PUSH_NIL; NIL; POP; CLEAR_ARGS 1`。collect 调用用 `FUNC 1` + `NIL; PUSH_NIL; NIL` 清理（同 `command`/`_al-bind-alist`），非 USUBR 的 `00 03`。尾上下文（kwote lambda 体末）同 list foreach 的 PUSH_NIL 占位 + 体首 POP。
- **符号收集**（cad_symbols.py `_collect_byteorder` ForeachNode 分支）：vlax-for 额外注册 `collect-init → var → collect-next → body → collect-release`（跨函数共享单槽、小写）。
- **资源段**（resource_builder.py）：collect-* 进 `_CASE_PRESERVE_SUBR_BLOCKS`，独立 `56 <name> 00 00` 块（同 `_al-bind-alist`/`kwote`/`ads-cmd`）。
- **foreach 循环变量**（cad_symbols.py）：var 是**本函数 `/ 局部变量`** 时，即使与 `_unique_params`（它函数唯一参数）同名也在 var 位置独立注册（menu.lsp `category` = cuix-add-category 参数 + remove-pkg-menu `/ local` + 外层 foreach 变量；`_al-bind-alist` 绑定协议需本函数槽）。非本函数局部仍按 `_unique_params` 跳过（cache.lsp `subdir` 复用参数拥有者槽）。

### 已固化的通用规则（对拍多次确认，后续改动须遵循）

以下规则已在代码中实现并锁入 golden，修改相关逻辑时须保持：

**编址（`cli.py _patch_usubr_idx`）**：
- 普通符号 `PUSH_G/PUSH_VALUE/SETQ_G` 操作数 = gvar 槽 - 1（fg 表命中）；表外符号（参数/末尾常量）gvar 槽 = nsyms（操作数 = nsyms-1-offset）
- 纯函数文件表外符号按 `fg_slot = _rslot - _res_offset` 编址（`_res_offset` = 末 fg 符号的 `_res_slot_of - fg 槽` 差）；混合文件顶层变量双注册（模块区 + 函数体区）用 `module_reg_count` 减法（`has_top_forms` + `count>1` 守卫）
- `_al-bind-alist` locals 常量 PUSH_G = `_al-bind-alist` 槽（资源注册序，不随 `-lambda-` 偏移）；quoted 单符号走 const 槽或 gvar 槽；`_strip_list_markers` 字符串/`'NIL'`/dotted 归一化
- **quoted 单符号 const 化**（dcl/audit）：唯一参数被其它函数 quoted 引用（`'STR` = @::dcl-escape 参数 + @::dcl-attrs-to-str `(eq 'STR (type ...))` 引用）时注册 const 并**延迟到资源序末尾**（`_deferred_consts`），owner args 循环跳过（`_quoted_param_collected`）；共享参数 quoted 引用照常收集（SYMBOL 槽）。quoted `'a` 单符号本身是普通 SYMBOL 槽（非 const）；仅列表/lambda/dotted 等复合结构 const 化
- **deferred 多叶子 const**（safe-eval 白名单 `'(car cdr ...)`、audit `'(:package.install ...)` 截断关键字）：按 const 叶子**序列**在资源流中匹配起始位置 `_res_to_fg` 编址；`_al-bind-alist` locals const 检测排除 `:keyword` 叶子
- `-lambda-` 槽：纯 `-lambda-` 文件按 `nsyms-1-_li`；含嵌套 defun 时按 `lambda_slot_map`（`nsyms - n_pre + pos`，`_pre_all` 位置，与 func-obj 共享高位槽区）
- 表外字符串操作数 = 资源 symbol_slots 真实索引（< nsyms 时）；emoji 等 GBK 无法编码字符在资源流注册为 `\U+XXXX` 转义（str_map 查询须转义）
- 大文件（nsyms>256）USUBR/FUNC 5/6 字节宽格式
- **模块注册段**：`nsyms = len(entries) - 模块注册符号数 + 1`；函数注册 GVARINIT st_init = nsyms；DEFCODE 后 GVARINIT var_pos = 模块注册符号数 + 2。顶层表达式符号与 defun 名按源码逆序交错注册

**符号收集（`compiler/cad_symbols.py`）**：
- `_all_params` 排除：函数体收集排除全部参数名（含唯一参数），由参数拥有者 args 循环注册；被其它函数引用的参数名（config/store `type`）CAD 注册在参数拥有者组
- 共享参数注册在逆序最后引用者（`_shared_last`，kept 扫描大小写不敏感、按 `_shared_ci` 大写集匹配并存入规范键）；局部同时是其它函数参数时由**后处理**拥有者注册（`_local_is_param_order`：param 参数拥有者后处理 → args 循环注册；local 局部拥有者后处理 → 函数体组/局部循环注册）
- kwote lambda 参数统一注册符号槽 + `-lambda-` 体 `PUSH_VALUE` 读取；可收集参数在 kwote 块开头（forward）；`_all_params` 排除参数拥有者逆序更晚处理的情况；quoted 唯一参数被逆序更晚函数引用时收集（`_quoted_param_collected`），owner args 循环跳过
- kwote 块插入：插到调用者后；lambda 是调用**首参**时插到后续字符串后（锚点不跳过字符串）；多 kwote 同调用者链式插入；无调用者时 kwote 在块体前；仅源码序第一个 lambda 插 marker；`(function 符号)`（非 lambda）不生成 kwote 标记
- `_al-bind-alist` 全文件共享单槽：注册在源码序第一个带 `/ locals` 的函数（多函数）；kwote lambda locals == 函数 locals 时早注册；嵌套 defun 外层有 locals 时归外层
- **T 槽**：cond else 键 `t` 与值位置 `t` 去重（T 槽位置由**外层 cond 的 else 键** forward 序第一个 force t 决定，纯顶层 reversed 注册序最后一个；内层 else 键 t 与值位置 T 复用该槽）；混合文件模块区与函数体区各注册一次；语句上下文（值被丢弃）progn 末 `T`/`nil` 不注册符号槽（`_is_tail` 传播）
- let 变量：bare 符号变量先于值绑定；`_all_params` 排除；let 体末 form 传播 `_is_tail`
- 顶层 kwote lambda 调用实参（setup `(if @::*uris* (mapcar (function (lambda ...)) ...))`）：CAD 把 lambda 体符号注册在源码位置的独立函数体组（`_collect_multi` 构造伪 Defun 复用函数体收集）
- `_seen`/`_in_name_set`/`_ci_ref_key` 对普通符号大小写不敏感、字符串/vla-/vlax-/`__` 键大小写敏感

**codegen**：
- `_in_stmt_ctx`（`_emit_stmt` 置位，值位置经 `_value_ctx` 清位）：裸语句 if/cond 才发 POP，值位置 if 不 POP
- 尾上下文（`_in_tail_context`）setq 补 DUP 保留返回值；`if` 条件/while 条件内值位置 setq 补 DUP
- 循环（while/foreach/repeat/cond）自带栈平衡，语句上下文 POP 排除列表须含它们；非尾 progn 末 if 值上下文补 POP
- **`if` 细则**：语句上下文（值被丢弃）then/else 分支末尾发 POP 丢弃分支值（else 为 setq 时 SETQ_G 已消费无需 POP）；then 为 while/foreach/repeat（自带栈平衡）时不 POP；then/else 为常量 `nil`/`T` 时省略整个分支代码（`PUSH_NIL; POP` 是纯 no-op）
- **`cond` 细则**：语句上下文自平衡（末动作按语句发射，外层不 POP）；末子句 `(t ...)` else 且语句上下文时省略死代码 `PUSH_NIL` 默认值；空体子句（无动作）不发入口 POP；条件测试值是 cond 的"值"（`_tail=True`，测试内 setq 补 DUP 保留返回值）
- **`while` 尾上下文**：多语句体中间语句 POP、尾语句 `_emit_expr(_tail=True)` 补 DUP 保留值（单语句体不受影响）
- **`foreach` 细则**：非尾 foreach 体多语句每句 POP（值被丢弃）；尾 foreach 体最后语句走值上下文（if 无 else 补 PUSH_NIL）；列表是 foreach 的输入（值上下文，须清 `_in_stmt_ctx`，否则列表为 if 时 else 分支被误 POP）
- **`repeat` 尾上下文**：loop 头 PUSH_NIL 占位 + JMP32_IFNOT 后 POP（同尾 while 协议）
- **立即 lambda `((lambda ...) args)`**（52/67）：实参先求值（留栈）→ `_emit_nested_lambda`（JUMP + `-lambda-` DEFUN）→ `PUSH_G <-lambda->; EVAL argc, 7`；不发 CLEAR_ARGS（host 函数末尾发）。`_collect_byteorder` ListExpr 分支先收 args 再收 lambda 头；参数进 `_param_lam_hosts`
- **裸 lambda 值**（file-utils/update/menu/load）：`(setq *error* (lambda ...))` 或函数返回 `(lambda ...)` 走 `_emit_nested_lambda` + `PUSH_G <-lambda-槽>`；quoted `'(lambda ...)` 仍走 `_emit_quoted`（数据 const）。`_collect_byteorder` LambdaNode 分支注册参数符号槽 + 体符号
- **let 原生 LET**（event-bus byte-identical）：`_emit_let` = `<e求值>; USUBR(1, <var槽>); NIL; PUSH_VALUE[0]; EVAL 0,7; body`；绑定变量普通符号槽 PUSH_VALUE 读取；let 体末 form 尾上下文（`_in_let_tail`：if 分支 setq DUP、label_end 后 `USUBR(2, LET); NIL; PUSH_VALUE[0]`）。nlp 的 CAD 用另一种结构（`PUSH_VALUE <var>; <e求值>; EVAL 1,7`），待真机确认
- 嵌套 defun 原生内嵌（见下）；嵌套 defun 尾上下文补 `PUSH_G <sym>`；0 参 `-lambda-` 无 CLEAR_ARGS
- `command` 每参数独立 `FUNC 1 <ads-cmd>`（非单次 `FUNC <argc>`）；`ads-cmd` 0x56 保留大小写独立块
- **模块代码**：defun 注册与 mid 顶层语句按源码位置交错（`_interleave_mid`，`sum(mid_counts)>0` 时）；`n_pre` = 首个顶层语句之前的连续 defun（START 注册，跳过 globals/in-package/defpackage），其余 TAIL 注册；`_n_globals` 只排除 Defun。顶层 setq 单对 DUP（多对末对已由 codegen 生成，`_stmt_bytes` 不重复插）；setq 值 = 函数符号 PUSH_G、set 值 = 函数符号 PUSH_VALUE；模块代码跨函数调用用模块注册槽（`_module_code_ctx`，不分配重复符号槽）

## 纯顶层 set/setq-lambda 协议（setq-lambda.lsp byte-identical）

`(setq @::fasext (lambda (file) ...))`（纯顶层，无 defun）经 `_defun_from_lambda` 转 Defun 复用 `generate_function`：
- **seg0**：`-lambda-` 是完整 compact stub（`14 <argc>x3 00` + GET_LOCAL + INIT_ARGS + 体 + CLEAR_ARGS + END_DEFUN，函数间 `16` 分隔、最后无 END）。**CAD 的 USUBR 用 5 字节宽格式**（`35 <argc> <idx16> 03`，flags=3，非小文件 3 字节）
- **nsyms** = fg 表长度 = `1 + len(top_lambda_body_syms)`（setq-lambda golden 12 = 1 + 11 第二区符号），非 `1 + len(top_lambda_binds)`
- **符号表布局**：第一区（模块注册段，仅顶层表达式符号）→ GVARINIT(0, 第一区数+2) → 函数目录（`_func_ranges_bytes`：每个 `-lambda-` 的 (offset . end)）→ 第二区（lambda 体符号 + 参数 + 最后调用名，跨 lambda 去重 strcat）→ `GET_LOCAL; GVARINIT(0, 第二区数+1)`（module_id=最后符号 FILE → build_mvar_tables 判 table1 = fg 表）→ 多 DEFCODE（offset 大的先）→ `GVARINIT(第一区数+2, 函数数)`
- **fg 表**（`_patch_usubr_idx` 映射依据）= 代码引用（fg[1]）+ 第二区符号（fg[2-11]），FILE 作 module_id 不占槽；`gvar_slot` 未命中返回 nsyms（参数 file→11）
- **模块代码绑定**用 setq 协议 `JUMP 0; PUSH_G <lam槽+1>; DUP; SETQ_G <sym>`；`-lambda-` 槽不在 symtab/gvar_map，PUSH_G 直接用 `_lam_slot + 1`（不能用 `_slot_gv`）
- **`_patch_usubr_idx`**：`top_lambda_args` 按 seg0 出现序传参；参数绑定 PUSH_G 与参数读取 PUSH_VALUE 用 `gvar_slot(arg) - 1`（str-vlx fg[9]→8）；参数读取槽识别 `nsyms - len(cur_args) <= idx < nsyms`
- `_collect_single` 的 `_has_top_lam` 分支走 `_register_module`（第一区）+ 3b 块（第二区）；普通纯顶层仍全局逆序（test-cond/setcmp/set5/setqa 不变）

**混合文件（defun+顶层）顶层 setq-lambda**（platform.lsp byte-identical）：func_offsets 键改用 `-lambda-`/`-lambda-#N`（不提升为同名 defun），`_top_lambda_offsets[offset] = 原名` 供 `_patch_usubr_idx` 按 seg0 offset 解析参数；`-lambda-` 键**不进** `symtab.function_offsets`/entries（否则纯顶层 setq-lambda byte-identity 会破）。纯顶层与混合文件统一走 `_rewrite_top_lambda_binds`（kwote 标记）入口。

## 嵌套 defun 原生编译（2026-08-25，P0-A）

函数体内 `(defun inner ...)` 不再降级为 setq-lambda 数据，而是发射 CAD 原生内嵌 DEFUN：

- **seg0 布局**（n1-n6 CAD 实测）：`DEFUN outer; [体]; JUMP <skip>; DEFUN inner; <体>; CLEAR_ARGS; END_DEFUN; <skip>: PUSH_G <inner-func-obj>; SETQ_G <inner-sym>`——内嵌 DEFUN 出现在外层函数体语句位置，JUMP 跳过（运行时由模块加载器预定义）；注册 `PUSH_G/SETQ_G` 绑定符号到函数对象。嵌套函数也进函数目录（DEFCODE 前置注册）
- **codegen**（`codegen.py _emit_nested_defun`）：JUMP + DEFUN 块 + 注册；嵌套参数按真实符号槽绑定/读取（`_nested_defun_depth`）；嵌套**递归**不 add_force 重复槽；嵌套 defun 是函数返回值（尾上下文）时 CAD 在 `SETQ_G` 后再推 `PUSH_G <inner-sym>`。defun-q（`(defun-q ...)`）嵌套仍走旧 setq-lambda 路径
- **符号收集**（`cad_symbols.py _collect_byteorder` Defun 分支）：嵌套块按「函数名 → 体符号正向 → _al-bind-alist → locals 常量 → 参数」注册（外层整体逆序后落在外层体符号最前）；闭包引用外层局部不排除；多参数嵌套参数逆序
- **func-obj 槽**（`cli.py funcobj_map` + `symbol_table.add_funcobj`）：codegen FUNCOBJ 占位槽（发射序 = 内层先于外层）→ `_patch_usubr_idx` 重映射为最终槽（base + DEFCODE 前置 offset 升序排名）
- **`-lambda-` 槽（`lambda_slot_map`）**：与 func-obj 共享高位槽区，按 `_pre_all` 位置编址（`nsyms - n_pre + pos`）；string-utils `[lambda@1740, lambda@816, s2la@638]` → s2la=93、lambda=92/91
- **resource_builder**：嵌套 defun 前置 DEFCODE（offset 升序，`-lambda-` 之后）；FUNCOBJ 跳过符号块发射；主 DEFCODE 区剔除嵌套
- **回归**：`tests/cad/nested/n1-n6 + s1/s2`（CAD golden 2026-08-25）锁入 `test_byte_identity_with_cad_golden`（8 用例）

## 已知限制（仍然有效）

- **变参 `&rest`/`&optional`：CAD 不支持，byte-identity 不适用**（large_synthetic 对拍）：CAD 编译器**不识别变参语义**，把 `&rest`/`&optional` 当**普通参数名**编译（`(a &optional opt &rest rest)` → DEFUN 头 argc=5、`&REST`/`&OPTIONAL` 当符号槽 GET_LOCAL、资源段注册这两个标记符号 nsyms +2），运行行为即错。atlispcc **正确支持**变参（t19/t21 真机功能验证通过），故含变参函数的文件无法整文件 byte-identity（每函数约 12 字节、nsyms 差 2），**不应追求 byte-identity**。
- **纯顶层 set/setq-lambda 第二区符号槽序残余 diff**（bootstrap fixture）：单 `-lambda-` 文件 CAD 用 **reversed-fwd（含 tail-call 与参数原位）** 编址；多 lambda 文件（无共享参数）按 `[体][参数][tail-call]`（setq-lambda.lsp byte-identical）；共享参数名跨 lambda 时 CAD 把共享参数移末尾、tail-call 前移。compiler 当前统一按 `[体][参数][tail-call]`，与 CAD 单 lambda/共享参数场景不符。fixture `tests/bootstrap.lsp` + golden `tests/cad/bootstrap_cad.fas` 保留作复现，byte-identity 测试从 CAD_GOLDEN_PAIRS 移除（优雅 skip）。
- **i18n 混合模式 seg1 模块代码残余 diff**：`tests/cad/i18n-cad.fas` 对拍中 seg0+nsyms 已逐字节一致，seg1 模块代码仍有 48 个 contiguous resource_items diff（CAD 多一条 `JUMP32 0; PUSH_G 37; SETQ_G 22; PUSH_G 22; POP` 顶层语句），与 kwote lambda 编址无关。`test_i18n_original_byte_identity` 保持 skip。
- **文件头注释/版本戳**（`;A<日期>`）随日期变化，非字节一致性目标；seg0+sec2 已全对齐
- **MCP CAD 连接不稳定**：建议手动测试；CAD 偶发弹出 `alert`/错误框（`#32770`）会阻塞 `atlisp-mcp` eval，用 `python -m tools.cad_dialog_killer <pid> --watch` 自动关闭

### 已固化的协议约束（改动时须保持）

- **`_patch_usubr_idx` 仅混合/多函数文件启用**：纯单函数文件（无顶层表达式且 ≤1 真实 defun）直接返回原 seg0（codegen 槽已与资源 symbol_slots 一致，重映射会破坏多 kwote）
- **0 参 `-lambda-` 无 CLEAR_ARGS 0**：argc=0 且无 `/ locals` 时直接 END_DEFUN（`16`）
- **`command` 每参数独立 `FUNC 1 <ads-cmd>`**（非单次 `FUNC <argc>`，后者 CAD 报"参数太多"）
- **含 `.` 的符号名截断**：CAD 词法级把含 `.` 的符号名截断到第一个 `.`（`x.y`→`X`、`:package.install`→`:PACKAGE`）；独立 `.` token（dotted pair）不受影响。lexer SYMBOL 分支 `split('.',1)[0]`
- **quoted 数据内 `(function ...)` 非 kwote**：引用上下文内是数据（FUNCTION 符号 + lambda 列表）；parser 的 `parse_form`/`parse_list` 的 FUNCTION 分支需 `kwote=(not quoted)`
- **foreach 循环变量独立注册**：即使与共享参数同名也独立符号槽；与唯一参数同名时不独立（CAD 复用参数拥有者槽）
- **`add_string` 数字字符串**：`(= choice "1")` 的 `"1"` 是 STRING 槽（非 SYMBOL）
- **跨区字符串重复注册**：字符串同时出现在模块区与函数体区时，CAD 各注册一个独立 gvar 槽（`add_string(force=True)` 追加重复 STRING 槽）
- **T 槽**：模块区（顶层 cond else 键）与函数体区各注册一次；模块区 T 槽全局唯一（位置由 forward 序第一个引用 T 的 form 决定）
- **模块注册区连续 STRING 合并**为单个 `55` 块；`kwote`/`_al-bind-alist`/`ads-cmd` 独立 `56` 保留大小写单块
- **`defpackage`/`in-package`**：CAD 视为编译期指令——模块代码不发射函数调用（发射会解析为 CL::IN-PACKAGE → 函数错误）；符号仍注册；`defpackage` 关键字（DEFPACKAGE/`:EXPORT`/`:USE`）也进模块注册段
- **`count_resource_items`**：CAD seg1 头 `<items>` = 模块注册 GVARINIT st_init + 函数注册 GVARINIT st_init（中间函数体 fg GVARINIT 不计数）
- **非 ASCII 字符串编码**：CAD 按系统 ACP（中文系统 GBK）写字符串；`get_ansi_encoding` 回退 `reg query` 注册表取 ACP
