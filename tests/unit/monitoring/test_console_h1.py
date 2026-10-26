from __future__ import annotations

import io
import json
import shutil
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

import pytest

from polysia.control.service import ControlService
from polysia.monitoring.console_bundle import verify_bundle
from polysia.monitoring.console_contract import Snapshot
from polysia.monitoring.console_gateway import PREFIX
from tests.fixtures.console_h1 import write_publication
from tests.unit.monitoring.test_console import application


def call(app, path: str, *, payload: dict | None = None, cookie: str = "", token="verified"):
    state: list[Any] = []
    route, _, query = path.partition("?")
    raw = json.dumps(payload).encode() if payload is not None else b""
    result = app(
        {
            "PATH_INFO": route,
            "QUERY_STRING": query,
            "REQUEST_METHOD": "POST" if payload is not None else "GET",
            "HTTP_CF_ACCESS_JWT_ASSERTION": token,
            "HTTP_HOST": "platform.example.com",
            "HTTP_ORIGIN": "https://platform.example.com",
            "CONTENT_TYPE": "application/json",
            "CONTENT_LENGTH": str(len(raw)),
            "wsgi.input": io.BytesIO(raw),
            "HTTP_COOKIE": cookie,
        },
        lambda status, headers: state.extend((status, dict(headers))),
    )
    body = b"".join(result)
    return (
        state[0],
        state[1],
        json.loads(body) if state[1]["Content-Type"].startswith("application/json") else body,
    )


def setup(tmp_path: Path, *, role="operator", count=4):
    app = application(
        tmp_path,
        role=role,
        targets=frozenset({"fixture-lab", "fixture-run:stop", "fixture-run:drain"}),
    )
    write_publication(tmp_path, wallets=count, orders=200)
    _, headers, session = call(app, PREFIX + "/session")
    return app, session, headers["Set-Cookie"].split(";")[0]


def preview(app, session, cookie, operation="session.stop"):
    snapshot = call(app, PREFIX + "/snapshot")[2]
    action = next(a for a in snapshot["actions"] if a["operation"] == operation)
    payload = {key: action[key] for key in ("operation", "target", "context")}
    status, _, value = call(
        app,
        PREFIX + "/preview",
        payload={**payload, "identity": session["identity"], "csrf": session["csrf"]},
        cookie=cookie,
    )
    assert status == "202 Accepted", value
    return value


def apply_payload(value, session, key="one-intended-operation"):
    return {
        key: value[key] for key in ("preview_id", "expected_revision", "context", "identity")
    } | {"csrf": session["csrf"], "idempotency_key": key}


def test_optional_record_and_supervision_failures_do_not_mask_protective_stop(
    tmp_path, monkeypatch
):
    app, session, cookie = setup(tmp_path)
    path = tmp_path / "publication.json"
    raw = json.loads(path.read_text())
    raw["diagnostic"]["discovery"]["candidates"][0]["wallet_id"] = []
    path.write_text(json.dumps(raw))
    supervision = tmp_path / "supervisor-status.json"
    raw = json.loads(supervision.read_text())
    raw["scope"] = []
    supervision.write_text(json.dumps(raw))
    snapshot = call(app, PREFIX + "/snapshot")[2]
    assert snapshot["financial"]["cash"]["value"] == "100"
    assert snapshot["supervision"]["status"] == "UNKNOWN"
    assert call(app, PREFIX + "/records?kind=wallet")[0] == "409 Conflict"
    actions = call(app, PREFIX + "/protective-actions")[2]["actions"]
    action = next(a for a in actions if a["operation"] == "session.stop")

    def no_optional_read():
        raise AssertionError("STOP must not consult an optional publication")

    monkeypatch.setattr(app, "_read_publication", no_optional_read)
    status, _, value = call(
        app,
        PREFIX + "/preview",
        payload={
            **{key: action[key] for key in ("operation", "target", "context")},
            "identity": session["identity"],
            "csrf": session["csrf"],
        },
        cookie=cookie,
    )
    assert status == "202 Accepted"
    assert (
        call(app, PREFIX + "/apply", payload=apply_payload(value, session), cookie=cookie)[0]
        == "202 Accepted"
    )


