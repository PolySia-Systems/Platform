from __future__ import annotations

import asyncio
import json
import sqlite3
from contextlib import closing
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from polysia.control.scoped_operations import ScopedPreview
from polysia.control.service import ControlService
from polysia.monitoring.console_contract import Workspace
from polysia.monitoring.console_gateway import PREFIX
from tests.fixtures.console_h2 import lab, write
from tests.unit.monitoring.test_console import application
from tests.unit.monitoring.test_console_h1 import apply_payload, call


def prepared(root, *, owner=None, role="operator"):
    app = application(
        root, role=role, targets=frozenset({"fixture-lab", "fixture-lab-two", "fixture-run:stop"})
    )
    write(root, wallets=4, orders=2, lab_view=owner.console_view() if owner else None)
    _, headers, session = call(app, PREFIX + "/session")
    return app, session, headers["Set-Cookie"].split(";")[0]


def preview(app, session, cookie, operation, target, arguments=None):
    catalog = call(app, PREFIX + "/snapshot")[2]["actions"]
    action = next(
        row for row in catalog if (row["operation"], row["target"]) == (operation, target)
    )
    status, _, result = call(
        app,
        PREFIX + "/preview",
        cookie=cookie,
        payload={
            "operation": operation,
            "target": target,
            "context": action["context"],
            "arguments": arguments or {},
            "identity": session["identity"],
            "csrf": session["csrf"],
        },
    )
    assert status == "202 Accepted", result
    return result


def publish_lab(app, owner):
    path = app._publication
    raw = json.loads(path.read_text())
    raw["shadow_lab"] = owner.console_view()
    path.write_text(json.dumps(raw, default=str))


def owner_preview(operation, target, arguments=()):
    now = datetime.now(UTC)
    return ScopedPreview(
        operation, target, 0, "fixture-owner", now, now + timedelta(minutes=1), arguments
    )


def test_all_registered_lab_forms_reach_actual_owner_and_comparison(tmp_path):
    owner = lab(tmp_path / "lab")
    app, session, cookie = prepared(tmp_path / "console", owner=owner)
    policies = list(owner.templates)

    def run(operation, target="fixture-lab", arguments=None):
        plan = preview(app, session, cookie, operation, target, arguments)
        key = str(uuid4())
        payload = apply_payload(plan, session, key)
        assert call(app, PREFIX + "/apply", cookie=cookie, payload=payload)[0] == "202 Accepted"
        result = ControlService.execute_scoped(
            app._commands, idempotency_key=key, now=datetime.now(UTC), execute=owner.execute
        )
        assert result["effect"] == "OBSERVED", result
        receipt = call(app, PREFIX + "/receipts?key=" + key)[2]["items"][0]
        assert receipt["phase"] == "APPLIED" and receipt["effect"] == "OBSERVED"
        publish_lab(app, owner)
        return receipt

    try:
        run("shadow.create", arguments={"policy_digest": policies[0]})
        run("shadow.clone", "fixture-lab-two", {"source": "fixture-lab"})
        run("policy.stage", "fixture-lab-two", {"policy_digest": policies[1]})
        run("shadow.start")
        run("shadow.start", "fixture-lab-two")
        comparison = run("shadow.compare", arguments={"other": "fixture-lab-two"})
        assert comparison["tables"][0]["total"] == 2
        assert (
            next(row for row in comparison["facts"] if row["label"] == "sum of returns")["value"]
            is None
        )
        run("shadow.drain")
        run("shadow.resume")
        run("shadow.drain")
        run("shadow.finalize")
        run("shadow.archive")
        run("shadow.drain", "fixture-lab-two")
        run("shadow.archive", "fixture-lab-two")
        assert owner.acquisition.status()["requests_charged"] == 0
        assert owner.slot("fixture-lab")["phase"] == "ARCHIVED"
        assert "rpc.fixture" not in json.dumps(call(app, PREFIX + "/workspace?panel=operate")[2])
    finally:
        asyncio.run(owner.close())


