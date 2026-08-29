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
| 纯顶层多 `-lambda-` setq 绑定 | ✅ | `setq-lambda.lsp`（两个顶层 `(setq X (lambda ...))`）seg0+nsyms+resource_items 与 CAD golden 逐字节一致（`test_byte_identity_with_cad_golden[setq-lambda.lsp]`）；CAD 真机 `(@::fasext "abc")`→`"abc.fas"`、`(@::vlx "a.vlx")`→`"a.vls"` |

> 单函数文件（`fun.lsp`）解密后与 CAD 编译器输出逐字节一致。

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

**v0.1.18（2026-08-08）**:304 用例（303 passed + 1 skip）。新增 t22_activex
（vla-/vlax- ActiveX）byte-identity golden 回归（`tests/cad/t22_activex_cad.fas`）。
CAD 真机 24/24 全过（含 t22/t23）。t22 修复与 t21 修正见 §9.6。

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

**剩余**：含递归的**多函数**符号槽仍未完全对齐
（递归的 `*`/`-` 与 mul/sub 的去重顺序），以及 while/cond/局部变量场景。

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

**CAD 真机复核（2026-08-08）⚠️ §3.6 结论需修正**：CAD 会话恢复后，对链接
产物做了真机验证，发现**链接输出在 CAD 加载后功能错误**（非仅参数名 cosmetic）：
- `add`（`(defun add (a b) (+ a b))`，与 `mul` 链接）：`(add 2 3)` 返回空
- `square`/`sum-squares`（跨文件调用）链接：`(square 7)` 报
  `Xsubr(L) 指令 (偏移代码) 错误: 29`，`(sum-squares 3 4)` 报 `函数错误`
- 同源码由 CAD `vlisp-compile` 直接编译（两函数同文件）真机正常
  （`(square 7)`=49、`(sum-squares 3 4)`=25）

**对比链接输出与 CAD 参考（link_ref.fas）发现的字节差异**：
1. **函数间分隔符**：CAD 用单个 `16`（END_DEFUN），链接输出 `01 00 16`。
   改 `16` 后 `(square 7)` 恢复 49，但本地 3 项 linker 测试失败——`01 00 16`
   被本地测试（`_decompile` 函数识别）依赖，两者冲突。
2. **参数绑定/读取槽**：CAD 参考用合并表 gvar 槽-1（square 参数 X 操作数 6、
   mix 参数 A/B 操作数 4/3），链接输出用 `param_delta`（merged_nsyms-file_nsyms）
   平移（square X→6 对、mix A/B→6/5 错）。尝试 `_pre_gvar-1` 映射修好
   square/sum-squares，但破坏 `test_link_first_definition_wins`（碰撞场景）。
3. **符号槽顺序**：合并符号表与 CAD 参考的 `+`/参数相对顺序不同，导致
   USUBR/PUSH 槽整体错位。

**结论**：§3.6 的「字节码功能正确」断言不成立。链接器需按合并 symbol_slots
布局 + CAD 参考逐字节对齐（分隔符、参数绑定 gvar 槽-1、符号槽顺序）。此修复
与本地 linker 测试（`_decompile` 依赖 `01 00 16`）存在张力，需专项处理：
- 生成更多 CAD 参考（跨文件调用、多参数、碰撞场景）作为 golden
- 修正 `_decompile` 依赖（若 `16` 是正确分隔符则修测试）
- 参数绑定用合并 gvar 槽-1，碰撞场景需特殊处理

**修复完成（2026-08-08）✅ §3.6 链接器 CAD 兼容根治**：
1. **函数间分隔符** `01 00 16` → `16`（CAD stub 实测，`t01_math_cad.fas`/
   链接 golden 两函数间仅 `16`）。`_decompile` 依赖同步修正（`16` 正确）。
2. **参数绑定/读取槽** 改用「合并 gvar 槽 - 1」（`_pre_gvar[sym] - 1`，表内）
   或「参数序 nsyms-1-arg_rev」（表外，CAD 实测 add 参数 A=nsyms-1、B=nsyms-2、
   3 函数 X=nsyms-1）。单函数文件参数绑定操作数 = 符号槽、多函数 = 符号槽-1
   （`_param_slot` 从文件 symbol_slots 反查符号名）。
3. **符号槽顺序**：单函数文件分离「函数体符号 + 参数」，参数区分共享（跨文件
   同名）最后注册、非共享紧跟所属文件；多函数文件（如 foo+call-foo）不分离
   （参数穿插在各函数体内）。
4. **sec2_items**：链接器补 `min_items = 2*nfuncs + 2` 修正（CAD 实测 2 函数→6、
   3 函数→8，而 `count_resource_records` 仅 4）。
