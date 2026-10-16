"""Native activity sampling, distinct from PolyCop's copyability policy."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any

from polysia.adapters.polymarket.data_api_v2 import (
    DATA_API_V2_ACTIVITY_PATH,
    DATA_API_V2_TRADES_PATH,
    DataApiV2Transport,
    fetch_data_api_v2_window,
)
from polysia.domain.wallet_intelligence import normalize_evm_wallet

PROFILE_VERSION = "native-recent-activity/v1"


async def discover_native_activity(
    transport: DataApiV2Transport, *, cutoff: datetime,
    cohort_limit: int, lookback: timedelta = timedelta(minutes=5), max_pages: int = 4,
) -> dict[str, Any]:
    """Complete bounded query, then freeze candidates before subsequent outcomes."""
    offset = cutoff.utcoffset()
    if cutoff.tzinfo is None or offset is None or offset.total_seconds() != 0:
        raise ValueError("cutoff must be UTC")
    if not 1 <= cohort_limit <= 10 or not timedelta(0) < lookback <= timedelta(hours=1):
        raise ValueError("native diagnostic cohort or window is outside bounds")
    lower = cutoff - lookback
    params = {"start": int(lower.timestamp()), "end": int(cutoff.timestamp()),
              "limit": 500, "taker_only": False}
    rows = await fetch_data_api_v2_window(
        transport, DATA_API_V2_TRADES_PATH, params,
        max_pages=max_pages, max_requests=max_pages, max_elapsed_seconds=60,
    )
    wallets: dict[str, tuple[str, datetime]] = {}
    excluded: dict[str, int] = {}
    for row in rows:
        try:
            wallet, when = qualifying_trade(row, lower=lower, cutoff=cutoff)
            wallet_id, _, address = normalize_evm_wallet("polygon", wallet)
            if wallet_id not in wallets or when > wallets[wallet_id][1]:
                wallets[wallet_id] = (address, when)
        except (ValueError, TypeError, InvalidOperation):
            excluded["invalid_or_out_of_window_trade"] = (
                excluded.get("invalid_or_out_of_window_trade", 0) + 1
            )
    selected = sorted(wallets, key=lambda key: (-wallets[key][1].timestamp(), key))[:cohort_limit]
    candidates: list[dict[str, Any]] = []
    for wallet_id in selected:
        address, last_trade = wallets[wallet_id]
        activity = await fetch_data_api_v2_window(
            transport, DATA_API_V2_ACTIVITY_PATH,
            {"user": address, "start": int(lower.timestamp()),
             "end": int(cutoff.timestamp()), "limit": 500, "type": "TRADE"},
            max_pages=max_pages, max_requests=max_pages, max_elapsed_seconds=60,
        )
        verified = []
        for row in activity:
            wallet, when = qualifying_trade(row, lower=lower, cutoff=cutoff)
            if wallet != address:
                raise ValueError("native_activity_wallet_mismatch")
            verified.append(when)
        candidates.append({
            "wallet_id": wallet_id, "address": address,
            "last_qualifying_activity": max(verified).isoformat() if verified else None,
            "feed_last_trade": last_trade.isoformat(),
            "complete_activity_rows": len(activity),
            "state": "ACTIVITY_CONFIRMED" if verified else "NO_COMPLETE_ACTIVITY",
            "execution_eligibility": "UNKNOWN_REQUIRES_MAPPING_BOOK_AND_FEE_EVIDENCE",
        })
    # Re-rank by complete wallet activity, never by a future outcome or P&L hint.
    candidates.sort(key=lambda item: (
        -(datetime.fromisoformat(item["last_qualifying_activity"]).timestamp()
          if item["last_qualifying_activity"] else 0), item["wallet_id"],
    ))
    result = {
        "profile": PROFILE_VERSION, "source": "polymarket-native",
        "coverage": "COMPLETE_FOR_BOUNDED_QUERY", "cutoff": cutoff.isoformat(),
        "window_start": lower.isoformat(), "source_rows": len(rows),
        "unique_wallets": len(wallets), "candidates": candidates,
        "excluded": excluded, "ranking": "activity_recency_then_identity_hash",
        "limitations": ["Activity sample, not proven trader skill or SHADOW_ALPHA.",
                        "Activity alone does not establish executable copyability."],
    }
    raw = json.dumps(result, sort_keys=True, separators=(",", ":"))
    return {**result, "digest": hashlib.sha256(raw.encode()).hexdigest()}


def qualifying_trade(
    row: dict[str, Any], *, lower: datetime, cutoff: datetime,
) -> tuple[str, datetime]:
    _, _, address = normalize_evm_wallet("polygon", str(row.get("proxyWallet", "")))
    stamp = row.get("timestamp")
    if type(stamp) is not int or row.get("is_combo") is True:
        raise ValueError("unsupported trade timestamp or combo")
    when = datetime.fromtimestamp(stamp, cutoff.tzinfo)
    price, size = row.get("price"), row.get("size")
    if (not isinstance(price, str | int | Decimal) or isinstance(price, bool)
            or not isinstance(size, str | int | Decimal) or isinstance(size, bool)):
        raise ValueError("inexact trade units")
    price, size = Decimal(price), Decimal(size)
    if (not price.is_finite() or not size.is_finite()
            or not Decimal(0) <= price <= Decimal(1) or size <= 0
            or not lower <= when <= cutoff or row.get("side") not in {"BUY", "SELL"}
            or row.get("type", "TRADE") != "TRADE"):
        raise ValueError("invalid or out of window trade")
    return address, when
