# atlispcc 项目进度报告

> 生成日期：2026-08-29
> 分支：main
> 本文档为滚动进度报告；历史周期记录保留于下方，最新周期见第 0 节。

---

## 0. 本周期（2026-08-29，v0.1.30+）摘要

| 指标 | 数值 |
|------|------|
| 测试用例 | **380 用例**（378 passed + 2 skipped） |
| kernel 编译 | **67/67 全部可编译** |
| kernel byte-identity | **67/67 逐字节一致**（seg0 + seg1 + nsyms，DIFF=0） |
| @lisp_u byte-identity | **100% 逐字节一致**（seg0+seg1+nsyms，此前 99.3%） |
| merged_2/4/8/16 byte-identity | **全部逐字节一致** |
| CAD 真机编译 | AutoCAD 24.1s `(vlisp-compile 'st ...)` 逐文件对比 |

### 本周期成果

1. **@lisp 综合包 atlisp_u 全量 byte-identity 达成（100%）**：
   - atlisp_u.lsp（502 函数 + 221 顶层语句）从 99.3%（seg0 622 字节 diff +
     seg1 9630 字节 diff）修到 **seg0+seg1+nsyms 与 CAD golden 逐字节一致**。
   - 涉及 4 个文件 8 项根因，详见 AGENTS.md「atlisp_u 全量 byte-identity（2026-08-29）」。
   - 核心修复：
     - `cad_symbols.py`：共享参数裸 lambda 归属（msg 由参数拥有者注册，不移除）
     - `patch.py`：wide SETQ_G 的 rg 列表常量 fallback 移除（CAD 一律用 fg 槽）
     - `compile_cmd.py`：嵌套 defun `#dup` FUNCOBJ 反查、混合 `_lam_slot`/
       `_tl_funcobj_slots` 补 `n_cmds+_tl_lam_count`
     - `module_code.py`：`_reg` b 槽 `i >= base-tl_funcobj_slot` 让位、`_mid_count_of`
       top-lambda-only 索引、`_skip` 函数仍发 mid（CondDefunBind）、`set` 协议
       纯顶层/混合不同槽
2. **版本**：v0.1.30（无版本号变化，bugfix 提交）。

---

## 0.1 本周期（2026-08-27，v0.1.30）摘要

| 指标 | 数值 |
|------|------|
| 测试用例 | **380 用例**（378 passed + 2 skipped） |
| kernel 编译 | **67/67 全部可编译** |
| kernel byte-identity | **67/67 逐字节一致**（seg0 + seg1 + nsyms，DIFF=0） |
| CAD 真机编译 | AutoCAD 24.1s `(vlisp-compile 'st ...)` 逐文件对比 |

### 本周期成果

1. **@lisp kernel 全量 byte-identity 达成（67/67）**：
   - 修复最后一个 DIFF `sub-system/ui/panel.lsp`：顶层
     `(if is-gcad (progn (defun C:% ...) (defun C:%% ...) (foreach ...)))`
     条件 defun **运行时绑定留在 if 守卫内**（`CondDefunBind` 标记 + 模块代码
     手动组装），此前无条件注册（守卫缺失 + 多余 `PUSH_G c; POP`）。
   - 关联修复：`-lambda-` DEFCODE 按 **codegen 发射序逆序**（嵌套 kwote lambda
     用发射序非 offset 序，前置 DEFCODE 父-子链允许 `-lambda-` 父）；`_offset_slots`
     const fallback 按 `first_cmd_slot` 判定 `+n_cmds`（panel 在命令前不加、
     menu/voice 在命令后加）；`_patch_usubr_idx` 双注册分支守卫
     （`0 <= _body_slot < nsyms` 否则落 `_res_offset`，BYTELEN 类 /local 错位 15）。
   - 详见 AGENTS.md「条件 defun 绑定（panel.lsp）」。
2. **版本**：v0.1.29 → v0.1.30（patch）。

---

## 0.1 本周期（2026-08-16，v0.1.22+）摘要

