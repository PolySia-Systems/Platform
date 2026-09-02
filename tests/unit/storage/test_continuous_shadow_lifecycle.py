from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

from polysia.application.ports.continuous_shadow import (
    ContinuousPollCompletion,
    ContinuousPositionMark,
    ContinuousSelectionSnapshot,
)
from polysia.application.ports.dynamic_shadow import ProtectedShadowCandidate
from polysia.application.services.continuous_shadow import CONTINUOUS_SHADOW_LEASE_RESOURCE
from polysia.deployment.recovery_bundle import (
    RecoveryBundleManifest,
    RecoveryDatabaseRecord,
    load_bundle_manifest,
    prune_rotating_bundles,
    rotating_bundle_dir,
    write_bundle_manifest,
)
from polysia.deployment.sqlite_backup import compact_sqlite_database
from polysia.domain.copytrading.continuous_shadow import (
    ContinuousPortfolio,
    ContinuousPortfolioKind,
    ContinuousPosition,
    ContinuousShadowConfig,
)
from polysia.storage.continuous_shadow import (
    CONTINUOUS_SHADOW_SCHEMA_VERSION,
    ContinuousShadowLeaseRepository,
    ContinuousShadowRepository,
)
from polysia.storage.lifecycle_policy import DEFAULT_STAGE4B_DATA_LIFECYCLE_POLICY

NOW = datetime(2026, 9, 2, 12, tzinfo=UTC)


def _portfolio(
    mark_price: Decimal,
    quantity: Decimal = Decimal("5"),
    *,
    status: str = "VERIFIED_EXECUTABLE_BID",
    freshness: str = "FRESH",
    marked_at: datetime = NOW,
) -> ContinuousPortfolio:
    position = ContinuousPosition(
        portfolio_id="follower",
        market_reference="market-1",
        outcome_reference="token-1",
        quantity=quantity,
        cost_basis=Decimal("2"),
        entry_fees=Decimal("0"),
        mark_price=mark_price,
        marked_at=marked_at,
        mark_status=status,
        freshness=freshness,
        source_at=marked_at,
        source_age_ms=10,
        observed_at=marked_at,
        state_changed_at=marked_at,
        last_observed_poll_run_id=None,
    )
    return ContinuousPortfolio(
        portfolio_id="follower",
        kind=ContinuousPortfolioKind.FOLLOWER,
        wallet_id=None,
        initial_cash=Decimal("1000"),
        cash=Decimal("1000"),
        realized_pnl=Decimal("0"),
        fees=Decimal("0"),
        high_water_nav=Decimal("1000"),
        drawdown=Decimal("0"),
        positions=(position,),
    )


def _mark(
    *,
    price: Decimal,
    status: str = "VERIFIED_EXECUTABLE_BID",
    quantity: Decimal = Decimal("5"),
    freshness: str = "FRESH",
    marked_at: datetime = NOW,
) -> ContinuousPositionMark:
    return ContinuousPositionMark(
        portfolio_id="follower",
        market_reference="market-1",
        outcome_reference="token-1",
        quantity=quantity,
        mark_price=price,
        market_value=quantity * price,
        unrealized_pnl=quantity * price - Decimal("2"),
        mark_status=status,
        marked_at=marked_at,
        source_timestamp=marked_at,
        source_age_ms=10,
        freshness=freshness,
        observed_at=marked_at,
        source_at=marked_at,
        state_changed_at=marked_at,
    )


def _completion(
    marks: tuple[ContinuousPositionMark, ...],
    portfolio: ContinuousPortfolio,
) -> ContinuousPollCompletion:
    return ContinuousPollCompletion(
        events=(),
        evaluations=(),
        portfolios=(portfolio,),
        attributions=(),
        ledger=(),
        marks=marks,
        raw_event_count=0,
        duplicate_count=0,
        settlement_count=0,
        settlement_backlog_count=0,
        request_telemetry={},
    )


def _start(repository: ContinuousShadowRepository, started_at: datetime):
    selection = ContinuousSelectionSnapshot.create(
        source_id="polycop",
        selection_run_id="selection-1",
        source_snapshot_id="snap-1",
        feature_set_version="f1",
        policy_id="p1",
        policy_version="v1",
        ranking_version="r1",
        published_at=started_at,
        candidates=(
            ProtectedShadowCandidate(
                wallet_id="w1",
                address="0x" + "1" * 40,
                pools=("SHADOW_ALPHA",),
                alpha_rank=1,
                stress_rank=None,
            ),
        ),
    )
    experiment = repository.start_experiment(
        selection=selection,
        config=ContinuousShadowConfig(),
        started_at=started_at,
    )
    return experiment.experiment_id, selection


