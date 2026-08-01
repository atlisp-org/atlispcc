# atlispcc 开发计划

> 本文档记录 `atlispcc`（FAS4 编译器/反编译器工具链）当前功能完成情况、
> 遗留问题与后续开发路线。基于 AutoCAD 24.1s 实测与代码测试状态
> （158/161 通过）。

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

### 2.2 CAD 兼容性（核心）✅

AutoCAD 24.1s 实测 **14/14 用例正确执行**：

- **多函数**：`(add 3 4)`→7、`(multiply 3 4)`→12；t07 四函数全对
- 递归：`(factorial 5)`→120、`(fib 10)`→55
- 控制流：while、cond、嵌套 if
- 字符串/局部变量/算术

关键逆向成果：
- **USUBR 索引 = 符号 gvar 槽 - 1**
- DEFCODE 仅最后一个追加 `01`
- 模块代码参数化、函数代码引用多函数范围
- 符号槽收集算法（函数名逆序、唯一参数紧跟、共享参数最后、递归重复槽）
- `nsyms = len(entries) - 函数数 + 1`

### 2.3 代码测试 158/161

3 个失败均为**多函数 stub 反编译**（不影响 CAD 兼容）：

| 测试 | 问题 |
|------|------|
| `test_complex_lsp_roundtrip_opt_levels` | 多函数反编译符号错位 |
| `test_link_cross_file_call` | 链接后多函数反编译 |
| `test_link_first_definition_wins` | 链接后多函数反编译 |

---

## 3. 遗留问题与根因分析

### 3.1 多函数 stub 反编译符号槽映射（优先级：高）

**现象**：编译-反编译往返时，多函数程序反编译出现符号错位
（如 `"total: "` 解析成 `i`、函数体混淆、局部变量名错乱）。

**根因**：
1. 编译端参数绑定/读取用 `nsyms-1-i` 槽位
2. 反编译器用 `symbol_slots[idx]` 解析，多函数时 `nsyms-1-i` 槽位
   与符号槽不一致
3. 反编译器需重建 CAD 的 **gvar 表**（`build_mvar_tables`）来正确
   映射参数槽，当前直接使用 symbol_slots

**技术路线**：
- 反编译器 `_collect_signature` 参数/局部绑定分析改用 gvar 表
  （`idx+1` = gvar 槽）
- 多函数函数切分（`_build_from_defun_headers`）验证 DEFUN argc 头
  与参数槽对应
- 链接器合并后的符号槽重建（`_extract_functions` + 索引重映射）

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

---

## 4. 开发计划

### 4.1 短期（P0，1-2 周）

目标：修复 3 个反编译测试，达到 161/161。

| 任务 | 说明 |
|------|------|
| 反编译器重建 gvar 表 | `_collect_signature` 参数/局部绑定用 `build_mvar_tables` |
| 多函数符号槽映射 | PUSH_VALUE/PUSH_G/USUBR 索引按 gvar 槽解析 |
| 链接器适配 | 合并后符号槽重建 + 函数名提取 |
| 回归验证 | CAD 14/14 + pytest 161/161 |

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
| P0 | 多函数反编译符号槽映射 | 代码质量（3 测试） |
| P0 | 链接器多函数适配 | 代码质量（2 测试） |
| P1 | while/cond/局部变量符号槽 | CAD 字节码逐字节一致 |
| P1 | 命令函数 `c:` 处理 | CAD 功能完整 |
| P2 | CAD 加载器内部逆向 | gvar 表精确模型 |
| P2 | 性能与多版本兼容 | 工具链健壮性 |

---

## 6. 验收标准

- **P0 完成**：`pytest` 161/161 通过；CAD 兼容 14/14 保持
- **P1 完成**：测试集 ≥ 20 个用例全部 CAD 执行正确；字节码逐字节一致
- **P2 完成**：多版本 CAD 兼容；大文件性能达标

---

## 7. 相关文档

- `docs/cad-stub-format.md` — CAD 紧凑 stub 格式规范（核心）
- `docs/fas-format.md` — FAS4 二进制格式
- `docs/opcodes.md` — 操作码参考
- `docs/development.md` — 架构详解
