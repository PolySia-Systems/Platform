"""A multi-query operational report must observe one SQLite read transaction."""

import sqlite3

from polysia.storage.continuous_shadow import ContinuousShadowRepository
from tests.integration.test_continuous_shadow_portfolio import (
    NOW,
    _Clock,
    _MarketPort,
    _Scenario,
    _seed_stage3,
    _service,
    _shadow_database,
)


def test_results_do_not_mix_commits_during_a_writer_update(tmp_path, monkeypatch):
    database = tmp_path / "source.sqlite3"
    _seed_stage3(database)
    clock = _Clock(NOW)
    experiment = _service(database, _Scenario(), _MarketPort(clock), clock).start("polycop")
    path = _shadow_database(database)
    with sqlite3.connect(path) as connection:
        connection.execute("PRAGMA journal_mode=WAL")
    store = ContinuousShadowRepository(path)
    before = store.results(experiment.experiment_id, limit=1)
    original = store._connect
    wrote = False

    def connect(*, read_only=False):
        connection = original(read_only=read_only)

        def trace(sql):
            nonlocal wrote
            # The experiment SELECT has completed; update before portfolio reads.
            if not wrote and "SELECT p.*, COALESCE" in sql:
                wrote = True
                with sqlite3.connect(path) as writer:
                    writer.execute(
                        "UPDATE continuous_shadow_portfolios SET cash = '777', nav = '777' "
                        "WHERE portfolio_id = 'follower'"
                    )
        connection.set_trace_callback(trace)
        return connection

    monkeypatch.setattr(store, "_connect", connect)
    during = store.results(experiment.experiment_id, limit=1)
    assert wrote
    assert during["follower"] == before["follower"]
    monkeypatch.setattr(store, "_connect", original)
    assert store.results(experiment.experiment_id, limit=1)["follower"]["cash"] == "777"