| 指标 | 数值 |
|------|------|
| 测试用例 | **348 用例**（304 passed + 35 skip + 9 failed，9 个 failed 为 `tests/compile_src/` fixture 缺失的既有失败） |
| kernel 编译 | **67/67 全部可编译**（修复 net/reload.lsp 嵌套 lambda 引用外层参数 KeyError） |
| kernel byte-identity | **9 个逐字节一致**（platform / version / funlib-download / funlib-record / net-cache / net-http / net-mid / net-registry / sub-system-config-config） |
| CAD 真机编译 | AutoCAD 24.1s `(vlisp-compile 'st ...)` 逐文件对比 |

### 本周期成果

1. **kernel 逐文件编译对拍 CAD 真机**（新增）：全部 67 个 `../kernel/src/*.lsp`
   用 atlispcc 编译（O0）成功；MCP 在 CAD 逐个 `(vlisp-compile 'st ...)` 编译生成
   67 份 golden，逐字节比对 nsyms/seg0/resource_items。**9 个 byte-identical**；
   58 个 DIFF（多数 nsyms ±1 符号槽序差异，少数大差异如 setup 228→166、
   config-dialog 160→196、package-version 117→124）。
2. **编译修复**：
   - `net/reload.lsp` KeyError：嵌套 `-lambda-` 内引用外层函数参数时走单函数
     参数读取分支 `self.local_slots[name]` 越界（`codegen.py` 条件改为
     `name in current_func_args and name in local_slots`）。
   - 模块区值位置 `t` 注册 T 槽：混合文件模块注册区无 cond else 键（force t）
     时，值位置 `(setq x (if c t))` 的 `t` 也注册 SYMBOL T
     （`cad_symbols._register_module` 预扫描 `_has_force_t`），@lisp-env /
     event-bus 的 nsyms 6/6、31/31 对齐。
   - `get_ansi_encoding` Cygwin 回退：POSIX Python（Cygwin）下 `ctypes.windll`
     不可用，现回退 `reg query` 注册表取系统 ACP（中文系统 = cp936/GBK），
     使字符串编码与 CAD 真机一致（@lisp-env "唯她" GBK vs UTF-8）。
3. **测试**：`pythonw -m pytest -q` = 304 passed + 35 skip + 9 failed。
   9 个 failed 全部在 `test_resource_stream.py`，为 `tests/compile_src/`
   fixture 未入库的**既有失败**（改动前同样 9 个），本次改动无新增回归。

### 已知残余

- 58 个 kernel 文件未 byte-identical：符号槽序 / nsyms ±1（大量）、命令模块
  `vl-ACAD-defun` 注册（voice/config-dialog/config-sync-config/package-version
  等）、大差异文件（setup/config-dialog/config-sync-file/package-load/ui-panel
  等），待逐个对拍修复。
- `tests/compile_src/`（16 个 fixture：01_math…16_i18n）未入库，导致
  `test_resource_stream.py` 9 个用例失败，需补齐 fixture 后恢复。

---

## 0.1 本周期（2026-08-15，v0.1.22+）摘要

| 指标 | 数值 |
|------|------|
| 测试用例 | **347 用例**（345 passed + 2 skip，无 xfail） |
| t-series byte-identity | **25 项** 不回归（t01-t18 + t22_activex + andor/and2/or2/andval + chinese + qsingle） |
| CAD 真机验证 | 25 项不回归 + setq-lambda 功能验证 |

### 本周期成果

1. **纯顶层多 `-lambda-` setq 绑定 byte-identity**（`7e434b1`，
   `setq-lambda.lsp`：两个顶层 `(setq X (lambda ...))`）：
   - seg0 `-lambda-` 完整 compact stub（`14 <argc>x3 00` + GET_LOCAL + INIT_ARGS +
     体 + CLEAR_ARGS + END_DEFUN，函数间 `16` 分隔、最后无 END），USUBR 5 字节
     宽格式（`35 <argc> <idx16> 03`）——与 CAD 141B 逐字节一致。
   - nsyms = fg 表长度 = `1 + len(第二区符号)`（12 = 1 + 11），非 `1 + lambda 数`。
   - 资源段布局：第一区（仅顶层表达式符号）→ 函数目录 → 第二区（体符号+参数+
     调用名，跨 lambda 去重）→ `GET_LOCAL; GVARINIT(0, 第二区数+1)` 建 fg 表
     （module_id=最后符号判 table1）→ 多 DEFCODE → `GVARINIT(第一区数+2, 函数数)`。
   - 模块代码 setq 协议 `JUMP 0; PUSH_G <lam槽+1>; DUP; SETQ_G <sym>`；`_patch_
     usur_idx` `top_lambda_args` 参数映射（绑定/读取 gvar 槽-1）。
   - 回归 `test_byte_identity_with_cad_golden[setq-lambda.lsp]`；CAD 真机
     `(@::fasext "abc")`→`"abc.fas"`、`(@::vlx "a.vlx")`→`"a.vls"`。
