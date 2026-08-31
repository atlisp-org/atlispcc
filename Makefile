# atlispcc — 开发/构建/测试 Makefile
#
# 常用目标:
#   make            # 默认: test（等价 make test）
#   make test       # pytest 全量测试
#   make check      # 一键全量检查（scripts/run_tests.sh: py_compile+pytest+往返+byte-identity）
#   make lint       # black 格式检查（--check）+ mypy 类型检查
#   make format     # black 格式化
#   make mypy       # mypy 类型检查
#   make build      # 构建分发包（wheel + sdist）
#   make publish    # twine check + 上传 PyPI（需 TWINE_USERNAME/PASSWORD）
#   make install    # pip install -e .[dev]（开发模式）
#   make clean      # 清理构建产物/缓存
#   make help       # 列出所有目标

PY      ?= python
PYTEST  ?= $(PY) -m pytest
BLACK   ?= $(PY) -m black
MYPY    ?= $(PY) -m mypy
BUILD   ?= $(PY) -m build
TWINE   ?= $(PY) -m twine

.PHONY: all test check cad-test lint format mypy build publish install clean help
.PHONY: validate-lib validate-pkg validate-all
.PHONY: cad-lib cad-pkg cad-all
.PHONY: compare-lib compare-pkg compare-all

all: test

## 运行 pytest 全量测试
test:
	$(PYTEST) -q

## 一键全量检查（py_compile + pytest + disasm→asm 往返 + byte-identity 状态）
check:
	bash scripts/run_tests.sh

## CAD 真机验证（需 CAD 已连接）
cad-test:
	bash scripts/run_tests.sh --cad

## 格式检查 + 类型检查（CI 用）
lint:
	$(BLACK) --check .
	$(MYPY) . --ignore-missing-imports

## black 自动格式化
format:
	$(BLACK) .

## mypy 类型检查
mypy:
	$(MYPY) . --ignore-missing-imports

## 构建分发包（dist/ 下的 wheel + sdist）
build:
	$(BUILD)

