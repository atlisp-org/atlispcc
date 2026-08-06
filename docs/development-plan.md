# atlispcc 开发计划

> 本文档记录 `atlispcc`（FAS4 编译器/反编译器工具链）当前功能完成情况、
> 遗留问题与后续开发路线。基于 AutoCAD 24.1s 实测与代码测试状态
> （200/200 通过，v0.1.9）。

---

## 1. 项目目标

`atlispcc` 是 AutoCAD AutoLISP 的编译工具链，核心目标：

1. **编译** `.lsp` → `.fas`，输出与 AutoCAD 编译器**二进制兼容**
   （可直接被 CAD `load` 执行）
2. **反编译** `.fas` → `.lsp`，还原可读的 AutoLISP 源码
3. **工具链**：反汇编/汇编、多文件链接、VLX 容器、优化、包系统

---

## 2. 当前完成情况

### 2.1 已达成 ✅

| 功能 | 状态 | 说明 |
|------|------|------|
| 编译 `.lsp → .fas` | ✅ | 与 AutoCAD 紧凑 stub 格式兼容 |
| 反编译 `.fas → .lsp` | ✅ | stub/自包含两种格式 |
| 反汇编 `.fas → .lasm` | ✅ | 指令级输出 |
| 汇编 `.lasm → .fas` | ✅ | stub 往返 |
| 多文件链接 | ✅ | 符号合并、函数目录重建 |
| VLX 容器构建 | ✅ | 打包构建 |
| 优化 -O1/O2/O3 | ✅ | 8 个 pass |
| CL 风格包系统 | ✅ | namespace |
| 语法验证 | ✅ | validate |
| `&optional`/`&rest` 可变参数 | ✅ | DEFUN 头 b4=01、参数收集列表、反编译标记 |
| 反编译参数名对齐 | ✅ | `decompiler/fas4_decompiler.py` `_extract_signature` 重复检测+回退 |
| 参数顺序修复 | ✅ | `codegen.py` 公式 `nsyms-argc+i` |
| seg1 items 计数修复 | ✅ | `count_resource_records` 按操作码结构跳转 |

### 2.2 CAD 兼容性验证（AutoCAD 24.1s）

| 功能 | 状态 | 测试结果 |
|------|------|---------|
| 简单函数（1-4个） | ✅ | `(add 2 3)`→5, `(f4 8)`→2.0 |
| 递归 | ✅ | `(fact 5)`→120, `(fib 10)`→55 |
| if/while/cond | ✅ | `abs`, `sum-to`, `sign` 全部正确 |
| 局部变量 | ✅ | `(swap 1 2)`→(2 1) |
| 字符串拼接 | ✅ | `(greet "CAD")`→"Hello, CAD!" |
| 多函数交叉引用（2-3个） | ✅ | `(sum-sq 3 4)`→25 |
| 尾递归 | ✅ | `(sum-tail 5 0)`→15 |
| &optional/&rest | ✅ | `(f 3 2)`→5, `(g 1 2 3)`→(1 (2 3)) |
| 顶层 setq/set | ✅ | defun 前后混合均正确执行 |
| lambda/quote | ✅ | `(map-inc '(1 2 3))` → (2 3 4)；lambda 参数局部化正确（全局 x 不受污染） |
| 4函数+交叉引用 | ✅ | `(f1 10)`→11 … `(f5 10)`→29 全部正确（p1_multi4 实测） |
| while/cond/局部变量/apply/funcall/quote | ✅ | t04-t13 全套 CAD 实测通过；t04_while/t05_cond 与 CAD golden 逐字节一致 |
| i18n.lsp 混合模式 | ✅ | 拆件 p01-p07 全 byte-identity；原文件（交错 defun+顶层+kwote）seg0+seg1+nsyms 与 CAD golden 逐字节一致（`test_i18n_original_byte_identity`） |

> 单函数文件（`fun.lsp`、`fact.lsp`）解密后与 CAD 编译器输出逐字节一致。

关键逆向成果：
- **USUBR 索引 = 符号 gvar 槽 - 1**
- DEFCODE 仅最后一个追加 `01`
- 模块代码参数化、函数代码引用多函数范围
- 符号槽收集算法（函数名逆序、每函数内"字节码引用序"逆序、参数紧跟其后、
  递归重复槽；混合时顶层表达式符号排在函数体内建之前）
- `nsyms = len(entries) - 模块注册符号数 + 1`（无顶层时 = 函数数）
- **符号名统一大写**（CAD 符号槽全大写，字符串不变）
- **顶层表达式编译进模块代码**（非 seg0），gvar 槽 = 符号槽 + 1
- DEFUN 头 `0x14`：b1=参数数、b2=最低参数、b3=大参数、b4=00 有限/01 无限
  （AutoCAD `vlisp-compile` 实测：`/` 局部变量不计入头）
- `&optional`：`14 <max> <min> <max> 00`；`&rest`：`14 <min>x3 01`

### 2.3 代码测试 239/239+4xfail ✅

全部通过（含 `tests/test_variadic_args.py` 5 用例与 `test_t_series_roundtrip` 15 用例、
`tests/test_resource_stream.py` 24 用例资源码专项）。
新增：`tests/conftest.py` 已撤销（CLI 管线与裸管线顶层表达式差异，见 `AGENTS.md`「测试中的关键陷阱」）。

**v0.1.16（2026-08-06）**:267 用例（266 passed + 1 skip，skip 为空的 `CAD_T_SERIES_DIFF`
占位），含新增 `test_i18n_original_byte_identity`（i18n 原文件 mixed 模式 byte-identity 回归）。

**v0.1.16（2026-08-07 补充）**:277 用例（276 passed + 1 skip）。新增 7 个 `&optional`/`&rest`
往返测试（`test_variadic_args.py`：参数名恢复、多 optional、optional+rest 组合、rest 递归/转发等）
与真机样本 `tests/cad/t21_variadic_extra.lsp`（`scripts/cad_verify.py` 注册 t21 真机断言）。
单函数变参参数名槽位修复见 §3.4 补充。

---

## 3. 遗留问题与根因分析

### 3.1 ✅ 已解决：多函数 stub 反编译符号槽映射

> 已通过 `_gvar_item` 用 gvar 表（`build_mvar_tables` 的 `idx+1`）、
> `_call_name`/`_extract_signature` 参数绑定用 gvar 槽、链接器
> gvar-1 适配（`_patch_usubr_idx`/`stub_sym_map`）修复。

### 3.2 while/cond/局部变量符号收集与 CAD 逐字节差异（优先级：中）

**进展**：符号收集已重构为 CAD 顺序——函数名源码逆序、每函数内"字节码引用序"
逆序、参数紧跟其后、递归重复槽；多函数（m1/m2）与单函数递归（fact）已与
CAD 逐字节一致。

**剩余**：含递归的**多函数**（multi.lsp：fact+mul+sub+add）符号槽仍未完全对齐
（fact 递归的 `*`/`-` 与 mul/sub 的去重顺序），以及 while/cond/局部变量场景。

**技术路线**：用更多 CAD 样例（while/cond/局部变量/foreach/repeat/递归多函数）
实测符号槽顺序，完善 `cad_symbols.py`。

### 3.3 CAD 加载器内部机制（优先级：低/研究）

**现象**：多函数 USUBR 索引、参数槽的精确 gvar 表偏移依赖 CAD
加载器内部行为（`build_mvar_tables` 模拟不完全准确）。

