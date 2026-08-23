"""CLI path tests — cmd_* functions and main() dispatch."""
import os
import sys
import tempfile
import pytest

sys.path.insert(0, '.')
from compiler.cli import cmd_compile, cmd_decompile, cmd_validate, cmd_link, main
from compiler.vlx_builder import build_vlx
from compiler.linker import link_fas
from decompiler.fas4_decompiler import Fas4Parser


def _tmp(name):
    return os.path.join(tempfile.gettempdir(), f'test_cli_{os.urandom(4).hex()}_{name}')


@pytest.mark.parametrize('level', [0, 1, 2, 3])
def test_compile_opt_level(level):
    src = '(defun add (a b) (+ a b))'
    out = _tmp(f'l{level}.fas')
    try:
        result = cmd_compile(src, out, opt_level=level)
        assert os.path.exists(result)
        fas = Fas4Parser().parse(result)
        assert len(fas.bytecode) > 0
    finally:
        if os.path.exists(out):
            os.unlink(out)


def test_compile_analyze_flag():
    out = _tmp('ana.fas')
    try:
        result = cmd_compile('(defun foo () 1)', out, opt_level=2, show_analysis=True)
        assert os.path.exists(result)
    finally:
        if os.path.exists(out):
            os.unlink(out)


def test_compile_report_json():
    """--report 写出结构化 JSON：分析 + 优化对比 + 产物统计。"""
    import json as _json

    out = _tmp('rep.fas')
    rep = _tmp('rep.json')
    try:
        cmd_compile('(defun add (a b) (+ a b))', out, opt_level=2, report_json=rep)
        assert os.path.exists(out)
        assert os.path.exists(rep)
        with open(rep, encoding='utf-8') as f:
            data = _json.load(f)
        assert data['command'] == 'compile'
        assert data['opt_level'] == 2
        assert data['analysis']['functions'] == 1
        assert data['analysis']['functions_detail'][0]['name'] == 'add'
        assert data['optimized'] is not None
        assert data['product']['nsyms'] > 0
        assert data['product']['seg0_size'] > 0
    finally:
        for p in (out, rep):
            if os.path.exists(p):
                os.unlink(p)


def test_compile_default_output():
    """Default output name replaces .lsp with .fas."""
    src_path = _tmp('in.lsp')
    with open(src_path, 'w') as f:
        f.write('(defun foo () 1)')
    expected = src_path.replace('.lsp', '.fas')
    try:
        result = cmd_compile(src_path)
        assert result == expected
        assert os.path.exists(expected)
    finally:
        for p in (src_path, expected):
            if os.path.exists(p):
                os.unlink(p)


@pytest.mark.parametrize('enc', ['utf-8', 'utf-8-sig', 'gbk'])
def test_compile_source_encoding_detection(enc):
    """UTF-8 / UTF-8 BOM / ANSI(GBK) 编码的中文源码均能正确编译读取。"""
    src = '(defun hello () (strcat "你好，" "世界"))'
    src_path = _tmp('enc.lsp')
    out = _tmp('enc.fas')
    try:
        with open(src_path, 'w', encoding=enc) as f:
            f.write(src)
        result = cmd_compile(src_path, out)
        fas = Fas4Parser().parse(result)
        strs = [it[1] for it in fas.resource_items
                if isinstance(it, tuple) and len(it) == 2 and it[0] == 'STRING']
        assert '你好，' in strs
        assert '世界' in strs
    finally:
        for p in (src_path, out):
            if os.path.exists(p):
                os.unlink(p)


def test_compile_source_gbk_file_roundtrip():
    """GBK(ANSI) 源码 + cp936 输出：FAS 字符串为 GBK 字节，反编译正确。"""
    src_path = _tmp('gbk.lsp')
    out = _tmp('gbk.fas')
    try:
        with open(src_path, 'w', encoding='gbk') as f:
            f.write('(defun a () "中文测试")')
        cmd_compile(src_path, out, encoding='cp936')
        fas = Fas4Parser().parse(out)
        sec2 = bytes(fas.sec2_data)
        assert b'\xd6\xd0\xce\xc4\xb2\xe2\xca\xd4' in sec2  # GBK 字节 "中文测试"
    finally:
        for p in (src_path, out):
            if os.path.exists(p):
                os.unlink(p)



