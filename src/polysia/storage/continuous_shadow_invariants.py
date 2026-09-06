"""Reusable Stage 4B accounting and publication invariant evaluator.

Decimal identities are reconstructed in Python. SQLite SUM() is not used because
it would coerce TEXT financial columns to binary floating point.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from decimal import Decimal

ACCOUNTING_BLOCKED = "accounting_blocked"
DUPLICATE_PROCESSING = "duplicate_processing"
_ZERO = Decimal("0")
_TOLERANCE = Decimal("0.000001")

_ACCOUNTING_VIOLATIONS = (
    "cash_mismatch",
    "realized_pnl_mismatch",
    "fee_mismatch",
    "position_quantity_mismatch",
    "cost_basis_mismatch",
    "orphan_ledger_position",
)


class ContinuousShadowInvariantError(RuntimeError):
    """Raised when accounting or publication invariants block progress."""

    def __init__(
        self,
        message: str,
        *,
        error_code: str,
        processing_stage: str,
        violations: tuple[str, ...] = (),
    ) -> None:
        super().__init__(message)
        self.error_code = error_code
        self.processing_stage = processing_stage
        self.violations = violations


@dataclass(frozen=True, slots=True)
class ShadowInvariantReport:
    accounting_passed: bool
    publication_passed: bool
    ledger_balanced: bool
    duplicate_processing_count: int
    accounting_violations: tuple[str, ...]
    publication_violations: tuple[str, ...]

    @property
    def passed(self) -> bool:
        return self.accounting_passed and self.publication_passed

    @property
    def block_code(self) -> str | None:
        if not self.accounting_passed:
            return ACCOUNTING_BLOCKED
        if not self.publication_passed:
            if "duplicate_processing" in self.publication_violations:
                return DUPLICATE_PROCESSING
            return ACCOUNTING_BLOCKED
        return None


def evaluate_shadow_invariants(
    connection: sqlite3.Connection,
    experiment_id: str,
    *,
    current_poll_run_id: str | None = None,
) -> ShadowInvariantReport:
    """Evaluate committed or tentative same-transaction Stage 4B state."""
    accounting_violations = _accounting_violations(connection, experiment_id)
    duplicate_processing_count = duplicate_processing_rows(connection, experiment_id)
    publication_violations: list[str] = []
    if duplicate_processing_count:
        publication_violations.append("duplicate_processing")
    publication_violations.extend(
        _journal_evaluation_violations(connection, experiment_id)
    )
    publication_violations.extend(
        _checkpoint_violations(
            connection,
            experiment_id,
            current_poll_run_id=current_poll_run_id,
        )
    )
    accounting_passed = not accounting_violations
    publication_passed = not publication_violations
    return ShadowInvariantReport(
        accounting_passed=accounting_passed,
        publication_passed=publication_passed,
        ledger_balanced=accounting_passed,
        duplicate_processing_count=duplicate_processing_count,
        accounting_violations=tuple(accounting_violations),
        publication_violations=tuple(publication_violations),
    )


def ledger_is_balanced(connection: sqlite3.Connection, experiment_id: str) -> bool:
    return evaluate_shadow_invariants(connection, experiment_id).ledger_balanced


def duplicate_processing_rows(
    connection: sqlite3.Connection,
    experiment_id: str,
) -> int:
    journal = connection.execute(
        "SELECT COALESCE(SUM(row_count - 1), 0) FROM ("
        "SELECT j.event_id, COUNT(*) AS row_count "
        "FROM continuous_shadow_event_journal j "
        "JOIN continuous_shadow_poll_runs p ON p.poll_run_id = j.first_poll_run_id "
        "WHERE p.experiment_id = ? GROUP BY j.event_id HAVING COUNT(*) > 1)",
        (experiment_id,),
    ).fetchone()
    evaluations = connection.execute(
        "SELECT COALESCE(SUM(row_count - 1), 0) FROM ("
        "SELECT event_id, portfolio_id, COUNT(*) AS row_count "
        "FROM continuous_shadow_evaluations WHERE experiment_id = ? "
        "GROUP BY event_id, portfolio_id HAVING COUNT(*) > 1)",
        (experiment_id,),
    ).fetchone()
    return int(journal[0]) + int(evaluations[0])


def _accounting_violations(
    connection: sqlite3.Connection,
    experiment_id: str,
) -> list[str]:
    violations: list[str] = []
    portfolio_rows = connection.execute(
        "SELECT portfolio_id, initial_cash, cash, realized_pnl, fees "
        "FROM continuous_shadow_portfolios WHERE experiment_id = ?",
        (experiment_id,),
    ).fetchall()
    ledger_rows = connection.execute(
        "SELECT portfolio_id, market_reference, outcome_reference, quantity_delta, "
        "cash_delta, cost_basis_delta, realized_pnl_delta, fee_delta "
        "FROM continuous_shadow_ledger WHERE experiment_id = ?",
        (experiment_id,),
    ).fetchall()
    portfolio_totals: dict[str, tuple[Decimal, Decimal, Decimal]] = {}
    position_totals: dict[tuple[str, str, str], tuple[Decimal, Decimal]] = {}
    for ledger_row in ledger_rows:
        portfolio_id = str(ledger_row["portfolio_id"])
        cash, realized, fees = portfolio_totals.get(
            portfolio_id, (_ZERO, _ZERO, _ZERO)
        )
        portfolio_totals[portfolio_id] = (
            cash + Decimal(str(ledger_row["cash_delta"])),
            realized + Decimal(str(ledger_row["realized_pnl_delta"])),
            fees + Decimal(str(ledger_row["fee_delta"])),
        )
        if (
            ledger_row["market_reference"] is not None
            and ledger_row["outcome_reference"] is not None
        ):
            key = (
                portfolio_id,
                str(ledger_row["market_reference"]),
                str(ledger_row["outcome_reference"]),
            )
            quantity, cost_basis = position_totals.get(key, (_ZERO, _ZERO))
            position_totals[key] = (
                quantity + Decimal(str(ledger_row["quantity_delta"])),
                cost_basis + Decimal(str(ledger_row["cost_basis_delta"])),
            )
    for row in portfolio_rows:
        totals = portfolio_totals.get(str(row["portfolio_id"]), (_ZERO, _ZERO, _ZERO))
        expected_cash = Decimal(str(row["initial_cash"])) + totals[0]
        if abs(expected_cash - Decimal(str(row["cash"]))) > _TOLERANCE:
            violations.append("cash_mismatch")
        if abs(totals[1] - Decimal(str(row["realized_pnl"]))) > _TOLERANCE:
            violations.append("realized_pnl_mismatch")
        if abs(totals[2] - Decimal(str(row["fees"]))) > _TOLERANCE:
            violations.append("fee_mismatch")
    position_rows = connection.execute(
        "SELECT portfolio_id, market_reference, outcome_reference, quantity, cost_basis "
        "FROM continuous_shadow_positions WHERE experiment_id = ?",
        (experiment_id,),
    ).fetchall()
    current_position_keys: set[tuple[str, str, str]] = set()
    for row in position_rows:
        key = (
            str(row["portfolio_id"]),
            str(row["market_reference"]),
            str(row["outcome_reference"]),
        )
        current_position_keys.add(key)
        position_total = position_totals.get(key, (_ZERO, _ZERO))
        if abs(position_total[0] - Decimal(str(row["quantity"]))) > _TOLERANCE:
            violations.append("position_quantity_mismatch")
        if abs(position_total[1] - Decimal(str(row["cost_basis"]))) > _TOLERANCE:
            violations.append("cost_basis_mismatch")
    for key, (quantity, cost_basis) in position_totals.items():
        if key not in current_position_keys and (
            abs(quantity) > _TOLERANCE or abs(cost_basis) > _TOLERANCE
        ):
            violations.append("orphan_ledger_position")
    ordered: list[str] = []
    seen: set[str] = set()
    for name in _ACCOUNTING_VIOLATIONS:
        if name in violations and name not in seen:
            ordered.append(name)
            seen.add(name)
    return ordered


def _journal_evaluation_violations(
    connection: sqlite3.Connection,
    experiment_id: str,
) -> list[str]:
    missing = connection.execute(
        "SELECT 1 FROM continuous_shadow_evaluations e "
        "WHERE e.experiment_id = ? AND NOT EXISTS ("
        "SELECT 1 FROM continuous_shadow_event_journal j "
        "JOIN continuous_shadow_poll_runs p ON p.poll_run_id = j.first_poll_run_id "
        "WHERE j.event_id = e.event_id AND p.experiment_id = e.experiment_id"
        ") LIMIT 1",
        (experiment_id,),
    ).fetchone()
    if missing is not None:
        return ["journal_evaluation_inconsistent"]
    return []


def _checkpoint_violations(
    connection: sqlite3.Connection,
    experiment_id: str,
    *,
    current_poll_run_id: str | None,
) -> list[str]:
    row = connection.execute(
        "SELECT c.last_poll_run_id, p.status "
        "FROM continuous_shadow_checkpoint c "
        "LEFT JOIN continuous_shadow_poll_runs p ON p.poll_run_id = c.last_poll_run_id "
        "WHERE c.experiment_id = ?",
        (experiment_id,),
    ).fetchone()
    if row is None:
        return []
    last_poll_run_id = str(row["last_poll_run_id"])
    status = row["status"]
    if current_poll_run_id is not None and last_poll_run_id == current_poll_run_id:
        return ["checkpoint_advanced_before_commit"]
    if status is not None and str(status) != "succeeded":
        return ["checkpoint_poll_not_succeeded"]
    return []
