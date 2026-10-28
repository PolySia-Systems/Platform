"""Bounded point-in-time reader of existing immutable Shadow opportunities.

The predeclared horizon uses the first later retained executable quote inside a
fixed tolerance. Missing depth/route/fees/provenance stays censored. No final
settlement, later portfolio result or provider rank is used as a predictor.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from contextlib import closing
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

from polysia.application.services.follower_qualification import FollowerSample
from polysia.domain.copytrading.continuous_shadow import calculate_taker_fee_amount
from polysia.domain.financial_session import SessionBlocked, digest, utc

D = Decimal


def retained_follower_samples(
    path: Path,
    experiment_id: str,
    *,
    selection_start: datetime,
    selection_end: datetime,
    horizon_seconds: int,
    tolerance_seconds: int,
    maximum_rows: int = 10000,
) -> tuple[FollowerSample, ...]:
    if (
        path.is_symlink()
        or not 0 < horizon_seconds <= 86400
        or not 0 < tolerance_seconds <= 3600
        or not 0 < maximum_rows <= 10000
        or not utc(selection_start) < utc(selection_end)
    ):
        raise SessionBlocked("bounded_follower_evidence_window_required")
    with closing(sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)) as connection:
        connection.execute("BEGIN")
        experiment = connection.execute(
            "SELECT config_json FROM continuous_shadow_experiments WHERE experiment_id=?",
            (experiment_id,),
        ).fetchone()
        if experiment is None:
            raise SessionBlocked("follower_experiment_unavailable")
        configured = json.loads(experiment[0])
        expected = hashlib.sha256(
            json.dumps(configured, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        rows = connection.execute(
            "SELECT o.evidence_json,o.evidence_digest,p.completed_at,"
            "p.selection_snapshot_digest FROM continuous_shadow_opportunities o JOIN "
            "continuous_shadow_poll_runs p ON p.poll_run_id=o.poll_run_id "
            "WHERE o.experiment_id=? AND p.experiment_id=? AND p.status='succeeded' "
            "AND p.completed_at<=? ORDER BY o.recorded_at,o.event_id LIMIT ?",
            (experiment_id, experiment_id, selection_end.isoformat(), maximum_rows + 1),
        ).fetchall()
    if len(rows) > maximum_rows:
        raise SessionBlocked("follower_evidence_row_budget_exhausted")
    retained: list[tuple[dict[str, Any], datetime]] = []
    for raw, sha, completed, selection in rows:
        item = json.loads(raw)
        if (
            hashlib.sha256(raw.encode()).hexdigest() != sha
            or item["config_digest"] != expected
            or item["selection_digest"] != selection
            or item.get("code_sha") != configured.get("code_sha")
        ):
            raise SessionBlocked("retained_follower_evidence_binding_changed")
        at = datetime.fromisoformat(completed)
        if not datetime.fromisoformat(item["decision_at"]) <= at <= selection_end:
            raise SessionBlocked("retained_follower_evidence_not_available")
        retained.append((item, at))
    result = []
    for entry, available in retained:
        if entry["side"] != "BUY" or entry.get("input_kind") == "POSITION_TRIGGER":
            continue
        source_at = datetime.fromisoformat(entry["source_at"])
        admitted = datetime.fromisoformat(entry["admission_at"])
        # Admission is known before the quote was acquired; a pre-admission
        # cached quote cannot be turned into a delayed follower observation.
        quote_at = datetime.fromisoformat(entry["decision_at"])
        source_quote_at = datetime.fromisoformat(entry["book_at"]) if entry.get("book_at") else None
        if (
            not selection_start <= source_at < selection_end
            or source_quote_at is None
            or not admitted <= quote_at
            or not 0
            <= (quote_at - source_quote_at).total_seconds() * 1000
            <= entry["maximum_quote_age_ms"]
        ):
            continue
        target = quote_at + timedelta(seconds=horizon_seconds)
        if target >= selection_end:
            continue  # horizon not matured at selection; never include evaluation data
        candidates = [
            (row, committed)
            for row, committed in retained
            if row["outcome_reference"] == entry["outcome_reference"]
            and row.get("book_at")
            and target
            <= datetime.fromisoformat(row["book_at"])
            <= min(selection_end, target + timedelta(seconds=tolerance_seconds))
            and row.get("book_bids")
        ]
        future = min(candidates, key=lambda pair: pair[0]["book_at"], default=None)
        asks, bids = entry.get("book_asks") or [], entry.get("book_bids") or []
        if not asks:
            continue
        price = D(asks[0]["price"])
        forward = future[0] if future else None
        bid = D(forward["book_bids"][0]["price"]) if forward else None
        entry_fee = _fee(entry, price)
        exit_fee = _fee(forward, bid) if forward is not None and bid is not None else None
        route = all(
            row.get("market_token_binding") == "VERIFIED"
            for row in (entry, forward)
            if row is not None
        )
        occurrence = entry.get("source_occurrence_id")
        proven = (
            entry.get("source_schema") == "corroborated-ctf-v2/v1"
            and occurrence
            and entry.get("source_evidence_reference")
        )
        result.append(
            FollowerSample(
                entry["wallet_id"],
                entry["outcome_reference"],
                str(occurrence or entry["event_id"]),
                source_at,
                admitted,
                quote_at,
                datetime.fromisoformat(forward["book_at"]) if forward else target,
                max(available, future[1]) if future else selection_end,
                price,
                bid,
                price - D(bids[0]["price"]) if bids else None,
                D(asks[0]["size"]),
                D(forward["book_bids"][0]["size"]) if forward else None,
                entry_fee + exit_fee if entry_fee is not None and exit_fee is not None else None,
                bool(route),
                bool(proven and forward is not None),
                digest((entry, forward)),
            )
        )
    return tuple(result)


def _fee(row: dict[str, Any], price: Decimal) -> Decimal | None:
    if row.get("fee_enabled") is False:
        return D(0)
    if (
        row.get("fee_enabled") is not True
        or row.get("fee_taker_only") is not True
        or row.get("fee_rate") is None
        or row.get("fee_exponent") is None
    ):
        return None
    rate, exponent = D(row["fee_rate"]), D(row["fee_exponent"])
    if not 0 <= rate <= 1 or not 0 <= exponent <= 10 or not 0 <= price <= 1:
        return None
    return calculate_taker_fee_amount(price=price, size=D(1), rate=rate, exponent=exponent)