5. **`final_offset`** 分隔符长度 3→1。

**回归**：新增 `test_link_byte_identity_with_cad_golden`（3 份 CAD golden：
addmul/sqsum/three，`tests/cad/link/*_cad.fas`，CAD `vlisp-compile` 2026-08-08
生成），链接输出与 CAD 直接编译同源码 **seg0+sec2+nsyms+sec2_items 逐字节一致**。
CAD 真机验证：add/mul `(5 20)`、square/sum-squares `(49 25)`、f1/f2/f3 `(6 7 8)`、
碰撞场景 foo/call-foo `(6 6)` 全部正常。pytest **309 passed + 1 skip**。

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

**决策（2026-08-08）**：采用 **A + C**。方案 A 已落地：
- `validate_danger`（quit/exit/startapp）✅ 已有
- `validate_unused`（`/` 局部变量未使用）✅ 已有
- **新增 `validate_command`**（2026-08-08）：检测 `command`/`command-s`/`vl-cmdf`/
  `vl-cmd-s` 调用危险系统命令（shell/del/erase/rename/copy/xcopy/mkdir/rmdir/
  type/vbastmt 等，含 `_.`/`_` 前缀规范化），warn 级不阻断。附 2 个测试
  （`test_validate_command_danger_warns` / `test_validate_command_danger_cli_rc_zero`）。
- C（脚本化跑 lint 做质量检查）作为可选运维手段，不强制。

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
| 编译符号整理 O(n²)→O(n)（2026-08-09） | ✅ | `compiler/cad_symbols.derive_name` 等改用 `_Seen`/set 去重，5000 函数源 `pytest` 编译 10.6s → 0.28s（~38×） |
| 反编译 O(n²) 热点（2026-08-09） | ✅ | `decompiler/fas4_decompiler` 的 `_stub_extended_gvar`、`_defun_headers_are_argc` 加 memoization，大文件反编译 456s → 6.9s（~66×） |
| 编译模块代码 per-form 反汇编消除（2026-08-09） | ✅ | `compiler/cli._stmt_bytes` setq 快路径新增 Integer 分肢（内联 `PUSH_INT8/INT32` + `DUP` + `SETQ_G`），消除每顶层 setq 的两段 disassemble（5000 setq → 10000×），字节输出与 codegen 逐字节一致 |
| 链接器去重复核 | ✅ | 字符串/符号表已 dict/set 背靠（`_collect_global_data` O(n)），确非 O(n²)，无需改动 |
| 性能基准套件 | ✅ | 新增 `scripts/benchmark.py`：compile -O0/-O2 + decompile + link，支持 --json/--profile/--samples/--baseline 相对改善率 |

### 4.2 短期（P0）✅ 已完成

| 任务 | 状态 | 说明 |
|------|------|------|
| 链接器多函数 CAD 注册（3.6） | ✅ 已修复（2026-08-08） | 分隔符 `16`、参数绑定 gvar 槽-1/参数序、符号槽顺序、sec2_items 修正；`test_link_byte_identity_with_cad_golden` 3 份 golden 逐字节一致 + CAD 真机可调用 |
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
| 性能 | 大文件编译/反编译优化（基准驱动，2026-08-09 已落地一线：cad_symbols O(n²)→O(n)、反编译两热点 memoization、模块代码 per-form 反汇编消除、`scripts/benchmark.py` 基准套件；后续以相对改善率为准） |
| CAD 版本兼容 | 多 AutoCAD 版本（2008-2025）FAS 变体 |
| VLX 增强 | 依赖收集、eTransmit |
| 文档完善 | 完整 FAS 格式规范 |
| ZELX 复杂文件压缩（8.D） | 复刻 ZWCAD 压缩重编码（模块代码重编码 + 符号重排），对小型/简单文件已逐字节一致，复杂文件需逆向 LispConverter.exe（`docs/zelx-format.md` §5-6 + `tools/zelx_diff.py`）+ ZWCAD 真机验证 |
| CAD 加载器内部逆向 | 逆向 acad.exe FAS 加载器，完善 `build_mvar_tables` gvar 表精确模型（`core/fas_core.py`） |
| ZELX 复杂文件压缩 | ZWCAD 压缩重编码复刻（见第 8 节 D1） |
| **链接器 CAD 兼容根治（3.6）** | ✅ 已修复（2026-08-08）：链接产物与 CAD golden 逐字节一致（分隔符 `16`、参数绑定 gvar 槽-1/参数序、符号槽顺序、sec2_items），CAD 真机 add/mul/square/sum-squares/f1-f3/碰撞场景全部可调用。见 §3.6「修复完成」 |

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
| P2 | 性能与多版本兼容 | 大文件性能（2026-08-09 首批优化已落地，见 §4.1）+ 工具链健壮性 |

