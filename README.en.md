# atlispcc — Atlisp Compiler Collection (FAS4 toolchain)

**English** | [简体中文](README.md)

`atlispcc` (**A**uto**L**ISP **C**ompiler **C**ollection) is a command-line compiler
suite that compiles AutoLISP (`.lsp`) to FAS4 bytecode (`.fas`), decompiles FAS4 back
to Lisp, links multiple FAS files, and validates Lisp syntax. Its output follows the
compact-stub layout produced by the AutoCAD compiler and loads and runs inside CAD.

## Features

- **Compile** `.lsp → .fas` with optional `-O0`…`-O3` optimization levels
- **Decompile** `.fas → .lsp` (self-contained and compact-stub layouts)
- **Disassemble / assemble** `.fas ↔ .lasm` (exact inverses)
- **Multi-file linking** merges `.fas` files, renumbers symbols/functions and fixes
  cross references
- **VLX container** packs `.fas` / `.dcl` / text members in the official
  **VRTLIB-1** layout (`LOAD` record + 4-byte-aligned record table + 16-byte
  footer); supports unpacking and `info`; `--export` compiles a `_VLX` export stub
- **Syntax validation** for parenthesis balance, defun structure, symbol legality
- **CL-style package system** with compile-time name mangling (`pkg|name`) that
  leaves the FAS4 format untouched
- **Project-level batch builds** — `project` compiles every Lisp source listed in
  `pkg.lsp` (`:FILES`) or a Visual LISP `.prj` (`:OWN-LIST`), skips resources, and
  emits a JSON report for CI/agents; `:MERGED` projects are linked into one module
- **Large @lisp packages** — top-level `(progn ...)` wrappers, conditional/nested
  defuns, multiple kwote callbacks (`(function (lambda ...))`) and files with more
  than 256 symbols (5-byte USUBR / 6-byte FUNC wide forms) all compile and load in CAD
- **kwote mechanism** — `(function (lambda ...))` becomes an embedded `-lambda-`
  DEFUN; top-level `(set/setq 'sym (lambda ...))` becomes an embedded `-lambda-`
  SUBR (byte-for-byte identical to CAD output)
- **`engine/` SBCL runtime** — an AutoLISP evaluation environment independent of
  CAD/FAS (`al-eval-source` / `al-run-file` / `al-repl`) used to cross-check
  compiler semantics

## Installation

```sh
pip install atlispcc
```

This installs the `atlispcc` command (`compiler.cli:main`); module invocation works too:

```sh
atlispcc compile input.lsp output.fas
python -m compiler.cli compile input.lsp output.fas          # equivalent
python -m decompiler.fas4_decompiler input.fas output.lsp    # decompile
python -m tools.validate output.lsp                          # validate
```

> Inside a source checkout you can also use `python -m`: `python -m compiler.cli ...`,
> `python -m decompiler.fas4_decompiler ...`, `python -m tools.validate ...`
> (both `python compiler/cli.py` and `python -m compiler.cli` work; the AST module is
> named `ast_nodes.py` so it no longer shadows the stdlib `ast`).

## CLI quick reference

```sh
atlispcc compile [-O {0,1,2,3}] <input.lsp> [output.fas]        # compile
atlispcc decompile <input.fas> [output.lsp]                      # FAS → Lisp
atlispcc disasm <input.fas> [output.lasm]                        # FAS → bytecode listing
atlispcc asm <input.lasm> [output.fas]                           # .lasm → FAS
atlispcc validate <input.lsp>                                    # validate syntax
atlispcc link [-o OUTPUT] <input.fas> <input.fas> [...]          # link FAS files
atlispcc build-vlx <input...> -o output.vlx [--export ...]       # build a VRTLIB-1 VLX
atlispcc unpack-vlx <input.vlx> [-o DIR] [--list] [--stub FILE]   # unpack / verify
atlispcc zelx <input.lsp|input.fas> [output.zelx]                # build a ZWCAD ZELX
atlispcc unzelx <input.zelx> [output.fas]                        # recover FAS from ZELX
atlispcc info <input.fas|input.zelx|input.vlx> [--json]          # quick overview
atlispcc analyze [-f text|dot|mermaid|json] [-o OUT] [--no-cc] <lsp|fas>
atlispcc roundtrip <input.lsp> [-O {0,1,2,3}] [--keep]           # round-trip smoke test
atlispcc project <pkg.lsp|dir|file.prj> [-o OUTDIR] [-O 0..3] [--json]  # batch build
```

