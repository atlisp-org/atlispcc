# atlispcc 项目进度报告

> 生成日期：2026-08-03
> 分支：main · 最新提交 `79cbaef`

---

## 1. 项目概况

**atlispcc** = AutoLISP Compiler Collection，FAS4 字节码编译器套件。
实现 `.lsp ↔ .fas` 编译/反编译，输出与 AutoCAD 编译器二进制兼容。

| 指标 | 数值 |
|------|------|
| 代码规模 | ~8,900 行 Python |
| 测试用例 | **167/167 通过**（14 个测试文件） |
| 核心模块 | `fas4_decompiler.py`(2533)、`opt.py`(1376)、`codegen.py`(796)、`fas_core.py`(707)、`cli.py`(660) |
| CLI 子命令 | compile / decompile / disasm / asm / validate / link / build-vlx |
| 优化级别 | -O1/-O2/-O3（8 个 pass） |

---

## 2. 本周期工作（2026-07-31 → 08-03）

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

## 3. 测试状态

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

## 4. 遗留问题

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

## 5. 下一步计划

1. **恢复 CAD 连接**，复测 `045b42a`（4+ 函数交叉引用）与复杂模式加载失败
2. **定位复杂模式 seg1 结构差异**（本会话疑点），修复后扩展 `tests/cad/` 回归
3. **P1：** while/cond/局部变量符号槽对齐，lambda 参数局部化
4. **P0 验收：** 链接输出 CAD 全部函数可调用、4+ 函数文件可加载

---

## 6. 关键文档

- `docs/development-plan.md` — 开发计划、遗留问题、路线图
- `docs/opcodes.md` — 操作码参考（本会话重写）
- `docs/fas-format.md` — FAS4 二进制格式
- `docs/cad-stub-format.md` — 紧凑 stub 格式规范
- `docs/lasm.md` — 反汇编/汇编文本表示
- `docs/cad-testing.md` — CAD 测试指南
