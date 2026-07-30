# atlispcc — FAS4 Bytecode Compiler & Decompiler

`atlispcc` is a unified CLI toolchain for compiling AutoLISP (`.lsp`) to FAS4 bytecode (`.fas`), decompiling FAS4 back to Lisp, linking multiple FAS files, and validating Lisp syntax.

## CLI

```sh
atlispcc compile [-O {0,1,2,3}] <input.lsp> [output.fas]      # compile
atlispcc decompile <input.fas> [output.lsp]                   # decompile
atlispcc validate <input.lsp>                                  # validate
atlispcc link [-o OUTPUT] <input.fas> <input.fas> [...]       # link
```

Without a subcommand, defaults to compile: `atlispcc <input.lsp> [output.fas]`

The decompiler can also be called directly: `python fas4_decompiler.py <input.fas> [output.lsp]`

## Compiler Pipeline

```
Lisp source → Parser.parse() → AST
           → SymbolTableBuilder.build() → SymbolTable
           → Codegen.generate() → List[FunctionDef] (instruction stream)
           → [OptPipeline.optimize()  # optional: -O1/-O2/-O3]
           → ResourceBuilder.build() → resource segment
           → FasWriter.write() → FAS4 binary
```

## Decompiler Pipeline

```
Fas4Parser.parse() → Disassembler.disassemble()
→ ControlFlowAnalyzer.find_functions() → LispGenerator.generate()
```

## Linker Pipeline

```
FAS A + FAS B + ... → merge symbol tables / function catalogs
→ re-index → fix cross-references → merged FAS
```

## Optimization Levels

| Level | Passes | Description |
|-------|--------|-------------|
| `-O0` | none | Raw compilation, no optimization |
| `-O1` | ConstantFold, DeadBranchElim, Peephole | Basic cleanup: `(+ 1 2)` → `3`, `(if T e1 e2)` → `e1`, `(progn x)` → `x` |
| `-O2` | O1 + ConstantPropagate, DeadAssignElim | Aggressive: `(setq x 3) (+ x 1)` → `(+ 3 1)`, remove unused `setq` |
| `-O3` | O2 + CrossFuncConstPropagate, DeadCodeElim, InlineSmallFuncs | Extreme: inline single-use functions, replace constant functions at call sites, remove dead code after `exit`/`quit` |

### Analysis

Use `--analyze` with any `-O` level to see compilation statistics:

```sh
atlispcc compile --analyze -O3 input.lsp output.fas
```

Output includes:
- Function count, instruction count, constants estimate
- Tail-recursive function detection
- Per-function detail: arg count, locals, called functions
- Before/after comparison when optimization is enabled

## Key Files

| File | Role |
|------|------|
| `fas4_decompiler.py` (2136 lines) | Main decompiler: parse + disassemble + analyze + generate |
| `fas_core.py` (690 lines) | Shared crypto/parse/symbol utilities |
| `compiler/cli.py` | CLI entry point, subcommand dispatch |
| `compiler/parser.py` | Lisp source parser → AST |
| `compiler/ast.py` | AST node definitions |
| `compiler/symbol_table.py` | Symbol table construction and scope analysis |
| `compiler/codegen.py` | Bytecode generator (AST → instruction stream) |
| `compiler/resource_builder.py` | Constant/symbol/function index → resource segment |
| `compiler/fas_writer.py` | Instruction stream → FAS4 binary |
| `compiler/opt.py` | Optimizer: 8 passes across O1-O3 |
| `compiler/analyzer.py` | Compilation analysis and statistics |
| `compiler/linker.py` | Multi-file FAS linker |
| `validate.py` | Generated `.lsp` syntax validator |

## Install

```sh
pip install -e ".[dev]"      # development mode with dev tools
```

## Tests

```sh
python -m pytest              # run all tests (75+ cases)
python -m pytest tests/ -v   # verbose output
```

Test files under `tests/`:
- `test_parser.py` — AST parser (14 cases)
- `test_compile_decompile.py` — compile-decompile roundtrip (15 cases)
- `test_compiler_output.py` — FAS output correctness (8 cases)
- `test_assembler.py` — disassemble/assemble roundtrip (4 cases)
- `test_linker.py` — multi-file linking (8 cases)
- `test_optimizer.py` — all optimization passes (26 cases)

## Docs

- `docs/development.md` — architecture deep-dive, coding conventions, debugging guide
- `docs/usage.md` — user installation, compile/decompile workflows, tool reference

## Safety

Always review decompiled `.lsp` before use. Test in a scratch drawing first. Some decoded commands may create, modify, or delete drawing entities.