With no subcommand it defaults to `compile`: `atlispcc <input.lsp> [output.fas]`

## Quick start

```sh
# Decompile (tests/cad/i18n-cad.fas is a self-contained CAD sample in the repo)
atlispcc decompile tests/cad/i18n-cad.fas output.lsp

# Validate the syntax
atlispcc validate output.lsp

# Expected: [PASS] output.lsp
```

## Subcommand details

### compile — Lisp → FAS

```sh
# Basic compile
atlispcc compile input.lsp output.fas

# Optimization: 0 = none (default), 1 = basic, 2 = aggressive, 3 = extreme
atlispcc compile -O2 input.lsp output.fas
atlispcc compile -O3 --analyze input.lsp output.fas
```

- `-O1`: constant folding, dead-branch elimination, peephole optimization
- `-O2`: adds constant propagation and dead-assignment elimination, then repeats the
  basic passes
- `-O3`: adds cross-function constant replacement, dead-code elimination and
  small-function inlining

#### Analysis (`--analyze`)

Use `--analyze` with any `-O` level to print compile statistics:

```sh
atlispcc compile --analyze -O3 input.lsp output.fas
```

The report includes function/instruction/constant counts, tail-recursion detection,
per-function parameters/locals/calls, and a before/after comparison when
optimization is enabled.

#### Reproducible builds (`--date` / `--salt`)

The FAS4 trailer key is **salt (6–10 bytes) + the 15-byte `;fas4 crunch` marker**.
The salt follows the Autodesk ANSI-C LCG (`random&`): byte range `1..255` (never
`0x00`), no two adjacent bytes equal, emitted in reverse draw order. The LCG is
seeded from the current time by default, so two builds differ; for byte-identical
output:

```sh
atlispcc compile app.lsp app.fas --date 2/3/26 --salt deterministic
atlispcc compile app.lsp app.fas --date 2/3/26 --salt seed:12345
atlispcc compile app.lsp app.fas --salt hex:0102030405
```

- `--date M/D/YY` pins the trailer stamp `$;A<M>/<D>/<YY>` (default: today)
- `--salt deterministic` uses the fixed salt `01 02 … 08`
- `--salt seed:<n>` generates an Autodesk-shaped salt from that seed
- `--salt hex:<bytes>` sets the salt directly (6–10 bytes; out-of-range salts
  cannot be located by the reader)
- Same source + same `--date`/`--salt` ⇒ **byte-identical `.fas`**
  (locked by `tests/test_fas_trailer.py`)
- `link`, `project`, `asm` and `build-vlx` accept the same two options

#### Compile report (`--report`)

Export statistics and product information as JSON (for CI/tooling):

```sh
atlispcc compile -O2 input.lsp output.fas --report report.json
```

Fields: `source`/`output`/`opt_level`/`encoding`, `analysis` (same as `--analyze`),
an `optimized` snapshot when optimization is on, and `product` (`nsyms`,
`codegen_nsyms`, module registration count, top-level expression count, seg0/seg1
sizes, seg1 item count).

### decompile — FAS → Lisp

```sh
atlispcc decompile input.fas output.lsp
# or via module
python -m decompiler.fas4_decompiler input.fas output.lsp
```

### validate — syntax check

```sh
atlispcc validate output.lsp
# or via module
python -m tools.validate output.lsp
```

