"""Native activity sampling, distinct from PolyCop's copyability policy."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any

from polysia.adapters.polymarket.bounded_market import BoundedMarketAdapter
from polysia.adapters.polymarket.data_api_v2 import (
    DATA_API_BASE_URL,
    DATA_API_V2_ACTIVITY_PATH,
    DATA_API_V2_TRADES_PATH,
    DataApiV2Transport,
    data_api_v2_rows,
    fetch_data_api_v2_window,
)
from polysia.domain.wallet_intelligence import normalize_evm_wallet

PROFILE_VERSION = "native-recent-activity/v1"


async def discover_native_activity(
    transport: DataApiV2Transport,
    *,
    cutoff: datetime,
    cohort_limit: int,
    lookback: timedelta = timedelta(minutes=5),
    max_pages: int = 4,
) -> dict[str, Any]:
    """Sample recent seed identities, then fully walk each wallet's activity."""
    offset = cutoff.utcoffset()
    if cutoff.tzinfo is None or offset is None or offset.total_seconds() != 0:
        raise ValueError("cutoff must be UTC")
    if not 1 <= cohort_limit <= 10 or not timedelta(0) < lookback <= timedelta(hours=1):
        raise ValueError("native diagnostic cohort or window is outside bounds")
    lower = cutoff - lookback
    # The official bare feed ignores start/end and spans two calendar months.
    # This is an explicitly sampled first page, never a completed feed walk or
    # watermark. Complete-query requirements apply to wallet activity below.
    seed = await transport.get_json(
        DATA_API_BASE_URL,
        DATA_API_V2_TRADES_PATH,
        {"limit": 500, "taker_only": False},
    )
    rows = data_api_v2_rows(seed)
    pagination = seed.get("pagination")
    cursor = pagination.get("next_cursor") if isinstance(pagination, dict) else None
    if (
        not isinstance(pagination, dict)
        or type(pagination.get("has_more")) is not bool
        or not (cursor is None or isinstance(cursor, str) and cursor)
        or pagination["has_more"] != (pagination.get("next_cursor") is not None)
    ):
        raise ValueError("seed_pagination_invalid")
    wallets: dict[str, tuple[str, datetime]] = {}
    excluded: dict[str, int] = {}
    observed_times: list[datetime] = []
    for row in rows:
        try:
            stamp = row.get("timestamp")
            if type(stamp) is int:
                when = datetime.fromtimestamp(stamp, cutoff.tzinfo)
                observed_times.append(when)
                if when < lower:
                    excluded["before_activity_window"] = (
                        excluded.get("before_activity_window", 0) + 1
                    )
                    continue
                if when > cutoff:
                    excluded["after_cutoff"] = excluded.get("after_cutoff", 0) + 1
                    continue
            wallet, when = qualifying_trade(row, lower=lower, cutoff=cutoff)
            wallet_id, _, address = normalize_evm_wallet("polygon", wallet)
            if wallet_id not in wallets or when > wallets[wallet_id][1]:
                wallets[wallet_id] = (address, when)
        except ValueError, TypeError, InvalidOperation:
            excluded["invalid_trade"] = excluded.get("invalid_trade", 0) + 1
    selected = sorted(wallets, key=lambda key: (-wallets[key][1].timestamp(), key))[:cohort_limit]
    candidates: list[dict[str, Any]] = []
    for wallet_id in selected:
        address, last_trade = wallets[wallet_id]
        activity = await fetch_data_api_v2_window(
            transport,
            DATA_API_V2_ACTIVITY_PATH,
            {
                "user": address,
                "start": int(lower.timestamp()),
                "end": int(cutoff.timestamp()),
                "limit": 500,
                "type": "TRADE",
            },
            max_pages=max_pages,
            max_requests=max_pages,
            max_elapsed_seconds=60,
        )
        verified: list[datetime] = []
        latest: dict[str, Any] | None = None
        for row in activity:
            wallet, when = qualifying_trade(row, lower=lower, cutoff=cutoff)
            if wallet != address:
                raise ValueError("native_activity_wallet_mismatch")
            verified.append(when)
            if latest is None or when > datetime.fromtimestamp(latest["timestamp"], cutoff.tzinfo):
                latest = row
        candidates.append(
            {
                "wallet_id": wallet_id,
                "address": address,
                "last_qualifying_activity": max(verified).isoformat() if verified else None,
                "feed_last_trade": last_trade.isoformat(),
                "complete_activity_rows": len(activity),
                "market_reference": latest.get("conditionId") if latest else None,
                "outcome_reference": latest.get("asset") if latest else None,
                "state": "ACTIVITY_CONFIRMED" if verified else "NO_COMPLETE_ACTIVITY",
                "execution_eligibility": "UNKNOWN_REQUIRES_MAPPING_BOOK_AND_FEE_EVIDENCE",
            }
        )
    # Re-rank by complete wallet activity, never by a future outcome or P&L hint.
    candidates.sort(
        key=lambda item: (
            -(
                datetime.fromisoformat(item["last_qualifying_activity"]).timestamp()
                if item["last_qualifying_activity"]
                else 0
            ),
            item["wallet_id"],
        )
    )
    result = {
        "profile": PROFILE_VERSION,
        "source": "polymarket-native",
        "coverage": "COMPLETE_WALLET_ACTIVITY_WITH_SAMPLED_SEEDS",
        "seed_coverage": "FIRST_PAGE_SAMPLE_NOT_EXHAUSTIVE",
        "seed_has_more": pagination["has_more"],
        "cutoff": cutoff.isoformat(),
        "window_start": lower.isoformat(),
        "source_rows": len(rows),
        "seed_newest_at": max(observed_times).isoformat() if observed_times else None,
        "seed_oldest_at": min(observed_times).isoformat() if observed_times else None,
        "seed_newest_age_seconds": (
            int((cutoff - max(observed_times)).total_seconds()) if observed_times else None
        ),
        "source_condition": (
            "DEGRADED_SOURCE_FRESHNESS"
            if rows and len(observed_times) == len(rows) and max(observed_times) < lower
            else "SAMPLED"
        ),
        "unique_wallets": len(wallets),
        "candidates": candidates,
        "excluded": excluded,
        "ranking": "activity_recency_then_identity_hash",
        "limitations": [
            "Activity sample, not proven trader skill or SHADOW_ALPHA.",
            "Activity alone does not establish executable copyability.",
        ],
    }
    raw = json.dumps(result, sort_keys=True, separators=(",", ":"))
    return {**result, "digest": hashlib.sha256(raw.encode()).hexdigest()}