def test_registered_argument_tampering_and_actor_target_changes_fail_closed(tmp_path):
    owner = lab(tmp_path / "lab")
    owner.execute(
        owner_preview(
            "shadow.create", "fixture-lab-two", (("policy_digest", next(iter(owner.templates))),)
        )
    )
    app, session, cookie = prepared(tmp_path / "console", owner=owner)
    try:
        action = next(
            row
            for row in call(app, PREFIX + "/snapshot")[2]["actions"]
            if row["operation"] == "shadow.create"
        )
        for arguments in (
            {"policy_digest": "f" * 64},
            {"policy_digest": next(iter(owner.templates)), "path": "secret"},
        ):
            assert (
                call(
                    app,
                    PREFIX + "/preview",
                    cookie=cookie,
                    payload={
                        **{key: action[key] for key in ("operation", "target", "context")},
                        "arguments": arguments,
                        "identity": session["identity"],
                        "csrf": session["csrf"],
                    },
                )[0]
                == "409 Conflict"
            )
        plan = preview(
            app, session, cookie, "shadow.clone", "fixture-lab", {"source": "fixture-lab-two"}
        )
        app._scoped_targets = frozenset({"fixture-lab"})
        # A changed related-target catalog must invalidate the exact original context.
        assert (
            call(app, PREFIX + "/apply", cookie=cookie, payload=apply_payload(plan, session))[0]
            == "409 Conflict"
        )
        assert owner.acquisition.status()["requests_charged"] == 0
    finally:
        asyncio.run(owner.close())


def test_clone_fences_unpublished_source_policy_change_before_owner_effect(tmp_path):
    owner = lab(tmp_path / "lab")
    first, second = owner.templates
    owner.execute(owner_preview("shadow.create", "fixture-lab", (("policy_digest", first),)))
    app, session, cookie = prepared(tmp_path / "console", owner=owner)
    try:
        plan = preview(
            app, session, cookie, "shadow.clone", "fixture-lab-two", {"source": "fixture-lab"}
        )
        assert {item["label"]: item["value"] for item in plan["arguments"]}[
            "source_policy_digest"
        ] == first
        key = "clone-frozen-policy-intent"
        assert (
            call(app, PREFIX + "/apply", cookie=cookie, payload=apply_payload(plan, session, key))[
                0
            ]
            == "202 Accepted"
        )
        owner.execute(owner_preview("policy.stage", "fixture-lab", (("policy_digest", second),)))
        result = ControlService.execute_scoped(
            app._commands, idempotency_key=key, now=datetime.now(UTC), execute=owner.execute
        )
        assert result["effect"] == "UNKNOWN_OR_FAILED"
        assert owner.slot("fixture-lab-two") is None
        receipt = call(app, PREFIX + "/receipts?key=" + key)[2]["items"][0]
        assert receipt["phase"] == "FAILED" and receipt["effect"] == "UNKNOWN"
        assert owner.acquisition.status()["requests_charged"] == 0
    finally:
        asyncio.run(owner.close())


def test_acquisition_exact_preview_receipt_recovery_and_cross_queue_key_rejection(tmp_path):
    app, session, cookie = prepared(tmp_path)
    path = tmp_path / "publication.json"
    path.unlink()
    plan = preview(app, session, cookie, "acquisition.stop", "acquisition")
    payload = apply_payload(plan, session, "one-acquisition-intention")
    first = call(app, PREFIX + "/apply", cookie=cookie, payload=payload)
    assert first[0] == "202 Accepted" and first[2]["phase"] == "REQUESTED"
    assert call(app, PREFIX + "/apply", cookie=cookie, payload=payload)[2] == first[2]
    assert app._commands.pending() == [(1, "stop")]
    app._commands.finish(1, status="FAILED", result={"effect": "UNKNOWN", "reason": "owner_lost"})
    recovered = call(app, PREFIX + "/receipts?key=one-acquisition-intention")[2]["items"][0]
    assert recovered["phase"] == "FAILED" and recovered["effect"] == "UNKNOWN"
    scoped = preview(app, session, cookie, "session.stop", "fixture-run:stop")
    assert (
        call(
            app,
            PREFIX + "/apply",
            cookie=cookie,
            payload=apply_payload(scoped, session, "one-acquisition-intention"),
        )[0]
        == "409 Conflict"
    )
    app._verify = lambda _: ("other-actor", "operator")
    assert call(app, PREFIX + "/receipts?key=one-acquisition-intention")[2]["items"] == []