2. **文档更新**：development.md / development-plan.md / cad-stub-format.md /
   compilation-process.md 同步 setq-lambda 布局与协议。

### 已知残余

- seg1 尾部 8 字节（密钥边界截取乱码）非 byte-identity 目标；`resource_items`
  已全对齐。
- t24_star_error 真机待 CAD 复核（延续）。

## 0.1 本周期（2026-08-11 → 08-12，v0.1.22）摘要

| 指标 | 数值 |
|------|------|
| 测试用例 | **348 用例**（347 passed + 1 skip，无 xfail） |
| t-series byte-identity | **25 项**（`CAD_T_SERIES_IDENTICAL`：t01-t18 + t22_activex + andor/and2/or2/andval + chinese + qsingle） |
| CAD 真机验证 | **25 项**（`scripts/cad_verify.py`：t01-t24 + i18n，t24 待复核） |
| 版本 | **v0.1.22** |

### 本周期成果

1. **真实 @lisp 文件编译推进**（kernel 单文件 / bootstrap / base-function）：
   - `9c2acee` kernel 单文件编译产物 CAD 加载修复（in-package/lambda 常量/
     字符串槽/循环检测）。
   - `b2ee792` 纯顶层文件顶层 lambda 编译为内嵌 `-lambda-` SUBR（bootstrap 与
     CAD **逐字节一致**）：seg0 紧凑 stub `14 <argc>x3 00` + 体、模块代码
     `PUSH_G <sym>; JUMP 0; PUSH_G <-lambda-槽>; FUNC_REF set`。
   - `52a41a6` base-function CAD 加载 `:dialog` 错误修复（foreach item 槽 gvar
     映射 + cond body 双 POP 修复 + strip_docstring + `command`→`ads-cmd` +
     超 int32 整数按 REAL + 字符串大小写敏感）。hkrepro 完全 byte-identical。
2. **`engine/` SBCL AutoLISP 运行时冒烟全绿**（`2abdc72`）：reader/parse-list/
   scan-token/builtins/eval 修复，R1-R15 全过（算术/defun/apply/list/dotted/
   if/while/cond/foreach/strcat/动态作用域/function-lambda/length/logand/fix）。
   文档：fas-format §7 探索索引、development-plan §16。
3. **文档精简**：development-plan §8-§13/§15 压缩为归档（1247→706 行），
   §14/§16/§17 保留；`compilation-process.md` 扩写至 583 行；`fas-format.md`
   更新至 v0.1.22（宽格式/`-lambda-`/module_id 槽/`ads-cmd`）。
4. **版本 0.1.22**：PyPI 发布。

### 已知残余

- t24_star_error 真机待 CAD 复核。
- atlisp_u 加载返回值偶发一次 `参数太少`（`@::compat1` foreach 边界原子），
  不影响任何功能。

## 0.2 本周期（2026-08-11，v0.1.21）摘要

| 指标 | 数值 |
|------|------|
| 测试用例 | **348 用例**（346 passed + 1 skip，zelx 偶发失败与编译无关） |
| t-series byte-identity | **18/18** 不变 |
| @lisp 综合包编译 | **atlisp_u.lsp**（502 函数 + 221 顶层语句）CAD 真机完整加载运行 |
| 版本 | **v0.1.21**（已发布 PyPI） |

### 本周期成果

