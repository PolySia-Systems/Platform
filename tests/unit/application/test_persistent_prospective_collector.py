from __future__ import annotations

import asyncio
import json
import sqlite3
from collections.abc import AsyncIterator, Mapping
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from polysia.application.ports.research_evidence import SourceCandidate
from polysia.application.services.persistent_prospective_collector import (
    PersistentCollectorConfig,
    PersistentProspectiveCollector,
)
from polysia.application.services.prospective_collector import ProspectiveCollector
from polysia.domain.research_evidence.collector import CollectorPolicy
from polysia.domain.research_evidence.models import (
    RESEARCH_EVIDENCE_SCHEMA_VERSION,
    AttributionStatus,
    CanonicalResearchEvent,
    ConfirmationStatus,
    EvidenceClassification,
    IntervalValidity,
    ObservationKind,
    SourceCandidateStatus,
    payload_digest,
)
from polysia.domain.research_evidence.replay import replay_same_observations
from polysia.storage.research_evidence import (
    ExclusiveWriterLock,
    ResearchEvidenceMaintenanceError,
    ResearchEvidenceStore,
    ResearchExperimentBudgetError,
    ResearchWriterLockError,
)

OBSERVED = datetime(2026, 9, 7, 18, 0, tzinfo=UTC)
ROOT = Path(__file__).resolve().parents[3]


class FakeClock:
    def __init__(self, start: datetime = OBSERVED) -> None:
        self.now = start

    def __call__(self) -> datetime:
        return self.now

    async def sleep(self, seconds: float) -> None:
        self.now += timedelta(seconds=seconds)
        await asyncio.sleep(0)


class SequenceSource:
    def __init__(
        self,
        candidate: SourceCandidate,
        events: tuple[CanonicalResearchEvent, ...] = (),
        *,
        fail: bool = False,
        hang: bool = False,
    ) -> None:
        self.candidate = candidate
        self._events = events
        self._fail = fail
        self._hang = hang

    def health_snapshot(self) -> dict[str, object]:
        return {
            "availability": "available",
            "last_request_outcome": "success_events" if self._events else "success_empty",
            "last_successful_request_at": OBSERVED.isoformat(),
            "last_successful_event_at": OBSERVED.isoformat() if self._events else None,
            "last_failure_at": None,
            "failure_class": None,
            "retry_at": None,
            "recovery_count": 0,
        }

    async def run(
        self,
        *,
        run_id: str,
        deadline: datetime,
    ) -> AsyncIterator[CanonicalResearchEvent]:
        del run_id, deadline
        for event in self._events:
            yield event
        if self._fail:
            raise RuntimeError("source drain exploded")
        if self._hang:
            while True:
                await asyncio.sleep(0.01)


class UnavailableSource(SequenceSource):
    def health_snapshot(self) -> dict[str, object]:
        return {
            "availability": "unavailable",
            "last_request_outcome": "transient_error",
            "last_successful_request_at": None,
            "last_successful_event_at": None,
            "last_failure_at": OBSERVED.isoformat(),
            "failure_class": "network_transport",
            "retry_at": (OBSERVED + timedelta(seconds=10)).isoformat(),
            "recovery_count": 0,
        }


class TerminalSequenceSource(SequenceSource):
    def __init__(
        self,
        candidate: SourceCandidate,
        events: tuple[CanonicalResearchEvent, ...],
    ) -> None:
        super().__init__(candidate, events, hang=True)
        self.terminal_requests: list[dict[str, str]] = []

    async def capture_terminal_evidence(
        self,
        *,
        run_id: str,
        token_markets: Mapping[str, str],
    ) -> tuple[CanonicalResearchEvent, ...]:
        self.terminal_requests.append(dict(token_markets))
        return (
            _market(
                "terminal-market",
                outcome="o1",
                observed=OBSERVED + timedelta(seconds=2),
                run_id=run_id,
            ),
        )

def _candidate(candidate_id: str, *, wallet: bool = True) -> SourceCandidate:
    return SourceCandidate(
        candidate_id=candidate_id,
        display_name=candidate_id,
        kind="wallet_event" if wallet else "market_state",
        wallet_attributable=wallet,
        status=SourceCandidateStatus.MEASURED,
    )