def test_acquisition_stop_admission_ignores_corrupt_optional_receipt_result(tmp_path):
    app, session, cookie = prepared(tmp_path)
    app._commands.submit(
        subject="owner-subject",
        action="stop",
        expected_revision=0,
        idempotency_key="prior-receipt-corruption",
    )
    with closing(sqlite3.connect(tmp_path / "commands.sqlite3")) as connection, connection:
        connection.execute("UPDATE commands SET result='broken-json'")
    plan = preview(app, session, cookie, "acquisition.stop", "acquisition")
    assert plan["expected_revision"] == 1
    assert (
        call(app, PREFIX + "/apply", cookie=cookie, payload=apply_payload(plan, session))[0]
        == "202 Accepted"
    )


@pytest.mark.parametrize("panel", ["operate", "evaluate", "system"])
def test_workspaces_actual_producers_bound_and_keep_unknowns(tmp_path, panel):
    app, _, _ = prepared(tmp_path)
    status, _, result = call(app, PREFIX + "/workspace?panel=" + panel)
    assert status == "200 OK"
    model = Workspace.model_validate(result)
    assert len(model.model_dump_json()) < 220_000
    assert all(len(table.rows) <= 100 for section in model.sections for table in section.tables)
    assert "private-fixture-account" not in model.model_dump_json()
    if panel == "system":
        capability = model.sections[0].tables[0]
        assert next(row for row in capability.rows if row[0] == "new_entries")[1] == "BLOCKED"
        assert "NOT_CONFIGURED" in model.model_dump_json()


def test_selection_records_source_filter_actual_trace_and_position_detail(tmp_path):
    app, _, _ = prepared(tmp_path)
    page = call(app, PREFIX + "/records?kind=wallet&source=polycop")[2]
    assert page["total"] == 4 and page["items"][0]["facts"] == []
    generation = page["generation"]
    wallet = call(app, PREFIX + f"/detail?kind=wallet&identity=wallet&generation={generation}")[2][
        "record"
    ]
    assert any(link["identity"] == "order-00000" for link in wallet["links"])
    order = call(app, PREFIX + f"/detail?kind=order&identity=order-00000&generation={generation}")[
        2
    ]["record"]
    assert next(f for f in order["facts"] if f["label"] == "trigger id")["value"] is not None
    assert any(f["label"].startswith("Fill ") for f in order["facts"])
    position = call(app, PREFIX + f"/detail?kind=position&identity=token&generation={generation}")[
        2
    ]["record"]
    assert position["state"] == "OPEN" and position["quantity"]["value"] == "1"
    assert next(f for f in position["facts"] if f["label"] == "redeemable")["value"] == "UNKNOWN"


def test_optional_publisher_and_capability_malformations_never_mask_financial_or_admit(tmp_path):
    app, _, _ = prepared(tmp_path)
    (tmp_path / "publisher-status.json").write_text(
        json.dumps({"status": {}, "scope": [], "checked_at": datetime.now(UTC).isoformat()})
    )
    snapshot = call(app, PREFIX + "/snapshot")[2]
    assert snapshot["financial"]["cash"]["value"] is not None
    assert (
        next(c for c in snapshot["components"] if c["name"] == "publisher")["state"] != "AVAILABLE"
    )
    path = tmp_path / "publication.json"
    raw = json.loads(path.read_text())
    raw["capabilities"]["capabilities"] = [
        {"capability": "new_entries", "status": "READY", "required": [], "requirements": []}
    ]
    path.write_text(json.dumps(raw))
    result = call(app, PREFIX + "/workspace?panel=system")[2]
    assert result["sections"][0]["tables"][0]["rows"][0][1] == "BLOCKED"

    # Two absent scope identities do not establish an exact verified run.
    raw["financial_session"]["identity"]["run"] = None
    raw["capabilities"]["capabilities"] = [
        {
            "capability": "startup",
            "status": "READY",
            "requirements": [
                {
                    "identity": "configuration",
                    "state": "VERIFIED",
                    "evidence": {
                        "observed_at": datetime.now(UTC).isoformat(),
                        "expires_at": (datetime.now(UTC) + timedelta(minutes=1)).isoformat(),
                        "scope": None,
                    },
                }
            ],
        }
    ]
    path.write_text(json.dumps(raw))
    result = call(app, PREFIX + "/workspace?panel=system")[2]
    assert result["sections"][0]["tables"][0]["rows"][0][1] == "BLOCKED"