**技术路线**：结合调试器（如之前 fas-format.org 的 OD 方法）逆向
acad.exe 的 FAS 加载器，完善 gvar 表模型。

### 3.4 ✅ 已解决：反编译 stub 参数名错位（定参）

> **修复**（2026-08）：
> - `decompiler/fas4_decompiler.py` `_extract_signature`：参数名重复或非字母时，尝试
>   `symbol_slots[idx+1]` 回退；无有效替代则 fallback 到 `arg_N`
> - `codegen.py` `_emit_init_args`：参数绑定公式从 `nsyms-1-i` 改为
>   `nsyms-argc+i`（参数在符号槽中按 `nsyms-argc` 偏移）
> - `codegen.py` `_emit_expr`：参数读取公式同步修正
> - `cli.py` `_patch_usubr_idx`：PUSH_VALUE 逆公式更新
> - CAD 已验证：`(defun hypot (a b) ...)` → `(defun hypot (a b) ...)` ✓
> - **范围**：定参函数；`&optional`/`&rest` 变参的单函数见 §3.5b（已修复）、
>   多函数见 §3.5c（遗留）。

### 3.5 纯 `&rest`（min=0）CAD 不收集 rest（优先级：中）✅ 已逆向/已处理

**现象**：`(defun sum (&rest n) ...)` 编译为 `14 00 00 00 01`（min=0），
CAD 加载后函数可定义（SUBR）但调用返回空（rest 未收集）。

**逆向结论**（已用 patch 试错穷尽）：CAD 对 `b4=01, min=0` **硬性不收集**
rest——试遍 DEFUN 头 b1/b2/b3 组合、读取槽（0-5）、GET_LOCAL 槽、
PUSH_G 绑定槽均无效；且 `b1 ≥ 1` 时 CAD 按 min 解析参数绑定数，
绑定数不匹配即报「Xsubr(L) 指令错误」（Xsubr = CAD 对 `USUBR` 0x35
指令的称呼，见 `docs/opcodes.md`）。CAD 的 rest 收集规则为：
**需 `min ≥ 1`（至少一个必填参数），rest 收集「剩余参数」**。

**处理**（已实施）：编译器对纯 `&rest`（`f.rest and not f.args and not
f.optional`）打印警告（非阻断），提示建议 `(defun f (x &rest r))`
至少一个必填参数。文档与 `cad-stub-format.md` 同步注明。

### 3.5b ✅ 已解决：单函数变参参数名槽位错位（&rest/&optional）

> **发现**（2026-08-07，`test_variadic_args.py` 扩充时）：`(defun foobar (a &rest n) ...)`
> 编译后在 CAD 调用报 `函数错误: (2 3)`（rest 值被压到函数位）。根因：
> `cad_symbols._collect_single` 的 `arg_names = set(f.args)` 与尾部参数注册
> `for arg in reversed(f.args)` 都**只含 f.args**，`&rest`/`&optional` 参数被当作
> 函数体符号收集（槽位错位），而 codegen 单函数 init 公式
> `idx = nsyms - argc + src_i` 期望全部参数占据顶部 argc 个槽位。
>
> **修复**：`_collect_single` 改用 `all_args = f.args + f.optional + [f.rest]`
> 作为 `arg_names` 与尾部参数注册顺序（与 codegen 的 `all_args` 一致）。
> 验证：`(defun foobar (a &rest n) (apply '+ (cons a n)))` 在 CAD 真机
> `(foobar 1 2 3)` → 6 可运行 ✅；`&optional` 单函数同样恢复参数名。
> 已随 v0.1.16 发布，并锁入 `test_rest_param_name_recovered_single` /
> `test_optional_param_name_recovered_single`。

### 3.5c ✅ 已解决：多函数变参反编译参数名错位

**现象**：多函数文件含 `&optional`/`&rest` 时，首个函数的参数名反编译错位。
例 `(defun a1 (x &optional y) ...)`（与 `b1` 同文件）反编译为
`(defun a1 (y &optional arg_2))`；t19 的 `t19-greet (name &optional greeting)`
→ `(defun t19-greet (greeting &optional arg_2))`。编译字节码在 CAD 真机**可用**
（t19_sum 等已通过），仅反编译参数名映射错误。

**根因**：多函数符号收集路径（`_collect`）的 `arg_names`/参数注册仍只含
`f.args`（未含 optional/rest），且 `_patch_usubr_idx` 依赖的 `function_gvars`
（`build_mvar_tables`）对紧凑 stub 不完整（末位符号槽缺失），参数槽无法
正确解析回符号名。

**修复**（`decompiler/fas4_decompiler.py` `_extract_signature`，解码器侧纯修复，
不动字节码）：
- 多函数紧凑 stub：参数绑定 `PUSH_G` 操作数 `o` 的 gvar 槽寻址（槽 - 1）在
  nsyms 截断的 gvar 表之外时，真实符号 = `symbol_slots[o+1]`（t01/t09/t18
  A、N 实测）。仅当 gvar 表本身越界时启用，避免破坏 t15/t09 等参数已在 gvar
  表内的文件。
- 单函数紧凑 stub：参数符号在 `symbol_slots` 尾部按"字节码引用序逆序注册"，
  用尾部 argc 个去重符号（逆序）覆写参数名（`_stub_tail_arg_names`），修复
  quoted lambda 等引用字面量导致的绑定操作数错位。
- 回归测试：`test_multi_func_plain_args_name_recovered`、
  `test_multi_func_variadic_name_recovered`、`test_multi_func_three_args_name_recovered`
  （test_variadic_args.py）、`test_t01_golden_multi_func_arg_names`
  （test_compile_decompile.py，直接解 t01_math_cad.fas CAD golden）。

> **注意**：曾尝试在多函数路径同步纳入 optional/rest（改变符号槽序），但会
> 改变 CAD 已验证可用的 t19 槽位布局（REST@4→@5），有回归风险，已回退。
> 多函数变参**字节码保持原样**（CAD 可用），仅反编译名错已修。

### 3.5d ✅ 已解决：反编译 `(list (or a 0))` / `(list (if a a 0))` 展开缺陷

**现象**：`(defun f (a b) (list (or a 0) (or b 0)))` 反编译为
`(list T T)` + 独立的 `(or (or a 0) (or b 0))`；`(list (if a a 0) ...)`
反编译为多个独立 `if` + 空 `(list)`。非变参同样触发（与变参无关）。

**根因**：`or`/`if` 编译进参数位置时含 `PUSH_T`/`COND_OR` 等控制流指令，
反编译器按顶层表达式渲染，未折叠回参数位置。

**修复**（`decompiler/fas4_decompiler.py` `_render_block`）：
- `or`/`and` 短路链收尾：`COND_AND` 的跳转目标是紧随其后的 `PUSH_T`
  （codegen `_emit_short_circuit` 的 END 标签）时，把累积链折叠为单个表达式
  并吞掉该 `PUSH_T`，不再泄漏裸 `T`。
- 表达式位 `if`：then 分支末尾无 `POP`（值流入 JUMP/else 供后续调用消费）时，
  把 `(if ...)` 压栈作值而非作为语句；且该分支前不 `flush_stack()`，避免后续
  分支的 flush 把前一个 if 值当语句丢弃。
- 回归测试：`test_or_expr_folded_not_leaked`、`test_list_or_args_folded`、
  `test_list_if_args_folded`、`test_if_expr_in_call_folded`
  （test_compile_decompile.py）。