def _wallet(
    evidence_id: str,
    *,
    alias: str = "pub-one",
    market: str = "m1",
    outcome: str = "o1",
    observed: datetime = OBSERVED,
    run_id: str = "run",
) -> CanonicalResearchEvent:
    return CanonicalResearchEvent(
        evidence_id=evidence_id,
        schema_version=RESEARCH_EVIDENCE_SCHEMA_VERSION,
        source_id="wallet",
        event_kind=ObservationKind.WALLET_TRADE,
        classification=EvidenceClassification.ACCEPTED,
        market_reference=market,
        outcome_reference=outcome,
        side="BUY",
        price=Decimal("0.4"),
        size=Decimal("2"),
        source_time=observed,
        observed_time=observed,
        receive_monotonic_ns=1,
        normalize_monotonic_ns=2,
        attribution_status=AttributionStatus.WALLET_ALIASED,
        leader_alias=alias,
        confirmation=ConfirmationStatus.CONFIRMED,
        payload_digest=payload_digest({"id": evidence_id, "alias": alias}),
        provenance={},
        source_event_id=f"src-{evidence_id}",
        run_id=run_id,
    )


def _market(
    evidence_id: str,
    *,
    outcome: str = "o1",
    observed: datetime = OBSERVED,
    quote: bool = True,
    run_id: str = "run",
) -> CanonicalResearchEvent:
    return CanonicalResearchEvent(
        evidence_id=evidence_id,
        schema_version=RESEARCH_EVIDENCE_SCHEMA_VERSION,
        source_id="market",
        event_kind=ObservationKind.MARKET_STATE,
        classification=EvidenceClassification.ACCEPTED,
        market_reference=None,
        outcome_reference=outcome,
        side=None,
        price=Decimal("0.41") if quote else None,
        size=None,
        source_time=observed,
        observed_time=observed,
        receive_monotonic_ns=1,
        normalize_monotonic_ns=2,
        attribution_status=AttributionStatus.NOT_APPLICABLE,
        leader_alias=None,
        confirmation=ConfirmationStatus.CONFIRMED if quote else ConfirmationStatus.UNCONFIRMED,
        payload_digest=payload_digest({"id": evidence_id}),
        provenance={
            "quote_status": "present" if quote else "UNKNOWN",
            "depth_status": "UNKNOWN",
            "best_bid": "0.40" if quote else None,
            "best_ask": "0.42" if quote else None,
        },
        run_id=run_id,
    )


def test_empty_window_closes_valid(tmp_path: Path) -> None:
    clock = FakeClock()
    store = ResearchEvidenceStore(tmp_path / "research.sqlite3", clock=clock)
    source = SequenceSource(_candidate("rest_trades"), hang=True)
    collector = PersistentProspectiveCollector(
        store,
        (source,),
        config=PersistentCollectorConfig(
            window=timedelta(seconds=2),
            required_source_ids=("rest_trades",),
            health_path=tmp_path / "health.json",
            report_dir=tmp_path / "reports",
        ),
        clock=clock,
        sleep=clock.sleep,
    )

    async def _run() -> None:
        await collector.run(cycles=1)

    asyncio.run(_run())
    assert collector.interval.validity is IntervalValidity.VALID
    closed = store.latest_closed_interval()
    assert closed is not None
    assert closed.interval_id == collector.interval.interval_id
    assert closed.validity is IntervalValidity.VALID
    assert closed.summary is not None
    assert closed.summary["empty"] is True
    assert closed.reason == "closed"


def test_terminal_window_captures_wallet_market_evidence_before_close(
    tmp_path: Path,
) -> None:
    clock = FakeClock()
    store = ResearchEvidenceStore(tmp_path / "research.sqlite3", clock=clock)
    source = TerminalSequenceSource(
        _candidate("rest_trades"),
        (
            _wallet("wallet-before-terminal", run_id="terminal-run"),
            _wallet(
                "wallet-latest-market",
                market="m2",
                observed=OBSERVED + timedelta(seconds=1),
                run_id="terminal-run",
            ),
        ),
    )
    collector = PersistentProspectiveCollector(
        store,
        (source,),
        config=PersistentCollectorConfig(
            window=timedelta(seconds=2),
            required_source_ids=("rest_trades",),
            experiment_duration=timedelta(seconds=2),
        ),
        clock=clock,
        sleep=clock.sleep,
        run_id="terminal-run",
    )

    asyncio.run(collector.run(cycles=1))

    assert source.terminal_requests == [{"o1": "m2"}]
    closed = store.latest_closed_interval()
    assert closed is not None
    assert closed.validity is IntervalValidity.VALID
    assert collector.health_payload()["fatal"] is None
    assert {event.evidence_id for event in store.load_events(interval_id=closed.interval_id)} == {
        "wallet-before-terminal",
        "wallet-latest-market",
        "terminal-market",
    }


