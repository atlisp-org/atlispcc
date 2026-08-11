# 功能完善开发计划（Feature-Completion Plan）

状态：2026-08-08，P0 阶段执行中（v0.1.18，310 tests 基线）。

本计划聚焦 **AutoLISP 语言特性支持** 的补齐与验证。以分阶段（P0/P1/P2）+ 验收
标准组织；每项标注：目标、验收、结论（验证时填充）。

---

## P0 核心语言特性（本次执行对象）

### A1. `set` / `setq`

**结论：已完全支持（无需代码改动）。**

- `(set 'x val)` 作为原生 `set` USUBR 调用编译，与 CAD byte-identity
  （setcmp / i18n golden 证明）。
- 期间曾尝试把 `(set 'x val)` 改写为 setq 路径，导致 5 个 byte-identity
  测试失败（setcmp/p06/p07/i18n），已 `git checkout compiler/codegen.py` 回退，
  恢复 291 绿。→ **`(set 'x val)` 必须以 `set` USUBR 发出，不可当 setq。**

### P0-A1. `*error*` 处理函数

**结论：已支持。**

- 作为独立 defun 编译/反编译/validate 全通过。
- 作为 `/ 局部变量`（经 `_al-bind-alist` 协议）亦通过；`tools/validate.py`
  的 `SYMBOL_RE` 已允许 `*` 等字符。
- 无代码改动。

### P0-A3. `eval`

**结论：已支持（功能正确）。**

- 单向 compile→decompile→validate 通过。
- 有一个既有的 cosmetic 反编译顺序重排（`(setq expr ...)` 移到 `(eval expr)`
  之后），属 §10.4 cosmetic 类，不影响功能。

### P0-A4. `apply` / `funcall`

**结论：已支持，所有变体单向通过。**

- `(apply '+ lst)`、`(funcall fn a b)`、`(apply '(lambda ...) (list ...))`、
  `(apply f args)`（&rest）全部编译/反编译/validate 通过。

### P0-A5. 多语句位置（progn / if / cond / foreach / while 嵌套）

**基础支持；发现 2 个既有缺陷（非本次会话引入）。**

正常：`(if c e1 e2)`、嵌入式 `foreach`/`while`/`cond`（无 `/ locals` 时）
roundtrip 正确，`t05_cond`（cond+T，无 locals）与 CAD golden 逐字节一致。

问题 A5-1（**编译产物错误，已修复**）：
`/ 局部变量` + `cond` 含大写 `T` 子句（`(T <int>)`）时，codegen 符号槽错位：
- `(defun s (x / lst) (setq lst (cond ((> x 10) 100) (T 5))) lst)`
  反编译 → `(defun s (t / lst) ... ((lst t 10) 100) ...)`，`>` 被映射成 `LST`，
  参数 `x` 变 `t`。
- disasm 证实是 **seg0 发射字节错误**（`USUBR 2` 引用 LST 而非 `>`），非
  反编译渲染问题。
- 小写 `(t 5)` 正常、无 `/ locals` 时 `(T 5)` 也正常 → 触发条件 = `_al-bind-alist`
  协议 + `cond` `T` 子句。
- 根因：`CadSymbolCollector.add()` 只过滤精确字符串 `'T'`（不滤 `t`），大写 T
  未进 derive；codegen `_emit_cond_stub` `symtab.get_or_add(cond.name)`
  （codegen.py:758）晚注册 → 槽位错位。
- **修复（2026-08-07）**：`add()` 的 `T`/`nil` 过滤改为仅非 force 时生效；
  Cond 收集对 `t`/`T` else 子句键以 `force=True` 注册（CAD t05 golden `SYMBOL T`
  实测，大小写不敏感）。`(T 5)` 与 `(t 5)` 现等价；`T` 单独作值（PUSH_T 内联）
  仍不占槽，仅 cond else 键占槽。
- 回归测试：`test_cond_upper_t_else_slot` / `test_cond_upper_t_if_value`。
  全量 293 tests、37 disasm→asm byte、18 CAD byte-identity 全绿。