def test_cmd_validate_ok():
    p = _tmp('ok.lsp')
    with open(p, 'w') as f:
        f.write('(defun foo () 1)\n')
    try:
        assert cmd_validate(p) == 0
    finally:
        os.unlink(p)


def test_cmd_validate_fail():
    p = _tmp('bad.lsp')
    with open(p, 'w') as f:
        f.write('(defun foo () (if x)\n')
    try:
        assert cmd_validate(p) == 1
    finally:
        os.unlink(p)


def test_validate_dangerous_funcs_warn():
    """quit/exit/startapp must be flagged (warning) but still validate (rc 0)."""
    from tools.validate import tokenize, parse_tokens, validate_ast, validate_danger
    src = '(defun run () (startapp "cmd.exe" "dir"))\n(defun stop () (quit))\n'
    tokens, _ = tokenize(src)
    forms, _ = parse_tokens(tokens)
    assert validate_ast(forms) == []
    warns = validate_danger(forms)
    assert len(warns) == 2
    assert all('dangerous' in w for w in warns)


def test_validate_unused_local_warns():
    """Declared-but-unused / locals must be flagged as warnings."""
    from tools.validate import tokenize, parse_tokens, validate_unused
    src = '(defun foo (x / a b) (+ x 1))\n'
    tokens, _ = tokenize(src)
    forms, _ = parse_tokens(tokens)
    warns = validate_unused(forms)
    names = [w for w in warns]
    assert any('a' in w for w in names)
    assert any('b' in w for w in names)
    # used local must not warn
    src2 = '(defun foo (x / a) (setq a (+ x 1)) a)\n'
    tokens, _ = tokenize(src2)
    forms, _ = parse_tokens(tokens)
    assert validate_unused(forms) == []


def test_validate_command_danger_warns():
    """command/command-s with dangerous system commands must be warned."""
    from tools.validate import tokenize, parse_tokens, validate_command
    # dangerous: shell / del / vbastmt via command/command-s
    src = ('(defun a () (command-s "_.SHELL" "dir"))\n'
           '(defun b () (command "_.DEL" f))\n'
           '(defun c () (vl-cmdf "_.VBASTMT" s))\n')
    tokens, _ = tokenize(src)
    forms, _ = parse_tokens(tokens)
    warns = validate_command(forms)
    assert len(warns) == 3
    assert all('dangerous command' in w for w in warns)
    # safe commands must not warn
    src2 = ('(defun d () (command-s "_.CIRCLE" "0,0" 5))\n'
            '(defun e () (command "line" p1 p2 ""))\n')
    tokens, _ = tokenize(src2)
    forms, _ = parse_tokens(tokens)
    assert validate_command(forms) == []


def test_validate_command_danger_cli_rc_zero():
    """CLI validate still returns 0 when command warnings are present."""
    from tools.validate import validate_file
    from pathlib import Path
    p = _tmp('cmd_warn.lsp')
    with open(p, 'w') as f:
        f.write('(defun run () (command-s "_.SHELL" "dir"))\n')
    try:
        assert validate_file(Path(p)) is True
    finally:
        os.unlink(p)


def test_validate_danger_unused_cli_rc_zero():
    """CLI validate still returns 0 when only warnings are present."""
    from tools.validate import validate_file
    from pathlib import Path
    p = _tmp('warn.lsp')
    with open(p, 'w') as f:
        f.write('(defun run () (startapp "cmd"))\n')
    try:
        assert validate_file(Path(p)) is True
        assert cmd_validate(p) == 0
    finally:
        os.unlink(p)


def test_cmd_link_roundtrip():
    f1 = cmd_compile('(defun a (x) (+ x 1))', _tmp('a.fas'))
    f2 = cmd_compile('(defun b (x) (a x))', _tmp('b.fas'))
    out = _tmp('linked.fas')
    try:
        result = cmd_link([f1, f2], out)
        assert os.path.exists(result)
        fas = Fas4Parser().parse(result)
        assert len(fas.bytecode) > 0
    finally:
        for p in (f1, f2, out):
            if os.path.exists(p):
                os.unlink(p)


