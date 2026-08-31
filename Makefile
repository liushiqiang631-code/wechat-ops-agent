.PHONY: install test lint verify serve

install:
	python -m pip install -e ".[dev]"

test:
	python -m pytest -q

lint:
	ruff check app tests scripts

verify:
	python scripts/verify_release.py

serve:
	python -m app.cli serve

