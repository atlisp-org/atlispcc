# atlispcc 编译过程详解（.lsp → .fas）

本文详细说明 atlispcc 如何把 AutoLISP 源码（`.lsp`）编译成与 AutoCAD 编译器
**逐字节一致**的 FAS4 二进制（`.fas`）。面向编译器开发与调试，对应代码路径为
`compiler/` 目录。

> 相关文档：`docs/development.md`（架构管线概览）、`docs/fas-format.md`
> （FAS4 二进制格式）、`docs/cad-stub-format.md`（紧凑 stub 布局）、
> `docs/lasm.md`（汇编语言参考）、`docs/opcodes.md`（操作码参考）。

## 1. 管线总览

```
.lsp 源码
  │
  ├─ 源码解码（core.fas_core.decode_source_text）  → UTF-8/ANSI 文本
  │
  ├─ Parser（lexer + parser）                     → Program（compiler/ast_nodes.py）
  │     └─ 包系统注册（defpackage/in-package → packages.py）
  │
  ├─ [可选] OptPipeline.optimize(-O1/2/3)          → 优化后的 Program
  │
  ├─ 改写（cli.py，@lisp 综合包支持）：
  │     ├─ _flatten_top_level_forms  顶层 (progn ...) 展开
  │     ├─ _lower_nested_defuns      条件/嵌套 defun → (setq f '(lambda ...))
  │     ├─ _rewrite_top_lambda_binds 顶层 (set 'sym (lambda ...)) → -lambda- SUBR
  │     ├─ _lower_multi_kwote        多 (function (lambda ...)) → 引用数据
  │     └─ _lower_immediate_lambda   ((lambda ...) args) → (apply '(lambda ...) ...)
  │
  ├─ derive_symbol_names（cad_symbols）            → CAD 符号槽顺序
  ├─ module_reg_count（cad_symbols）               → 模块注册域宽度
  │
  ├─ SymbolTable                                   → entries / name_to_idx / 常量表
  │
  ├─ CodeGenerator（stub_format=True）             → seg0 函数字节码
  │     ├─ 每函数 generate_function → (bytes, start_offset)
  │     ├─ 内嵌 -lambda-（kwote）→ 独立目录项
  │     └─ 顶层表达式 → top_level_code（模块代码输入）
  │
  ├─ _build_cad_module_code / build_command_module_code / build_module_code
  │                                                 → seg1 模块代码
  │
  ├─ ResourceBuilder.build()  ← 两轮               → seg1 资源段
  │     └─ build_mvar_tables 重建 gvar 表
  │     └─ _patch_usubr_idx / _offset_slots 修正 seg0 索引
  │
  └─ FasWriter.write(compact=True)                 → .fas 二进制
```

CLI 入口：`compiler/cli.py::cmd_compile`（`atlispcc compile`），默认
`compact=True`（CAD 紧凑 stub 格式）。

## 2. 阶段零：源码解码

`cmd_compile` 以二进制打开源码文件，经 `core.fas_core.decode_source_text`
解码。`encoding` 参数决定解释：`'ansi'`/`'auto'`/`'system'` 解析为系统 ANSI
编码（`resolve_encoding`），否则按指定编码。中文 GB2312/ANSI 源码在此转为
Python 字符串。若传入的 `source` 不是文件路径，则视为源码文本直接使用。

## 3. 阶段一：解析（Parser）

`Parser(source)` 先 `lexer.tokenize` 产出 Token 流，再逐 form 构建 AST。

### 3.1 词法（compiler/lexer.py，102 行）

