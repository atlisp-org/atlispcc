# atlispcc 开发计划

> 本文档记录 `atlispcc`（FAS4 编译器/反编译器工具链）当前功能完成情况、
> 遗留问题与后续开发路线。基于 AutoCAD 24.1s 实测与代码测试状态
> （166/166 通过）。

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

### 2.2 CAD 兼容性（核心）✅

AutoCAD 24.1s 实测正确执行：

- **多函数**：`(add 3 4)`→7、`(multiply 3 4)`→12；t07 四函数全对
- 递归：`(factorial 5)`→120、`(fib 10)`→55
- 控制流：while、cond、嵌套 if
- 字符串/局部变量/算术
- **`&optional`**：`(opt1 1)`→`(1 nil)`、`(opt1 1 2)`→`(1 2)`（缺省 nil）
- **`&rest`**：`(g 1 2 3)`→`(1 (2 3))`、`(h 1 2 3 4)`→`(1 2 (3 4))`（收集为列表）
  > 注意：最后一次 CAD 回归（t01/multi2 既有用例）因 CAD 运行异常中断，
  > CAD 恢复后需复核既有 14/14 用例。

关键逆向成果：
- **USUBR 索引 = 符号 gvar 槽 - 1**
- DEFCODE 仅最后一个追加 `01`
- 模块代码参数化、函数代码引用多函数范围
- 符号槽收集算法（函数名逆序、唯一参数紧跟、共享参数最后、递归重复槽）
- `nsyms = len(entries) - 函数数 + 1`
- DEFUN 头 `0x14`：b1=参数数、b2=最低参数、b3=大参数、b4=00 有限/01 无限
  （AutoCAD `vlisp-compile` 实测：`/` 局部变量不计入头）
- `&optional`：`14 <max> <min> <max> 00`；`&rest`：`14 <min>x3 01`

### 2.3 代码测试 166/166 ✅

全部通过（含 `tests/test_variadic_args.py` 5 用例）。

---

## 3. 遗留问题与根因分析

### 3.1 ✅ 已解决：多函数 stub 反编译符号槽映射

> 已通过 `_gvar_item` 用 gvar 表（`build_mvar_tables` 的 `idx+1`）、
> `_call_name`/`_extract_signature` 参数绑定用 gvar 槽、链接器
> gvar-1 适配（`_patch_usubr_idx`/`stub_sym_map`）修复。

### 3.2 while/cond/局部变量符号收集与 CAD 逐字节差异（优先级：中）

**现象**：t04/t05/t11 的字节码与 CAD 不完全一致，但 CAD 执行正确。

**根因**：CAD 对 while/cond/局部变量的符号槽收集有特殊规则
（如 `_al-bind-alist` 辅助符号、字符串/内建顺序），尚未完全逆向。

**技术路线**：用更多 CAD 样例（while/cond/局部变量/foreach/repeat）
实测符号槽顺序，完善 `cad_symbols.py`。

### 3.3 CAD 加载器内部机制（优先级：低/研究）

**现象**：多函数 USUBR 索引、参数槽的精确 gvar 表偏移依赖 CAD
加载器内部行为（`build_mvar_tables` 模拟不完全准确）。

**技术路线**：结合调试器（如之前 fas-format.org 的 OD 方法）逆向
acad.exe 的 FAS 加载器，完善 gvar 表模型。

### 3.4 反编译 stub 参数名错位（优先级：高）

**现象**：stub 反编译的参数名错位，如 `(defun add (a b) ...)` 反编译为
`(defun add (b b_2) ...)`；`(defun g (a &rest r))` → `(defun g (n &rest r))`。

**根因**：编译端参数绑定/读取槽 = `gvar_slot(arg)-1`（参数符号可能不在
gvar 表，fallback 为 `nsyms`），与 `symbol_slots`（符号注册顺序）索引
不一致；`_gvar_item(idx)`/`_gvar_symbol_gvar(idx)` 对参数槽 fallback 到
`symbol_slots[idx]` 取错符号。参数槽与 `symbol_slots` 的偏移因符号注册
顺序而异（t01 差 1、restpure 差 2），无通用映射。

**技术路线**：
- 从 `INIT_ARGS`（`2*全部参数数+1`）与 DEFUN 头 b2 确定参数区间，
  用「参数顺序 + 源码符号推断」重建参数名
- 或：反编译时按 gvar 表（含参数符号）重建参数槽 → 符号映射
- 或：编译端把参数符号也注册到 gvar 表（使 `gvar_slot-1` 与 slots 一致）

### 3.5 纯 `&rest`（min=0）CAD 运行时空（优先级：中）

**现象**：`(defun sum (&rest n) ...)` 编译为 `14 00 00 00 01`（min=0），
CAD 加载后函数可定义（SUBR）但调用返回空（rest 未收集）。

**根因**：CAD 对 `b4=01` 且 `b1/b2/b3=0` 的 rest 收集行为未逆向；实测
`min≥1` 的 `&rest`（如 `(a &rest r)`）收集正确。

