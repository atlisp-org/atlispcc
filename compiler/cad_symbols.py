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

# vlax- 属性/方法访问函数：第 2 个参数（args[1]）是 ActiveX 属性/方法名
# （quoted 单符号，如 `(vlax-get-property obj 'Item)` 的 'Item、`(vlax-invoke
# obj 'Method ...)` 的 'Method）。ActiveX 接口**大小写敏感**（t22_activex 实测），
# 属性名须保留大小写注册——不递归 quoted 分支（否则 `_is_other_param` 把
# `'Item` 误判为「参数 item 被 quoted 引用」→ deferred const `('SYMBOL','Item')`
# → 追加到 cl-* 组 → 多 ITEM 槽抢占 `=` 槽位，atlisp_u fg 2537）。
_VLAX_PROPERTY_FUNCS = frozenset({
    "vlax-get-property", "vlax-invoke", "vlax-put-property", "vlax-get",
})


# 无 get-/put-/call-/add-/insert- 子前缀的 vla- 方法名 → 标准 ActiveX
# CamelCase（base-function CAD 实测 `vla-sendcommand`→`vla-SendCommand`、
# `vla-postcommand`→`vla-PostCommand`）。未收录的走首字母大写 fallback。
_VLA_METHOD_MAP = {
    "vla-add": "vla-Add",
    "vla-add3dpoly": "vla-Add3DPoly",
    "vla-addarc": "vla-AddArc",
    "vla-addcircle": "vla-AddCircle",
    "vla-adddimension": "vla-AddDimension",
    "vla-addellipse": "vla-AddEllipse",
    "vla-addhatch": "vla-AddHatch",
    "vla-addline": "vla-AddLine",
    "vla-addmenuitem": "vla-AddMenuItem",
    "vla-addmtext": "vla-AddMText",
    "vla-addpolyline": "vla-AddPolyline",
    "vla-addrectangle": "vla-AddRectangle",
    "vla-addseparator": "vla-AddSeparator",
    "vla-addspline": "vla-AddSpline",
    "vla-addsubmenu": "vla-AddSubMenu",
    "vla-addtext": "vla-AddText",
    "vla-addtoolbarbutton": "vla-AddToolbarButton",
    "vla-appendinnerloop": "vla-AppendInnerLoop",
    "vla-appenditems": "vla-AppendItems",
    "vla-appendouterloop": "vla-AppendOuterLoop",
    "vla-attachtoolbartoflyout": "vla-AttachToolbarToFlyout",
    "vla-copyobjects": "vla-CopyObjects",
    "vla-delete": "vla-Delete",
    "vla-endundomark": "vla-EndUndoMark",
    "vla-getattributes": "vla-GetAttributes",
    "vla-getboundingbox": "vla-GetBoundingBox",
    "vla-getbulge": "vla-GetBulge",
    "vla-getinterfaceobject": "vla-GetInterfaceObject",
    "vla-insertblock": "vla-InsertBlock",
    "vla-insertinmenubar": "vla-InsertInMenuBar",
    "vla-intersectwith": "vla-IntersectWith",
    "vla-item": "vla-Item",
    "vla-load": "vla-Load",
    "vla-move": "vla-Move",
    "vla-offset": "vla-Offset",
    "vla-open": "vla-Open",
    "vla-postcommand": "vla-PostCommand",
    "vla-regen": "vla-Regen",
    "vla-removefrommenubar": "vla-RemoveFromMenuBar",
    "vla-rotate": "vla-Rotate",
    "vla-saveas": "vla-SaveAs",
    "vla-scaleentity": "vla-ScaleEntity",
    "vla-sendcommand": "vla-SendCommand",
    "vla-setalignment": "vla-SetAlignment",
    "vla-setbitmaps": "vla-SetBitmaps",
    "vla-setcolorbookcolor": "vla-SetColorBookColor",
    "vla-setfont": "vla-SetFont",
    "vla-settextheight": "vla-SetTextHeight",
    "vla-startundomark": "vla-StartUndoMark",
    "vla-transformby": "vla-TransformBy",
    "vla-update": "vla-Update",
    "vla-wblock": "vla-Wblock",
}

# vlax-* 及其他需保留 CamelCase 的特殊符号（lib golden 实测）。
# normalize_vla_name 通过此表规范化，_enc_sym 通过 _VLISP_CASE_PRESERVE 编码。
_SPECIAL_CASE_MAP = {
    "vlax-curve-getclosestpointto": "vlax-curve-getClosestPointTo",
    "vlax-curve-getclosestpointtoprojection": "vlax-curve-getClosestPointToProjection",
    "vlax-curve-getdistatparam": "vlax-curve-getDistAtParam",
    "vlax-curve-getdistatpoint": "vlax-curve-getDistAtPoint",
    "vlax-curve-getendparam": "vlax-curve-getEndParam",
    "vlax-curve-getendpoint": "vlax-curve-getEndPoint",
    "vlax-curve-getfirstderiv": "vlax-curve-getFirstDeriv",
    "vlax-curve-getparamatpoint": "vlax-curve-getParamAtPoint",
    "vlax-curve-getpointatdist": "vlax-curve-getPointAtDist",
    "vlax-curve-getpointatparam": "vlax-curve-getPointAtParam",
    "vlax-curve-getsecondderiv": "vlax-curve-getSecondDeriv",
    "vlax-curve-isclosed": "vlax-curve-isClosed",
    "vlax-dump-object": "vlax-dump-Object",
    "vlax-vbdouble": "vlax-vbDouble",
    "vlax-vbinteger": "vlax-vbInteger",
    "vlax-vblong": "vlax-vbLong",
    "vlax-vbobject": "vlax-vbObject",
    "vlax-vbstring": "vlax-vbString",
    "vlax-vbvariant": "vlax-vbVariant",
    ":vlr-commandcancelled": ":VLR-commandCancelled",
    ":vlr-commandended": ":VLR-commandEnded",
    ":vlr-commandfailed": ":VLR-commandFailed",
    ":vlr-commandwillstart": ":VLR-commandWillStart",
    "acallviewports": "acAllViewports",
    "acdatarow": "acDataRow",
    "acextendnone": "acExtendNone",
    "acheaderrow": "acHeaderRow",
    "actitlerow": "acTitleRow",
    "achatchpatterntypepredefined": "acHatchPatternTypePreDefined",
    "acmiddlecenter": "acMiddleCenter",
    "nextent": "nextent",
    "safearray": "safearray",
    "safearray-value": "safearray-value",
    "variant": "variant",
    "vla->e": "VLA->E",
}

