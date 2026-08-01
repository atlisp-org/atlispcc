# CAD 安全测试指南

> 目标：验证 atlispcc 编译/链接输出的 FAS 在 CAD 中可执行，**同时不破坏
> CAD 的 Lisp 环境**。遵循本指南可避免「加载坏 FAS → 环境损坏 → 需重启
> CAD/系统」的问题。

## 为什么需要安全策略

AutoLISP 的 `(load "...fas")` 在**加载阶段**解析字节码并建立符号/函数表。
若 FAS 字节码非法（USUBR 索引越界、DEFUN 头错误、符号槽错位），
CAD 加载器可能：

- **访问冲突**（0xC0000005），Lisp 解释器损坏
- 函数绑定到错误槽，调用**无限递归/卡死**
- 符号表污染，后续 `load`/`getvar` 异常
- 最坏情况：`No open document`、`new_document` 失败，**需重启 CAD 甚至系统**

## 安全测试流程

```
源码 .lsp → 编译/链接 → 本地字节码校验 → CAD 加载（独立实例）→ 环境检查
```

### 1. 本地字节码校验（不做不行）

CAD 加载前，先在本项目内校验输出：

```sh
# 反汇编，检查 USUBR 索引与 DEFUN 头
atlispcc disasm out.fas out.lasm
# 反编译，确认函数/参数/符号结构
atlispcc decompile out.fas out_decomp.lsp
# 单元测试确保 167/167
python -m pytest
```

重点核对：
- DEFUN 头 `14 <b1> <b2> <b3> <b4>` 与参数一致
- USUBR 索引 → gvar 槽 = 索引 + 1，指向正确符号（`build_mvar_tables`）
- 符号槽布局与 cmd 编译的等价文件一致（多函数链接场景）

### 2. 使用独立 CAD 实例

`atlisp-mcp` 支持多实例。**测试未验证/实验性的 FAS 用独立实例**，
不要污染主会话：

```sh
# 发现/连接独立实例（如第二个 AutoCAD）
cad_pool_discover
cad_pool_connect key=<独立实例key>
```

主实例仅用于**已验证输出**的最终确认。

### 3. 加载前快照 + 加载后检查

```lisp
;; 加载前
(getvar "DWGNAME")          ; 非空 = 环境正常

;; 加载
(load "D:/atlisp-test/mine_new/xxx.fas")

;; 加载后
(type 函数名)               ; SUBR = 已注册
(函数名 ...)                ; 执行验证
(getvar "DWGNAME")          ; 仍非空 = 环境未被破坏
```

### 4. 恢复策略

| 症状 | 处理 |
|---|---|
| `No open document` | `new_document`；失败则 CAD 命令行 `NEW` |
| 调用超时/卡死 | 等 10-20s；仍卡则终止该调用 |
| 访问冲突 / 无文档且无法恢复 | **重启 CAD 进程**；极端情况重启系统 |
| 连接池 reconnect 返回 `\` | `cad_pool_discover` 后重新 connect |

## 禁忌

- ❌ 不要在 CAD 中 `load` 手动 patch 过字节码的 FAS（试错）
- ❌ 不要在**主会话**测试未经验证的多函数/链接输出
- ❌ 连续加载多个坏 FAS 后继续开发（环境已污染，先恢复）
- ✅ 坏字节码试错改用**独立实例**或先本地校验

## 相关

- `docs/development-plan.md` 3.7 — CAD 环境稳定性与安全策略
- `docs/cad-stub-format.md` — FAS 格式规范（DEFUN 头、符号槽、USUBR）
