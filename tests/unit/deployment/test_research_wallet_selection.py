from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from polysia.adapters.polymarket.research_sources import public_wallet_alias
from polysia.application.ports.continuous_shadow import ContinuousSelectionSnapshot
from polysia.application.ports.dynamic_shadow import ProtectedShadowCandidate
from polysia.deployment.research_wallet_selection import (
    POLYCOP_SHADOW_ALPHA_ACTIVE_TOP3_V1,
    POLYCOP_SHADOW_ALPHA_ACTIVE_V2,
    POLYCOP_SHADOW_ALPHA_CONFIGURED_V1,
    POLYCOP_SHADOW_ALPHA_TOP3_V1,
    ResearchWalletSelectionError,
    load_current_polycop_snapshot,
    public_selection_payload,
    reconstruction_payload,
    resolve_polycop_active_follow_set,
    resolve_polycop_follow_set,
    resolve_polycop_shadow_alpha_top3,
    verify_reconstruction,
)

NOW = datetime(2026, 9, 19, 12, tzinfo=UTC)
WALLET_1 = "0x1111111111111111111111111111111111111111"
WALLET_2 = "0x2222222222222222222222222222222222222222"
WALLET_3 = "0x3333333333333333333333333333333333333333"
WALLET_4 = "0x4444444444444444444444444444444444444444"
WALLET_STRESS = "0x5555555555555555555555555555555555555555"


def _candidate(
    wallet_id: str,
    address: str,
    *,
    alpha_rank: int | None = None,
    stress_rank: int | None = None,
    pools: tuple[str, ...] | None = None,
) -> ProtectedShadowCandidate:
    selected_pools: tuple[str, ...] = pools or ()
    if not selected_pools:
        if alpha_rank is not None:
            selected_pools = (*selected_pools, "SHADOW_ALPHA")
        if stress_rank is not None:
            selected_pools = (*selected_pools, "SHADOW_STRESS")
    return ProtectedShadowCandidate(
        wallet_id=wallet_id,
        address=address,
        pools=selected_pools,
        alpha_rank=alpha_rank,
        stress_rank=stress_rank,
    )


def _snapshot(
    candidates: tuple[ProtectedShadowCandidate, ...],
    *,
    published_at: datetime = NOW,
    digest: str | None = None,
) -> ContinuousSelectionSnapshot:
    snapshot = ContinuousSelectionSnapshot.create(
        source_id="polycop",
        selection_run_id="selection-run-1",
        source_snapshot_id="source-snap-1",
        feature_set_version="features-v1",
        policy_id="copyability-v1",
        policy_version="policy-v1",
        ranking_version="ranking-v1",
        published_at=published_at,
        candidates=candidates,
    )
    if digest is None:
        return snapshot
    return ContinuousSelectionSnapshot(
        source_id=snapshot.source_id,
        selection_run_id=snapshot.selection_run_id,
        source_snapshot_id=snapshot.source_snapshot_id,
        feature_set_version=snapshot.feature_set_version,
        policy_id=snapshot.policy_id,
        policy_version=snapshot.policy_version,
        ranking_version=snapshot.ranking_version,
        published_at=snapshot.published_at,
        candidates=snapshot.candidates,
        digest=digest,
    )


def _alpha_snapshot() -> ContinuousSelectionSnapshot:
    return _snapshot(
        (
            _candidate("w-stress", WALLET_STRESS, stress_rank=1),
            _candidate("w4", WALLET_4, alpha_rank=4),
            _candidate("w2", WALLET_2, alpha_rank=2),
            _candidate("w1", WALLET_1, alpha_rank=1, stress_rank=9),
            _candidate("w3", WALLET_3, alpha_rank=3),
            _candidate("w1", WALLET_1, alpha_rank=1, stress_rank=9),
        )
    )


def test_selects_top_ranked_distinct_shadow_alpha_wallets() -> None:
    selection = resolve_polycop_shadow_alpha_top3(_alpha_snapshot(), now=NOW)

    assert selection.policy_version == POLYCOP_SHADOW_ALPHA_TOP3_V1
    assert selection.wallet_ids == ("w1", "w2", "w3")
    assert selection.selected_ranks == (1, 2, 3)
    assert selection.selected_pools == ("SHADOW_ALPHA",)
    assert selection.addresses_by_alias[public_wallet_alias(WALLET_1)] == WALLET_1
    assert public_wallet_alias(WALLET_STRESS) not in selection.addresses_by_alias
    assert public_wallet_alias(WALLET_4) not in selection.addresses_by_alias
    public = public_selection_payload(selection)
    assert "0x1111111111111111111111111111111111111111" not in str(public)
    reconstruction = reconstruction_payload(selection)
    restored = verify_reconstruction(reconstruction, public | {"aliases": list(selection.aliases)})
    assert restored == selection.addresses_by_alias