## twine check + 上传 PyPI
publish: build
	$(TWINE) check dist/*
	$(TWINE) upload dist/*

## 安装开发依赖（可编辑模式）
install:
	pip install -e ".[dev]"

## 清理构建产物与缓存
clean:
	rm -rf build/ dist/ *.egg-info .pytest_cache .mypy_cache
	find . -name __pycache__ -type d -prune -exec rm -rf {} +

## ============================================================
## 批量测试 lib/kernel/packages（无需 CAD 真机）
## ============================================================

## 快速验证 lib/src（编译检查，不对比）
validate-lib:
	$(PY) scripts/quick_validate.py --src ../lib/src

## 快速验证 packages（编译检查，不对比）
validate-pkg:
	$(PY) scripts/quick_validate.py --src ../packages

## 快速验证 kernel/src（编译检查，不对比）
validate-kernel:
	$(PY) scripts/quick_validate.py --src ../kernel/src

## 快速验证全部
validate-all: validate-lib validate-pkg validate-kernel

## ============================================================
## CAD 真机编译生成 golden（需 CAD 连接 + MCP）
## ============================================================

## CAD 编译 lib/src → tests/cad/lib_golden/
cad-lib:
	$(PY) scripts/batch_compare.py cad \
		--src ../lib/src \
		--golden tests/cad/lib_golden \
		--cad-root W:/atlisp/lib/src

## CAD 编译 packages → tests/cad/packages_golden/
cad-pkg:
	$(PY) scripts/batch_compare.py cad \
		--src ../packages \
		--golden tests/cad/packages_golden \
		--cad-root W:/atlisp/packages

## CAD 编译 kernel/src → tests/cad/kernel_golden/
cad-kernel:
	$(PY) scripts/batch_compare.py cad \
		--src ../kernel/src \
		--golden tests/cad/kernel_golden \
		--cad-root W:/atlisp/kernel/src

## CAD 编译全部
cad-all: cad-lib cad-pkg cad-kernel

## ============================================================
## atlispcc 编译 + 对比（无需 CAD，需先有 golden）
## ============================================================

## atlispcc 编译 lib/src
ours-lib:
	$(PY) scripts/batch_compare.py ours \
		--src ../lib/src \
		--ours /tmp/opencode/lib-ours

## atlispcc 编译 packages
ours-pkg:
	$(PY) scripts/batch_compare.py ours \
		--src ../packages \
		--ours /tmp/opencode/packages-ours

## atlispcc 编译 kernel/src
ours-kernel:
	$(PY) scripts/batch_compare.py ours \
		--src ../kernel/src \
		--ours /tmp/opencode/kernel-ours

## 对比 lib（需先 golden + ours）
compare-lib:
	$(PY) scripts/batch_compare.py compare \
		--src ../lib/src \
		--golden tests/cad/lib_golden \
		--ours /tmp/opencode/lib-ours

## 对比 packages
compare-pkg:
	$(PY) scripts/batch_compare.py compare \
		--src ../packages \
		--golden tests/cad/packages_golden \
		--ours /tmp/opencode/packages-ours

## 对比 kernel
compare-kernel:
	$(PY) scripts/batch_compare.py compare \
		--src ../kernel/src \
		--golden tests/cad/kernel_golden \
		--ours /tmp/opencode/kernel-ours

## 对比全部
compare-all: compare-lib compare-pkg compare-kernel

## 一键: atlispcc 编译 + 对比（需先有 golden）
test-lib: ours-lib compare-lib
test-pkg: ours-pkg compare-pkg
test-kernel: ours-kernel compare-kernel
test-batch: test-lib test-pkg test-kernel

## ============================================================
## 列出所有目标
## ============================================================
help:
	@echo "atlispcc Makefile 目标:"
	@echo ""
	@echo "=== 基础测试 ==="
	@echo "  test          pytest 全量测试"
	@echo "  check         一键全量检查 (run_tests.sh)"
	@echo "  cad-test      CAD 真机验证 (cad_verify.py)"
	@echo ""
	@echo "=== 批量验证（无需 CAD）==="
	@echo "  validate-lib  快速验证 lib/src 编译"
	@echo "  validate-pkg  快速验证 packages 编译"
	@echo "  validate-kernel  快速验证 kernel/src 编译"
	@echo "  validate-all  快速验证全部"
	@echo ""
	@echo "=== CAD 编译 golden（需 CAD 连接）==="
	@echo "  cad-lib       CAD 编译 lib/src → lib_golden/"
	@echo "  cad-pkg       CAD 编译 packages → packages_golden/"
	@echo "  cad-kernel    CAD 编译 kernel/src → kernel_golden/"
	@echo "  cad-all       CAD 编译全部"
	@echo ""
	@echo "=== 编译+对比 ==="
	@echo "  ours-lib      atlispcc 编译 lib/src"
	@echo "  ours-pkg      atlispcc 编译 packages"
	@echo "  ours-kernel   atlispcc 编译 kernel/src"
	@echo "  compare-lib   对比 lib（需 golden + ours）"
	@echo "  compare-pkg   对比 packages"
	@echo "  compare-kernel 对比 kernel"
	@echo "  compare-all   对比全部"
	@echo "  test-lib      lib 编译+对比"
	@echo "  test-pkg      packages 编译+对比"
	@echo "  test-kernel   kernel 编译+对比"
	@echo "  test-batch    全部编译+对比"
	@echo ""
	@echo "=== 代码质量 ==="
	@echo "  lint          black --check + mypy"
	@echo "  format        black 格式化"
	@echo "  mypy          mypy 类型检查"
	@echo ""
	@echo "=== 构建/发布 ==="
	@echo "  build         构建分发包"
	@echo "  publish       上传 PyPI"
	@echo "  install       开发模式安装"
	@echo "  clean         清理构建产物"