问题 A5-2（**仅反编译渲染**，产物正确）：
```
(setq x (if c e1 e2))
```
seg0 正确（if 值留栈 → SETQ_G），反编译却渲染为 `(if c e1 e2)` + `(setq x nil)`，
丢失赋值关系。属 decompiler 渲染层缺陷，不影响 CAD 运行。

---

## 修补补齐清单（P1，建议优先级）

1. **已修复 A5-1**（2026-08-07）：`/ locals` + `cond` 大写 `T` else 槽位错位
   已修（`add()` force + Cond else 键 force 注册）。见上方 P0-A5 节。
2. **已修复 单函数 + quoted 数值型常量 丢失**（CAD golden 证实 = 纯 decompile-only，
   编译产物正确，2026-08-07）。
   - **结论**：`(defun a () (quote (1 2 3)))` 的**编译产物完全正确**——
     CAD golden `D:/atlisp-test/qsingle.fas`（`vlisp-compile 'st` 真机生成）
     与我们的 seg0、nsyms、sec2 **逐字节一致**（`seg0=1400000000090100`、
     `symbo_slots=[A,A]`、`fg[1]=(CONS,0,9)`）。且在 CAD 加载运行
     `(a)` 均返回 `(1 2 3)`（golden 与 ours 双验证）✅。
   - **已修复（2026-08-07）**：单函数常量以 deferred 字节区间引用存于资源
     `(('CONS',A,B),)`（A=相对偏移、B=字节长度，数据紧跟 deferred 语句）。
     在 `_gvar_item` 对单函数 stub 的 PUSH_G 槽位做 deref：
     - `_locate_deferred_base`：在 `resource_items_with_offsets` 找
       `INT8 A, INT8 B, CONS, LIST1` 三元组 → base = 语句结束偏移。
     - `_decode_deferred_value`：按资源流语义解码 sec2[base:base+B]
       （INT8/INT32/SYMBOL/STRING/LIST/CONS 递归），得到 `(1 2 3)`。
     - 仅当长度>0 且解码出真实值时采纳；`(CONS,0,0)` 占位（dotted
       `(cons 1 . 2)` 合成产物）与多元素链式（t12）不受影响。
     - 单函数 stub 的 PUSH_G 操作数**直接指向 gvar 槽**（非多函数 +1），
       修复前 `idx+1` 越界回退符号 `'a`。
   - 验收：`test_qsingle_golden_deferred_quoted_list`（qsingle_cad.fas 反编译
     得 `(defun a () '(1 2 3))`，validate PASS）。全量 296 tests、38 disasm→asm、
     18 CAD byte-identity 全绿。
3. **已修复 A5-2**（本为"反编译渲染"，2026-08-07 实证为**编译器 bug**）：
   `(setq r (if c e1 e2))`（`if` 作为 setq RHS 的**值位置**，函数中段）。
   - **结论**：CAD golden `D:/atlisp-test/a4.fas` 逐字节证实——值位置的 `if`
     不 POP then 分支值（`PUSH_INT8[1]; JUMP; PUSH_INT8[2]; SETQ_G`），值须
     流到外围消费者（SETQ_G / 算术/函数实参）。
   - **根因**：`_emit_if`（codegen.py:496）原以 `not self._in_tail_context`
     判别 then 分支是否 POP——但中段 setq RHS / 算术实参的 `if` 使尾上下文为
     False，误发 `POP` 丢弃 then 值，SETQ_G 拿到 nil。
   - **修复**：引入语句上下文标志 `_in_stmt_ctx`（codegen.py）。仅裸语句位置
     （函数体中间语句 / progn 中间语句 / while·foreach·repeat 体 / cond 体 /
     kwote `-lambda-` 体 / init code）置位；值位置（setq RHS、算术、函数实参、
     list/cond 求值）经 `_value_ctx()` 清位。`_emit_if` 的 then-POP 改由
     `self._in_stmt_ctx` 触发（`_emit_stmt` 封装）。语句位置的 if 仍 POP。
   - 回归：`test_value_position_if_no_then_pop`（PUSH_INT8→JUMP 间无 POP）。
     全量 295 tests、CAD a4 值位置字节对齐、既有 byte-identity（i18n/t-series/
     CAD golden）全绿。