def test_build_vlx_container():
    f1 = cmd_compile('(defun main () 1)', _tmp('vlx_a.fas'))
    out = _tmp('app.vlx')
    try:
        result = build_vlx([f1], out, exports=['main'], package_name='app')
        assert os.path.exists(result)
        with open(result, 'rb') as fh:
            data = fh.read()
        assert data[:12] == b'VXL_FIRM\x00\x00\x00\x00'
        assert b'_VLX' in data
        assert b'vl-doc-export' in data
    finally:
        for p in (f1, out):
            if os.path.exists(p):
                os.unlink(p)


def test_main_compile_dispatch(monkeypatch, capsys):
    out = _tmp('main.fas')
    try:
        monkeypatch.setattr(sys, 'argv', ['atlispcc', 'compile', '-O1', '(defun foo () 1)', out])
        rc = main()
        assert rc == 0
        assert os.path.exists(out)
    finally:
        if os.path.exists(out):
            os.unlink(out)


def test_main_validate_dispatch(monkeypatch, capsys):
    p = _tmp('main_ok.lsp')
    with open(p, 'w') as f:
        f.write('(defun foo () 1)\n')
    try:
        monkeypatch.setattr(sys, 'argv', ['atlispcc', 'validate', p])
        rc = main()
        assert rc == 0
    finally:
        os.unlink(p)


def test_main_link_dispatch(monkeypatch):
    f1 = cmd_compile('(defun a (x) (+ x 1))', _tmp('m_a.fas'))
    f2 = cmd_compile('(defun b (x) (* x 2))', _tmp('m_b.fas'))
    out = _tmp('m_linked.fas')
    try:
        monkeypatch.setattr(sys, 'argv', ['atlispcc', 'link', f1, f2, '-o', out])
        rc = main()
        assert rc == 0
        assert os.path.exists(out)
    finally:
        for p in (f1, f2, out):
            if os.path.exists(p):
                os.unlink(p)


def test_cmd_info_fas():
    """info 对 CAD 自包含样本报出函数目录与段规模。"""
    from compiler.cli import cmd_info

    info = cmd_info('tests/cad/i18n-cad.fas', json_out=True)
    assert info['format'] == 'compact-stub'
    assert info['nsyms'] > 0
    assert info['seg0_size'] > 0
    assert info['seg1_size'] > 0
    assert info['func_count'] >= 1
    assert any('CODEPAGE2LANG' in name for name, _ in info['catalog'])


def test_cmd_info_zelx():
    """info 对 .zelx 容器读取 ZAS 头与载荷规模。"""
    from compiler.cli import cmd_info

    info = cmd_info('samples/zelx-reversing/asetq.zelx', json_out=True)
    assert info['format'] == 'zelx'
    assert info['zelx']['payload_size'] > 0
    assert info['zelx']['X'] > 0


def test_cmd_info_cli_json_dispatch(monkeypatch, capsys):
    """CLI `atlispcc info --json <fas>` 输出合法 JSON 且 rc=0。"""
    import json as _json

    monkeypatch.setattr(sys, 'argv', ['atlispcc', 'info', '--json', 'tests/cad/i18n-cad.fas'])
    rc = main()
    assert rc == 0
    out = capsys.readouterr().out
    data = _json.loads(out)
    assert data['file'].endswith('i18n-cad.fas')


def test_compile_top_level_progn_and_conditional_defun():
    """@lisp 包模式：顶层 `(progn ...)` 包裹 + 条件/嵌套 defun 可编译。

    顶层 progn 展开提取 defun；`(if c (defun f ...))` 改写为
    `(setq f '(lambda ...))`（AutoLISP 符号绑定 lambda 可调用，等价 defun-q）。
    """
    src = '''
(progn
  (defun add (a b) (+ a b))
  (if (null add) (set 'add -))
  (defun helper () (add 1 2)))
(if (boundp 'extra)
  (defun extra-fn (x) (* x 2)))
(defun c:go () (extra-fn 3))
'''
    out = _tmp('progn_lower.fas')
    try:
        result = cmd_compile(src, out)
        assert os.path.exists(result)
        fas = Fas4Parser().parse(result)
        assert len(fas.bytecode) > 0
    finally:
        if os.path.exists(out):
            os.unlink(out)


