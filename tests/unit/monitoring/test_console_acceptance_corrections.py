"""Cross-view financial qualification through the actual retained gateway."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import pytest

from polysia.monitoring.console_gateway import PREFIX
from tests.unit.monitoring.test_console_h1 import call
from tests.unit.monitoring.test_console_h2 import prepared


@pytest.mark.parametrize(
    "case",
    [
        "fresh",
        "expired",
        "missing_at",
        "missing_until",
        "malformed_at",
        "malformed_until",
        "future_at",
        "mode",
        "scope",
        "blocked",
    ],
)
def test_economics_reuses_snapshot_financial_qualification(tmp_path, case):
    app, _, _ = prepared(tmp_path)
    path = tmp_path / "publication.json"
    raw = json.loads(path.read_text(encoding="utf-8"))
    financial = raw["financial_session"]
    now = datetime.now(UTC)
    financial["account_observed_at"] = now.isoformat()
    financial["account_valid_until"] = (now + timedelta(seconds=20)).isoformat()
    if case == "expired":
        financial["account_observed_at"] = (now - timedelta(hours=1)).isoformat()
        financial["account_valid_until"] = (now - timedelta(minutes=59)).isoformat()
    elif case.startswith("missing_"):
        financial.pop("account_observed_at" if case.endswith("_at") else "account_valid_until")
    elif case.startswith("malformed_"):
        financial["account_observed_at" if case.endswith("_at") else "account_valid_until"] = "bad"
    elif case == "future_at":
        financial["account_observed_at"] = (now + timedelta(hours=1)).isoformat()
    elif case == "mode":
        financial["identity"]["configured_mode"] = "LIVE"
        financial["trading_mode"] = "PAPER"
    elif case == "scope":
        financial["identity"]["run"] = None
    elif case == "blocked":
        financial["exposure"]["reconciliation"] = "BLOCKED"
    path.write_text(json.dumps(raw), encoding="utf-8")
    snapshot = call(app, PREFIX + "/snapshot")[2]
    meta = next(row for row in snapshot["components"] if row["name"] == "financial")
    result = call(app, PREFIX + "/workspace?panel=evaluate")[2]
    economics = next(
        row for row in result["sections"] if row["title"] == "Actual trading economics"
    )
    assert economics["validity"] == meta
    values = {row["label"]: row["value"] for row in economics["facts"]}
    assert values["cash"] == (None if case == "blocked" else financial["economics"]["cash"])
    if case == "blocked":
        assert values["status"] == "UNKNOWN_RECONCILIATION_BLOCKED"
    if case == "fresh":
        assert meta["state"] == "AVAILABLE"
        assert meta["valid_until"] == financial["account_valid_until"]
    else:
        assert meta["state"] != "AVAILABLE"
    # Account qualification is not a dependency of retained latency evidence.
    system = call(app, PREFIX + "/workspace?panel=system")[2]
    latency = next(row for row in system["sections"] if row["title"] == "Latency and coverage")
    assert latency["validity"]["state"] == "AVAILABLE"


def test_invalid_scope_cannot_fall_back_to_publication_validity(tmp_path):
    app, _, _ = prepared(tmp_path)
    path = tmp_path / "publication.json"
    raw = json.loads(path.read_text(encoding="utf-8"))
    raw["financial_session"]["identity"]["account"] = []
    path.write_text(json.dumps(raw), encoding="utf-8")
    status, _, snapshot = call(app, PREFIX + "/snapshot")
    assert status == "200 OK"
    assert snapshot["financial"] is None
    assert snapshot["context"]["provenance"] == "publication_unavailable_or_incompatible"
    meta = next(row for row in snapshot["components"] if row["name"] == "financial")
    assert meta["state"] == "UNAVAILABLE"
    status, _, value = call(app, PREFIX + "/workspace?panel=evaluate")
    assert status == "409 Conflict"
    assert value == {"reason": "invalid_or_incompatible_console_request"}
