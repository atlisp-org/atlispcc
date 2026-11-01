# VLX 容器（VRTLIB-1）格式

> 本文描述 `compiler/vlx_builder.py` 读写的 `.vlx` 容器：布局、记录表、
> LOAD 规格、成员命名，以及 `atlispcc build-vlx` / `unpack-vlx` / `info`
> 的对应行为。FAS4 本体格式见 [fas-format.md](fas-format.md)。

## 1. 总布局

```
偏移 0    "VRTLIB-1"                        8 字节 magic
偏移 8    u32 LE 尾部标记偏移                = 文件长度 - 16
偏移 12   记录 #0（4 字节对齐）              LOAD 描述符
          …记录 #n（各自 4 字节对齐）        成员
末尾 16   00 00 00 00 "VRTLIB-1" 00 00 00 00 固定文件尾
```

magic 与首条记录之间**没有其它头部结构**：`u32@8` 是文件尾偏移，
`u32@12 / u16@16 / u8@18` 已经是记录 #0 自己的 `total_len / tag / name_len`。

## 2. 记录结构

```
u32 LE  total_len = 7 + name_len + payload_len
u16 LE  tag
u8      name_len
bytes   NAME        （大写化；DBCS 首字节 + 尾字节整体保留）
bytes   payload     （与独立文件逐字节相同，容器不重新加密）
填充    0x00，补齐到 4 字节边界（按文件绝对偏移对齐）
```

| tag | 含义 | LOAD 清单键 |
|---|---|---|
| `1240` | LOAD 描述符（记录 #0，名字固定 `LOAD`） | — |
| `1330` | `.fas` 代码模块 | `:fas` |
| `1335` | 纯文本资源 | 不进清单 |
| `1340` | `.dvb` | 不进清单 |
| `1350` | DCL 对话框 | `:DCL` |

成员名 = `basename` 的大写化（`nstring-upcase`）：ASCII `a-z` 转大写，
`0x81..0xFE` 双字节字符整体保留（中文名不会被拆坏）。容器不添加/剥离扩展名。

## 3. LOAD 规格（记录 #0 的 payload）

`prv-make` 无条件写出的列表，`T` 为点对、`nil` 为裸键：

```lisp
((:protected . T) (:active-x . T) (:separate-namespace . T)
 (:load-file-list (:fas "core.fas") (:DCL "dlg.dcl")))
```

- `:load-file-list` 保留成员声明顺序；编译期生成的导出桩（`--export`）追加在末尾
- `:require-file-list` 的成员只作为记录存在，**不**进 LOAD 清单
- 规格文本按 `--encoding`（默认系统 ACP）编码

## 4. 打包与加载语义

`build-vlx` 的三条路径：

```sh
atlispcc build-vlx app.fas res/dlg.dcl readme.txt -o app.vlx
atlispcc build-vlx app.fas -o app.vlx --export main setup     # 追加 _VLX 导出桩
atlispcc build-vlx --prv app.prv                              # 按 .prv 规范打包
```

- `--export` 会把 `(vl-doc-export 'name)` 编译成 `_VLX` 成员；容器本身不承载
  命名空间导出，导出必须由 FAS 代码在加载时执行
- `.prv` 路径：`(:load-file-list (:lsp …) (:fas …) (:prj …) (:dcl …))` 中
  `:lsp` 现场编译为 `<stem>.fas`，`:prj` 先编译工程（`:MERGED` 取合并产物），
  `(:require-file-list …)` 只作为资源携带

## 5. 校验与解包

```sh
atlispcc info app.vlx [--encoding gbk] [--json]
atlispcc unpack-vlx app.vlx -o dist/app [--list] [--stub load.lsp] [--no-verify]
```

- `info`：文件尾偏移、LOAD 规格文本、每个成员的 tag / 大小 / 偏移
- `unpack-vlx`：默认做结构校验——记录 #0 必须是 `(1240, "LOAD")`、成员 tag 合法、
  名字不重复、payload 非空、记录 4 字节对齐；成员名为 `.`/`..`、含路径分隔符或
  NUL 时拒绝写出（防目录穿越）
- `--stub`：按成员顺序生成 `(load "NAME")` 加载桩

## 6. 与 `.prj` / `.prv` 的关系

| 输入 | 行为 |
|---|---|
| `.prj`（`atlispcc project x.prj`） | 编译源码，`:MERGED` 时链接为单个 `.fas`（不打包 VLX） |
| `.prv`（`atlispcc build-vlx --prv x.prv`） | 按 VLIDE 的打包规范直接产出 `.vlx` |

`.prv` 的 `:target` 决定默认输出（`-o` 优先），`:optimization` 为 `st` 时 `-O0`、
`lsm`/`lsa` 时 `-O1`。