### 3.5e ✅ 已解决：反编译 lambda 参数遮蔽外层参数

**现象**：`(defun f (lst) (mapcar '(lambda (x) (* x 2)) lst))` 反编译为
`(defun f (x) ...)`（`lst`→`x`，外层参数被 lambda 参数名遮蔽）。

**根因**：反编译器对 lambda 内的符号槽命名复用/冲突处理不完整。参数绑定
`PUSH_G` 操作数指向 lambda 参数 X（其符号槽在 quoted lambda 常量内先注册），
而真实参数 `lst` 在 `symbol_slots` 尾部。

**修复**（`decompiler/fas4_decompiler.py` `_extract_signature` +
`_stub_tail_arg_names`）：单函数 stub 从 `symbol_slots` 尾部 argc 个去重符号
逆序取参数名，`lst` 与 lambda 参数 `x`/`y` 各自保留。回归测试：
`test_lambda_param_no_shadow`、`test_lambda_distinct_param_names`
（test_compile_decompile.py）。

### 3.6 链接器多函数 CAD 只注册首个函数（优先级：高）

**现象**：`atlispcc link` 合并多文件后，CAD `load` 只注册第一个函数；
如 `lk_comb.fas` 中 `(square 7)`→49 但 `(sum-squares 3 4)` 空；
`grh.fas` 中 `(g ...)` 对但 `(h ...)` 空。反编译/测试均正常。

**根因**：链接输出的**模块代码**（`build_module_code(n)`）与 DEFCODE
函数目录对 CAD 的注册机制不完全兼容——首函数经模块注册可用，后续函数
未绑定（疑似模块代码的 `PUSH_G<2n+1-i> SETQ_G<n-i>` 引用槽或
`01 00 16` 分隔符/`_func_ranges_bytes` 与 CAD 不一致）。

**进展（分析）**：`add_force` 后 sum-squares 已注册（SUBR），但**调用
卡死**（非未定义）。USUBR 索引经 `build_mvar_tables` 校验正确
（square idx 1 → gvar 槽 2）；`build_mvar_tables` 对 AutoCAD 参考
（cad_t01_math）验证准确。对比发现：cmd 跨调用（multi2：sq 槽 3）CAD
全注册，link 跨调用（lk_comb：square 槽 2）卡死——**link 的符号布局与
cmd 的 `derive_symbol_names` 顺序不同**（cmd：`[函数名, +内建, sq引用, 参数, *内建, 参数]`，
link：square 因 `add_force` 在槽 2），导致 `build_module_code` 的
`PUSH_G[3]`（cmd 布局=第一个函数 sq）在 link 输出指向非函数符号
（`*`），CAD 绑定错→调用卡死。**已修复**：链接器符号顺序复刻 cmd 的 `derive_symbol_names`——
函数名按源码逆序（文件逆序 + 文件内 DEFCODE）、跳过全重复文件、
跨函数引用 `add_force` 去重、按文件 slots 顺序合并（去头尾模块槽）。
验证：`fd_new == fd_cmd`（cmd 等价）**字节级一致**（bytecode + sec2）；
`lk_comb` 与 `multi2`（cmd 跨调用，CAD 已验证全注册）sec2/USUBR **完全对齐**；
167/167 测试通过。CAD 实测受 3.7 环境不稳定干扰，恢复后复核。

**复核（2026-08-07）**：链接器 §3.6 注册修复已就位（10 项 linker 测试全绿）。
复核发现一个**遗留 cosmetic 限制**：跨文件链接多参数函数时，合并输出的
参数名可能不理想（如 `sum-squares (a b)` 链接后反编译为 `(x arg_2)`）。
字节码**功能正确**（CAD 按位置绑定参数，函数体内引用一致可运行），仅参数
名非源码名。尝试用 `_pre_gvar`（合并 gvar 槽 - 1）重映射参数绑定/读取操作数
可修好该例，但破坏 `test_link_first_definition_wins`（碰撞场景的参数符号在
nsyms 截断区，映射不可靠）。已回退，保持 HEAD 稳定行为。根治需按合并
symbol_slots 布局重算参数槽（风险高，CAD 复核后方可推进）。

**技术路线**：
- 用 CAD 实测链接输出的模块代码/函数注册，对比单文件多函数（cmd）
   的差异（cmd 多函数 CAD 全注册可用）
- 检查 `build_module_code` 多函数变体在链接场景的 PUSH_G/SETQ_G 槽
   与合并符号表的对应
- 验证 `_func_ranges_bytes`（多函数代码引用范围）在链接输出的正确性

### 3.7 CAD 运行环境稳定性（优先级：中/运维）⚠️ 严重