def test_actual_producer_scope_mode_supervision_and_exact_amounts(tmp_path):
    app, _, _ = setup(tmp_path)
    status, headers, data = call(app, PREFIX + "/snapshot")
    assert status == "200 OK" and headers["Cache-Control"] == "no-store"
    checked = Snapshot.model_validate(data)
    assert checked.context.configured_mode == checked.context.observed_mode == "PAPER"
    assert checked.context.scope.run == "fixture-run"
    assert checked.financial.cash.value == "100"
    assert checked.financial.reserved.value == "1.010"
    assert checked.supervision.status == "STOPPED" and checked.atomic is False
    assert "Independent STOP" in checked.blocker
    (tmp_path / "supervisor-status.json").write_text(
        json.dumps(
            {"status": "STOP", "scope": "wrong-run", "observed_at": datetime.now(UTC).isoformat()}
        )
    )
    data = call(app, PREFIX + "/snapshot")[2]
    assert data["supervision"]["status"] == "UNKNOWN"
    assert data["components"][-1]["reason"] == "supervision_scope_mismatch"


@pytest.mark.parametrize("mutation", ["missing", "expired", "bad_status", "future"])
def test_supervision_is_independently_invalidated(tmp_path, mutation):
    app, _, _ = setup(tmp_path)
    path = tmp_path / "supervisor-status.json"
    raw = json.loads(path.read_text())
    if mutation == "missing":
        path.unlink()
    else:
        if mutation == "expired":
            raw["expires_at"] = (datetime.now(UTC) - timedelta(seconds=1)).isoformat()
        if mutation == "bad_status":
            raw["status"] = "MAYBE_READY"
        if mutation == "future":
            raw["observed_at"] = (datetime.now(UTC) + timedelta(hours=1)).isoformat()
        path.write_text(json.dumps(raw))
    data = call(app, PREFIX + "/snapshot")[2]
    assert data["supervision"]["status"] == "UNKNOWN"
    assert data["financial"]["cash"]["value"] == "100"


def test_bounded_10000_wallet_200_order_pages_detail_and_expired_cursor(tmp_path):
    app, _, _ = setup(tmp_path, count=10_000)
    data = call(app, PREFIX + "/records?kind=wallet")[2]
    assert len(data["items"]) == 50 and data["total"] == 10_000
    assert len(json.dumps(data)) < 30_000
    second = call(app, PREFIX + "/records?kind=wallet&cursor=" + data["next_cursor"])[2]
    assert second["items"][0]["identity"] == "wallet-00050"
    detail = call(
        app,
        PREFIX
        + "/detail?"
        + urlencode({"kind": "order", "identity": "order-00199", "generation": data["generation"]}),
    )[2]
    assert detail["record"]["identity"] == "order-00199"
    assert call(app, PREFIX + "/records?kind=wallet&limit=101")[0] == "409 Conflict"
    assert call(app, PREFIX + "/records?kind=wallet&sort=sql")[0] == "409 Conflict"
    assert call(app, PREFIX + "/records?kind=wallet&kind=order")[0] == "409 Conflict"
    raw = json.loads((tmp_path / "publication.json").read_text())
    raw["version"] = "next-generation"
    (tmp_path / "publication.json").write_text(json.dumps(raw))
    assert call(app, PREFIX + "/records?kind=wallet&cursor=" + data["next_cursor"])[0] == "410 Gone"