The validator checks parenthesis balance, top-level forms, `C:` commands without
required arguments, symbol legality, and common structural mistakes (too few `if`
arguments, odd `setq` argument count, empty `progn`, …).

Success prints `[PASS] <file>`; failures list each problem.

### roundtrip — round-trip smoke test

One-command self-check per `.lsp`: `compile → decompile → validate → compare`.

```sh
atlispcc roundtrip app.lsp          # O0
atlispcc roundtrip app.lsp -O2      # with optimization
atlispcc roundtrip app.lsp -O2 --keep   # keep intermediates and print their paths
```

- **Pipeline**: deliberately uses the "bare in-memory pipeline" (the same one as the
  test suite) — top-level expressions (`setq`/`princ` outside defuns) stay in seg0
  bytecode so the decompiler can recover their strings. The CLI `compile` pipeline
  puts them into seg1 module code, where a top-level `princ` decompiles to `nil`.
- The report lists defun/string counts for the original and the decompiled output,
  plus missing/extra items and every string.
- Exit code: 0 = PASS, 1 = FAIL (differences, validation failure, or a compile /
  decompile exception).
- Note: `-O3` runs `RemoveDeadFuncs`, which drops unreferenced non-command
  functions; they disappear from the decompiled output by design. Use `-O0`/`-O2`
  when you need a complete per-function round trip.

### info — quick overview

Reads headers and resource sizes without a full decompile:

```sh
atlispcc info tests/cad/t01_math_cad.fas
atlispcc info tests/cad/i18n-cad.fas --json
```

FAS output: layout (`compact` / `selfcontained`), `nsyms`, seg0/seg1 sizes, decrypted
resource size and item count, XOR key length, function catalog, symbol/string counts,
trailer marker. ZELX output: the four `.zelx` parts (X/Y/Z/sub), payload size, key
length and payload entropy.

### analyze — call graph / dependency analysis

Analyzes `.lsp` sources or `.fas` bytecode and emits four formats:

```sh
atlispcc analyze app.lsp                      # text summary
atlispcc analyze app.lsp -f dot  -o app.dot   # Graphviz
atlispcc analyze app.lsp -f mermaid
atlispcc analyze app.fas  -f json             # structured graph data
atlispcc analyze app.lsp --no-cc              # do not treat c:*/*error* as roots
```

The model contains **nodes** (function + in/out degree + root/unused), **edges**
(intra-program call edges), **roots** (`c:*`/`*error*` or functions called from
top-level expressions), **externals** (built-in/external references) and **unused**
(no incoming edges and not a root). For `.fas` input, callee names are recovered from
USUBR/FUNC operands; DEFCODE-registered public functions are promoted to roots to
avoid false "unused" reports.

### disasm — FAS → `.lasm`

Disassembles `.fas` bytecode into readable assembly text (`.lasm`):

```sh
atlispcc disasm input.fas output.lasm
# or
atlispcc disassemble input.fas
```

The output contains a `.format` directive, the symbol table (`.symbols`) and each
function's instruction list (`.function`):

```
.format compact
.nsyms 4

.symbols
  0: SYMBOL hello
  1: SYMBOL x
.end_symbols

.function c:fn0, 0
  0x0000: DEFUN hello, 0
  0x0005: PUSH_G x
  0x000a: INIT_ARGS 2
.end_function
```

### asm — `.lasm` → FAS

Reassembles `.lasm` text into `.fas`:

```sh
atlispcc asm input.lasm output.fas
# or
atlispcc assemble input.lasm
```

`disasm` / `asm` are exact inverses: `.fas → .lasm → .fas` reproduces **seg0
byte-for-byte**. The layout comes from the leading `.format` directive:
`.format compact` (CAD compact stub) loads directly in CAD, `.format selfcontained`
produces the self-contained layout. Assembly syntax is documented in `docs/lasm.md`.

### link — multi-file linking

Merges several `.fas` files into one, renumbering symbols/functions and fixing
cross references:

```sh
atlispcc link lib1.fas lib2.fas main.fas -o combined.fas
```

At least two inputs are required; the default output name is based on the last input.

The linked output is **byte-for-byte identical** to compiling the same sources with
the CAD compiler (seg0 + seg1 + nsyms + items; `tests/cad/link/*_cad.fas` golden
regression). Real CAD can load it and call every function:
simple multi-function files (`add`/`mul`), cross-file references
(`square`/`sum-squares`), multi-file multi-argument cases (`f1`/`f2`/`f3`), and
duplicate names where the first definition wins.

```sh
atlispcc link lib.fas program.fas -o combined.fas
# In CAD: (load "combined.fas") then call every function from lib/program
```

### build-vlx — build a VRTLIB-1 VLX container

Packs `.fas` / `.dcl` / text members into the official **VRTLIB-1** container:

```sh
atlispcc build-vlx app.fas -o app.vlx
atlispcc build-vlx app.fas res/dlg.dcl readme.txt -o app.vlx --export main setup
atlispcc build-vlx app.fas -o app.vlx --no-separate-namespace --no-protected
atlispcc build-vlx --prv app.prv              # pack from a VLIDE .prv spec
atlispcc build-vlx --prv app.prv --json       # packing report (members/switches/errors)
atlispcc unpack-vlx app.vlx -o dist/app       # unpack (structural check by default)
atlispcc unpack-vlx app.vlx --stub load.lsp   # emit (load "…") loader stub
atlispcc info app.vlx                         # show the LOAD spec and member table
```

Container layout (byte-for-byte identical to AutoCAD `PRV`/`KLB` output):

```
"VRTLIB-1" + u32 footer offset
record #0  u32 total, u16 tag=1240, u8 len, "LOAD", LOAD spec text
record #n  u32 total, u16 tag,    u8 len, NAME,  payload   (each 4-byte aligned)
u32 0 + "VRTLIB-1" + u32 0                                (16-byte footer)
```

- Record tags: `1330` = `.fas`, `1350` = `.dcl`, `1335` = text, `1340` = `.dvb`
- Member names are the uppercased `basename` (DBCS double-byte pairs preserved);
  payloads are byte-identical to the standalone files
- LOAD spec: `((:protected . T) (:active-x . T) (:separate-namespace . T) (:load-file-list (:fas "app.fas") …))`
- `--export` compiles an extra `_VLX` export stub (`(vl-doc-export 'main)`) and
  appends it to the LOAD list
- Text/`.dvb` members are carried as resources only, never listed in the LOAD spec
- `--prv <file>` reads a Visual LISP application spec: `:lsp` members are compiled,
  `:prj` projects are built first, `:require-file-list` becomes resources; `:target`
  selects the default output (`-o` wins)
- `--date` / `--salt` also apply to packing (forwarded to the internal compile/link)
- `--prv --json` / `--report <path>`: structured packing report (`target` / `members` /
  `compiled` / `switches` / `errors` / `diagnostics`); exit code 1 means errors

### project — package/project batch build (CI / agents)

Reads `:FILES` from `pkg.lsp`, or `:OWN-LIST` from a Visual LISP `.prj`, compiles
every Lisp source and skips resources (`.pat` / `.dwg` / `.txt` …):

```sh
atlispcc project packages/at-landscape
atlispcc project packages/at-landscape -o dist/at-landscape -O2
atlispcc project packages/at-landscape --json --report build-report.json
atlispcc project packages/at-landscape --dry-run     # list files only
atlispcc project myapp.prj                           # Visual LISP project
```

`.prj` support:

```lisp
(VLISP-PROJECT-LIST
  :NAME "demo"
  :OWN-LIST ("src/a.lsp" "src/b" "src")     ; dirs are scanned recursively; .lsp is appended
  :PROJECT-KEYS (:BUILD (:OPTIMIZE :LINK) :SAFE-MODE T :MERGED T :MSGLEVEL 1)
  :FAS-DIRECTORY "./build")                  ; -o wins
```