def test_compile_atlisp_u_fixture():
    """tests/atlisp_u.lsp（@lisp 综合包：顶层 progn + 条件/嵌套 defun +
    引用数据特殊形式 + 超 int32 整数字面量）整体编译通过。"""
    src = os.path.join('tests', 'atlisp_u.lsp')
    if not os.path.exists(src):
        pytest.skip('missing atlisp_u.lsp fixture')
    out = _tmp('atlisp_u.fas')
    try:
        result = cmd_compile(src, out)
        assert os.path.exists(result)
        fas = Fas4Parser().parse(result)
        assert len(fas.bytecode) > 0
        assert fas.nsyms > 0
    finally:
        if os.path.exists(out):
            os.unlink(out)


def test_compile_symbol_string_collision():
    """回归：符号 `>`（内建 subr）与字符串 `">"` 在 fg 表同 key 时，
    USUBR/FUNC 引用必须指向 SYMBOL 槽而非 STRING 槽，否则 CAD
    `(">" 24.1 20.1)` ill-fun 错误（@lisp_u 真机暴露，2026-08-13）。"""
    from core.fas_core import parse_fas4, build_mvar_tables
    from decompiler.fas4_decompiler import Disassembler

    src = '''(defun test-cmp (a b) (> a b))
(defun test-eq (a b) (= a b))
(defun use-str () (if (= (car nil) ">") 1 2))
'''
    out = _tmp('symstr.fas')
    try:
        cmd_compile(src, out)
        p = parse_fas4(out)
        rg, fg = build_mvar_tables(p['res_data_decrypted'], p['nsyms'])
        insts = Disassembler(short_subr=p['nsyms'] <= 256).disassemble(
            p['bytecode'], p['nsyms']
        )
        bad = []
        for inst in insts:
            if inst.op_name in ('USUBR', 'FUNC') and len(inst.operands) >= 2:
                t = inst.operands[1] + 1  # 操作数 = gvar 槽 - 1
                if 0 <= t < len(fg) and isinstance(fg[t], tuple) and len(fg[t]) == 2 and fg[t][0] == 'STRING':
                    bad.append((inst.offset, inst.op_name, inst.operands, fg[t]))
        assert bad == [], f'USUBR/FUNC 引用了 STRING 槽: {bad}'
        # 符号 `>` 与字符串 `">"` 都在资源段注册（各自独立槽）
        gt_sym = any(isinstance(v, tuple) and len(v) == 2 and v[0] == 'SYMBOL' and str(v[1]).upper() == '>' for v in fg)
        gt_str = any(isinstance(v, tuple) and len(v) == 2 and v[0] == 'STRING' and str(v[1]) == '>' for v in fg)
        assert gt_sym, 'SYMBOL `>` 未在资源段注册'
        assert gt_str, '字符串 ">" 未在资源段注册'
    finally:
        if os.path.exists(out):
            os.unlink(out)


def _module_reg_names(fas):
    """从解密 seg1 中提取模块注册段名字序列（`5b`/`56`/`55` 块直到模块
    GVARINIT `01 01`）。@lisp 综合包混合模式（defun + 命令 + 顶层表达式）
    如何被编译进 seg1 模块注册段的核心结构信号。"""
    from core.fas_core import parse_fas4

    res = parse_fas4(fas)['res_data_decrypted']
    # 模块注册段以 `5b @::INIT`（atlisp_u）或首个大写 `5b` 块开头。
    start = res.find(bytes([0x5B, 0x40, 0x3A, 0x3A, 0x49, 0x4E, 0x49, 0x54]))
    if start < 0:
        return []
    i, protect = start, 0
    names = []
    while i < len(res) and protect < 12000:
        protect += 1
        b = res[i]
        if b == 0x5B:
            k = i + 1
            while True:
                z = res.index(0, k)
                if z == k:
                    break
                names.append(res[k:z].decode('latin1'))
                k = z + 1
                if k >= len(res) or res[k] == 0:
                    break
            i = k + 1
            if i < len(res) and res[i] == 0x00:
                i += 1
            continue
        elif b == 0x56:
            z = res.index(0, i + 1)
            names.append(res[i + 1:z].decode('latin1'))
            i = z + 2
            continue
        elif b == 0x55:
            cnt = int.from_bytes(res[i + 1:i + 3], 'little')
            k = i + 3
            for _ in range(cnt):
                ln = int.from_bytes(res[k:k + 2], 'little')
                k += 2 + ln
            i = k
            continue
        elif b == 0x01 and i + 1 < len(res) and res[i + 1] == 0x01:
            break
        else:
            break
    return names


