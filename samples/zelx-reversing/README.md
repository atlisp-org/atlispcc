# ZELX 受控样本生产指南（用于逆向 ZwStream 编码）

目标是产出**微型** `.lsp → .fas → .zelx` 三件套，逐字节对齐以逆向 ZWCAD 的
载荷编码。已准备好的测试文件在 `samples/zelx-reversing/`：

- `t1.lsp` = `(defun t1 (x) (1+ x))` → `t1.fas`（201B）
- `tiny.lsp` = 两个函数（`tiny-add`、`tiny-hello`）→ `tiny.fas`（306B）

## 操作步骤（在你的桌面上）

1. 打开 ZWCAD（或任一台有 LispConverter.exe 的机器）。
2. 启动 `LispConverter.exe`（FAS&VLX Converter）。
3. 点 **Select File** 添加 `t1.fas`（先用最小的）。
4. 「Convert to」保持默认；输出目录选 **Original Directory**。
5. 点 **Convert All**，得到 `t1.zelx`（与 t1.fas 同目录）。
6. 对 `tiny.fas` 重复。
7. 把 `t1.zelx`、`tiny.zelx` 放回 `samples/zelx-reversing/`。

## 提交后我做什么

用 `tools/zelx_info.py` 解密 + `tools/zelx_diff.py` 逐字节对比：

```
python -m tools.zelx_diff samples/zelx-reversing/t1.fas samples/zelx-reversing/t1.zelx --full
```

微型样本能直接暴露：
- ZWCAD 载荷头（模块头 / 代码引用 / `XX` 字段）
- 符号表编码（`5b→57`、类型标记、顺序）
- ZwStream 代码区 opcode 语义（对单个函数，每个 opcode 可定位到 Lisp 语句）
- ZAS 目录段（段1）字段

逆向出编码后即可在 `compiler/` 下实现 `fas→zelx` 写入器。

## 已破解（参考 docs/zelx-format.md）

- 容器：`!ZAS` 64B 头 + 段1目录 + 段2 `[len][field][1]` + 加密载荷 + 密钥尾部
- 加密：载荷 = 明文 滚动XOR(密钥)，密钥 = 尾部 `[key_len][0][2][前缀]\n;fas4 crunch\n;`
- 载荷 ≈ fas seg1 重编码：符号 `5b→57`、`55` 字符串块同构、opcode 重映射
