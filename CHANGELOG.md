# Changelog

本文件记录 atlispcc 的版本变更。格式参考 [Keep a Changelog](https://keepachangelog.com/)，
版本号遵循 [SemVer](https://semver.org/)。

## [0.2.1] — 2026-11-01

### Performance

- 符号表大小写不敏感查找改为预建索引（`SymbolTable._ci_index` /
  `has_case_insensitive`）：`atlisp_u` 编译 13.0 s → 2.96 s（整体约 4×）。
- `is_builtin` 的内建名集合改为模块级预计算（原先每次调用重建 152 项集合）。
- 符号收集：`_SeenList` 维护 upper 集合、共享参数判定复用循环外构建的映射，
  去掉逐符号全表扫描。
- 模块代码：提升 defun 的跳过数与 mid 计数改前缀和，`_has_mid` 不再切片求和。
- 补丁阶段：`_res_slot_of` 预建末次出现索引，不再线性扫描 `symbol_slots`。
- 反汇编符号计数一次预计算（195 KB 4.3 s → 1.1 s）；
  `disasm` 复用布局探测阶段的指令表。
- 反编译 `is_compact_stub` 缓存键去掉未参与判定的 `sym_count`（1.93 s → 1.63 s）。
- 写盘只加密一次（`build_trailer(return_ciphertext=True)`）。

### Added

- `atlispcc --version`。
- `decompiler.detect_layout()` / `detect_layout_bytes()`：按函数前导的 `5c`/`05`
  局部变量指令 + DEFUN 头（UNK 计数兜底）判定紧凑/自包含布局；
  `use_short_subr`、反编译器、链接器、`info` 统一使用（小型紧凑 stub 不再误报）。
- `build-vlx --prv --json` / `--report <path>`：结构化打包报告。
- `scripts/cad_verify_vlx.py --remote-file/--wait`：SMB 目录缓存导致看不到新文件时，
  复用已可见文件名并在放弃前重试；探针目录改为持久隐藏目录，加载前
  `vl-unload-vlx` 卸载同名应用，COM 忙/无文档自动重试。
- `.prj` 的 `:MERGED` 输出名与源模块同名时自动改名为 `<NAME>_merged.fas` 并告警。
- `info` 的「格式」字段改用 DEFUN 头启发式判定（原先固定输出 compact-stub）。
- `build-vlx` 拒绝重复成员名；`build-vlx --prv` 与位置参数同用时报错；
  `project <file.prv>` 提示改用 `build-vlx --prv`。
- `--salt` 显式盐长度限制在 6..10（否则读取端 `find_key` 无法定位）。
- `requires-python` 下限由 3.8 提到 3.10（与 CI 矩阵和 mypy 配置一致）。

### Fixed

- 同源码同参数构建的可复现性覆盖 `build-vlx` 的 `_VLX` 导出桩编译。

## [0.2.0] — 2026-11-01

### Added

- **VLX（VRTLIB-1）打包**：`build-vlx` 按厂方容器布局写出
  `"VRTLIB-1"` 记录表（`u32 total + u16 tag + u8 name_len + NAME + payload`，
  4 字节对齐，16 字节文件尾），成员支持 `.fas`(1330) / `.dcl`(1350) /
  文本(1335) / `.dvb`(1340)，成员 payload 与独立产物逐字节相同。
- **`unpack-vlx` 子命令**：解包成员、`--list` 列成员、`--stub` 生成
  `(load "NAME")` 加载桩、默认结构校验（LOAD 记录 / tag / 重名 / 空 payload /
  对齐）与目录穿越防护。
- **`info <.vlx>`**：打印文件尾偏移、LOAD 规格、成员 tag/大小/偏移，支持
  `--encoding` 与 `--json`。
- **`.prv` 打包**：`build-vlx --prv app.prv` 读 Visual LISP 应用规范
  （`:load-file-list` 的 `:lsp`/`:fas`/`:prj`/`:dcl`、`:require-file-list`、
  `:protected` / `:active-x` / `:separate-namespace` / `:optimization` / `:target`），
  `:lsp` 现场编译，`:prj` 先编译工程。
- **`project <.prj>`**：编译 Visual LISP 工程文件（`:OWN-LIST`、`:REQUIRE`、
  `:LOAD`、`:PROJECT-KEYS`、`:FAS-DIRECTORY`、`:MERGED` 链接），支持目录递归、
  无扩展名补 `.lsp`、通配符与 Windows 反斜杠路径。
- **可复现构建**：`compile` / `link` / `project` / `asm` 新增
  `--date M/D/YY` 与 `--salt deterministic|seed:<n>|hex:<bytes>|<int>`；
  同源码同参数产出逐字节一致的 `.fas`。
- `docs/vlx-format.md`：VRTLIB-1 容器、LOAD 规格与校验规则。
- `scripts/cad_verify_vlx.py`：CAD 真机验证 —— 生成探针 VLX、`(load "…")`、
  断言导出函数可用且未导出函数隔离（AutoCAD 24.1s 实测通过）。

### Changed

- 容器尾部的盐改为厂方生成规则（ANSI-C LCG `random&`）：长度 6~10、
  字节域 `1..255`（不含 `0x00`）、相邻不重复、逆序写出。
- `build-vlx` 的 `--export` 改为编译 `_VLX` 导出桩并排进 LOAD 清单；
  移除从未接线的 `--package` 参数。
- `info` 支持 `.vlx` 输入；`unpack-vlx` 成员名按 `--encoding` 编码/解码。

### Performance

- 反汇编符号解析改用一次性计数表（原先逐指令 `list.count`，O(n²)）：
  195 KB FAS 反汇编 4.3 s → 1.1 s。
- 编译期符号收集只跑一遍，供槽序与模块注册计数共享（原先三遍）：
  `tests/atlisp_u.lsp`（312 KB）编译 13.0 s → 7.6 s。
- 符号去重改用大小写不敏感索引集合（原先线性扫描并逐项归一化）。
- 尾部加密只算一次（原先为校验 marker 加密一遍、写盘再加密一遍）。
- `disasm` 复用布局探测阶段已反汇编的指令表，不再第三次全量反汇编。

### Fixed

- `scripts/run_tests.sh` 在缺少 CAD golden `.fas` 语料时不再把
  “disasm→asm 往返”误报为失败，改为 `WARN` 跳过；`compile_src` 自检把
  `verify` 警告聚合为计数，不再刷屏。

## [0.1.35] — 2026-09-05

- lib 全量 byte-identity 836/862，`--encoding gbk` 对拍基建。
