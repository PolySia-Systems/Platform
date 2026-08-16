.PHONY: install test lint typecheck standards security dependency-audit build sbom check health readiness runbook release-manifest deploy-check final-handoff

install:
	python -m pip install -e ".[dev]"

test:
	python -m pytest

lint:
	python -m ruff check .

typecheck:
	python -m mypy src

standards:
	python scripts/validate_standards.py --mode full --allow-baseline

security:
	python -m polysia.security.secret_scan

dependency-audit:
	python -m pip_audit --strict --vulnerability-service osv

build:
	python -m build

sbom:
	cyclonedx-py environment --output-format JSON --output-file artifacts/sbom.json

check: lint typecheck standards test security
	python -m pip check

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
