"""Provider-free reporting over a consistent, private financial snapshot."""

from __future__ import annotations

import csv
import hashlib
import io
import json
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from polysia.backtesting import prospective_economics, shadow_opportunity_replay
from polysia.backtesting.shadow_opportunity_replay import replay_shadow_opportunities
from polysia.deployment.sqlite_backup import backup_sqlite_database
from polysia.domain.research_evidence import replay as research_replay
from polysia.storage.continuous_shadow import ContinuousShadowRepository


class UnsupportedReportingWindow(ValueError):
    """The retained evidence cannot reconstruct the requested calendar bounds."""


class ShadowReportingService:
    """Share canonical accounting between CLI, export jobs and Console."""

    def __init__(self, database: Path) -> None:
        self._database = database

    def report(
        self,
        experiment_id: str,
        *,
        limit: int = 100,
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> dict[str, Any]:
        # Backup handles WAL consistently and bounds copy time. Never initialize
        # or migrate the input and never copy live DB/WAL files separately.
        with TemporaryDirectory(prefix="polysia-report-") as directory:
            snapshot = backup_sqlite_database(
                self._database,
                Path(directory),
                keep=1,
                timeout_seconds=20,
            )
            store = ContinuousShadowRepository(snapshot.backup_path)
            operational = store.results(experiment_id, limit=limit)
            comparison = store.opportunity_report(
                experiment_id,
                include_financial_state=True,
                include_retained_evidence=start is not None or end is not None,
            )
        if start is not None or end is not None:
            comparison["selected_window"] = _selected_window(
                comparison,
                operational,
                experiment_id=experiment_id,
                start=start,
                end=end,
            )
        # Operational health is sampled against wall time and belongs outside
        # the analytical digest. A temporary filesystem path is not evidence ID.
        analytical = dict(comparison)
        analytical["report_scope"] = "session_cumulative; selected_window is separately bounded"
        engine_paths = {
            "reporting_service": Path(__file__),
            "prospective_economics": Path(prospective_economics.__file__),
            "shadow_opportunity_replay": Path(shadow_opportunity_replay.__file__),
            "research_replay": Path(research_replay.__file__),
        }
        analytical["reporter_code_digests"] = {
            name: hashlib.sha256(path.read_text(encoding="utf-8").encode()).hexdigest()
            for name, path in engine_paths.items()
        }
        raw_supporting = analytical.get("supporting_artifacts", {})
        if not isinstance(raw_supporting, dict):
            raise ValueError("invalid supporting evidence")
        supporting = dict(raw_supporting)
        supporting.pop("snapshot_database", None)
        analytical["supporting_artifacts"] = supporting
        canonical = json.dumps(analytical, sort_keys=True, separators=(",", ":"))
        return {
            "schema_version": "platform-shadow-report/v1",
            "scope": (
                "selected_utc_interval_with_reconstructed_opening_state"
                if start is not None
                else "single_financial_session_inception_to_retained_cutoff"
            ),
            "provider_calls": 0,
            "analytical": analytical,
            "analytical_digest": hashlib.sha256(canonical.encode()).hexdigest(),
            "operational": operational,
            "limitations": [
                "Separately funded financial sessions are not compounded.",
                "Unsupported calendar boundaries require retained opening state and marks.",
                "Zero simulations are no measurable profitability evidence.",
            ],
        }


def _selected_window(
    comparison: dict[str, Any],
    operational: dict[str, Any],
    *,
    experiment_id: str,
    start: datetime | None,
    end: datetime | None,
) -> dict[str, Any]:
    if start is None or end is None:
        raise UnsupportedReportingWindow("paired_increasing_bounds_required")
    if any(value.utcoffset() != timedelta(0) for value in (start, end)):
        raise UnsupportedReportingWindow("UTC_bounds_required")
    if start >= end:
        raise UnsupportedReportingWindow("paired_increasing_bounds_required")
    first = datetime.fromisoformat(operational["experiment"]["started_at"])
    cutoff = comparison.get("source_poll_cutoff")
    if cutoff is None or start < first or end > datetime.fromisoformat(cutoff):
        raise UnsupportedReportingWindow("range_outside_retained_financial_session")
    retained = comparison.pop("retained_evidence")
    rows, settlements = retained["opportunities"], retained["settlements"]

    def at(boundary: datetime) -> dict[str, Any]:
        prefix = tuple(row for row in rows if datetime.fromisoformat(row["decision_at"]) < boundary)
        marks = tuple(
            row for row in settlements if datetime.fromisoformat(row["observed_at"]) < boundary
        )
        replay: dict[str, Any] = replay_shadow_opportunities(
            prefix,
            experiment_id=experiment_id,
            settlements=marks,
            include_financial_state=True,
        )
        for name in ("control", "target"):
            state = replay["financial_state"][name]
            if state["net_result"] is None:
                raise UnsupportedReportingWindow("boundary_valuation_unavailable")
            for position in state["closing_positions"]:
                recent = any(
                    row["market_reference"] == position["market_reference"]
                    and row["outcome_reference"] == position["outcome_reference"]
                    and isinstance(row.get("book_bids"), list)
                    and row["book_bids"]
                    and isinstance(row.get("book_at"), str)
                    and timedelta(0)
                    <= boundary - datetime.fromisoformat(row["book_at"])
                    <= timedelta(milliseconds=int(row.get("maximum_quote_age_ms", 30_000)))
                    for row in prefix
                )
                if not recent:
                    raise UnsupportedReportingWindow("boundary_mark_not_retained_or_stale")
        return replay

    opening, closing = at(start), at(end)
    policies = {}
    for name in ("control", "target"):
        left, right = opening["financial_state"][name], closing["financial_state"][name]
        policies[name] = {
            "opening_cash": left["closing_cash"],
            "opening_positions": left["closing_positions"],
            "closing_cash": right["closing_cash"],
            "closing_positions": right["closing_positions"],
            "capital_flows": "0",
            "net_result": format(Decimal(right["net_result"]) - Decimal(left["net_result"]), "f"),
            "realized_before_fees": format(
                Decimal(right["realized_before_fees"]) - Decimal(left["realized_before_fees"]), "f"
            ),
            "unrealized_after_hypothetical_exit_fees": format(
                Decimal(right["unrealized_after_hypothetical_exit_fees"])
                - Decimal(left["unrealized_after_hypothetical_exit_fees"]),
                "f",
            ),
            "hypothetical_exit_fees": format(
                Decimal(right["hypothetical_exit_fees"]) - Decimal(left["hypothetical_exit_fees"]),
                "f",
            ),
            "recorded_fees": format(
                Decimal(right["recorded_fees"]) - Decimal(left["recorded_fees"]), "f"
            ),
            "fill_embedded_slippage": format(
                Decimal(right["fill_embedded_slippage"]) - Decimal(left["fill_embedded_slippage"]),
                "f",
            ),
            "opening_liquidation_value": left["known_liquidation_value"],
            "closing_liquidation_value": right["known_liquidation_value"],
            "operating_costs": "UNALLOCATED_NOT_INCLUDED",
        }
    return {
        "start": start.isoformat(),
        "end": end.isoformat(),
        "boundary_convention": "[start,end)",
        **policies,
        "target_minus_control": format(
            Decimal(policies["target"]["net_result"]) - Decimal(policies["control"]["net_result"]),
            "f",
        ),
        "observation_count": sum(
            start <= datetime.fromisoformat(row["decision_at"]) < end for row in rows
        ),
        "drawdown_scope": "session_cumulative_cost_basis; interval_mark_drawdown_unsupported",
    }


def comparison_csv(report: dict[str, Any]) -> str:
    """Export the same canonical JSON fields without calculating another result."""
    output = io.StringIO(newline="")
    writer = csv.writer(output)
    window = report["analytical"].get("selected_window")
    if window:
        writer.writerow(
            (
                "analytical_digest",
                "start",
                "end",
                "policy",
                "opening_cash",
                "closing_cash",
                "net_result",
                "recorded_fees",
                "fill_embedded_slippage",
            )
        )
        for name in ("control", "target"):
            state = window[name]
            writer.writerow(
                (
                    report["analytical_digest"],
                    window["start"],
                    window["end"],
                    name,
                    *(
                        state[key]
                        for key in (
                            "opening_cash",
                            "closing_cash",
                            "net_result",
                            "recorded_fees",
                            "fill_embedded_slippage",
                        )
                    ),
                )
            )
        return output.getvalue()
    economic = report["analytical"]["report"]
    fields = (
        "policy",
        "cash",
        "gross_pnl",
        "fees",
        "slippage",
        "net_pnl",
        "valuation_status",
        "evaluated",
        "rejected",
    )
    writer.writerow(("analytical_digest", *fields))
    for name in ("control", "target"):
        row = economic[name]
        writer.writerow((report["analytical_digest"], *(row.get(key) for key in fields)))
    return output.getvalue()