def test_lost_response_same_key_two_tabs_and_restart_unknown(tmp_path):
    app, session, cookie = setup(tmp_path)
    first = preview(app, session, cookie)
    second = preview(app, session, cookie)
    payload = apply_payload(first, session)
    status, _, receipt = call(app, PREFIX + "/apply", payload=payload, cookie=cookie)
    assert status == "202 Accepted" and receipt["phase"] == "REQUESTED"
    assert call(app, PREFIX + "/apply", payload=payload, cookie=cookie)[2] == receipt
    assert (
        call(
            app,
            PREFIX + "/apply",
            payload=apply_payload(second, session, "second-tab-intention"),
            cookie=cookie,
        )[0]
        == "409 Conflict"
    )
    found = call(app, PREFIX + "/receipts?key=one-intended-operation")[2]["items"]
    assert found == [receipt]
    store = app._commands
    assert store.claim_scoped("one-intended-operation", now=datetime.now(UTC)) is not None
    store.retire_scoped_claims(targets=frozenset({"fixture-run:stop"}))
    receipt = call(app, PREFIX + "/receipts?key=one-intended-operation")[2]["items"][0]
    assert receipt["phase"] == "FAILED" and receipt["effect"] == "UNKNOWN"
    assert store.claim_scoped("one-intended-operation", now=datetime.now(UTC)) is None


def test_protective_stop_without_publication_and_revoked_reader_denial(tmp_path):
    app, session, cookie = setup(tmp_path)
    (tmp_path / "publication.json").unlink()
    value = preview(app, session, cookie)
    assert (
        call(app, PREFIX + "/apply", payload=apply_payload(value, session), cookie=cookie)[0]
        == "202 Accepted"
    )
    app._verify = lambda _: ("other-actor", "operator")
    assert call(app, PREFIX + "/receipts?key=one-intended-operation")[2]["items"] == []
    app._verify = lambda _: ("owner-subject", "reader")
    assert (
        call(app, PREFIX + "/apply", payload=apply_payload(value, session), cookie=cookie)[0]
        == "403 Forbidden"
    )
    assert call(app, PREFIX + "/snapshot")[2]["actions"] == []


def test_exact_receipt_beyond_history_window_and_target_scope(tmp_path):
    app, session, cookie = setup(tmp_path)
    original = None
    for index in range(105):
        value = preview(app, session, cookie)
        key = f"intent-{index:016}"
        result = call(
            app, PREFIX + "/apply", payload=apply_payload(value, session, key), cookie=cookie
        )
        assert result[0] == "202 Accepted"
        original = original or result[2]
        ControlService.execute_scoped(
            app._commands,
            idempotency_key=key,
            now=datetime.now(UTC),
            execute=lambda _: {"effect": "OBSERVED", "reason": "synthetic_stop"},
        )
    data = call(app, PREFIX + "/receipts")[2]
    assert len(data["items"]) == 50 and data["next_cursor"]
    receipt = call(app, PREFIX + "/receipts?key=" + original["idempotency_key"])[2]["items"][0]
    assert receipt["phase"] == "APPLIED" and receipt["effect"] == "OBSERVED"
    app._scoped_targets = frozenset({"different-run:stop"})
    assert call(app, PREFIX + "/receipts?key=" + original["idempotency_key"])[2]["items"] == []


@pytest.mark.parametrize("mutation", ["api", "release", "traversal", "identity", "unlisted"])
def test_bundle_rejects_incompatible_or_unlisted_custody(tmp_path, mutation):
    from polysia.monitoring import console_bundle

    source = Path(console_bundle.__file__).with_name("human_console_assets")
    bundle = tmp_path / "bundle"
    shutil.copytree(source, bundle)
    path = bundle / "manifest.json"
    manifest = json.loads(path.read_text())
    if mutation == "api":
        manifest["api"] = "console/v999"
    if mutation == "release":
        manifest["release"] = "999.0.0"
    if mutation == "traversal":
        manifest["files"]["../private.js"] = "0" * 64
    if mutation == "identity":
        manifest["source"] = "f" * 64
    if mutation == "unlisted":
        (bundle / "unexpected.js").write_text("not shipped")
    path.write_text(json.dumps(manifest))
    with pytest.raises(ValueError):
        verify_bundle(bundle)