def test_compile_atlisp_u_module_reg_bounded():
    """回归：atlisp_u 混合模式（476+ 函数 + 命令 + 顶层表达式）的 seg1 模块
    注册段只含"模块代码引用函数 + 命令 + 顶层符号"，不得把全部函数
    名登记进模块注册段（CAD @lisp_u.fas 实测模块注册 65 个名字，CC 61；
    修复前 518）。func_names_all 按模块尾块截断，其余函数经函数体符号区
    注册（2026-08-14 修复，逆向确认 CAD 规则：模块注册 = 最后一个顶层
    模块级 setq 之后的 defun）。"""
    from core.fas_core import parse_fas4

    src = os.path.join('tests', 'atlisp_u.lsp')
    if not os.path.exists(src):
        pytest.skip('missing atlisp_u.lsp fixture')
    out = _tmp('atlisp_u.fas')
    try:
        cmd_compile(src, out)
        mod_names = _module_reg_names(out)
        assert mod_names, '模块注册段应为空或解析失败'
        # 命令 + 顶层引用函数必须注册（CAD 一致）
        assert 'C:@DIAG' in mod_names or any(n.startswith('C:') for n in mod_names)
        assert any(n.startswith('@::INIT') for n in mod_names)
        # 核心回归：模块注册段不得膨胀为全部函数名的 5b 链。
        # CAD @lisp_u.fas 实测 65 个名字（init 链 + 命令 + 配置符号 +
        # RANGE 常量），CC 修复后 61。阈值取 <100，防止膨胀为全部函数名。
        assert len(mod_names) < 100, (
            f'module registration ballooned to {len(mod_names)} names; '
            'CAD only registers module-code-referenced funcs + commands + '
            'top-level symbols, not all defuns'
        )
    finally:
        if os.path.exists(out):
            os.unlink(out)


def test_vlax_for_expanded_to_foreach():
    """回归：`(vlax-for var coll body...)` 须展开为 foreach 迭代（ForeachNode），
    不得编译成对未定义 `vlax-for` 函数的调用（运行时错误）。

    @lisp_u 中 vlax-for 用于遍历 ActiveX 集合（CUIX 菜单组、screensize 等）；
    修复前编译产物把 `vlax-for` 当普通函数 USUBR 调用（无此函数 → CAD 报
    "函数错误"）。修复后经 parser 展开为 ForeachNode，复用 foreach stub 协议。
    CAD 资源段注册符号槽为 **VLAX-FOR**（大小写保留，ui.lsp CAD golden 实测
    `5b VLAX-FOR`），故符号表中应存在 VLAX-FOR 且编译成功。"""
    src = os.path.join('tests', 'atlisp_u.lsp')
    if not os.path.exists(src):
        pytest.skip('missing atlisp_u.lsp fixture')
    out = _tmp('vlax_for.fas')
    try:
        cmd_compile(src, out)
        parser = Fas4Parser()
        fas = parser.parse(out)
        # CAD 注册 VLAX-FOR 符号槽（_enc_sym _VLISP_CASE_PRESERVE 规范化为大写）；
        # 若展开失败退化为 USUBR 调用则无此槽且运行时错误。编译成功 + 槽存在
        # = ForeachNode 展开正确。
        vla = [s for s in fas.symbol_slots if str(s[1]).upper() == 'VLAX-FOR']
        assert vla, 'vlax-for 应展开为 ForeachNode 并注册 VLAX-FOR 符号槽'
    finally:
        if os.path.exists(out):
            os.unlink(out)