**技术路线**：
- 逆向 CAD 加载器对 `b4=01, min=0` 的处理（rest 槽位置）
- 或：编译器对纯 `&rest` 报错/提示「需至少一个必填参数」
- 文档已注明建议 `(defun f (x &rest r))` 形式

### 3.6 链接器多函数 CAD 只注册首个函数（优先级：高）

**现象**：`atlispcc link` 合并多文件后，CAD `load` 只注册第一个函数；
如 `lk_comb.fas` 中 `(square 7)`→49 但 `(sum-squares 3 4)` 空；
`grh.fas` 中 `(g ...)` 对但 `(h ...)` 空。反编译/测试均正常。

**根因**：链接输出的**模块代码**（`build_module_code(n)`）与 DEFCODE
函数目录对 CAD 的注册机制不完全兼容——首函数经模块注册可用，后续函数
未绑定（疑似模块代码的 `PUSH_G<2n+1-i> SETQ_G<n-i>` 引用槽或
`01 00 16` 分隔符/`_func_ranges_bytes` 与 CAD 不一致）。

**技术路线**：
- 用 CAD 实测链接输出的模块代码/函数注册，对比单文件多函数（cmd）
  的差异（cmd 多函数 CAD 全注册可用）
- 检查 `build_module_code` 多函数变体在链接场景的 PUSH_G/SETQ_G 槽
  与合并符号表的对应
- 验证 `_func_ranges_bytes`（多函数代码引用范围）在链接输出的正确性

### 3.7 CAD 运行环境稳定性（优先级：中/运维）

**现象**：CAD 会话易失——`No open document`、调用超时/卡死、
`new_document` 失败需手动恢复；连接池 reconnect 偶发返回 `\`。

**技术路线**：
- 自动化测试前确保 CAD 有活动文档；卡死时手动恢复
- 为 CAD 实测建立独立测试脚本（`D:\atlisp-test`），避免干扰主会话

---

## 4. 开发计划

### 4.1 短期（P0，1-2 周）

目标：修复反编译参数名、链接器 CAD 注册、纯 &rest。

| 任务 | 说明 |
|------|------|
| 反编译参数名（3.4） | 参数槽 → 符号映射（INIT_ARGS/gvar 表） |
| 链接器多函数 CAD 注册（3.6） | 模块代码/DEFCODE 与 CAD 对齐 |
| 纯 `&rest` min=0（3.5） | 逆向 CAD rest 收集或编译报错 |
| CAD 回归复核 | CAD 恢复后重测既有 14/14 用例 |

### 4.2 中期（P1，1-2 月）

目标：扩大 CAD 兼容覆盖，字节码逐字节一致。

| 任务 | 说明 |
|------|------|
| while/cond/局部变量符号槽 | 逆向 CAD 特殊规则（`_al-bind-alist` 等） |
| 命令函数 `c:` 特殊处理 | `vl-ACAD-defun` 注册 |
| 复杂表达式 | mapcar/lambda/apply/foreach 的 CAD 编码 |
| 错误处理函数 | `*error*`、条件子程序 |
| CAD 兼容回归套件 | 扩展 D:\atlisp-test 测试集 |

### 4.3 长期（P2，3-6 月）

目标：完整工具链，健壮性与性能。

| 任务 | 说明 |
|------|------|
| 优化器增强 | 跨函数常量传播、死代码消除扩展 |
| 性能 | 大文件编译/反编译优化 |
| CAD 版本兼容 | 多 AutoCAD 版本（2008-2025）FAS 变体 |
| VLX 增强 | 依赖收集、eTransmit |
| 文档完善 | 完整 FAS 格式规范 |

---

## 5. 优先级排序

| 优先级 | 内容 | 影响 |
|--------|------|------|
| P0 | 反编译 stub 参数名（3.4） | 反编译质量（参数名错位） |
| P0 | 链接器多函数 CAD 注册（3.6） | 链接输出 CAD 可用性（只注册首函数） |
| P1 | 纯 `&rest` min=0（3.5） | 可变参数完整性（CAD 空） |
| P1 | while/cond/局部变量符号槽 | CAD 字节码逐字节一致 |
| P1 | 命令函数 `c:` 处理 | CAD 功能完整 |
| P2 | CAD 加载器内部逆向 | gvar 表精确模型 |
| P2 | 性能与多版本兼容 | 工具链健壮性 |

---

## 6. 验收标准

- **P0 完成**：`pytest` 166/166 通过；反编译参数名正确；链接输出 CAD 全部函数可调用
- **P1 完成**：测试集 ≥ 20 个用例全部 CAD 执行正确；字节码逐字节一致；纯 `&rest` CAD 可用
- **P2 完成**：多版本 CAD 兼容；大文件性能达标

---

## 7. 相关文档

- `docs/cad-stub-format.md` — CAD 紧凑 stub 格式规范（核心）
- `docs/fas-format.md` — FAS4 二进制格式
- `docs/opcodes.md` — 操作码参考
- `docs/development.md` — 架构详解
