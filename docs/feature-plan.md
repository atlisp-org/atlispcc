# 功能完善开发计划（Feature-Completion Plan）

状态：2026-08-07，P0 阶段执行中（v0.1.16，291 tests 基线）。

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
2. **单函数 + quoted 数值型常量 丢失**（CAD golden 证实 = 纯 decompile-only，
   编译产物正确，2026-08-07）。
   - **结论**：`(defun a () (quote (1 2 3)))` 的**编译产物完全正确**——
     CAD golden `D:/atlisp-test/qsingle.fas`（`vlisp-compile 'st` 真机生成）
     与我们的 seg0、nsyms、sec2 **逐字节一致**（`seg0=1400000000090100`、
     `symbo_slots=[A,A]`、`fg[1]=(CONS,0,9)`）。且在 CAD 加载运行
     `(a)` 均返回 `(1 2 3)`（golden 与 ours 双验证）✅。
   - **仅反编译器渲染失败**：单函数常量以指针形式存于资源
     `(CONS,0,9)`（byte-offset 引用），而 t12 多函数因槽位错开把常量
     存为**已解析值** `fg[2]=(1,2,3)`，故 PUSH_G[1]→gvar(2) 恰命中、可渲染。
     单函数缺该错位 → 反编译回退 `symbol_slots[1]`=`'a`，或经实验性改动
     渲染成 `'((cons 0 9))`（未达 `'(1 2 3)`）。
   - 已尝试在 `_gvar_item` 加直接 idx 解析，但会破坏其他符号解析 → 回退。
     正解是把 `(CONS,off,off)` byte-offset 指针 deref 成资源项（该项工作与
     `resource_items_with_offsets` 复用），属 decompiler 范围。
   - 验收：单函数 decoded 反编译得 `'(1 2 3)`，(resolve) validate PASS。
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
4. **反编译 A5-2**：`(setq x (if ...))` 渲染保留赋值语义。

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

## P1（延展，未执行）

| 项 | 说明 | 难度 |
|---|---|---|
| B1 | `defun-q` 引用定义机制 | 中 |
| B2 | `eval`/`read` 极端用例回归 | 低 |
| B3 | 大型图元/实体对齐 | 中 |
| B4 | 符号名大小写规范化统一 | 中 |
| B5 | `&optional`/`&rest` 多参数组合 | 中（已有 t19/t21） |

## P2（延展，未执行）

| 项 | 说明 |
|---|---|
| C1 | `vla-`/`vlax-` ActiveX 调用 |
| C2 | `command` 交互调用 |
| C3 | 多 CAD 版本（ZWCAD/ZRX）兼容矩阵 |
| C4 | DCL/ODCL 对话框 |