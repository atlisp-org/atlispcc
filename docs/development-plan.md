# atlispcc 开发计划

> 本文档记录 `atlispcc`（FAS4 编译器/反编译器工具链）当前功能完成情况、
> 遗留问题与后续开发路线。基于 AutoCAD 24.1s 实测与代码测试状态
> （167/167 通过）。

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
| i18n.lsp 混合模式 | ❌ | seg1 模块代码结构差异 |

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

### 2.3 代码测试 167/167 ✅

全部通过（含 `tests/test_variadic_args.py` 5 用例）。

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

### 3.4 ✅ 已解决：反编译 stub 参数名错位

> **修复**（2026-08）：
> - `decompiler/fas4_decompiler.py` `_extract_signature`：参数名重复或非字母时，尝试
>   `symbol_slots[idx+1]` 回退；无有效替代则 fallback 到 `arg_N`
> - `codegen.py` `_emit_init_args`：参数绑定公式从 `nsyms-1-i` 改为
>   `nsyms-argc+i`（参数在符号槽中按 `nsyms-argc` 偏移）
> - `codegen.py` `_emit_expr`：参数读取公式同步修正
> - `cli.py` `_patch_usubr_idx`：PUSH_VALUE 逆公式更新
> - CAD 已验证：`(defun hypot (a b) ...)` → `(defun hypot (a b) ...)` ✓

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

### 4.2 短期（P0，1-2 周）

目标：修复链接器 CAD 注册、4+函数交叉引用模块代码。

| 任务 | 说明 |
|------|------|
| 链接器多函数 CAD 注册（3.6） | 模块代码/DEFCODE 与 CAD 对齐 |
| `build_module_code` PUSH_G 越界 | n≥4 时 `2*n+1` 超出 `nsyms-1`，需动态计算 |
| `_build_cad_module_code` 增强 | 支持 defun 间夹杂 setq/if 的复杂顶层表达式 |

### 4.3 中期（P1，1-2 月）

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
| ~~P0~~ | ~~反编译 stub 参数名（3.4）~~ | ✅ 已修复 |
| ~~P0~~ | ~~链接器多函数 CAD 注册（3.6）~~ | ✅ 已修复 |
| ~~P0~~ | ~~`build_module_code` PUSH_G 越界~~ | ✅ 已修复（4+函数交叉引用 CAD 实测通过） |
| ~~P1~~ | ~~lambda 参数绑定~~ | ✅ 已修复（λ 常量 PUSH_G 操作数 = gvar 槽-1 = symtab 槽-nfuncs+1） |
| ~~P1~~ | ~~while/cond/局部变量符号槽~~ | ✅ 已修复（while 无 WHILE 槽/末体无 POP；cond 测试正序+结果倒序） |
| P1 | i18n.lsp 混合模式 | defun+顶层表达式混杂，`cad_symbols.py` 持续块规则 |
| P2 | CAD 加载器内部逆向 | gvar 表精确模型 |
| P2 | 性能与多版本兼容 | 工具链健壮性 |

> 纯 `&rest` min=0（3.5）已逆向并加编译警告（CAD 硬性不收集），移出优先级表。

---

## 6. 验收标准

- **P0 完成**：`pytest` 167/167 通过；反编译参数名正确；链接输出 CAD 全部函数可调用
- **P1 完成**：测试集 ≥ 20 个用例全部 CAD 执行正确；字节码逐字节一致；纯 `&rest` 编译警告已实施
- **P2 完成**：多版本 CAD 兼容；大文件性能达标

---

## 7. 相关文档

- `docs/cad-stub-format.md` — CAD 紧凑 stub 格式规范（核心）
- `docs/fas-format.md` — FAS4 二进制格式
- `docs/opcodes.md` — 操作码参考
- `docs/development.md` — 架构详解