> 纯 `&rest` min=0（3.5）已逆向并加编译警告（CAD 硬性不收集），移出优先级表。

---

## 6. 验收标准

- **P0 完成**：✅ `pytest` 全绿（266 passed，无 xfail）；✅ t-series 与 `tests/cad/` golden 逐字节一致（见 §8.C）；✅ i18n 混合模式字节一致
- **P1 完成**：工具链健壮性修复落地；t-series byte-identity 回归（239 passed + 4 xfailed）；i18n roundtrip 用例通过；CI 绿
- **P2 完成**：复杂 zelx 逐字节一致 + ZWCAD 加载通过；多版本 CAD 兼容；大文件性能达标
- **当前（2026-08-09）**：`pytest` **314 用例**（313 passed + 1 skip，无 xfail）；t-series byte-identity **18/18**（t01-t18，t22_activex 另锁入回归）；CAD 真机 **24/24**（`scripts/cad_verify.py`）；disasm→asm 往返 43 文件一致；性能基线见 `scripts/benchmark.py`
- **当前（2026-08-11）**：`pytest` **344 用例**（343 passed + 1 skip，无 xfail）；t-series byte-identity **18/18** 不回归；**t12 链式 quote 常量解码修复**（`(setq lst '(a b c))` + dotted `'(1 . 2)`，见 §12T5）；**`*error*` 真机用例 t24_star_error**（cad_verify 覆盖 22→24 项）；zelx 15/15 样本 payload 复核一致；测试环境恢复（.venv 装 pytest，`PYTHON=.venv/bin/python` 可跑 `scripts/run_tests.sh`）
- **当前（2026-08-15）**：`pytest` **347 用例**（345 passed + 2 skip，无 xfail）；**纯顶层多 `-lambda-` setq 绑定 byte-identity**（setq-lambda.lsp：seg0+nsyms+resource_items 与 CAD golden 逐字节一致，`test_byte_identity_with_cad_golden[setq-lambda.lsp]`，CAD 真机 `(@::fasext "abc")`→`"abc.fas"`、`(@::vlx "a.vlx")`→`"a.vls"`）；t-series byte-identity **18/18** 不回归
- **当前（2026-08-18）**：`pytest` **356 用例**（354 passed + 2 skip）；`tests/compile_src/` 16 fixture 入库（此前缺失致 9 个测试在其他环境失败）；**kernel 67/67 编译产物验证全绿**、**byte-identity 13/67**（表外字符串 + CONST fallback 两类 PUSH_G 越界、模块区 T 槽位置、顶层 progn 语句语义、纯顶层 REAL 槽引用、未使用 / 局部变量槽五类修复；t14_command/t10_init 黄金逐字节恢复，`test_compile_src_byte_identity` 锁入；`scripts/kernel_compare_http.py` + `tests/cad/kernel_golden/` 67 份 CAD 参考 golden 建立对拍基建）；bootstrap.lsp 纯顶层 set-lambda fixture 重建 + CAD golden（第二区符号槽序残余 diff 登记，见 AGENTS.md）
- **当前（2026-08-28）**：`pytest` **380 用例**（378 passed + 2 skip）；**kernel 67/67 byte-identical 全部一致**——修复 `sub-system/ui/panel.lsp`（顶层 `(if is-gcad (progn (defun C:% ...) (defun C:%% ...) (foreach ...)))` 条件 defun 绑定留在 if 守卫内 + `-lambda-` DEFCODE 发射序逆序 + const fallback `first_cmd_slot` 判定 + `_patch_usubr_idx` 双注册分支守卫，见 AGENTS.md「条件 defun 绑定」）；`scripts/kernel_compare_http.py`（ours→compare）复核 67/67 DIFF=0
- **当前（2026-08-29）**：`pytest` **456 用例**（454 passed + 2 skip）；**@lisp_u 全量 byte-identical 达成（100%）**——atlisp_u.lsp（502 函数 + 221 顶层语句）seg0+seg1+nsyms 与 CAD golden `tests/atlisp_u_cad2.fas` 逐字节一致（此前 99.3%，seg0 622 + seg1 9630 字节 diff）。4 文件 8 项根因（详见 AGENTS.md「atlisp_u 全量 byte-identity」）：共享参数裸 lambda 归属（cad_symbols）、wide SETQ_G fallback 移除（patch）、嵌套 defun `#dup` FUNCOBJ 反查 + 混合 `_lam_slot`/`_tl_funcobj_slots` 补 `n_cmds`（compile_cmd）、`_reg` b 槽统一让位 + `_mid_count_of` top-lambda-only 索引 + `_skip` 仍发 mid + `set` 协议纯顶层/混合不同槽（module_code）。**新增测试**：`test_atlisp_u_byte_identity.py`（atlisp_u 全量 byte-identity + roundtrip + kernel 67 文件参数化 golden 回归）+ `test_compiler_output.py` 8 项根因定向回归。验证：kernel 67/67 + merged_2/4/8/16 IDENTICAL + pytest 456 passed
- **当前（2026-08-29 P0 收尾，v0.1.32）**：`pytest` **458 用例**（458 passed + 1 empty-skip 占位）。**bootstrap.lsp 转正 byte-identity**——纯顶层 `(set 'X (lambda ...))` + in-package/use-package + 跨 lambda 共享参数 `file` 的第二区符号槽序对齐 CAD golden：跨 lambda 共享参数推迟到第二区最末尾（`STRCAT @::*FASEXT* FILE`）、含 in-package/use-package 的 `-lambda-` 运行时槽整体 +1（`_lam_slot` 加 `_lam_extra`），移回 `test_byte_identity_with_cad_golden[bootstrap.lsp]`。**i18n 混合模式恢复**——`test_i18n_original_byte_identity` 移除 skip（seg0+seg1+nsyms 与 `tests/cad/i18n-cad.fas` 逐字节一致，48 项 diff 已被此前修复消除，仅测试 skip 未同步）。验证：bootstrap/setq-lambda/net-wget/reload/atlisp_u/kernel 67/67 不回归