def qualifying_trade(
    row: dict[str, Any],
    *,
    lower: datetime,
    cutoff: datetime,
) -> tuple[str, datetime]:
    _, _, address = normalize_evm_wallet("polygon", str(row.get("proxyWallet", "")))
    stamp = row.get("timestamp")
    if type(stamp) is not int or row.get("is_combo") is True:
        raise ValueError("unsupported trade timestamp or combo")
    when = datetime.fromtimestamp(stamp, cutoff.tzinfo)
    price, size = row.get("price"), row.get("size")
    if (
        not isinstance(price, str | int | Decimal)
        or isinstance(price, bool)
        or not isinstance(size, str | int | Decimal)
        or isinstance(size, bool)
    ):
        raise ValueError("inexact trade units")
    price, size = Decimal(price), Decimal(size)
    if (
        not price.is_finite()
        or not size.is_finite()
        or not Decimal(0) <= price <= Decimal(1)
        or size <= 0
        or not lower <= when <= cutoff
        or row.get("side") not in {"BUY", "SELL"}
        or row.get("type", "TRADE") != "TRADE"
    ):
        raise ValueError("invalid or out of window trade")
    return address, when


async def verify_native_eligibility(
    discovered: dict[str, Any], market_adapter: BoundedMarketAdapter,
    *, clock: Callable[[], datetime],
) -> None:
    for candidate in discovered["candidates"]:
        condition, token = candidate["market_reference"], candidate["outcome_reference"]
        if not isinstance(condition, str) or not isinstance(token, str):
            candidate["execution_eligibility"] = "UNKNOWN_MISSING_MARKET_TOKEN"
            continue
        try:
            market = await market_adapter.get_market_by_condition_id(condition)
            book = await market_adapter.get_order_book(token)
            mapped = any(outcome.token_id == token for outcome in market.outcomes)
            fee = market.fee_schedule
            fee_known = fee is not None and (
                fee.enabled is False or fee.rate is not None and fee.exponent is not None
            )
            current = book.timestamp is not None and (
                0 <= (clock() - book.timestamp).total_seconds() <= 30
            )
            candidate["execution_eligibility"] = (
                "ELIGIBLE_FOR_RESEARCH"
                if mapped
                and fee_known
                and current
                and book.asks
                and book.bids
                and market.active
                and not market.closed
                else "UNKNOWN_MAPPING_FEE_BOOK_OR_MARKET_STATE"
            )
            candidate["mapping_verified"] = mapped
            candidate["fee_known"] = fee_known
            candidate["book_current"] = current
            candidate["exclusions"] = [
                reason
                for passed, reason in (
                    (mapped, "market_token_mapping_unverified"),
                    (fee_known, "fee_evidence_missing"),
                    (current, "book_stale_or_timestamp_missing"),
                    (bool(book.asks and book.bids), "executable_depth_missing"),
                    (market.active and not market.closed, "market_not_active"),
                )
                if not passed
            ]
        except ValueError:
            candidate["execution_eligibility"] = "INVALID_MARKET_OR_BOOK_SCHEMA"


