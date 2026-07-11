.PHONY: install test lint typecheck health readiness runbook release-manifest deploy-check final-handoff

install:
	python -m pip install -e ".[dev]"

test:
	python -m pytest

lint:
	python -m ruff check .

typecheck:
	python -m mypy src

health:
	python -m polysia.cli health

readiness:
	python -m polysia.cli deployment-readiness

runbook:
	python -m polysia.cli operator-runbook

release-manifest:
	python -m polysia.cli release-manifest

deploy-check:
	python -m polysia.cli deployment-automation

final-handoff:
	python -m polysia.cli final-handoff