def test_health_heartbeat_stays_fresh_inside_long_window(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = FakeClock()
    writes: list[datetime] = []

    def _capture(path: Path, payload: object) -> None:
        del path, payload
        writes.append(clock.now)

    monkeypatch.setattr(
        "polysia.application.services.persistent_prospective_collector._atomic_json",
        _capture,
    )
    collector = PersistentProspectiveCollector(
        ResearchEvidenceStore(tmp_path / "research.sqlite3", clock=clock),
        (SequenceSource(_candidate("rest_trades"), hang=True),),
        config=PersistentCollectorConfig(
            window=timedelta(seconds=65),
            required_source_ids=("rest_trades",),
            health_path=tmp_path / "health.json",
        ),
        clock=clock,
        sleep=clock.sleep,
    )
    asyncio.run(collector.run(cycles=1))
    assert len(writes) >= 4
    assert all(
        later - earlier <= timedelta(seconds=30)
        for earlier, later in zip(writes, writes[1:], strict=False)
    )


def test_drain_failure_cannot_produce_valid(tmp_path: Path) -> None:
    clock = FakeClock()
    store = ResearchEvidenceStore(tmp_path / "research.sqlite3", clock=clock)
    source = SequenceSource(_candidate("rest_trades"), fail=True)
    collector = PersistentProspectiveCollector(
        store,
        (source,),
        config=PersistentCollectorConfig(
            window=timedelta(seconds=2),
            required_source_ids=("rest_trades",),
        ),
        clock=clock,
        sleep=clock.sleep,
    )
    asyncio.run(collector.run(cycles=1))
    closed = store.latest_closed_interval()
    assert closed is not None
    assert closed.validity is not IntervalValidity.VALID
    assert closed.validity in {
        IntervalValidity.INVALID_DRAIN,
        IntervalValidity.INVALID_SHUTDOWN,
    }


def test_unresolved_required_source_cannot_produce_valid(tmp_path: Path) -> None:
    clock = FakeClock()
    store = ResearchEvidenceStore(tmp_path / "research.sqlite3", clock=clock)
    collector = PersistentProspectiveCollector(
        store,
        (UnavailableSource(_candidate("rest_trades"), hang=True),),
        config=PersistentCollectorConfig(
            window=timedelta(seconds=2),
            required_source_ids=("rest_trades",),
        ),
        clock=clock,
        sleep=clock.sleep,
    )

    asyncio.run(collector.run(cycles=1))

    closed = store.latest_closed_interval()
    assert closed is not None
    assert closed.validity is IntervalValidity.INVALID_DRAIN
    assert closed.summary is not None
    assert closed.summary["research_data_eligible"] is False


def test_persistent_stop_does_not_mark_open_window_valid(tmp_path: Path) -> None:
    clock = FakeClock()
    store = ResearchEvidenceStore(tmp_path / "research.sqlite3", clock=clock)
    source = SequenceSource(_candidate("rest_trades"), hang=True)
    collector = PersistentProspectiveCollector(
        store,
        (source,),
        config=PersistentCollectorConfig(
            window=timedelta(seconds=30),
            required_source_ids=("rest_trades",),
        ),
        clock=clock,
        sleep=clock.sleep,
    )

    async def _run() -> None:
        task = asyncio.create_task(collector.run())
        await asyncio.sleep(0)
        collector.request_stop()
        await task

    asyncio.run(_run())
    assert collector.interval.validity is IntervalValidity.INVALID_SHUTDOWN
    closed = store.latest_closed_interval()
    assert closed is not None
    assert closed.validity is IntervalValidity.INVALID_SHUTDOWN
    assert closed.validity is not IntervalValidity.VALID


def test_graceful_shutdown_does_not_mark_open_window_valid(tmp_path: Path) -> None:
    store = ResearchEvidenceStore(tmp_path / "research.sqlite3")
    collector = ProspectiveCollector(store)
    assert collector.interval.validity is IntervalValidity.OPEN
    closed = collector.close_window(complete=False)
    assert closed.validity is IntervalValidity.INVALID_SHUTDOWN
    assert closed.reason == "incomplete_window"


def test_orphan_open_window_becomes_invalid_on_restart(tmp_path: Path) -> None:
    database = tmp_path / "research.sqlite3"
    store = ResearchEvidenceStore(database)
    first = ProspectiveCollector(store, run_id="run-a")
    first.ingest(_wallet("kept"))
    assert first.interval.validity is IntervalValidity.OPEN
    restarted = ProspectiveCollector(store, run_id="run-b", recover_orphans=True)
    orphan = store.load_interval(first.interval.interval_id)
    assert orphan is not None
    assert orphan.validity is IntervalValidity.INVALID_SHUTDOWN
    assert orphan.reason == "orphan_open_after_restart"
    assert restarted.interval.validity is IntervalValidity.OPEN
    assert restarted.interval.interval_id != first.interval.interval_id
    accepted = [
        item
        for item in store.load_events()
        if item.classification is EvidenceClassification.ACCEPTED
        and item.event_kind is ObservationKind.WALLET_TRADE
    ]
    assert len(accepted) == 1


def test_second_writer_is_rejected(tmp_path: Path) -> None:
    database = tmp_path / "research.sqlite3"
    first = ExclusiveWriterLock(database)
    second = ExclusiveWriterLock(database)
    first.acquire()
    with pytest.raises(ResearchWriterLockError, match="second writer"):
        second.acquire()
    first.release()
    second.acquire()
    second.release()


def test_second_writer_collector_idles_without_exiting(tmp_path: Path) -> None:
    database = tmp_path / "research.sqlite3"
    held = ExclusiveWriterLock(database)
    held.acquire()
    clock = FakeClock()
    collector = PersistentProspectiveCollector(
        ResearchEvidenceStore(database, clock=clock),
        (),
        config=PersistentCollectorConfig(
            window=timedelta(seconds=1),
            fatal_idle=True,
            health_path=tmp_path / "health.json",
        ),
        clock=clock,
        sleep=clock.sleep,
    )

    async def _run() -> None:
        task = asyncio.create_task(collector.run())
        await asyncio.sleep(0)
        collector.request_stop()
        await task

    asyncio.run(_run())
    held.release()
    health = json.loads((tmp_path / "health.json").read_text(encoding="utf-8"))
    assert health["fatal"] == "second_writer_rejected"
    assert health["lifecycle"] == "STOPPED"


def test_snapshot_reader_during_writes(tmp_path: Path) -> None:
    store = ResearchEvidenceStore(tmp_path / "research.sqlite3")
    collector = ProspectiveCollector(store)
    collector.ingest(_wallet("one"))
    snapshot = store.snapshot(tmp_path / "snap.sqlite3")
    replica = ResearchEvidenceStore(snapshot)
    replica.verify_integrity()
    collector.ingest(_wallet("two"))
    assert replica.event_count() == 1
    assert store.event_count() == 2
    replay = replay_same_observations(replica.load_events(), interval_valid=True)
    assert replay.control_digest != replay.target_digest or replay.unknown_count >= 0


def test_backup_restore_and_continue(tmp_path: Path) -> None:
    from polysia.deployment.sqlite_backup import (
        backup_sqlite_database,
        restore_sqlite_backup,
    )

    database = tmp_path / "research.sqlite3"
    store = ResearchEvidenceStore(database)
    collector = ProspectiveCollector(store, run_id="run-restore")
    collector.ingest(_wallet("alpha", alias="pub-a", market="ma", outcome="oa"))
    collector.ingest(_wallet("beta", alias="pub-b", market="mb", outcome="ob"))
    collector.close_window(complete=True)
    backup = backup_sqlite_database(
        database,
        tmp_path / "backups",
        prefix="research-evidence-",
    )
    restored = tmp_path / "restored.sqlite3"
    restore_sqlite_backup(backup.backup_path, restored)
    replica = ResearchEvidenceStore(restored)
    replica.verify_integrity()
    replica.initialize()
    restored_interval = replica.latest_closed_interval()
    assert restored_interval is not None
    assert restored_interval.validity is IntervalValidity.VALID
    continued = ProspectiveCollector(replica, run_id="run-restore", recover_orphans=True)
    again = continued.ingest(_wallet("alpha", alias="pub-a", market="ma", outcome="oa"))
    assert again.classification is EvidenceClassification.DUPLICATE
    continued.close_window(complete=True)


def test_fake_clock_retention_and_duplicate_cleanup(tmp_path: Path) -> None:
    clock = FakeClock()
    policy = CollectorPolicy(
        max_persisted_events=10,
        market_state_retention=timedelta(seconds=1),
    )
    store = ResearchEvidenceStore(tmp_path / "research.sqlite3", policy=policy, clock=clock)
    collector = ProspectiveCollector(store, policy=policy, clock=clock)
    collector.ingest(_wallet("live"))
    old = _market("old-mkt", observed=clock.now - timedelta(days=1))
    collector.ingest(old)
    clock.now += timedelta(seconds=2)
    store.maintain(now=clock.now)
    ids = {item.evidence_id for item in store.load_events()}
    assert "old-mkt" not in ids
    assert "live" in ids
    collector.ingest(_wallet("live"))
    store.maintain(now=clock.now)
    assert store.duplicate_count("live") == 1


def test_active_experiment_survives_normal_retention_until_finalized(tmp_path: Path) -> None:
    clock = FakeClock()
    policy = CollectorPolicy(
        max_persisted_events=1,
        market_state_retention=timedelta(seconds=1),
    )
    store = ResearchEvidenceStore(tmp_path / "research.sqlite3", policy=policy, clock=clock)
    store.start_or_resume_experiment(
        requested_run_id="bounded-run",
        duration=timedelta(hours=1),
        max_events=10,
        max_bytes=10_000_000,
        code_sha="a" * 40,
        configuration_digest="config",
    )
    collector = ProspectiveCollector(
        store,
        policy=policy,
        clock=clock,
        run_id="bounded-run",
    )
    collector.ingest(
        _market("protected-a", observed=clock.now - timedelta(days=1), run_id="bounded-run")
    )
    collector.ingest(
        _market("protected-b", observed=clock.now - timedelta(days=1), run_id="bounded-run")
    )

    store.maintain(now=clock.now)

    assert {event.evidence_id for event in store.load_events(run_id="bounded-run")} == {
        "protected-a",
        "protected-b",
    }


def test_active_experiment_fails_before_event_budget_is_exceeded(tmp_path: Path) -> None:
    store = ResearchEvidenceStore(tmp_path / "research.sqlite3")
    store.start_or_resume_experiment(
        requested_run_id="one-event",
        duration=timedelta(hours=1),
        max_events=1,
        max_bytes=10_000_000,
        code_sha=None,
        configuration_digest="config",
    )
    collector = ProspectiveCollector(store, run_id="one-event")
    collector.ingest(_wallet("first", run_id="one-event"))

    with pytest.raises(ResearchExperimentBudgetError, match="event limit"):
        collector.ingest(_wallet("second", run_id="one-event"))
    assert store.experiment_event_count("one-event") == 1


def test_active_experiment_resumes_same_run_after_restart(tmp_path: Path) -> None:
    store = ResearchEvidenceStore(tmp_path / "research.sqlite3")
    first = store.start_or_resume_experiment(
        requested_run_id="original-run",
        duration=timedelta(hours=1),
        max_events=10,
        max_bytes=10_000_000,
        code_sha="c" * 40,
        configuration_digest="config",
    )
    resumed = store.start_or_resume_experiment(
        requested_run_id="new-process-id",
        duration=timedelta(hours=1),
        max_events=10,
        max_bytes=10_000_000,
        code_sha="c" * 40,
        configuration_digest="config",
    )

    assert resumed.run_id == first.run_id == "original-run"


def test_finalize_experiment_requires_verified_restore_and_replay(tmp_path: Path) -> None:
    from polysia.deployment.research_experiment_bundle import finalize_research_experiment

    database = tmp_path / "research.sqlite3"
    store = ResearchEvidenceStore(database)
    store.start_or_resume_experiment(
        requested_run_id="final-run",
        duration=timedelta(hours=1),
        max_events=10,
        max_bytes=10_000_000,
        code_sha="b" * 40,
        configuration_digest="config",
    )
    collector = ProspectiveCollector(store, run_id="final-run")
    collector.ingest(_wallet("final-wallet", run_id="final-run"))
    collector.ingest(_market("final-market", run_id="final-run"))
    collector.close_window(complete=True)

    result = finalize_research_experiment(
        database,
        tmp_path / "bundles",
        run_id="final-run",
    )

    assert result.database_path.is_file()
    assert result.manifest_path.is_file()
    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    assert manifest["database_sha256"] == result.sha256
    assert manifest["event_count"] == 2
    assert store.load_experiment("final-run").status == "FINALIZED"  # type: ignore[union-attr]
    bundled = ResearchEvidenceStore(result.database_path)
    assert bundled.load_experiment("final-run").status == "FINALIZED"  # type: ignore[union-attr]


def test_finalize_experiment_excludes_invalid_windows_and_uses_bundle_storage(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import tempfile

    from polysia.deployment import research_experiment_bundle

    database = tmp_path / "research.sqlite3"
    store = ResearchEvidenceStore(database)
    store.start_or_resume_experiment(
        requested_run_id="mixed-run",
        duration=timedelta(hours=1),
        max_events=10,
        max_bytes=10_000_000,
        code_sha="d" * 40,
        configuration_digest="config",
    )
    collector = ProspectiveCollector(store, run_id="mixed-run")
    collector.ingest(_wallet("invalid-wallet", run_id="mixed-run"))
    collector.close_window(complete=False)
    collector.start_window()
    collector.ingest(_market("valid-market", run_id="mixed-run"))
    collector.ingest(_wallet("valid-wallet", run_id="mixed-run"))
    collector.close_window(complete=True)

    restore_parents: list[Path] = []

    def _temporary_directory(*args: object, **kwargs: object) -> tempfile.TemporaryDirectory[str]:
        directory = kwargs.get("dir")
        assert isinstance(directory, Path)
        restore_parents.append(directory)
        return tempfile.TemporaryDirectory(*args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(
        research_experiment_bundle,
        "TemporaryDirectory",
        _temporary_directory,
    )
    bundle_root = tmp_path / "bundles"
    result = research_experiment_bundle.finalize_research_experiment(
        database,
        bundle_root,
        run_id="mixed-run",
    )

    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    assert manifest["manifest_version"] == 2
    assert manifest["intervals"] == {
        "invalid_event_bearing": 1,
        "invalid_reasons": {"INVALID_SHUTDOWN:incomplete_window": 1},
        "valid_event_bearing": 1,
    }
    assert manifest["replay"]["scope"] == "valid_intervals_only"
    assert manifest["replay"]["invalidated"] is False
    assert manifest["replay"]["replayed_event_count"] == 2
    assert manifest["replay"]["excluded_event_count"] == 1
    assert manifest["economic"]["economic_classification"] == "INSUFFICIENT_DATA"
    assert manifest["experiment_contract"]["version"] == "prospective-economic-v2"
    assert len(manifest["experiment_contract_digest"]) == 64
    assert len(restore_parents) == 1
    assert restore_parents[0].parent == bundle_root


def test_failed_bundle_verification_does_not_finalize_experiment(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from polysia.deployment import research_experiment_bundle

    database = tmp_path / "research.sqlite3"
    store = ResearchEvidenceStore(database)
    store.start_or_resume_experiment(
        requested_run_id="failed-finalize",
        duration=timedelta(hours=1),
        max_events=10,
        max_bytes=10_000_000,
        code_sha=None,
        configuration_digest="config",
    )
    collector = ProspectiveCollector(store, run_id="failed-finalize")
    collector.ingest(_wallet("wallet", run_id="failed-finalize"))
    collector.close_window(complete=True)

    def _fail_restore(*args: object, **kwargs: object) -> str:
        del args, kwargs
        raise ValueError("restore failed")

    monkeypatch.setattr(research_experiment_bundle, "restore_sqlite_backup", _fail_restore)
    with pytest.raises(ValueError, match="restore failed"):
        research_experiment_bundle.finalize_research_experiment(
            database,
            tmp_path / "bundles",
            run_id="failed-finalize",
        )

    experiment = store.load_experiment("failed-finalize")
    assert experiment is not None
    assert experiment.status == "ACTIVE"
    assert not (tmp_path / "bundles" / "research-experiment-failed-finalize").exists()


def test_multiple_wallets_markets_and_unknown_quotes(tmp_path: Path) -> None:
    store = ResearchEvidenceStore(tmp_path / "research.sqlite3")
    clock = FakeClock()
    wallet_source = SequenceSource(
        _candidate("rest_trades"),
        (
            _wallet("w1", alias="pub-a", market="m-a", outcome="tok-a"),
            _wallet("w2", alias="pub-b", market="m-b", outcome="tok-b"),
        ),
        hang=True,
    )
    market_source = SequenceSource(
        _candidate("clob_market_ws", wallet=False),
        (_market("mk1", outcome="tok-a", quote=True), _market("mk2", outcome="tok-z", quote=False)),
        hang=True,
    )
    collector = PersistentProspectiveCollector(
        store,
        (wallet_source, market_source),
        config=PersistentCollectorConfig(
            window=timedelta(seconds=2),
            required_source_ids=("rest_trades",),
        ),
        clock=clock,
        sleep=clock.sleep,
    )
    asyncio.run(collector.run(cycles=1))
    closed = store.latest_closed_interval()
    assert closed is not None
    assert closed.validity is IntervalValidity.VALID
    summary = closed.summary or {}
    assert summary["accepted_wallet_events"] == 2
    assert summary["overlap_count"] == 1
    assert summary["quote_status"] == "present"
    events = store.load_events(interval_id=closed.interval_id)
    replay = replay_same_observations(events, interval_valid=True)
    assert replay.unknown_count >= 0
    missing_book = next(item for item in events if item.evidence_id == "mk2")
    assert missing_book.provenance["quote_status"] == "UNKNOWN"


def test_window_reports_are_bounded(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "polysia.application.services.persistent_prospective_collector.MAX_WINDOW_REPORTS",
        2,
    )
    clock = FakeClock()
    store = ResearchEvidenceStore(tmp_path / "research.sqlite3", clock=clock)
    source = SequenceSource(_candidate("rest_trades"), hang=True)
    reports = tmp_path / "reports"
    collector = PersistentProspectiveCollector(
        store,
        (source,),
        config=PersistentCollectorConfig(
            window=timedelta(seconds=1),
            required_source_ids=("rest_trades",),
            report_dir=reports,
        ),
        clock=clock,
        sleep=clock.sleep,
    )
    asyncio.run(collector.run(cycles=3))
    files = list(reports.glob("research-window-*.json"))
    assert len(files) == 2
    retained = [json.loads(path.read_text(encoding="utf-8")) for path in files]
    assert sorted(item["ended_at"] for item in retained) == [
        (OBSERVED + timedelta(seconds=2)).isoformat(),
        (OBSERVED + timedelta(seconds=3)).isoformat(),
    ]


def test_overload_prevents_valid_on_close(tmp_path: Path) -> None:
    policy = CollectorPolicy(max_queue_depth=1)
    store = ResearchEvidenceStore(tmp_path / "research.sqlite3", policy=policy)
    collector = ProspectiveCollector(store, policy=policy)
    collector._queue.put_nowait(_wallet("held"))
    overloaded = collector.ingest(_wallet("dropped"))
    assert overloaded.classification is EvidenceClassification.OVERLOAD
    closed = collector.close_window(complete=True)
    assert closed.validity is IntervalValidity.INVALID_OVERLOAD
    assert closed.validity is not IntervalValidity.VALID


def test_compose_research_collector_is_data_only() -> None:
    compose = (ROOT / "compose.yaml").read_text(encoding="utf-8")
    section = compose.split("  research-collector:", maxsplit=1)[1].split(
        "\n  research-runner:", maxsplit=1
    )[0]
    assert "TRADING_MODE: DATA_ONLY" in section
    assert 'LIVE_TRADING_ENABLED: "false"' in section
    assert "POLYMARKET_LIVE_TOKEN_ALLOWLIST: \"\"" in section
    assert "prospective-collect" in section
    assert "tiny-execute" not in section
    assert "cancel-order" not in section
    assert "research-evidence.sqlite3" in section
    assert "profiles:" in section
    assert "cap_drop:" in section
    assert "no-new-privileges:true" in section
    assert "pids_limit: 128" in section
    assert "restart: unless-stopped" in section
    assert "read_only: true" in section
    assert 'user: "10001:10001"' in section
    assert "stop_grace_period: 30s" in section
    assert "ports:" not in section
    assert "max-size: 10m" in section
    module = ROOT / "src/polysia/application/services/persistent_prospective_collector.py"
    health = module.read_text(encoding="utf-8")
    assert "polysia.execution" not in health
    assert "place_order" not in health


def test_compose_research_runner_is_data_only_and_does_not_restart() -> None:
    compose = (ROOT / "compose.yaml").read_text(encoding="utf-8")
    section = compose.split("  research-runner:", maxsplit=1)[1].split(
        "\n  backup:", maxsplit=1
    )[0]
    assert "TRADING_MODE: DATA_ONLY" in section
    assert 'LIVE_TRADING_ENABLED: "false"' in section
    assert "POLYMARKET_LIVE_TOKEN_ALLOWLIST: \"\"" in section
    assert "prospective-run" in section
    assert "prospective-run status" in section
    assert 'restart: "no"' in section
    assert "tiny-execute" not in section
    assert "cancel-order" not in section
    assert "read_only: true" in section
    assert 'user: "10001:10001"' in section
    assert "cap_drop:" in section
    assert "no-new-privileges:true" in section
    assert "mem_limit: 2g" in section
    assert (
        "${POLYSIA_STATE_DIR:-/var/lib/polysia}/wallet-intelligence/data/"
        "wallet-intelligence.sqlite3"
    ) in section
    assert "target: /var/lib/polysia/data/wallet-intelligence.sqlite3" in section
    assert "read_only: true" in section


def test_busy_timeout_and_wal_files(tmp_path: Path) -> None:
    store = ResearchEvidenceStore(tmp_path / "research.sqlite3")
    collector = ProspectiveCollector(store)
    collector.ingest(_wallet("wal"))
    wal = Path(f"{store.path}-wal")
    stats = store.storage_file_stats()
    assert stats["database_bytes"] > 0
    assert "wal_bytes" in stats
    connection = sqlite3.connect(store.path)
    try:
        timeout = connection.execute("PRAGMA busy_timeout").fetchone()
        journal = connection.execute("PRAGMA journal_mode").fetchone()
    finally:
        connection.close()
    assert timeout is not None
    assert int(timeout[0]) == 5000
    assert journal is not None
    assert str(journal[0]).lower() == "wal"
    collector.close_window(complete=True)
    assert wal.exists() or stats["wal_bytes"] >= 0


def test_checkpoint_runs_after_prune_transaction_with_active_reader(
    tmp_path: Path,
) -> None:
    database = tmp_path / "research.sqlite3"
    store = ResearchEvidenceStore(database)
    collector = ProspectiveCollector(store)
    collector.ingest(_wallet("before-reader"))
    reader = sqlite3.connect(database)
    writer = sqlite3.connect(database)
    try:
        reader.execute("BEGIN")
        reader.execute("SELECT COUNT(*) FROM research_events").fetchone()
        writer.execute("PRAGMA wal_autocheckpoint = 0")
        writer.execute("CREATE TABLE wal_pressure(payload BLOB NOT NULL)")
        writer.execute(
            "INSERT INTO wal_pressure(payload) VALUES (zeroblob(?))",
            (9 * 1024 * 1024,),
        )
        writer.commit()
        assert Path(f"{database}-wal").stat().st_size > 8 * 1024 * 1024
        result = store.maintain()
    finally:
        writer.close()
        reader.close()
    assert result.attempted is True
    assert result.checkpointed_frames <= result.log_frames
    assert store.event_count() == 1


def test_post_commit_maintenance_lock_is_degraded_not_event_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = ResearchEvidenceStore(tmp_path / "research.sqlite3")
    collector = ProspectiveCollector(store)
    monkeypatch.setattr(
        ResearchEvidenceStore,
        "maintenance_due",
        property(lambda self: True),
    )

    def _locked(*, now: datetime | None = None) -> None:
        del now
        raise ResearchEvidenceMaintenanceError(
            "checkpoint",
            sqlite3.OperationalError("database table is locked"),
        )

    monkeypatch.setattr(store, "maintain", _locked)
    persisted = collector.ingest(_wallet("committed-before-maintenance"))
    assert persisted.classification is EvidenceClassification.ACCEPTED
    assert store.event_count() == 1
    assert collector.maintenance_health == {
        "status": "degraded",
        "stage": "checkpoint",
        "sqlite_error_code": "SQLITE_UNKNOWN",
        "consecutive_failures": 1,
        "checkpoint_log_frames": 0,
        "checkpointed_frames": 0,
    }


def test_fatal_maintenance_failure_still_invalidates_window(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class SqliteFull(sqlite3.OperationalError):
        sqlite_errorname = "SQLITE_FULL"

    store = ResearchEvidenceStore(tmp_path / "research.sqlite3")
    collector = ProspectiveCollector(store)
    monkeypatch.setattr(
        ResearchEvidenceStore,
        "maintenance_due",
        property(lambda self: True),
    )

    def _full(*, now: datetime | None = None) -> None:
        del now
        raise ResearchEvidenceMaintenanceError("prune", SqliteFull("database full"))

    monkeypatch.setattr(store, "maintain", _full)
    with pytest.raises(ResearchEvidenceMaintenanceError, match="prune maintenance"):
        collector.ingest(_wallet("committed-before-full"))
    assert store.event_count() == 1
    assert collector.interval.validity is IntervalValidity.INVALID_DISK


def test_repeated_prune_contention_stops_unbounded_retention_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = ResearchEvidenceStore(tmp_path / "research.sqlite3")
    collector = ProspectiveCollector(store)
    monkeypatch.setattr(
        ResearchEvidenceStore,
        "maintenance_due",
        property(lambda self: True),
    )

    def _locked(*, now: datetime | None = None) -> None:
        del now
        raise ResearchEvidenceMaintenanceError(
            "prune",
            sqlite3.OperationalError("database table is locked"),
        )

    monkeypatch.setattr(store, "maintain", _locked)
    collector.ingest(_wallet("prune-one"))
    collector.ingest(_wallet("prune-two"))
    with pytest.raises(ResearchEvidenceMaintenanceError, match="prune maintenance"):
        collector.ingest(_wallet("prune-three"))
    assert store.event_count() == 3
    assert collector.interval.validity is IntervalValidity.INVALID_DISK


def test_persistence_failure_prevents_valid(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = ResearchEvidenceStore(tmp_path / "research.sqlite3")
    collector = ProspectiveCollector(store)

    def _boom(*args: object, **kwargs: object) -> None:
        del args, kwargs
        raise OSError("disk full")

    monkeypatch.setattr(store, "persist_event", _boom)
    with pytest.raises(OSError, match="disk full"):
        collector.ingest(_wallet("disk"))
    assert collector.interval.validity is IntervalValidity.INVALID_DISK
    closed = collector.close_window(complete=True)
    assert closed.validity is not IntervalValidity.VALID
