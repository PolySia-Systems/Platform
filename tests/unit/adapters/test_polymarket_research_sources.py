from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from polysia.adapters.polymarket.research_sources import (
    ACTIVITY_SOURCE_ID,
    REST_ACTIVITY_CANDIDATE,
    USER_CHANNEL_CANDIDATE,
    DataApiWalletPollSource,
    OfficialMarketStreamSource,
    _normalize_wallet_row,
    discover_public_follow_set,
    public_wallet_alias,
)
from polysia.application.ports.copytrading import LeaderReadPurpose
from polysia.domain.events import MarketDataEvent
from polysia.domain.research_evidence.models import (
    AttributionStatus,
    ObservationKind,
    SourceCandidateStatus,
)

WALLET = "0x1111111111111111111111111111111111111111"
OBSERVED = datetime(2026, 9, 7, 12, 0, tzinfo=UTC)


class _BoundedClock:
    def __init__(self) -> None:
        self.n = 0

    def __call__(self) -> datetime:
        self.n += 1
        if self.n < 8:
            return OBSERVED
        return OBSERVED + timedelta(seconds=10)


class FakeTransport:
    def __init__(self, payload: object) -> None:
        self.payload = payload
        self.calls: list[tuple[str, str]] = []

    async def get_json(
        self,
        base_url: str,
        path: str,
        params: dict[str, str | int | bool],
        *,
        purpose: LeaderReadPurpose = LeaderReadPurpose.BASELINE,
    ) -> object:
        del purpose
        self.calls.append((base_url, path))
        return self.payload


@pytest.mark.asyncio
async def test_wallet_poll_source_aliases_and_does_not_emit_addresses() -> None:
    transport = FakeTransport(
        [
            {
                "proxyWallet": WALLET,
                "side": "BUY",
                "price": "0.51",
                "size": "2",
                "timestamp": int(OBSERVED.timestamp()) - 3,
                "conditionId": "0x" + "a" * 64,
                "asset": "token-1",
                "transactionHash": "0x" + "b" * 64,
            }
        ]
    )
    source = DataApiWalletPollSource(
        REST_ACTIVITY_CANDIDATE,
        path="/activity",
        source_id=ACTIVITY_SOURCE_ID,
        aliases={public_wallet_alias(WALLET): WALLET},
        transport=transport,
        clock=_BoundedClock(),
        monotonic_ns=lambda: 10,
        sleep=_noop_sleep,
        poll_interval_seconds=1,
    )
    events = []
    async for event in source.run(run_id="r1", deadline=OBSERVED + timedelta(seconds=5)):
        events.append(event)
    assert events
    assert events[0].leader_alias == public_wallet_alias(WALLET)
    assert WALLET not in events[0].leader_alias
    assert events[0].attribution_status is AttributionStatus.WALLET_ALIASED
    assert "user" not in events[0].provenance


@pytest.mark.asyncio
async def test_market_stream_is_not_wallet_attributable() -> None:
    async def factory():
        yield MarketDataEvent(
            source="polymarket",
            event_type="price_change",
            token_id="token-1",
            received_at=OBSERVED,
            exchange_ts=OBSERVED - timedelta(milliseconds=20),
            payload={"price": "0.42"},
            raw_payload={},
        )

    source = OfficialMarketStreamSource(
        token_ids=("token-1",),
        event_factory=factory,
        clock=lambda: OBSERVED,
        monotonic_ns=lambda: 5,
    )
    events = [
        event
        async for event in source.run(run_id="r1", deadline=OBSERVED + timedelta(seconds=1))
    ]
    assert events[0].event_kind is ObservationKind.MARKET_STATE
    assert events[0].attribution_status is AttributionStatus.NOT_APPLICABLE
    assert events[0].leader_alias is None
    assert source.candidate.wallet_attributable is False


def test_wallet_observation_identity_preserves_distinct_wallet_attribution() -> None:
    second_wallet = "0x2222222222222222222222222222222222222222"
    shared = {
        "side": "BUY",
        "price": "0.51",
        "size": "2",
        "timestamp": int(OBSERVED.timestamp()) - 3,
        "conditionId": "0x" + "a" * 64,
        "asset": "token-1",
        "transactionHash": "0x" + "b" * 64,
    }
    first = _normalize_wallet_row(
        {**shared, "proxyWallet": WALLET},
        source_id=ACTIVITY_SOURCE_ID,
        alias=public_wallet_alias(WALLET),
        expected_wallet=WALLET,
        run_id="r1",
        observed_time=OBSERVED,
        receive_ns=1,
        normalize_ns=2,
    )
    second = _normalize_wallet_row(
        {**shared, "proxyWallet": second_wallet},
        source_id=ACTIVITY_SOURCE_ID,
        alias=public_wallet_alias(second_wallet),
        expected_wallet=second_wallet,
        run_id="r1",
        observed_time=OBSERVED,
        receive_ns=1,
        normalize_ns=2,
    )
    assert first.source_event_id == second.source_event_id
    assert first.evidence_id != second.evidence_id
    assert first.leader_alias != second.leader_alias


@pytest.mark.asyncio
async def test_public_discovery_and_unavailable_user_channel() -> None:
    transport = FakeTransport(
        [
            {
                "proxyWallet": WALLET,
                "asset": "token-1",
            }
        ]
    )
    aliases, tokens = await discover_public_follow_set(transport, wallet_limit=2)
    assert public_wallet_alias(WALLET) in aliases
    assert aliases[public_wallet_alias(WALLET)] == WALLET
    assert tokens == ("token-1",)
    assert USER_CHANNEL_CANDIDATE.status is SourceCandidateStatus.UNAVAILABLE
    assert USER_CHANNEL_CANDIDATE.unavailable_reason is not None


async def _noop_sleep(delay: float) -> None:
    del delay
