"""CLI helpers for public research-source benchmarking.

Keeps research.py free of venue wiring. Reports are sanitized before print.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
from collections.abc import Awaitable, Callable, Mapping
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

from polysia.adapters.polymarket.copytrading_source import (
    JsonGetTransport,
    UrllibJsonGetTransport,
)
from polysia.adapters.polymarket.public import PolymarketPublicAdapter
from polysia.adapters.polymarket.research_sources import (
    ACTIVITY_SOURCE_ID,
    DATA_API_V2_ACTIVITY_PATH,
    DATA_API_V2_TRADES_PATH,
    REST_ACTIVITY_CANDIDATE,
    REST_TRADES_CANDIDATE,
    TRADES_SOURCE_ID,
    USER_CHANNEL_CANDIDATE,
    DataApiGlobalTradePollSource,
    DataApiWalletPollSource,
    OfficialMarketStreamSource,
    TerminalMarketSnapshot,
    discover_clob_market_fee_schedules,
    discover_market_fee_schedules,
    discover_public_follow_set,
    fetch_data_api_v2_window,
    public_wallet_alias,
    unique_wallet_rows,
)
from polysia.application.ports.copytrading import LeaderReadPurpose
from polysia.application.ports.research_evidence import ResearchObservationSource
from polysia.application.services.active_wallet_selection import active_selection_options
from polysia.application.services.source_benchmark import SourceBenchmarkReport
from polysia.domain.market import MarketFeeSchedule, MarketOrderBookSnapshot
from polysia.domain.market.settlement import verified_settlement_prices
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
                path=DATA_API_V2_ACTIVITY_PATH,
                source_id=ACTIVITY_SOURCE_ID,
                aliases=aliases,
                transport=transport,
            )
        )
        sources.append(
            DataApiWalletPollSource(
                REST_TRADES_CANDIDATE,
                path=DATA_API_V2_TRADES_PATH,
                source_id=TRADES_SOURCE_ID,
                aliases=aliases,
                transport=transport,
            )
        )
        sources.append(
            DataApiGlobalTradePollSource(aliases=aliases, transport=transport)
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
    runtime: Mapping[str, object] | None = None,
) -> tuple[tuple[ResearchObservationSource, ...], dict[str, object]]:
    from polysia.deployment.research_run_contract import (
        ACTIVE_SELECTION_POLICY,
        ACTIVE_SELECTION_POLICY_V2,
        CONFIGURED_SELECTION_POLICY,
        DEFAULT_SELECTION_POLICY,
        DEFAULT_WALLET_COUNT,
        RANKED_SELECTION_POLICY_V2,
    )
    from polysia.deployment.research_wallet_selection import (
        DEFAULT_SELECTION_DATABASE,
        load_current_polycop_snapshot,
        public_selection_payload,
        reconstruction_payload,
        resolve_polycop_active_follow_set,
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
    transport = UrllibJsonGetTransport()
    activity_evidence: dict[str, object] | None = None
    if policy in {ACTIVE_SELECTION_POLICY, ACTIVE_SELECTION_POLICY_V2}:
        counts, activity_evidence = await _measure_recent_alpha_activity(
            snapshot.candidates,
            transport=transport,
            observed=observed,
            candidate_limit=max(50, count),
            minimum_candidates=count,
            market_evidence_reader=(
                (lambda tokens: measure_latest_market_availability(transport, tokens))
                if policy == ACTIVE_SELECTION_POLICY_V2
                else None
            ),
        )
        selection = resolve_polycop_active_follow_set(
            snapshot,
            counts,
            now=observed,
            wallet_limit=count,
            policy_version=policy,
        )
    elif policy == DEFAULT_SELECTION_POLICY:
        selection = resolve_polycop_shadow_alpha_top3(
            snapshot, now=observed, wallet_limit=count
        )
    elif policy in {CONFIGURED_SELECTION_POLICY, RANKED_SELECTION_POLICY_V2}:
        selection = resolve_polycop_follow_set(
            snapshot,
            now=observed,
            wallet_limit=count,
            policy_version=policy,
        )
    else:
        raise ValueError("research selection policy is unsupported")
    sources, discovery = await build_persistent_sources_from_aliases(
        selection.addresses_by_alias,
        transport=transport,
        runtime=runtime,
    )
    discovery.update(public_selection_payload(selection))
    discovery["_reconstruction"] = reconstruction_payload(selection)
    discovery["_restricted_aliases"] = dict(selection.addresses_by_alias)
    discovery["discovery_status"] = "polycop_shadow_alpha"
    discovery["selection_mode"] = selection.policy_version
    if activity_evidence is not None:
        discovery["activity_preflight"] = activity_evidence
    return sources, discovery


async def measure_latest_market_availability(
    transport: JsonGetTransport,
    token_markets: Mapping[str, str],
) -> Mapping[str, tuple[bool, bool]]:
    """Read bounded public book depth and canonical fee metadata for preflight."""

    if not token_markets:
        return {}
    adapter = PolymarketPublicAdapter()
    tokens = tuple(token_markets)
    books: dict[str, MarketOrderBookSnapshot] = {}
    for offset in range(0, len(tokens), 50):
        books.update(await adapter.get_order_books(tokens[offset : offset + 50]))
    fees = await discover_clob_market_fee_schedules(transport, token_markets)
    return {
        token: (
            token in books and bool(books[token].bids) and bool(books[token].asks),
            token in fees,
        )
        for token in tokens
    }


async def _measure_recent_alpha_activity(
    candidates: tuple[object, ...],
    *,
    transport: JsonGetTransport,
    observed: datetime,
    lookback: timedelta = timedelta(hours=4),
    candidate_limit: int = 50,
    minimum_candidates: int = 3,
    market_limit_per_wallet: int = 4,
    max_pages_per_wallet: int = 20,
    max_requests_per_wallet: int = 20,
    max_total_data_requests: int = 1000,
    max_total_market_tokens: int = 500,
    time_budget_seconds: int = 180,
    market_evidence_reader: Callable[
        [Mapping[str, str]], Awaitable[Mapping[str, tuple[bool, bool]]]
    ] | None = None,
) -> tuple[dict[str, int], dict[str, object]]:
    from polysia.application.ports.dynamic_shadow import ProtectedShadowCandidate
    from polysia.deployment.research_wallet_selection import ResearchWalletSelectionError

    if not 1 <= candidate_limit <= 500 or not 1 <= market_limit_per_wallet <= 20:
        raise ValueError("candidate or market scan limit is outside the reviewed bound")
    if not 1 <= max_pages_per_wallet <= max_requests_per_wallet <= 100:
        raise ValueError("activity page/request budget is invalid")
    if not 1 <= time_budget_seconds <= 600:
        raise ValueError("activity time budget is invalid")
    if not 1 <= max_total_data_requests <= 5000 or not 1 <= max_total_market_tokens <= 1000:
        raise ValueError("aggregate activity budgets are invalid")

    class BudgetedTransport:
        def __init__(self) -> None:
            self.used = 0

        async def get_json(
            self, base_url: str, path: str, params: Mapping[str, str | int | bool],
            *, purpose: LeaderReadPurpose = LeaderReadPurpose.BASELINE,
        ) -> Any:
            if self.used >= max_total_data_requests:
                raise ValueError("aggregate Data API request budget exhausted")
            self.used += 1
            return await transport.get_json(base_url, path, params, purpose=purpose)

    budgeted_transport = BudgetedTransport()
    preparation_started = asyncio.get_running_loop().time()

    candidates_by_wallet: dict[str, ProtectedShadowCandidate] = {}
    for candidate in sorted(
        (
            candidate
            for candidate in candidates
            if isinstance(candidate, ProtectedShadowCandidate)
            and "SHADOW_ALPHA" in candidate.pools
            and candidate.alpha_rank is not None
        ),
        key=lambda item: (int(item.alpha_rank or 0), item.wallet_id),
    ):
        candidates_by_wallet.setdefault(candidate.wallet_id, candidate)
    ranked = tuple(candidates_by_wallet.values())[:candidate_limit]
    if len(ranked) < minimum_candidates:
        raise ResearchWalletSelectionError(
            "activity preflight has insufficient SHADOW_ALPHA candidates"
        )
    start = observed - lookback

    semaphore = asyncio.Semaphore(5)

    async def measure(
        candidate: ProtectedShadowCandidate,
    ) -> tuple[str, int, str, int, tuple[tuple[str, str, int], ...]]:
        try:
            async with semaphore:
                rows = await fetch_data_api_v2_window(
                    budgeted_transport,
                    DATA_API_V2_TRADES_PATH,
                    {
                        "user": candidate.address,
                        "limit": 1000,
                        "start": int(start.timestamp()),
                        "end": int(observed.timestamp()),
                        "taker_only": False,
                    },
                    purpose=LeaderReadPurpose.DISCOVERY,
                    max_pages=max_pages_per_wallet,
                    max_requests=max_requests_per_wallet,
                    max_elapsed_seconds=min(30, time_budget_seconds),
                )
        except (OSError, TimeoutError, TypeError, ValueError) as error:
            raise ResearchWalletSelectionError(
                "recent activity has insufficient coverage"
            ) from error
        for row in rows:
            wallet = row.get("proxyWallet")
            timestamp = row.get("timestamp")
            if (
                not isinstance(wallet, str)
                or wallet.casefold() != candidate.address.casefold()
                or isinstance(timestamp, bool)
                or not isinstance(timestamp, int)
                or not int(start.timestamp()) <= timestamp <= int(observed.timestamp())
            ):
                raise ResearchWalletSelectionError(
                    "recent activity has insufficient coverage"
                )
        unique_rows = unique_wallet_rows(rows)
        recent = sorted(
            unique_rows,
            key=lambda row: (int(row["timestamp"]), str(row.get("id") or "")),
            reverse=True,
        )
        market_counts: dict[tuple[str, str], int] = {}
        for row in recent:
            token, market = row.get("asset"), row.get("conditionId")
            if isinstance(token, str) and token and isinstance(market, str) and market:
                key = (token, market)
                market_counts[key] = market_counts.get(key, 0) + 1
        return (
            candidate.wallet_id,
            len(unique_rows),
            public_wallet_alias(candidate.address),
            int(candidate.alpha_rank or 0),
            tuple((token, market, market_counts[(token, market)]) for token, market in
                  tuple(market_counts)[:market_limit_per_wallet]),
        )

    try:
        measured = await asyncio.wait_for(
            asyncio.gather(*(measure(candidate) for candidate in ranked)),
            timeout=time_budget_seconds,
        )
    except TimeoutError as error:
        raise ResearchWalletSelectionError(
            "recent activity has insufficient coverage within the preflight time budget"
        ) from error
    token_markets: dict[str, str] = {}
    for _wallet_id, _count, _alias, _rank, markets in measured:
        for token, market, _same_token_count in markets:
            previous = token_markets.setdefault(token, market)
            if previous != market:
                raise ResearchWalletSelectionError(
                    "market evidence preflight has conflicting token identity"
                )
    if len(token_markets) > max_total_market_tokens:
        raise ResearchWalletSelectionError(
            "market evidence token budget exhausted before complete screening"
        )
    availability: Mapping[str, tuple[bool, bool]] = {}
    if market_evidence_reader is not None:
        try:
            remaining = time_budget_seconds - (
                asyncio.get_running_loop().time() - preparation_started
            )
            if remaining <= 0:
                raise TimeoutError("activity preflight deadline exhausted")
            availability = await asyncio.wait_for(
                market_evidence_reader(token_markets), timeout=min(60, remaining),
            )
        except (OSError, TimeoutError, TypeError, ValueError) as error:
            raise ResearchWalletSelectionError(
                "market evidence preflight has insufficient coverage"
            ) from error
        if set(availability) != set(token_markets):
            raise ResearchWalletSelectionError(
                "market evidence preflight returned incomplete token coverage"
            )
    counts: dict[str, int] = {}
    observable_counts: dict[str, int] = {}
    public_rows: list[dict[str, object]] = []
    observable_event_count = 0
    for wallet_id, count, alias, rank, markets in measured:
        checked = [
            (token, events, *availability.get(token, (False, False)))
            for token, _market, events in markets
        ]
        observable = sum(events for _token, events, book, fee in checked if book and fee)
        book = any(item[2] for item in checked)
        fee = any(item[3] for item in checked)
        eligible = count > 0 and (market_evidence_reader is None or observable > 0)
        counts[wallet_id] = count if eligible else 0
        observable_counts[wallet_id] = observable if eligible else 0
        if eligible and market_evidence_reader is not None:
            observable_event_count += observable
        row_payload: dict[str, object] = {
            "alpha_rank": rank, "event_count": count, "wallet_alias": alias,
            "wallet_id": wallet_id,
            "market_token_bound": bool(markets),
            "market_pairs_checked": len(markets),
            "market_pairs_available": sum(
                1 for _token, _events, has_book, has_fee in checked if has_book and has_fee
            ),
            "book_depth_available": book if market_evidence_reader is not None else None,
            "fee_available": fee if market_evidence_reader is not None else None,
            "selection_eligible": eligible,
            "reason": (
                "inactive" if count == 0 else
                "recent_activity_market_unchecked" if market_evidence_reader is None else
                "missing_market_token_mapping" if not markets else
                "missing_book_or_depth" if market_evidence_reader is not None and not book else
                "missing_fee" if market_evidence_reader is not None and not fee else
                "unobservable_market_pairs" if market_evidence_reader is not None
                and observable == 0 else
                "observable_recent_activity"
            ),
        }
        if market_evidence_reader is not None:
            row_payload["observable_recent_event_count"] = observable
        public_rows.append(row_payload)
    evidence = {
        "candidate_count": len(measured),
        "lookback_ends_at": observed.isoformat(),
        "lookback_seconds": int(lookback.total_seconds()),
        "rows": public_rows,
        "source": "polymarket:data-api-v2:trades",
        "market_evidence_status": (
            "checked_bounded_recent_market_pairs" if market_evidence_reader is not None
            else "not_checked"
        ),
    }
    observed_eligible = observable_event_count
    evidence["evaluable_rate_estimate"] = (
        {"status": "UNAVAILABLE", "reason": "insufficient_observed_eligible_activity"}
        if observed_eligible < 5 or market_evidence_reader is None else
        {
            "status": "ROUGH_OBSERVABLE_ACTIVITY_RATE_NOT_FORECAST",
            "bounded_market_observable_events_per_hour": str(
                Decimal(observed_eligible) * Decimal(3600) /
                Decimal(int(lookback.total_seconds()))
            ),
            "hours_for_20_if_rate_and_evidence_hold": str(
                Decimal(20) * Decimal(lookback.total_seconds()) /
                (Decimal(3600) * Decimal(observed_eligible))
            ),
            "uncertainty": "high; future wallets and markets may differ",
        }
    )
    if market_evidence_reader is not None:
        evidence["cohort_options"] = active_selection_options(
            ranked, counts, observable_counts,
            lookback_seconds=int(lookback.total_seconds()),
            requested_count=minimum_candidates,
        )
    evidence["digest"] = hashlib.sha256(
        json.dumps(evidence, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return counts, evidence


async def build_persistent_sources_from_aliases(
    aliases: Mapping[str, str],
    *,
    transport: UrllibJsonGetTransport | None = None,
    discovered_tokens: tuple[str, ...] = (),
    runtime: Mapping[str, object] | None = None,
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
            verified = verified_settlement_prices(market)
            if verified is not None and token in verified:
                settlements[token] = verified[token]
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
    source_runtime: dict[str, Any] = {} if runtime is None else {
        "poll_interval_seconds": float(str(runtime["poll_interval_seconds"])),
        "page_limit": int(str(runtime["page_limit"])),
        "max_pages": int(str(runtime["max_pages"])),
        "max_requests": int(str(runtime["max_requests"])),
        "request_timeout_seconds": int(str(runtime["request_timeout_seconds"])),
        "overlap_seconds": int(str(runtime["overlap_seconds"])),
    }
    if aliases:
        sources.append(
            DataApiWalletPollSource(
                REST_TRADES_CANDIDATE,
                path=DATA_API_V2_TRADES_PATH,
                source_id=TRADES_SOURCE_ID,
                aliases=aliases,
                transport=transport,
                initial_delay_seconds=_PERSISTENT_MARKET_WARMUP_SECONDS,
                **source_runtime,
            )
        )
        sources.append(
            DataApiWalletPollSource(
                REST_ACTIVITY_CANDIDATE,
                path=DATA_API_V2_ACTIVITY_PATH,
                source_id=ACTIVITY_SOURCE_ID,
                aliases=aliases,
                transport=transport,
                initial_delay_seconds=_PERSISTENT_MARKET_WARMUP_SECONDS,
                **source_runtime,
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