---

## 7. 相关文档

- `docs/cad-stub-format.md` — CAD 紧凑 stub 格式规范（核心）
- `docs/fas-format.md` — FAS4 二进制格式
- `docs/opcodes.md` — 操作码参考
- `docs/development.md` — 架构详解

---

## 8. 功能完善开发计划（2026-08 版，v0.1.9 → v0.2）✅ 已完成（D 除外）

> 精简归档：A（工具链健壮）/B（测试/CI）/C（字节兼容）全部完成；D（ZELX
> 复杂压缩）为 P2 遗留，需 ZWCAD 真机（阻塞，见 §17 P2-2）。详细阶段已折叠。

| 任务 | 结论 |
|------|------|
| 8.A 工具链健壮 | ✅ CLI 双入口、validate_danger/unused/command 门禁、`--analyze` 增强 |
| 8.B 测试/CI | ✅ t-series byte-identity 回归（18 份 golden）、i18n roundtrip、mypy、twine 依赖 |
| 8.C 字节兼容 | ✅ t01-t18 **18/18 byte-identity**；i18n 拆件 p01-p07 + 原文件 byte-identity |
| 8.D ZELX 复杂压缩 | ⏳ 小型简单文件逐字节一致（15/15）；复杂文件阻塞（需 ZWCAD 环境） |

**8.C 关键协议（实现参考）**：递归/跨函数重复槽共享（t03/t09）；参数逆序（t13）；
`_al-bind-alist` 局部变量绑定（t11）；dotted `'(1 . 2)` 常量 `2a` 收尾（t12）；
`c:` 命令 `vl-ACAD-defun` 保留大小写注册（t14）；foreach/repeat 内建 stub（t16/t17）。
涉及：`compiler/{codegen,cad_symbols,resource_builder,cli}.py`、`tests/cad/`

---

# 9. 字节兼容收尾开发计划（2026-08-05 版）✅ 已完成 18/18

> 精简归档：t10/t11/t12/t14/i18n/t16/t17 全部转正 byte-identity，`CAD_T_SERIES_DIFF` 空。
> 2026-08-15：纯顶层多 `-lambda-`（setq-lambda.lsp）转正 byte-identity（见 §9.1）。

- 阶段 1 t11 `_al-bind-alist '(locals)`：INIT_ARGS 后发 `PUSH_G;FUNC 1;NIL;PUSH_NIL;NIL;POP`，
  CLEAR_ARGS = argc + len(locals)
- 阶段 2 t10 混合模式顶层符号序 + 多函数模块代码尾（`PUSH_G<2n+1-i> SETQ_G<n-i>`）
- 阶段 3 t12 dotted `2a` + t14 `vl-ACAD-defun`（`build_command_module_code`，0x56 不进 symtab）
- 阶段 4 i18n defun/顶层交错「持续块规则」+ 模块注册段交错序
- 阶段 6 t16/t17 stub：foreach `PUSH_G;PUSH_NIL;INIT_ARGS 3` + `JMP32_IFNOT` + 尾 `CLEAR_ARGS 1`；
  repeat `GET_LOCAL;PUSH_INT8 0;FIX_LEQ;JMP32_IFNOT` + 体前 `DEC`；DEFUN 头 `b1=argc+1`