def test_unchanged_observation_updates_current_state_without_history(
    tmp_path: Path,
) -> None:
    database = tmp_path / "continuous-shadow.sqlite3"
    repository = ContinuousShadowRepository(database)
    repository.initialize()
    experiment_id, selection = _start(repository, NOW)
    first_poll = repository.start_poll(
        lease=_lease(database, NOW),
        experiment_id=experiment_id,
        selection=selection,
        selection_fresh=True,
        window_start=NOW,
        window_end=NOW + timedelta(minutes=1),
        started_at=NOW,
    )
    price = Decimal("0.40")
    repository.complete_poll(
        first_poll,
        experiment=repository.active_experiment("polycop"),
        selection=selection,
        completion=_completion((_mark(price=price),), _portfolio(price)),
        completed_at=NOW + timedelta(seconds=1),
    )
    second_at = NOW + timedelta(minutes=1)
    second_poll = repository.start_poll(
        lease=_lease(database, second_at),
        experiment_id=experiment_id,
        selection=selection,
        selection_fresh=True,
        window_start=second_at,
        window_end=second_at + timedelta(minutes=1),
        started_at=second_at,
    )
    stale = _mark(
        price=price,
        status="LAST_KNOWN_GOOD",
        freshness="STALE_LAST_KNOWN_GOOD",
        marked_at=second_at,
    )
    # freshness-only LKG after a verified price is a status change: one history row.
    # A second identical LKG must not append.
    repository.complete_poll(
        second_poll,
        experiment=repository.active_experiment("polycop"),
        selection=selection,
        completion=_completion(
            (stale,),
            _portfolio(
                price,
                status="LAST_KNOWN_GOOD",
                freshness="STALE_LAST_KNOWN_GOOD",
                marked_at=second_at,
            ),
        ),
        completed_at=second_at + timedelta(seconds=1),
    )
    third_at = NOW + timedelta(minutes=2)
    third_poll = repository.start_poll(
        lease=_lease(database, third_at),
        experiment_id=experiment_id,
        selection=selection,
        selection_fresh=True,
        window_start=third_at,
        window_end=third_at + timedelta(minutes=1),
        started_at=third_at,
    )
    repeated = _mark(
        price=price,
        status="LAST_KNOWN_GOOD",
        freshness="STALE_LAST_KNOWN_GOOD",
        marked_at=third_at,
    )
    repository.complete_poll(
        third_poll,
        experiment=repository.active_experiment("polycop"),
        selection=selection,
        completion=_completion(
            (repeated,),
            _portfolio(
                price,
                status="LAST_KNOWN_GOOD",
                freshness="STALE_LAST_KNOWN_GOOD",
                marked_at=third_at,
            ),
        ),
        completed_at=third_at + timedelta(seconds=1),
    )
    with sqlite3.connect(database) as connection:
        history = connection.execute(
            "SELECT COUNT(*) FROM continuous_shadow_position_marks"
        ).fetchone()[0]
        observed = connection.execute(
            "SELECT observed_at, last_observed_poll_run_id, mark_status, freshness "
            "FROM continuous_shadow_positions"
        ).fetchone()
    health = repository.health(
        "polycop", now=third_at + timedelta(seconds=2), poll_interval_seconds=60
    )
    assert history == 2
    assert observed[1] == third_poll
    assert observed[2] == "LAST_KNOWN_GOOD"
    assert health.stale_last_known_good_mark_count >= 1


