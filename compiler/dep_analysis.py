"""调用图/依赖分析 — 为 `atlispcc analyze` 提供统一图模型与输出格式。

输入适配器:
 - ``.lsp``: Parser → analyze() 的每函数 calls 集合
 - ``.fas``: Fas4Parser → Disassembler → ControlFlowAnalyzer.find_functions(),
             按函数指令扫描 USUBR/FUNC 操作数（符号槽索引）解析被调名

输出语义统一:
 - nodes: 程序内定义函数 + 入边度数 + 是否 root
 - edges: 程序内「调用者 → 被调用者」有向边
 - externals: 程序内函数引用的非程序内符号（内建/外部）
 - unused: 无入边且非 root 的函数
"""
import collections
from typing import Any, Dict, List, Optional, Set, Tuple


def _defun_nodes(program) -> List[Any]:
    from compiler.ast_nodes import Defun

    return [f for f in program.forms if isinstance(f, Defun)]


def _lsp_call_map(program) -> Dict[str, Set[str]]:
    """按函数收集其 body 内全部调用名（含内建，与 analyzer._collect_call_names 同逻辑）。"""
    from compiler.analyzer import _collect_call_names

    defuns = _defun_nodes(program)
    call_map: Dict[str, Set[str]] = {}
    for f in defuns:
        calls: Set[str] = set()
        for e in f.body:
            _collect_call_names(e, calls)
        call_map[f.name] = calls
    return call_map


def _collect_top_level_calls(program) -> Set[str]:
    """defun 之外的顶层表达式调用名集合（入口 root 来源之一）。"""
    from compiler.analyzer import _collect_call_names
    from compiler.ast_nodes import Defun

    calls: Set[str] = set()
    for f in program.forms:
        if not isinstance(f, Defun):
            _collect_call_names(f, calls)
    return calls


def build_from_lsp(program) -> Dict:
    defuns = _defun_nodes(program)
    name_set = {f.name for f in defuns}
    call_map = _lsp_call_map(program)

    edges: List[Tuple[str, str]] = []
    externals: Set[str] = set()
    for caller, calls in call_map.items():
        for callee in calls:
            if callee in name_set:
                edges.append((caller, callee))
            else:
                externals.add(callee)

    top_calls = _collect_top_level_calls(program)
    roots = _compute_roots(name_set, top_calls)
    return _graph(name_set, edges, roots, sorted(externals))


def build_from_fas(source: str) -> Dict:
    """从 .fas 字节码重建依赖图（仅反汇编 + 控制流，无 LispGenerator 生成）。"""
    from decompiler.fas4_decompiler import (
        Fas4Parser,
        Disassembler,
        ControlFlowAnalyzer,
        is_compact_stub,
        extract_stub_function_names,
    )

    parser_obj = Fas4Parser()
    fas = parser_obj.parse(source)
    disasm = Disassembler(short_subr=is_compact_stub(fas.bytecode, fas.function_catalog))
    instructions = disasm.disassemble(fas.bytecode, fas.nsyms)
    # 紧凑 stub 格式：从资源段 DEFCODE 绑定序列解析真实函数名（如 FIB），
    # 否则 find_functions 返回合成名（c:fn0），无法与调用目标匹配。
    func_names = extract_stub_function_names(fas)
    cfa = ControlFlowAnalyzer(instructions, fas.function_catalog, function_names=func_names)
    functions = cfa.find_functions()

    # DEFCODE 注册的函数即文件导出的公开入口（root）：未被任何函数调用的
    # 公开 API 不应标为 UNUSED。自包含格式无 DEFCODE 目录时回退为 c:/*error*。
    defcode_roots = set(func_names.values()) if func_names else set()

    # 符号槽 → 名称：与 asm/assembler 的符号编址一致（资源注册顺序）。
    # USUBR/FUNC 第二操作数是符号槽索引；SYMBOL 记录取名称，其余为 None。
    slot_names: List[Optional[str]] = []
    source_slots = fas.symbol_slots if getattr(fas, "symbol_slots", None) else None
    if source_slots:
        for it in source_slots:
            if isinstance(it, tuple) and len(it) >= 2 and it[0] == "SYMBOL":
                slot_names.append(str(it[1]))
            else:
                slot_names.append(None)
    else:
        slot_names = list(fas.symbols)

    def _symname(idx: int) -> Optional[str]:
        if 0 <= idx < len(slot_names):
            return slot_names[idx]
        return None

    func_entries: List[Tuple[str, Set[str]]] = []
    for fd in functions:
        callees: Set[str] = set()
        for inst in fd.instructions:
            if inst.op_name in ("USUBR", "FUNC") and inst.operands:
                idx = int(inst.operands[-2]) if len(inst.operands) >= 2 else int(inst.operands[-1])
                name = _symname(idx)
                if name:
                    callees.add(name)
        func_entries.append((fd.name, callees))

    name_set = {name for name, _ in func_entries if name}
    edges: List[Tuple[str, str]] = []
    externals: Set[str] = set()
    for caller, callees in func_entries:
        if not caller:
            continue
        for callee in callees:
            if callee in name_set:
                edges.append((caller, callee))
            else:
                externals.add(callee)

    roots = _compute_roots(name_set, set())
    roots = roots | (defcode_roots & name_set)
    return _graph(name_set, edges, roots, sorted(externals))


