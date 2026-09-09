"""CLI helpers for public research-source benchmarking.

Keeps research.py free of venue wiring. Reports are sanitized before print.
"""

from __future__ import annotations

import json
import re
from collections.abc import Awaitable, Callable
from datetime import timedelta
from pathlib import Path
from typing import Any

from polysia.adapters.polymarket.copytrading_source import UrllibJsonGetTransport
from polysia.adapters.polymarket.research_sources import (
    ACTIVITY_SOURCE_ID,
    REST_ACTIVITY_CANDIDATE,
    REST_TRADES_CANDIDATE,
    TRADES_SOURCE_ID,
    USER_CHANNEL_CANDIDATE,
    DataApiWalletPollSource,
    OfficialMarketStreamSource,
    discover_market_fee_schedules,
    discover_public_follow_set,
)
from polysia.application.ports.research_evidence import ResearchObservationSource
from polysia.application.services.source_benchmark import SourceBenchmarkReport
from polysia.storage.research_evidence import ResearchEvidenceStore

_WALLET_RE = re.compile(r"0x[a-fA-F0-9]{40}")
_PERSISTENT_MARKET_WARMUP_SECONDS = 30.0
BenchmarkRunner = Callable[..., Awaitable[SourceBenchmarkReport]]


def sanitize_report(payload: dict[str, Any]) -> dict[str, Any]:
    text = json.dumps(payload, sort_keys=True, default=str)
    redacted = json.loads(_WALLET_RE.sub("0xREDACTED", text))
    if not isinstance(redacted, dict):
        raise ValueError("sanitized report must be an object")
    return redacted


async def build_public_benchmark(
    *,
    duration_seconds: int,
    database: Path,
    code_sha: str | None,
    runner: BenchmarkRunner,
) -> dict[str, Any]:
    transport = UrllibJsonGetTransport()
    aliases, token_ids = await discover_public_follow_set(transport)
    store = ResearchEvidenceStore(database)
    sources: list[ResearchObservationSource] = []
    if aliases:
        sources.append(
            DataApiWalletPollSource(
                REST_ACTIVITY_CANDIDATE,
                path="/activity",
                source_id=ACTIVITY_SOURCE_ID,
                aliases=aliases,
                transport=transport,
            )
        )
        sources.append(
            DataApiWalletPollSource(
                REST_TRADES_CANDIDATE,
                path="/trades",
                source_id=TRADES_SOURCE_ID,
                aliases=aliases,
                transport=transport,
            )
        )
    fee_schedules = await discover_market_fee_schedules(token_ids)
    sources.append(
        OfficialMarketStreamSource(token_ids=token_ids, fee_schedules=fee_schedules)
    )
    report = await runner(
        tuple(sources),
        store=store,
        duration=timedelta(seconds=duration_seconds),
        code_sha=code_sha,
        configuration={
            "duration_seconds": duration_seconds,
            "followed_alias_count": len(aliases),
            "market_token_count": len(token_ids),
        },
        unavailable=(USER_CHANNEL_CANDIDATE,),
    )
    return {
        **report.payload,
        "followed_alias_count": len(aliases),
        "market_token_count": len(token_ids),
        "discovery_status": "measured" if aliases else "insufficient_public_wallets",
    }


async def build_persistent_public_sources() -> tuple[
    tuple[ResearchObservationSource, ...],
    dict[str, object],
]:
    transport = UrllibJsonGetTransport()
    aliases, discovered_tokens = await discover_public_follow_set(transport)
    from polysia.adapters.polymarket.research_sources import (
        MARKET_STREAM_CANDIDATE,
        FollowedMarketDiscovery,
    )

    discovery = FollowedMarketDiscovery(transport, aliases) if aliases else None
    snapshot = await discovery.refresh() if discovery is not None else None
    followed_markets = {} if snapshot is None else snapshot.token_markets
    token_ids = tuple(followed_markets) or discovered_tokens
    fee_schedules = (
        snapshot.fee_schedules
        if snapshot is not None
        else await discover_market_fee_schedules(token_ids)
    )
    sources: list[ResearchObservationSource] = []
    if aliases:
        sources.append(
            DataApiWalletPollSource(
                REST_TRADES_CANDIDATE,
                path="/trades",
                source_id=TRADES_SOURCE_ID,
                aliases=aliases,
                transport=transport,
                initial_delay_seconds=_PERSISTENT_MARKET_WARMUP_SECONDS,
            )
        )
        sources.append(
            DataApiWalletPollSource(
                REST_ACTIVITY_CANDIDATE,
                path="/activity",
                source_id=ACTIVITY_SOURCE_ID,
                aliases=aliases,
                transport=transport,
                initial_delay_seconds=_PERSISTENT_MARKET_WARMUP_SECONDS,
            )
        )
    sources.append(
        OfficialMarketStreamSource(
            token_ids=token_ids,
            fee_schedules=fee_schedules,
            market_discovery=None if discovery is None else discovery.refresh,
            discovery_interval_seconds=1.0,
        )
    )
    return tuple(sources), {
        "followed_alias_count": len(aliases),
        "followed_aliases": sorted(aliases),
        "market_token_count": len(token_ids),
        "market_tokens": list(token_ids),
        "market_fee_schedule_count": len(fee_schedules),
        "required_source_ids": [REST_TRADES_CANDIDATE.candidate_id]
        if aliases
        else [],
        "optional_source_ids": [
            REST_ACTIVITY_CANDIDATE.candidate_id,
            MARKET_STREAM_CANDIDATE.candidate_id,
        ],
        "unavailable": [USER_CHANNEL_CANDIDATE.candidate_id],
        "discovery_status": "measured" if aliases else "insufficient_public_wallets",
    }
