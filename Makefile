.PHONY: demo test check
demo:
	python examples/run_demo.py
test:
	python -m pytest
check:
	python -m ruff check src tests examples
	python -m ruff format --check src tests examples
	python -m mypy src/dataloom