1. **@lisp 综合包编译支持**（`tests/atlisp_u.lsp` 此前无法解析/加载）：
   - 裸引用关键字 `'(defun)`/`'(lambda)`/`'(setq)`/`'(cond)` 按数据解析
     （`parser.py`）。
   - 顶层 `(progn ...)` 展开、条件/嵌套 defun → `(setq f '(lambda ...))`、
     80 个多 kwote 改写为引用数据（`cli.py`）。
   - **commands + 顶层混合** gvar 槽重映射：新增 `compiler/_gvar_map.py` 解析
     seg1 模块注册段，`_offset_slots` 二次生成模块代码按实际槽位修正
     USUBR/PUSH_G/FUNC。
   - **大文件 USUBR/FUNC 宽格式**：符号槽 >255 用 5 字节 USUBR
     （`35 argc idx16 flags=3`）、6 字节 FUNC（`51 argc idx16 flags=1 00`），
     小文件保持 3 字节（golden 逐字节不变）。
   - `top_level_count` 由收集器 `module_reg_count` 推导（避免高估）。
   - 编译产物在 CAD 真机（AutoCAD 24.1s）**模块代码完整执行、功能全部可用**
     （`@::safe-eval`/`define-config-typed`/`@::compat1` 等正常）。详见
     `docs/development-plan.md` §15。
2. **版本 0.1.21**：补丁版本升级 + 发布 PyPI。
3. **文档同步**：AGENTS.md 测试统计（344→348）、@lisp 综合包编译支持、
   development-plan §15 新章节。

## 1. 本周期（2026-08-08）摘要

| 指标 | 数值 |
|------|------|
| 测试用例 | **310 用例**（309 passed + 1 skip，无 xfail） |
| t-series byte-identity | **19/19**（t01-t18 + t22_activex） |
| CAD 真机验证 | **24/24**（`scripts/cad_verify.py`）+ 链接器 4 场景可调用 |
| disasm→asm 往返 | 39 文件字节一致 |

### 本周期成果

1. **CAD 环境恢复**：CAD 进程崩溃（0xC0000005）后经 MCP 子进程探测确认
   `atlisp-mcp --stdio` 通道可用，`cad_verify.py` 独立连接复核 24/24 全过。
2. **t22 vla-/vlax- ActiveX 真机缺陷修复**（编译 bug，非测试问题）：
   - vla- 符号名保留大小写（ActiveX 方法名大小写敏感），`_enc_sym` 不再对
     `vla-`/`vlax-` 前缀 `.upper()`；`normalize_vla_name` 方法名首字母大写。
   - 值位置 `T`/`t` 注册符号槽并 `PUSH_VALUE` 引用（此前大写 `T` 被过滤+内联
     PUSH_T，导致 nsyms 少 1、后续符号槽偏移）。
   - USUBR/FUNC 目标符号槽末尾（超出 gvar 表）按 `gvar 槽 = nsyms` 编址。
   - 编译产物与 CAD golden `tests/cad/t22_activex_cad.fas` 逐字节一致，锁入
     `test_t_series_byte_identity`。详见 `docs/development-plan.md` §11。
3. **t21 测试期望修正**：`t21-product` 由 `(&optional factor &rest rest)`（min=0，
   触发 §3.5 CAD 硬性不收集 rest）改为 `(factor &rest rest)`（min=1），真机
   `(t21-product 2 3 4)` → 24。
4. **文档同步**：AGENTS.md 测试统计（292→304）、t22 golden 覆盖、
   development-plan §11 新章节、feature-plan C1/C2 真机确认。

## 1.2 追加（2026-08-08，§3.6 链接器 CAD 兼容根治）

修复链接器输出在 CAD 真机功能错误的预先存在问题（§3.6「字节码功能正确」
断言不成立，CAD 复核证实）：
- **分隔符** `01 00 16` → `16`（CAD stub 实测）；`final_offset` 长度 3→1
- **参数绑定/读取槽** 按合并 gvar 槽-1（`_pre_gvar` 表内）或参数序
  `nsyms-1-arg_rev`（表外）；单/多函数文件操作数语义区分
- **符号槽顺序** 单函数文件分离体符号/参数（共享参数最后），多函数不分离
- **sec2_items** 补 `2*nfuncs+2` 修正
- 新增 `test_link_byte_identity_with_cad_golden`（3 份 CAD golden：
  addmul/sqsum/three，`tests/cad/link/*_cad.fas`）逐字节一致；CAD 真机
  add/mul、square/sum-squares、f1/f2/f3、碰撞场景全部可调用
