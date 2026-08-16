"""Run the bounded, read-only PolySia Copy Trading Stage 1 probe."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

from polysia.adapters.polymarket.copytrading_source import (
    PolymarketCopyTradingSource,
    PolymarketCopyTradingSourceError,
    PolymarketSourceCoverage,
)
from polysia.application.ports import LeaderTradeCheckpoint
from polysia.domain.copytrading import (
    LeaderPositionEffect,
    LeaderTradeEvent,
    classify_position_effects,
    deduplicate_leader_trade_events,
)

LEADER_ADDRESS_ENV = "POLYSIA_COPYTRADING_LEADER_ADDRESS"
LEADER_ALIAS = "leader-001"


def main() -> int:
    args = _parse_args()
    wallet = os.getenv(LEADER_ADDRESS_ENV, "").strip()
    if not wallet:
        raise SystemExit(
            f"Set {LEADER_ADDRESS_ENV} in the current process; do not store it in Git."
        )
    report = asyncio.run(
        _run_probe(
            wallet=wallet,
            output_dir=args.output_dir,
            window_minutes=args.window_minutes,
            page_size=args.page_size,
            max_pages=args.max_pages,
        )
    )
    print(
        json.dumps(
            {
                "decision": report["decision"],
                "normalized_events": report["valid_normalized_events"],
                "output_dir": str(args.output_dir),
                "raw_wallet_printed": False,
            },
            sort_keys=True,
        )
    )
    return 0 if report["decision"] != "NO_GO" else 2


async def _run_probe(
    *,
    wallet: str,
    output_dir: Path,
    window_minutes: int,
    page_size: int,
    max_pages: int,
) -> dict[str, Any]:
    ended_at = datetime.now(UTC).replace(microsecond=0)
    started_at = ended_at - timedelta(minutes=window_minutes)
    source = PolymarketCopyTradingSource({LEADER_ALIAS: wallet})
    checkpoint: LeaderTradeCheckpoint | None = None
    collected: list[LeaderTradeEvent] = []
    raw_count = 0
    filtered_count = 0
    rejected_count = 0
    page_duplicate_count = 0
    pages_read = 0
    source_errors: list[str] = []

    for _ in range(max_pages):
        try:
            page = await source.read_page(
                LEADER_ALIAS,
                start_at=started_at,
                end_at=ended_at,
                page_size=page_size,
                checkpoint=checkpoint,
            )
        except PolymarketCopyTradingSourceError as error:
            source_errors.append(str(error))
            break
        pages_read += 1
        raw_count += page.raw_count
        filtered_count += page.filtered_count
        rejected_count += page.rejected_count
        page_duplicate_count += page.duplicate_count
        collected.extend(page.events)
        checkpoint = page.next_checkpoint
        if checkpoint is None:
            break

    unique, cross_page_duplicate_count = deduplicate_leader_trade_events(collected)
    classified = classify_position_effects(unique)
    coverage: PolymarketSourceCoverage | None = None
    try:
        coverage = await source.probe_source_coverage(
            LEADER_ALIAS,
            start_at=started_at,
            end_at=ended_at,
            page_limit=min(500, max(page_size, 100)),
        )
    except PolymarketCopyTradingSourceError as error:
        source_errors.append(str(error))

    duplicate_count = page_duplicate_count + cross_page_duplicate_count
    report = _quality_report(
        events=classified,
        coverage=coverage,
        started_at=started_at,
        ended_at=ended_at,
        pages_read=pages_read,
        raw_count=raw_count,
        filtered_count=filtered_count,
        rejected_count=rejected_count,
        duplicate_count=duplicate_count,
        source_errors=source_errors,
        truncated=checkpoint is not None,
    )
    _write_artifacts(
        output_dir=output_dir,
        events=classified,
        report=report,
        forbidden_wallet=wallet,
    )
    return report


def _quality_report(
    *,
    events: tuple[LeaderTradeEvent, ...],
    coverage: PolymarketSourceCoverage | None,
    started_at: datetime,
    ended_at: datetime,
    pages_read: int,
    raw_count: int,
    filtered_count: int,
    rejected_count: int,
    duplicate_count: int,
    source_errors: list[str],
    truncated: bool,
) -> dict[str, Any]:
    latency_seconds = sorted(
        max(0, int((event.observed_at - event.executed_at).total_seconds()))
        for event in events
    )
    ambiguous_count = sum(
        event.position_effect is LeaderPositionEffect.UNKNOWN for event in events
    )
    target_count = raw_count - filtered_count
    mapped_count = len(events) + duplicate_count
    mapping_rate = mapped_count / target_count if target_count else 0
    classification_rate = (
        (len(events) - ambiguous_count) / len(events) if events else 0
    )
    condition_outcomes: dict[str, set[str]] = {}
    for event in events:
        condition_outcomes.setdefault(event.market_reference, set()).add(
            event.outcome_reference
        )
    opposite_outcome_conditions = sum(
        len(outcomes) > 1 for outcomes in condition_outcomes.values()
    )

    decision = "CONDITIONAL_GO"
    reasons = [
        "Official public read-only Data API fields normalized without credentials.",
        "Continuous polling latency is not yet measured; reported lag is a one-shot upper bound.",
        "UNKNOWN position effects remain fail-closed and cannot create an intent.",
    ]
    if not events or mapping_rate < 0.95 or source_errors:
        decision = "NO_GO"
        reasons = [
            "No reliable bounded Stage 1 evidence was produced.",
            "Resolve source or mapping failures before any later Copy Trading stage.",
        ]

    coverage_payload = (
        {
            **asdict(coverage),
            "smallest_visible_position": _decimal_string(
                coverage.smallest_visible_position
            ),
            "maker_coverage_delta": coverage.maker_coverage_delta,
            "page_truncated": any(
                value >= coverage.page_limit
                for value in (
                    coverage.all_trade_count,
                    coverage.taker_trade_count,
                    coverage.activity_trade_count,
                    coverage.current_position_count,
                )
            ),
        }
        if coverage is not None
        else None
    )
    return {
        "schema_version": "1.0",
        "stage": "Stage 1 - Data Feasibility",
        "source": "Polymarket Data API and Gamma API",
        "leader_alias": LEADER_ALIAS,
        "window_started_at": started_at.isoformat(),
        "window_ended_at": ended_at.isoformat(),
        "generated_at": datetime.now(UTC).replace(microsecond=0).isoformat(),
        "pages_read": pages_read,
        "page_truncated": truncated,
        "observed_raw_events": raw_count,
        "filtered_non_btc_15m_events": filtered_count,
        "target_btc_15m_events": target_count,
        "valid_normalized_events": len(events),
        "duplicates": duplicate_count,
        "duplicate_rate": duplicate_count / raw_count if raw_count else 0,
        "rejected_or_missing_events": rejected_count,
        "missing_or_ambiguous_rate": (
            (rejected_count + ambiguous_count) / target_count if target_count else 0
        ),
        "ambiguous_position_effects": ambiguous_count,
        "btc_15m_mapping_success_rate": mapping_rate,
        "position_effect_classification_rate": classification_rate,
        "opposite_outcome_conditions": opposite_outcome_conditions,
        "observation_lag_seconds": {
            "p50": _percentile(latency_seconds, 0.50),
            "p95": _percentile(latency_seconds, 0.95),
            "maximum": max(latency_seconds, default=None),
            "semantics": (
                "executed_at is Data API epoch seconds; observed_at is local UTC receipt. "
                "This bounded historical probe measures first-observation lag, not isolated "
                "Data API indexing latency."
            ),
            "clock_uncertainty": (
                "Local clock was required to be aware UTC; external NTP error was not "
                "independently measured in this probe."
            ),
        },
        "source_coverage": coverage_payload,
        "source_errors": source_errors,
        "credentials_used": False,
        "venue_mutation_path_present": False,
        "decision": decision,
        "decision_reasons": reasons,
    }


def _write_artifacts(
    *,
    output_dir: Path,
    events: tuple[LeaderTradeEvent, ...],
    report: dict[str, Any],
    forbidden_wallet: str,
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    raw_path = output_dir / "raw-events.jsonl"
    normalized_path = output_dir / "normalized-events.jsonl"
    report_json_path = output_dir / "quality-report.json"
    report_md_path = output_dir / "quality-report.md"

    raw_text = "".join(
        json.dumps(_sanitized_source_projection(event), sort_keys=True) + "\n"
        for event in events
    )
    normalized_text = "".join(
        json.dumps(_normalized_projection(event), sort_keys=True) + "\n"
        for event in events
    )
    report_json = json.dumps(report, indent=2, sort_keys=True) + "\n"
    report_md = _render_markdown(report)
    combined = raw_text + normalized_text + report_json + report_md
    if forbidden_wallet.casefold() in combined.casefold():
        raise RuntimeError("sanitization failed: raw leader address reached an artifact")

    raw_path.write_text(raw_text, encoding="utf-8")
    normalized_path.write_text(normalized_text, encoding="utf-8")
    report_json_path.write_text(report_json, encoding="utf-8")
    report_md_path.write_text(report_md, encoding="utf-8")

    checksum_lines = [
        f"{_sha256(path)}  {path.name}"
        for path in (
            raw_path,
            normalized_path,
            report_json_path,
            report_md_path,
        )
    ]
    (output_dir / "checksum.sha256").write_text(
        "\n".join(checksum_lines) + "\n",
        encoding="utf-8",
    )


def _sanitized_source_projection(event: LeaderTradeEvent) -> dict[str, Any]:
    return {
        "source": event.source_id,
        "leaderAlias": event.leader_id,
        "conditionId": event.market_reference,
        "asset": event.outcome_reference,
        "side": event.trade_action.value,
        "price": str(event.executed_price),
        "size": str(event.executed_size),
        "timestamp": int(event.executed_at.timestamp()),
        "evidenceReference": event.external_evidence_reference,
    }


def _normalized_projection(event: LeaderTradeEvent) -> dict[str, Any]:
    return {
        "event_id": event.event_id,
        "source_id": event.source_id,
        "leader_id": event.leader_id,
        "market_reference": event.market_reference,
        "outcome_reference": event.outcome_reference,
        "trade_action": event.trade_action.value,
        "position_effect": event.position_effect.value,
        "executed_price": str(event.executed_price),
        "executed_size": str(event.executed_size),
        "executed_at": event.executed_at.isoformat(),
        "observed_at": event.observed_at.isoformat(),
        "external_evidence_reference": event.external_evidence_reference,
        "schema_version": event.schema_version,
    }


def _render_markdown(report: dict[str, Any]) -> str:
    latency = report["observation_lag_seconds"]
    coverage = report["source_coverage"]
    coverage_lines = (
        [
            f"- All trades (`takerOnly=false`): {coverage['all_trade_count']}",
            f"- Taker-only trades: {coverage['taker_trade_count']}",
            f"- Maker coverage delta: {coverage['maker_coverage_delta']}",
            f"- Activity trades: {coverage['activity_trade_count']}",
            f"- Current positions (`sizeThreshold=0`): {coverage['current_position_count']}",
            f"- Closed positions: {coverage['closed_position_count']}",
            f"- Smallest visible position: {coverage['smallest_visible_position']}",
        ]
        if coverage is not None
        else ["- Coverage probe unavailable."]
    )
    return "\n".join(
        [
            "# PolySia Copy Trading Stage 1 Quality Report",
            "",
            f"- Decision: **{report['decision']}**",
            f"- Leader: `{report['leader_alias']}` (sanitized alias)",
            f"- Raw events: {report['observed_raw_events']}",
            f"- Filtered non-BTC 15m events: {report['filtered_non_btc_15m_events']}",
            f"- Valid normalized events: {report['valid_normalized_events']}",
            f"- Duplicates: {report['duplicates']}",
            f"- Rejected or missing: {report['rejected_or_missing_events']}",
            f"- BTC 15m mapping success: {report['btc_15m_mapping_success_rate']:.2%}",
            (
                "- Position-effect classification: "
                f"{report['position_effect_classification_rate']:.2%}"
            ),
            (
                "- Observation lag seconds: "
                f"p50={latency['p50']}, p95={latency['p95']}, max={latency['maximum']}"
            ),
            "",
            "## Source coverage",
            "",
            *coverage_lines,
            "",
            "## Safety",
            "",
            "- Public unauthenticated GET requests only.",
            "- No strategy, CopyDecision, OrderIntent, order, cancel, or venue mutation.",
            "- Raw leader address and transaction hash are absent from artifacts.",
            "- UNKNOWN position effects remain fail-closed.",
            "",
            "## Limitation",
            "",
            f"- {latency['semantics']}",
            f"- {latency['clock_uncertainty']}",
            "",
        ]
    )


def _percentile(values: list[int], probability: float) -> int | None:
    if not values:
        return None
    index = max(0, min(len(values) - 1, int((len(values) - 1) * probability)))
    return values[index]


def _decimal_string(value: Decimal | None) -> str | None:
    return str(value) if value is not None else None


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("artifacts/copytrading/data-feasibility"),
    )
    parser.add_argument("--window-minutes", type=int, default=360)
    parser.add_argument("--page-size", type=int, default=100)
    parser.add_argument("--max-pages", type=int, default=5)
    args = parser.parse_args()
    if not 1 <= args.window_minutes <= 10_080:
        parser.error("--window-minutes must be within [1, 10080]")
    if not 1 <= args.page_size <= 500:
        parser.error("--page-size must be within [1, 500]")
    if not 1 <= args.max_pages <= 20:
        parser.error("--max-pages must be within [1, 20]")
    return args


if __name__ == "__main__":
    raise SystemExit(main())