4. **已修复反编译 A5-2**（随 codegen A5-2 修复连带解决，2026-08-07）：
   CAD golden `D:/atlisp-test/a4.fas` 现正确反编译为 `(setq r (if ...))`（保留
   赋值语义），不再把值丢给外侧。无 decompiler 改动。

---

## 验收标准（本次 P0）

- [x] A1 set/setq 已支持（byte-identity 净校验）。
- [x] A2 *error* 单向通过。
- [x] A3 eval 单向通过（含 cosmetic 备注）。
- [x] A4 apply/funcall 全变体单向通过。
- [x] A5 多语句位置正常路径通过；新增 A5-1 / A5-2 两个缺陷登记。
- [ ] 全量 pytest 保持 291 passed / 1 skipped。
- [ ] `scripts/run_tests.sh` 全绿。

---

## P1（延展）

| 项 | 说明 | 难度 | 状态 |
|---|---|---|---|
| B1 | `defun-q` 引用定义机制 | 中 | ✅ 已补强 |
| B2 | `eval`/`read` 极端用例回归 | 低 | ✅ 已补测 |
| B3 | 实体/DXF 数据结构 roundtrip | 中 | ✅ 已补测 |
| B4 | 符号名大小写规范化统一 | 中 | ✅ 已补测 |
| B5 | `&optional`/`&rest` 多参数组合 | 中（已有 t19/t21） | ✅ 真机运行验证（无 golden，CAD 不支持变参编译） |

### B1 `defun-q`（已完成）

`(defun-q foo (x) (princ x))` 编译成 `(setq foo '(lambda (x) (princ x)))`（foo 为
quoted 数据列表，非被调函数）。codegen `_generate_quoted_defun` 已实现；新增回归
`test_defun_q_preserves_lambda_semantics`：断言 `setq foo`/`lambda`/`princ` 保留、
`(foo ...)` 命名调用不出现、validate PASS。语义正确。

### B2 `eval`/`read`（已完成，纯测试）

P0-A3 已支持 eval。新增 `test_eval_read_edge_cases_roundtrip` 锁住 7 组极端组合：
`(eval x)`、`(eval (list '+ 1 2))`、无参 `(read)`、`(read-line fp)`、
`(eval (quote (setq y 5)))`、`(eval (read s))`、`(eval (quote (+ 1 2)))`——全部
roundtrip + validate PASS，关键调用名保留。无代码改动。

### B3 实体/DXF 数据结构（已完成，纯测试）

新增 `test_entity_dxf_data_roundtrip` 锁住 6 组实体操作：`(assoc 0 (entget ent))`、
`entmake` 组码列表、`(entmod (subst (cons 62 1) (assoc 62 e) e))`、
`(cons (car e) (cdr e))`、`entsel`、`cons`/`list` 构造组码——全部
roundtrip + validate PASS，关键调用与组码/字符串不丢失。无代码改动。

### B4 符号名大小写规范化（已完成，纯测试）

新增 `test_symbol_case_normalization_roundtrip` 验证混合大小写符号稳定规范化：
函数名统一小写（`MyFunc→myfunc`、`c:MyCmd→c:mycmd`、`Calc2→calc2`、`Mix123→mix123`），
参数/布尔/`/`/`*` 等符号不破坏、括号合法。无代码改动（现行统一大写
策略已覆盖大小写不敏感）。

### B5 `&optional`/`&rest`（真机运行验证，**无 golden**）

t19_variadic / t21_variadic_extra 有 17 个单测（`test_variadic_args.py`）+ 真机
功能验证（`scripts/cad_verify.py`）。**无法产出 byte-identity golden**：CAD 的
`vlisp-compile`/编译器本身不支持 `&optional`/`&rest`（AutoLISP 标准参数不支持
变参），因此**不存在**可比对的 CAD 编译产物。