- pytest **309 passed + 1 skip**

---

## 2. 项目概况

**atlispcc** = AutoLISP Compiler Collection，FAS4 字节码编译器套件。
实现 `.lsp ↔ .fas` 编译/反编译，输出与 AutoCAD 编译器二进制兼容。

| 指标 | 数值 |
|------|------|
| 代码规模 | ~17,400 行 Python（compiler+decompiler+core+asm+tools+scripts） |
| 测试用例 | **348 用例**（347 passed + 1 skip，20 个测试文件） |
| 核心模块 | `decompiler/fas4_decompiler.py`(3149)、`compiler/cli.py`(2274)、`compiler/codegen.py`(1441)、`compiler/opt.py`(1376)、`core/fas_core.py`(902) |
| CLI 子命令 | compile / decompile / info / analyze / roundtrip / validate / zelx / unzelx / disasm / asm / link / build-vlx |
| 优化级别 | -O1/-O2/-O3（9 个 pass） |

---

## 3. 本周期工作（2026-07-31 → 08-03）

### 2.1 已提交

| 提交 | 内容 |
|------|------|
| `7466fa0` | stub 字节码对齐 CAD、文档重组、测试收集 `tests/cad/` |
| `86d5f4f` | 多函数/递归/混合场景字节码对齐 CAD、符号大写、顶层表达式模块代码 |
| `8dbe1c5` | 反编译参数名、codegen 公式 `nsyms-argc+i`、seg1 items 计数、死代码清理 |
| `d50f264` | 开发计划阶段 1+2：重复代码移除、gitignore、while/lambda 符号、`build_module_code` nsyms 参数 |
| `6cab1ac` | P0-2 nsyms 接线、P1-2 lambda skip_reg（quoted 参数） |
| `30afd4e` | GVARINIT cap st_init 到 nsyms 范围（修复 cross4 越界 gvar 槽） |
| `045b42a` | 4+ 函数交叉引用加载失败（Xsubr 0x44 错误） |
| `79cbaef` | **cond 末子句非 T 时标签未解析 bug 修复 + opcodes 文档全面更新** |

### 2.2 本会话新增成果（`79cbaef`）

**Bug 修复 — `compiler/codegen.py` `_emit_cond`：**
- 现象：编译 `(cond ((< x 0) "negative") ((= x 0) "zero") ((> x 0) "positive"))`
  这类**无 `T` 兜底子句**的 cond 时，报 `ValueError: Unresolved label: _cond_next_XX_Y`
- 根因：最后一个非 `T` 子句创建的 `label_next` 标签从未被标记，`BytecodeBuffer.resolve()` 找不到目标
- 修复：最后一个子句改用 `label_end` 作为 JMP16_IFNOT 跳转目标
- 回归：167/167 测试通过

**文档 — `docs/opcodes.md` 全面重写：**
- 57 个操作码逐一说明：格式、描述、**代码生成器发射位置**
- 新增自包含 vs 紧凑 stub 格式**操作码级对比表**
- 10+ 个完整字节码示例：if/else、while、cond、foreach、repeat、setq、
  and/or 短路求值、尾递归、DEFUN 头、USUBR 调用（两种格式对比）
- 控制流结构图示 + 编码函数参考表（`encode_usubr3`/`encode_func3` 等）

---

## 4. 测试状态

### 3.1 全量测试 167/167 ✅

| 测试文件 | 用例 | 覆盖 |
|---------|------|------|
| test_parser.py | 19 | AST 解析 |
| test_lexer.py | 11 | 词法分析 |
| test_symbol_table.py | 10 | 符号表/作用域 |
| test_analyzer.py | 9 | 编译分析/尾递归 |
| test_cli.py | 10 | CLI 路径 |
| test_compile_decompile.py | 29 | 编译-反编译往返（含 AutoCAD `fun-cad.fas` 参考回归） |
| test_compiler_output.py | 12 | FAS 输出正确性 |
| test_optimizer.py | 32 | 优化 pass |
| test_linker.py | 10 | 多文件链接 |
| test_assembler.py | 5 | 反汇编/汇编往返 |
| test_disasm.py | 8 | 反汇编健壮性 |
| test_packages.py | 4 | CL 风格包系统 |
| test_variadic_args.py | 5 | 可变参数 |
| test_vlx_builder.py | 3 | VLX 容器 |