# `vla-get-*`/`vla-put-*` 多词方法名 → CAD 规范 CamelCase（AutoCAD ActiveX
# 属性名；@lisp_u CAD golden 实测：modelspace→ModelSpace、insertionpoint→
# InsertionPoint、objectname→ObjectName、textstyles→TextStyles，而
# linetypes→Linetypes、viewports→Viewports 保持 CAD 原生写法）。键为小写
# 方法名（不含前缀），值含前缀的规范形式。
_VLA_GET_PROP_MAP = {
    "activedimstyle": "vla-get-ActiveDimStyle",
    "activedocument": "vla-get-ActiveDocument",
    "activelayer": "vla-get-ActiveLayer",
    "bigfontfile": "vla-get-BigFontFile",
    "colorindex": "vla-get-ColorIndex",
    "customscale": "vla-get-CustomScale",
    "dimstyles": "vla-get-DimStyles",
    "effectivename": "vla-get-EffectiveName",
    "elementname": "vla-get-ElementName",
    "endpoint": "vla-get-EndPoint",
    "entitycolor": "vla-get-EntityColor",
    "fontfile": "vla-get-FontFile",
    "graphicswinlayoutbackgrndcolor": "vla-get-GraphicsWinLayoutBackgrndColor",
    "helpstring": "vla-get-HelpString",
    "insertionpoint": "vla-get-InsertionPoint",
    "isxref": "vla-get-IsXRef",
    "layeron": "vla-get-LayerOn",
    "linetypes": "vla-get-Linetypes",
    "menubar": "vla-get-MenuBar",
    "menugroups": "vla-get-MenuGroups",
    "modelcrosshaircolor": "vla-get-ModelCrosshairColor",
    "modelspace": "vla-get-ModelSpace",
    "objectname": "vla-get-ObjectName",
    "paperspace": "vla-get-PaperSpace",
    "patternscale": "vla-get-PatternScale",
    "propertyname": "vla-get-PropertyName",
    "readonly": "vla-get-ReadOnly",
    "startpoint": "vla-get-StartPoint",
    "taborder": "vla-get-TabOrder",
    "tagstring": "vla-get-TagString",
    "textformat": "vla-get-TextFormat",
    "textheight": "vla-get-TextHeight",
    "textstring": "vla-get-TextString",
    "textstyles": "vla-get-TextStyles",
    "truecolor": "vla-get-TrueColor",
    "twistangle": "vla-get-TwistAngle",
    "viewports": "vla-get-Viewports",
    "xscalefactor": "vla-get-XScaleFactor",
    "yscalefactor": "vla-get-YScaleFactor",
    "zscalefactor": "vla-get-ZScaleFactor",
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
    # vlax-* 及其他特殊符号：按小写查规范 CamelCase 表
    mapped = _SPECIAL_CASE_MAP.get(name.lower())
    if mapped:
        return mapped
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
    """CAD 丢弃 defun 体中语句位置的裸字符串（docstring/分节注释）。

    开头的 docstring 与体中间的分节字符串编译时全部丢弃（不注册符号槽、
    不发射 PUSH_G）：
    - docstr.fas CAD 实测 strings 为空（开头 docstring）
    - base-function CAD 实测 handle-keywords 双 docstring 均不注册
    - dialog.lsp CAD 实测 @::edit-config 体中间 6 个分节字符串全部不注册
    仅体末 form（返回值位置）的字符串保留。只影响 defun 体顶层的
    裸 String，不影响 `(strcat "a" "b")` 等表达式内字符串。
    """
    body = list(body)
    if len(body) <= 1:
        return body
    return [x for i, x in enumerate(body) if i == len(body) - 1 or not isinstance(x, String)]


def to_const(node):
    """把引用的字面量节点规范化为常量结构元组；不可常量化的返回 None。

    CAD 把 ``'(lambda ...)`` 等引用字面量注册为资源段常量（值在加载期由
    资源流 BUILD_LIST 构建），字节码只发一条 ``PUSH_G``。结构与资源流
    记录一一对应：('SYMBOL', name) / ('INT', v) / ('REAL', v) /
    ('STRING', s) / ('LIST', (item, ...)) / ('NIL',) / ('T',)。
    """
    if isinstance(node, Symbol):
        if node.name.upper() == 'T':
            return ('T',)
        if node.name.lower() == 'nil':
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
        # 引用包装符号：`(quote X)` → QUOTE，`(function X)`/`#'X` → FUNCTION
        # （均含引用上下文内嵌套的写法）。CAD 分别注册对应符号叶子
        # （text/get-matrix `'(lambda ...)` 内层 `'(lambda ...)` → QUOTE；
        # setup.lsp kernel golden `'(... (function (lambda ...)) ...)` →
        # FUNCTION，实测）。kwote（运行时函数引用）在此前已返回 None。
        _wrap = node.wrap or ('function' if node.kwote else 'QUOTE')
        return ('LIST', (('SYMBOL', _wrap), inner))
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
            # dotted 引用 `'(a . b)`：CAD 以 `2a`(LIST_END) 收尾而非
            # `39 <count>`（t12_quote 实测），需标记以便 _emit_const 正确编码。
            # 但当 cdr 本身是列表时（如 `'(1 . (255 0 0))`），等价于平列表
            # `'(1 255 0 0)`，CAD 用 BUILD_LIST 编码（color/aci2rgb 实测）。
            if isinstance(d, tuple) and d[0] == 'LIST':
                items = items + d[1]
                return ('LIST', items)
            items = items + (d,)
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
        # `(defun-q name ...)`（parser Defun quoted=True）注册 DEFUN-Q 符号
        #（CAD setup 实测 fg DEFUN-Q），普通 defun 为 DEFUN。
        _kind = "defun-q" if getattr(node, "quoted", False) else "defun"
        return ('LIST', (('SYMBOL', _kind), ('SYMBOL', node.name),
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
        # 唯一参数被其它函数 quoted 引用的 const（dcl `'STR`）：延迟到资源序
        # 末尾注册（单函数路径也初始化，否则 _is_other_param 分支 AttributeError）。
        self._deferred_consts: list = []

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
        # 顶层 kwote lambda 调用实参（setup `(if @::*uris* (mapcar (function
        # (lambda (x) ...)) ...))` 实测）：CAD 把 lambda 体符号注册在源码位置
        # 的独立函数体组（check-pgp 组后、remove-path-in-trustedpaths 组前）。
        # 构造伪 Defun（body = lambda 体）插入 defuns 源码序，复用 _collect_multi
        # 的函数体收集/注册机制（参数过滤、外部函数 seen_refs 去重自然生效）。
        if len(defuns) > 1:
            _tl_pseudo = 0
            _di = 0
            for _fi, _f in enumerate(program.forms):
                if isinstance(_f, Defun):
                    _di += 1
                    continue
                for _lam in self._iter_kwote_lambdas(_f):
                    _la = list(getattr(_lam, "args", []) or [])
                    _loc = []
                    if "/" in _la:
                        _loc = _la[_la.index("/") + 1 :]
                        _la = _la[: _la.index("/")]
                    _tl_pseudo += 1
                    _pd = Defun(
                        name=f"__tl_lambda_{_tl_pseudo}__",
                        args=[_a for _a in _la if _a != "/"],
                        optional=[],
                        rest=None,
                        locals=_loc,
                        body=list(getattr(_lam, "body", []) or []),
                    )
                    defuns.insert(_di, _pd)
                    _di += 1
        # 参数使用统计：argname -> 使用它的函数数（共享参数判定）
        arg_usage: dict = {}
        # 嵌套 defun（函数体内 `(defun inner ...)`）的参数也计入——panel.lsp
        # @::panel-dialog-core 内嵌 run-function 的参数 `func` 与顶层
        # @::panel-after-exec 的参数 `func` 同名，CAD 共享同一符号槽
        # （golden fg[163]），嵌套 defun 参数须让 func 进入 shared 合并。
        def _count_nested(fnode):
            for _e in fnode.body:
                if isinstance(_e, Defun):
                    for _a in _e.args + list(getattr(_e, "optional", [])) + (
                        [getattr(_e, "rest")] if getattr(_e, "rest", None) else []
                    ):
                        arg_usage[_a] = arg_usage.get(_a, 0) + 1
                    _count_nested(_e)
        for f in defuns:
            for a in f.args:
                arg_usage[a] = arg_usage.get(a, 0) + 1
            _count_nested(f)
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
        # 被 foreach 循环变量引用的唯一参数（merged `@::confirm` `(foreach str
        # ...)` 的 str = @::parse-version-constraint 唯一参数）：CAD 把槽注册在
        # foreach 宿主组（宿主逆序处理比参数拥有者更晚——confirm rev 27 >
        # parse rev 6），args 循环据此跳过（与 `_param_lam_hosts` 同模式，
        # line 1030）。`_foreach_host_rev` = 参数名 → 引用它的 foreach 宿主
        # **最大逆序索引**（宿主比参数拥有者逆序更晚时由宿主注册）。
        self._foreach_var_refs: set = set()
        self._foreach_host_rev: dict = {}
        _n_fns = len(defuns)
        for _j, _f in enumerate(defuns):
            for _b in _f.body:
                self._scan_foreach_vars(_b, host_rev=_n_fns - 1 - _j)
        # let 绑定变量 → 逆序最后宿主 rev（atlisp_u `entry` = @::event-add-handler
        # src93 的 `(let ((entry ...)))` 变量 + @::log-write-file src152 参数）：
        # let 宿主源码更早（逆序更晚处理）时 CAD 由 let 宿主注册（fg[2110]），
        # `_local_is_param` 拦截（order=param）会让参数拥有者注册——宿主绕过。
        self._let_host_rev: dict = {}
        for _j, _f in enumerate(defuns):
            for _b in _f.body:
                self._scan_let_vars(_b, host_rev=_n_fns - 1 - _j)

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
        # 共享参数的逆序**最后声明拥有者**（args 声明序，与 `_collect_multi`
        # 的 `_shared_last` 一致）。嵌套块用它判定参数是否由**当前外层函数**
        # 的 args 循环注册（string-utils s2la `(str separator)` = 外层参数，
        # `separator` 的 last=6 == 外层 reversed 6；`str` 的 last=9 ≠ 6）。
        self._n_funcs = len(defuns)
        _shared_last_decl: dict = {}
        for _di, _df in enumerate(reversed(defuns)):
            for _da in _df.args:
                if _da in self.shared:
                    _shared_last_decl[_da] = max(_shared_last_decl.get(_da, -1), _di)
        self._shared_last_decl = _shared_last_decl
        # 共享参数 → 逆序最后**参数声明**者（供裸 lambda / kwote lambda 参数
        # 归属判定：CAD 把共享参数槽注册在参数拥有者 args 循环处，裸/kwote
        # lambda 宿主不重复收集——atlisp_u `msg` 由 cleanup-dcl 等 6 函数声明，
        # 裸 lambda `(lambda (msg) ...)` 宿主若抢先收集会占错槽）。
        self._shared_last = {}
        for _di, _df in enumerate(reversed(defuns)):
            for _da in _df.args:
                if _da in self.shared:
                    self._shared_last[_da] = max(self._shared_last.get(_da, -1), _di)

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
        # 唯一参数被其它函数 quoted 引用的 const（dcl `'STR`）：延迟到资源序
        # 末尾注册（kept_refs[-1] 末尾，reversed 注册最后）——CAD slot 227。
        self._deferred_consts: list = []

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
        # 预计算顶层 defun 的 locals 结构 → 逆序最后声明者（供 kwote lambda
        # locals 常量归属判定：kwote lambda 的 `(quote (locals))` 若与某顶层
        # defun 的 locals 结构相同，CAD 合并到顶层 defun 的 locals_last 位置，
        # 不在 kwote 块处注册——atlisp_u `@::load-error-handler` kwote lambda
        # `/ fp` 与 `@::platform-machineid-save` 等 6 个 defun 的 `('fp',)`
        # 共享，CAD 槽在 src 7 组（fg[2377]），CC 提前到 `@::load-error-handler`
        # 组（fg[677]）→ fg/seg0 错位）。键用 `('LIST', (('SYMBOL', l)...))`
        # 结构与 kwote 分支 `_lc` 一致。
        self._locals_last = {}
        for _li, _lf in enumerate(reversed(defuns)):
            if _lf.locals:
                self._locals_last[
                    ("LIST", tuple(("SYMBOL", l) for l in _lf.locals))
                ] = _li
        # 嵌套 defun 参数（`(defun @::pkg-deps-tree-rec (name depth))` 的
        # `depth`）→ 宿主外层函数逆序索引（`_count_nested` 已把它们并入
        # shared 但不在顶层 args，`_shared_last` 无值）。CAD 在宿主外层组
        # 注册（fg[611] DEPTH），注册循环据此限定注册位置。
        self._nested_param_host: dict = {}
        for _ni, _nf in enumerate(reversed(defuns)):
            for _nb in _nf.body:
                if isinstance(_nb, Defun):
                    for _na in _nb.args + list(getattr(_nb, "optional", [])) + (
                        [getattr(_nb, "rest")] if getattr(_nb, "rest", None) else []
                    ):
                        if _na in self.shared and _na not in getattr(
                            self, "_shared_last", {}
                        ):
                            # 逆序最大宿主（源码序最靠前的宿主外层函数）：
                            # CAD `depth` 槽在 `@::pkg-deps-tree`(rev 132)
                            # 而非 `@::pkg-reverse-deps-tree`(rev 131)。
                            self._nested_param_host[_na] = max(
                                self._nested_param_host.get(_na, -1), _ni
                            )
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

        # 延迟 const（唯一参数 quoted 引用）：追加到**第一个函数**的 kept
        # 末尾（zip(reversed(defuns), reversed(kept_refs)) 最后迭代 = 资源序
        # 末尾，CAD `'STR` slot 227）。
        if self._deferred_consts:
            kept_refs[0].extend(((CONST_MARK, _c), False) for _c in self._deferred_consts)

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
        _shared_last = self._shared_last
        # 共享参数在 body/quoted 引用（含大小写变体，file-utils `'STR` 引用
        # parse-header、参数声明 str 在 path-win/path-unix/path-os）时按
        # **逆序最后引用者**注册：kept 扫描大小写不敏感（与 `_ci_ref_key`
        # 一致），存入规范键（参数声明名）——否则 parse-header 的 `'STR` 不
        # 计入 → _shared_last['str']=7（path-win args）抢先占槽，CAD 在
        # parse-header 组 slot 60。
        _shared_ci = {str(s).upper(): s for s in self.shared}
        for _i, (_f, _k) in enumerate(zip(reversed(defuns), reversed(kept_refs))):
            # kept_refs 覆盖恢复为**所有引用者**（quoted 引用 `'STR` 也覆盖，
            # CAD 槽在引用者组——browse `@::funhelp` `(eq 'str ...)` 的 STR 槽
            # 在 funhelp 组 fg[117]）。但 **kwote lambda 参数**（`(lambda (msg)
            # ...)` 的 msg，`@::save-list-to-file` `*error*` 处理器）不覆盖——
            # 否则 `_shared_last['msg']` 被 kwote 宿主（rev 441）抢先，参数
            # 拥有者（cleanup-dcl rev 422）处不匹配 → `msg` 永不注册。kwote
            # 块内符号（`kwote` → `__kwote_end__` 之间）跳过。
            _in_kwote = False
            for _n, _ in _k:
                if isinstance(_n, str) and _n == "kwote":
                    _in_kwote = True
                    continue
                if isinstance(_n, str) and _n == "__kwote_end__":
                    _in_kwote = False
                    continue
                if _in_kwote:
                    continue
                if isinstance(_n, str) and _n.upper() in _shared_ci:
                    _canon = _shared_ci[_n.upper()]
                    _shared_last[_canon] = max(
                        _shared_last.get(_canon, -1), _i
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
                                # kwote lambda 是调用**首参**、调用者后续引用数据
                                # 参数（const，version `(vl-remove-if kwote '("base"
                                # ...))` 实测）时：CAD 把 const 注册在 kwote 块**之前**
                                # ——插入点推进到调用者后的 const 参数之后。
                                while (
                                    _j + 1 < len(_rev)
                                    and is_const_entry(_rev[_j + 1][0])
                                ):
                                    _j += 1
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
                _fh_rev = getattr(self, "_foreach_host_rev", {}).get(name, -1)
                _is_foreach_host = (
                    name in getattr(self, "_foreach_var_refs", set())
                    and _fh_rev >= 0
                )
                # 宿主是**逆序最后拥有者**（rev 大于所有局部/参数拥有者）时，
                # foreach 变量由宿主注册（merged_16 `item` = host 128 >
                # local 61/param 41）；否则（persist `pkg-info` = host 2 <
                # param 7 @::pkg）由 `_local_is_param` 原逻辑注册。
                _fh_is_last_owner = (
                    _is_foreach_host
                    and _fh_rev > _local_is_param_last.get(name, -1)
                    and _fh_rev > _param_is_param_last.get(name, -1)
                )
                if (
                    _fh_is_last_owner
                    and isinstance(name, str)
                    and name in _local_is_param
                    and name not in self.shared
                    and _fh_rev > i
                ):
                    # foreach 循环变量同时是局部+参数且**非共享**（merged_16
                    # `item` = @::handle-keywords foreach 宿主 rev128 +
                    # @::macro-subst 局部 rev61 + @::dcl-attr-p 参数 rev41）：
                    # CAD 把槽注册在**逆序最后宿主**（fg[702] @::handle-keywords
                    # 组）。宿主 rev 更大（宿主逆序更晚处理）时当前函数跳过，
                    # 由宿主注册；否则（宿主先处理已注册）当前函数正常走。
                    # 共享参数（`n` = 6 函数参数 + foreach 变量）走 `_shared_last`
                    # （@::sleep rev 121），不由宿主注册——故排除 shared。
                    continue
                if (
                    _fh_is_last_owner
                    and isinstance(name, str)
                    and name in _local_is_param
                    and name not in self.shared
                    and _fh_rev == i
                ):
                    # foreach 宿主（`_fh_rev == i`）且该符号是局部+参数混合
                    # 非共享、宿主是逆序最后拥有者：绕过 `_local_is_param`
                    # 拦截（否则宿主 i != 局部拥有者 last 被跳过 → item 落
                    # @::macro-subst 组而非 CAD 的 @::handle-keywords 组）。
                    pass
                elif isinstance(name, str) and name in _local_is_param:
                    if (
                        name in self.shared
                        and _shared_last.get(
                            next(
                                (s for s in self.shared if str(s).upper() == name.upper()),
                                name,
                            )
                        )
                        != i
                    ):
                        # 共享参数 + `_local_is_param`（atlisp_u `msg` = @::cleanup-dcl
                        # 等 6 函数参数 + @::voice-test 局部，`_shared_last` =
                        # @::error-handler rev416）：CAD 槽由 `_shared_last` 拥有者
                        # 注册，`_local_is_param`（order=param）会让参数拥有者
                        # 抢先注册——跳过（走 `_shared_last` 拦截，否则 msg 落
                        # @::cleanup-dcl 组而非 CAD 的 `_shared_last` 组）。
                        continue
                    if any(
                        str(name).upper() == x.upper()
                        for x in getattr(self, "_quoted_param_collected", set())
                    ):
                        # 唯一参数被其它函数 **quoted 引用**（merged_32 `'file`
                        # = @::cleanup-dcl `(eq 'file (type fp))` + @::save-list-
                        # to-file 参数 + @::cache-load 局部）：CAD 的 `'file`
                        # quoted 槽注册在引用函数组（@::cleanup-dcl fg[507]），
                        # 不由 `_local_is_param` 拥有者注册——绕过拦截（否则
                        # order=param 且引用者无 file 参数 → 跳过 → FILE 缺失）。
                        pass
                    elif getattr(self, "_let_host_rev", {}).get(name, -1) == i and name not in self.shared:
                        # let 绑定变量 + 参数/局部混合（atlisp_u `entry` =
                        # @::event-add-handler src93 的 `(let ((entry ...)))` 变量
                        # + @::log-write-file src152 参数）：let 宿主源码更早
                        # （逆序更晚处理）时 CAD 由 let 宿主注册（fg[2110]）——
                        # 绕过 `_local_is_param` 拦截（否则 order=param 且宿主
                        # 无该参数 → 跳过 → entry 落参数组 fg[1891]）。
                        pass
                    elif _shared_last.get(name) == i:
                        # 共享参数 + 嵌套 defun 参数（merged_32 `name` = 7 顶层
                        # 函数参数 + `@::pkg-deps-tree` 内嵌 `(defun
                        # @::pkg-deps-tree-rec (name depth))` 参数，`_shared_last`
                        # = 164 嵌套宿主）：CAD 把槽注册在嵌套宿主组（fg[858]），
                        # `_local_is_param`（order=param）会让参数拥有者注册——
                        # 绕过（否则宿主无 name 参数 → `name not in f.args`
                        # 跳过 → NAME 缺失）。
                        pass
                    else:
                        # 局部同时是其它函数参数：槽注册在**最后处理的拥有者**处。
                        # order="param"（参数拥有者后处理，net/probe `cached`）：
                        # 局部拥有者（name in f.locals）跳过，参数拥有者注册。
                        # order="local"（局部拥有者后处理，net/module
                        # `response-str` = load-module/fetch-module 局部 +
                        # cache-module-response/eval-module 参数）：参数拥有者
                        # （name not in f.locals）与**非最后**局部拥有者
                        # （i != _local_is_param_last）跳过，仅最后局部拥有者
                        # 注册（否则 @::load-module i=0 抢先占低位槽，CAD 在
                        # @::fetch-module i=4 组 fg[50]）。
                        _lo = _local_is_param_order.get(name)
                        if _lo == "param":
                            # order="param"：参数拥有者注册该槽。局部拥有者
                            # （name in f.locals）跳过；**非参数拥有者**（name
                            # not in f.args，如 foreach 循环变量引用，atlisp_u
                            # `@::save-pkg-lock-states` `(foreach pkg-name ...)`
                            # 的 pkg-name 既非参数也非局部）同样跳过——CAD 把
                            # pkg-name 注册在参数拥有者组（fg[1857]
                            # @::update-locale），foreach 处无独立槽。旧逻辑仅
                            # 跳过局部拥有者，foreach 变量引用漏过 → 提前注册
                            # 到 foreach 宿主组（fg[783]）→ fg/seg0 错位。
                            if name in f.locals or name not in f.args:
                                continue
                        else:
                            if name not in f.locals or i != _local_is_param_last.get(name):
                                continue
                if (
                    isinstance(name, str)
                    and name.upper()
                    in {str(s).upper() for s in self.shared}
                    and name not in _local_is_param
                    and _shared_last.get(
                        next(
                            (s for s in self.shared if str(s).upper() == name.upper()),
                            name,
                        )
                    )
                    is not None
                    and _shared_last.get(
                        next(
                            (s for s in self.shared if str(s).upper() == name.upper()),
                            name,
                        )
                    )
                    != i
                ):
                    # 共享参数名在 body/foreach 引用（persist pkg-name foreach 变量、
                    # cache subdir foreach 变量）：仅在逆序最后引用者（_shared_last）
                    # 处注册，先处理者跳过（否则抢先占低位槽）。_local_is_param
                    # 符号（局部+参数混合）由 _local_is_param_order/_last 决定
                    # 注册者，不走 _shared_last。
                    # 大小写不敏感：quoted `'SYM`（`@::to-string` `(eq 'SYM ...)`)
                    # 与共享参数 `sym`（cl::stringp 等）——`name in self.shared`
                    # 精确匹配失败 → `'SYM` 逃过拦截注册到引用组（to-string），
                    # 而 CAD 槽在 `_shared_last` 拥有者组（cl::stringp fg 末尾）。
                    continue
                if isinstance(name, str) and name == "_al-bind-alist" and f is not source_first_local:
                    # `_al-bind-alist` 全文件共享单槽（AGENTS：i18n-cad 实测仅 1 个），
                    # 由 source_first_local（源码序第一个 `/ locals` 函数，cl::find）
                    # 统一注册。kwote lambda locals == 函数 locals 时 body 收集会
                    # 引用 `_al-bind-alist`（line 2198-2200），但**非 source_first_local**
                    # 的函数（atlisp_u `@::proxy-running-p` kwote `/ shell exec stdout
                    # result`）不应重复注册——逆序先处理者抢先占槽（fg[1662]），
                    # 而 CAD 槽在 cl::find 组（fg[2524]）→ fg/seg0 错位。
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
                _lc_key = ('LIST', tuple(('SYMBOL', l) for l in f.locals))
                if getattr(self, "_locals_last", {}).get(_lc_key) == i:
                    self.add((CONST_MARK, _lc_key))
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
                _loc_fh_rev = getattr(self, "_foreach_host_rev", {}).get(loc, -1)
                if (
                    loc in getattr(self, "_foreach_var_refs", set())
                    and loc not in self.shared
                    and _loc_fh_rev > i
                    and _loc_fh_rev > _local_is_param_last.get(loc, -1)
                    and _loc_fh_rev > _param_is_param_last.get(loc, -1)
                ):
                    # 局部同时是 foreach 变量且宿主逆序更晚且为最后拥有者
                    # （merged_16 `item` = @::macro-subst 局部 rev61 +
                    # @::handle-keywords foreach 宿主 rev128）：CAD 把槽注册在
                    # 宿主组，局部拥有者跳过（否则 @::macro-subst order=local
                    # last 先注册 → 宿主 rev128 后处理复用 → item 落局部组
                    # 而非 CAD 宿主组）。共享参数（`n`）走 `_shared_last`，
                    # 不由宿主注册——排除。
                    continue
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
                    # 唯一参数被 foreach 变量引用且宿主逆序处理更晚（merged
                    # `@::confirm` `(foreach str ...)` = str 唯一参数
                    # @::parse-version-constraint rev6，宿主 confirm rev27 更晚）：
                    # CAD 把槽注册在 foreach 宿主组（merged_4 实测 STR fg[199]
                    # 在 confirm 组），args 循环跳过（否则 parse rev6 先处理
                    # 占位 → confirm rev27 复用 → STR 落到 parse 组 fg[75]
                    # 错位）。与 `_param_lam_hosts` 同模式。cache `subdir` 宿主
                    # rev < 参数 rev 时不跳过（参数拥有者注册，AGENTS 实测）。
                    if getattr(self, "_foreach_host_rev", {}).get(arg, -1) > i:
                        continue
                    # 参数同时是**逆序更晚处理**的 let 绑定变量（atlisp_u `entry`
                    # = @::log-write-file 参数 + @::event-add-handler 的
                    # `(let ((entry ...)))` 变量，let 宿主 i=412 > 参数 i=353）：
                    # CAD 由 let 宿主注册（fg[2110]），args 循环跳过（否则参数
                    # 拥有者先注册 → entry 落参数组 fg[1891]）。
                    if getattr(self, "_let_host_rev", {}).get(arg, -1) > i:
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

    def _scan_foreach_vars(self, node, host_rev=None):
        """递归收集函数体内 foreach/vlax-for 循环变量名 → `_foreach_var_refs`。

        唯一参数被 foreach 变量引用且宿主逆序处理更晚（merged `@::confirm`
        `(foreach str ...)`，confirm rev 27 > parse rev 6）时，CAD 把槽注册在
        foreach 宿主组——args 循环须跳过（line 1030），否则参数拥有者先注册
        占位、宿主复用 → 槽落参数组。`host_rev` = 宿主函数逆序索引。
        """
        from compiler.ast_nodes import (
            ForeachNode as _F,
            IfNode as _I,
            Progn as _P,
            WhileNode as _W,
            RepeatNode as _R,
            Cond as _Cnd,
            Setq as _S,
            ListExpr as _LE,
            Call as _C,
        )
        if isinstance(node, _F):
            if node.var is not None:
                _vn = node.var.name if hasattr(node.var, "name") else str(node.var)
                self._foreach_var_refs.add(_vn)
                if host_rev is not None:
                    self._foreach_host_rev[_vn] = max(
                        self._foreach_host_rev.get(_vn, -1), host_rev
                    )
            if node.list_expr:
                self._scan_foreach_vars(node.list_expr, host_rev=host_rev)
            for _b in node.body:
                self._scan_foreach_vars(_b, host_rev=host_rev)
        elif isinstance(node, _I):
            for _p in (node.cond, node.then, node.else_expr):
                if _p:
                    self._scan_foreach_vars(_p, host_rev=host_rev)
        elif isinstance(node, _P):
            for _f in node.forms:
                self._scan_foreach_vars(_f, host_rev=host_rev)
        elif isinstance(node, (_W, _R)):
            if getattr(node, "count", None):
                self._scan_foreach_vars(node.count, host_rev=host_rev)
            for _b in node.body:
                self._scan_foreach_vars(_b, host_rev=host_rev)
        elif isinstance(node, _Cnd):
            for _cl in node.clauses:
                for _it in _cl[1:]:
                    self._scan_foreach_vars(_it, host_rev=host_rev)
        elif isinstance(node, _S):
            for _t, _v in node.pairs:
                if _v:
                    self._scan_foreach_vars(_v, host_rev=host_rev)
        elif isinstance(node, _LE):
            for _i in node.items:
                self._scan_foreach_vars(_i, host_rev=host_rev)
        elif isinstance(node, _C):
            for _a in getattr(node, "args", []) or []:
                self._scan_foreach_vars(_a, host_rev=host_rev)

    def _scan_let_vars(self, node, host_rev=None):
        """递归收集函数体内 let 绑定变量名 → `_let_host_rev`（变量 → 逆序最后
        宿主 rev）。let 变量同时是其它函数参数（atlisp_u `entry` = @::event-add-
        handler 的 `(let ((entry ...)))` 变量 + @::log-write-file 参数）且 let
        宿主源码更早（逆序更晚处理）时，CAD 由 let 宿主注册——`_local_is_param`
        拦截须绕过（否则 order=param 且宿主无该参数 → 跳过 → entry 落参数组）。
        """
        from compiler.ast_nodes import (
            IfNode as _I,
            Progn as _P,
            WhileNode as _W,
            RepeatNode as _R,
            Cond as _Cnd,
            Setq as _S,
            ListExpr as _LE,
            Call as _C,
            LambdaNode as _LN,
            QuotedExpr as _Q,
        )
        if isinstance(node, _C) and node.name == "let" and node.args:
            _bind = node.args[0]
            if isinstance(_bind, _LE):
                for _b1 in _bind.items:
                    if isinstance(_b1, _S):
                        _vn = _b1.pairs[0][0].name if _b1.pairs and isinstance(_b1.pairs[0][0], Symbol) else None
                    elif isinstance(_b1, _C):
                        _vn = _b1.name
                    elif isinstance(_b1, Symbol):
                        _vn = _b1.name
                    else:
                        _vn = None
                    if _vn and host_rev is not None:
                        self._let_host_rev[_vn] = max(
                            self._let_host_rev.get(_vn, -1), host_rev
                        )
            for _b in node.args[1:]:
                self._scan_let_vars(_b, host_rev=host_rev)
        elif isinstance(node, _I):
            for _p in (getattr(node, "cond", None), getattr(node, "then", None), getattr(node, "else_expr", None)):
                if _p:
                    self._scan_let_vars(_p, host_rev=host_rev)
        elif isinstance(node, _P):
            for _f in node.forms:
                self._scan_let_vars(_f, host_rev=host_rev)
        elif isinstance(node, (_W, _R)):
            if getattr(node, "count", None):
                self._scan_let_vars(node.count, host_rev=host_rev)
            for _b in node.body:
                self._scan_let_vars(_b, host_rev=host_rev)
        elif isinstance(node, _Cnd):
            for _cl in node.clauses:
                for _it in _cl[1:]:
                    self._scan_let_vars(_it, host_rev=host_rev)
        elif isinstance(node, _S):
            for _t, _v in node.pairs:
                if _v:
                    self._scan_let_vars(_v, host_rev=host_rev)
        elif isinstance(node, _LE):
            for _i in node.items:
                self._scan_let_vars(_i, host_rev=host_rev)
        elif isinstance(node, _LN):
            for _b in getattr(node, "body", []) or []:
                self._scan_let_vars(_b, host_rev=host_rev)
        elif isinstance(node, _Q):
            if getattr(node, "expr", None):
                self._scan_let_vars(node.expr, host_rev=host_rev)
        elif isinstance(node, _C):
            for _a in getattr(node, "args", []) or []:
                self._scan_let_vars(_a, host_rev=host_rev)

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

        def _top_lam_of(form):
            """从顶层 `(set/setq 'sym (lambda ...))` form 提取 lambda 节点。"""
            if isinstance(form, Setq):
                for _t, _v in form.pairs:
                    if isinstance(_v, _LN) or (isinstance(_v, _Q) and isinstance(_v.expr, _LN)):
                        return _v if isinstance(_v, _LN) else _v.expr
            elif isinstance(form, Call) and form.name == "set" and len(form.args) == 2:
                _v1 = form.args[1]
                if isinstance(_v1, _LN) or (isinstance(_v1, _Q) and isinstance(_v1.expr, _LN)):
                    return _v1 if isinstance(_v1, _LN) else _v1.expr
            return None

        # 预扫描：收集第二区所有顶层 lambda 的**真实参数**（`/` 后局部变量不算），
        # 计算跨 lambda 共享参数集。CAD 把共享参数名推迟到第二区**最末尾**注册
        # （bootstrap_cad.fas 实测：fasext/vlx 两个 `(lambda (file) ...)` 共享
        # `file`，gold 第二区符号块 `... .fas STRCAT @::*FASEXT* FILE`——FILE 在
        # 全部体符号 + 尾调用之后）。仅**纯顶层**（无 defun）文件走此处理
        # （net/wget/setq-lambda.lsp）；混合文件（platform 等，有 defun）的顶层
        # setq-lambda 是引用数据，其体符号已在模块注册段，不在此重复处理。
        _top_lam_forms = []
        if _has_top_lam and not defuns:
            for form in reversed(others):
                _lam = _top_lam_of(form)
                if _lam is not None:
                    _top_lam_forms.append(_lam)
        _param_counts = {}
        for _lam in _top_lam_forms:
            _lam_params = _lam.args
            if "/" in _lam_params:
                _lam_params = _lam_params[: _lam_params.index("/")]
            for _arg in _lam_params:
                _k = normalize_vla_name(str(_arg))
                _param_counts[_k] = _param_counts.get(_k, 0) + 1
        _shared_params = {k for k, c in _param_counts.items() if c >= 2}
        _deferred_params = []  # 共享参数按首次出现序推迟注册

        _lam_seen = set()  # 3b 内部去重：跨 lambda 的重复符号（strcat）只注册一次
        for form in reversed(others) if (_has_top_lam and not defuns) else ():
            _lam = _top_lam_of(form)
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
                _ak = normalize_vla_name(str(arg))
                if _ak in _shared_params:
                    # 跨 lambda 共享参数：推迟到第二区末尾注册（bootstrap 共享
                    # `file` CAD 实测在 STRCAT @::*FASEXT* 之后）。
                    if _ak not in _deferred_params:
                        _deferred_params.append(_ak)
                    continue
                if arg not in self._name_set:
                    self.add(arg)
            # 最后调用名（strcat，跨 lambda 去重）。
            if _tail_call is not None and _tail_call not in _lam_seen:
                _lam_seen.add(_tail_call)
                self.add(_tail_call, force=True)
        # 共享参数：第二区最末尾注册（bootstrap 共享 `file` → FILE 槽）。
        for _ak in _deferred_params:
            self.add(_ak)        #    递归函数名：多次自身调用共享同一个重复槽（t03 递归两次仅 1 个重复
        #    FIB 槽；fact 递归一次 1 个重复槽）。
        for f in reversed(defuns):
            all_args = f.args + f.optional + ([f.rest] if f.rest else [])
            arg_names = set(all_args)
            refs = _SeenList()
            _body_forms = strip_docstring(f.body)
            for _i, expr in enumerate(_body_forms):
                # 末 body form 是函数返回值（尾上下文）：值位置 T/值符号按尾
                # 上下文收集（activelayer `(if ... (progn ... t) nil)` 返回
                # `t`，CAD golden 把 T 注册在函数体符号最前；非尾时该 T 被
                # progn 末 T 省略规则跳过，反被 codegen 资源构建补到末尾错槽）。
                self._collect_byteorder(
                    expr, refs, arg_names, cur_locals=set(f.locals),
                    _is_tail=(_i == len(_body_forms) - 1),
                )
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
            self._collect_byteorder(_f, _fr, set(), module_ctx=True)
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
        self._module_ctx = True
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
                self._collect_byteorder(form, form_refs, set(), module_ctx=True)
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
                        elif isinstance(name, str) and name in self.func_names:
                            # 用户函数在**模块代码**（顶层 form）被调用，且其
                            # defun 归属**不是**该调用 form（即 defun 在调用
                            # 之前已注册，或 defun 在模块尾块之外）时，调用
                            # form 是最早引用者 → CAD 把函数名注册在调用者
                            # 位置（atlisp_u `@::alert` defun@387、调用 form1，
                            # CAD rg[1027] 在调用者组；p04 `@::codepage2lang`
                            # defun@1、调用 form4，owner=defun → 此分支跳过）。
                            if _owner_of(name) == i:
                                module_seen.add(name)
                                self.add(name, force=False)
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
                        # T-form 自身**有** force-t（cond else 键）时，值位置 t
                        # 复用其槽（j != _t_reg_idx 跳过）；T-form 是**裸值 T**
                        # （无 force-t，_t_reg_idx=-1，atlisp_u 末尾 `T` 顶层
                        # form）时不能跳过——否则模块区无 T 槽、模块代码返回
                        # 值 PUSH_VALUE 引用越界（CAD 实测 T 在模块区 rg[876]，
                        # 旧逻辑跳过 → PUSH_VALUE 3531 → CAD 拒绝加载）。
                        if _has_force_t and _t_reg_idx >= 0 and j != _t_reg_idx:
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
        self._module_ctx = False
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
            # 顶层 setq-lambda 绑定（`(set/setq 'sym (lambda ...))`）：
            # CAD 按 `-lambda-` SUBR 机制处理，**不**注册 kwote 标记、lambda
            # 体符号也不进模块注册段（体符号走第二区 `-lambda-` 收集）。
            # atlisp_u `(set '@::wget (function (lambda ...)))` 若走 kwote 分支
            # 会把 kwote 归属到该 form（rg[545]），而 CAD kwote 在 mapcar 调用
            # form 组（rg[454]）。`_skip_lam_bodies=True` 的纯顶层路径已跳过，
            # 混合文件（atlisp_u）同样须跳过。
            from compiler.ast_nodes import LambdaNode as _FRT_LN
            _is_set_lam = (
                node.name == "set"
                and len(node.args) == 2
                and isinstance(node.args[1], QuotedExpr)
                and isinstance(node.args[1].expr, _FRT_LN)
            )
            if _is_set_lam:
                reads.add("set")
                _t0 = node.args[0]
                if isinstance(_t0, QuotedExpr) and isinstance(_t0.expr, Symbol):
                    targets.add(_t0.expr.name)
                # 参数/体符号不在此收集（`-lambda-` 第二区单独处理）
            else:
                for a in node.args:
                    if isinstance(a, QuotedExpr) and a.kwote and isinstance(a.expr, LambdaNode):
                        # 调用参数的 kwote lambda（`(mapcar (function (lambda ...))
                        # @::*uris*)`，setup 模块注册段实测 slot[7]=kwote）——
                        # 注册 `kwote` 标记符号。
                        if "kwote" not in reads:
                            reads.add("kwote")
                        self._form_read_target(a.expr, reads, targets, arg_names, in_quote)
                    else:
                        self._form_read_target(a, reads, targets, arg_names, in_quote)
                if node.name not in self.func_names:
                    # `command` 内建 SUBR 的**调用目标**以 `ads-cmd` 槽独立注册
                    # （与值引用的 `COMMAND` 分离），read 归属同步用该名。
                    reads.add("ads-cmd" if node.name == "command" else node.name)
                else:
                    # 用户函数调用：顶层 form 调用用户函数时，函数名也计入该 form
                    # 的 reads——模块归属取**最早引用**（read 或 target）的 form。
                    # atlisp_u `@::alert` 被 form1（顶层 progn）调用、defun 在
                    # form387 → CAD 槽注册在调用者 form1 组（rg[1027]），而非
                    # defun 组；p04 `@::codepage2lang` defun 在 form1、调用在
                    # form3 → 仍归 defun（min owner = form1）。不登记则唯一归
                    # defun，`@::alert` 错位到 form387 组。
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

    def _collect_byteorder(self, node, out, arg_names, in_quote=False, cur_locals=None, _is_tail=False,
                           module_ctx=False):
        """按字节码首次引用序向前收集 (name, forced) 列表（单函数算法）。

        ``module_ctx`` 仅入口调用方传入；递归子调用统一用
        ``self._module_ctx``（在 `_register_module` 期间置位，否则 False）。

        `_is_tail=True` 表示该表达式的值是函数返回值（尾/值上下文）——语句
        上下文（值被丢弃）progn 末 `T`/`nil` 的符号槽 CAD 不注册（permission
        `@::fetch-user-role` `(progn ... T)` 实测；checksum 函数返回 T 仍注册）。
        `module_ctx=True` 表示在模块注册域（顶层 form）收集——quoted 单符号
        若与某函数参数同名（atlisp_u `'int`/`'bool`/`'str` 类型实参 vs
        `@::ash` 的参数 `int`）**不**走 `_is_other_param` 参数延迟（CAD 把顶层
        define-config-typed 的 `'int` 类型注册进模块区，延迟到函数体区 → 模块
        代码 PUSH_G 引用越界 → CAD 拒绝加载）。
        """
        if not module_ctx:
            module_ctx = bool(getattr(self, "_module_ctx", False))
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
            if node.name == "let" and node.args:
                # CAD 原生 LET（event-bus golden 实测，前向符号序）：
                # 绑定值 args → 绑定值 name → 绑定变量 → body → LIST → LET
                # （fg 表 `LET LIST SUBST CONS CDR ENTRY ASSOC *EVENTS*` =
                # reversed：*EVENTS* ASSOC ENTRY CDR CONS SUBST LIST LET）。
                # 绑定变量是符号槽（body PUSH_VALUE 读取，非函数调用——parser
                # 把 `(v e)` 绑定对解析为 Call(name=v)）。
                bindings = node.args[0]
                if isinstance(bindings, ListExpr):
                    # 绑定变量收集顺序：**bare 符号变量（无初值，如 `(let ((x v)
                    # y z) ...)` 的 y/z）先于**值绑定**（`(x v)` 的 v 值 + x）。
                    # CAD nlp.lsp @::cmd-match-web 实测：forward = [expr, pkg-to-ins,
                    # input, @::get-cmd-from-web, lst-cmd, ...]，reversed 后
                    # @::GET-CMD-FROM-WEB 在 PKG-TO-INS 前（slot 55/56）。旧实现
                    # 逐绑定值先收 → reversed 后 pkg-to-ins 提前错位。event-bus
                    # 单值绑定不受影响。
                    for _b1 in bindings.items:
                        if isinstance(_b1, Symbol):
                            _v1 = _b1.name
                            if _v1 not in arg_names and not self._seen(out, _v1):
                                if _v1 in getattr(self, "_all_params", set()):
                                    continue
                                out.append((_v1, False))
                    for b in bindings.items:
                        if isinstance(b, Call) and b.args:
                            self._collect_byteorder(b.args[0], out, arg_names, in_quote)
                            v = b.name
                        elif isinstance(b, ListExpr) and b.items:
                            if len(b.items) > 1:
                                self._collect_byteorder(b.items[1], out, arg_names, in_quote)
                            v = b.items[0].name if isinstance(b.items[0], Symbol) else str(b.items[0])
                        else:
                            continue
                        if v not in arg_names and not self._seen(out, v):
                            # let 绑定变量是符号槽，但若它是**其它函数**的参数
                            # （nlp.lsp `expr` = @::ensure-str 参数 + 多个
                            # @::cmd-match-* 的 let 变量），CAD 注册在参数拥有者
                            # 处（EXPR@149），let 组不注册（否则提前到 let 组、
                            # CAD 槽错位）。**例外**：let 宿主源码**更早**（entry
                            # = @::event-add-handler src93 的 let 变量，参数
                            # @::log-write-file src152 更晚源码 → 逆序更晚处理）
                            # 时 CAD 由 let 宿主注册（fg[2110]），收集——否则
                            # 参数拥有者先注册 → entry 落参数组（CC fg[1891]
                            # 而非 CAD fg[2110]）。
                            if (
                                v in getattr(self, "_all_params", set())
                                and getattr(self, "_param_first_source", {}).get(v, 10**9)
                                < getattr(self, "_cur_source_idx", 10**9)
                            ):
                                continue
                            out.append((v, False))
                _lb = node.args[1:]
                for _bi, form in enumerate(_lb):
                    # let 体末 form 是 let 的返回值 = 函数返回值（`_is_tail`
                    # 传播）：`(let ((expr ...)) (if expr (progn ... t)))` 的
                    # 尾 `t` 在值上下文须注册（nlp.lsp CAD T@67；旧实现不传播
                    # → `(progn ... t)` 尾 T 被 `_last_const_stmt` 跳过 → T
                    # 槽缺失、后续槽整体偏移 1）。
                    _f_tail = _is_tail and (_bi == len(_lb) - 1)
                    self._collect_byteorder(form, out, arg_names, in_quote, _is_tail=_f_tail)
                if not self._seen(out, "list"):
                    out.append(("list", False))
                if not self._seen(out, "let"):
                    out.append(("let", False))
                return
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
            if node.name in _VLAX_PROPERTY_FUNCS and len(node.args) > 1:
                # ActiveX 属性/方法名（`vlax-get-property obj 'Item` 的 'Item、
                # `vlax-invoke obj 'Method ...` 的 'Method）：quoted 单符号
                # **保留大小写**（ActiveX 接口大小写敏感，t22_activex 实测）。
                # 直接收集（不递归 quoted 分支）——否则 `_is_other_param` 把
                # `'Item` 误判为「参数 item 被 quoted 引用」→ 注册 deferred
                # const `('SYMBOL','Item')` → 追加到 cl-* 组 → 多 ITEM 槽
                # （atlisp_u fg 2537 抢占 `=` 槽位，_patch_usubr_idx 138 条
                # 指令错编址）。属性名经 `_ci_ref_key` 与同名普通符号合并
                # （CAD 的 'Item 在 @::macro-subst 组 ITEM 槽）。
                for _ai, _a in enumerate(node.args):
                    if (
                        _ai == 1
                        and isinstance(_a, QuotedExpr)
                        and isinstance(_a.expr, Symbol)
                    ):
                        _ap = _a.expr.name
                        # 属性名与**本函数参数同名**（regexp-match/regexp-replace
                        # `(defun ... (str pattern) ... (vlax-put-property reg
                        # 'pattern pattern) ...)`：'pattern 既是 ActiveX 属性名
                        # 又是实参 pattern）时**不在此收集**——参数由拥有者
                        # args 循环注册在参数组（CAD golden PATTERN 在表末参数
                        # 组，此前在此收集使槽位提前到函数体组、后续槽错位）。
                        # 属性名经 `_ci_ref_key` 与同名参数/普通符号合并，由
                        # 参数组那条注册（保留唯一槽）。
                        if _ap in arg_names:
                            continue
                        if not self._seen(out, _ap):
                            out.append((_ap, False))
                    else:
                        self._collect_byteorder(_a, out, arg_names, in_quote)
            else:
                for a in node.args:
                    self._collect_byteorder(a, out, arg_names, in_quote)
            if node.name.lower() in ('and', 'or'):
                # CAD 短路 and/or：编译为 COND_AND/COND_OR 指令，不注册符号槽
                # （i18n-cad 实测无 AND/OR 符号；符号名大小写不敏感，AND/OR 同）。
                pass
            elif node.name in self.func_names:
                # 同函数内对同一函数符号的多次引用（quoted `'bar` + 调用
                # `(bar)`，probe1-5 CAD 实测）仅保留**首次出现**位置的槽——
                # 后续引用（含强制调用）复用首槽。旧实现强制调用无条件
                # append 绕过 _seen，quoted 在前时产生双槽（error/handler
                # `(boundp '@::*error*) ... (@::*error* msg)` OURS 双
                # @::*ERROR* 槽 vs CAD 单槽）。首现非强制条目注册时经
                # `_module_reg_upper` 提升 force，重复槽照常生成。
                if not self._seen(out, node.name):
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
                    module_ctx
                    or node.name not in getattr(self, "_all_params", set())
                    or getattr(self, "_param_first_source", {}).get(node.name, 10**9)
                    >= getattr(self, "_cur_source_idx", 10**9)
                )
                and not self._seen(out, node.name)
            ):
                out.append((node.name, False))
        elif isinstance(node, Defun):
            # 函数体内嵌套 `(defun inner ...)`（CAD 原生内嵌 DEFUN，n1-n6 实测）：
            # 嵌套函数符号块按「参数逆序 → locals 常量 → _al-bind-alist →
            # 体符号逆序 → 函数名」追加到 forward out——外层 `_collect_single`/
            # `_collect_multi` 整体逆序注册后，该块落在外层体符号**最前**，
            # 顺序为「函数名 → 体符号正向 → _al-bind-alist → locals 常量 →
            # 参数」（n2 CAD 实测 `N2-INNER Z + _al-bind-alist Z Y X`）。
            # 嵌套函数体引用外层参数/局部（闭包，version `(member name seen)`、
            # n4 `(setq r (+ r y))` 的 R）时排除（由外层注册，嵌套块不再重复）。
            _inner_all = node.args + node.optional + ([node.rest] if node.rest else [])
            _inner_locals = list(node.locals)
            # 内层体收集排除：内层参数 + 外层参数（arg_names）。外层**局部**
            # 不排除——闭包引用（n3 `(member name seen)`、n4 `(+ r y)`）由嵌套
            # 块注册 body 槽（GOLD n3 `... MEMBER SEEN NAME`、n4 `+ Y R`），
            # 外层 locals 区再注册 _al-bind-alist + const（SEEN/R 双槽）。
            _collect_args = set(_inner_all) | set(arg_names)
            _inner_refs = _SeenList()
            # 嵌套 defun 体同样丢弃语句位置（非末 form）的裸字符串（docstring/
            # 分节注释）：error-exit 的 `(defun *error* ...)` 体中间串、dbx
            # `dbx-clean-att`、dcl-subdialog `sub-dialog` 的 `"2..6. ..."` 均被
            # CAD 丢弃不注册（此前只剥**开头**连续 docstring，中间串泄漏进符号
            # 表 → nsyms +N、后续槽错位）。规则同顶层 `strip_docstring`：仅
            # 体末 form（返回值位置）的字符串保留。
            if len(node.body) > 1:
                _inner_body = [
                    x for i, x in enumerate(node.body)
                    if i == len(node.body) - 1 or not isinstance(x, String)
                ]
            else:
                _inner_body = list(node.body)
            for _ie in _inner_body:
                self._collect_byteorder(_ie, _inner_refs, _collect_args, in_quote,
                                        cur_locals=set(_inner_locals))
            # 参数：out 被外层整体逆序，故按正向追加（外层逆序后 = 逆序，
            # 与普通函数参数 `reversed(all_args)` 一致——version @::pkg-deps-tree-rec
            # `(name depth)` CAD 实测 `DEPTH NAME`）。
            for _a in _inner_all:
                # 共享参数且其 args 声明逆序最后拥有者 == **当前外层函数**
                #（string-utils s2la `(str separator)` = 外层参数，`separator`
                # last=6 == 外层 reversed 6）：由外层 args 循环注册（在外层
                # locals 常量之后），嵌套块不注册——否则提前到体符号组、CAD
                # 槽错位（SEPARATOR 应在外层 `('S2LA',)` locals const 之后）。
                # STR 的 last=9（max-char）≠ 外层 6，照常由嵌套块注册。
                if (
                    _a in self.shared
                    and self._shared_last_decl.get(_a)
                    == self._n_funcs - 1 - getattr(self, "_cur_source_idx", 10**9)
                ):
                    continue
                if not self._seen(out, _a):
                    out.append((_a, False))
            # locals 常量 + _al-bind-alist 助手（n2 实测 const 在 _al-bind-alist 后）
            if _inner_locals:
                _lc = (CONST_MARK, ("LIST", tuple(("SYMBOL", _l) for _l in _inner_locals)))
                # 嵌套 defun 的 locals 常量若与某**顶层 defun** 的 locals 结构
                # 相同（atlisp_u `@::edit-config` 内嵌 `save-config` 的 `/ i` =
                # `@::set-headers-ext` 的 `/ i`），CAD 合并到顶层 `_locals_last`
                # 位置（`@::set-headers-ext` rev 322，fg[1766]），不注册在嵌套
                # 宿主组——否则 `(quote (i))` 提前到 `@::edit-config` 组（资源流
                # @49938，fg 差 1、seg0 错位）。
                _llast = getattr(self, "_locals_last", {}).get(_lc[1])
                if _llast is not None:
                    _cur_rev = (
                        self._n_funcs - 1 - getattr(self, "_cur_source_idx", 0)
                        if self._n_funcs
                        else None
                    )
                    if _llast != _cur_rev:
                        _lc = None
                if _lc is not None and not self._seen(out, _lc):
                    out.append((_lc, False))
                if getattr(self, "_cur_source_idx", None) is None and not cur_locals and not self._seen(out, "_al-bind-alist"):
                    # `_al-bind-alist` 符号全文件共享：单函数路径（n2，无其它
                    # local 函数）由嵌套块注册；多函数路径由 `source_first_local`
                    # （源码序第一个 `/ locals` 函数，string-utils @::max-char）
                    # 统一注册，嵌套块不注册（否则提前到嵌套位置、CAD 槽错位）。
                    # 外层函数也有 `/ locals` 时（compat `(defun @::compat1
                    # (/ sym-name) ...)` 内嵌 load-custom）由外层 locals 区
                    # 统一注册，嵌套块跳过——否则 _al-bind-alist 提前到嵌套
                    # 位置（compat CAD slot 74，OURS 提前到 29 错位）。
                    out.append(("_al-bind-alist", False))
            # 体符号：_inner_refs 为 `_collect_byteorder` 正向（Setq 值先于目标、
            # n2 `(+ y 1)` 的 + 在 setq 目标 Z 前），该块在 out 中整体被外层
            # 逆序——故按正向追加，外层逆序后即目标序（n2 `Z +`）。
            for _n, _f in _inner_refs:
                if not self._seen(out, _n):
                    out.append((_n, _f))
            # 函数名最后（外层逆序后落在最前）
            if not self._seen(out, node.name):
                out.append((node.name, True))
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
            _wbody = node.body
            if len(_wbody) > 1:
                _wbody = [
                    x for i, x in enumerate(_wbody)
                    if i == len(_wbody) - 1 or not isinstance(x, String)
                ]
            for expr in _wbody:
                self._collect_byteorder(expr, out, arg_names, in_quote)
        elif isinstance(node, Progn):
            # 语句位置（值被丢弃）的裸字符串不注册：progn **中间 form**（非末
            # form，无论值/语句上下文其值都被丢弃）CAD 一律丢弃（error-exit
            # `(progn "这是一个未定义的函数。在这里异常退出." (mmma))` 首 form、
            # sort 各 `(progn "前者为偶时" ...)` 实测）。末 form 若为字符串可能
            # 是返回值/实参值（保留，下同 codegen 值上下文），不在此丢弃。
            _n_forms = len(node.forms)
            for _pi, form in enumerate(node.forms):
                if _pi < _n_forms - 1 and isinstance(form, String):
                    continue
                _f_tail = _is_tail and (_pi == _n_forms - 1)
                if (
                    not _f_tail
                    and _pi == _n_forms - 1
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
            if getattr(node, "name", None) == "vlax-for":
                # vlax-for 的 collect 枚举协议（kernel ui/menu.lsp golden）：额外
                # collect-init/next/release 三个内部 SUBR 符号，按字节码引用序
                # 注册在函数体符号区（golden 符号流 `collect-release GROUP =
                # @LISP STRCASE vla-get-Name collect-next G collect-init GROUPS`，
                # 即 kept 正序 = list_expr → collect-init → var → collect-next →
                # body → collect-release）。collect-* 为跨函数共享单槽（小写）。
                if node.list_expr:
                    self._collect_byteorder(node.list_expr, out, arg_names, in_quote)
                out.append(("collect-init", False))
                if node.var is not None:
                    _v = normalize_vla_name(node.var.name)
                    if (
                        _v not in arg_names
                        and _v not in getattr(self, "_unique_params", set()) - (cur_locals or set()) - (cur_locals or set())
                        and not self._seen(out, _v)
                    ):
                        out.append((_v, False))
                out.append(("collect-next", False))
                _vbody = node.body
                if len(_vbody) > 1:
                    _vbody = [
                        x for i, x in enumerate(_vbody)
                        if i == len(_vbody) - 1 or not isinstance(x, String)
                    ]
                for expr in _vbody:
                    self._collect_byteorder(expr, out, arg_names, in_quote)
                out.append(("collect-release", False))
                return
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
                # 参数拥有者槽（fg[46]，参数组），foreach 处无独立槽。例外：var
                # 是**本函数 `/ 局部变量`**（menu.lsp `category` = cuix-add-category
                # 参数 + remove-pkg-menu `/ local` + 外层 foreach 变量）时 CAD 仍在
                # var 位置独立注册（golden 局部块 `ITEM ITEMS CATEGORY NEW-MENU`，
                # `_al-bind-alist` 绑定协议需要本函数槽）。
                _v = normalize_vla_name(node.var.name)
                # 唯一参数（cache `subdir` = cache-store 参数 + cache-clear-all
                # foreach 变量）同名时**不独立注册**——CAD 复用参数拥有者槽。
                # 例外：参数拥有者源码序**更晚**（foreach 宿主逆序处理更晚，
                # merged base-function `@::confirm` `(foreach str ...)` = str
                # 唯一参数 @::parse-version-constraint src28 更晚，confirm src7
                # 逆序更晚处理）时 foreach 变量**独立注册**在宿主组（CAD
                # merged_4 实测 STR fg[199] 在 confirm 组，非参数拥有者组）。
                _is_later_host = (
                    getattr(self, "_param_first_source", {}).get(_v, 10**9)
                    > getattr(self, "_cur_source_idx", 10**9)
                )
                if (
                    _v not in arg_names
                    and (
                        _v not in getattr(self, "_unique_params", set())
                        - (cur_locals or set())
                        or _is_later_host
                    )
                    and not self._seen(out, _v)
                ):
                    out.append((_v, False))
            _fbody = node.body
            if len(_fbody) > 1:
                _fbody = [
                    x for i, x in enumerate(_fbody)
                    if i == len(_fbody) - 1 or not isinstance(x, String)
                ]
            for expr in _fbody:
                self._collect_byteorder(expr, out, arg_names, in_quote)
        elif isinstance(node, RepeatNode):
            # CAD repeat 字节码：count 先求值存局部槽（`_emit_repeat_stub`
            # `count; SET_LOCAL`），随后 body。符号引用序 = count → body
            # （panel.lsp @::panel-dcl-config-buttons 的 repeat count
            # `(- max-menus (length (vl-remove-if kwote ...)))` 符号
            # `- LENGTH VL-REMOVE-IF kwote = X` 在 body 字符串前，golden 实测；
            # 逆序注册后 body 字符串低槽）。
            if node.count:
                self._collect_byteorder(node.count, out, arg_names, in_quote)
            _rbody = node.body
            if len(_rbody) > 1:
                _rbody = [
                    x for i, x in enumerate(_rbody)
                    if i == len(_rbody) - 1 or not isinstance(x, String)
                ]
            for expr in _rbody:
                self._collect_byteorder(expr, out, arg_names, in_quote)
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
                _body = clause[1:]
                # CAD 丢弃 cond 子句体中语句位置的裸字符串（分节注释/说明，
                # grread.lsp `(t "其它情况" (princ gr))` 实测——"其它情况"、
                # "按下了键盘按键" 等不注册 STRING 槽）。仅**末 form**（子句
                # 返回值位置）的字符串保留（`(t "message")` 返回值）。与
                # `strip_docstring`（defun 体）同规则：非末字符串 = docstring。
                if len(_body) > 1:
                    _body = [x for i, x in enumerate(_body) if i == len(_body) - 1 or not isinstance(x, String)]
                for item in _body:
                    self._collect_byteorder(item, out, arg_names, in_quote)
        elif isinstance(node, ListExpr):
            if node.items and isinstance(node.items[0], LambdaNode):
                # 立即应用 `((lambda ...) args)`：实参先求值（字节码序，dcl CAD
                # 实测 args 的 gensym 在 lambda 参数 dcl-str/dcl-name 之前），
                # 先收集 args、后收集 lambda 头（参数 + 体）。
                for _it in node.items[1:]:
                    self._collect_byteorder(_it, out, arg_names, in_quote)
                self._collect_byteorder(node.items[0], out, arg_names, in_quote,
                                        _is_tail=_is_tail)
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
                if not _excluded and _a in self.shared:
                    pass
                if (
                    _a not in arg_names
                    and not _excluded
                    and not self._seen(out, _a)
                ):
                    out.append((_a, False))
            if _lam_locals:
                _lc = ("LIST", tuple(("SYMBOL", l) for l in _lam_locals))
                # 裸 lambda 值的 locals 常量若与某**顶层 defun** 的 locals
                # 结构相同（atlisp_u `@::load-error-handler` 返回 `(lambda
                # (msg / fp) ...)` 的 `(fp,)` 与 6 个 defun 的 `('fp',)`
                # 共享），CAD 把它合并到顶层 defun 的 locals_last 位置（逆序
                # 最后声明者 = `@::platform-machineid-save` src 7，fg[2377]），
                # 不在 lambda 宿主处注册。当前外层函数若**不是**逆序最后
                # 声明者（`_cur_source_idx` 正序 ≠ n-1-locals_last），跳过
                # const 收集——否则 `(fp,)` 提前注册到 `@::load-error-handler`
                # 组（fg[677]）→ fg/seg0 全表错位。
                _llast = getattr(self, "_locals_last", {}).get(_lc)
                if _llast is not None:
                    _cur_rev = (
                        self._n_funcs - 1 - getattr(self, "_cur_source_idx", 0)
                        if self._n_funcs
                        else None
                    )
                    if _llast != _cur_rev:
                        _lc = None
                if _lc is not None and not self._seen(out, (CONST_MARK, _lc)):
                    out.append(((CONST_MARK, _lc), False))
                for _l in _lam_locals:
                    if not self._seen(out, _l):
                        out.append((_l, False))
            _lbody = node.body
            if len(_lbody) > 1:
                _lbody = [
                    x for i, x in enumerate(_lbody)
                    if i == len(_lbody) - 1 or not isinstance(x, String)
                ]
            for _bi, _b in enumerate(_lbody):
                self._collect_byteorder(
                    _b, out, arg_names, in_quote, _is_tail=(_bi == len(_lbody) - 1)
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
                    _lam_locals = []
                    if "/" in node.expr.args:
                        _lam_locals = node.expr.args[node.expr.args.index("/") + 1 :]
                    # kwote lambda 参数：非 `_all_params` 排除（参数拥有者逆序
                    # 更晚处理，base-function `x` = pair 参数 src12 < getf src13
                    # 时由参数拥有者注册，lambda 不收集）的**可收集**参数在
                    # kwote 块**开头**注册（= _rev 块末尾、reverse 后最后，
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
                    # 可收集参数在 locals 常量**之前**（compat `(lambda (line / pos)
                    # ...)` CAD 实测 forward = [kwote, line, const(pos), body...]，
                    # fg[39]=const(POS)、fg[40]=LINE——param 先于 locals const）。
                    if _multi:
                        for _p in _collectible:
                            if not self._seen(out, _p):
                                out.append((_p, False))
                    # kwote lambda 的 `/ 局部变量` locals 常量 `(quote (locals...))`
                    # 需注册（codegen `_emit_al_bind_alist_locals` 会 add_constant），
                    # 否则 symtab 在 codegen 阶段插入新常量导致后续符号索引漂移
                    # （@lisp_u `(lambda (line / pos) ...)` 的 `(quote (pos))`
                    # 被推到 nsyms 外，_patch_usubr_idx const_map 找不到 → PUSH_G
                    # 越界 → CAD 0xC0000005）。常量结构与 codegen 一致
                    # （`('LIST', (('SYMBOL', loc)...))`）。
                    # `_al-bind-alist` 助手：仅当 kwote lambda locals == 外层函数
                    # locals（net/proxy kwote lambda `/ shell exec stdout result`
                    # == 函数 locals，CAD `_al-bind-alist` 在 locals 之前、0x56
                    # 块在 const 前）时早注册；kwote lambda locals ≠ 函数 locals
                    # （command `@::F` kwote /req resp boot ≠ 函数 /ok req，CAD
                    # 实测 `const(req resp boot), VL-LOAD-COM, _al-bind-alist,
                    # const(ok req)`）则 `_al-bind-alist` 由外层函数 locals 处理
                    # 统一注册，不在此提前。
                    if _lam_locals:
                        _lc = ("LIST", tuple(("SYMBOL", l) for l in _lam_locals))
                        # kwote lambda 的 locals 常量若与某**顶层 defun** 的
                        # locals 结构相同（atlisp_u `@::load-error-handler`
                        # kwote lambda `/ fp` 与 6 个 defun 的 `('fp',)` 共享），
                        # CAD 把它合并到顶层 defun 的 locals_last 位置（逆序最后
                        # 声明者 = `@::platform-machineid-save` src 7，fg[2377]），
                        # 不在 kwote 块处注册。当前外层函数若**不是**逆序最后
                        # 声明者（`_cur_source_idx` 正序 ≠ n-1-locals_last），跳过
                        # const 收集——否则 `(fp,)` 提前注册到 kwote 宿主组
                        # （fg[677]）→ fg/seg0 全表错位。
                        _llast = getattr(self, "_locals_last", {}).get(_lc)
                        if _llast is not None:
                            _cur_rev = (
                                self._n_funcs - 1 - getattr(self, "_cur_source_idx", 0)
                                if self._n_funcs
                                else None
                            )
                            if _llast != _cur_rev:
                                _lc = None
                        if _lc is not None and not self._seen(out, (CONST_MARK, _lc)):
                            out.append(((CONST_MARK, _lc), False))
                        if set(_lam_locals) == set(cur_locals or []):
                            if not self._seen(out, "_al-bind-alist"):
                                out.append(("_al-bind-alist", False))
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
                    # `_all_params`/`self.shared`/`_param_first_source` 为参数
                    # 声明名（小写 str），quoted 单符号 `_n` 可能大写 `'STR`
                    # （dcl line 32 `(eq 'STR ...)`）——排除判断须大小写不敏感
                    #（AGENTS file-utils 段），否则 dcl 的 `'STR` 落普通分支
                    # 注册 SYMBOL 槽（slot 205）而非 const。
                    _all_params_ci = {p.upper() for p in getattr(self, "_all_params", set())}
                    _shared_ci2 = {s.upper() for s in getattr(self, "shared", set())}
                    _pfs_ci = {
                        k.upper(): v for k, v in getattr(self, "_param_first_source", {}).items()
                    }
                    _is_other_param = (
                        _n.upper() in _all_params_ci
                        and _n.upper() not in _shared_ci2
                        and _pfs_ci.get(_n.upper(), 10**9)
                        < getattr(self, "_cur_source_idx", 10**9)
                    )
                    if module_ctx:
                        # 模块注册域（顶层 form）：quoted 单符号**不**走参数
                        # 延迟——CAD 把 define-config-typed 的 `'int`/`'bool`
                        # 类型实参注册进模块区（虽与 `@::ash` 参数 `int` 同名）。
                        _is_other_param = False
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
                        # 注册 const 使 codegen 命中 const 槽（PUSH_G）。const
                        # 延迟到**资源序末尾**注册（kept_refs[-1] 末尾，reversed
                        # 注册最后）——CAD 的 `'STR` const 在 slot 227（末尾），
                        # 旧实现在引用函数组注册 → slot 205 提前 22 槽、后续
                        # 整体偏移 +1。
                        _c = ("SYMBOL", _n)
                        if _c not in self._deferred_consts:
                            self._deferred_consts.append(_c)
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
            if node.count:
                self._collect_forward(node.count, out, locals_)
            for expr in node.body:
                self._collect_forward(expr, out, locals_)
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
