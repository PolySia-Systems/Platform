# Verify Delivery

This folder is a delivery-ready copy of the Polymarket Trading System at:

```text
fb00357 Fix Phase 36 secure env bridge
```

It is intended to represent the approved Phase 36 project state.

## Environment

Use the existing conda environment:

```powershell
conda activate polymarket
cd "C:\Users\Siamak\Documents\Polymarket Python SDK"
python -m pip install -e ".[dev]"
```

## Quality Checks

Run these checks before delivery:

```powershell
python -m pytest
python -m ruff check .
python -m mypy src
git status --short --branch
```

Expected result:

- Tests pass.
- Ruff passes.
- Mypy passes.
- Git worktree is clean after committed delivery docs.

## Basic Runtime Checks

```powershell
python -m pm_trader.cli health
python -m pm_trader.cli final-handoff --require-clean-git
```

## Safety Notes

- Default mode remains `DATA_ONLY`.
- Live trading remains disabled unless explicitly enabled by environment flags.
- `.env` is present in this delivery folder and contains real secrets.
- Do not publish this folder without removing `.env`.
- No later-phase files are included in this delivery copy.
