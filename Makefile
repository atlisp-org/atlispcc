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

## 列出所有目标
help:
	@echo "atlispcc 开发 Makefile 目标:"
	@echo "  test        运行 pytest 全量测试"
	@echo "  check       一键全量检查 (scripts/run_tests.sh)"
	@echo "  cad-test    CAD 真机验证 (scripts/cad_verify.py，需 CAD 连接)"
	@echo "  lint        black --check + mypy 类型检查"
	@echo "  format      black 自动格式化"
	@echo "  mypy        mypy 类型检查"
	@echo "  build       构建分发包 (wheel + sdist)"
	@echo "  publish     twine check + 上传 PyPI"
	@echo "  install     pip install -e .[dev]"
	@echo "  clean       清理构建产物与缓存"