- `:MERGED T` with ≥2 modules links them into `<NAME>.fas` (renamed to
  `<NAME>_merged.fas` if it would collide with a module)
- `:BUILD (:OPTIMIZE …)` without an explicit `-O` compiles with `-O1`
- `:REQUIRE` / `:LOAD` dependencies are appended after `:OWN-LIST`
- A single failure does not abort the batch (`--stop-on-error` changes that)
- Exit code: 0 when everything succeeds, 1 on compile errors or missing files
- `--json` prints `summary` (ok/error/missing/skipped) plus per-file
  `status/bytes/elapsed_ms/log`

### zelx — build a ZWCAD ZELX

Builds a ZWCAD `.zelx` distribution directly from `.lsp` or `.fas` (no LispConverter GUI):

```sh
atlispcc zelx app.lsp app.zelx      # .lsp is compiled to FAS4 first
atlispcc zelx app.fas app.zelx      # convert an existing .fas
```

- `.zelx` = `!ZAS` container: payload (resources) + segment-1 directory (function
  bytecode) + rolling XOR encryption
- The algorithm is reverse-engineered from ZWCAD `LispConverter.exe`; small/simple
  files are **byte-for-byte identical** to the official output (15/15 samples)
- Complex files (many symbols/top-level expressions) still need ZWCAD's compressed
  re-encoding (module-code re-encoding + symbol reordering); see `docs/zelx-format.md`

## Complete workflow

```sh
# 1. Compile Lisp → FAS (with optimization)
atlispcc compile -O2 source.lsp program.fas

# 2. Link several FAS files
atlispcc link lib.fas program.fas -o combined.fas

# 3. Decompile and validate
atlispcc decompile combined.fas combined.lsp
atlispcc validate combined.lsp
```

## Testing in CAD

**Automated live verification** (recommended):

```sh
make cad-test    # or: python scripts/cad_verify.py
```

`scripts/cad_verify.py` compiles t01–t24 + i18n, loads them in CAD and asserts the
return values (25 checks).

> **Auto-closing CAD modal dialogs**: CAD occasionally shows a modal dialog (an
> `alert` error box, a command-abort box) that blocks `atlisp-mcp` eval calls.
> `tools.cad_dialog_killer` closes them automatically:
>
> ```sh
> python -m tools.cad_dialog_killer <cad-pid> --watch --timeout-s 3600 &
> python -m tools.cad_dialog_killer all --watch --timeout-s 3600   # all CAD processes
> python -m tools.cad_dialog_killer <cad-pid>                      # one-shot scan
> ```
>
> The tool is C# (`tools/src/cad_dialog_killer.cs`) compiled to an exe on first run;
> it enumerates CAD windows, detects visible `#32770` dialogs and clicks their
> buttons. Verified to unblock MCP sessions (2026-08-08). Requires Windows + .NET
> Framework.

Manual testing:

```lisp
;; Load a compiled FAS file
(load "D:/atlisp-test/add.fas")
(add 2 3)  ;; → 5

;; Batch test
(load "D:/atlisp-test/test_all_final.lsp")
```

### Verified CAD compatibility (AutoCAD 24.1s)

