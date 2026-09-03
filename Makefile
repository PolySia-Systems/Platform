.PHONY: install fast test lint typecheck standards security dependency-audit build sbom check health readiness runbook release-manifest deploy-check final-handoff dependency-locks-check dependency-locks

install:
	python -m pip install -e ".[dev]"

fast:
	python scripts/fast_check.py

test:
	python -m pytest

lint:
	python -m ruff check .

typecheck:
	python -m mypy src

standards:
	python scripts/validate_standards.py --mode full

security:
	python -m polysia.security.secret_scan

dependency-audit:
	python -m pip_audit --strict --vulnerability-service osv

build:
	python -m build

sbom:
	cyclonedx-py environment --output-format JSON --output-file artifacts/sbom.json

dependency-locks-check:
	python scripts/dependency_locks.py check

dependency-locks:
	python scripts/dependency_locks.py refresh --scope pip --upgrade

check: lint typecheck standards test security
	python -m pip check
	python scripts/dependency_locks.py check

health:
	python -m polysia.cli system health

readiness:
	python -m polysia.cli ops deployment-readiness

runbook:
	python -m polysia.cli system runbook

release-manifest:
	python -m polysia.cli ops release-manifest

deploy-check:
	python -m polysia.cli ops deployment-automation

final-handoff:
	python -m polysia.cli ops final-handoff
