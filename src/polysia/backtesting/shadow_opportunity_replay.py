"""Read-only adapter from durable Shadow opportunities to prospective replay."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta
from decimal import Decimal

from polysia.backtesting.prospective_economics import evaluate_prospective_economics
from polysia.domain.research_evidence.models import (
    RESEARCH_EVIDENCE_SCHEMA_VERSION,
    AttributionStatus,
    CanonicalResearchEvent,
    ConfirmationStatus,
    EvidenceClassification,
    ObservationKind,
)
from polysia.domain.research_evidence.replay import replay_same_observations


def replay_shadow_opportunities(
    rows: tuple[dict[str, object], ...], *, experiment_id: str,
    settlements: tuple[dict[str, str], ...] = (),
) -> dict[str, object]:
    """Keep both policies on all admitted observations, including Shadow rejects."""

    events: list[CanonicalResearchEvent] = []
    snapshots: list[CanonicalResearchEvent] = []
    reasons: dict[str, int] = {}
    used_books: set[tuple[str, str, str, str]] = set()
    for row in sorted(rows, key=lambda item: (str(item["decision_at"]), str(item["event_id"]))):
        source_at = _time(row["source_at"])
        first_at = _time(row["first_observed_at"])
        admitted_at = _time(row["admission_at"])
        decided_at = _time(row["decision_at"])
        if not source_at <= first_at <= admitted_at <= decided_at:
            raise ValueError("Shadow opportunity timestamps violate causal order")
        evidence_id = _digest({"experiment_id": experiment_id, "event_id": row["event_id"]})
        event = _event(
            evidence_id=evidence_id,
            source_id=str(row["source_id"]),
            kind=ObservationKind.WALLET_TRADE,
            market=str(row["market_reference"]),
            token=str(row["outcome_reference"]),
            side=str(row["side"]),
            price=Decimal(str(row["price"])),
            size=Decimal(str(row["size"])),
            source_at=source_at,
            observed_at=first_at,
            admission_at=admitted_at,
            wallet=str(row["wallet_id"]),
            related=None,
            provenance={
                "first_observed_at": first_at.isoformat(),
                "admission_at": admitted_at.isoformat(),
                "decision_at": decided_at.isoformat(),
                "selection_digest": row["selection_digest"],
                "config_digest": row["config_digest"],
                "policy_version": row["policy_version"],
            },
            source_event_id=str(row["event_id"]),
            experiment_id=experiment_id,
        )
        events.append(event)
        if row.get("market_token_binding") != "VERIFIED":
            _count(reasons, "unverified_market_token")
            continue
        book_at_value = row.get("book_at")
        levels = row.get("book_levels")
        if not isinstance(book_at_value, str) or not isinstance(levels, list) or not levels:
            _count(reasons, "missing_book_or_depth")
            continue
        book_at = _time(book_at_value)
        if book_at > decided_at:
            _count(reasons, "future_book")
            continue
        max_age = int(str(row.get("maximum_quote_age_ms", 30_000)))
        if decided_at - book_at > timedelta(milliseconds=max_age):
            _count(reasons, "stale_book")
            continue
        scope = (
            str(row["poll_run_id"]),
            str(row["outcome_reference"]),
            str(row["side"]),
            str(row.get("book_hash") or book_at_value),
        )
        if scope in used_books:
            _count(reasons, "shared_book_depth_unallocated")
            continue
        used_books.add(scope)
        snapshot_id = _digest({"opportunity": evidence_id, "kind": "execution"})
        fee_enabled = row.get("fee_enabled")
        provenance = {
            "execution_evidence_version": "order-book-depth-v1",
            "book_levels": levels,
            "fees_enabled": fee_enabled,
            "fee_rate": row.get("fee_rate"),
            "fee_exponent": row.get("fee_exponent"),
            "fee_taker_only": row.get("fee_taker_only"),
            "fee_calculation_version": row.get("cost_model_version"),
            "markout_eligible": False,
        }
        snapshots.append(
            _event(
                evidence_id=snapshot_id,
                source_id="shadow:recorded-book",
                kind=ObservationKind.MARKET_STATE,
                market=str(row["market_reference"]),
                token=str(row["outcome_reference"]),
                side=str(row["side"]),
                price=Decimal(str(levels[0]["price"])),
                size=Decimal(str(levels[0]["size"])),
                source_at=book_at,
                observed_at=decided_at,
                wallet=None,
                related=evidence_id,
                provenance=provenance,
                source_event_id=None,
                experiment_id=experiment_id,
            )
        )
        bids = row.get("book_bids")
        if str(row["side"]) == "BUY" and isinstance(bids, list) and bids:
            snapshots.append(
                _event(
                    evidence_id=_digest({"opportunity": evidence_id, "kind": "liquidation"}),
                    source_id="shadow:recorded-book",
                    kind=ObservationKind.MARKET_STATE,
                    market=str(row["market_reference"]),
                    token=str(row["outcome_reference"]),
                    side="SELL",
                    price=Decimal(str(bids[0]["price"])),
                    size=Decimal(str(bids[0]["size"])),
                    source_at=book_at,
                    observed_at=decided_at,
                    wallet=None,
                    related=evidence_id,
                    provenance={**provenance, "book_levels": bids},
                    source_event_id=None,
                    experiment_id=experiment_id,
                )
            )
    for settlement in settlements:
        observed_at = _time(settlement["observed_at"])
        price = Decimal(settlement["price"])
        if price not in {Decimal("0"), Decimal("1")}:
            raise ValueError("Shadow settlement price is not terminal")
        snapshots.append(_event(
            evidence_id=_digest({"experiment_id": experiment_id, "settlement": settlement}),
            source_id="shadow:verified-settlement",
            kind=ObservationKind.MARKET_STATE,
            market=settlement["market_reference"],
            token=settlement["outcome_reference"],
            side="SELL",
            price=price,
            size=None,
            source_at=observed_at,
            observed_at=observed_at,
            wallet=None,
            related=None,
            provenance={
                "settlement_evidence_version": "official-terminal-settlement-v1",
                "settlement_price": str(price),
                "poll_run_id": settlement["poll_run_id"],
            },
            source_event_id=None,
            experiment_id=experiment_id,
        ))
    replay = replay_same_observations(
        events,
        snapshots=snapshots,
        require_related_execution_snapshot=True,
        record_markouts=False,
    )
    report = evaluate_prospective_economics(replay, events=tuple((*events, *snapshots)))
    return {
        "report": report.to_dict(),
        "opportunity_count": len(events),
        "excluded_execution_evidence": reasons,
        "evidence_version": (
            str(rows[0].get("version", "shadow-opportunity-v1"))
            if rows and all(
                row.get("version", "shadow-opportunity-v1")
                == rows[0].get("version", "shadow-opportunity-v1") for row in rows
            ) else "mixed_or_empty"
        ),
        "evidence_versions": sorted({
            str(row.get("version", "shadow-opportunity-v1")) for row in rows
        }),
        "comparison": "separate_prospective_policies_not_shadow_ledger_parity",
    }


def _event(
    *,
    evidence_id: str,
    source_id: str,
    kind: ObservationKind,
    market: str,
    token: str,
    side: str,
    price: Decimal,
    size: Decimal | None,
    source_at: datetime,
    observed_at: datetime,
    wallet: str | None,
    related: str | None,
    provenance: dict[str, object],
    source_event_id: str | None,
    experiment_id: str,
    admission_at: datetime | None = None,
) -> CanonicalResearchEvent:
    return CanonicalResearchEvent(
        evidence_id=evidence_id,
        schema_version=RESEARCH_EVIDENCE_SCHEMA_VERSION,
        source_id=source_id,
        event_kind=kind,
        classification=EvidenceClassification.ACCEPTED,
        market_reference=market,
        outcome_reference=token,
        side=side,
        price=price,
        size=size,
        source_time=source_at,
        observed_time=observed_at,
        admission_time=admission_at,
        receive_monotonic_ns=0,
        normalize_monotonic_ns=0,
        attribution_status=(
            AttributionStatus.WALLET_ALIASED if wallet else AttributionStatus.NOT_APPLICABLE
        ),
        leader_alias=wallet,
        confirmation=ConfirmationStatus.CONFIRMED,
        payload_digest=evidence_id,
        provenance=provenance,
        source_event_id=source_event_id,
        related_evidence_id=related,
        run_id=experiment_id,
    )


def _time(value: object) -> datetime:
    if not isinstance(value, str):
        raise ValueError("Shadow opportunity timestamp is missing")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() != timedelta(0):
        raise ValueError("Shadow opportunity timestamp must be UTC")
    return parsed


def _digest(value: dict[str, object]) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def _count(reasons: dict[str, int], reason: str) -> None:
    reasons[reason] = reasons.get(reason, 0) + 1