- 涉及：`compiler/{codegen,cad_symbols,resource_builder,cli}.py`、`tests/test_compiler_output.py`

**9.1 纯顶层多 `-lambda-` setq 绑定**（2026-08-15，byte-identity，`setq-lambda.lsp`）：
- seg0：`-lambda-` 完整 compact stub（`14 <argc>x3 00` + GET_LOCAL + INIT_ARGS + 体 +
  CLEAR_ARGS + END_DEFUN，函数间 `16`、最后无 END），USUBR 5 字节宽格式（flags=3）
- nsyms = fg 表长度 = `1 + len(第二区符号)`（12 = 1 + 11）
- 符号表布局：第一区 → 函数目录 → 第二区（体符号+参数+调用名，跨 lambda 去重）
  → `GET_LOCAL; GVARINIT(0, 第二区数+1)` 建 fg 表（module_id=最后符号判 table1）
  → 多 DEFCODE → `GVARINIT(第一区数+2, 函数数)`
- 模块代码 setq 协议 `JUMP 0; PUSH_G <lam槽+1>; DUP; SETQ_G <sym>`（`_lam_slot+1`
  不走 `_slot_gv`）；`_patch_usur_idx` `top_lambda_args` 参数映射（gvar 槽-1）
- 回归：`test_byte_identity_with_cad_golden[setq-lambda.lsp]`；CAD 真机
  `(@::fasext "abc")`→`"abc.fas"`、`(@::vlx "a.vlx")`→`"a.vls"`

---

# 10. 反编译正确性完善计划（2026-08-07 版）✅ 已完成

> 精简归档：§3.5c/d/e + §10.4 全为解码器侧纯修复，字节码零改动。pytest 276→291；
> t-series golden 参数名/结构全对齐；t14 `c:add(/ a b)` 属有意设计。

- `_extract_signature`：多函数 gvar 越界→`symbol_slots[o+1]`；`_stub_tail_arg_names` 尾部
  argc 去重逆序（单函数/lambda 遮蔽）
- `_render_block`：or/if 参数位折叠（COND_AND 短路链 + 表达式位 if 压栈）
- `_stub_extended_gvar`（共享参数）、`_localize_assigned_globals` `/` 误判、
  `_defun_headers_are_argc` `b1==b3+1` + `_detect_repeat_setup`（循环协议）
- 涉及：`decompiler/fas4_decompiler.py` 8 处 + `tests/{test_variadic_args,test_compile_decompile}.py`

---

# 11. vla-/vlax- ActiveX 真机缺陷修复（2026-08-08）✅ 已完成

> 精简归档：t22 编译产物与 CAD golden 逐字节一致；CAD 真机 24/24。

- A. vla- 保留大小写（方法名首字母大写，`vlax-` 小写）：`normalize_vla_name` + `_enc_sym`
  对 vla-/vlax- 前缀不 `.upper()`
- B. 值位置 `T`/`t` 注册符号槽 + stub 下 `PUSH_VALUE` 引用（nil 仍内联）
- C. USUBR/FUNC 槽末尾编址：操作数 = `nsyms - 1 - offset`
- t21 修正：`(factor &rest rest)` min=1（§3.5 CAD 硬性限制）
- 涉及：`cad_symbols`/`codegen`/`resource_builder`/`cli` + `tests/cad/t22_activex*`

---

# 12. 反编译精细度收尾开发计划（v0.3，S3 主线，2026-08-09）✅ 已完成

> 精简归档：T1-T7 全部完成；pytest 313→316；大样本基准 6.9s→5.5s（-20%）。

- T1 循环 setq 保序在循环前（`_detect_loop`/`_detect_repeat_setup`）
- T2 `/ 局部变量` 清单 = 真实局部声明（t16/t17 循环 setq 目标保持全局）
- T3 c: 命令参数本地化 = 有意设计（文档+回归注释标注）
- T4 `(setq ...)` 与 `(eval ...)` 顺序：`_render_block` POP 分支先 flush 滞留语句
- T5 setq 重排：t11 `_gvar_item` branch1 命中 `gvar_table[idx+1]` 立即 return；
  t12 module_id 槽（`build_module_id_slots`）+ dotted `(1 . 2)` 渲染
- T6 性能：`is_compact_stub` lru_cache（6.9s→5.5s）；`_render_block` 已线性无热点
- T7 回归：`test_stmt_order_*`、`test_t11_locals_decl_and_setq_order`；§10.4 仅剩 t14
- 涉及：`decompiler/fas4_decompiler.py`、`scripts/benchmark.py`、`tests/`

---

# 13. 工具链新功能（S4，2026-08-09）✅ 已完成