def test_configured_count_keeps_stress_out_of_profitability_selection() -> None:
    selection = resolve_polycop_follow_set(
        _alpha_snapshot(),
        now=NOW,
        wallet_limit=2,
        policy_version=POLYCOP_SHADOW_ALPHA_CONFIGURED_V1,
    )
    assert selection.policy_version == POLYCOP_SHADOW_ALPHA_CONFIGURED_V1
    assert selection.wallet_ids == ("w1", "w2")
    assert public_wallet_alias(WALLET_STRESS) not in selection.addresses_by_alias
    public = public_selection_payload(selection)
    assert public["selection_policy"] == POLYCOP_SHADOW_ALPHA_CONFIGURED_V1
    assert public["wallet_count"] == 2
    assert selection.reasons[0].startswith("highest-ranked distinct SHADOW_ALPHA")


def test_activity_aware_selection_prefers_recent_active_alpha_wallets() -> None:
    selection = resolve_polycop_active_follow_set(
        _alpha_snapshot(),
        {"w1": 1, "w2": 12, "w3": 0, "w4": 25, "w-stress": 100},
        now=NOW,
    )

    assert selection.policy_version == POLYCOP_SHADOW_ALPHA_ACTIVE_TOP3_V1
    assert selection.wallet_ids == ("w4", "w2", "w1")
    assert selection.selected_ranks == (4, 2, 1)
    assert public_wallet_alias(WALLET_STRESS) not in selection.addresses_by_alias
    assert selection.reasons[0] == "recent-active SHADOW_ALPHA event_count=25 alpha_rank=4"


def test_activity_aware_selection_requires_three_active_alpha_wallets() -> None:
    with pytest.raises(ResearchWalletSelectionError, match="recent-active"):
        resolve_polycop_active_follow_set(
            _alpha_snapshot(),
            {"w1": 1, "w2": 12, "w3": 0, "w4": 0},
            now=NOW,
        )


@pytest.mark.parametrize("wallet_count", [5, 10, 20, 40])
def test_v2_active_selection_freezes_requested_supported_count(wallet_count: int) -> None:
    candidates = tuple(
        _candidate(f"w{index}", f"0x{index:040x}", alpha_rank=index)
        for index in range(1, 41)
    )
    snapshot = _snapshot(candidates)
    counts = {f"w{index}": index for index in range(1, 41)}
    selected = resolve_polycop_active_follow_set(
        snapshot, counts, now=NOW, wallet_limit=wallet_count,
        policy_version=POLYCOP_SHADOW_ALPHA_ACTIVE_V2,
    )
    assert len(selected.wallet_ids) == wallet_count
    assert selected.wallet_ids[0] == "w40"
    assert selected.policy_version == POLYCOP_SHADOW_ALPHA_ACTIVE_V2
    assert len(verify_reconstruction(
        reconstruction_payload(selected), public_selection_payload(selected)
    )) == wallet_count


def test_missing_snapshot_fails_closed(tmp_path: Path) -> None:
    with pytest.raises(ResearchWalletSelectionError, match="unavailable"):
        load_current_polycop_snapshot(tmp_path / "missing.sqlite3")


def test_stale_inconsistent_and_insufficient_selection_fail_closed() -> None:
    stale = _alpha_snapshot()
    with pytest.raises(ResearchWalletSelectionError, match="stale"):
        resolve_polycop_shadow_alpha_top3(
            stale,
            now=NOW + timedelta(hours=36, seconds=1),
        )
    inconsistent = _snapshot(
        (_candidate("w1", WALLET_1, alpha_rank=1),),
        digest="0" * 64,
    )
    with pytest.raises(ResearchWalletSelectionError, match="digest mismatch"):
        resolve_polycop_shadow_alpha_top3(inconsistent, now=NOW)
    insufficient = _snapshot(
        (
            _candidate("w1", WALLET_1, alpha_rank=1),
            _candidate("w2", WALLET_2, alpha_rank=2),
            _candidate("stress", WALLET_STRESS, stress_rank=1),
        )
    )
    with pytest.raises(ResearchWalletSelectionError, match="insufficient"):
        resolve_polycop_shadow_alpha_top3(insufficient, now=NOW)


