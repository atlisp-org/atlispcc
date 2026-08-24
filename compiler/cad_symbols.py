"""CAD stub 符号槽顺序推导（AutoCAD 24.1s 实测逆向）。

CAD 紧凑 stub 格式按符号槽编址。符号槽注册顺序按文件结构分两套：

**多函数文件**（≥2 个 defun，样本 m2/m3/cross/sh/multi/f4*/f5 实测）：
1. 所有函数名逆序（最后一个函数名在前，槽 0）——模块注册域
2. 函数体符号按**字节码首次引用序**（后序：先内层调用后外层函数名，即
   USUBR 出现序）逐函数收集，源函数序拼接、先到先得去重后**整体逆序**；
   逆序后每函数引用组连续（源逆序），其唯一参数按逆序紧跟组末
3. **共享参数**（被多个函数使用）推迟到最后统一注册；递归/跨函数调用函数名
   由调用者引用组登记（模块注册域已占位，函数名重复槽；递归名不重复）

**单函数文件**（≤1 个 defun，fact/sf_cond/fun 实测）：
按"字节码引用序逆序"收集：函数体符号按字节码首次引用序的反向注册
（调用内参数先于函数名出现在字节码中：PUSH_G arg… → USUBR func，逆序后
函数名在前），参数（含共享）放最后；递归函数名产生重复槽但不提前。

逆向来源：samples/cad-compare/（m2/m3/cross/sh/multi 的 CAD 官方产物）与
tests/（fact/fun/sf_cond/mix 的 CAD 官方产物）。
"""
from compiler.ast_nodes import (
    Symbol, String, Integer, Real, ListExpr, QuotedExpr,
    Defun, Setq, IfNode, WhileNode, ForeachNode, RepeatNode, Call, Progn,
    LambdaNode, Cond, Defpackage, InPackage,
)

CONST_MARK = '__const__'


# 无 get-/put-/call-/add-/insert- 子前缀的 vla- 方法名 → 标准 ActiveX
# CamelCase（base-function CAD 实测 `vla-sendcommand`→`vla-SendCommand`、
# `vla-postcommand`→`vla-PostCommand`）。未收录的走首字母大写 fallback。
_VLA_METHOD_MAP = {
    "vla-sendcommand": "vla-SendCommand",
    "vla-postcommand": "vla-PostCommand",
    "vla-addarc": "vla-AddArc",
    "vla-addcircle": "vla-AddCircle",
    "vla-adddimension": "vla-AddDimension",
    "vla-addellipse": "vla-AddEllipse",
    "vla-addhatch": "vla-AddHatch",
    "vla-addline": "vla-AddLine",
    "vla-addmtext": "vla-AddMText",
    "vla-addpolyline": "vla-AddPolyline",
    "vla-addrectangle": "vla-AddRectangle",
    "vla-addspline": "vla-AddSpline",
    "vla-addtext": "vla-AddText",
    "vla-delete": "vla-Delete",
    "vla-endundomark": "vla-EndUndoMark",
    "vla-insertinmenubar": "vla-InsertInMenuBar",
    "vla-item": "vla-Item",
    "vla-regen": "vla-Regen",
    "vla-removefrommenubar": "vla-RemoveFromMenuBar",
    "vla-startundomark": "vla-StartUndoMark",
    "vla-update": "vla-Update",
}

# `vla-get-*`/`vla-put-*` 多词方法名 → CAD 规范 CamelCase（AutoCAD ActiveX
# 属性名；@lisp_u CAD golden 实测：modelspace→ModelSpace、insertionpoint→
# InsertionPoint、objectname→ObjectName、textstyles→TextStyles，而
# linetypes→Linetypes、viewports→Viewports 保持 CAD 原生写法）。键为小写
# 方法名（不含前缀），值含前缀的规范形式。
_VLA_GET_PROP_MAP = {
    "modelspace": "vla-get-ModelSpace",
    "paperspace": "vla-get-PaperSpace",
    "insertionpoint": "vla-get-InsertionPoint",
    "objectname": "vla-get-ObjectName",
    "startpoint": "vla-get-StartPoint",
    "endpoint": "vla-get-EndPoint",
    "textstring": "vla-get-TextString",
    "textstyles": "vla-get-TextStyles",
    "dimstyles": "vla-get-DimStyles",
    "menubar": "vla-get-MenuBar",
    "menugroups": "vla-get-MenuGroups",
    "activedocument": "vla-get-ActiveDocument",
    "linetypes": "vla-get-Linetypes",
    "viewports": "vla-get-Viewports",
}
# `vla-put-*` 变体：同一属性名（去掉前缀后）映射到 vla-put- 前缀。
_VLA_PUT_PROP_MAP = {
    k: "vla-put-" + v[len("vla-get-"):]
    for k, v in _VLA_GET_PROP_MAP.items()
}


def normalize_vla_name(name):
    """规范化 vla- 前缀的 ActiveX 方法符号名（AutoCAD 24.1s 实测）。

    CAD 对 ``vla-get-<Method>`` / ``vla-put-<Method>`` 等 ActiveX 方法符号
    保留**原始大小写**（方法名大小写敏感，ActiveX 接口方法区分大小写），
    且方法名部分首字母大写（t22_activex 实测：源码 ``vla-get-count`` →
    符号槽 ``vla-get-Count``、``vla-get-Documents`` 保持、``vla-get-ModelSpace``
    保持、``vla-get-ActiveDocument`` 保持）。无子前缀的 ``vla-<Method>``
    按标准 ActiveX CamelCase（base-function CAD 实测 ``vla-sendcommand`` →
    ``vla-SendCommand``）。``vlax-`` 前缀的 VLISP 扩展函数保持小写
    （``vlax-get-acad-object`` 原样）。非 vla-/vlax- 符号不变。

    三个 CAD 实测全大写（不在 CAD 真实方法表，白名单 const 数据里
    ``vla-addrectangle``/``vla-adddimension``/``vla-get-distance`` → 全大写
    VLA-ADDRECTANGLE/VLA-ADDDIMENSION/VLA-GET-DISTANCE；safe-eval 白名单实测，
    而 vla-addline 保留 vla-AddLine）。
    """
    if name.lower() in ("vla-addrectangle", "vla-adddimension", "vla-get-distance"):
        return name.upper()
    for prefix in ("vla-get-", "vla-put-", "vla-call-", "vla-add-", "vla-insert-"):
        if name.lower().startswith(prefix):
            method = name[len(prefix):]
            # 多词属性名用 CAD 规范 CamelCase 表（modelspace→ModelSpace 等）；
            # 不在表中时首字母大写（count→Count）。
            if prefix in ("vla-get-", "vla-put-"):
                low = method.lower()
                prop_map = _VLA_GET_PROP_MAP if prefix == "vla-get-" else _VLA_PUT_PROP_MAP
                if low in prop_map:
                    return prop_map[low]
            if method and method[0].islower():
                return prefix + method[0].upper() + method[1:]
            return name
    if name.lower().startswith("vla-"):
        mapped = _VLA_METHOD_MAP.get(name.lower())
        if mapped:
            return mapped
        rest = name[len("vla-"):]
        if rest and rest[0].islower():
            # 不在方法表的无子前缀 vla- 名（voice.lsp `vla-object` 类型名，
            # CAD fg[88] 实测 VLA-OBJECT 大写）：返回大写形式——resource_builder
            # `_enc_sym` 对 vla- 前缀不 `.upper()`，此处直接给全大写。此前首字母
            # 大写 fallback（vla-Object）对类型名错（CAD 用全大写）。
            return name.upper()
        return name
    return name


def strip_docstring(body):
    """CAD 忽略 defun 后开头的连续裸字符串（docstring）。

    `(defun f () "文档说明" ...)` 编译时丢弃该字符串（AutoLISP 惯例，
    docstr.fas CAD 实测 strings 为空）。连续多个 docstring 全部剥离
    （base-function CAD 实测 handle-keywords 双 docstring 均不注册）。
    仅当它是函数体**开头**的独立字符串字面量时跳过，不影响
    `(strcat "a" "b")` 等表达式内字符串。
    """
    body = list(body)
    while len(body) > 1 and isinstance(body[0], String):
        body = body[1:]
    return body


def to_const(node):
    """把引用的字面量节点规范化为常量结构元组；不可常量化的返回 None。

    CAD 把 ``'(lambda ...)`` 等引用字面量注册为资源段常量（值在加载期由
    资源流 BUILD_LIST 构建），字节码只发一条 ``PUSH_G``。结构与资源流
    记录一一对应：('SYMBOL', name) / ('INT', v) / ('REAL', v) /
    ('STRING', s) / ('LIST', (item, ...)) / ('NIL',) / ('T',)。
    """
    if isinstance(node, Symbol):
        if node.name == 'T':
            return ('T',)
        if node.name == 'nil':
            return ('NIL',)
        # quoted vla- 符号同样规范化（base-function `(set 'vla-postcommand
        # vla-sendcommand)` CAD 实测 `'vla-postcommand` → 常量符号
        # `vla-PostCommand`，与函数引用/定义名一致）。
        return ('SYMBOL', normalize_vla_name(node.name))
    if isinstance(node, Integer):
        return ('INT', node.value)
    if isinstance(node, Real):
        return ('REAL', node.value)
    if isinstance(node, String):
        return ('STRING', node.value)
    if isinstance(node, QuotedExpr):
        # 嵌套在更大引用结构内的 `'X`（如 save-mt error-handler 的
        # `'(if (eq 'file (type fp)) ...)` 里的 `'file`）：CAD 展开为
        # `(QUOTE FILE)` 列表（i18n-cad fg[15] 实测），而非原样失败回落
        # 到运行时构建。kwote=True（`(function ...)`）走函数机制不 const。
        if node.kwote:
            return None
        inner = to_const(node.expr)
        if inner is None:
            return None
        return ('LIST', (('SYMBOL', 'QUOTE'), inner))
    if isinstance(node, IfNode):
        # 引用数据里的 `(if ...)`：`if` 是数据符号（CAD 收集 IF 作常量结构，
        # save-mt error-handler `'(if (eq 'file (type fp)) (close fp))` 实测
        # fg[15] = `((IF)((EQ)((QUOTE FILE)((TYPE FP)))((CLOSE FP)))`）。
        items = [('SYMBOL', 'if')]
        for sub in (node.cond, node.then, node.else_expr):
            if sub is None:
                break
            c = to_const(sub)
            if c is None:
                return None
            items.append(c)
        return ('LIST', tuple(items))
    if isinstance(node, LambdaNode):
        if node.args:
            params = ('LIST', tuple(('SYMBOL', a) for a in node.args))
        else:
            # 空参数表 `(lambda () ...)`：CAD 以 NIL 表示（与 to_const(ListExpr)
            # 对空列表的处理一致），否则与 _lambda_list 生成的 ListExpr 常量键
            # 不一致，get_const_idx 找不到 → 退化为运行时逐符号 BUILD_LIST，
            # 引用的符号被按值压栈（topsetq `(set '@::acadver (lambda () ...))`
            # 实测 @::acadver 被绑成 @::*acadver* 的值 24.1）。
            params = ('NIL',)
        body = tuple(to_const(b) for b in node.body)
        if any(b is None for b in body):
            return None
        return ('LIST', (('SYMBOL', 'lambda'), params) + body)
    if isinstance(node, ListExpr):
        # CAD 把 dotted 引用 `'(1 . 2)` 编译为普通列表常量 `(1 2)`
        # （resource 流 `INT8 1; INT8 2; BUILD_LIST 2`，t12_quote 实测）。
        items = tuple(to_const(i) for i in node.items)
        if any(i is None for i in items):
            return None
        if node.dotted is not None:
            d = to_const(node.dotted)
            if d is None:
                return None
            items = items + (d,)
            # dotted 引用 `'(a . b)`：CAD 以 `2a`(LIST_END) 收尾而非
            # `39 <count>`（t12_quote 实测），需标记以便 _emit_const 正确编码。
            return ('LIST', items, True)
        if not items:
            # 空列表 `'()` = nil：CAD 用 PUSH_NIL(01) 而非 BUILD_LIST 0
            # （i18n_v2 顶层 `'()` 实测），避免多占一个 gvar 槽。
            return ('NIL',)
        return ('LIST', items)
    if isinstance(node, Call):
        items = (to_const(Symbol(node.name)),) + tuple(to_const(a) for a in node.args)
        if any(i is None for i in items):
            return None
        return ('LIST', items)
    if isinstance(node, Progn):
        body = tuple(to_const(f) for f in node.forms)
        if any(b is None for b in body):
            return None
        return ('LIST', (('SYMBOL', 'progn'),) + body)
    if isinstance(node, Cond):
        clauses = []
        for c in node.clauses:
            items = tuple(to_const(x) for x in c)
            if any(i is None for i in items):
                return None
            clauses.append(('LIST', items))
        return ('LIST', (('SYMBOL', 'cond'),) + tuple(clauses))
    if isinstance(node, Setq):
        # 引用数据里的 `(setq ...)`：`(SETQ T1 V1 T2 V2 ...)` 列表
        items = [('SYMBOL', 'setq')]
        for t, v in node.pairs:
            tc = to_const(t)
            vc = to_const(v) if v is not None else ('NIL',)
            if tc is None or vc is None:
                return None
            items.append(tc)
            items.append(vc)
        return ('LIST', tuple(items))
    if isinstance(node, WhileNode):
        body = tuple(to_const(f) for f in node.body)
        if any(b is None for b in body):
            return None
        c = to_const(node.cond)
        if c is None:
            return None
        return ('LIST', (('SYMBOL', 'while'), c) + body)
    if isinstance(node, ForeachNode):
        body = tuple(to_const(f) for f in node.body)
        if any(b is None for b in body):
            return None
        v = to_const(node.var)
        lst = to_const(node.list_expr)
        if v is None or lst is None:
            return None
        return ('LIST', (('SYMBOL', node.name or 'foreach'), v, lst) + body)
    if isinstance(node, RepeatNode):
        body = tuple(to_const(f) for f in node.body)
        if any(b is None for b in body):
            return None
        c = to_const(node.count or Integer(0))
        if c is None:
            return None
        return ('LIST', (('SYMBOL', 'repeat'), c) + body)
    if isinstance(node, Defun):
        # 引用数据里的 `(defun name (args) body...)`（如 install 里序列化的
        # `'(progn (defun ...) ...)`）：整体作为列表常量
        arg_items = [('SYMBOL', a) for a in node.args]
        if node.optional:
            arg_items += [('SYMBOL', '&optional')] + [('SYMBOL', a) for a in node.optional]
        if node.rest:
            arg_items += [('SYMBOL', '&rest'), ('SYMBOL', node.rest)]
        if node.locals:
            arg_items += [('SYMBOL', '/')] + [('SYMBOL', l) for l in node.locals]
        body = tuple(to_const(b) for b in node.body)
        if any(b is None for b in body):
            return None
        return ('LIST', (('SYMBOL', 'defun'), ('SYMBOL', node.name),
                         ('LIST', tuple(arg_items))) + body)
    return None