def test_unchanged_verified_price_does_not_append_history(tmp_path: Path) -> None:
    database = tmp_path / "continuous-shadow.sqlite3"
    repository = ContinuousShadowRepository(database)
    repository.initialize()
    experiment_id, selection = _start(repository, NOW)
    first_poll = repository.start_poll(
        lease=_lease(database, NOW),
        experiment_id=experiment_id,
        selection=selection,
        selection_fresh=True,
        window_start=NOW,
        window_end=NOW + timedelta(minutes=1),
        started_at=NOW,
    )
    price = Decimal("0.40")
    repository.complete_poll(
        first_poll,
        experiment=repository.active_experiment("polycop"),
        selection=selection,
        completion=_completion((_mark(price=price),), _portfolio(price)),
        completed_at=NOW + timedelta(seconds=1),
    )
    later = NOW + timedelta(minutes=1)
    second_poll = repository.start_poll(
        lease=_lease(database, later),
        experiment_id=experiment_id,
        selection=selection,
        selection_fresh=True,
        window_start=later,
        window_end=later + timedelta(minutes=1),
        started_at=later,
    )
    repository.complete_poll(
        second_poll,
        experiment=repository.active_experiment("polycop"),
        selection=selection,
        completion=_completion(
            (_mark(price=price, marked_at=later),),
            _portfolio(price, marked_at=later),
        ),
        completed_at=later + timedelta(seconds=1),
    )
    with sqlite3.connect(database) as connection:
        history = connection.execute(
            "SELECT COUNT(*) FROM continuous_shadow_position_marks"
        ).fetchone()[0]
        observed = connection.execute(
            "SELECT last_observed_poll_run_id, freshness FROM continuous_shadow_positions"
        ).fetchone()
    health = repository.health(
        "polycop", now=later + timedelta(seconds=2), poll_interval_seconds=60
    )
    assert history == 1
    assert observed[0] == second_poll
    assert observed[1] == "FRESH"
    assert health.stale_last_known_good_mark_count == 0


def test_price_change_appends_one_history_row(tmp_path: Path) -> None:
    database = tmp_path / "continuous-shadow.sqlite3"
    repository = ContinuousShadowRepository(database)
    repository.initialize()
    experiment_id, selection = _start(repository, NOW)
    first_poll = repository.start_poll(
        lease=_lease(database, NOW),
        experiment_id=experiment_id,
        selection=selection,
        selection_fresh=True,
        window_start=NOW,
        window_end=NOW + timedelta(minutes=1),
        started_at=NOW,
    )
    repository.complete_poll(
        first_poll,
        experiment=repository.active_experiment("polycop"),
        selection=selection,
        completion=_completion(
            (_mark(price=Decimal("0.40")),), _portfolio(Decimal("0.40"))
        ),
        completed_at=NOW + timedelta(seconds=1),
    )
    later = NOW + timedelta(minutes=1)
    second_poll = repository.start_poll(
        lease=_lease(database, later),
        experiment_id=experiment_id,
        selection=selection,
        selection_fresh=True,
        window_start=later,
        window_end=later + timedelta(minutes=1),
        started_at=later,
    )
    repository.complete_poll(
        second_poll,
        experiment=repository.active_experiment("polycop"),
        selection=selection,
        completion=_completion(
            (_mark(price=Decimal("0.41"), marked_at=later),),
            _portfolio(Decimal("0.41")),
        ),
        completed_at=later + timedelta(seconds=1),
    )
    with sqlite3.connect(database) as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM continuous_shadow_position_marks"
        ).fetchone()[0] == 2
        assert connection.execute(
            "SELECT schema_version FROM continuous_shadow_metadata"
        ).fetchone()[0] == CONTINUOUS_SHADOW_SCHEMA_VERSION


def test_prune_preserves_current_state_and_uses_clock(tmp_path: Path) -> None:
    database = tmp_path / "continuous-shadow.sqlite3"
    repository = ContinuousShadowRepository(database)
    repository.initialize()
    experiment_id, selection = _start(repository, NOW)
    poll = repository.start_poll(
        lease=_lease(database, NOW),
        experiment_id=experiment_id,
        selection=selection,
        selection_fresh=True,
        window_start=NOW,
        window_end=NOW + timedelta(minutes=1),
        started_at=NOW,
    )
    repository.complete_poll(
        poll,
        experiment=repository.active_experiment("polycop"),
        selection=selection,
        completion=_completion(
            (_mark(price=Decimal("0.40")),), _portfolio(Decimal("0.40"))
        ),
        completed_at=NOW + timedelta(seconds=1),
    )
    with sqlite3.connect(database) as connection:
        connection.execute(
            "UPDATE continuous_shadow_position_marks SET marked_at = ? "
            "WHERE poll_run_id = ?",
            ((NOW - timedelta(days=31)).isoformat(), poll),
        )
        connection.commit()
    result = repository.prune_mark_history(now=NOW, deduplicate=True)
    with sqlite3.connect(database) as connection:
        remaining = connection.execute(
            "SELECT COUNT(*) FROM continuous_shadow_position_marks"
        ).fetchone()[0]
        positions = connection.execute(
            "SELECT COUNT(*) FROM continuous_shadow_positions"
        ).fetchone()[0]
    assert result["deleted_expired_count"] >= 1
    assert remaining == 0
    assert positions == 1