正确锚点 = **真机运行验证**：`scripts/cad_verify.py` 把编译好的 t19/t21 `.fas`
加载进 CAD 执行并断言返回值（optional 缺省、rest 收集、组合、纯 optional），
结果语义一致性由此保证，而非字节比对。已转正为 B5 的主要验收方式。（该限制
同时说明：变参语法是 LispConverter 扩展，超出 CAD 原生编译范围。）

> **t21-product 修正**（2026-08-08，CAD 真机发现）：`t21-product` 原定义
> `(&optional factor &rest rest)` 为 min=0，触发 §3.5 CAD 硬性不收集 rest
> 限制（CAD 真机任何参数均返回空）。已改为 `(factor &rest rest)`（min=1，
> CAD 收集「剩余参数」），真机 `(t21-product 2 3 4)` → 24。optional+rest 组合
> 的测试意图由 `t21-greet`（纯 optional）+ `t21-first-arg`（纯 rest）保留。

## P2（延展）

| 项 | 说明 | 状态 |
|---|---|---|
| C1 | `vla-`/`vlax-` ActiveX 调用 | ✅ 已补测（roundtrip + cad_verify t22） |
| C2 | `command` 交互调用 | ✅ 已补测（roundtrip + cad_verify t23） |
| C3 | 多 CAD 版本（ZWCAD/ZRX）兼容矩阵 | 未执行 |
| C4 | DCL/ODCL 对话框 | ✅ 已补测（roundtrip，纯测试） |

### C4 DCL/ODCL 对话框（已完成，纯测试）

DCL 对话框函数（`load_dialog`/`new_dialog`/`action_tile`/`start_dialog`/
`done_dialog`/`unload_dialog`/`set_tile`/`get_tile`/`mode_tile`/`dimx_tile`/
`dimy_tile`）作为普通内建（USUBR）调用编译，无需特殊编译器逻辑。新增
`test_dcl_dialog_roundtrip`：6 组形态（对话框生命周期、action_tile 回调绑定、
控件读写、mode_tile、尺寸查询、完整流程含 done_dialog 状态码）全 roundtrip +
validate PASS。无代码改动（DCL 函数早已在内建调用路径）。

### C1 `vla-`/`vlax-` ActiveX（已完成）

`vla-`/`vlax-` 属性和方法作为普通内建调用（USUBR）编译。**2026-08-08 真机
验证暴露两个编译器缺陷并修复**（`t22_activex` 原编译产物在 CAD 返回空）：

1. **vla- 符号名保留大小写**：CAD 对 `vla-get-<Method>` 等方法符号保留
   **原始大小写**且方法名首字母大写（ActiveX 方法名大小写敏感）——
   源码 `vla-get-count` → 符号槽 `vla-get-Count`（`vlax-` 前缀保持小写）。
   此前 `_enc_sym` 统一大写导致 CAD 无法匹配 ActiveX 方法。修复：
   `cad_symbols.normalize_vla_name` + `codegen` 同名函数 + `resource_builder._enc_sym`
   对 vla-/vlax- 前缀保留大小写。
2. **值位置 `T` 符号槽**：`(if c T nil)` 的大写 `T` 此前被 `add()` 过滤且
   codegen 内联 `PUSH_T`，导致 T 符号槽缺失、nsyms 少 1、后续符号槽整体偏移。
   CAD 对值位置 `T`/`t` 均注册符号槽并用 `PUSH_VALUE` 引用（t18 小写 `t`
   碰巧走符号引用路径通过，t22 大写 `T` 触发）。修复：`add()` 对 `t`/`T`
   大小写不敏感注册（nil 恒内联），codegen stub 格式下 `T` 走 `PUSH_VALUE`。

