"""Deterministic interleavings over shared read-only Console state."""

import hashlib
import json
from concurrent.futures import ThreadPoolExecutor
from threading import Event

import pytest

from polysia.monitoring.console_example import publication
from polysia.monitoring.console_projection import ConsoleReadModel
from tests.unit.monitoring.test_console import application


def test_index_is_built_once_for_concurrent_readers(monkeypatch):
    model = ConsoleReadModel(publication(), "a" * 64)
    entered, release, second = Event(), Event(), Event()
    original = model._add
    additions = []

    def add(kind, row):
        additions.append(row["identity"])
        if len(additions) == 1:
            entered.set()
            assert release.wait(5)
        original(kind, row)

    monkeypatch.setattr(model, "_add", add)

    def reader():
        second.set()
        return model.page(kind="wallet")

    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(model.page, kind="wallet")
        assert entered.wait(5)
        other = pool.submit(reader)
        assert second.wait(5)
        release.set()
        assert first.result(5) == other.result(5)
    assert len(additions) == 2


def test_model_keeps_payload_and_generation_from_the_same_read(tmp_path, monkeypatch):
    app = application(tmp_path)
    old = app._publication.read_bytes()
    entered, release = Event(), Event()
    original = app._read_publication_snapshot

    def held_snapshot():
        snapshot = original()
        entered.set()
        assert release.wait(5)
        return snapshot

    monkeypatch.setattr(app, "_read_publication_snapshot", held_snapshot)
    with ThreadPoolExecutor(max_workers=1) as pool:
        pending = pool.submit(app._gateway.model)
        assert entered.wait(5)
        next_path = tmp_path / "next.json"
        next_path.write_text(json.dumps({"marker": "new generation"}), encoding="utf-8")
        next_path.replace(app._publication)
        fresh, fresh_generation = original()
        release.set()
        model = pending.result(5)
    assert model.publication == json.loads(old)
    assert model.generation == hashlib.sha256(old).hexdigest()
    assert fresh["marker"] == "new generation"
    assert fresh_generation != model.generation


def test_failed_index_can_retry_without_publishing_partial_results(monkeypatch):
    model = ConsoleReadModel(publication(), "a" * 64)
    original = model._add

    def fail(kind, row):
        original(kind, row)
        raise ValueError("incomplete")

    monkeypatch.setattr(model, "_add", fail)
    with pytest.raises(ValueError, match="incomplete"):
        model.page(kind="wallet")
    assert not model._indexed
    monkeypatch.setattr(model, "_add", original)
    assert len(model.page(kind="wallet").items) == 2