def test_schema_v5_to_v6_is_idempotent(tmp_path: Path) -> None:
    database = tmp_path / "legacy-v5.sqlite3"
    schema = (
        Path(__file__).resolve().parent / "fixtures" / "continuous_shadow_schema_v5.sql"
    ).read_text(encoding="utf-8")
    with sqlite3.connect(database) as connection:
        connection.executescript(schema)
        connection.execute(
            "INSERT INTO continuous_shadow_metadata (schema_version, initialized_at) "
            "VALUES (5, ?)",
            (NOW.isoformat(),),
        )
    ContinuousShadowRepository(database).initialize()
    ContinuousShadowRepository(database).initialize()
    with sqlite3.connect(database) as connection:
        assert connection.execute(
            "SELECT schema_version FROM continuous_shadow_metadata"
        ).fetchone()[0] == 6
        columns = {
            row[1]
            for row in connection.execute("PRAGMA table_info(continuous_shadow_positions)")
        }
    assert "observed_at" in columns
    assert "state_changed_at" in columns


def test_compact_backup_does_not_modify_source(tmp_path: Path) -> None:
    source = tmp_path / "source.sqlite3"
    destination = tmp_path / "compact.sqlite3"
    with sqlite3.connect(source) as connection:
        connection.execute("CREATE TABLE demo (id INTEGER PRIMARY KEY, note TEXT)")
        connection.execute("INSERT INTO demo (note) VALUES ('keep')")
        connection.execute("DELETE FROM demo")
        connection.execute("INSERT INTO demo (note) VALUES ('keep')")
        connection.commit()
    before = source.stat().st_size
    compact_sqlite_database(source, destination)
    assert source.stat().st_size == before
    with sqlite3.connect(destination) as connection:
        assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert connection.execute("SELECT note FROM demo").fetchone()[0] == "keep"


def test_rotating_bundles_never_remove_pinned_directory(tmp_path: Path) -> None:
    created = NOW
    first = rotating_bundle_dir(tmp_path, created)
    second = rotating_bundle_dir(tmp_path, created + timedelta(hours=1))
    third = rotating_bundle_dir(tmp_path, created + timedelta(hours=2))
    fourth = rotating_bundle_dir(tmp_path, created + timedelta(hours=3))
    pinned = tmp_path / "pinned" / "migration-v1"
    for path in (first, second, third, fourth, pinned):
        record = RecoveryDatabaseRecord(
            role="continuous-shadow",
            filename="continuous-shadow.sqlite3",
            sha256="a" * 64,
            schema_version=6,
            integrity="ok",
            created_at=NOW.isoformat(),
            size_bytes=1,
            counts={"marks": 1},
        )
        (path / "continuous-shadow.sqlite3").parent.mkdir(parents=True, exist_ok=True)
        (path / "continuous-shadow.sqlite3").write_bytes(b"x")
        write_bundle_manifest(
            path,
            RecoveryBundleManifest(
                manifest_version=1,
                policy_version="recovery-bundle-v1",
                role="rotating" if path != pinned else "pinned-migration-checkpoint",
                created_at=created,
                release_sha="abc",
                experiment_id="exp",
                watermark=NOW.isoformat(),
                max_skew_seconds=3600,
                databases=(record,),
            ),
        )
    removed = prune_rotating_bundles(tmp_path, keep=3)
    assert len(removed) == 1
    assert pinned.exists()
    manifest = load_bundle_manifest(fourth)
    assert manifest.role == "rotating"
    assert DEFAULT_STAGE4B_DATA_LIFECYCLE_POLICY.mark_history_retention_days == 30


def _lease(database: Path, now: datetime):
    leases = ContinuousShadowLeaseRepository(database)
    leases.initialize()
    return leases.acquire_lease(
        CONTINUOUS_SHADOW_LEASE_RESOURCE,
        owner_id="test",
        acquired_at=now,
        lease_duration=timedelta(minutes=30),
    )