> 精简归档：`--report`/`info`/`analyze`/`roundtrip` 落地；pytest 340。全为 CLI/独立层新增，
> 编译器核心零改动（18/18 byte-identity 不回归）。

| 子命令 | 说明 |
|--------|------|
| `compile --report <json>` | 编译统计+产物信息导出 |
| `info` | .fas/.zelx 头部/段/函数目录/符号/字符串概览，`--json` |
| `analyze` | `dep_analysis.py` 调用图 text/dot/mermaid/json；.lsp/.fas 双输入；DEFCODE 公开函数自动 root |
| `roundtrip` | `roundtrip.py` 编译→反编译→validate→compare 冒烟（裸内存管线） |

- 涉及：`compiler/cli.py`、`compiler/{dep_analysis,roundtrip}.py`（新增）、`tools/compare_lsp.py`、
  `tests/test_diagnostics.py`（+20）、`tests/test_cli.py`（+4）

---

# 14. 裸管线往返名字稳定缺口（已知限制记录，2026-08-09）

> 反编译验证（2026-08-09）中发现并核实：**仅影响裸内存往返测试管线**，
> 不属 decompiler bug，CAD/正式 CLI 产物路径不受影响。本条为已知限制登记 +
> 潜在修复方向，非既定期限任务。

## 14.1 现象

对 CAD golden 首轮反编译正确还原参数/局部名（如 `t11_localvars_cad.fas`
→ `(defun sum-to-n (n / result i)` + `(_al-bind-alist '(result i))`）。但把
反编译产物经**裸内存管线**（`tests/test_compile_decompile.py` 的
`SymbolTable→Codegen→ResourceBuilder→FasWriter`）再编译、再反编译时，名字
丢失：

| 样本 | 首轮反编译 | 二次反编译（裸管线产物） |
|---|---|---|
| `t09_funcall_cad.fas` | `(defun sum-of-squares (a b)` | `(defun sum-of-squares (a square)` |
| `t11_localvars_cad.fas` | `(defun sum-to-one (n / result i)` | `(defun sum-to-one (n / local_1 local_2)` |
| `t14_command_cad.fas` | `(defun c:add (/ a b)` | `(defun c:add ()` |
| `t17_repeat_cad.fas` | `(defun repeat-count (n)` | `(defun repeat-count (n / local_1)` |

## 14.2 根因

裸内存管线存储符号槽/参数槽的方式与 CAD 编译器资源段不同（无 CAD seg1
模块注册、`_al-bind-alist` 协议顺序、USUBR 槽排序等），反编译器名字恢复
启发式（`_extract_signature`/`_stub_tail_arg_names`/`_localize_assigned_
globals`）面向 CAD 格式设计，对裸管线产物无法匹配 → 参数/局部名退化为
`local_N` 或误取内层函数名。CLI/链接器等**正式产物路径**（走 seg1 模块
资源）不受影响，首轮反编译名字正确。

## 14.3 修复方向（未排期）

把裸管线 `compile_and_decompile` 改为亦输出 CAD 风格资源槽（stub 类似
`resource_builder` seg1 模块注册 + `_al-bind-alist` 协议），使手动往返名字
稳定。成本：裸管线与 CLI 管线的已知差异（AGENTS.md「测试中的关键陷阱」）
需一并拉齐，涉及 `tests/test_compile_decompile.py` 大量既有断言。价值：
仅替代 path（roundtrip/测试）名字可读性，正式产物路径已正确——当前定为
**不做**。

## 14.4 验证基线（已确认无回归）

- `pytest` 104 通过（disasm/resource/编译往返/汇编）；full-suite 基线不变
- 全部 CAD golden 首轮反编译名字正确（区别于 §14.1 的二次反编译差异）
- corrupt/截断输入 CLI 优雅退出（`Not a valid FAS4 file`，exit 1），无崩溃

---

# 15. @lisp 综合包编译支持（2026-08-11）✅ 已完成

> 精简归档：`tests/atlisp_u.lsp`（502 函数 + 221 顶层语句 + 80 kwote）编译产物在 CAD 真机
> 模块代码完整执行、功能全部可用；v0.1.21 发布。详细修复折叠。

- A. 解析器：裸引用关键字 `'(defun)` 等按数据列表解析（`parser.py`）
- B. 顶层 `(progn ...)` 展开 + 条件/嵌套 defun → `(setq f '(lambda ...))` 数据赋值 + 
  多 kwote→引用数据（`_flatten_top_level_forms`/`_lower_nested_defuns`/`_lower_multi_kwote`）
- C. commands+顶层混合 gvar 槽重映射：`compiler/_gvar_map.py` 解析 seg1 模块注册段，
  `_offset_slots` 二次生成按实际槽位重映射 USUBR/PUSH_G/FUNC
