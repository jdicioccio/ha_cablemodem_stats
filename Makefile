# Simple developer Makefile for ha_cablemodem_stats
#
# This is intentionally lightweight. Most Python projects don't need a heavy
# Makefile, but having `make test` is convenient and not considered taboo.

.PHONY: help test test-parser clean

help:
	@echo "Common developer targets:"
	@echo "  make test          - Run the full test suite"
	@echo "  make test-parser   - Run only the parser regression tests (fastest feedback)"
	@echo "  make clean         - Remove Python cache files"

test:
	@source .venv/bin/activate 2>/dev/null || true; \
	python -m pytest

test-parser:
	@source .venv/bin/activate 2>/dev/null || true; \
	python -m pytest tests/test_parser.py -q

clean:
	find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	find . -name "*.pyc" -delete 2>/dev/null || true
	rm -rf .pytest_cache 2>/dev/null || true