def is_const_entry(item):
    return isinstance(item, tuple) and len(item) == 2 and item[0] == CONST_MARK


class _SeenList(list):
    """维护 `_seen` 去重的 O(1) 集合，供收集器 `out` 列表单调 append 使用。

    与原始 O(n) 语义完全一致：`names` set 记录已出现的名字（含 "str"/real
    键），`structs` set 记录已出现的常量结构。索引/逆序/迭代行为继承 list，
    仅覆盖 append 以同步集合。
    """

    __slots__ = ("names", "structs")

    def __init__(self):
        super().__init__()
        self.names = set()
        self.structs = set()

    def append(self, item):
        name, _forced = item
        super().append(item)
        if is_const_entry(name):
            self.structs.add(name[1])
        else:
            self.names.add(name)


class CadSymbolCollector:
    def __init__(self):
        self.names = []
        self._name_set = set()
        self._const_set = set()
        self.shared = set()
        self.func_names = set()
        # 模块注册域符号数（_register_module 结束后立即记录）。该域 = 函数名 +
        # 顶层表达式符号（entries 前 module_reg_count 项），`top_level_count`
        # 应由它推导而非 `max(顶层符号槽)+1-n_funcs`——后者在顶层表达式引用
        # 函数体符号（高槽位）时会严重高估（atlisp_u 实测 3036 vs 实际 342）。
        self.module_reg_count = 0
        # 模块注册函数名数（模块尾块 defun 数；CAD 只把模块代码引用的尾块
        # 函数名注册进模块注册段，其余库函数名经函数体符号区注册）。
        self.module_reg_func_count = 0
        # 唯一参数被逆序更晚处理的函数 quoted 引用（file-utils `'STR`）时由
        # 引用函数组收集注册；owner args 循环须跳过（否则抢先占低位槽）。
        self._quoted_param_collected = set()

    def add(self, name, force=False):
        if is_const_entry(name):
            structure = name[1]
            if force or structure not in self._const_set:
                self.names.append(name)
                self._const_set.add(structure)
            return
        name = normalize_vla_name(name)
        if name.lower() in ('t', 'nil'):
            # T/nil 为内建常量（PUSH_T/PUSH_NIL 内联），默认不占符号槽。
            # 但 CAD 对 `(if c T nil)` / `(cond (c ... T))` 等**值位置**的 T
            # 会注册真实符号槽并用 PUSH_VALUE 引用（t18 小写 t、t22 大写 T
            # golden 实测，大小写不敏感）；纯 `(and ...)` 短路与 cond else 键
            # 仍内联/强制。仅 nil 恒不占槽（PUSH_NIL 内联）。
            # t/T 大小写不敏感统一为 `T` 槽（CAD weak_keywords）：else 键
            # `(t ...)` 与值位置 `T` 共享同一 SYMBOL T。T 槽全局唯一——即使
            # force 也不重复注册（递归函数名才需重复槽，T 无此语义）。
            if name.lower() == 't':
                name = 'T'
            if not force and name.lower() == 'nil':
                return
            if not self._in_name_set(name):
                self.names.append(name)
                self._name_set.add(name)
            return
        if force or not self._in_name_set(name):
            self.names.append(name)
            self._name_set.add(name)

    def _in_name_set(self, name) -> bool:
        """_name_set 大小写不敏感检查（非 vla-/vlax- 符号）。CAD 符号槽全大写、
        大小写不敏感：quoted 'Count 与 local count / 跨函数 'Status 合并一个槽。
        vla-/vlax- 保留大小写（ActiveX 方法大小写敏感，voice.lsp 'GetVoices 等）。
        **字符串**（`"..."` 键）大小写敏感（help-system `"cmdecho"`/`"CMDECHO"`
        是两个独立槽——`_seen` 同样大小写敏感，此处不一致会反向合并）。"""
        if (
            isinstance(name, str)
            and not name.startswith('"')
            and not name.lower().startswith(("vla-", "vlax-"))
        ):
            nk = name.upper()
            return any(
                isinstance(s, str)
                and not s.startswith('"')
                and not s.lower().startswith(("vla-", "vlax-"))
                and s.upper() == nk
                for s in self._name_set
            )
        return name in self._name_set

    @staticmethod
    def _seen(out, name=None):
        if name is None:
            return out
        if isinstance(out, _SeenList):
            if is_const_entry(name):
                structure = name[1]
                return structure in out.structs
            # 符号大小写不敏感（CAD 符号槽全大写）：quoted 'Status 与 local
            # status 收集层合并一个（位置 = 首次出现），否则逆序注册时 status
            # 排在 vlax-get-property 前、CAD 在后者（voice.lsp 实测）。vla-/
            # vlax- 保留大小写（ActiveX 方法大小写敏感），**字符串**（`"..."` 键）
            # 也大小写敏感（help-system `"cmdecho"`/`"CMDECHO"` 是两个槽）。
            if (
                isinstance(name, str)
                and not name.startswith('"')
                and not name.lower().startswith(("vla-", "vlax-"))
            ):
                nk = name.upper()
                return any(isinstance(n, str) and n.upper() == nk for n in out.names)
            return name in out.names
        if is_const_entry(name):
            structure = name[1]
            return any(is_const_entry(n) and n[1] == structure for n, _ in out)
        return any(n == name for n, _ in out)

    def collect_program(self, program):
        defuns = [f for f in program.forms if isinstance(f, Defun)]
        others = [f for f in program.forms if not isinstance(f, Defun)]
        self.func_names = {f.name for f in defuns}
        # 参数使用统计：argname -> 使用它的函数数（共享参数判定）
        arg_usage: dict = {}
        for f in defuns:
            for a in f.args:
                arg_usage[a] = arg_usage.get(a, 0) + 1
        self.shared = {a for a, c in arg_usage.items() if c > 1}
        # 全部函数参数名（含唯一参数）：函数体收集时排除——参数由各函数 args
        # 循环注册（唯一参数在所属函数、共享参数在 _shared_last 处）。否则某函数
        # 的参数名被**其它函数**作内建/全局引用（config/store `type` =
        # define-config-typed 参数 + config-validate `(type value)` 调用）时，
        # 会在引用函数的函数体组抢先注册，错位到参数拥有者组（CAD 实测 TYPE
        # 在 define-config-typed 组 fg[78]，非 config-validate 组 fg[59]）。
        self._all_params = set(arg_usage.keys())
        # 每个参数名 → 最早声明它的函数源码序（= 逆序处理**最后**的拥有者）。
        # 符号同时是 kwote lambda 参数 + 其它函数参数时（base-function `x` =
        # pair 参数 + getf lambda 参数；string-utils `x` = strbytelen 参数 +
        # string-split lambda 参数），CAD 注册在**逆序最后处理**的拥有者处——
        # 参数拥有者处理更晚（owner 源码序 < 引用函数源码序，base-function
        # pair src12 < getf src13）时参数拥有者注册；lambda 宿主处理更晚
        # （string-split src1 < strbytelen src9）时 lambda 收集注册。
        self._param_first_source = {}
        for _j, _f in enumerate(defuns):
            for _a in _f.args:
                self._param_first_source.setdefault(_a, _j)
        # 每个参数名 → 含 kwote lambda 且参数为其 lambda 参数的宿主函数
        # （逆序 idx 最大 = 处理最晚）。参数同时是 kwote lambda 参数时，
        # CAD 注册在逆序最后处理的拥有者处（string-utils `x` = strbytelen
        # 参数 + string-split lambda 参数，string-split 处理更晚 → x 在
        # string-split kwote 块内 fg[44]，strbytelen args 循环跳过）。
        self._param_lam_hosts = {}
        for _j, _f in enumerate(defuns):
            _ri = len(defuns) - 1 - _j
            for _b in _f.body:
                for _lam in self._iter_kwote_lambdas(_b):
                    for _p in _lam.args:
                        if _p == "/":
                            break
                        self._param_lam_hosts[_p] = max(
                            self._param_lam_hosts.get(_p, -1), _ri
                        )

        if len(defuns) <= 1:
            return self._collect_single(defuns, others, program)

        # 1. 模块注册域（CAD：按源码逆序逐 form 交错，defun 与顶层表达式均参与）。
        #    defun → 函数名；顶层 → 其字节码引用符号（逆序）。混合模式
        #    （i18n）下顶层表达式与 defun 按源码逆序交错，最后出现的顶层
        #    `(set '_ @::_)` 的 `_` 排在模块注册最前（i18n-cad 实测）。
        #    纯函数文件（无顶层）退化为"函数名逆序"，与多函数实测一致。
        self._register_module(program)
        self.module_reg_count = len(self.names)

        # 3. 函数体符号：按字节码引用序收集，逆序注册；唯一参数紧跟所属函数，
        #    共享参数注册在其源码序最先使用的函数之后。CAD 实测
        #    （f4/f4b/f4c/f4d/f4e/f4x/f4r/f5/m3/cross/sh/multi/rt_e/t15）：
        #    函数体内符号按"字节码首次引用序"（后序：先内层调用后外层函数名，
        #    即 USUBR 出现序）逐函数收集，源函数序拼接、先到先得去重后整体逆序；
        #    逆序后每函数引用组连续（源逆序），其唯一参数按逆序紧跟组末；
        #    跨函数共享参数注册在**源码序最先使用它的函数**（逆序迭代最后一个
        #    使用者）之后——multi 中 a/b 最先被源码第 0 个函数 add 使用，槽序
        #    排末尾；t15 中 p1/p2 最先被 get-dist（源码第 1 个）使用，槽序 =
        #    …DISTANCE, P2, P1, GETPOINT, STRING。链式/递归交叉调用下函数名
        #    由调用者引用组登记（递归名不重复槽）。
        seen_refs = set()
        kept_refs = []

        def _ci_ref_key(n):
            """跨函数 seen_refs 去重的规范化键：普通符号大小写不敏感
            （CAD 大小写不敏感，lifecycle `'LIST`(quoted) 与 `list`(内建调用)
            应去重到**源码序首次**出现——lifecycle CAD 实测 LIST fg[38] 在
            @::pkg-on-load（首个 `(list ...)` 调用）区而非 @::get-pkg-deps
            （`(eq 'LIST ...)` quoted），旧 case-sensitive set 使两者并存 →
            OURS LIST fg[12] 提前 26 槽）；vla-/vlax- 与字符串/常量结构保留
            原键（大小写敏感/精确）。"""
            if isinstance(n, str) and not n.lower().startswith(("vla-", "vlax-")) and not n.startswith(('"', "'", "__")):
                return n.upper()
            return n
        # 唯一参数（只在一个函数出现的参数名，非共享）：foreach 循环变量若与
        # 其同名不独立注册——CAD 复用参数拥有者的槽（cache.lsp `subdir` =
        # cache-store 参数 + cache-clear-all foreach 变量，CAD 实测共享 fg[46]，
        # foreach 处无独立槽）。@lisp_u `cmd`（foreach + **共享**参数）才独立
        # 注册（共享参数槽不特定于某函数）。
        _arg_count: dict = {}
        for _f in defuns:
            for _a in _f.args:
                _arg_count[_a] = _arg_count.get(_a, 0) + 1
        self._unique_params = {a for a, c in _arg_count.items() if c == 1}
        for _jf, f in enumerate(defuns):
            self._cur_source_idx = _jf
            refs = _SeenList()
            arg_names = set(f.args)
            body = strip_docstring(f.body)
            for _bi, expr in enumerate(body):
                self._collect_byteorder(
                    expr, refs, arg_names, cur_locals=set(f.locals),
                    _is_tail=(_bi == len(body) - 1),
                )
            # 同一函数内对函数名的多次调用共享同一个重复槽（t09 中 sum-of-squares
            # 两次调用 square 仅 1 个重复 SQUARE 槽；CAD 实测）。
            seen_forced = set()
            intra_dedup = []
            for name, fr in refs:
                if fr and name in seen_forced:
                    continue
                intra_dedup.append((name, fr))
                if fr:
                    seen_forced.add(name)
            kept = [(n, fr) for n, fr in intra_dedup if _ci_ref_key(n) not in seen_refs]
            seen_refs.update(_ci_ref_key(n) for n, _ in intra_dedup)
            kept_refs.append(kept)

        nfuncs = len(defuns)
        # 每个共享参数：记录源码序最先使用它的函数索引（逆序迭代最后处理到）。
        shared_first_user = {}
        for i, f in enumerate(defuns):
            for arg in f.args:
                if arg in self.shared and arg not in shared_first_user:
                    shared_first_user[arg] = i

        # 混合模式（defun + 顶层表达式）下，模块注册已含顶层符号；函数体符号
        # 若与模块注册符号同名，需作为重复槽**强制**再注册（t10_init 实测
        # `*VERSION* PRINC` 在模块段与函数体段各出现一次）。纯函数文件不受影响
        # （模块注册仅函数名，函数体符号本就独立）。
        module_reg_names = set(self.names)
        # 大小写不敏感集合：`vla-sendcommand`（函数体原始名）与模块注册的
        # 规范化名 `vla-SendCommand` 需判定为同符号（否则 force=False → 重复
        # 槽被 add() 丢弃 → fg 表缺该符号 → USUBR 走 nsyms-1 越界编码，
        # CAD 加载访问冲突 0xC0000005，@lisp_u 实测）。
        _module_reg_upper = {str(n).upper() for n in module_reg_names}
        # `_al-bind-alist` 共享槽注册在**源码序第一个**带 `/ 局部变量` 的函数
        # （逆序迭代最后一个 local 函数 = `@::update-locale`），而非第一个遍历到
        # 的 local 函数（i18n-cad 实测 slot 121 在 @::update-locale 区）。其余
        # local 函数不重复注册 `_al-bind-alist`（共享，codegen 按符号名取回）。
        source_first_local = next((f for f in defuns if f.locals), None)
        # 全局"已被函数体引用"的符号集合。局部变量若已被任一函数体字节码引用
        # （即出现在某 kept_refs 中，如 save-mt 的 fp/opt%/*error% 分别由
        # load-locale/load-mt 引用），则不在此单独注册槽（i18n-cad 实测：
        # save-mt 无独立局部变量槽，均由引用它的函数体组注册）。
        claimed_in_body = set()
        for kept in kept_refs:
            for n, _ in kept:
                claimed_in_body.add(n)
        # CAD 的 locals 常量（`(quote (locals...))`）对相同结构只注册一次，
        # 位置在**逆序最后遇到**它的函数处（base-function 实测 remove-dups
        # 与 getf 同为 `(quote (result))`，CAD 槽在 getf 组而非 remove-dups 组）。
        # 预扫描每个 locals 常量结构的逆序最后出现索引。
        locals_last = {}
        for _i, _f in enumerate(reversed(defuns)):
            if _f.locals:
                locals_last[tuple(_f.locals)] = _i
        # cond else 键 `T` 同规则：跨函数只注册一次，位置在逆序最后遇到它的
        # 函数处（base-function 实测 5 处 `(t ...)`，CAD 槽在 handle-keywords 组，
        # 而非先遇到的 pair 组）。其余普通符号仍先到先得去重。
        t_last = None
        for _i, _k in enumerate(reversed(kept_refs)):
            if any(str(n).lower() == "t" for n, _ in _k):
                t_last = _i
        # 局部变量同时是**其它函数参数**（net/probe `cached` = internetp 的
        # `/ cached` 局部 + check-cached-online 的参数；cmd.lsp `pkg-name` =
        # C:@DEP/C:@R 局部 + @::package-remove 参数）：CAD 把该槽注册在**后处理
        # 的拥有者**处——参数拥有者处理更晚（net/probe check-cached-online
        # reversed idx 2 > internetp idx 0）时由参数函数 args 循环注册
        # （fg[75]）；局部拥有者处理更晚（cmd.lsp C:@DEP reversed idx 1 >
        # @::package-remove idx 0）时由局部拥有者函数体组/局部注册（fg[75]）。
        # 先处理的拥有者须跳过（否则 `_name_set` 抢先占用低位槽）。
        _n_funcs = len(defuns)
        _local_is_param = {
            loc
            for func in defuns
            for loc in func.locals
            if any(loc in g.args for g in defuns)
        }
        _local_is_param_order = {}
        _local_is_param_last = {}
        _param_is_param_last = {}
        for _loc in _local_is_param:
            _local_last = max(
                (_n_funcs - 1 - _j for _j, _f in enumerate(defuns) if _loc in _f.locals),
                default=-1,
            )
            _param_last = max(
                (_n_funcs - 1 - _j for _j, _f in enumerate(defuns) if _loc in _f.args),
                default=-1,
            )
            _local_is_param_order[_loc] = "local" if _local_last >= _param_last else "param"
            _local_is_param_last[_loc] = _local_last
            _param_is_param_last[_loc] = _param_last
        # 共享参数注册位置：逆序处理**最后遇到**的引用者（参数声明或 body/
        # foreach 引用，如 persist `pkg-name` = package-path/get-local-pkg-info
        # 参数 + save-pkg-in-use foreach 变量 → CAD fg[81] 在 save-pkg-in-use
        # 组；cache `subdir` = cache-store 等参数 + cache-clear-all foreach 变量
        # → CAD fg[46] 在 cache-store 组，因 cache-clear-all 逆序 i=0 先处理、
        # 参数 i 更高）。故共享参数/foreach 变量仅在 ``_shared_last[名] == i``
        # 的函数处注册（先处理者跳过，避免抢先占低位槽）。
        _shared_last: dict = {}
        for _i, _f in enumerate(reversed(defuns)):
            for _arg in _f.args:
                if _arg in self.shared:
                    _shared_last[_arg] = max(_shared_last.get(_arg, -1), _i)
        # 共享参数在 body/quoted 引用（含大小写变体，file-utils `'STR` 引用
        # parse-header、参数声明 str 在 path-win/path-unix/path-os）时按
        # **逆序最后引用者**注册：kept 扫描大小写不敏感（与 `_ci_ref_key`
        # 一致），存入规范键（参数声明名）——否则 parse-header 的 `'STR` 不
        # 计入 → _shared_last['str']=7（path-win args）抢先占槽，CAD 在
        # parse-header 组 slot 60。
        _shared_ci = {str(s).upper(): s for s in self.shared}
        for _i, _k in enumerate(reversed(kept_refs)):
            for _n, _ in _k:
                if isinstance(_n, str) and _n.upper() in _shared_ci:
                    _shared_last[_shared_ci[_n.upper()]] = max(
                        _shared_last.get(_shared_ci[_n.upper()], -1), _i
                    )
        for i, (f, kept) in enumerate(zip(reversed(defuns), reversed(kept_refs))):
            # 函数体符号逆序注册；CAD 对 kwote 块（kwote + lambda 体，由
            # `__kwote_end__` 标记）保持收集序整体插到**调用者**（块后第一个
            # 函数名）之后：base-function getf 实测 `[CADR, VL-MEMBER-IF,
            # kwote, VL-PRIN1]`，i18n load-mt 实测 `[REVERSE, @::WITH-FILE-
            # LINES, kwote, ...]`（kwote 不随其它符号逆序沉底）。
            _kwote_blocks = []  # (kwote 项, 块体逆序, 调用者名)
            _rest = []
            _pos = 0
            while _pos < len(kept):
                _x = kept[_pos]
                if _x[0] == "kwote":
                    _pos += 1
                    _body = []
                    while _pos < len(kept) and kept[_pos][0] != "__kwote_end__":
                        _body.append(kept[_pos])
                        _pos += 1
                    _pos += 1  # 跳过 __kwote_end__
                    _caller = None
                    _cj = _pos
                    while _cj < len(kept):
                        _c = kept[_cj]
                        if _c[0] == "kwote":
                            # 跳过后续 kwote 块（含其体）：多 kwote 时前一 kwote
                            # 的调用者在后续 kwote 块之后（probe-network-uris 双
                            # kwote 实测 kwote1 调用者 = @::network-circuit-trip，
                            # 在 kwote2 块之后；不跳过则误判为 `kwote` 标记）。
                            _cj += 1
                            while _cj < len(kept) and kept[_cj][0] != "__kwote_end__":
                                _cj += 1
                            _cj += 1
                            continue
                        if not str(_c[0]).startswith(("'", "(")) and str(_c[0]) not in (
                            "nil",
                            "T",
                        ):
                            _caller = _c[0]
                            break
                        _cj += 1
                    # kwote lambda 体符号逆序注册（与其他函数体符号一致；
                    # net/proxy.lsp 双函数 kwote 实测 `VL-STRING-SEARCH @proxy.exe
                    # vlax-release-object ...` 逆序，net/reload 单函数同）。
                    _kwote_blocks.append((_x, list(reversed(_body)), _caller))
                else:
                    _rest.append(_x)
                    _pos += 1
            _rev = list(reversed(_rest))
            # 多 kwote 同调用者（probe-network-uris 双 kwote 都跟在
            # @::network-circuit-trip 后，CAD 实测 `[OFFLINE, kwote, @::EVENT-EMIT,
            # NETWORK-STATUS-CHANGED]` = reversed(`[kwote, NETWORK-STATUS-CHANGED,
            # @::EVENT-EMIT, kwote, OFFLINE]`)）：合并为「逆序块体 + kwote」链
            # （每个块 `[body_rev, kwote]`，按块逆序拼接，kwote 去重）。单 kwote
            # （net/proxy/cache/reload）保持 `[kwote, body_rev]`。
            if len(_kwote_blocks) >= 2 and len({_b[2] for _b in _kwote_blocks}) == 1:
                _merged = []
                for _kw, _body, _caller in reversed(_kwote_blocks):
                    _merged += _body + [_kw]
                _caller = _kwote_blocks[0][2]
                if _caller is not None:
                    for _j, (_m, _) in enumerate(_rev):
                        if _m == _caller:
                            _rev = _rev[: _j + 1] + _merged + _rev[_j + 1 :]
                            break
                    else:
                        _rev = _merged + _rev
                else:
                    _rev = _merged + _rev
            else:
                # 多 kwote 不同调用者（cmd.lsp @::package-remove 的 kwote3
                # vl-catch-all-apply / kwote4 config-sync-packages-push）：CAD
                # 的 kwote 槽只在**源码序第一个** lambda kwote 块处注册（cmd.lsp
                # CAD 实测 kwote 在 fg[21] = kwote3 块 marker 位置，kwote4 块
                # body 无 marker；net/proxy 的 proxy 函数 kwote 块被跨函数
                # seen_refs 去重、不在此）。故仅第一个块插 marker，其余块只插
                # body（marker 去重）。
                _first_block = _kwote_blocks[0] if _kwote_blocks else None
                for _blk in reversed(_kwote_blocks):
                    _kw, _body, _caller = _blk
                    _pre = [_kw] if _blk is _first_block else []
                    if _caller is not None:
                        for _j, (_m, _) in enumerate(_rev):
                            if _m == _caller:
                                _rev = _rev[: _j + 1] + _pre + _body + _rev[_j + 1 :]
                                break
                        else:
                            _rev = _pre + _body + _rev
                    else:
                        # kwote 块无后续调用者（调用者已被跨函数去重，net/cache
                        # @::uri-safe 的 vl-catch-all-apply 被前一函数占用）：CAD
                        # 把 `kwote` 放在块体之前（实测 [kwote, @::uri]）。
                        _rev = _pre + _body + _rev
            _t_added = False
            for name, force in _rev:
                if str(name).lower() == "t":
                    # CAD T 槽：模块注册区（顶层 cond else 键）与函数体区
                    # （函数 cond else 键）各自独立注册（platform.lsp CAD 实测
                    # 两处 `T`：模块 [27] + 函数体 [43]，后者喂 fg 表 gvar 槽）。
                    # T 已在模块区注册过（_name_set 含 T）时直接追加重复槽，
                    # 否则走 add() 常规注册。同函数内多个 `t`（值位置 `(setq x t)`
                    # 与 cond else 键 `(t ...)`，reactor.lsp 实测）只注册一次——
                    # 旧代码 _rev 两个 `t` 都过 `i != t_last` 分支 → T 槽双发
                    # （nsyms +1、后续槽错位）。
                    if i != t_last or _t_added:
                        continue
                    _t_added = True
                    if "T" in self._name_set:
                        self.names.append("T")
                    else:
                        self.add("T", force=True)
                    continue
                if isinstance(name, str) and name in _local_is_param:
                    # 局部同时是其它函数参数：槽注册在**最后处理的拥有者**处。
                    # order="param"（参数拥有者后处理，net/probe `cached`）：局部
                    # 拥有者（name in f.locals）跳过，参数拥有者注册。
                    # order="local"（局部拥有者后处理，net/module `response-str` =
                    # load-module/fetch-module 局部 + cache-module-response/eval-module
                    # 参数）：参数拥有者（name not in f.locals）与**非最后**局部
                    # 拥有者（i != _local_is_param_last）跳过，仅最后局部拥有者
                    # 注册（否则 @::load-module i=0 抢先占低位槽，CAD 在
                    # @::fetch-module i=4 组 fg[50]）。
                    _lo = _local_is_param_order.get(name)
                    if _lo == "param":
                        if name in f.locals:
                            continue
                    else:
                        if name not in f.locals or i != _local_is_param_last.get(name):
                            continue
                if (
                    isinstance(name, str)
                    and name in self.shared
                    and name not in _local_is_param
                    and _shared_last.get(name) != i
                ):
                    # 共享参数名在 body/foreach 引用（persist pkg-name foreach 变量、
                    # cache subdir foreach 变量）：仅在逆序最后引用者（_shared_last）
                    # 处注册，先处理者跳过（否则抢先占低位槽）。_local_is_param
                    # 符号（局部+参数混合）由 _local_is_param_order/_last 决定
                    # 注册者，不走 _shared_last。
                    continue
                self.add(
                    name,
                    force=force
                    or (isinstance(name, str) and name.upper() in _module_reg_upper),
                )
            # CAD `/ 局部变量`（多函数）：与单函数一致注入 `_al-bind-alist` +
            # `(quote (locals...))` 常量；`_al-bind-alist` 全文件共享一个符号槽
            # （i18n-cad 实测仅 1 个 `_al-bind-alist`），locals 常量每函数独立。
            # i18n-cad 实测槽序：`_al-bind-alist` → locals 常量 → 局部变量 →
            # 参数（@::update-locale: `_al-bind-alist (LOC-FILE) LOC-FILE PKG-NAME`）。
            if f.locals:
                if f is source_first_local:
                    self.add('_al-bind-alist')
                if locals_last.get(tuple(f.locals)) == i:
                    self.add((CONST_MARK, ('LIST', tuple(('SYMBOL', l) for l in f.locals))))
            for loc in reversed(f.locals):
                # 仅**用过**的 / 局部变量注册独立符号槽：used 局部有 body+const
                # 双槽（i18n LOC-FILE@108+122），unused 局部仅 const 槽
                # （checksum.lsp 未使用的 `checksum` CAD 无独立槽实测，此前
                # `not in claimed_in_body` 反向注册 unused → nsyms +1）。
                # 注意：claimed_in_body 的局部由**引用它的函数**的函数体组注册
                # （CAD 槽在所属函数体组内），此处不重复注册——否则跨函数共享
                # 局部（net/cache 的 `result` 被 3 个函数声明、仅 cache-store
                # 体 `setq result` 引用）会在先处理的声明函数（逆序首个 =
                # uri-safe）提前注册，错位到函数体组前。unused 局部（checksum
                # 的 `checksum`）同样不注册（CAD 无独立槽）。故仅当局部在
                # **当前函数体**引用（`loc in 本函数 kept`）且未被函数体组
                # 注册时才 add——实际已由函数体组注册，此处为安全 no-op。
                _kept_names = {n for n, _ in kept}
                if loc in _local_is_param:
                    # 局部同时是其它函数参数：由 _local_is_param_order/_last 决定
                    # 注册者。order="param" 局部拥有者跳过（参数拥有者注册）；
                    # order="local" 仅**最后**局部拥有者注册——即使 local 被
                    # shared 过滤出 kept（net/module `response-str` shared 参数
                    # 被 Setq target 收集过滤，@::fetch-module kept 无 response-str，
                    # 仅 locals 循环能注册）。
                    _lo = _local_is_param_order.get(loc)
                    if _lo == "param" or (
                        _lo == "local" and i != _local_is_param_last.get(loc)
                    ):
                        continue
                    if loc not in self._name_set:
                        self.add(loc)
                    continue
                if loc in _kept_names and loc not in self.shared and loc not in self._name_set:
                    self.add(loc)
            for arg in reversed(f.args):
                if arg in _local_is_param and _local_is_param_order.get(arg) == "local":
                    # 局部拥有者后处理（net/module `response-str` = cache-module-
                    # response/eval-module 参数 + load-module/fetch-module 局部，
                    # order="local"）：由局部拥有者注册，参数 args 循环不注册
                    # （否则 @::cache-module-response 按 _shared_last=3 抢先占槽，
                    # CAD 在 @::fetch-module i=4 组）。注意此检查须在 shared 之前
                    # （response-str 同时是 shared 参数）。
                    continue
                if arg in self.shared:
                    # 共享参数注册在逆序最后引用者（_shared_last）处：
                    # persist pkg-name 在 save-pkg-in-use（foreach）注册；
                    # cache subdir 在 cache-store（参数，i 更高）注册。
                    if _shared_last.get(arg) == i:
                        self.add(arg)
                elif arg not in self._name_set:
                    # 唯一参数被逆序更晚处理的函数 quoted 引用（file-utils
                    # `'STR` = path-win 参数 + parse-header `(eq 'STR ...)`，
                    # CAD slot 在 parse-header 组）：由引用函数组收集注册，
                    # args 循环跳过（否则 owner 先处理抢低位槽）。
                    if any(
                        str(arg).upper() == x.upper()
                        for x in getattr(self, "_quoted_param_collected", set())
                    ):
                        continue
                    # 参数同时是**逆序更晚处理**的 kwote lambda 参数（string-utils
                    # `x` = strbytelen 参数 + string-split lambda 参数，宿主
                    # reversed idx 6 > strbytelen 0）：由 kwote lambda 宿主收集
                    # 注册（CAD x 在 string-split kwote 块 fg[44]），args 循环
                    # 跳过（否则 strbytelen 抢先占 fg[7]，后续槽错位）。
                    if getattr(self, "_param_lam_hosts", {}).get(arg, -1) > i:
                        continue
                    self.add(arg)

        return self.names

    def _lam_tail_value(self, node):
        """提取顶层 setq-lambda 的尾调用名（最后一个 body form 的值函数）。
        简单符号（net/wget 末 form `outfile`）返回 None（无尾调用）；函数调用
        返回函数名（fasext 末 `(strcat ...)` → strcat）；`if`/`setq`/`progn`
        递归取分支值（vlx 末 `(if ... (setq str-vlx (strcat ...)) str-vlx)`
        → then 分支 setq 值 strcat）。
        """
        if isinstance(node, Symbol):
            return None
        if isinstance(node, Call):
            return str(node.name)
        if isinstance(node, IfNode):
            for branch in (node.then, node.else_expr):
                if branch is not None:
                    v = self._lam_tail_value(branch)
                    if v:
                        return v
            return None
        if isinstance(node, Setq):
            if node.pairs:
                return self._lam_tail_value(node.pairs[-1][1])
            return None
        if isinstance(node, Progn):
            if node.forms:
                return self._lam_tail_value(node.forms[-1])
            return None
        return None

    def _iter_kwote_lambdas(self, node):
        """递归收集 AST 中的 kwote lambda（`(function (lambda ...))`）。"""
        from compiler.ast_nodes import (
            QuotedExpr as _Q,
            LambdaNode as _LN,
            Call as _C,
            IfNode as _I,
            Progn as _P,
            WhileNode as _W,
            ForeachNode as _F,
            RepeatNode as _R,
            Cond as _Cnd,
            Setq as _S,
            ListExpr as _LE,
        )

        if isinstance(node, _Q) and getattr(node, "kwote", False) and isinstance(node.expr, _LN):
            yield node.expr
            for _b in node.expr.body:
                yield from self._iter_kwote_lambdas(_b)
        elif isinstance(node, _LE) and node.items and isinstance(node.items[0], _LN):
            # 立即应用 `((lambda ...) args)`（CAD 内嵌 `-lambda-` DEFUN + EVAL）：
            # lambda 参数同 kwote lambda 注册符号槽（dcl `dcl-name` = dcl-run
            # 参数 + dcl-dialog lambda 参数，CAD 槽在 dcl-dialog 组）。
            yield node.items[0]
            for _b in node.items[0].body:
                yield from self._iter_kwote_lambdas(_b)
        elif isinstance(node, _LN):
            for _b in node.body:
                yield from self._iter_kwote_lambdas(_b)
        elif isinstance(node, _C):
            for _a in node.args:
                yield from self._iter_kwote_lambdas(_a)
        elif isinstance(node, _I):
            for _x in (node.cond, node.then, node.else_expr):
                if _x:
                    yield from self._iter_kwote_lambdas(_x)
        elif isinstance(node, _P):
            for _f_ in node.forms:
                yield from self._iter_kwote_lambdas(_f_)
        elif isinstance(node, (_W, _R)):
            for _b in node.body:
                yield from self._iter_kwote_lambdas(_b)
        elif isinstance(node, _F):
            for _b in node.body:
                yield from self._iter_kwote_lambdas(_b)
        elif isinstance(node, _Cnd):
            for _cl in node.clauses:
                for _it in _cl[1:]:
                    yield from self._iter_kwote_lambdas(_it)
        elif isinstance(node, _S):
            for _t, _v in node.pairs:
                if _v:
                    yield from self._iter_kwote_lambdas(_v)

    def _collect_single(self, defuns, others, program):
        """单函数文件（≤1 defun）：模块注册与函数体符号按 CAD 序收集。

        函数体符号按首次字节码引用序的逆序注册（调用内参数先于函数名出现在
        字节码中：PUSH_G arg… → USUBR func，逆序后函数名在前），参数（含共享）
        放最后；递归函数名产生重复槽但不提前。
        """
        # 模块注册域：有 defun 时（含纯函数与混合模式）CAD 按源码逆序逐 form
        # 交错注册（顶层符号可能穿插在 defun 名前后）。纯顶层文件（无 defun）
        # 退化为：函数名字段为空 + 顶层 refs 全局逆序（setcmp/set5/setqa 实测）。
        # 含顶层 `(set/setq 'sym (lambda ...))` 的纯顶层文件（setq-lambda.lsp）：
        # CAD 的模块注册段（第一区）只含顶层表达式符号，`-lambda-` 体符号
        # 单独在第二区（`-lambda-` 函数体）。故走 `_register_module` 生成模块
        # 注册段，kwote lambda 体符号由下方单独收集。普通纯顶层文件（无 kwote
        # lambda）仍走全局逆序（test-cond/setcmp/set5/setqa byte-identity）。
        from compiler.ast_nodes import LambdaNode as _TLN, QuotedExpr as _TQ

        def _is_top_lam(v):
            # 顶层 `(set/setq 'sym (lambda ...))`：lambda 可为 kwote QuotedExpr
            # 或裸 LambdaNode（net/wget `(set '@::wget (lambda ...))` AST 实测
            # arg1 是裸 LambdaNode，kwote=False；cli `_lambda_of` 两种都认）。
            return isinstance(v, _TLN) or (isinstance(v, _TQ) and isinstance(v.expr, _TLN))

        _has_top_lam = any(
            (isinstance(_f, Setq)
             and any(isinstance(_t, Symbol) and _is_top_lam(_v) for _t, _v in _f.pairs))
            or (isinstance(_f, Call) and _f.name == "set" and len(_f.args) == 2
                and _is_top_lam(_f.args[1]))
            for _f in others
        )
        if program and defuns:
            self._register_module(program)
            self.module_reg_count = len(self.names)
        elif _has_top_lam:
            self._register_module(program, _skip_lam_bodies=True)
            self.module_reg_count = len(self.names)
        elif others:
            # 纯顶层文件：顶层 refs 按字节码引用序收集后全局逆序注册。
            refs = _SeenList()
            for form in others:
                self._collect_byteorder(form, refs, set())
            _rev = list(reversed(refs))
            # CAD 中 T 槽由**外层 cond 的 else 键** `(t ...)`（forward 序第一个
            # force t，reversed 序最后一个）位置决定（test-cond 实测 `"chs" ...
            # T "autocad"`——T 在结果体后、测试符号前）。内层 cond 的 else 键
            # t 与值位置 `T`（`(strcase ... T)`）复用该槽。reversed 注册时值
            # 位置 T（非 force）与内层 else 键 t（force）会抢先注册，故仅保留
            # reversed 序**最后一个** force t 注册，其余 t/T 跳过。
            _t_force_idx = [i for i, (n, f) in enumerate(_rev)
                            if isinstance(n, str) and n.lower() == 't' and f]
            _t_reg_idx = _t_force_idx[-1] if _t_force_idx else -1
            for i, (name, force) in enumerate(_rev):
                # kwote 块结束标记（`__kwote_end__`）仅作收集分隔，不注册符号
                # （多函数路径同样过滤，纯顶层路径也需过滤——setq-lambda.lsp
                # 顶层 `(setq X (lambda ...))` 走 `_rewrite_top_lambda_binds`
                # 产生的 kwote 标记泄漏为符号槽实测）。
                if name == "__kwote_end__":
                    continue
                if isinstance(name, str) and name.lower() == 't':
                    if i != _t_reg_idx:
                        continue
                self.add(name, force=force)
            self.module_reg_count = len(self.names)
        module_reg_names = set(self.names)
        # 大小写不敏感集合（vla- 原始名 vs 规范化名，见多函数路径注释）。
        _module_reg_upper = {str(n).upper() for n in module_reg_names}

        # 3b. 纯顶层 `(set/setq 'sym (lambda ...))`（kwote，CAD `-lambda-` 机制）：
        #     CAD 把 `-lambda-` 函数体符号 + 参数放模块注册段之后的第二区
        #     （setq-lambda.lsp CAD golden 实测 `.vls = SUBSTR - STRLEN .vlx
        #     IS-ZWCAD STR-VLX STRCAT @::*FASEXT* FILE`——@::vlx 体在前、@::fasext
        #     体在后，各含参数 str-vlx/file，源码逆序）。故为每个 kwote lambda
        #     收集其 lambda 体符号（**不**排除参数，参数也要注册）+ 参数。
        from compiler.ast_nodes import LambdaNode as _LN, QuotedExpr as _Q

        _lam_seen = set()  # 3b 内部去重：跨 lambda 的重复符号（strcat）只注册一次
        # 仅**纯顶层**（无 defun）文件走第二区 `-lambda-` 处理（net/wget/
        # setq-lambda.lsp）；混合文件（platform 等，有 defun）的顶层 setq-lambda
        # 是引用数据，其体符号已在模块注册段，不在此重复处理。
        for form in reversed(others) if (_has_top_lam and not defuns) else ():
            _lam = None
            if isinstance(form, Setq):
                for _t, _v in form.pairs:
                    if isinstance(_v, _LN) or (isinstance(_v, _Q) and isinstance(_v.expr, _LN)):
                        _lam = _v if isinstance(_v, _LN) else _v.expr
                        break
            elif isinstance(form, Call) and form.name == "set" and len(form.args) == 2:
                _v1 = form.args[1]
                if isinstance(_v1, _LN) or (isinstance(_v1, _Q) and isinstance(_v1.expr, _LN)):
                    _lam = _v1 if isinstance(_v1, _LN) else _v1.expr
            if _lam is None:
                continue
            # CAD `-lambda-` 体符号顺序（setq-lambda.lsp golden 实测 @::vlx 体
            # `.vls = SUBSTR - STRLEN .vlx IS-ZWCAD` + 参数 STR-VLX + STRCAT，
            # @::fasext 体 `@::*FASEXT* FILE`）：`_collect_byteorder` forward
            # 逆序（去最后调用名 strcat）→ 参数 → 最后调用名（strcat，跨 lambda
            # 去重）。用空 arg_names 收集（参数也收集，随后移末尾）。
            refs = _SeenList()
            for expr in _lam.body:
                self._collect_byteorder(expr, refs, set())
            _fwd = [(n, f) for n, f in refs if n != "__kwote_end__" and n != "kwote"]
            # 最后调用名 = **最后一个 body form 的值**（setq 值/末表达式函数名）。
            # setq-lambda vlx/fasext 以 `(strcat ...)` / `(if ... (setq str-vlx
            # (strcat ...)) str-vlx)` 结尾 → strcat（CAD 尾调用槽）；net/wget 以
            # `outfile`（Symbol）结尾 → 无尾调用（null 是中间 `(if (null ...))`
            # 的条件函数，不应剔除——旧 pop 策略把它误当尾调用，nsyms 少 1）。
            _tail_call = None
            if _lam.body:
                _tail_call = self._lam_tail_value(_lam.body[-1])
                if _tail_call is not None:
                    # 从 _fwd 剔除尾调用名（其余体符号逆序注册后、参数前单独
                    # 注册；net/wget 无尾调用时 _fwd 完整保留）。
                    _fwd = [(n, f) for n, f in _fwd if n != _tail_call]
            # 逆序注册体符号（去 strcat）。
            _lam_real_params = set(_lam.args)
            if "/" in _lam.args:
                _lam_real_params = set(_lam.args[: _lam.args.index("/")])
            for name, force in reversed(_fwd):
                if isinstance(name, str) and name in _lam_real_params:
                    continue  # 真参数最后注册（`/` 后的局部变量照常注册为体符号）
                if isinstance(name, str) and name in _lam_seen:
                    continue
                _lam_seen.add(name)
                self.add(name, force=True)
            # 参数（逆序）：`/` 分隔符之后是 `/ 局部变量`（走 `_al-bind-alist`
            # 绑定，不注册为参数槽；`/` 本身也不注册——net/wget
            # `(lambda (uri outfile extra-headers / cmd headers) ...)` CAD 实测
            # 只注册 URI/OUTFILE/EXTRA-HEADERS，CMD/HEADERS 由函数体 + const 注册）。
            _lam_params = _lam.args
            _lam_locals = []
            if "/" in _lam_params:
                _lam_params = _lam_params[:_lam_params.index("/")]
                _lam_locals = _lam.args[_lam.args.index("/") + 1 :]
            # `/ 局部变量`：注入 `_al-bind-alist` 助手 + `(quote (locals...))`
            # 常量（net/wget CAD 实测 `_al-bind-alist` 在 body 后、参数前，
            # const 紧随其后），与 defun locals 同协议。
            if _lam_locals:
                self.add("_al-bind-alist")
                self.add((CONST_MARK, ("LIST", tuple(("SYMBOL", l) for l in _lam_locals))))
            for arg in reversed(_lam_params):
                if arg not in self._name_set:
                    self.add(arg)
            # 最后调用名（strcat，跨 lambda 去重）。
            if _tail_call is not None and _tail_call not in _lam_seen:
                _lam_seen.add(_tail_call)
                self.add(_tail_call, force=True)        #    递归函数名：多次自身调用共享同一个重复槽（t03 递归两次仅 1 个重复
        #    FIB 槽；fact 递归一次 1 个重复槽）。
        for f in reversed(defuns):
            all_args = f.args + f.optional + ([f.rest] if f.rest else [])
            arg_names = set(all_args)
            refs = _SeenList()
            for expr in strip_docstring(f.body):
                self._collect_byteorder(expr, refs, arg_names)
            seen_forced = set()
            deduped = []
            for name, force in refs:
                if force and name in seen_forced:
                    continue
                deduped.append((name, force))
                if force:
                    seen_forced.add(name)
            # CAD 对 kwote 块（kwote + lambda 体）：lambda 体符号按收集序逆序
            # 注册（与其他函数体符号一致），`kwote` 符号插到调用者之后而非随
            # 体逆序沉底（net/reload.lsp 单函数双 kwote 实测：
            # `@::EVENT-EMIT LIST MODULE-RELOADED @::LOAD-MODULE
            # VL-CATCH-ALL-APPLY kwote RESULT ...`——两个 lambda 体逆序分列
            # 调用者前后，kwote 在调用者 VL-CATCH-ALL-APPLY 之后）。
            _kwote_blocks = []  # (kwote 项, 调用者名)
            _rest = []
            _pos = 0
            while _pos < len(deduped):
                _x = deduped[_pos]
                if _x[0] == "kwote":
                    _pos += 1
                    _body = []
                    while _pos < len(deduped) and deduped[_pos][0] != "__kwote_end__":
                        _body.append(deduped[_pos])
                        _pos += 1
                    _pos += 1  # 跳过 __kwote_end__
                    _caller = None
                    for _c in deduped[_pos:]:
                        if not str(_c[0]).startswith(('"', "'", "(")) and str(_c[0]) not in (
                            "nil",
                            "T",
                        ):
                            _caller = _c[0]
                            break
                    # lambda 体符号逆序（与其他函数体符号一致）
                    _kwote_blocks.append((_x, list(reversed(_body)), _caller))
                else:
                    _rest.append(_x)
                    _pos += 1
            _rev = list(reversed(_rest))
            # kwote 块：体逆序注册（kwote 之后的顺序），kwote 插到调用者之后。
            # 多块共享调用者时（net/reload 两个 vl-catch-all-apply），块按
            # 源码逆序插入，kwote 去重后位于调用者之后、最后一个块的体之前。
            for _kw, _body, _caller in reversed(_kwote_blocks):
                if _caller is not None:
                    for _j, (_m, _) in enumerate(_rev):
                        if _m == _caller:
                            _rev = _rev[: _j + 1] + [_kw] + _body + _rev[_j + 1 :]
                            break
                    else:
                        _rev = [_kw] + _body + _rev
                else:
                    _rev = _body + _rev
            for name, force in _rev:
                # kwote 块结束标记（`__kwote_end__`）仅作收集分隔，不注册符号。
                if name == "__kwote_end__":
                    continue
                # 混合模式（defun + 顶层）：函数体符号若与模块注册符号同名，需作为
                # 重复槽强制再注册（base-function `(set item item)` 的 SET 在模块段
                # 与函数体段各一次，CAD 实测；t10_init `*VERSION* PRINC` 同）。
                # 纯函数文件模块注册仅函数名，函数体符号本就独立（force 不影响）。
                self.add(
                    name,
                    force=force
                    or (isinstance(name, str) and name.upper() in _module_reg_upper),
                )
            # CAD `/ 局部变量`：注入 `_al-bind-alist` 助手符号与局部变量引用
            # 常量 `(quote (locals...))`，紧跟函数体符号之后、参数之前
            # （t11_localvars 实测：`+ <= I RESULT _al-bind-alist (RESULT I) N`）。
            if f.locals:
                self.add('_al-bind-alist')
                self.add((CONST_MARK, ('LIST', tuple(('SYMBOL', l) for l in f.locals))))
            for arg in reversed(all_args):
                if arg not in self._name_set:
                    self.add(arg)
            # / 局部变量不在此注册独立槽：used 局部已由函数体 refs 注册
            # （body 槽），unused 局部仅存于 `_al-bind-alist` const（const 槽）
            # ——与多函数路径 `claimed_in_body` 规则一致（checksum.lsp 未使用
            # 的 `checksum` CAD 无独立槽实测，此前 `add(loc)` 致 nsyms +1）。
        return self.names

    def _module_tail_boundary(self, program) -> int:
        """模块尾块边界：最后一个"模块初始化"顶层 setq 的 form 索引。

        CAD 把模块尾块（module code 引用的函数：init 链 + 命令 + sync 组）
        的函数名注册进模块注册段，之前的"库函数"仅经函数体符号区注册
        （atlisp_u 实测模块注册 = 源 defun 索引 416-463 = `(setq @::*sync-files*'
        ...)` 之后的全部 defun；i18n = `(setq @::*codepage* (vl-catch-all-apply
        ...))` 之后的 defun）。判定信号 = 顶层 setq 的值非平凡（引号/列表/
        调用/非 nil 符号）——纯 nil 的 `(setq x nil)` 不构成模块初始化边界。
        纯函数文件（无顶层 setq）返回 -1，即全部 defun 进模块注册。
        """
        last = -1
        for i, form in enumerate(program.forms):
            if isinstance(form, Setq):
                for _t, value in form.pairs:
                    if isinstance(value, QuotedExpr):
                        last = i
                        break
                    elif isinstance(value, Call):
                        last = i
                        break
                    elif isinstance(value, Symbol) and value.name not in ("nil", "T"):
                        last = i
                        break
        return last

    def _register_module(self, program, _skip_lam_bodies: bool = False):
        """模块注册域：按源码逆序逐 form 交错注册（defun 与顶层表达式均参与）。

        defun → 函数名；顶层 → _collect_byteorder 字节码引用符号（逆序注册）。
        混合模式（i18n）下顶层表达式与 defun 按源码逆序交错：位于源码尾部
        的顶层 form 其符号排在模块注册最前（i18n-cad/p03 实测：
        `(setq @::*codepage* (vl-catch-all-apply ...))` 在 defun 之后，其符号
        @::*CODEPAGE* VL-CATCH-ALL-APPLY syscodepage GETVAR 排在 @::CODEPAGE2LANG
        之前）。纯函数文件（无顶层）退化为"函数名逆序"。
        顶层 form 里的用户函数名调用（force=True）不另发槽——并入 defun
        槽（p04 实测 form4 调用 @::codepage2lang 不占顶层组）。

        模块注册 defun 名限定到"模块尾块"（_module_tail_boundary 之后）：
        CAD 只把模块代码引用的函数名注册进模块注册段（atlisp_u = 尾块 48
        个 defun），之前的库函数名仅经函数体符号区注册（否则模块注册段
        膨胀为全部函数名，golden 字节不一致）。
        """
        # InPackage `(in-package :@)`：CAD 在模块代码发射
        # `PUSH_VALUE :@; FUNC_REF in-package`，符号 `in-package`/`:@` 也注册进
        # 模块注册域（base-function/platform-api 实测 IN-PACKAGE/:@ 槽位紧跟
        # use-package 的 :AUTOLISP 之后）。插入源码原位参与逆序注册。
        module_boundary = self._module_tail_boundary(program)
        forms_all = []
        for f in program.forms:
            if isinstance(f, (Defpackage, InPackage)):
                # Defpackage `(defpackage :theme (:use :cl) (:export :bg-color))`：
                # CAD 注册名字/use/export 符号进模块注册段（atlisp_u 实测
                # :BG-COLOR/:THEME 紧跟顶层 set 符号、命令之前；:C 包的
                # export 别名在命令之后）。InPackage 同前保留。
                forms_all.append(f)
            else:
                forms_all.append(f)
        n = len(forms_all)
        reads, targets = [], []
        for form in forms_all:
            r, t = set(), set()
            if isinstance(form, Defun):
                t.add(form.name)
            elif isinstance(form, InPackage):
                r.update(("in-package", form.name))
            elif isinstance(form, Defpackage):
                r.add(form.name)
                r.update(form.use or [])
                r.update(form.export or [])
                # `defpackage`/`:export`/`:use` 关键字符号登记（CAD sub-system/
                # command 模块注册 = DEFPACKAGE + :EXPORT + 逆序 export + :USE +
                # use 包 + 包名）。
                r.update(("defpackage", ":export", ":use"))
            else:
                # 顶层 `(set/setq 'sym (lambda ...))`：**纯顶层文件**（无 defun）
                # 时 lambda 体符号不进模块注册段（由第二区 `_collect_forward`
                # 单独收集，net/wget 实测模块区仅 SET/@::WGET/#-SBCL）；混合
                # 文件（有 defun，platform 等）的顶层 lambda 是引用数据，体
                # 符号照常在模块注册段。
                from compiler.ast_nodes import (
                    LambdaNode as _ModLN,
                    QuotedExpr as _ModQE,
                )

                _skip_lam = False
                if _skip_lam_bodies:
                    if isinstance(form, Setq):
                        for _t, _v in form.pairs:
                            if isinstance(_t, Symbol) and (
                                isinstance(_v, _ModLN)
                                or (isinstance(_v, _ModQE) and isinstance(_v.expr, _ModLN))
                            ):
                                _skip_lam = True
                                t.add(_t.name)
                                break
                    elif isinstance(form, Call) and form.name == "set" and len(form.args) == 2:
                        _t0 = form.args[0]
                        _v1 = form.args[1]
                        if isinstance(_v1, _ModLN) or (
                            isinstance(_v1, _ModQE) and isinstance(_v1.expr, _ModLN)
                        ):
                            _skip_lam = True
                            r.add("set")
                            if isinstance(_t0, _ModQE) and isinstance(_t0.expr, Symbol):
                                t.add(_t0.expr.name)
                if _skip_lam:
                    pass
                else:
                    self._form_read_target(form, r, t, set())
            reads.append(r)
            targets.append(t)
        # 符号归属：setq 目标优先 → 最早赋值的 form；否则 → 最早读取的 form。
        # CAD p05/p06/p07 实测：`@::*LANG*` 既是 form0 `(setq @::*lang* ...)`
        # 的目标，又被末尾 `(null @::*lang*)` 读取——槽归属到目标 form0
        # （排在 pre-form 组尾部），而非读取它的 post-form。
        owner_read = {}
        owner_target = {}
        for i in range(n):
            for s in targets[i]:
                if s not in owner_target:
                    owner_target[s] = i
            for s in reads[i]:
                if s not in owner_read:
                    owner_read[s] = i
        ancestor = {}

        def _owner_of(sym):
            # 符号归属到**最早出现的 form**（read 或 target 的最小 form 序）：
            # CAD 把符号排在它首次被引用的 form 组。setq-lambda.lsp 实测
            # `command-s` 在 form2 `(type command-s)` 首次读取、form4 才是
            # setq 目标——CAD 槽排在 VL-CMDF（form2）之后而非 form4 组；
            # 若仅 owner_target 优先会误排到 form4。test-cond（纯顶层 cond）
            # 走 `_collect_single` 其他路径，不受此影响。
            cand = [i for i in (owner_target.get(sym), owner_read.get(sym)) if i is not None]
            return min(cand) if cand else -1

        # 模块区是否有 cond else 键 `t`（force t）：有则所有值位置 t 复用该槽，
        # 无则值位置 `t` 也注册 T 槽（@lisp-env 实测）。预扫描全部顶层 form。
        # CAD T 槽在模块区**全局唯一**（tcond5 实测：孤立顶层 `T` 与 userinfo
        # setq 的 cond else 键共享一个 T 槽），位置由 **forward 序第一个引用
        # T 的 form**（force t 或值位置 t 均可）决定（即 reversed 遍历序
        # 最后一个引用 T 的 form，tcond5 孤立 T 在 userinfo 之前 → T 槽在
        # userinfo 符号之后、函数名之前）。其余 form 的 force t / 值位置 t
        # 均复用该槽，不重复注册。
        _has_force_t = False
        _t_form = -1
        for _fi, _f in enumerate(forms_all):
            if isinstance(_f, (Defun, Defpackage, InPackage)):
                continue
            _fr = _SeenList()
            self._collect_byteorder(_f, _fr, set())
            _has_t_ref = any(
                isinstance(_n, str) and _n.lower() == 't' for _n, _ in _fr
            )
            if _has_t_ref and _t_form < 0:
                _t_form = _fi
            if any(isinstance(_n, str) and _n.lower() == 't' and _ff
                   for _n, _ff in _fr):
                _has_force_t = True

        module_seen = set()
        module_funcs = 0
        for i in reversed(range(n)):
            form = forms_all[i]
            if isinstance(form, Defun):
                # 模块尾块（_module_tail_boundary 之后）的 defun 名注册进模块
                # 注册段；之前的库函数名仍注册符号槽（保留名字可调用），但
                # 由 resource_builder 的 module_func_count 截断不落模块注册
                # 块（经函数体符号区注册）。
                if _owner_of(form.name) == i and form.name not in module_seen:
                    module_seen.add(form.name)
                    self.add(form.name)
                    if i >= module_boundary:
                        module_funcs += 1
            elif isinstance(form, (Defpackage, InPackage)):
                # Defpackage `(defpackage :C (:use :cl) (:export :@@W ...))`：
                # CAD 模块注册 = DEFPACKAGE + :EXPORT + 逆序 export 符号
                # （sub-system/command CAD 实测 `DEFPACKAGE :EXPORT :@DIAG :@AI
                # :@@ :@X :@T :@H :@W :@F :@C :@1 ATLISP :@ :@@W`）；in-package
                # = in-package + 包名。`defpackage`/`:export` 关键字符号需登记
                # （旧实现漏掉 → 后续 export 符号槽位错位）。
                if isinstance(form, InPackage):
                    _dp_items = [("in-package", False), (form.name, False)]
                else:
                    _dp_items = [("defpackage", False), (":export", False)]
                    _dp_items += [(e, False) for e in reversed(form.export or [])]
                    if form.use:
                        _dp_items.append((":use", False))
                    _dp_items += [(u, False) for u in (form.use or [])]
                    _dp_items += [(form.name, False)]
                for s in _dp_items:
                    if _owner_of(s[0]) == i and s[0] not in module_seen:
                        module_seen.add(s[0])
                        self.add(s[0])
            else:
                form_refs = _SeenList()
                self._collect_byteorder(form, form_refs, set())
                _rev = list(reversed(form_refs))
                # CAD T 槽由**外层 cond 的 else 键**（`(t ...)`）位置决定
                # （platform.lsp 实测 T 槽紧跟 else 键体符号 @::PGP-FILE/chs
                # 之后）。保留 reversed 序最后一个 force t 注册，其余 t/T
                # （内层 else 键、值位置 `(strcase ... T)` 等）跳过复用该槽
                # ——与纯顶层路径（test-cond）同规则。
                _t_force_idx = [j for j, (n, f) in enumerate(_rev)
                                if isinstance(n, str) and n.lower() == 't' and f]
                _t_reg_idx = _t_force_idx[-1] if _t_force_idx else -1
                # 模块区 T 槽全局唯一：仅 forward 序第一个引用 T 的 form
                # （_t_form）注册 T；其余 form 的 force t 与值位置 t 均跳过
                # 复用该槽（tcond5/atlisp_u 实测孤立 T 与各 cond else 键共享）。
                _i_is_t_form = i == _t_form
                for j, (name, force) in enumerate(_rev):
                    # 顶层符号调用（force=True）不登记槽——并入 defun 槽
                    # （CAD p04 form4 cadr/not/codepage 组无 c2l）。例外：
                    # cond else 键 `t`（force=True）在 T 槽位注册（CAD 实测）。
                    if force:
                        if (
                            _i_is_t_form
                            and isinstance(name, str)
                            and name.lower() == 't'
                            and j == _t_reg_idx
                        ):
                            self.add('T', force=True)
                        continue
                    # 值位置 t/T 与内层 else 键复用 T 槽，跳过（仅 force t 注册）。
                    # 例外：模块区无任何 cond else 键（force t）时，值位置 `t`
                    # 也要注册 T 槽（@lisp-env 实测 `(setq x (if c t))` 的 t
                    # 在模块区注册 SYMBOL T，nsyms 多 1）。tcond5 实测孤立顶层
                    # `T`（值位置）若位于 T 槽归属 form，同样注册。
                    # 有 force t 时：T 槽位置由外层 cond else 键（_t_reg_idx）
                    # 决定，值位置 t / 内层 else 键均复用该槽——此前值位置 t
                    # 在归属 form 按其 _rev 原位注册，会先于 else 键占槽
                    # （platform.lsp 实测 T 落在 `(strcase ... T)` 前、cht 前，
                    # CAD 在 else 键体 `chs` 之后）。
                    if isinstance(name, str) and name.lower() == 't':
                        if _has_force_t and not _i_is_t_form:
                            continue
                        if _has_force_t and j != _t_reg_idx:
                            continue
                        if _owner_of(name) != i and not _i_is_t_form:
                            continue
                        self.add('T', force=force)
                        continue
                    # 符号由"归属 form"独占登记，其它 form 引用不重复发槽
                    # （CAD p04：lang 属 form0 被放尾部，codepage 属 form3）。
                    if _owner_of(name) != i:
                        continue
                    if is_const_entry(name):
                        if name[1] in (('NIL',), ('T',)):
                            # NIL/T 由 PUSH_NIL/PUSH_T 内建编码，不占常量槽
                            # （CAD i18n golden 无 NIL/T 槽）。
                            continue
                        self.add(name, force=force)
                    elif name not in module_seen:
                        module_seen.add(name)
                        self.add(name, force=force)
        self.module_reg_func_count = module_funcs

    def _form_read_target(self, node, reads, targets, arg_names, in_quote=False):
        """收集 form 的 读(value)/setq目标(target) 符号集合（模块归属用）。"""
        if isinstance(node, InPackage):
            reads.add('in-package')
            reads.add(node.name)
        elif isinstance(node, Symbol):
            if node.name not in arg_names:
                reads.add(node.name)
        elif isinstance(node, Call):
            for a in node.args:
                self._form_read_target(a, reads, targets, arg_names, in_quote)
            if node.name not in self.func_names:
                # `command` 内建 SUBR 的**调用目标**以 `ads-cmd` 槽独立注册
                # （与值引用的 `COMMAND` 分离），read 归属同步用该名。
                reads.add("ads-cmd" if node.name == "command" else node.name)
        elif isinstance(node, Setq):
            for target, value in node.pairs:
                if value:
                    self._form_read_target(value, reads, targets, arg_names, in_quote)
                if isinstance(target, Symbol) and target.name not in arg_names:
                    targets.add(target.name)
                else:
                    self._form_read_target(target, reads, targets, arg_names, in_quote)
        elif isinstance(node, IfNode):
            for part in (node.cond, node.then, node.else_expr):
                if part:
                    self._form_read_target(part, reads, targets, arg_names, in_quote)
        elif isinstance(node, WhileNode):
            if node.cond:
                self._form_read_target(node.cond, reads, targets, arg_names, in_quote)
            for expr in node.body:
                self._form_read_target(expr, reads, targets, arg_names, in_quote)
        elif isinstance(node, Progn):
            for form in node.forms:
                self._form_read_target(form, reads, targets, arg_names, in_quote)
        elif isinstance(node, ForeachNode):
            for expr in node.body:
                self._form_read_target(expr, reads, targets, arg_names, in_quote)
            if node.list_expr:
                self._form_read_target(node.list_expr, reads, targets, arg_names, in_quote)
            if node.var is not None:
                self._form_read_target(node.var, reads, targets, arg_names, in_quote)
        elif isinstance(node, RepeatNode):
            for expr in node.body:
                self._form_read_target(expr, reads, targets, arg_names, in_quote)
            if node.count:
                self._form_read_target(node.count, reads, targets, arg_names, in_quote)
        elif isinstance(node, Integer):
            # 超 int32 整数字面量按 REAL 键收集（与 `_collect_byteorder` 一致，
            # base-function 顶层 `(setq @::*mktime-epoch* 2208988800)` CAD 实测）。
            if node.value > 2147483647 or node.value < -2147483648:
                reads.add('__real_%s__' % float(node.value))
        elif isinstance(node, Cond):
            for clause in node.clauses:
                for item in clause:
                    self._form_read_target(item, reads, targets, arg_names, in_quote)
        elif isinstance(node, ListExpr):
            for item in node.items:
                self._form_read_target(item, reads, targets, arg_names, in_quote)
        elif isinstance(node, QuotedExpr):
            if node.expr is not None:
                if isinstance(node.expr, Symbol) and node.expr.name not in ('T', 'nil'):
                    if node.expr.name not in arg_names:
                        reads.add(node.expr.name)
                elif to_const(node.expr) is not None:
                    reads.add((CONST_MARK, to_const(node.expr)))
                else:
                    self._form_read_target(node.expr, reads, targets, arg_names, True)
        elif isinstance(node, LambdaNode):
            if to_const(node) is not None:
                reads.add((CONST_MARK, to_const(node)))
            else:
                for expr in node.body:
                    self._form_read_target(expr, reads, targets, arg_names | set(node.args), in_quote)
        elif isinstance(node, String):
            reads.add('"' + node.value + '"')
        elif isinstance(node, Real):
            # 实数常量：模块注册域需归属到 form（`_register_module` 对无归属的
            # 符号跳过 → REAL 默认值槽缺失，config 类顶层调用 slot 错位）。
            # 键与 `_collect_byteorder`/symtab.add_real 一致（`__real_<v>__`）。
            reads.add('__real_%s__' % node.value)

    def _collect_byteorder(self, node, out, arg_names, in_quote=False, cur_locals=None, _is_tail=False):
        """按字节码首次引用序向前收集 (name, forced) 列表（单函数算法）。

        `_is_tail=True` 表示该表达式的值是函数返回值（尾/值上下文）——语句
        上下文（值被丢弃）progn 末 `T`/`nil` 的符号槽 CAD 不注册（permission
        `@::fetch-user-role` `(progn ... T)` 实测；checksum 函数返回 T 仍注册）。
        """
        if cur_locals is None:
            cur_locals = getattr(self, "_cur_locals", None)
        elif cur_locals is not None:
            self._cur_locals = cur_locals
        if isinstance(node, Symbol):
            _is_local = bool(cur_locals and node.name in cur_locals)
            if (
                node.name not in arg_names
                and not self._seen(out, node.name)
                and not (
                    # 其它函数的参数名（config/store `type`）与共享参数名
                    # （persist pkg-name）作普通符号引用时过滤——由参数拥有者
                    # 注册。仅当参数拥有者在逆序处理中**更晚**（源码序更前，
                    # `_param_first_source < 当前源码序`，base-function `x` =
                    # pair src12 拥有者 vs getf src13 引用）时过滤；kwote lambda
                    # 宿主处理更晚（string-split src1 vs strbytelen src9）时
                    # lambda 收集注册（CAD 在 string-split kwote 块内 fg[44]）。
                    # 当前函数局部（net/module `response-str`）放行。
                    node.name in getattr(self, "_all_params", set())
                    and not _is_local
                    and getattr(self, "_param_first_source", {}).get(node.name, 10**9)
                    < getattr(self, "_cur_source_idx", 10**9)
                )
                and not (node.name in self.shared and not _is_local)
            ):
                out.append((node.name, False))
        elif isinstance(node, InPackage):
            # `(in-package :@)` → `PUSH_VALUE :@; FUNC_REF in-package`：
            # 引用序 `:@` 先、`in-package` 后（CAD 模块代码实测）。
            if not self._seen(out, node.name):
                out.append((node.name, False))
            if not self._seen(out, 'in-package'):
                out.append(('in-package', False))
        elif isinstance(node, Call):
            if node.name == "command":
                # CAD 把 `(command a b ...)` 编译为每参数独立 `FUNC 1 <ads-cmd>`
                # 调用，符号收集序 = 每参数后紧跟 ads-cmd（net/wget `(command
                # "shell" (strcat ...))` 实测 forward = shell, ads-cmd, 其余；
                # 逆序注册 = 其余, ads-cmd, shell）。故 args[0] 后立即收 ads-cmd。
                for _ai, _a in enumerate(node.args):
                    self._collect_byteorder(_a, out, arg_names, in_quote)
                    if _ai == 0 and not self._seen(out, "ads-cmd"):
                        out.append(("ads-cmd", False))
                return
            for a in node.args:
                self._collect_byteorder(a, out, arg_names, in_quote)
            if node.name in ('and', 'or'):
                # CAD 短路 and/or：编译为 JMP16 指令，不注册符号槽
                # （i18n-cad 实测无 AND/OR 符号）。
                pass
            elif node.name in self.func_names:
                out.append((node.name, True))
            elif node.name == "command":
                # `command` 内建 SUBR 的**调用目标**注册为独立符号槽 `ads-cmd`
                # （base-function CAD 实测 `(command ...)` → `ads-cmd`），与值
                # 引用的普通符号槽 `COMMAND` 分离。codegen 调用处已 `get_or_add
                # ("ads-cmd")`，收集阶段同步改名避免槽位错位。
                if not self._seen(out, "ads-cmd"):
                    out.append(("ads-cmd", False))
            elif (
                node.name not in arg_names
                and (
                    node.name not in getattr(self, "_all_params", set())
                    or getattr(self, "_param_first_source", {}).get(node.name, 10**9)
                    >= getattr(self, "_cur_source_idx", 10**9)
                )
                and not self._seen(out, node.name)
            ):
                out.append((node.name, False))
        elif isinstance(node, Setq):
            for target, value in node.pairs:
                if value:
                    self._collect_byteorder(value, out, arg_names, in_quote)
                if isinstance(target, Symbol):
                    _is_local = bool(cur_locals and target.name in cur_locals)
                    if (
                        target.name not in arg_names
                        and not self._seen(out, target.name)
                        and not (
                            target.name in getattr(self, "_all_params", set())
                            and not _is_local
                            and getattr(self, "_param_first_source", {}).get(target.name, 10**9)
                            < getattr(self, "_cur_source_idx", 10**9)
                        )
                        and not (target.name in self.shared and not _is_local)
                    ):
                        out.append((target.name, False))
                else:
                    self._collect_byteorder(target, out, arg_names, in_quote)
        elif isinstance(node, IfNode):
            # quoted 数据里 `(if ...)` 的 `if` 是符号（CAD 收集 IF，
            # i18n-cad 实测 save-mt `'((if ...))` 收集 IF）；正常代码用条件指令不收集。
            if in_quote and not self._seen(out, 'if'):
                out.append(('if', False))
            if node.cond:
                self._collect_byteorder(node.cond, out, arg_names, in_quote, _is_tail=False)
            if node.then:
                # then/else 分支值 = if 的值（if 为尾/值上下文时分支亦为值）。
                self._collect_byteorder(node.then, out, arg_names, in_quote, _is_tail=_is_tail)
            if node.else_expr:
                self._collect_byteorder(node.else_expr, out, arg_names, in_quote, _is_tail=_is_tail)
        elif isinstance(node, WhileNode):
            if node.cond:
                self._collect_byteorder(node.cond, out, arg_names, in_quote)
            for expr in node.body:
                self._collect_byteorder(expr, out, arg_names, in_quote)
        elif isinstance(node, Progn):
            for _pi, form in enumerate(node.forms):
                _f_tail = _is_tail and (_pi == len(node.forms) - 1)
                if (
                    not _f_tail
                    and _pi == len(node.forms) - 1
                    and isinstance(form, Symbol)
                    and form.name.lower() in ("t", "nil")
                ):
                    # 语句上下文（值被丢弃）progn 末 `T`/`nil`：CAD 不注册符号槽
                    # （permission `@::fetch-user-role` `(progn ... T)` 实测；
                    # checksum 函数返回 T 走尾上下文仍注册）。
                    continue
                self._collect_byteorder(form, out, arg_names, in_quote, _is_tail=_f_tail)
        elif isinstance(node, ForeachNode):
            # CAD foreach/vlax-for 字节码：列表求值存局部槽 → loop 头 GET_LOCAL/JMP →
            # 体 SETQ_G <var>（循环变量先于体求值）→ 体各式。故符号引用序 =
            # list_expr → var → body（i18n-cad 实测 update-locale-all 组
            # [PKG, @::*PKG-IN-USE*, ...]：list 在 var 之前）。
            if node.list_expr:
                self._collect_byteorder(node.list_expr, out, arg_names, in_quote)
            if node.var is not None:
                # foreach 循环变量注册为符号槽（CAD t16_foreach 实测 X 槽、
                # @lisp_u `(foreach cmd '(...) ...)` 的 CMD 槽）。即使 var 名
                # 与共享参数同名（@lisp_u `cmd` 同时是 @::cmd2str 等函数参数）
                # 也独立注册——共享参数排除仅适用于**参数符号引用**，不适用于
                # foreach 循环变量（CAD 模块区 510 CMD + 函数体区共享参数槽并存）。
                # 但 var 名与**唯一参数**（cache.lsp `subdir` = cache-store 参数
                # + cache-clear-all foreach 变量）同名时不独立注册——CAD 复用
                # 参数拥有者槽（fg[46]，参数组），foreach 处无独立槽。
                _v = normalize_vla_name(node.var.name)
                if (
                    _v not in arg_names
                    and _v not in getattr(self, "_unique_params", set())
                    and not self._seen(out, _v)
                ):
                    out.append((_v, False))
            for expr in node.body:
                self._collect_byteorder(expr, out, arg_names, in_quote)
        elif isinstance(node, RepeatNode):
            for expr in node.body:
                self._collect_byteorder(expr, out, arg_names, in_quote)
            if node.count:
                self._collect_byteorder(node.count, out, arg_names, in_quote)
        elif isinstance(node, Cond):
            # CAD cond 字节码：测试体按源码序发出（各子句条件），结果体按源码
            # 倒序发出（末子句体最先）。符号引用序 = 测试正序 + 结果倒序
            # （t05_cond 实测：> < T zero positive negative）。
            clauses = [c for c in node.clauses if c]
            for clause in clauses:
                if clause:
                    cond = clause[0]
                    # cond 的 else 子句键 `(t ...)`/`(T ...)` 在 CAD 中注册一个真实
                    # SYMBOL T 槽（t05_cond golden 实测），需 force 强制注册。
                    # CAD weak_keywords 里 t 大小写不敏感，统一作 SYMBOL T。
                    if isinstance(cond, Symbol) and cond.name.lower() in ('t',):
                        # cond else 键 `(t ...)` 强制注册 SYMBOL T，但若函数体内
                        # 已有值位置 `t`（`(setq x t)`，reactor.lsp 实测）则跳过——
                        # 值位置 t 已注册 T 槽（_seen 命中），再 append 强制 t 会
                        # 产生两个 T（nsyms +1、T 槽提前到测试组前、后续槽错位）。
                        # CAD T 槽位置由**最后一个** `t` 引用决定（reactor CAD 实测
                        # IS-BRICSCAD @::PLATFORM-IS-LINUX-P T——T 在测试组后）。
                        if not self._seen(out, cond.name):
                            out.append((cond.name, True))
                    else:
                        self._collect_byteorder(cond, out, arg_names, in_quote)
            for clause in reversed(clauses):
                for item in clause[1:]:
                    self._collect_byteorder(item, out, arg_names, in_quote)
        elif isinstance(node, ListExpr):
            if node.items and isinstance(node.items[0], LambdaNode):
                # 立即应用 `((lambda ...) args)`：实参先求值（字节码序，dcl CAD
                # 实测 args 的 gensym 在 lambda 参数 dcl-str/dcl-name 之前），
                # 先收集 args、后收集 lambda 头（参数 + 体）。
                for _it in node.items[1:]:
                    self._collect_byteorder(_it, out, arg_names, in_quote)
                self._collect_byteorder(node.items[0], out, arg_names, in_quote)
            else:
                for item in node.items:
                    self._collect_byteorder(item, out, arg_names, in_quote)
        elif isinstance(node, LambdaNode):
            # 裸 lambda 值（`(setq *error* (lambda (msg) ...))`、函数返回
            # `(lambda (msg / fp) ...)`，CAD 编译为 `-lambda-` DEFUN）：参数
            # 注册符号槽 + 体符号收集（file-utils/update/menu/load 的
            # `*error*` 处理器实测）。forward 序 = 参数 → `/ 局部变量`
            # locals 常量 → locals → 体（load.lsp CAD 实测 `[MSG, (FP), FP,
            # body...]`，逆序注册 `[body, FP, (FP), MSG]`）。
            _lam_args = list(node.args)
            _lam_locals = []
            if "/" in _lam_args:
                _i = _lam_args.index("/")
                _lam_locals = _lam_args[_i + 1 :]
                _lam_args = _lam_args[:_i]
            for _a in _lam_args:
                # 共享参数（dcl `dcl-name` = dcl-run/dcl-run-with-setup 参数 +
                # dcl-dialog 立即 lambda 参数）也收集——`_shared_last` 按 kept
                # 逆序最后引用者（dcl-dialog idx 6）注册，owner args 循环跳过。
                # **参数拥有者逆序更晚处理**（`_param_first_source < 当前 source`，
                # safe-eval `fn` = safe-fn-in-list-p src3 参数 + safe-form-p src4
                # lambda 参数，owner 更晚 idx3）时**排除**——由 owner（_shared_last）
                # args 循环注册（CAD fn 在 safe-fn-in-list-p 组 fg[61]，非
                # safe-form-p 组）。
                _excluded = (
                    _a in getattr(self, "_all_params", set())
                    and getattr(self, "_param_first_source", {}).get(_a, 10**9)
                    < getattr(self, "_cur_source_idx", 10**9)
                )
                if (
                    _a not in arg_names
                    and not _excluded
                    and not self._seen(out, _a)
                ):
                    out.append((_a, False))
            if _lam_locals:
                _lc = ("LIST", tuple(("SYMBOL", l) for l in _lam_locals))
                if not self._seen(out, (CONST_MARK, _lc)):
                    out.append(((CONST_MARK, _lc), False))
                for _l in _lam_locals:
                    if not self._seen(out, _l):
                        out.append((_l, False))
            for _bi, _b in enumerate(node.body):
                self._collect_byteorder(
                    _b, out, arg_names, in_quote, _is_tail=(_bi == len(node.body) - 1)
                )
        elif isinstance(node, QuotedExpr):
            if node.kwote:
                # `(function ...)`：CAD kwote 机制（i18n-cad 实测）。
                # 仅 lambda 生成 `kwote` 符号（0x56 独立块）；`(function 符号)`
                # （如 `(mapcar (function car) ...)`、`(function @::pkg-fas-file)`，
                # cmd.lsp 实测）CAD **不**生成 kwote 标记——符号本身作为普通
                # SUBR 槽注册（CAD fg 里 kwote 槽只在 lambda kwote 块处，其余
                # 无 marker）。lambda 体照常收集符号（builtin 调用如 CONS/READ
                # 会注册），但不注册字面 `lambda` 符号、不按 quote 语义收集
                # `if` 等数据符号、参数（局部槽）由 arg_names 排除。
                if isinstance(node.expr, LambdaNode):
                    out.append(("kwote", False))
                    # `/ 局部变量` 不排除：局部变量照常从函数体收集注册
                    # （与 defun `/ locals` 同协议，_al-bind-alist 绑定符号槽），
                    # 否则 SETQ_G 引用未注册槽 → CAD 访问冲突。仅真参数排除。
                    _lambda_args = list(node.expr.args)
                    if "/" in _lambda_args:
                        _lambda_args = _lambda_args[: _lambda_args.index("/")]
                    lambda_args = set(_lambda_args)
                    # kwote lambda 的 `/ 局部变量` locals 常量 `(quote (locals...))`
                    # 需注册（codegen `_emit_al_bind_alist_locals` 会 add_constant），
                    # 否则 symtab 在 codegen 阶段插入新常量导致后续符号索引漂移
                    # （@lisp_u `(lambda (line / pos) ...)` 的 `(quote (pos))`
                    # 被推到 nsyms 外，_patch_usubr_idx const_map 找不到 → PUSH_G
                    # 越界 → CAD 0xC0000005）。常量结构与 codegen 一致
                    # （`('LIST', (('SYMBOL', loc)...))`）。
                    _lam_locals = []
                    if "/" in node.expr.args:
                        _lam_locals = node.expr.args[node.expr.args.index("/") + 1 :]
                    if _lam_locals:
                        # locals 常量先注册。`_al-bind-alist` 助手：仅当 kwote
                        # lambda locals == 外层函数 locals（net/proxy kwote
                        # lambda `/ shell exec stdout result` == 函数 locals，
                        # CAD `_al-bind-alist` 在 locals 之前、0x56 块在 const
                        # 前）时早注册；kwote lambda locals ≠ 函数 locals
                        # （command `@::F` kwote /req resp boot ≠ 函数 /ok req，
                        # CAD 实测 `const(req resp boot), VL-LOAD-COM,
                        # _al-bind-alist, const(ok req)`）则 `_al-bind-alist` 由
                        # 外层函数 locals 处理统一注册，不在此提前。
                        _lc = ("LIST", tuple(("SYMBOL", l) for l in _lam_locals))
                        if not self._seen(out, (CONST_MARK, _lc)):
                            out.append(((CONST_MARK, _lc), False))
                        if set(_lam_locals) == set(cur_locals or []):
                            if not self._seen(out, "_al-bind-alist"):
                                out.append(("_al-bind-alist", False))
                    # kwote lambda 参数：非 `_all_params` 排除（参数拥有者逆序
                    # 更晚处理，base-function `x` = pair 参数 src12 < getf src13
                    # 时由参数拥有者注册，lambda 不收集）的**可收集**参数在
                    # kwote 块**末尾**逆序注册（= forward 块开头、_rev 块末尾，
                    # persist e1/e2、browse X/LIBFILE、string-utils X 实测）。
                    # 逆序更晚的 kwote lambda 宿主（string-utils string-split
                    # src3 vs strbytelen src9）也收集（`_all_params` 条件排除
                    # + args 循环 `_param_lam_hosts` 延迟）。
                    def _lam_param_excluded(_p):
                        return (
                            _p in getattr(self, "_all_params", set())
                            and getattr(self, "_param_first_source", {}).get(_p, 10**9)
                            < getattr(self, "_cur_source_idx", 10**9)
                        )

                    _collectible = [
                        _p
                        for _p in _lambda_args
                        if _p not in arg_names
                        and _p not in self.shared
                        and not _lam_param_excluded(_p)
                    ]
                    _multi = bool(_collectible)
                    _body_args = arg_names | lambda_args if _multi else arg_names
                    if _multi:
                        for _p in _collectible:
                            if not self._seen(out, _p):
                                out.append((_p, False))
                    _kb = node.expr.body
                    for _bi, expr in enumerate(_kb):
                        self._collect_byteorder(
                            expr, out, _body_args, in_quote,
                            _is_tail=(_bi == len(_kb) - 1),
                        )
                    # kwote 块结束标记：CAD 注册序把 kwote 块（kwote + lambda 体）
                    # 保持收集序整体插到**调用者**（外层调用名）之后，不随其它
                    # 函数体符号逆序沉底（base-function getf / i18n load-mt 实测）。
                    out.append(("__kwote_end__", False))
                else:
                    # `(function 符号)`（cmd.lsp `(function car)` / `(function
                    # @::pkg-fas-file)` 实测）：不生成 kwote 块标记，符号本身
                    # 作为普通符号注册（CAD fg `@::*LOCAL-PKGS* CAR` 无 marker）。
                    self._collect_byteorder(node.expr, out, arg_names, in_quote)
            elif node.expr is not None:
                # CAD 引用单符号 `'a`：编译为 PUSH_G 普通符号槽，不注册
                # CONST（setcmp/setqa 实测 `(set 'a 5)` 的 A、`(setq x 'a)`
                # 的 A 均为普通 SYMBOL 槽）。仅列表/lambda/dotted 等复合
                # 结构才 const 化。
                if isinstance(node.expr, Symbol) and node.expr.name not in ('T', 'nil'):
                    # quoted vla- 符号同样规范化（base-function `(set
                    # 'vla-postcommand vla-sendcommand)` CAD 实测 `'vla-postcommand`
                    # → `vla-PostCommand` 符号槽）。
                    _n = normalize_vla_name(node.expr.name)
                    # 唯一参数名（非共享）被其它函数 quoted 引用时排除——由
                    # 参数拥有者注册（platform-api `'str` = @::platform-path
                    # 唯一参数，owner src0 < quoter src10，CAD 单槽 fg[120]
                    # 在 owner 组）。共享参数（cl-functions `str` = 4 函数
                    # 参数）quoted 引用照常收集（CAD 双槽 fg[64] body +
                    # fg[105] param）。**quoter 逆序处理更晚**（owner src >
                    # quoter src，file-utils `'STR` = path-win src3 参数 +
                    # parse-header src2 `(eq 'STR ...)`，CAD slot 60 在
                    # parse-header 组）时**收集**——槽注册在引用函数组、
                    # owner args 循环跳过（_quoted_param_collected）。
                    _is_other_param = (
                        _n in getattr(self, "_all_params", set())
                        and _n not in self.shared
                        and getattr(self, "_param_first_source", {}).get(_n, 10**9)
                        < getattr(self, "_cur_source_idx", 10**9)
                    )
                    if (
                        _n not in arg_names
                        and not _is_other_param
                        and not self._seen(out, _n)
                    ):
                        out.append((_n, False))
                        if (
                            _n.upper()
                            in {p.upper() for p in getattr(self, "_all_params", set())}
                            and _n.lower()
                            not in {s.lower() for s in getattr(self, "shared", set())}
                        ):
                            self._quoted_param_collected.add(_n)
                    elif _is_other_param and not arg_names:
                        # 唯一参数被**其它函数** quoted 引用（dcl `'STR` =
                        # @::dcl-escape 参数 + @::dcl-attrs-to-str
                        # `(eq 'STR (type ...))` 引用）：CAD 作 const 数据
                        # （quoted 单符号 `('SYMBOL','STR')` const 槽，slot
                        # 205 = `=` 而非 STR）——收集器排除 SYMBOL 槽后若
                        # codegen `_emit_quoted` 的 get_const_idx 找不到会
                        # get_or_add 注册独立 SYMBOL 槽 → 后续槽位错位。
                        # 注册 const 使 codegen 命中 const 槽（PUSH_G）。
                        _c = ("SYMBOL", _n)
                        if not self._seen(out, (CONST_MARK, _c)):
                            out.append(((CONST_MARK, _c), False))
                else:
                    const = to_const(node.expr)
                    if const is not None:
                        # quoted 数据 const 去重（保留**正序第一次**出现）：CAD
                        # cache.lsp 两处 `'("." "..")`（member subdir / member f）
                        # 只注册一个槽、位置在第一次（member 后）。逆序处理会
                        # 保留 refs 最后一个，需在此 _seen 去重。
                        if not self._seen(out, (CONST_MARK, const)):
                            out.append(((CONST_MARK, const), False))
                    else:
                        # 不可常量化的 quoted 表达式运行时拆开构建：其内部
                        # `(if ...)` 等特殊形式的 `if` 作为数据符号收集。
                        self._collect_byteorder(node.expr, out, arg_names, in_quote=True)
        elif isinstance(node, String):
            if not self._seen(out, '"' + node.value + '"'):
                out.append(('"' + node.value + '"', False))
        elif isinstance(node, Real):
            # 实数常量：CAD 注册为资源段 REAL 槽（字节码 PUSH_G 引用），符号
            # 收集随其它符号逆序注册（real/real_arith/real_list/real_param
            # CAD golden 实测 `[+, 2.5, 1.5]`——第二个实参 2.5 槽更小）。
            # 键与 codegen `symtab.add_real` 一致（`__real_<value>__`）。
            key = '__real_%s__' % node.value
            if not self._seen(out, key):
                out.append((key, False))
        elif isinstance(node, Integer):
            # 超出 int32 范围的整数字面量：codegen 按 REAL 编码/注册
            # （base-function 顶层 `(setq @::*mktime-epoch* 2208988800)` → 资源
            # 段 REAL 槽 `2208988800.0`，CAD 实测），此处按 REAL 键收集。
            if node.value > 2147483647 or node.value < -2147483648:
                key = '__real_%s__' % float(node.value)
                if not self._seen(out, key):
                    out.append((key, False))

    def _collect_forward(self, node, out, locals_):
        """深度优先收集符号 (name, forced) 列表。

        调用：函数名在前，参数按源码逆序展开。
        """
        if isinstance(node, Symbol):
            if node.name in self.shared or node.name in locals_:
                return
            if not self._seen(out, node.name):
                out.append((node.name, False))
        elif isinstance(node, Call):
            if node.name in self.func_names:
                out.append((node.name, True))
            elif node.name not in locals_ and not self._seen(out, node.name):
                out.append((node.name, False))
            for a in reversed(node.args):
                self._collect_forward(a, out, locals_)
        elif isinstance(node, Setq):
            for target, value in node.pairs:
                if value:
                    self._collect_forward(value, out, locals_)
                if isinstance(target, Symbol):
                    if target.name not in locals_ and not self._seen(out, target.name):
                        out.append((target.name, False))
                else:
                    self._collect_forward(target, out, locals_)
        elif isinstance(node, IfNode):
            if node.cond:
                self._collect_forward(node.cond, out, locals_)
            if node.then:
                self._collect_forward(node.then, out, locals_)
            if node.else_expr:
                self._collect_forward(node.else_expr, out, locals_)
        elif isinstance(node, WhileNode):
            out.append(("while", False))
            if node.cond:
                self._collect_forward(node.cond, out, locals_)
            for expr in node.body:
                self._collect_forward(expr, out, locals_)
        elif isinstance(node, Progn):
            for form in node.forms:
                self._collect_forward(form, out, locals_)
        elif isinstance(node, ForeachNode):
            out.append((node.name or "foreach", False))
            for expr in node.body:
                self._collect_forward(expr, out, locals_)
            if node.list_expr:
                self._collect_forward(node.list_expr, out, locals_)
            if node.var is not None:
                self._collect_forward(node.var, out, locals_)
        elif isinstance(node, RepeatNode):
            out.append(("repeat", False))
            for expr in node.body:
                self._collect_forward(expr, out, locals_)
            if node.count:
                self._collect_forward(node.count, out, locals_)
        elif isinstance(node, Cond):
            for clause in node.clauses:
                for item in clause:
                    self._collect_forward(item, out, locals_)
        elif isinstance(node, ListExpr):
            for item in node.items:
                self._collect_forward(item, out, locals_)
        elif isinstance(node, QuotedExpr):
            if node.expr is not None:
                # CAD 引用单符号 `'a`：普通符号槽（PUSH_G），非 CONST。
                if isinstance(node.expr, Symbol) and node.expr.name not in ('T', 'nil'):
                    if node.expr.name not in locals_ and not self._seen(out, node.expr.name):
                        out.append((node.expr.name, False))
                else:
                    const = to_const(node.expr)
                    if const is not None:
                        out.append(((CONST_MARK, const), False))
                    else:
                        self._collect_forward(node.expr, out, locals_)
        elif isinstance(node, LambdaNode):
            const = to_const(node)
            if const is not None:
                out.append(((CONST_MARK, const), False))
            else:
                out.append(("lambda", False))
                lambda_args = set(node.args)
                for expr in node.body:
                    self._collect_forward(expr, out, locals_ | lambda_args)
        elif isinstance(node, String):
            if not self._seen(out, '"' + node.value + '"'):
                out.append(('"' + node.value + '"', False))
        elif isinstance(node, Integer):
            # 超 int32 整数字面量：codegen 按 REAL 编码/注册，收集为 REAL 键
            # （base-function 顶层 `(setq @::*mktime-epoch* 2208988800)` → 资源
            # 段 REAL 槽，CAD 实测），此处与 `_collect_byteorder` 一致处理。
            if node.value > 2147483647 or node.value < -2147483648:
                key = '__real_%s__' % float(node.value)
                if not self._seen(out, key):
                    out.append((key, False))
        elif isinstance(node, Real):
            pass