| Feature | Status | Example |
|---------|--------|---------|
| Simple functions | ✅ | `(add 2 3)` → 5 |
| Recursion | ✅ | `(fact 5)` → 120 |
| if/while/cond | ✅ | `(sum-to 5)` → 15 |
| Local variables | ✅ | `(swap 1 2)` → (2 1) |
| String concatenation | ✅ | `(greet "CAD")` → "Hello, CAD!" |
| Cross-function references | ✅ | `(sum-sq 3 4)` → 25 |
| Tail recursion | ✅ | `(sum-tail 5 0)` → 15 |
| &optional/&rest | ✅ | `(f 3 2)` → 5, `(g 1 2 3)` → (1 (2 3)) |
| Pythagoras | ✅ | `(hypot 3 4)` → 5.0 |
| Top-level setq/set | ✅ | setq runs correctly before and after defuns |
| lambda/quote | ✅ | `(map-inc '(1 2 3))` → (2 3 4); lambda params localized |
| vla-/vlax- ActiveX | ✅ | `(t22-acad-doc)` returns the document object; output byte-identical to the CAD golden |
| `command` interaction | ✅ | `(t23-created-circle-p)` → T (draw → assert → clean up) |
| `*error*` handling | ✅ | `(t24-handler-test)` → "handler-ran" (live t24_star_error case) |
| **Multi-file linking** | ✅ | `atlispcc link` output is byte-identical to a direct CAD build; every function is callable in CAD (cross-file refs, multiple args, name collisions) |
| **VLX (VRTLIB-1)** | ✅ | `atlispcc build-vlx` output loads with `(load "app.vlx")`; `--export` functions are visible in the host namespace (`(SUBR 42)`), unexported ones stay isolated |

> A single-function file (`fun.lsp`) is byte-for-byte identical to the decrypted CAD
> compiler output.
> `CAD_T_SERIES_IDENTICAL` locks **6 byte-identity** cases (andor/and2/or2/andval +
> chinese + qsingle; the original t0X sources moved to `tests/compile_src/` and are
> covered by structural assertions); the split i18n modules are in the same regression.
> Link output matches the **3 CAD goldens** under `tests/cad/link/*_cad.fas`
> byte-for-byte.
> Live CAD verification: **25/25** (`scripts/cad_verify.py`, t01–t24 + i18n).
> **VLX live verification** (2026-11, AutoCAD 24.1s): `python scripts/cad_verify_vlx.py`
> builds a probe VLX, loads it, and asserts `(type vlx-probe)` = SUBR, the call returns
> 42, and the unexported function stays nil (separate-namespace isolation works).
>
> **@lisp kernel full comparison** (2026-08-27): all **67 `.lsp` files** under
> `../kernel/src/` are **byte-for-byte identical** to AutoCAD 24.1s output
> (`(vlisp-compile 'st ...)`) in seg0 + seg1 + nsyms, including conditional defun
> binding, native LET, vlax-for enumeration, nested defuns and `&optional`/`&rest`
> variadics. Status is re-checked with `scripts/kernel_compare_http.py` (ours→compare).
>
> **@lisp package atlisp_u full comparison** (2026-08-29): `tests/atlisp_u.lsp`
> (502 functions + 221 top-level forms) is **byte-for-byte identical** to the CAD
> golden `tests/atlisp_u_cad2.fas` in seg0+seg1+nsyms, covering commands+top-level
> gvar slot remapping, top-level kwote lambda func-obj slots, conditional defun mid
> emission and `set` protocol slots.

## Complete example

```sh
# compile → decompile → validate
atlispcc compile input.lsp input.fas
atlispcc decompile input.fas recovered.lsp
atlispcc validate recovered.lsp

# Decompile an in-repo CAD sample
atlispcc decompile tests/cad/i18n-cad.fas output.lsp
atlispcc validate output.lsp
```

## Package system (CL-style namespace)

### Syntax

```lisp
(defpackage vec
  (:use)
  (:export vec2 vec3))

(in-package vec)

(defun vec2 (x) (+ x 1))   ; internally mangled to vec|vec2

;; cross-package call:
(in-package app)
(defun foo (x) (vec:vec2 x))  ; resolved to vec|vec2 at compile time
```

### How it works

- CL-style packages operate at **compile time** and do not affect the FAS4 format
- Package-qualified function names are encoded as flat symbol names (`pkg|name`)
- The FAS4 binary format is unchanged, so every CAD can load the output
- The decompiler restores `pkg|name` → `pkg:name`
- Only `defun` names and `pkg:name` references are affected; locals are untouched

## Optimization levels