def test_reconstruction_digest_tampering_fails_closed() -> None:
    selection = resolve_polycop_shadow_alpha_top3(_alpha_snapshot(), now=NOW)
    public = public_selection_payload(selection) | {"aliases": list(selection.aliases)}
    reconstruction = reconstruction_payload(selection)
    reconstruction["digest"] = "0" * 64
    with pytest.raises(ResearchWalletSelectionError, match="reconstruction digest"):
        verify_reconstruction(reconstruction, public)
    public["selection_digest"] = "0" * 64
    with pytest.raises(ResearchWalletSelectionError, match="selection digest"):
        verify_reconstruction(reconstruction_payload(selection), public)


def test_runner_sources_do_not_fall_back_to_public_discovery(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from polysia.cli_commands import research_evidence_cli

    async def boom_discover(
        *_args: object, **_kwargs: object
    ) -> tuple[dict[str, str], tuple[str, ...]]:
        raise AssertionError("public discovery must not run for Canary/Main")

    async def fake_builder(aliases: dict[str, str], **_kwargs: object):
        return (), {
            "followed_aliases": sorted(aliases),
            "market_tokens": [],
            "required_source_ids": [],
            "optional_source_ids": [],
            "unavailable": [],
        }

    monkeypatch.setattr(research_evidence_cli, "discover_public_follow_set", boom_discover)
    monkeypatch.setattr(
        research_evidence_cli,
        "build_persistent_sources_from_aliases",
        fake_builder,
    )
    monkeypatch.setattr(
        "polysia.deployment.research_wallet_selection.load_current_polycop_snapshot",
        lambda _database: _alpha_snapshot(),
    )
    sources, discovery = asyncio.run(
        research_evidence_cli.build_persistent_runner_sources(
            database=Path("unused.sqlite3"),
            now=NOW,
        )
    )
    assert sources == ()
    assert discovery["selection_policy"] == POLYCOP_SHADOW_ALPHA_TOP3_V1
    assert discovery["selection_mode"] == POLYCOP_SHADOW_ALPHA_TOP3_V1
    assert "0x1111111111111111111111111111111111111111" not in str(
        {key: value for key, value in discovery.items() if not str(key).startswith("_")}
    )


def test_runner_activity_policy_freezes_recent_active_alpha_wallets(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from polysia.cli_commands import research_evidence_cli
    from polysia.deployment.research_run_contract import ACTIVE_SELECTION_POLICY

    activity = {WALLET_1: 1, WALLET_2: 12, WALLET_3: 0, WALLET_4: 25}

    class ActivityTransport:
        async def get_json(
            self,
            _base_url: str,
            path: str,
            params: dict[str, str | int | bool],
            **_kwargs: object,
        ) -> object:
            assert path == "/v2/trades"
            count = activity.get(str(params["user"]), 0)
            return {
                "data": [
                    {"proxy_wallet": params["user"], "id": str(index),
                     "timestamp": int(NOW.timestamp())}
                    for index in range(count)
                ],
                "pagination": {"has_more": False, "next_cursor": None},
            }

    async def fake_builder(aliases: dict[str, str], **_kwargs: object):
        return (), {
            "followed_aliases": sorted(aliases),
            "market_tokens": [],
            "required_source_ids": [],
            "optional_source_ids": [],
            "unavailable": [],
        }

    monkeypatch.setattr(research_evidence_cli, "UrllibJsonGetTransport", ActivityTransport)
    monkeypatch.setattr(
        research_evidence_cli,
        "build_persistent_sources_from_aliases",
        fake_builder,
    )
    monkeypatch.setattr(
        "polysia.deployment.research_wallet_selection.load_current_polycop_snapshot",
        lambda _database: _alpha_snapshot(),
    )

    sources, discovery = asyncio.run(
        research_evidence_cli.build_persistent_runner_sources(
            database=Path("unused.sqlite3"),
            now=NOW,
            selection_policy=ACTIVE_SELECTION_POLICY,
        )
    )

    assert sources == ()
    assert discovery["selection_policy"] == POLYCOP_SHADOW_ALPHA_ACTIVE_TOP3_V1
    assert discovery["wallet_ids"] == ["w4", "w2", "w1"]
    preflight = discovery["activity_preflight"]
    assert isinstance(preflight, dict)
    assert preflight["candidate_count"] == 4
    assert preflight["source"] == "polymarket:data-api-v2:trades"
    assert len(str(preflight["digest"])) == 64


def test_activity_preflight_counts_all_pages_once_and_fails_on_incomplete() -> None:
    from polysia.cli_commands.research_evidence_cli import _measure_recent_alpha_activity

    candidates = _alpha_snapshot().candidates

    class PagedTransport:
        def __init__(self, fail: bool = False) -> None:
            self.fail = fail
            self.calls: list[dict[str, str | int | bool]] = []

        async def get_json(
            self,
            _base_url: str,
            _path: str,
            params: dict[str, str | int | bool],
            **_kwargs: object,
        ) -> object:
            self.calls.append(dict(params))
            if params["user"] == WALLET_1:
                if "cursor" not in params:
                    return {
                        "data": [{"id": "a", "transaction_hash": "tx-a",
                                  "proxy_wallet": WALLET_1, "timestamp": int(NOW.timestamp())}],
                        "pagination": {"has_more": True, "next_cursor": "next"},
                    }
                if self.fail:
                    return {"data": None, "pagination": {"has_more": False}}
                return {
                    "data": [
                        {"id": "a", "transaction_hash": "tx-a",
                         "proxy_wallet": WALLET_1, "timestamp": int(NOW.timestamp())},
                        {"id": "b", "transaction_hash": "tx-b",
                         "proxy_wallet": WALLET_1, "timestamp": int(NOW.timestamp())},
                    ],
                    "pagination": {"has_more": False, "next_cursor": None},
                }
            return {
                "data": [{"id": "one", "transaction_hash": "tx-one",
                          "proxy_wallet": params["user"],
                          "timestamp": int(NOW.timestamp())}],
                "pagination": {"has_more": False, "next_cursor": None},
            }

    transport = PagedTransport()
    counts, evidence = asyncio.run(_measure_recent_alpha_activity(
        candidates, transport=transport, observed=NOW
    ))
    assert counts["w1"] == 2
    assert evidence["lookback_ends_at"] == NOW.isoformat()
    first, second = [call for call in transport.calls if call["user"] == WALLET_1]
    assert second == {**first, "cursor": "next"}

    with pytest.raises(ResearchWalletSelectionError, match="insufficient coverage"):
        asyncio.run(_measure_recent_alpha_activity(
            candidates, transport=PagedTransport(fail=True), observed=NOW
        ))


def test_active_preflight_filters_missing_market_evidence_without_hiding_source_counts() -> None:
    from polysia.cli_commands.research_evidence_cli import _measure_recent_alpha_activity

    class Transport:
        async def get_json(
            self, _base_url: str, _path: str,
            params: dict[str, str | int | bool], **_kwargs: object,
        ) -> object:
            address = str(params["user"])
            index = int(address[2:], 16)
            return {
                "data": [{
                    "id": f"trade-{index}", "transaction_hash": f"tx-{index}",
                    "proxy_wallet": address, "timestamp": int(NOW.timestamp()),
                    "token_id": f"token-{index}", "condition_id": f"market-{index}",
                }],
                "pagination": {"has_more": False, "next_cursor": None},
            }

    candidates = tuple(
        _candidate(f"w{index}", f"0x{index:040x}", alpha_rank=index)
        for index in range(1, 6)
    )

    async def availability(
        tokens: dict[str, str],
    ) -> dict[str, tuple[bool, bool]]:
        assert len(tokens) == 5
        return {
            token: (token != "token-1", token != "token-2")
            for token in tokens
        }

    counts, evidence = asyncio.run(_measure_recent_alpha_activity(
        candidates, transport=Transport(), observed=NOW,
        minimum_candidates=5, market_evidence_reader=availability,
    ))
    assert counts == {"w1": 0, "w2": 0, "w3": 1, "w4": 1, "w5": 1}
    rows = evidence["rows"]
    assert isinstance(rows, list)
    assert [row["event_count"] for row in rows] == [1] * 5
    assert [row["reason"] for row in rows[:2]] == [
        "missing_book_or_depth", "missing_fee",
    ]
    assert evidence["evaluable_rate_estimate"]["status"] == "UNAVAILABLE"
    options = evidence["cohort_options"]
    assert isinstance(options, list)
    assert options[0]["wallet_count"] == 5
    assert options[0]["status"] == "INSUFFICIENT_ACTIVE_CANDIDATES"


def test_activity_preflight_checks_earlier_recent_market_and_bounds_aggregate_reads() -> None:
    from polysia.cli_commands.research_evidence_cli import _measure_recent_alpha_activity

    class Transport:
        def __init__(self) -> None:
            self.calls = 0

        async def get_json(
            self, _base_url: str, _path: str,
            params: dict[str, str | int | bool], **_kwargs: object,
        ) -> object:
            self.calls += 1
            return {"data": [
                {"id": "latest", "transaction_hash": "latest", "proxy_wallet": params["user"],
                 "timestamp": int(NOW.timestamp()), "token_id": "unavailable",
                 "condition_id": "market-latest"},
                {"id": "earlier", "transaction_hash": "earlier", "proxy_wallet": params["user"],
                 "timestamp": int(NOW.timestamp()) - 60, "token_id": "available",
                 "condition_id": "market-earlier"},
            ], "pagination": {"has_more": False, "next_cursor": None}}

    transport = Transport()

    async def availability(tokens: dict[str, str]) -> dict[str, tuple[bool, bool]]:
        assert tokens == {"unavailable": "market-latest", "available": "market-earlier"}
        return {"unavailable": (False, False), "available": (True, True)}

    counts, evidence = asyncio.run(_measure_recent_alpha_activity(
        (_candidate("one", WALLET_1, alpha_rank=1),),
        transport=transport, observed=NOW, minimum_candidates=1,
        market_evidence_reader=availability,
    ))
    assert counts == {"one": 2}
    assert evidence["rows"][0]["market_pairs_checked"] == 2
    assert evidence["rows"][0]["observable_recent_event_count"] == 1
    assert evidence["rows"][0]["selection_eligible"] is True
    assert transport.calls == 1
    with pytest.raises(ResearchWalletSelectionError, match="insufficient coverage"):
        asyncio.run(_measure_recent_alpha_activity(
            (_candidate("one", WALLET_1, alpha_rank=1),
             _candidate("two", WALLET_2, alpha_rank=2)),
            transport=transport, observed=NOW, minimum_candidates=2,
            max_total_data_requests=1,
        ))


def test_activity_preflight_rejects_incomplete_market_response() -> None:
    from polysia.cli_commands.research_evidence_cli import _measure_recent_alpha_activity

    class Transport:
        async def get_json(
            self, _base_url: str, _path: str,
            params: dict[str, str | int | bool], **_kwargs: object,
        ) -> object:
            return {"data": [{"id": "x", "transaction_hash": "x",
                              "proxy_wallet": params["user"],
                              "timestamp": int(NOW.timestamp()),
                              "token_id": "one", "condition_id": "market"}],
                    "pagination": {"has_more": False, "next_cursor": None}}

    async def missing(_tokens: dict[str, str]) -> dict[str, tuple[bool, bool]]:
        return {}

    with pytest.raises(ResearchWalletSelectionError, match="incomplete token coverage"):
        asyncio.run(_measure_recent_alpha_activity(
            (_candidate("one", WALLET_1, alpha_rank=1),),
            transport=Transport(), observed=NOW, minimum_candidates=1,
            market_evidence_reader=missing,
        ))


def test_public_benchmark_discovery_remains_available(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from polysia.cli_commands import research_evidence_cli

    async def fake_discover(
        *_args: object, **_kwargs: object
    ) -> tuple[dict[str, str], tuple[str, ...]]:
        return {public_wallet_alias(WALLET_1): WALLET_1}, ("token-1",)

    async def fake_builder(aliases: dict[str, str], **_kwargs: object):
        return (), {
            "followed_aliases": sorted(aliases),
            "market_tokens": ["token-1"],
            "required_source_ids": ["rest_trades"],
            "optional_source_ids": [],
            "unavailable": [],
        }

    monkeypatch.setattr(research_evidence_cli, "discover_public_follow_set", fake_discover)
    monkeypatch.setattr(
        research_evidence_cli,
        "build_persistent_sources_from_aliases",
        fake_builder,
    )
    _sources, discovery = asyncio.run(research_evidence_cli.build_persistent_public_sources())
    assert discovery["selection_mode"] == "public-discovery"
    assert discovery["discovery_status"] == "measured"


def test_actual_persistent_source_composition_uses_frozen_cursor_budgets(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from polysia.cli_commands import research_evidence_cli
    from polysia.deployment.research_run_contract import ResearchRunSpec, resolve_run_plan

    class NoNetworkDiscovery:
        def __init__(self, *_args: object, **_kwargs: object) -> None:
            pass

        async def refresh(self) -> None:
            return None

    async def no_fees(_tokens: tuple[str, ...]) -> dict[str, object]:
        return {}

    monkeypatch.setattr(
        "polysia.adapters.polymarket.research_sources.FollowedMarketDiscovery",
        NoNetworkDiscovery,
    )
    monkeypatch.setattr(research_evidence_cli, "discover_market_fee_schedules", no_fees)
    plan = resolve_run_plan(ResearchRunSpec(
        profile="canary", code_sha="a" * 40,
        spec_version="research-run-spec-v2",
        runtime={"poll_interval_seconds": 3, "max_pages": 7,
                 "max_requests": 9, "overlap_seconds": 90},
    ), observed=NOW)
    sources, _discovery = asyncio.run(
        research_evidence_cli.build_persistent_sources_from_aliases(
            {public_wallet_alias(WALLET_1): WALLET_1},
            transport=object(),  # No request runs during source composition.
            runtime=plan.runtime,
        )
    )
    assert len(sources) == 3
    for source in sources[:2]:
        assert source._poll_interval_seconds == 3
        assert source._max_pages == 7
        assert source._max_requests == 9
        assert source._overlap_seconds == 90


@pytest.mark.parametrize("wallet_count", [5, 10, 20, 40])
def test_v3_selected_wallets_reach_real_source_factory(
    monkeypatch: pytest.MonkeyPatch, wallet_count: int,
) -> None:
    from polysia.cli_commands import research_evidence_cli
    from polysia.deployment.research_run_contract import (
        CAPACITY_SPEC_VERSION,
        RANKED_SELECTION_POLICY_V2,
        ResearchRunSpec,
        resolve_run_plan,
    )

    class NoNetworkDiscovery:
        def __init__(self, *_args: object, **_kwargs: object) -> None:
            pass

        async def refresh(self) -> None:
            return None

    async def no_fees(_tokens: tuple[str, ...]) -> dict[str, object]:
        return {}

    snapshot = _alpha_snapshot()
    candidates = tuple(
        _candidate(f"wallet-{index}", f"0x{index:040x}", alpha_rank=index)
        for index in range(1, 41)
    )
    monkeypatch.setattr(
        "polysia.deployment.research_wallet_selection.load_current_polycop_snapshot",
        lambda _database: snapshot.__class__.create(
            source_id=snapshot.source_id,
            selection_run_id=snapshot.selection_run_id,
            source_snapshot_id=snapshot.source_snapshot_id,
            feature_set_version=snapshot.feature_set_version,
            policy_id=snapshot.policy_id,
            policy_version=snapshot.policy_version,
            ranking_version=snapshot.ranking_version,
            published_at=snapshot.published_at,
            candidates=candidates,
        ),
    )
    monkeypatch.setattr(
        "polysia.adapters.polymarket.research_sources.FollowedMarketDiscovery",
        NoNetworkDiscovery,
    )
    monkeypatch.setattr(research_evidence_cli, "discover_market_fee_schedules", no_fees)
    plan = resolve_run_plan(ResearchRunSpec(
        profile="canary", code_sha="a" * 40, spec_version=CAPACITY_SPEC_VERSION,
        wallet_count=wallet_count, selection_policy=RANKED_SELECTION_POLICY_V2,
        runtime={"poll_interval_seconds": 3, "max_pages": 7, "max_requests": 9},
    ), observed=NOW)
    sources, discovery = asyncio.run(research_evidence_cli.build_persistent_runner_sources(
        database=Path("unused.sqlite3"), now=NOW,
        wallet_count=wallet_count, selection_policy=RANKED_SELECTION_POLICY_V2,
        runtime=plan.runtime,
    ))
    assert len(sources) == 3
    assert discovery["wallet_count"] == wallet_count
    assert len(discovery["aliases"]) == wallet_count
    for source in sources[:2]:
        assert len(source._aliases) == wallet_count
        assert source._max_pages == 7