def _compute_roots(name_set: Set[str], top_calls: Set[str]) -> Set[str]:
    roots: Set[str] = set()
    for name in name_set:
        if name.startswith("c:") or name == "*error*":
            roots.add(name)
    for call in top_calls:
        if call in name_set:
            roots.add(call)
    return roots


def _graph(name_set: Set[str], edges: List[Tuple[str, str]], roots: Set[str], externals: List[str]) -> Dict:
    indegree: Dict[str, int] = collections.Counter(callee for _, callee in edges)
    outdegree: Dict[str, int] = collections.Counter(caller for caller, _ in edges)

    nodes = []
    for name in sorted(name_set):
        nodes.append(
            {
                "name": name,
                "calls": outdegree.get(name, 0),
                "called_by": indegree.get(name, 0),
                "root": name in roots,
                "unused": name not in roots and indegree.get(name, 0) == 0,
            }
        )

    unused = sorted(name for name in name_set if name not in roots and indegree.get(name, 0) == 0)
    return {
        "nodes": nodes,
        "edges": edges,
        "roots": sorted(roots),
        "externals": externals,
        "unused": unused,
    }


# ─── 输出格式 ────────────────────────────────────────────────────────────────


def format_text(graph: Dict) -> str:
    nodes_by_name = {n["name"]: n for n in graph["nodes"]}
    lines = []
    lines.append(f"Functions: {len(graph['nodes'])}   Edges: {len(graph['edges'])}   "
                 f"External refs: {len(graph['externals'])}   Unused: {len(graph['unused'])}")
    if graph["roots"]:
        lines.append(f"Roots: {', '.join(graph['roots'])}")
    if graph["unused"]:
        lines.append(f"Unused (no caller, not a root): {', '.join(graph['unused'])}")
    lines.append("")
    if graph["externals"]:
        lines.append(f"External/builtin references: {', '.join(sorted(graph['externals']))}")
        lines.append("")
    for node in graph["nodes"]:
        flags = []
        if node["root"]:
            flags.append("root")
        if node["unused"]:
            flags.append("UNUSED")
        suffix = f"  [{' | '.join(flags)}]" if flags else ""
        called = [c for caller, c in graph["edges"] if caller == node["name"]]
        callee_txt = ""
        if called:
            callee_txt = "  -> " + ", ".join(sorted(called))
        lines.append(f"  {node['name']} (calls={node['calls']}, called_by={node['called_by']}){suffix}{callee_txt}")
    return "\n".join(lines)


def format_dot(graph: Dict) -> str:
    lines = ["digraph callgraph {", '  rankdir="LR";']
    for node in graph["nodes"]:
        shape = "box" if node["root"] else "ellipse"
        style = ", style=filled, fillcolor=\"#ffcccc\"" if node["unused"] else ""
        lines.append(f'  "{node["name"]}" [shape={shape}{style}];')
    for caller, callee in graph["edges"]:
        lines.append(f'  "{caller}" -> "{callee}";')
    for caller in sorted({c for c, _ in graph["edges"]}):
        for ext in sorted(graph["externals"]):
            lines.append(f'  "{caller}" -> "{ext}" [style=dotted, color=gray];')
    lines.append("}")
    return "\n".join(lines)


def format_mermaid(graph: Dict) -> str:
    lines = ["flowchart LR"]
    for node in graph["nodes"]:
        style = ":::root" if node["root"] else (":::unused" if node["unused"] else "")
        cls = ""
        if node["root"]:
            cls = ":::root"
        elif node["unused"]:
            cls = ":::unused"
        lines.append(f'  {node["name"]}["{node["name"]}"]{cls}')
    for caller, callee in graph["edges"]:
        lines.append(f"  {caller} --> {callee}")
    if graph["externals"]:
        lines.append("  subgraph external")
        for ext in sorted(graph["externals"]):
            lines.append(f'    EXT_{ext}["{ext}"]')
        lines.append("  end")
    lines.append("classDef root fill:#dfd")
    lines.append("classDef unused fill:#fdd")
    return "\n".join(lines)