def test_bundle_rejects_stale_source_even_when_shipped_bytes_match(tmp_path):
    from polysia.monitoring import console_bundle

    source = Path(console_bundle.__file__).with_name("human_console_assets")
    repository = Path(__file__).resolve().parents[3]
    root = tmp_path / "checkout"
    shutil.copytree(
        repository / "frontend",
        root / "frontend",
        ignore=shutil.ignore_patterns("node_modules", ".build"),
    )
    contract = root / "src/polysia/monitoring/console_contract.py"
    contract.parent.mkdir(parents=True)
    shutil.copyfile(repository / "src/polysia/monitoring/console_contract.py", contract)
    verify_bundle(source, source_root=root)
    messages = root / "frontend/src/messages.ts"
    messages.write_bytes(messages.read_bytes() + b"\n// source changed\n")
    with pytest.raises(ValueError, match="stale_console_source_build"):
        verify_bundle(source, source_root=root)


def test_bundle_custody_traversal_missing_changed_and_financial_binding(tmp_path):
    from polysia.deployment.financial_session_runtime import package_tree_digest
    from polysia.monitoring import console_bundle

    original = Path(console_bundle.__file__).with_name("human_console_assets")
    bundle = tmp_path / "bundle"
    shutil.copytree(original, bundle)
    verify_bundle(bundle)
    root = tmp_path / "package"
    shutil.copytree(bundle, root / "human_console_assets")
    before = package_tree_digest(root)
    manifest = root / "human_console_assets/manifest.json"
    manifest.write_bytes(manifest.read_bytes() + b" ")
    assert package_tree_digest(root) != before
    entry = next(bundle.glob("*.js"))
    entry.write_bytes(entry.read_bytes() + b";")
    with pytest.raises(ValueError, match="changed"):
        verify_bundle(bundle)
    entry.unlink()
    with pytest.raises(ValueError):
        verify_bundle(bundle)
    app, _, _ = setup(tmp_path / "gateway")
    assert call(app, "/h1/assets/../console.py")[0] == "404 Not Found"
    assert call(app, "/h1", token="invalid")[0] == "403 Forbidden"


@pytest.mark.parametrize(
    "field,value",
    [
        ("trading_mode", "UNSAFE"),
        ("cash", "NaN"),
        ("cash", 1.01),
        ("configured_mode", "UNSAFE"),
        ("scope", "missing"),
    ],
)
def test_malformed_safety_contract_never_becomes_ready(tmp_path, field, value):
    app, _, _ = setup(tmp_path)
    path = tmp_path / "publication.json"
    raw = json.loads(path.read_text())
    view = raw["financial_session"]
    if field == "cash":
        view["exposure"]["cash"] = value
    elif field == "configured_mode":
        view["identity"][field] = value
    elif field == "scope":
        view["identity"].pop("run")
    else:
        view[field] = value
    path.write_text(json.dumps(raw))
    snapshot = call(app, PREFIX + "/snapshot")[2]
    assert not all(c["state"] == "AVAILABLE" for c in snapshot["components"])


def test_expired_csrf_preview_session_payload_key_and_context_recheck(tmp_path, monkeypatch):
    app, session, cookie = setup(tmp_path)
    value = preview(app, session, cookie)
    payload = apply_payload(value, session)
    assert (
        call(app, PREFIX + "/apply", payload={**payload, "expected_revision": True}, cookie=cookie)[
            0
        ]
        == "409 Conflict"
    )
    assert (
        call(app, PREFIX + "/apply", payload={**payload, "context": "f" * 64}, cookie=cookie)[0]
        == "409 Conflict"
    )
    import polysia.monitoring.console as console_module

    now = console_module.time.time()
    monkeypatch.setattr(console_module.time, "time", lambda: now + 3700)
    assert call(app, PREFIX + "/apply", payload=payload, cookie=cookie)[0] == "403 Forbidden"
    _, headers, renewed = call(app, PREFIX + "/session")
    new_cookie = headers["Set-Cookie"].split(";")[0]
    assert renewed["csrf"] != session["csrf"]
    assert (
        call(
            app, PREFIX + "/apply", payload={**payload, "csrf": renewed["csrf"]}, cookie=new_cookie
        )[0]
        == "409 Conflict"
    )
    assert (
        app._commands.pending_scoped(
            targets=app._scoped_targets, operations=frozenset({"session.stop"})
        )
        == []
    )