- D. 大文件宽格式：符号槽 >255 用 5 字节 USUBR / 6 字节 FUNC（`wide_subr`/`short_subr=False`）
- E. 顶层符号槽推导：`top_level_count` 由 `module_reg_count` 推导（避免高估）
- F. 资源段杂项：REAL 整数降温（`2208988800.0`）、commands+顶层模块注册段补齐
- 涉及：`compiler/{parser,cli,codegen,cad_symbols,resource_builder}.py`、`compiler/_gvar_map.py`

---

# 16. engine/（SBCL AutoLISP 运行时）探索（v0.1.21+）

## 16.1 目标

建立独立于 CAD/FAS 的 AutoLISP 求值环境，作为**跨校验器**：同一源码经
atlispcc 编译产物与 engine 求值结果互相对照，验证编译器语义正确性。

## 16.2 当前状态

- `engine/atlisp.asd`：ASDF 系统，`src/{packages,values,reader,env,eval,builtins,main}.lisp`
- 公共 API（`:atlisp` 导出）：`al-eval-source` / `al-run-file` / `al-repl`
- 值模型：AutoLISP 数据映射到 CL 原生值（nil/t/int/double-float/string/AL 包符号/cons）
- 冒烟基线（`engine/engine_smoke.lsp`，S1-S17 全 OK）：算术/递归/if/while/cond/
  foreach/repeat/局部变量/&optional/&rest/互递归/dotted/strcat/geometry/
  kwote-mapcar/apply/funcall/T-NIL 常量
- **CAD 对拍**（2026-08-12，`scripts/engine_crosscheck.sh`）：t01-t21 同源用例
  engine 求值结果与 CAD 期望值**全部一致**（21/21 OK）
- 关键修复记录：
  - reader：转义符 `#\)`→`#\\`（第 51 行）；`scan-token` loop 补 `do`；
    `parse-list` 重写（原 `:rparen`/`:dot` 分支 return 使死代码，普通表恒 nil、
    dotted 丢数据——改 `case` + `nreverse`/`rplacd`，删 `al-splice`）
  - reader 短 quote：`'` 用 `(list QUOTE ...)` 而非 `(cons QUOTE ...)`——`'(1 . 2)`
    此前解析为 `(QUOTE 1 . 2)`（dotted 到 QUOTE 层），求值取 car 错；`'x` 解析为
    `(QUOTE . X)` 报 "not of type LIST"（2026-08-12）
  - builtins：`length` 用 `(loop for x in l count t)`（`always`+`count` 非法）；
    `al-bitop` 用 `(lambda (x) (floor x))`（defsubr 不产生 CL 函数，`#'fix` 未定义）
  - eval：`al-eval-special` ECASE 键改双冒号 `al::QUOTE`…`al::DEFUN`
    （`al:` 单冒号要求导出，AL 包 `:use` 空不导出，READ error）
  - eval：`al-value-symbol` 对 AL `T`→t、`NIL`→nil（此前 `(eq (al-int "T") t)`
    为假，cond else 键 `(t ...)` 与互递归真值全错，2026-08-12）
  - builtins：补 `terpri`；补几何 `distance`/`angle`/`polar`（点 = (x y [z]) 列表）
  - main：`al-run-file` 读文件改逐行（`file-length`+`make-string` 在 Windows SBCL
    崩溃），2026-08-12

## 16.3 后续方向（未排期）

- 异常语义细化（*error* handler、vl-catch-all-apply 等 CAD 错误分发）
- `al-bind` 等内建补齐（atoms-family、vl-string-*、wcmatch 等 VLISP 层）
- CAD 真机对拍扩展（`scripts/cad_verify.py` 剩余 CAD 专属用例，需 CAD 环境）
- 后续回到 P0/P1 主线（kernel/lib 包验证、ZELX）


---

# 17. 整体开发计划（2026-08-12 版，v0.1.22 → v0.3）

## 17.1 目标

以 v0.1.22（真实 @lisp 文件编译推进 + engine 冒烟全绿 + asm 宽格式闭环）为基线，
按三条主线收敛：真实包全面落地（P0）→ engine 对拍补全（P1）→ 工具链收尾（P2）。

## 17.2 已完成（2026-08-12 复核）