def test_combined_receipts_beyond_100_have_stable_pages_and_safe_downloads(tmp_path):
    app, _, _ = prepared(tmp_path)
    for index in range(105):
        app._commands.submit(
            subject="owner-subject",
            action="export",
            expected_revision=index,
            idempotency_key=f"retained-export-{index:016}",
        )
    app._commands.finish(1, status="APPLIED", result={"download": "javascript:alert(1)"})
    first = call(app, PREFIX + "/receipts")[2]
    assert len(first["items"]) == 50
    second = call(app, PREFIX + "/receipts?cursor=" + first["next_cursor"])[2]
    assert len(second["items"]) == 50
    assert not {r["idempotency_key"] for r in first["items"]} & {
        r["idempotency_key"] for r in second["items"]
    }
    exact = call(app, PREFIX + "/receipts?key=retained-export-0000000000000000")[2]["items"][0]
    assert exact["effect"] == "OBSERVED" and exact["download"] is None


def test_export_bounds_preview_expiry_and_request_limits(tmp_path):
    app, session, cookie = prepared(tmp_path)
    plan = preview(
        app,
        session,
        cookie,
        "acquisition.export",
        "acquisition",
        {"start": "2026-10-01T00:00:00Z", "end": "2026-10-02T00:00:00Z"},
    )
    assert len(plan["arguments"]) == 2
    with closing(sqlite3.connect(tmp_path / "commands.sqlite3")) as connection, connection:
        raw = json.loads(
            connection.execute("SELECT preview FROM console_acquisition_previews").fetchone()[0]
        )
        raw["expires_at"] = (datetime.now(UTC) - timedelta(seconds=1)).isoformat()
        connection.execute("UPDATE console_acquisition_previews SET preview=?", (json.dumps(raw),))
    assert (
        call(app, PREFIX + "/apply", cookie=cookie, payload=apply_payload(plan, session))[0]
        == "409 Conflict"
    )
    assert call(app, PREFIX + "/records?" + "q=x&" * 20)[0] == "409 Conflict"
    assert call(app, PREFIX + "/workspace?panel=" + "x" * 2100)[0] == "409 Conflict"
    assert app._commands.pending() == []


def test_fresh_publication_cannot_renew_expired_account_or_claim_reconciled_cash(tmp_path):
    app, _, _ = prepared(tmp_path)
    path = tmp_path / "publication.json"
    raw = json.loads(path.read_text())
    financial = raw["financial_session"]
    financial["account_observed_at"] = (datetime.now(UTC) - timedelta(hours=1)).isoformat()
    financial["account_valid_until"] = (datetime.now(UTC) - timedelta(minutes=59)).isoformat()
    path.write_text(json.dumps(raw))
    snapshot = call(app, PREFIX + "/snapshot")[2]
    assert next(c for c in snapshot["components"] if c["name"] == "financial")["state"] == "STALE"
    financial["account_observed_at"] = datetime.now(UTC).isoformat()
    financial["account_valid_until"] = (datetime.now(UTC) + timedelta(seconds=30)).isoformat()
    financial["exposure"]["reconciliation"] = "BLOCKED"
    financial["economics"]["status"] = "COMPLETE"
    path.write_text(json.dumps(raw))
    snapshot = call(app, PREFIX + "/snapshot")[2]
    assert snapshot["financial"]["cash"]["value"] is None
    assert snapshot["financial"]["economics"] == "UNKNOWN_RECONCILIATION_BLOCKED"
    assert (
        "Reconciliation is blocked" in snapshot["blocker"]
        or snapshot["supervision"]["status"] == "STOPPED"
    )


def test_mutations_reverify_installed_bundle_and_preserve_protective_cli_fallback(
    tmp_path, monkeypatch
):
    import polysia.monitoring.console_gateway as gateway

    app, session, cookie = prepared(tmp_path)
    plan = preview(app, session, cookie, "session.stop", "fixture-run:stop")

    def changed():
        raise ValueError("console_asset_missing_or_changed")

    monkeypatch.setattr(gateway, "verify_bundle", changed)
    assert call(app, PREFIX + "/session")[2]["bundle"] is None
    assert call(app, PREFIX + "/protective-actions")[2]["actions"] == []
    assert (
        call(app, PREFIX + "/apply", cookie=cookie, payload=apply_payload(plan, session))[0]
        == "409 Conflict"
    )
    assert app._commands.scoped_status() == []