def derive_symbol_names(program):
    """返回与 CAD 一致的符号槽顺序列表。

    字符串以 ``"value"`` 形式表示（含引号），符号为普通名字。
    """
    coll = CadSymbolCollector()
    coll.collect_program(program)
    return coll.names


def module_reg_count(program) -> int:
    """模块注册域符号数：函数名 + 顶层表达式符号。

    模块注册区宽 = n_funcs + top_level_count。由收集器 _register_module
    实际注册数推导，避免 `max(顶层符号槽)+1-n_funcs` 在顶层表达式引用
    函数体符号时的高估（atlisp_u 实际 844 = 502 函数 + 342 顶层符号）。
    """
    coll = CadSymbolCollector()
    coll.collect_program(program)
    return coll.module_reg_count


def module_reg_func_count(program) -> int:
    """模块注册域函数名数（模块尾块 defun 数）。

    CAD 只把模块代码引用的尾块函数名注册进模块注册段（atlisp_u = 48，
    i18n = 8），其余库函数名经函数体符号区注册。cli 用它传给
    resource_builder 的 module_func_count，截断模块注册块的函数名；
    codegen/top_level_count 仍按全部 defun 数（len(defun_forms)）计算。
    """
    coll = CadSymbolCollector()
    coll.collect_program(program)
    return coll.module_reg_func_count