async def revalidate_native_cohort(
    discovery: dict[str, Any], transport: DataApiV2Transport,
    market_adapter: BoundedMarketAdapter, *, clock: Callable[[], datetime],
) -> dict[str, Any]:
    """Revalidate only admitted identities; never discover or admit replacements."""
    cutoff = clock()
    if cutoff.utcoffset() != timedelta(0):
        raise ValueError("cutoff must be UTC")
    original_window = datetime.fromisoformat(discovery["cutoff"]) - datetime.fromisoformat(
        discovery["window_start"]
    )
    if not timedelta(0) < original_window <= timedelta(hours=1):
        raise ValueError("native revalidation window invalid")
    lower = cutoff - original_window
    candidates = []
    for original in discovery["candidates"]:
        if original["execution_eligibility"] != "ELIGIBLE_FOR_RESEARCH":
            continue
        rows = await fetch_data_api_v2_window(
            transport, DATA_API_V2_ACTIVITY_PATH,
            {"user": original["address"], "start": int(lower.timestamp()),
             "end": int(cutoff.timestamp()), "limit": 500, "type": "TRADE"},
            max_pages=4, max_requests=4, max_elapsed_seconds=60,
        )
        latest = None
        latest_at = None
        for row in rows:
            address, when = qualifying_trade(row, lower=lower, cutoff=cutoff)
            if address != original["address"]:
                raise ValueError("native_activity_wallet_mismatch")
            if latest_at is None or when > latest_at:
                latest, latest_at = row, when
        candidates.append({
            "wallet_id": original["wallet_id"], "address": original["address"],
            "state": "ACTIVITY_CONFIRMED" if latest else "NO_COMPLETE_ACTIVITY",
            "execution_eligibility": "UNKNOWN_REQUIRES_MAPPING_BOOK_AND_FEE_EVIDENCE",
            "last_qualifying_activity": latest_at.isoformat() if latest_at else None,
            "complete_activity_rows": len(rows),
            "market_reference": latest.get("conditionId") if latest else None,
            "outcome_reference": latest.get("asset") if latest else None,
        })
    result = {
        "profile": PROFILE_VERSION, "source": "polymarket-native",
        "coverage": "COMPLETE_FIXED_ADMITTED_WALLET_ACTIVITY",
        "seed_coverage": "NOT_RESAMPLED_FIXED_ADMITTED_COHORT",
        "original_cohort_digest": discovery["digest"],
        "cutoff": cutoff.isoformat(), "window_start": lower.isoformat(),
        "candidates": candidates, "unique_wallets": len(candidates),
        "source_rows": sum(row["complete_activity_rows"] for row in candidates),
    }
    await verify_native_eligibility(result, market_adapter, clock=clock)
    result["frozen_at"] = clock().isoformat()
    raw = json.dumps(result, sort_keys=True, separators=(",", ":"))
    return {**result, "digest": hashlib.sha256(raw.encode()).hexdigest()}