def test_status_symlinks_do_not_expose_private_json_or_mask_financial(tmp_path):
    app, _, _ = prepared(tmp_path)
    secret = tmp_path / "private-fixture.json"
    secret.write_text(json.dumps({"private": "fixture-never-serve", "status": "OK"}))
    for name in ("publisher-status.json", "supervisor-status.json"):
        path = tmp_path / name
        path.unlink(missing_ok=True)
        try:
            path.symlink_to(secret)
        except OSError:
            pytest.skip("OS does not permit this fixture to create symlinks")
    assert call(app, "/api/health")[0] == "503 Service Unavailable"
    assert call(app, "/api/supervision")[0] == "503 Service Unavailable"
    status, _, snapshot = call(app, PREFIX + "/snapshot")
    assert status == "200 OK" and snapshot["financial"] is not None
    assert "fixture-never-serve" not in json.dumps(snapshot)


def test_actual_partial_resolution_and_settled_cash_keep_distinct_states(tmp_path):
    from decimal import Decimal

    from polysia.domain.financial_session import ObservedRedemption
    from polysia.monitoring.financial_session import financial_session_view
    from tests.integration.test_financial_session import BINDING, SCOPE, Harness, opportunity

    h = Harness(tmp_path)
    try:
        asyncio.run(h.coordinator.submit(opportunity()))
        identity = next(iter(h.journal.read()["orders"]))
        h.fill(identity, size="1", terminal=False, fill_id="partial-one")
        partial = financial_session_view(h.journal.read(), h.auth, now=h.now)
        assert partial["orders"][0]["fill_state"] == "PARTIAL_FILL"
        assert partial["positions"][0]["redeemable"] == "UNKNOWN"
        h.coordinator.record_valuation(
            {"token": Decimal("1")}, observed_at=h.now, method="confirmed_resolution"
        )
        resolved = financial_session_view(h.journal.read(), h.auth, now=h.now)
        assert resolved["positions"][0]["redeemable"] == "REDEEMABLE_REVIEW"
        assert resolved["positions"][0]["cash_events"] == []
        stale = financial_session_view(h.journal.read(), h.auth, now=h.now + timedelta(hours=1))
        assert stale["positions"][0]["redeemable"] == "UNKNOWN"
        h.fill(identity, size="1", terminal=True, fill_id="partial-two")
        h.now += timedelta(seconds=1)
        h.execution.cash += Decimal("2")
        h.execution.positions = {}
        redemption = ObservedRedemption(
            "settlement-one",
            BINDING.account,
            SCOPE.collateral,
            (("token", Decimal("2")),),
            Decimal("2"),
            h.now,
            "fixture-finality",
        )
        h.coordinator.observe_redemption(redemption, h.execution.account())
        settled = financial_session_view(h.journal.read(), h.auth, now=h.now)
        assert settled["positions"][0]["state"] == "CLOSED"
        assert settled["positions"][0]["average_price"] is None
        assert settled["positions"][0]["cash_events"][0]["confirmed_cash"] == "2"
    finally:
        h.journal.close()


def test_authoritative_empty_selection_and_nonfinancial_metrics_do_not_relax_money(tmp_path):
    app, _, _ = prepared(tmp_path)
    path = tmp_path / "publication.json"
    raw = json.loads(path.read_text())
    raw["selection"]["records"] = []
    raw["diagnostic"] = {
        "discovery": {"candidates": [{"wallet_id": "stale-wallet", "state": "DISCOVERED"}]}
    }
    raw["financial_session"]["sources"] = [{"source": "native", "age_seconds": 1.25}]
    raw["financial_session"]["economics"]["fees"] = 1.01
    path.write_text(json.dumps(raw))
    assert call(app, PREFIX + "/records?kind=wallet")[2]["total"] == 0
    system = call(app, PREFIX + "/workspace?panel=system")[2]
    source = next(
        t
        for section in system["sections"]
        for t in section["tables"]
        if t["title"] == "Source health"
    )
    assert source["rows"][0][4] == "1.25"
    evaluation = call(app, PREFIX + "/workspace?panel=evaluate")[2]
    economics = next(
        section
        for section in evaluation["sections"]
        if section["title"] == "Actual trading economics"
    )
    assert next(fact for fact in economics["facts"] if fact["label"] == "fees")["value"] is None