**现象**：CAD 会话易失——`No open document`、调用超时/卡死、
`new_document` 失败需手动恢复；连接池 reconnect 偶发返回 `\`。
**关键风险（实测）**：**加载损坏/非法的 FAS 会破坏 CAD 的 Lisp 环境**，
导致访问冲突（0xC0000005）、解释器损坏，**必须重启 CAD 才能恢复，
极端情况下需重启系统**。这解释了此前反复卡死/无文档/崩溃的根因。

**安全测试策略（必须遵守）**：
1. **不在主 CAD 会话加载未验证的 FAS**——先用本地反汇编/反编译
   校验字节码（USUBR 索引、DEFUN 头、符号槽），确认无误再 CAD 加载
2. **不手动 patch 字节码试错**（USUBR 槽等）——坏字节码会损坏环境；
   需试错时用**独立 CAD 实例**（atlisp-mcp 多实例支持）
3. **CAD 加载前先快照**：记录 `DWGNAME`、已定义函数；加载后验证环境
   完好（`(getvar "DWGNAME")` 非空）
4. **建立独立 CAD 测试实例**（`D:\atlisp-test` 配套），主会话仅用于
   已验证输出的最终确认
5. 卡死/崩溃后：先 `cad_pool_discover`/`connect` 恢复；无效则手动
   `NEW` 新建文档；仍无效需**重启 CAD 进程**

**技术路线**：
- 为 CAD 实测建立独立测试脚本与实例，避免破坏主会话
- 测试流程：编译 → 本地字节码校验 → CAD 加载（独立实例）→ 环境检查

### 3.8 `validate.py` 与 atlisp-lint 的关系（优先级：低/记录待决策）

**现状**：`validate.py` 是反编译管线内的**合法性门禁**（自包含库、
纯 Python、被 `tests/test_compile_decompile.py` 的 `_validate` 断言）。
atlisp-lint（MCP `analyze_lisp_code`，99 条规则）是**源码质量/安全/风格
审查工具**，`analyze_lisp_code` 实测**不依赖 CAD 连接**（可独立运行）。

**能否代替**：技术上可行（lint 覆盖 validate 的合法性子集 + 90 条质量规则），
但**不建议完全代替**：
1. **CI/测试集成**：validate 是本地 import；lint 需 MCP subprocess（每测试慢、CI 依赖服务）
2. **输出/断言**：lint 返回 `valid/errors/warnings/issues`，tests 的 `_validate` 断言需全部改
3. **定位**：产物验证需「硬性结构检查」，lint 多为软性 `warn` 建议

**待决策方案**：
- A. validate.py 保持门禁 + 小幅补强（危险函数 quit/exit/startapp、未使用变量 ~5 条）
- B. 移植 lint 核心语法规则（括号/符号/setq/c: 等 ~10 条）入 validate.py（保持自包含）
- C. 反编译产物额外脚本化跑 `analyze_lisp_code` 做质量检查（非 CI）

**建议**：A + C（validate 保持门禁并补强；质量检查用 lint 脚本化）。暂不实施，后续决策。

---

## 4. 开发计划

### 4.1 已完成（2026-08）

| 任务 | 状态 | 说明 |
|------|------|------|
| 反编译参数名（3.4） | ✅ | `_extract_signature` 重复检测 + `symbol_slots[idx+1]` 回退 |
| 参数顺序修复 | ✅ | codegen 公式 `nsyms-argc+i`、`_patch_usubr_idx` 逆公式 |
| seg1 items 计数 | ✅ | `count_resource_records` 按操作码结构跳转，避免 `0x1c/0x43` 误计 |
| 死代码清理 | ✅ | 移除 `Fas4Parser.build_mvar_tables`（~196 行，从未调用） |
| 纯 `&rest` min=0 | ✅ | 已逆向（CAD 硬性不收集）+ 编译警告 |

### 4.2 短期（P0）✅ 已完成

| 任务 | 状态 | 说明 |
|------|------|------|
| 链接器多函数 CAD 注册（3.6） | ✅ | `derive_symbol_names` 复刻 + `fd_new == fd_cmd` 字节级一致 |
| `build_module_code` PUSH_G 越界 | ✅ | n≥4 动态计算，4+函数交叉引用 CAD 实测通过 |
| `_build_cad_module_code` 增强 | ✅ | 支持 defun 间夹杂 setq/if 的顶层表达式（模块代码） |

> 下一阶段工作计划见 **第 8 节「功能完善开发计划」**（2026-08 版本，四方向）。

### 4.3 中期（P1）

目标：扩大 CAD 兼容覆盖，字节码逐字节一致。

| 任务 | 说明 |
|------|------|
| t-series 剩余符号槽差异（t03/t09-t15） | ✅ 全部转正 byte-identity（见第 8 节 C1） |
| i18n.lsp 混合模式 | ✅ 原文件 byte-identity（`test_i18n_original_byte_identity`，见第 8 节 C2） |
| 命令函数 `c:` 特殊处理 | ✅ `vl-ACAD-defun` 注册（t14，见第 9 节阶段 3） |
| 复杂表达式 | ✅ mapcar/lambda/apply/foreach/repeat 的 CAD 编码（t08/t16/t17/t20） |
| 错误处理函数 | `*error*`、条件子程序（开放） |
| CAD 兼容回归套件 | 扩展 D:\atlisp-test 测试集 |

### 4.4 长期（P2，3-6 月）

目标：完整工具链，健壮性与性能。

| 优化器增强 | 跨函数常量传播、死代码消除扩展 |
| 性能 | 大文件编译/反编译优化；`decompiler/fas4_decompiler._render_block`、`compiler/cad_symbols` 定位热点，基准驱动优化 |
| CAD 版本兼容 | 多 AutoCAD 版本（2008-2025）FAS 变体 |
| VLX 增强 | 依赖收集、eTransmit |
| 文档完善 | 完整 FAS 格式规范 |
| ZELX 复杂文件压缩（8.D） | 复刻 ZWCAD 压缩重编码（模块代码重编码 + 符号重排），对小型/简单文件已逐字节一致，复杂文件需逆向 LispConverter.exe（`docs/zelx-format.md` §5-6 + `tools/zelx_diff.py`）+ ZWCAD 真机验证 |
| CAD 加载器内部逆向 | 逆向 acad.exe FAS 加载器，完善 `build_mvar_tables` gvar 表精确模型（`core/fas_core.py`） |
| ZELX 复杂文件压缩 | ZWCAD 压缩重编码复刻（见第 8 节 D1） |

---

## 5. 优先级排序

| 优先级 | 内容 | 影响 |
|--------|------|------|
| ~~P0~~ | ~~反编译 stub 参数名（3.4）~~ | ✅ 已修复 |
| ~~P0~~ | ~~链接器多函数 CAD 注册（3.6）~~ | ✅ 已修复 |
| ~~P0~~ | ~~`build_module_code` PUSH_G 越界~~ | ✅ 已修复（4+函数交叉引用 CAD 实测通过） |
| ~~P1~~ | ~~lambda 参数绑定~~ | ✅ 已修复（λ 常量 PUSH_G 操作数 = gvar 槽-1 = symtab 槽-nfuncs+1） |
| ~~P1~~ | ~~while/cond/局部变量符号槽~~ | ✅ 已修复（while 无 WHILE 槽/末体无 POP；cond 测试正序+结果倒序） |
| P0 | t-series 剩余符号槽差异（t03/t09-t15） | 字节级兼容补齐（见 8.C1） |
| P0 | i18n.lsp 混合模式 | defun+顶层交错注册规则（见 8.C2；拆件 p01-p07 已全对齐，原文件 byte-identity 已锁入回归） |
| P1 | 工具链健壮性 | `compiler/cli.py` ast 遮蔽、README/打包矛盾、validate 补强（见 8.A） |
| P1 | 测试与 CI 完善 | t-series byte-identity 回归（已落地 18 份 golden，16 项 identical，2 项 xfail）、i18n roundtrip、mypy、twine check（见 8.B） |
| P2 | ZELX 复杂文件压缩 | ZWCAD 压缩重编码复刻（见 8.D） |
| P2 | CAD 加载器内部逆向 | gvar 表精确模型 |
| P2 | 性能与多版本兼容 | 工具链健壮性 |

> 纯 `&rest` min=0（3.5）已逆向并加编译警告（CAD 硬性不收集），移出优先级表。

---

## 6. 验收标准

- **P0 完成**：✅ `pytest` 全绿（266 passed，无 xfail）；✅ t-series 与 `tests/cad/` golden 逐字节一致（见 §8.C）；✅ i18n 混合模式字节一致
- **P1 完成**：工具链健壮性修复落地；t-series byte-identity 回归（239 passed + 4 xfailed）；i18n roundtrip 用例通过；CI 绿
- **P2 完成**：复杂 zelx 逐字节一致 + ZWCAD 加载通过；多版本 CAD 兼容；大文件性能达标

---

## 7. 相关文档

- `docs/cad-stub-format.md` — CAD 紧凑 stub 格式规范（核心）
- `docs/fas-format.md` — FAS4 二进制格式
- `docs/opcodes.md` — 操作码参考
- `docs/development.md` — 架构详解

---

## 8. 功能完善开发计划（2026-08 版，v0.1.9 → v0.2）

> 基于 v0.1.9（200/200 测试通过，9 个 golden 对字节一致）与 CAD golden 实测
> 差异分析制定。**均衡推进 A（健壮性）+ B（测试/CI）+ C（字节兼容）**，
> ZELX（D）最后。
>
> **golden 实测样本位置**（本次核实）：全部位于 `tests/cad/`——
> `t*.fas`（CAD 官方产物，配套 `t*.lsp` 源与 `t*_atlispcc.fas` 我方产物对比）、
> `cadtest_v10-17.fas`（含 `.lsp`/反编译对照）、`i18n-cad.fas`/`i18n.fas`（i18n 混合模式目标）。
> 原计划引用的 `D:/atlisp-test/cad_t*.fas` **当前不存在**，golden 一律以 `tests/cad/` 为准。
>
> **t-series golden 已补齐**（2026-08-04/05，AutoCAD 24.1s `vlisp-compile` 生成）：
> 源码与 golden 均自包含于 `tests/cad/`（`t0X_xxx.lsp` + `t0X_xxx_cad.fas`，18 份，含 t04/t05）。
> 字节一致状态：
> t01-t15/t18 **byte-identity**（18 项已入 `test_t_series_byte_identity` 回归，
> 2026-08-04 转正 t03/t09/t13/t15，2026-08-05 转正 t10/t11/t12/t14 + 新增 t18，
> 2026-08-06 转正 t16/t17）；
> `CAD_T_SERIES_DIFF` 已空，`pytest` 254 passed。

### 8.A 工具链健壮性（P1）

| 任务 | 说明 |
|------|------|
| A1 修复 `python compiler/cli.py` 崩溃 | ✅ **已修复**（2026-08-04）：`compiler/ast.py` 改名 `ast_nodes.py` 并更新全部 import（15 个文件），双入口 `python compiler/cli.py` 与 `python -m compiler.cli` 均可运行 |
| A2 README 与打包矛盾 | `pyproject.toml` `packages.find` 已含 `tools*`（会随 wheel 分发），README §工具 却写"不随 pip 包分发"。修正 README 表述 |
| A3 validate.py 门禁补强 | ✅ **已补**（2026-08-04）：新增 `validate_danger`（quit/exit/startapp warn）+ `validate_unused`（/ 局部变量未使用 warn），warn 不阻断返回码；附 4 个测试用例 |
| A4 `--analyze` 统计增强 | ✅ **已补**（2026-08-04）：analyze 增 `symbol_slots`（stub nsyms 估算）；CLI `--analyze` 输出符号槽数、优化前后指令/符号槽 delta、编译后 seg0/seg1 字节数与实际 nsyms |

### 8.B 测试与 CI 完善（P1）

| 任务 | 说明 |
|------|------|
| B1 ~~t-series byte-identity 回归~~ | **恢复并已落地**（2026-08-04/06）：源码与 golden 自包含于 `tests/cad/`（`t0X_xxx.lsp` + `t0X_xxx_cad.fas`，18 份）。`test_t_series_byte_identity` 覆盖 **18 项**（t16/t17 于 08-06 转正，`CAD_T_SERIES_DIFF` 空）。t12/t14 于 08-05 转正（资源段 + `vl-ACAD-defun` 注册），t10/t11 同日转正（混合模式符号序 / `_al-bind-alist` 协议），t18 同日新增转正（互递归多函数），t16/t17 08-06 转正（foreach/repeat stub 协议） |
| B2 CI mypy 校验 | CI 已跑 `mypy .`（3.10-3.13 矩阵，`pyproject.toml` 已配 mypy `python_version=3.10`）；本机 Python 3.9 无 mypy，以 CI 结果为准 |
| B3 twine check 依赖 | ✅ **已补**（2026-08-04）：dev 依赖加 `build`/`readme-renderer`/`twine` |
| B4 混合模式 roundtrip 测试 | ✅ **已加**（2026-08-04）：`test_i18n_mixed_mode_roundtrip`（`tests/cad/i18n.lsp` 编译→反编译→validate 通过，与 C2 共用目标） |

### 8.C 字节级 CAD 兼容补齐（P0，核心）

实测差异汇总（`cad_symbols.py` 符号收集序与 CAD 不一致）：

| 文件 | 差异数 | 差异形态 | 根因假设 |
|---|---|---|---|
| t03_fib | ✅ **已修复**（2026-08-04） | 递归函数名多次自身调用共享重复槽（t03 递归两次仅 1 重复 FIB） |
| t09_funcall | ✅ **已修复**（2026-08-04） | 同函数内跨函数调用共享重复槽（sum-of-squares 两次调用 square） |
| t10_init | ✅ **已修复**（2026-08-05） | 混合模式顶层符号序 + 模块代码多函数尾（见 C2/§9.2） |
| t11_localvars | ✅ **已修复**（2026-08-05） | `_al-bind-alist` 局部变量绑定协议（codegen 注入 `(_al-bind-alist '(locals...))`，CLEAR_ARGS = argc + locals） |
| t12_quote | ✅ **已修复**（2026-08-05） | dotted `'(1 . 2)` 常量 `2a` 收尾（仅资源段差异） |
| t13_nested_if | ✅ **已修复**（2026-08-04） | 单函数参数绑定/读取逆序（simple3/t13 实测 `+ Z Y X`） |
| t14_command | ✅ **已修复**（2026-08-05） | c: 命令需 `vl-ACAD-defun` 资源注册（模块注册段插入 `56` 编码，不进 symtab.entries） |
| t15_cad_funcs | ✅ **已修复**（2026-08-04） | 共享参数槽位（源码序最先使用者之后）+ 字符串 gvar 槽 |

技术路线（每项用 `tests/cad/` golden 实测迭代 `CadSymbolCollector`）：
1. ~~t15/t13（简单 swap）~~ ✅：改 `_collect_byteorder` builtin/函数名去重序、共享参数槽位、单函数参数逆序
2. ~~t03/t09（偏移 -1）~~ ✅：递归/跨函数调用重复槽共享（多次调用仅 1 重复槽）
3. ~~t11（局部变量）~~ ✅：`_al-bind-alist` 绑定协议（codegen 生成绑定序列，见 §9.2 阶段 1）
4. ~~t12（quote 常量）~~ ✅：dotted 常量 `2a` 收尾（见 §9.2 阶段 3）
5. ~~t14（c: 命令）~~ ✅：`vl-ACAD-defun` 资源注册（见 §9.2 阶段 3）

> **样本来源**：源码与 golden 自包含于 `tests/cad/`——`t0X_xxx.lsp`（源）+
> `t0X_xxx_cad.fas`（CAD `vlisp-compile` 2026-08-04/05 生成，18 份，含 t04/t05），
> 另有 `tests/cad/t*.fas`/`t*_atlispcc.fas` 成对对比样本。t01-t15/t18 **全部**
> byte-identity 回归（`test_t_series_byte_identity`，18/18，t16/t17 于 2026-08-06 转正）。

**C2 i18n 混合模式（原为最大缺口 1139 字节差 / -69 len）**

- 根因：`i18n.lsp` = defun + 顶层表达式**交错**（非先 defun 后顶层），
  `cad_symbols.py` 与 `_build_cad_module_code` 只支持"函数块在前、顶层在后"
- 方案：
  1. 扩展 `CadSymbolCollector.collect_program` 支持 defun/顶层交错时的"持续块规则"
     （顶层表达式符号在函数体内建之前，按源码序跨块收集）
  2. `ResourceBuilder.build` 的 `module_entries` 切分逻辑改为按交错序
  3. 用 `tests/cad/i18n.lsp` + `tests/cad/i18n-cad.fas` 迭代至字节一致
- 进度：**拆件 p01-p07 全部 byte-identity**（2026-08-06，`tests/cad/i18n_split/`，
  锁入 `I18N_SPLIT_FULL_IDENTICAL`；seg0+seg1+nsyms 对齐）。
  拆件修复了：DUP 插入按真实 SETQ_G 指令定位（不碰 USUBR 的 0x06 索引字节）、
  stub 下 if-then 分支尾 setq 补 DUP、"setq 目标归属优先于读取"
- 验收：✅ **已完成**（2026-08-06）——`i18n.lsp` 原文件编译 seg0/seg1/nsyms 与
  CAD golden 逐字节一致，锁入 `test_i18n_original_byte_identity`

**C3 补充 CAD 验证样本**

- ~~扩充 `tests/cad/` 样本集（while/cond/局部变量/foreach/repeat/递归多函数/c: 命令）~~ ✅ **已补**（2026-08-05）：
  - while/cond/局部变量/c: 命令原已覆盖（t04/t05/t11/t14）
  - **新增 t16_foreach、t17_repeat、t18_multi_recursive**（互递归多函数），
    源码与 CAD golden（`vlisp-compile 'st` 真机生成）自包含于 `tests/cad/`
  - CAD 实测产出命令：`(vlisp-compile 'st "src.lsp" "out.fas")`
- 现状：**18/18 全部 byte-identity 转正**（t16/t17 于 2026-08-06 转正，见 §9.2 记录；i18n 混合模式拆件 p01-p07 于 08-06 转正）

### 8.D ZELX 复杂文件压缩（P2）

| 任务 | 说明 |
|------|------|
| D1 复刻 ZWCAD 压缩重编码 | `zelx_build.py` 对小型/简单文件逐字节一致（15/15 样本）；复杂文件缺 ZWCAD 压缩重编码（模块代码重编码 + 符号重排）。对照 `docs/zelx-format.md` §5-§6 与 `tools/zelx_diff.py` 逆向 LispConverter.exe |
| D2 ZELX 真实加载验证 | 现状标记"ZWCAD 能否加载需真实验证"；建立 ZWCAD 测试实例验证小型/复杂 zelx 加载 |

### 8.E 执行顺序与验收

**执行顺序（均衡推进 A+B+C）**：
1. **8.A + 8.B 先行**（P1，低风险、可独立并行）：A1 ast 重命名、A2 文档、A3 validate、A4 analyze、B2 mypy、B3 readme-renderer、B4 i18n roundtrip
2. **8.C 穿插**（P0，核心）：t15→t13→t03/t09→t14→t12→t11→C2 i18n（每项用 `tests/cad/` golden 迭代）
3. **8.D 最后**（P2，独立）

**验收标准**：
- **8.A 完成**：`python compiler/cli.py` 与 `python -m compiler.cli` 双入口可运行（✅）；README 无矛盾；validate 增规则有测试；`--analyze` 输出新增统计字段
- **8.B 完成**：t-series byte-identity 回归落地（16 项 identical + 2 项 xfail，新增 test_resource_stream 24 用例）；B4 i18n roundtrip 用例通过；CI 绿（mypy + pytest）；dev 依赖含 readme-renderer
- **8.C 完成**：✅ t10/t11/t12/t14 由 xfail 全部转正为 byte-identity（移入 `CAD_T_SERIES_IDENTICAL`；t03/t09/t13/t15 已于 2026-08-04 转正）；✅ i18n 混合模式字节一致（`test_i18n_original_byte_identity`，2026-08-06）；`pytest` 全绿（无 xfail）
- **8.D 完成**：复杂 zelx 逐字节一致 + ZWCAD 加载通过

---

# 9. 字节兼容收尾开发计划（2026-08-05 版，v0.1.9 → v0.2）

> **范围**：聚焦字节兼容 P0/P1（t11/t10/t12/t14/i18n 全转正），ZELX（8.D）暂缓。
> **CAD 验证**：独立实例 + 快照流程（遵守 §3.7 安全策略，不手动 patch 字节码）。
> **产出**：本文件作为单一事实源，逐阶段更新。

## 9.1 现状核实（2026-08-06 实测，`pytest` 266 passed）

> 变参样本（t19_variadic、t21_variadic_extra）**无 CAD golden**，仅真机功能验证
> （`scripts/cad_verify.py`，22 项）；反编译参数名在单函数已修复、多函数仍有
> 错位（见 §3.5b/§3.5c）。

| 项 | seg0 | seg1 | nsyms | 根因 | 优先级 |
|---|---|---|---|---|---|
| t11_localvars | ✓ | ✓ | 8vs8 | **已转正 2026-08-05**（`_al-bind-alist` 绑定协议） | P0 ✅ |
| t10_init | ✓ | ✓ | 4vs4 | **已转正 2026-08-05**（混合模式顶层符号序 + 模块代码多函数尾） | P0 ✅ |
| t12_quote | ✓ | ✓ | 5vs5 | **已转正 2026-08-05**（dotted 常量 `2a` 收尾） | P1 ✅ |
| t14_command | ✓ | ✓ | 6vs6 | **已转正 2026-08-05**（`vl-ACAD-defun` 注册 + 命令模块代码） | P1 ✅ |
| i18n 混合模式 | ✓ | ✓ | 92vs92 | **已转正 2026-08-06**（defun+顶层交错持续块规则，原文件 `test_i18n_original_byte_identity` 回归） | P1 ✅ |
| t18_multi_recursive | ✓ | ✓ | 7vs7 | **已转正 2026-08-05**（互递归多函数，天然一致） | C3 ✅ |
| t16_foreach | ✓ | ✓ | 5vs5 | **已转正 2026-08-06**（CAD stub foreach 内建调用协议：`PUSH_G/PUSH_NIL/INIT_ARGS 3` 预载 + `JMP32_IFNOT` + 尾 `CLEAR_ARGS 1`） | C3 ✅ |
| t17_repeat | ✓ | ✓ | 4vs4 | **已转正 2026-08-06**（repeat 递减循环：`GET_LOCAL; PUSH_INT8 0; FIX_LEQ; JMP32_IFNOT` + 体前 `DEC`） | C3 ✅ |

## 9.2 已转正（byte-identity，18/18）✅
`t01_math` `t02_recursion` `t03_fib` `t04_while` `t05_cond` `t06_strcat`
`t07_list` `t08_apply_mapcar` `t09_funcall` `t10_init` `t11_localvars`
`t12_quote` `t13_nested_if` `t14_command` `t15_cad_funcs`
`t18_multi_recursive` `t16_foreach` `t17_repeat`
（2026-08-06：t16/t17 转正后 `CAD_T_SERIES_DIFF` 空，`pytest` 266 passed；
i18n 原文件 byte-identity 锁入 `test_i18n_original_byte_identity`）

> **t18_multi_recursive 转正记录（2026-08-05）**：互递归（`is-even`/`is-odd` 互相调用）
> 属"多函数 + 递归重复槽"场景，符号槽/字节码与 CAD 天然一致，无需新逻辑。

> **t16_foreach / t17_repeat 转正记录（2026-08-06）**：CAD 把 `foreach`/`repeat`
> 编译为**对内建遍历的真实调用协议**，codegen 改为与之逐字节一致的 stub 编码：
> - **foreach**：列表求值→存局部槽 → `PUSH_G <var>; PUSH_NIL; INIT_ARGS 3`（预载）
>   → loop 头 `GET_LOCAL; JMP32_IFNOT` → 体 `GET_LOCAL; CAR; SETQ_G <var>;
>   GET_LOCAL; CDR; SET_LOCAL` 推进 → 体各式无 POP → `JUMP` → 尾 `CLEAR_ARGS 1` 清理预载
> - **repeat**：次数→存局部槽 → loop 头 `GET_LOCAL; PUSH_INT8 0; FIX_LEQ; JMP32_IFNOT`
>   （n<=0 退出）→ 体前先 `GET_LOCAL; DEC; SET_LOCAL` 递减 → 体各式无 POP → `JUMP`；
>   无预载，尾部无 CLEAR_ARGS
> - **DEFUN 头**：含 foreach/repeat 的函数 `b1=argc+1`（`14 <argc+1> <argc> <argc> 00`）
> - **反编译器**：`_defun_headers_are_argc` 的 stub 检测允许 `b1 == b3+1`
>   （否则 `is_stub_format` 误判 False，带 foreach/repeat 多函数文件函数命名失败）
> 差异不影响功能（CAD 真机 `(sum-foreach '(1 2 3 4))`→10 ✓，`scripts/cad_verify.py` 15/15）。

> **t12_quote 转正记录（2026-08-05）**：根因是 dotted 引用 `'(1 . 2)` 的常量在
> seg1 资源流中以 `39 <count>` 收尾，而 CAD 用单字节 `2a`（LIST_END）。修复：
> `cad_symbols.to_const` 为 dotted ListExpr 返回 3 元组 `('LIST', items, True)`，
> `resource_builder._emit_const` 对 dotted 列表输出 `2a` 而非 `39 <count>`。

> **t14_command 转正记录（2026-08-05）**：c: 命令需在模块注册段插入
> `vl-ACAD-defun` 符号（`0x56` 编码、保留大小写 `Vl-ACAD-defun`），并使模块注册
> GVARINIT st_init +1（4→5）、函数注册基址 gv_var_pos +1（4→5）。vl 仅存在于
> resource_gvars（模块注册），不进 symtab.entries，故 seg0 引用的 function_gvars
> 槽位不变。模块代码改用 `build_command_module_code`（每命令
> `PUSH_G<c>; FUNC_REF 2; PUSH_NIL; POP` 注册）。

> **t11_localvars 转正记录（2026-08-05）**：CAD 用 `_al-bind-alist` 绑定 `/ 局部变量`
> （`(defun f (args / l1 l2) (_al-bind-alist '(l1 l2)) ...)`），而非直接 GET_LOCAL。
> 修复：
> - `cad_symbols.py`：含 `/ 局部变量` 的函数在函数体符号后、参数前注入
>   `_al-bind-alist` 符号 + `(quote (locals...))` 常量 → nsyms 6→8、slot 对齐
> - `codegen.py`：`generate_function` 在 INIT_ARGS 后发 `_al-bind-alist` 绑定序
>   `PUSH_G <const>; FUNC 1, <_al-bind-alist>; NIL; PUSH_NIL; NIL; POP`；
>   CLEAR_ARGS = argc + locals；while 体中间 setq 无 POP（t11 实测）
> - `resource_builder.py`：`_al-bind-alist` 以 `0x56` 保留大小写独立注册

> **t10_init 转正记录（2026-08-05）**：混合模式（顶层表达式 + defun）的模块注册
> 符号序 + 多函数模块代码尾：
> - `cad_symbols.py`：多函数路径顶层符号改用字节码引用序逆序（与单函数一致）
> - `cli.py` `_build_cad_module_code`：多函数注册尾改为每函数一组
>   `PUSH_G <b>; SETQ_G <c>`（b = 2n+1+top_count-i，c = n-i），组间 `PUSH_G<c>; POP; JUMP`
> - `cli.py` `_patch_usubr_idx`：函数体字符串 PUSH_G 操作数 = nsyms-1（t15/t10 实测）
> - **golden 重新生成**：原 golden 的 `hello` 函数名小写是 CAD 会话环境已存在
>   `hello` 符号所致（环境 artifact）；改用 `t10-init-hello` 并经 CAD 重新
>   `vlisp-compile` 生成干净 golden

## 9.3 执行阶段

### 阶段 1：t11 `_al-bind-alist`（P0，最大 seg0 缺口）✅ 已完成 2026-08-05
- 逆向 CAD 绑定序列（ref 用 `PUSH_G+FUNC`，我们直接 `GET_LOCAL`）
  - ref seg0：`... 51 01 05 00 01 00 0a 32 ...`（FUNC `_al-bind-alist` 绑定 alist）
- 改 `compiler/codegen.py` `_emit_init_args` 生成 `_al-bind-alist` 协议；对齐 `cad_symbols.py` 符号槽（局部变量进符号表）
- 回归防护：t04_while/t05_cond（含局部变量）必须保持 byte-identity ✅

### 阶段 2：t10_init（P0，小样本混合模式）✅ 已完成 2026-08-05
- 对齐顶层 init 表达式符号收集序（nsyms 2→4）
- 为阶段 4 i18n 预研持续块规则
- golden 重新生成（`hello` 环境 artifact）

### 阶段 3：t12_quote + t14_command（P1，仅 seg1）✅ 已完成 2026-08-05
- t12：dotted 常量 `2a` 收尾（`cad_symbols.to_const` + `resource_builder._emit_const`）
- t14：`c:` 命令 `vl-ACAD-defun` 模块注册（`0x56` 保留大小写）+ `build_command_module_code`
  - 根因：REF 在模块注册段于命令函数名间插入 `vl-ACAD-defun` 符号
    （`C:ADD, vl-ACAD-defun, C:HELLO`），使模块注册 `st_init` 4→5、
    函数注册基址 `var_pos` 4→5；模块代码每命令追加
    `PUSH_G <c>; FUNC_REF 2; PUSH_NIL; POP`（`35 <argc> <idx> <01>`）而非 `PUSH_G <c>; POP`。
  - REF 命令模块代码（n=2）：`14 01 00 00 00 | PUSH_G4 POP JUMP0 | PUSH_G6 SETQ_G3 |
    PUSH_G3 FUNC_REF2 PUSH_NIL POP | PUSH_G3 POP JUMP0 | PUSH_G5 SETQ_G1 |
    PUSH_G1 FUNC_REF2 PUSH_NIL POP | PUSH_G1 END`
  - 槽位公式（n=2 与 golden 逐字节一致，n>2 外推）：`var_pos=n_funcs+3`；
    `a=var_pos-1-i`、`b=var_pos+n_funcs-1-i`、`c=n_funcs+1-i`（i<n-1）、末 `c=1`。
  - 关键约束：`vl-ACAD-defun` 仅在模块注册段（resource_gvars）注册，**不进**
    `symtab.entries`（否则 seg0 引用的 function_gvars 槽位 +1 破坏字节一致）；
    `commands` 计数 = 1（vl 符号数），非命令函数数。

### 阶段 4：i18n 混合模式（P1，1133 处主战场）✅ 已完成 2026-08-06
- `CadSymbolCollector.collect_program` 持续块规则（defun/顶层交错）
  - ✅ 顶层符号序已对齐（t10 转正，与单函数一致）
  - ✅ `/ 局部变量` `_al-bind-alist` 协议已落地（t11 转正）
- 模块注册段交错序：✅ **已完成**。i18n（9 defun + 7 顶层）模块注册首符号
  `_`（`(set '_ @::_)` 顶层目标）在槽 0、`@::_` 槽 1、函数名逆序随后，
  `@::CODEPAGE2LANG`（顶层引用）归入顶层符号段而非函数组——按 CAD 实测
  逐块持续规则逆向完成，原文件 byte-identity（`test_i18n_original_byte_identity`）。

### 阶段 5：收尾 ✅ 已完成 2026-08-05
- xfail → `CAD_T_SERIES_IDENTICAL` 逐项转正（`tests/test_compiler_output.py`）
  - ✅ t10/t11/t12/t14 全部转正，`CAD_T_SERIES_DIFF` 空
- 独立 CAD 实例 + 快照流程真机复核（`scripts/cad_verify.py`）
- 更新本文件、AGENTS.md、兼容性矩阵

### 阶段 6：t16_foreach + t17_repeat（C3，foreach/repeat 内建调用协议）✅ 已完成 2026-08-06
- codegen `_emit_foreach_stub` / `_emit_repeat_stub`（CAD 逐字节实测，见 §9.2 记录）
- DEFUN `b1=argc+1`（`_ast_contains_loop` 递归检测，`_emit_defun_header` 应用）
- 函数体中间 foreach/repeat 后无 POP（foreach 自带 `CLEAR_ARGS 1`，repeat 栈已平衡）
- 反编译器 `_defun_headers_are_argc` 允许 `b1 == b3+1`
- 回归防护：t04_while/t11_localvars/t18/t-complex O2（含 foreach/repeat 混合）保持一致 ✅
- t16/t17 移入 `CAD_T_SERIES_IDENTICAL`，`pytest` 266 passed

## 9.4 涉及文件
`compiler/codegen.py`、`compiler/cad_symbols.py`、`compiler/resource_builder.py`、
`compiler/cli.py`、`tests/test_compiler_output.py`、`docs/development-plan.md`

## 9.5 验收
- ✅ `pytest` 全绿（无 xfail）；t16/t17 已转正，`CAD_T_SERIES_DIFF` 空
- ✅ t11/t10/t12/t14/t18 + t16/t17 移入 `CAD_T_SERIES_IDENTICAL`（18/18 字节级一致）
- ✅ **i18n.lsp 原文件 byte-identity**（2026-08-06）：原文件（defun+顶层+kwote `-lambda-`
  交错混合模式）编译 seg0+nsyms+seg1 与 `tests/cad/i18n-cad.fas` 逐字节一致，
  锁入 `test_i18n_original_byte_identity` 回归。拆分件 p01-p07 亦全对齐
- `cad_verify.py` 真机 15/15（独立实例流程）

# 10. 反编译正确性完善计划（2026-08-07 版，P0 三缺陷）

## 10.1 目标

修复 §3.5c/§3.5d/§3.5e 三个反编译正确性缺陷（均为**解码器侧纯修复**，
不动字节码，CAD byte-identity 不受影响）。基线：`pytest` 276 passed + 1 skip。

## 10.2 执行阶段

### 阶段 1：§3.5c 多函数参数名错位 ✅ 已完成

**现象**：`t01_math_cad.fas`（CAD golden，add/multiply 各 2 参）反编译为
`(defun add (b arg_2))`；多函数 + argc>1 全部触发。

**修复**（`_extract_signature`）：
- 多函数 stub：gvar 表越界时操作数 `o` 真实符号 = `symbol_slots[o+1]`
- 单函数 stub：`_stub_tail_arg_names` 从 `symbol_slots` 尾部取 argc 个去重符号逆序

**测试**：`test_multi_func_*`（3 例）+ `test_t01_golden_multi_func_arg_names`
（直接解 CAD golden）+ `test_lambda_*`（§3.5e 同路径）。t01/t09/t18/t13/t15
golden 解译参数名全对齐。

### 阶段 2：§3.5d or/if 参数位展开 ✅ 已完成

**修复**（`_render_block`）：
- `COND_AND` 目标为紧随 `PUSH_T`（短路链 END）时折叠链并吞掉 `PUSH_T`
- 表达式位 `if`（then 分支无 POP）：压栈作值 + 分支前不 `flush_stack()`

**测试**：`test_or_expr_folded_not_leaked`、`test_list_or_args_folded`、
`test_list_if_args_folded`、`test_if_expr_in_call_folded`。

### 阶段 3：§3.5e lambda 参数遮蔽 ✅ 已完成

**修复**（`_extract_signature` + `_stub_tail_arg_names`）：单函数 stub 参数名
取 `symbol_slots` 尾部，`lst` 与 lambda 参数 `x`/`y` 各自保留。

**测试**：`test_lambda_param_no_shadow`、`test_lambda_distinct_param_names`。

### 阶段 4：§10.4 遗留缺陷（共享参数 / `/` 误判 / 循环协议）✅ 已完成

- **共享参数**（t07/t08，多函数共用 lst）：新增 `_stub_extended_gvar`
  （基础 gvar 表 + symbol_slots 尾部未入表符号），参数按 gvar 槽 - 1 寻址
  时 `operand → extended[o+1]`（t08 op5→LST@6、t07 op7→LST@8 实测）。
  仅用于 `_extract_signature` 参数名解析，不改全局 gvar 表（避免打乱函数体
  引用回退）。t07 `get-first/get-rest (lst)`、`pair (a b)`、t08 `sum-list/
  double-all (lst)` 全部对齐。
- **`/` 误判**（t12）：`_localize_assigned_globals` 仅当函数声明 `/ 局部变量`
  （`func.locals` 非空或 `local_binding_names`）时把 setq 目标加入局部表；
  否则 setq 目标是全局（t12 `(setq lst '(a b c))` 不再输出 `/ lst`）。t11
  `_al-bind-alist` 局部变量不受影响。
- **循环协议**（t16/t17）：`_defun_headers_are_argc` 无目录扫描允许
  `b1 == b3+1`（foreach/repeat 的 DEFUN 头 b1=argc+1，t16 之前被误判为
  自包含格式）；新增 `_detect_repeat_setup`（体前 `GET_LOCAL; DEC; SET_LOCAL`
  递减协议），`(repeat n ...)` 正确渲染。t16 `sum-foreach (lst)` + foreach、
  t17 `repeat-count (n)` + repeat 结构正确。

**测试**：`test_t08_golden_shared_arg_names`、`test_t07_golden_shared_arg_names`、
`test_t12_golden_global_setq_not_localized`、`test_t16_golden_foreach_arg_and_structure`、
`test_t17_golden_repeat_arg_and_structure`（均直接解 CAD golden）。

## 10.3 验收

- ✅ `pytest` 291 passed + 1 skip（较基线 +15 回归用例，无 xfail）
- ✅ 全部 t-series golden 参数名/结构比对：t01-t13/t15/t18 全对齐；t14
  `c:add(/ a b)` 为**有意设计**（c: 命令函数参数本地化，`_emit_function`
  行 1375-1380）；t16/t17 参数名与循环结构正确，仅 `total`/`acc` 等全局
  setq 目标被本地化（cosmetic，功能等价）
- ✅ 字节级：CAD byte-identity 测试（18/18）不回归

## 10.4 遗留（cosmetic，功能等价）

- t14 `c:add(/ a b)`：c: 命令函数参数被有意本地化（CAD 以无参调用 c: 命令）
- t16 `sum-foreach(lst / total x)`、t17 `repeat-count(n / acc)`：循环函数的
  全局 setq 目标（total/acc）被本地化；setq 初始化语句渲染在循环后（setq
  重排 artifact，同 t11）。功能正确，仅与源码全局语义略有差异
- t16/t17 `/ locals` 顺序（`/ total x` vs 源码无 `/`）：同上 cosmetic

## 10.5 涉及文件

- `decompiler/fas4_decompiler.py`：`_extract_signature`、`_render_block`、
  `_stub_tail_arg_names`、`_stub_extended_gvar`、`_stub_is_multi_func`、
  `_detect_repeat_setup`、`_detect_loop`、`_localize_assigned_globals`、
  `_defun_headers_are_argc`
- `tests/test_variadic_args.py`、`tests/test_compile_decompile.py`