**现状**：`t22_activex` 编译产物与 CAD golden（`tests/cad/t22_activex_cad.fas`）
seg0+sec2+nsyms **逐字节一致**（锁入 `test_t_series_byte_identity`），CAD 真机
24/24 用例全过。新增：
- `test_activex_vla_vlax_roundtrip`：8 组形态（`vla-get-*`/`vla-put-*`/`vla-Add*`、
  `vlax-get/put-property`、`vlax-invoke-method`、`vlax-variant-value`、
  `vlax-get-acad-object`）全 roundtrip + validate PASS。
- `tests/cad/t22_activex.lsp` + `scripts/cad_verify.py` 真机用例：只读结构断言
  （ActiveDoc 存在 + 文档计数 > 0），不用具体图元名，无破坏性。**CAD 真机确认**
  （2026-08-08）：`(t22-acad-doc)` 返回 VLA 对象、`has-doc`=T、`pos-count`=T。

### C2 `command` 交互调用（已完成）

`command`/`command-s`/`vl-cmdf`/`vl-cmd-s` 作为普通内建（USUBR）调用，参数正常
求值（字符串/坐标列表/数字/`pause` 符号），无需特殊编译器逻辑。新增：
- `test_command_vlcmdf_roundtrip`：9 组形态（字符串命令、坐标列表、pause、
  多语句、`(if ...)` 实参、`nil` 结尾）全 roundtrip + validate PASS。
- `tests/cad/t23_command.lsp` + `scripts/cad_verify.py` 真机用例：`command-s`
  画圆 → `entlast` 断言为 CIRCLE → 擦除，全程包在 UNDO 组内自清理，不留新
  实体。**CAD 真机确认**（2026-08-08）：`(t23-created-circle-p)` = T。

---

## S3 反编译精细度收尾（2026-08-09，已完成 ✅）

主线计划见 `docs/development-plan.md` §12（T0-T7）。全部为解码器侧修复，
compiler/资源段零改动，CAD byte-identity 18/18 不回归。完成项：

| 任务 | 内容 | 结果 |
|---|---|---|
| T1 | foreach/repeat 循环前置 setq 保序 | t16/t17 golden 与源码顺序一致 |
| T2 | `/ locals` 清单与源码对齐 | t16/t17 移除多余本地化（保持全局）；t11 经 `_al-bind-alist` 不变 |
| T3 | c: 命令参数本地化语义澄清 | 确认有意设计（§10.4 显式标注），不改 |
| T4 | `(setq expr)` 与 `(eval expr)` 顺序 | 根因 POP 分支先 flush 滞留语句；+2 回归 |
| T5 | `_gvar_item` stub 多元素常量 | `PUSH_G` 命中 `gvar_table[idx+1]` 立即返回；t11 `'(result i)` 完整 + setq 保序；+1 回归 |
| T6 | `_render_block` 性能热点 | 大样本 6.9s → 5.5s（`lru_cache` 缓存 `is_compact_stub`）；无残余热点 |
| T7 | 回归与文档 | pytest 316 passed / 1 skipped；新增 4 项语义回归；新增 `docs/compilation-process.md` |

**已知限制**（非本阶段范围）：~~t12 的 deferred 链式 quote 常量解码
（`(setq lst 'a)` 应为 `'(a b c)`、`'(cons 1 2)` 应为 `'(1 . 2)`）——
`_deref_deferred_constant` 仅处理单元素包裹，多元素链式 tuple 未展开，另出处理。~~

**✅ 已解决（2026-08-11，P0-3）**：t12 deferred 链式 quote 常量解码已修复——
根因是函数表 GVARINIT 的 **module_id 槽**（`var_pos + st_init`，结构化常量如
`(A B C)`）未被解析。新增 `core.fas_core.build_module_id_slots`（仅登记结构化
LIST/CONS module_id，原子型 SYMBOL/STRING 是符号槽重复不登记）+ 反编译器
`_gvar_item` 越界查询该槽 → `(setq lst '(a b c))` 正确还原；dotted 常量
`('CONS',1,2)` 由 `_render_data_item` 改渲染为 `(1 . 2)`（原误渲染 `(cons 1 2)`）。
新增回归：`test_module_id_slots_structured_only` + 扩展
`test_t12_golden_global_setq_not_localized`。