"""CLI helpers for public research-source benchmarking.

Keeps research.py free of venue wiring. Reports are sanitized before print.
"""

from __future__ import annotations

import asyncio
import json
import re
from collections.abc import Awaitable, Callable, Mapping
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

from polysia.adapters.polymarket.copytrading_source import UrllibJsonGetTransport
from polysia.adapters.polymarket.public import PolymarketPublicAdapter
from polysia.adapters.polymarket.research_sources import (
    ACTIVITY_SOURCE_ID,
    REST_ACTIVITY_CANDIDATE,
    REST_TRADES_CANDIDATE,
    TRADES_SOURCE_ID,
    USER_CHANNEL_CANDIDATE,
    DataApiWalletPollSource,
    OfficialMarketStreamSource,
    TerminalMarketSnapshot,
    discover_clob_market_fee_schedules,
    discover_market_fee_schedules,
    discover_public_follow_set,
)
from polysia.application.ports.research_evidence import ResearchObservationSource
from polysia.application.services.source_benchmark import SourceBenchmarkReport
from polysia.domain.market import MarketFeeSchedule, MarketOrderBookSnapshot
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
    sources, discovery = await build_persistent_sources_from_aliases(
        aliases,
        transport=transport,
        discovered_tokens=discovered_tokens,
    )
    discovery["discovery_status"] = "measured" if aliases else "insufficient_public_wallets"
    discovery["selection_mode"] = "public-discovery"
    return sources, discovery


async def build_persistent_runner_sources(
    *,
    database: Path | None = None,
    now: datetime | None = None,
    wallet_count: int | None = None,
    selection_policy: str | None = None,
) -> tuple[tuple[ResearchObservationSource, ...], dict[str, object]]:
    from polysia.deployment.research_run_contract import (
        CONFIGURED_SELECTION_POLICY,
        DEFAULT_SELECTION_POLICY,
        DEFAULT_WALLET_COUNT,
    )
    from polysia.deployment.research_wallet_selection import (
        DEFAULT_SELECTION_DATABASE,
        load_current_polycop_snapshot,
        public_selection_payload,
        reconstruction_payload,
        resolve_polycop_follow_set,
        resolve_polycop_shadow_alpha_top3,
    )

    count = DEFAULT_WALLET_COUNT if wallet_count is None else wallet_count
    policy = selection_policy or (
        DEFAULT_SELECTION_POLICY
        if count == DEFAULT_WALLET_COUNT
        else CONFIGURED_SELECTION_POLICY
    )
    snapshot = load_current_polycop_snapshot(database or DEFAULT_SELECTION_DATABASE)
    observed = now or datetime.now(UTC)
    if policy == DEFAULT_SELECTION_POLICY:
        selection = resolve_polycop_shadow_alpha_top3(
            snapshot, now=observed, wallet_limit=count
        )
    else:
        selection = resolve_polycop_follow_set(
            snapshot,
            now=observed,
            wallet_limit=count,
            policy_version=policy,
        )
    sources, discovery = await build_persistent_sources_from_aliases(
        selection.addresses_by_alias
    )
    discovery.update(public_selection_payload(selection))
    discovery["_reconstruction"] = reconstruction_payload(selection)
    discovery["_restricted_aliases"] = dict(selection.addresses_by_alias)
    discovery["discovery_status"] = "polycop_shadow_alpha"
    discovery["selection_mode"] = selection.policy_version
    return sources, discovery


async def build_persistent_sources_from_aliases(
    aliases: Mapping[str, str],
    *,
    transport: UrllibJsonGetTransport | None = None,
    discovered_tokens: tuple[str, ...] = (),
) -> tuple[tuple[ResearchObservationSource, ...], dict[str, object]]:
    transport = transport or UrllibJsonGetTransport()
    public_adapter = PolymarketPublicAdapter()
    snapshot_fee_cache: dict[str, MarketFeeSchedule] = {}
    from polysia.adapters.polymarket.research_sources import (
        MARKET_STREAM_CANDIDATE,
        FollowedMarketDiscovery,
    )

    discovery = FollowedMarketDiscovery(transport, aliases) if aliases else None

    async def terminal_snapshot(
        token_markets: Mapping[str, str],
    ) -> TerminalMarketSnapshot:
        books: dict[str, MarketOrderBookSnapshot] = {}
        tokens = tuple(token_markets)
        batches = await asyncio.gather(
            *(
                public_adapter.get_order_books(tokens[index : index + 50])
                for index in range(0, len(tokens), 50)
            )
        )
        for batch in batches:
            books.update(batch)
        missing_fees = {
            token: market
            for token, market in token_markets.items()
            if token not in snapshot_fee_cache
        }
        if missing_fees:
            snapshot_fee_cache.update(
                await discover_clob_market_fee_schedules(transport, missing_fees)
            )
        fees = {
            token: snapshot_fee_cache[token]
            for token in token_markets
            if token in snapshot_fee_cache
        }
        return TerminalMarketSnapshot(books=books, fee_schedules=fees)

    async def terminal_settlements(
        token_markets: Mapping[str, str],
    ) -> Mapping[str, Decimal]:
        conditions = tuple(dict.fromkeys(token_markets.values()))
        results = await asyncio.gather(
            *(public_adapter.get_market_by_condition_id(item) for item in conditions),
            return_exceptions=True,
        )
        markets = {
            market.condition_id: market
            for market in results
            if not isinstance(market, BaseException)
            and market.closed is True
            and market.condition_id is not None
        }
        settlements: dict[str, Decimal] = {}
        for token, condition in token_markets.items():
            market = markets.get(condition)
            if market is None:
                continue
            for outcome in market.outcomes:
                if outcome.token_id == token and outcome.price in {
                    Decimal("0"),
                    Decimal("1"),
                }:
                    settlements[token] = outcome.price
                    break
        return settlements

    snapshot = await discovery.refresh() if discovery is not None else None
    followed_markets = {} if snapshot is None else snapshot.token_markets
    token_ids = tuple(followed_markets) or discovered_tokens
    fee_schedules = (
        snapshot.fee_schedules
        if snapshot is not None
        else await discover_market_fee_schedules(token_ids)
    )
    snapshot_fee_cache.update(fee_schedules)
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
            token_markets=followed_markets,
            market_discovery=None if discovery is None else discovery.refresh,
            discovery_interval_seconds=1.0,
            terminal_snapshot_fetcher=terminal_snapshot,
            terminal_settlement_fetcher=terminal_settlements,
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
    }