| 项 | 内容 | 状态 |
|----|------|------|
| P1-1 | §3.6 链接器多函数 CAD 注册 | ✅ 2026-08-08 根治（3 份 CAD golden 逐字节一致） |
| P1-2 | §12 T2 `/ 局部变量` 声明清单对齐 | ✅ §12 T1-T7 全部完成 |
| P1-3 | §12 T3 c: 命令参数语义 | ✅ 有意设计，文档标注 |
| P1-4 | §12 T4-T5 setq 重排治理 | ✅ 完成（t11 module_id 槽 / t12 dotted） |
| P2-3a | asm 大文件宽格式（nsyms>256） | ✅ 2026-08-12 闭环：`_detect_compact` 宽解析 + 5/6 字节 USUBR/FUNC 汇编；37 样本 seg0+nsyms 往返逐字节一致（`a6c0844`） |
| P2-3b | 纯顶层 selfcontained nsyms | ✅ 空函数不注册 + `.nsyms` 覆盖（set5/setcmp/setqa 还原） |
| P0-3b | t20_kwote kwote 内嵌 `-lambda-` 真机修复 | ✅ 2026-08-12 CAD 真机 `(t20-kwote)` → 42：`_emit_nested_lambda` 不设 `current_func_args` + Symbol 分支 lambda 参数读取 GET_LOCAL（原符号槽命中 `-lambda-` 槽 → `参数类型错误`）。i18n golden 字节差异（kwote lambda 参数编址 trade-off，i18n 功能等价）锁入 `test_i18n_original_byte_identity` skip |
| P0-3c | CAD 真机 t01-t24 全量验证 | ✅ 2026-08-12 22/22 通过（`scripts/cad_mcp_verify.py`，含 t19-t24 新特性）；`scripts/mcp_cad.py` MCP stdio 助手 |

## 17.3 P0 — 真实 @lisp 包全面落地

| 项 | 内容 | 状态 |
|----|------|------|
| P0-1 | kernel/lib 剩余 @lisp 包逐个编译验证（同型缺陷：gvar 槽映射、-lambda- 内嵌、cond 双 POP、ads-cmd、大小写敏感槽） | ⏳ 需 CAD 真机（当前 MCP 不可用） |
| P0-2 | 真机缺陷修复后锁入 byte-identity 回归 + pytest 全量 | 350 cases 无回归 |
| P0-3 | atlisp_u 偶发 `参数太少`（`@::compat1` foreach 边界原子）定位修复 | ✅ 2026-08-12 离线定位：`tests/atlisp_u.fas` golden 为旧版（`COMMAND`/vla- 全大写、乱码槽），与当前编译器（`ads-cmd`/vla- 混合大小写）系统性差异，非当前编译器确定性 bug；@::compat1 foreach 协议（预载/遍历/CLEAR_ARGS）结构完整。真机复核待 CAD 环境 |

## 17.4 P1 — engine 与 CAD 对拍

| 项 | 内容 | 状态 |
|----|------|------|
| P1-1 | engine 对拍：`scripts/cad_verify.py` t-series 同源用例在 engine 复跑 | ✅ 2026-08-12：t01-t21 全部一致（`scripts/engine_crosscheck.sh`）；修复短 quote/T-NIL/terpri/几何内建/al-run-file 读文件 |
| P1-2 | engine 补全：foreach/repeat、`/ 局部变量`、`&optional`/`&rest`、`_al-bind-alist`、异常语义 | ✅ 冒烟 S1-S17 全过（`engine/engine_smoke.lsp`）；异常捕获验证通过 |

## 17.5 P2 — 工具链收尾

| 项 | 内容 | 验收 |
|----|------|------|
| P2-1 | ZELX 复杂文件压缩（D1，`tools/zelx_build.py` vs LispConverter 大文件逐字节） | 复杂 zelx byte-identity（阻塞：需 ZWCAD 环境） |
| P2-2 | `unzelx` 健壮性、链接器多格式/宽槽 >255 边界复核 | 无崩溃 + 逐字节一致 |
| P2-3 | 多 CAD 平台矩阵（ZWCAD/GStarCAD/BricsCAD） | 平台真机验证（远期） |

## 17.6 验收标准

- `./scripts/run_tests.sh` 全过（py_compile + pytest + disasm→asm 往返 + byte-identity）
- 25 项 CAD golden byte-identity 不变，新增样本继续转正
- CAD 真机（AutoCAD 24.1s）清单 >=25 项全过
- `engine/` 冒烟：`al-eval-source` 覆盖 t-series 主语义无回归

## 17.7 涉及文件

- `compiler/{codegen,resource_builder,cad_symbols,linker}.py`
- `compiler/cli.py`、`compiler/_gvar_map.py`
- `decompiler/fas4_decompiler.py`、`asm/assembler.py`、`asm/opcodes.py`
- `engine/src/{reader,eval,builtins,env,values,main}.lisp`
- `tools/zelx_build.py`、`scripts/cad_verify.py`
- `tests/`（新增回归 + atlisp_u/kernel 产物）