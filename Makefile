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
	python -m pm_trader.cli health

readiness:
	python -m pm_trader.cli deployment-readiness

runbook:
	python -m pm_trader.cli operator-runbook

release-manifest:
	python -m pm_trader.cli release-manifest

deploy-check:
	python -m pm_trader.cli deployment-automation

final-handoff:
	python -m pm_trader.cli final-handoff