### 3.2 CAD 兼容性（AutoCAD 24.1s）

| 场景 | 状态 |
|------|------|
| 简单函数（1-4 个） | ✅ `(add 2 3)`→5 |
| 递归 | ✅ `(fact 5)`→120 |
| if/while/cond | ✅ 全部正确 |
| 局部变量 / 字符串拼接 | ✅ |
| 多函数交叉引用（2-3 个） | ✅ `(sum-sq 3 4)`→25 |
| 尾递归 / &optional/&rest / 顶层 setq | ✅ |
| lambda/quote | ⚠️ `(map-inc ...)` → `no function: X` |
| 4+ 函数交叉引用 | ⚠️ 已修复 Xsubr 0x44（`045b42a`），待 CAD 复测 |

---

## 5. 遗留问题

### 4.1 本会话发现：复杂函数 CAD 加载失败（**待解决**）

**现象：** `(defun f (n / i limit) (if (< n 2) nil (progn ... (while (and ...) ...))))`
这类**复杂模式**（`progn` 在 if-else 中 + `while` 配合 `and` 条件）编译出的
FAS 在 CAD 加载时报：
```
无效的二进制文件格式: 体 (2) 错误
```

**已排查：**
- ✅ 编译-反编译往返正常，字节码语义正确
- ✅ seg0 头部/total_size/紧凑 stub 结构正常
- ✅ USUBR 索引经 `build_mvar_tables` 校验全部正确
- ✅ `fun_our.fas`、`multi_our.fas`、`test_classify.fas`（cond 无 T 子句）均可在 CAD 加载
- ❌ `test_prime.fas`（progn-in-if + while-and）、`test_6func.fas`、`cad_test_complex.fas` 加载失败

**疑点：** seg1 资源段结构（符号注册/GVARINIT 顺序）对复杂函数体可能与 CAD 不一致。
MCP 调试工具会话中途不可用，尚未定位到根因。

**待办：** 恢复 CAD 连接后，用最小复现（`test_prime.fas`）对比工作/失败文件的
seg1 明文结构，定位符号注册差异。

### 4.2 开发计划中的遗留（`docs/development-plan.md`）

| 优先级 | 问题 | 状态 |
|--------|------|------|
| P0 | 链接器多函数 CAD 注册（只注册首函数） | 符号顺序已复刻 cmd（`c88e4c0`），字节级对齐，CAD 复测待 3.7 环境稳定 |
| P0 | `build_module_code` PUSH_G 越界（4+ 函数） | 已修复 `045b42a`，待 CAD 复测 |
| P1 | while/cond/局部变量符号槽逐字节对齐 | 进行中 |
| P1 | lambda 参数绑定（`(lambda (x) ...)` x 未局部化） | 部分修复（skip_reg） |
| P2 | CAD 加载器内部逆向（gvar 表精确模型） | 未开始 |
| 严重 | CAD 会话稳定性（坏 FAS 破坏 Lisp 环境需重启） | 运维约束 |

---

## 6. 下一步计划

1. **恢复 CAD 连接**，复测 `045b42a`（4+ 函数交叉引用）与复杂模式加载失败
2. **定位复杂模式 seg1 结构差异**（本会话疑点），修复后扩展 `tests/cad/` 回归
3. **P1：** while/cond/局部变量符号槽对齐，lambda 参数局部化
4. **P0 验收：** 链接输出 CAD 全部函数可调用、4+ 函数文件可加载

---

## 7. 关键文档

- `docs/development-plan.md` — 开发计划、遗留问题、路线图
- `docs/opcodes.md` — 操作码参考（本会话重写）
- `docs/fas-format.md` — FAS4 二进制格式
- `docs/cad-stub-format.md` — 紧凑 stub 格式规范
- `docs/lasm.md` — 反汇编/汇编文本表示
- `docs/cad-testing.md` — CAD 测试指南
- `docs/compilation-process.md` — 编译过程说明（.lsp → .fas 各阶段详解）