| Level | Description |
|-------|-------------|
| `-O0` | No optimization |
| `-O1` | Basic cleanup: `(+ 1 2)` → `3`, `(if T e1 e2)` → `e1`, `(progn x)` → `x` |
| `-O2` | Aggressive: `(setq x 3) (+ x 1)` → `(+ 3 1)`, removes unused `setq` |
| `-O3` | Extreme: inlines single-call functions, cross-function constant replacement, removes dead code after `exit`/`quit` |

## Helper tools

Analysis helpers in `tools/` (shipped with the pip package, runnable with `python -m`):

- `tools.fas-analyzer` — FAS4 file analysis (`--dump`/`--json`)
- `tools.fas-split` — function splitting (`--trim`/`--outdir`)
- `tools.decrypt_fas4` / `tools.crack_key` — decryption / key cracking
- `tools.find_key` — locate the XOR key inside a FAS
- `tools.validate` — syntax / dangerous function (`quit`/`exit`/`startapp`) / dangerous
  command (`command-s` invoking shell/del …) / unused-local checks for generated `.lsp`
- `tools.compare_lsp` — `.lsp` diff analysis
- `tools.zelx_info` / `tools.zelx_diff` / `tools.zelx_build` / `tools.zelx_to_fas` —
  ZWCAD `.zelx` inspect/diff/build/recover (reverse-engineered LispConverter)
- `tools.lisp_converter_auto` — ZWCAD LispConverter.exe GUI automation (sample generation)
- `tools.cad_probe` — MCP CAD interaction helper (development/debugging)
- `tools.cad_dialog_killer` — auto-close CAD modal dialogs (alert etc.) that block MCP
  sessions; `python -m tools.cad_dialog_killer <pid> [--watch]`
- `scripts/cad_verify.py` / `scripts/cad_verify_vlx.py` — live CAD verification
  (compiled-output assertions / VRTLIB-1 VLX loading with namespace exports; use
  `--remote-file probe.vlx --wait 5` when the shared directory has not refreshed)
- `tools.analyze_rosetta` — Rosetta code analysis

Usage and output are documented in `docs/development.md`.

## Compatibility

The decompiler adds wrapper helpers to avoid built-in name collisions:

- `fas-polar1` / `fas-rtos1` / `fas-rtos3`
- `fas-getvar2` / `fas-getvar3`
- `fas-1-`
- `in_param` / `fas-assoc-value`
- `fas-select-entity` / `projet_pa_projet_ar_projet`

Different CAD platforms may be unable to load another platform's `.fas` files, so
this project emits plain `.lsp` text.

## Limitations

- External dependencies (other `.fas`, `.vlx`, `.arx`, `.dcl`, `.odcl`, `.lsp` files)
  are not packaged automatically
- Some behavior is inferred from bytecode rather than recovered from original source
- Output may require manual cleanup

## Development

The repository ships Makefile shortcuts (`make help` lists them all):

```sh
make test        # full pytest suite
make check       # py_compile + pytest + disasm→asm round trip + byte-identity
make lint        # black --check + mypy
make format      # black formatting
make build       # build distributions
make clean       # remove build artifacts and caches
```

## Documentation

- `docs/cad-stub-format.md` — AutoCAD compact-stub format and compatibility notes (core)
- `docs/fas-format.md` — FAS4 binary format reference
- `docs/opcodes.md` — opcode reference
- `docs/vlx-format.md` — VLX (VRTLIB-1) container format, LOAD spec and validation
- `docs/lasm.md` — LASM assembly reference (disasm/asm text format)
- `docs/compilation-process.md` — how `.lsp` becomes `.fas`, stage by stage
- `docs/development.md` — architecture, pipeline, tests, coding conventions
- `docs/development-plan.md` — plan, known issues and roadmap
- `engine/` — SBCL AutoLISP runtime (`engine/atlisp.asd`), experimental cross-checker

## Security

Review decompiled `.lsp` output before use, and test it in an empty drawing first:
some commands can create, modify or delete drawing entities.