| Token | 说明 |
|---|---|
| `LPAREN` / `RPAREN` | `(` / `)` |
| `QUOTE` | `'`（quote） |
| `FUNCTION` | `#'`（双字符，function） |
| `DOT` | `.`（dotted pair） |
| `STRING` | `"..."`，处理 `\n \r \t \e \\ \"` 已知转义，未知保留 `\`+字符 |
| `REAL` | `-?\d+\.\d+(?:[eE]...)?` |
| `INTEGER` | 整数 |
| `SYMBOL` | `[^\s()'";]+` |
| 注释 | `;` 行注释至行尾；`;| ... |;` 块注释（支持跨行，行列计数正确） |
| `1+`/`1-` | `1+` 恒为 SYMBOL；`1-` 需后跟空白/括号/引号等边界才为 SYMBOL（否则落入数字/符号） |

UTF-8 逐字符推进天然支持（非 ASCII 落入 SYMBOL 分支）。

### 3.2 语法（compiler/parser.py，300 行）

`parse()` 循环 `parse_form()` 直至 EOF，收集 `Program(forms)`。读者条件：

- `#-sbcl <form>`：消费标记、保留其后 form（@lisp 包用 `#-sbcl` 包裹 CL 兼容层）
- `#+sbcl <form>`：非 SBCL 环境跳过下一 form

`parse_form(quoted)` 分派：

- `LPAREN` → `parse_list`
- `QUOTE` `'` → `QuotedExpr(expr=parse_form(quoted=True))`
- `FUNCTION` `#'` → `QuotedExpr(..., kwote=True)`（`(function X)` 走 kwote 机制）
- 叶子 → `Symbol/Integer/Real/String`

`parse_list(quoted)` 按首符号分派特殊形式：

| 形式 | 处理 |
|---|---|
| 空 `()` | `ListExpr()` |
| **裸引用关键字** | `quoted=True` 且单符号为 `defun/setq/if/lambda/cond/...` 关键字列表且紧跟 RPAREN → 普通 `ListExpr(items=[head])` 数据列表（`'(defun)` 等，@::safe-form-p 白名单比对用） |
| defun/defun-q | `_parse_defun`：包名 munge（`包|名`）、`/` 切 locals、`&optional`/`&rest` 收集、`is_cmd = name 大写 C:` 前缀 |
| setq | 成对解析，奇数目标允许 `value=None` |
| if | `cond + then + [else]`（else 可缺省） |
| while/foreach/repeat | body 收集；foreach 的 var/list_expr 在前 |
| progn | 语句序列 |
| lambda | 参数列表 → `LambdaNode(args, body)` |
| cond | 子句 `(test action...)` → `Cond(clauses)` |
| defpackage | `:use`/`:export`（含 `(use a b)`、`(export a b)` 两种形态）→ `packages.add_package` |
| in-package | `packages.set_current(pkg_name)` |
| quote/function 字面量 | `QuotedExpr(expr, kwote=(name=='function'))` |
| 其他 | 普通调用或数据列表；dotted 引用 → `ListExpr(..., dotted=True)` |

**包系统**（compiler/packages.py，49 行）：`PackageTable.munge(pkg, name)` →
`f'{pkg}|{name}'`（分隔符 `|`）；`resolve('pkg:sym')` → `pkg|sym`。`in-package`/
`defpackage` 在解析期注册；`_parse_defun` 对当前包非空、非 `C:` 前缀、不含 `:`
的函数名做 munge。

### 3.3 解析错误

解析失败抛 `ParseError`，CLI 打印到 stderr 后 `sys.exit(1)`。

## 4. 阶段二：优化（可选）

`opt_level > 0` 时调用 `opt.optimize(program, level=opt_level)`（compiler/opt.py，
1376 行）：

| 级别 | 内容 |
|---|---|
| O1 | 常量折叠 + 死分支消除 + 窥孔优化 |
| O2 | O1 + 常量传播 + 死赋值消除 + 重复 O1 |
| O3 | O2 + 跨函数常量传播 + 死代码消除 + 小函数内联 + 删除死函数 |

## 5. 阶段三：源码改写（cli.py，@lisp 综合包支持）

优化前/后，`cmd_compile` 对 `program.forms` 依次做改写（v0.1.21 起，让
`tests/atlisp_u.lsp` 等真实 @lisp 大包可编译）：

| 改写 | 函数 | 作用 |
|---|---|---|
| 顶层 `(progn ...)` 展开 | `_flatten_top_level_forms` | @lisp 包整体包裹模式展开为顶层 form |
| 条件 defun 提升 | `_hoist_conditional_defuns` | 顶层 `(if c (progn (defun f ...) ...))` 的 defun 体提升为独立函数（进 seg0 + DEFCODE），if 内留 `CondDefunBind` 绑定标记——运行时绑定留在 if 守卫内（panel.lsp 实测，非无条件注册），模块代码发射 `PUSH_G <func-obj>; SETQ_G <sym>; USUBR(1, vl-ACAD-defun); PUSH_NIL; POP` |
| 嵌套 defun 原生内嵌 | `_emit_nested_defun`（codegen） | 函数体内局部辅助函数 `(defun g () ...)` → CAD 原生内嵌 DEFUN（`JUMP; DEFUN g; ...; END_DEFUN; PUSH_G <g-obj>; SETQ_G g`），n1-n6 实测 byte-identity |
| 顶层 lambda 绑定 | `_rewrite_top_lambda_binds` | 纯顶层文件 `(set/setq 'sym (lambda ...))` → CAD 内嵌 `-lambda-` SUBR（seg0 完整 compact stub：`14 <argc>x3 00` + GET_LOCAL + INIT_ARGS + 体 + CLEAR_ARGS + END_DEFUN；函数间 `16` 分隔、最后无 END；USUBR 5 字节宽格式），模块代码 setq 协议 `JUMP 0; PUSH_G <-lambda-槽+1>; DUP; SETQ_G <sym>`；资源段：第一区 → 函数目录 → 第二区（体符号+参数+调用名，跨 lambda 去重）→ fg 表 GVARINIT → 多 DEFCODE → `-lambda-` 超表槽（setq-lambda.lsp byte-identity） |
| 多 kwote 降级 | `_lower_multi_kwote` | 多个 `(function (lambda ...))`（>1）→ 引用数据 `'(lambda ...)`（apply/mapcar 回调等价） |
| 立即 lambda 调用 | `_lower_immediate_lambda` | `((lambda ...) args)` → `(apply '(lambda ...) (list ...))` |

## 6. 阶段四：符号注册（cad_symbols）

### 6.1 收集入口

```python
for sym in derive_symbol_names(program):
    if is_const_entry(sym):      symtab.add_constant(sym[1])
    elif __real_<n>__:           symtab.add_real(float(...))
    elif "..."（字符串）:         symtab.add_string(s[1:-1])
    elif sym in name_to_idx:     symtab.add_force(sym)   # 递归/跨函数重复槽
    else:                        symtab.get_or_add(sym)
```

`derive_symbol_names(program)`（compiler/cad_symbols.py，993 行）按 **CAD 符号槽
顺序**收集，是逐字节一致性的核心。规则（AutoCAD 24.1s 实测）：

### 6.2 多函数规则（`CadSymbolCollector.collect_program`）

1. 区分 defun/顶层，统计参数使用 → `shared`（被 ≥2 函数使用的共享参数）。
2. `_register_module(program)` 计算 `module_reg_count`（模块注册域符号数 =
   函数名 + 顶层表达式符号，**由实际注册数推导**，不能用 `max(顶层槽)+1-n_funcs`
   否则顶层引用函数体符号时严重高估，atlisp_u 实测 3036 vs 实际 342）。
3. 函数体符号：每函数 `_collect_byteorder`（**字节码首次引用序**）收集，
   函数内重复槽去重（t09 两次调用 square 仅 1 重复槽）、跨函数去重。
4. **共享参数**注册在源码序最先使用它的函数之后（t15 实测）。
5. **locals 常量**只注册一次，位置在逆序最后遇到它的函数处；cond else `T` 键同。
6. **kwote 块**（`(function (lambda ...))`）：`kwote` + lambda 体保持收集序
   整体插到调用者之后，不随其它符号逆序沉底（base-function getf 实测）。
7. 每函数**逆序注册** `_rev`；`/ 局部变量` 的 `_al-bind-alist` 全文件共享 1 槽
   （注册在源码序第一个 local 函数处）。
8. 参数**逆序注册**（共享参数仅 shared_first_user 处注册）。

### 6.3 单函数规则（`_collect_single`）

- 函数体符号逆序注册（`reversed(deduped)`）。
- `/ 局部变量`：`_al-bind-alist` + `(quote (locals...))` 常量紧跟函数体符号
  之后、参数之前（t11 实测 `+ <= I RESULT _al-bind-alist (RESULT I) N`）。
- 参数逆序最后注册；递归名重复槽由 `add_force` 产生（t03 递归两次仅 1 重复
  FIB 槽）。

### 6.4 模块注册域（`_register_module`）

- 按源码逆序逐 form 交错注册（defun → 函数名；顶层 → `_collect_byteorder`
  符号逆序）。混合模式（i18n）顶层与 defun 按源码逆序交错。
- `InPackage` 插入原位（`:@` 先、`in-package` 后）。
- 符号归属：setq 目标优先 → 最早赋值的 form；否则最早读取的 form。
- 顶层 form 的用户函数名调用（force 符号）**不登记槽**——并入 defun 槽。
- `('NIL',)`/`('T',)` 常量不占槽。

### 6.5 常量结构（`to_const`）

AST 引用字面量 → CAD 常量结构元组（资源段加载期 BUILD_LIST 构建）：

| AST | 常量结构 | 备注 |
|---|---|---|
| Symbol | `('T',)` / `('NIL',)` / `('SYMBOL', normalize_vla_name(name))` | quoted vla- 同样规范化 |
| Integer/Real/String | `('INT',v)` / `('REAL',v)` / `('STRING',s)` | |
| QuotedExpr | `('LIST', (('SYMBOL','QUOTE'), inner))` | 嵌套 `'X` 展开为 `(QUOTE X)` |
| LambdaNode | `('LIST', ('SYMBOL','lambda'), params, body...)` | 空参 → `('NIL',)` |
| ListExpr | `('LIST', items)` | 空列表 → `('NIL',)`；**dotted → `('LIST', items, True)`**（`2a` 收尾） |
| Call/Progn/While/... | `('LIST', ('SYMBOL',<op>), ...)` | 引用数据里特殊形式还原为数据列表 |

### 6.6 vla-/vlax- 规范化（`normalize_vla_name`）

- `vla-get-`/`vla-put-`/`vla-call-`/`vla-add-`/`vla-insert-` 前缀：保留大小写、
  方法名首字母大写（ActiveX 方法名大小写敏感，t22 实测 `vla-get-Count`）。
- 其余 `vla-` 查 `_VLA_METHOD_MAP`（23 项 CamelCase 映射）否则首字母大写 fallback。
- `vlax-` 保持小写。codegen.py 与 cad_symbols.py 各一份实现保持一致。

### 6.7 顶层表达式符号与 top_level_count

`other_forms`（非 Defun/Defpackage）的符号/字符串并入模块注册段：

```python
if defun_forms:
    top_level_count = max(0, module_reg_count(program) - len(defun_forms))
else:
    top_level_count = max(_top_slots) + 1 if _top_slots else 0
```

`_top_slots` 由 `_collect_symbol_nodes(other_forms)` 的符号/字符串在
`symtab.name_to_idx` 的槽索引收集。

## 7. 阶段五：字节码生成（CodeGenerator）

`CodeGenerator(symtab, stub_format=True, defined_funcs=[函数名], nsyms=codegen_nsyms)`
其中：

```python
codegen_nsyms = len(symtab.entries) - len(defun_forms) - top_level_count + 1
wide_subr      = stub_format and nsyms > 256   # 大文件 5/6 字节 USUBR/FUNC
```

### 7.1 指令编码速查

| 指令 | 字节序列 | 来源 |
|---|---|---|
| PUSH_INT8 | `32 <val:u8>` | codegen L375-389 |
| PUSH_INT32 | `33 <i32:LE>` | |
| PUSH_VALUE / PUSH_G / SETQ_G | `03/09/06 <idx:u16>` | |
| GET_LOCAL | `05 <slot:u8>`（<256）/ `5C <slot:u16>`（GET_LOCAL_WIDE） | |
| SET_LOCAL | `5D <slot:u16>` | |
| JUMP | `57 <rel:i32 LE>` | |
| JMP32_IFNOT / COND_OR / COND_AND | `67/68/6A <rel:i32 LE>` | |
| USUBR 3 字节 | `35 <argc> <idx8>` | encode_usubr3 |
| USUBR 5 字节（大文件） | `35 <argc> <idx16> <flags=3>` | |
| FUNC 3 字节 | `51 <argc> <idx8>` | |
| FUNC 6 字节（大文件） | `51 <argc> <idx16> <flags=1> 00` | |
| INIT_ARGS | `18 <n:u16>` | |
| CLEAR_ARGS | `19 <n:u16>` | |
| END_DEFUN / DUP / POP | `16` / `0B` / `0A` | |
| FIX_LEQ / DEC / CAR / CDR / CONS | `4B` / `50` / `28` / `29` / `2A` | |
| BUILD_LIST | `39 <count:u16>` | |
| DEFUN 头 | `14 <b1> <b2> <b3> <b4>` | |
| 调用后清理 | `00 03`（NIL + PUSH_VALUE 0） | `_emit_subr_cleanup` |
| `command` 清理 | `00 01 00`（NIL + PUSH_NIL + NIL） | |

### 7.2 DEFUN 头编码（`_emit_defun_header`，stub 5 字节）

| 函数形态 | 字节序列 | 说明 |
|---|---|---|
| `&rest` 无限参数 | `14 <min> <min> <min> 01` | b4=01，b1/b2/b3=最小必填参数数 |
| `&optional` 有限可选 | `14 <max> <min> <max> 00` | b1=总参数，b2=必填，b3=max |
| 普通定参 | `14 <argc> <argc> <argc> 00` | **含 foreach/repeat 时 b1=argc+直接体并发循环深度**（单层 `14 02 01 01 00`；嵌套 2 层 `14 03 01 01 00`，嵌套 lambda/defun 内循环不计） |

含循环检测由 `_ast_contains_loop(node)` 递归完成。

### 7.3 参数绑定（`_emit_init_args`）

- **stub 单函数**：参数**逆序**绑定——`PUSH_G (nsyms-argc+(argc-1-i)); GET_LOCAL_16 i`；
  随后 `INIT_ARGS <len*2+1:u16>`（t13 实测 `PUSH_G [4],[3],[2]` = C,B,A）。
- **stub 多函数**：正序占位 `PUSH_G (nsyms-argc+i)`，由 `_patch_usubr_idx`
  依据 `sym_of(idx)∈cur_args` 统一改写为 gvar 槽。
- 非 stub：`PUSH_G idx + GET_LOCAL_8(05 <i>)`，`INIT_ARGS <len*2:u16>`。

### 7.4 `/ 局部变量` 绑定（`_emit_al_bind_alist`，t11 实测）

```
PUSH_G <locals 常量槽>; FUNC3 1 <_al-bind-alist>; NIL(00); PUSH_NIL(01); NIL(00); POP
```

把 `(quote (loc1 ...))` 常量压栈、调用 `_al-bind-alist` 绑定为 nil、POP 丢弃
返回值。`_al-bind-alist` 为保留大小写的 0x56 单符号。

### 7.5 语句 vs 值上下文（`_in_stmt_ctx`）

- `_emit_stmt()` 置 `_in_stmt_ctx=True`（值将被 POP 丢弃，仅裸语句位置）；
- `_value_ctx()`（contextmanager）清位（setq RHS、算术、实参等值位置）。
- `_emit_if` 据此决定 then 末尾是否 POP：语句上下文 then 尾 POP（位于 JUMP
  前，实测 `03 0a 57`）；值上下文不 POP（值须流到 SETQ_G/算术/实参）。

### 7.6 控制流 stub 协议

**if**（stub）：
```
cond → JMP32_IFNOT <else:4字节相对> → then
  → [语句上下文且 then 非 setq/if/progn 时 POP] → JUMP <end:4>
  → <else> → [无 else：尾/模块/值上下文补隐式 PUSH_NIL]
→ <end>
```

**while**（stub）：
```
[尾 while] PUSH_NIL 占位 + 体开头 POP
loop: cond（_tail=True，条件内 setq 需 DUP）→ JMP32_IFNOT <end>
      体（中间 setq/while/if 无 POP；非尾 while 其余语句 POP）
      JUMP <loop:4>
end:
```

**foreach**（stub，t16 逐字节实测）：
```
<list> 求值 → SET_LOCAL_16 <slot>          # 列表存局部槽
PUSH_G <var>; PUSH_NIL; INIT_ARGS 3        # 预载（内建遍历）
loop:  GET_LOCAL_16 <slot>; JMP32_IFNOT <end:4>
       GET_LOCAL_16 <slot>; CAR; SETQ_G <var>          # 体前取头
       GET_LOCAL_16 <slot>; CDR; SET_LOCAL_16 <slot>   # 推进
       body（无 POP）; JUMP <loop:4>
end:   CLEAR_ARGS 1                          # 清理预载（非 POP）
```

**repeat**（stub，t17 逐字节实测）：
```
count 求值 → SET_LOCAL_16 <slot>
loop:  GET_LOCAL_16 <slot>; PUSH_INT8 0; FIX_LEQ; JMP32_IFNOT <end:4>  # n<=0 退出
       GET_LOCAL_16 <slot>; DEC; SET_LOCAL_16 <slot>                    # 先递减
       body（无 POP）; JUMP <loop:4>
end:
```
无预载、循环结束栈平衡、无 CLEAR_ARGS。

**cond**（stub，`_emit_cond_stub`）：
- 各子句测试按源码序发出（`t` 子句直接 `PUSH_VALUE T` 槽），每个测试后
  `COND_OR <s4>` 跳对应 body_i；全假默认 `PUSH_NIL` + `JUMP`。
- **结果体按源码倒序发出**（末子句体最先），除首发出体外各接 `JUMP` 链式跳过。

**and/or 短路**（`_emit_short_circuit`）：必须用 COND_OR/COND_AND 4 字节偏移
（JMP16 系列在 CAD stub 运行时出错，i18n mark-locale 实测）。短路时栈保留
子表达式值作为结果，全真/有真时 `PUSH_T` 规范化。

### 7.7 kwote 机制（`(function (lambda ...))`，`_emit_kwote`）

- 非 stub 或非 Lambda → 退回 `_emit_quoted`。
- **`_module_mode`**：顶层 `(set/setq 'sym (function (lambda ...)))` 用内嵌
  `-lambda-` SUBR，模块代码发 setq 协议 `JUMP 0; PUSH_G <-lambda-槽+1>; DUP;
  SETQ_G <sym>`（非 `FUNC kwote`）。seg0 `-lambda-` 由 cli 用 `generate_function`
  生成完整 compact stub（见 §6.4），资源段按第一区/函数目录/第二区/fg 表/多
  DEFCODE 布局（setq-lambda.lsp byte-identity）。
- 普通：`_emit_nested_lambda` 发内嵌 DEFUN（`JUMP <label:4>; 14 argc argc argc
  00; 体; CLEAR_ARGS; 16; <label>`），随后 `PUSH_G <lam_idx>; FUNC3 1 <kwote>;
  NIL(00); PUSH_NIL(01); NIL(00)`。
- 每个内嵌 `-lambda-` **独立符号槽**：首个 `get_or_add("-lambda-")`，后续
  `add_force` 追加重复槽（t3 槽 18、t4 槽 17、t5 槽 16 实测）。

### 7.8 函数生成流程（`generate_function`）

1. 保存当前上下文；**每函数独立局部槽分配**（`local_slots={}`、`next_slot=0`）。
2. `_emit_defun_header`；登记参数槽 `local_slots[arg] = i`。
3. `_emit_init_args(all_args)`。
4. **stub + locals** → `_emit_al_bind_alist`（CAD 用符号槽协议而非局部槽）。
5. `label(_tail_entry_label)`；剥离 docstring（连续裸字符串，CAD 不注册）。
6. 中间语句 `_emit_stmt`；**stub 下 setq/while/foreach/repeat/if 后无 POP**，
   普通表达式补 POP。
7. 尾语句 `_emit_expr(_tail=True)`；无 body → stub 补 `PUSH_NIL`。
8. 收尾：stub 下有参或有 locals 的函数发 `CLEAR_ARGS <argc+locals:u16>`；
   无参函数直接结束。
9. `buf.resolve()` 回填所有跳转补丁，返回 `(bytes, start_offset)`。

`BytecodeBuffer`（L147-177）：累积缓冲 + 标签重定位（`labels`/`patches`/
`resolve()` 统一回填相对偏移）。

## 8. 阶段六：seg0 组装

```python
all_bytecode = BytecodeBuffer()
for i, form in enumerate(defun_forms):
    offset = len(all_bytecode.data)
    func_bytecode, _ = codegen.generate_function(form)
    func_offsets[normalize_vla_name(form.name)] = offset
    all_bytecode.emit(func_bytecode)
    if i < len(defun_forms) - 1:
        all_bytecode.emit(bytes([0x16]))   # 函数间分隔符 END_DEFUN
```

- **函数间分隔符 `16`**（END_DEFUN）：CLEAR_ARGS `19 <argc> 00` 已由
  generate_function 生成，仅需追加 `16`。
- **内嵌 `-lambda-` 绝对偏移**：`codegen._func_nested_lambdas` 记录的相对偏移
  转换到 seg0 绝对偏移，独立登记 `-lambda-`/`-lambda-#N` 目录项，供
  func-ranges 与 DEFCODE 注册。
- 顶层表达式编译到 `top_level_bc`（`_module_mode=True`），作为模块代码输入。

## 9. 阶段七：模块代码（seg1 尾部）

CAD 把源码中的**顶层表达式**编译进 seg1 模块代码，seg0 只含 defun 函数。
`_build_cad_module_code` 规则：

- 模块代码符号引用使用 **gvar 槽 = 符号槽 + 1**。
- 顶部 `PUSH_G <模块注册符号数+1>; POP` 占位。
- 顶层 setq → `PUSH_G <值槽+1>; DUP; SETQ_G <变量槽+1>`（中间 pair 无 DUP，
  最后一对 DUP；`'()`/`nil` → PUSH_NIL；整数字面量内联 PUSH_INT8/INT32）。
- 每个顶层语句后 POP（最后一句除外）。
- `(in-package :@)` → `PUSH_VALUE <pkg槽>; FUNC_REF in-package`。
- 有 defun 时追加函数注册尾：`JUMP + PUSH_G <b>; SETQ_G <c>`（b =
  `2*n_funcs+1 + top_level_count - i`，c = 函数符号槽 + 1），组间
  `PUSH_G <c>; POP; JUMP`。
- **post-form 分组**：最后一个 defun 之后的顶层语句排到函数注册尾之后
  （`n_post_forms`）；首个 defun 之前的顶层语句（globals）排在最前。
- 顶层 `(set/setq 'sym (lambda ...))`（纯顶层，`top_lambda_slots`）：
  setq 协议 `JUMP 0; PUSH_G <-lambda-槽+1>; DUP; SETQ_G <sym>`（`-lambda-` gvar
  槽 = `_lam_slot + 1` = `top_level_count + 2 - i + 1`，setq-lambda.lsp 实测）。

纯命令文件（无顶层表达式）走 `build_command_module_code`：
- 每命令 `PUSH_G <a> POP JUMP0`（占位）+ `PUSH_G <b> SETQ_G <c>` +
  `PUSH_G <c>; FUNC_REF <vl_idx=2>; PUSH_NIL; POP`（vl-ACAD-defun 注册）。
- 槽位公式：`var_pos = n_funcs + 3`；`a = var_pos-1-i`、`b = var_pos+n_funcs-1-i`、
  `c = n_funcs+1-i`（i<n-1）、末 `c=1`。

纯函数文件（无顶层、无命令）走 `build_module_code`：
- n_funcs=0：`DEFUN头 + 顶层表达式 + END_DEFUN`。
- n_funcs=1：固定字节 `09 02 00 0a 57 00 00 00 00 09 03 00 06 01 00 09 01 00 16`。
- n_funcs>1：每函数 `PUSH_G <a>; POP; JUMP; PUSH_G <b>; SETQ_G <c>`（a=n_funcs+1-i、
  b=2n+1-i、c=n-i），末 `PUSH_G 1; END`。

## 10. 阶段八：资源段构建（ResourceBuilder，两轮）

关键：**两轮构建**，因为代码引用长度依赖 seg0 最终长度。

### 10.1 seg1 结构

```
模块头(14 01 01 01 00) + 代码引用 + 模块注册符号/字符串 + PUSH_NIL + GVARINIT
+ 函数代码引用 + 其余符号/字符串/常量 + GET_LOCAL + GVARINIT
+ 每个函数一个 DEFCODE（GET_LOCAL + PUSH_INT8 <offset> + SYMBOL + DEFCODE）
+ GVARINIT + INIT_DONE + 模块代码
```

- **符号名统一大写**（`_enc_sym`）：AutoLISP 大小写不敏感；字符串字面量不变。
  例外：`command` 内建注册为 `ads-cmd`；`vla-`/`vlax-` 前缀保留大小写；
  `_al-bind-alist`/`kwote` 保留大小写、独立 0x56 单符号块。
- 连续 SYMBOL 合并为单个 `5b` 块，遇 STRING 分块；连续 STRING 合并为单个
  `55` 块。
- 常量结构经 `_emit_const` 序列化；**dotted 引用 `'(1 . 2)` 用单字节 `2a`
  （LIST_END）收尾**（t12 实测），普通列表用 `39 <count>`。
- 每个函数一个 DEFCODE，stub 格式按**源码逆序**注册；只有最后一个 DEFCODE
  追加 `01`。
- 模块注册 GVARINIT `st_init = module_entries_count + 2 (+commands)`；
  函数注册 GVARINIT `st_init = len(entries) - skip_first + 1`（= nsyms）；
  DEFCODE 后 GVARINIT `var_pos = len(func_names) + top_level_count + 2 (+commands)`。
- kwote 内嵌 `-lambda-`：在 GVARINIT(0, nsyms) 前置 DEFCODE，按 seg0 偏移
  **逆序**发射（每个独立 DEFCODE）。

### 10.2 多函数代码引用（`_func_ranges_bytes`）

每个函数的 (start, end) 范围，从末尾逆序：
`32 <start> 32 <end> 2a ... 39 <count> 00`。kwote 内嵌 `-lambda-` 的 end 用其
自身结束偏移（nested_ends），宿主函数 end 用下一个非内嵌函数的起始。

### 10.3 sec2_items

`count_resource_records(seg1)`（按操作码结构正确跳转，非简单字节扫描）统计
GVARINIT(0x43) 与 INIT_DONE(0x1c) 记录数，并按 CAD 语义兜底：

- 含 defun：`2 * (defun 数 + 顶层 form 数) + 2`（实测 1 函数→4、2→6、3→8）。
- 纯顶层：`len(symtab.entries) + 2`。
- 若偏小会遗漏函数注册（CAD 按 items 处理 GVARINIT 记录）。

## 11. 阶段九：索引修正（`_patch_usubr_idx`）

CAD 用 **`gvar 槽 - 1`** 编址（gvar 表由资源段 GVARINIT 建立）。codegen 用
占位生成，此处用第一轮 seg1 重建 gvar 表修正：

- **USUBR/FUNC**：`sym ∈ gvar_map` → 操作数 = `gvar_map[sym] - 1 - offset`；
  符号槽末尾（超出 gvar 表，fg 仅 nsyms 项）→ 操作数 = `nsyms - 1 - offset`
  （t22 实测 vlax-get-acad-object）。
- **参数绑定 PUSH_G**（DEFUN 后 argc 个，多函数）：`gvar_slot(arg) - 1 - offset`。
- **参数读取 PUSH_VALUE**（多函数，size=3）：凭 `sym_of(idx) ∈ cur_args` 识别，
  改写为 gvar 槽 - 1。
- **CONST 常量引用**：quoted 单符号按 gvar 槽；复合结构用 `const_map`（结构
  匹配 fg 表）→ gvar 槽 - 1。
- **STRING**：已在 GVARINIT 表（fg 含 STRING）按 gvar 槽映射；否则注册于符号
  槽末尾（gvar 槽 = nsyms，操作数 = nsyms-1）。
- **函数体普通符号**（不在 fg）：同样 `gvar 槽 - 1`（hkrepro 实测，有顶层
  form 时 symtab 槽与资源段 gvar 槽错位，CAD 报 `:DIALOG`）。
- **REAL 常量**：按值匹配资源段 REAL 槽（codegen symtab 槽可能偏离 GVARINIT）。
- **kwote `-lambda-`**：不参与资源段符号注册，按其在所有 `-lambda-` 条目中的
  序号编址（lambda i 槽 = `nsyms - i`，操作数 = `nsyms - 1 - i`）。
- **offset 修正**：`offset = nsyms - codegen_nsyms`（kwote 使 fas_nsyms 比
  codegen_nsyms 大 1 时，gvar 槽 - 2）。
- **占位 PUSH_VALUE[0]**（单字节 `03`，size=1）必须跳过，否则被扩展成 3 字节
  破坏字节一致性。
- **大文件**（nsyms>256）：`wide=True`，用 5 字节 USUBR / 6 字节 FUNC 重编码。

`func_args` 顺序须与 seg0 DEFUN 顺序一致：顶层 defun 参数 + 各函数内嵌 kwote
`-lambda-` 参数。

## 12. 阶段十：写出（FasWriter）

```python
writer = FasWriter(symtab)
writer.write(output, seg0, seg1, sec2_items=sec2_items, nsyms=fas_nsyms, compact=True)
```

- **`compact=True`** → 紧凑 stub 格式：`total_size = len(seg0) + 1`（CAD 实测
  恒等：cross/m2/m3/multi/sh/lambda_test 六份产物）。注意不能写成
  `len(seg0_payload) - 2`：seg0 头部 `{nsyms} $` 长度随 nsyms 位数变化。
- 自包含格式 `total_size = len(seg0_payload)`（不带 compact）。
- 文件头 `FAS4_MAGIC` + `<total_size>\r\n`；seg0 = `<nsyms> $` + 字节码；
  段分隔符 `16 24 0d 0a`（seg0 空时 ` $\r\n`）；seg1 头 `<len> <items> $`。
- seg1 使用**滚动 XOR 加密**（`_rolling_xor`，双字节滚动：`data[i] ^ key_new ^
  key_old`），尾部含密钥长度字节 + 密钥 + `;fas4 crunch` 标记 + `$;` + 日期标记
  （`A7/31/26` 格式）。`build_trailer` 默认 key_len=23 与 AutoCAD 一致，随机
  前缀 + `;fas4 crunch`。

## 13. 关键 CAD 兼容约定速查

| 约定 | 说明 |
|---|---|
| seg0 | 函数字节码（`<nsyms> $...`），纯字节码 |
| seg1 | 资源段：模块头(`14 01 01 01 00`) + 代码引用 + 符号/字符串注册 + GVARINIT + DEFCODE + INIT_DONE + 模块代码 |
| seg1 头 items | GVARINIT + INIT_DONE 计数 |
| 符号名 | 统一大写（`ResourceBuilder._enc_sym`）；字符串字面量不变；vla-/vlax-、`_al-bind-alist`、`kwote` 保留大小写 |
| 符号槽顺序 | 源码函数逆序，每函数内字节码引用序逆序，参数紧跟其后；混合时顶层符号在函数体内建之前；递归重复槽 |
| 顶层表达式 | 编译进 seg1 模块代码（非 seg0）：`DEFUN头 + [顶层表达式] + [函数注册尾] + END_DEFUN`；gvar 槽 = 符号槽 + 1 |
| 紧凑 stub 规则 | 中间 setq 无 POP、尾 setq 先 DUP、无 else 的 if 补 PUSH_NIL、有参函数末尾 `19 <argc> 00`（CLEAR_ARGS） |
| 函数间分隔符 | `16`（END_DEFUN） |
| foreach/repeat | DEFUN 头 `b1=argc+1`（`14 <argc+1> <argc> <argc> 00`） |
| 值位置 T/t | 均注册符号槽并用 PUSH_VALUE 引用（nil 仍内联） |
| 大文件 | nsyms>256 用 5 字节 USUBR / 6 字节 FUNC；小文件 3 字节 |
| `command` | 资源段注册名 `ads-cmd`；调用 `FUNC3 + NIL + PUSH_NIL + NIL` |
| `-lambda-` | 保留小写；`-LAMBDA-` 是错的；多 lambda 用 `-lambda-#N` 目录键 |

## 14. 反编译对应路径（供理解格式）

```
.fas 二进制 → Fas4Parser.parse() → Fas4File
            → Disassembler.disassemble()  → List[Instruction]
            → ControlFlowAnalyzer.find_functions() → List[FunctionDef]
            → LispGenerator.generate() → AutoLISP 源码
```

解码器问题一律在 `decompiler/fas4_decompiler.py` 修复，**从不修改生成的 `.lsp`**。

## 15. 调试建议

```sh
# 编译 + 反编译 + 验证
python -m compiler.cli compile -O2 tests/fun.lsp test.fas
python -m decompiler.fas4_decompiler test.fas test.lsp
python -m tools.validate test.lsp

# 逐字节比对 CAD golden
python -m pytest tests/test_compiler_output.py -k "byte_identity"

# 分析 FAS 结构
python -m tools.fas-analyzer test.fas --dump

# 编译分析（指令数/符号槽/尾递归）
python -m compiler.cli compile --analyze test.lsp test.fas
python -m compiler.cli compile --report report.json test.lsp test.fas
```

- 编译产物与 CAD 不一致时：先比 `seg0` → 再比 `sec2`/`nsyms`（`tools.fas-analyzer`）。
- 符号槽偏移问题：检查 `derive_symbol_names` 顺序与 `top_level_count` 计算。
- USUBR/参数槽错位：检查 `_patch_usubr_idx` 的 gvar 槽 - 1 编址与
  `all_func_args` 顺序。
- 大文件字节数不对：检查 `wide_subr`（nsyms>256 分支）与 `_offset_slots`
  的 `short_subr=False`。
- 顶层表达式缺失/错位：检查 `_build_cad_module_code` 的 globals/mid/post
  分组与 `n_post_forms`/`n_globals` 计算。

## 16. 测试覆盖

- `tests/test_compiler_output.py`：50 用例，含 4 对 CAD golden 逐字节比对 +
  16 个 `tests/compile_src/` 结构断言 + i18n 拆分件 byte-identity 回归。
- `tests/test_compile_decompile.py`：74 用例编译-反编译往返（16 个 `tests/compile_src/` fixture 系列）。
- `tests/test_optimizer.py`：32 用例优化 pass。
- `tests/test_cli.py`：28 用例 CLI 路径。
- `tests/test_assembler.py` / `test_disasm.py`：反汇编/汇编往返。
- `scripts/run_tests.sh`：一键全部检查（py_compile + pytest + disasm→asm
  往返 + byte-identity 状态）。
