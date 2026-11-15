"""Offline receipt workflow regression coverage; never uses an owner key or network."""

from __future__ import annotations

import base64
import copy
import hashlib
import io
import json
from dataclasses import asdict, replace
from datetime import datetime, timedelta
from decimal import Decimal as D
from pathlib import Path

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from polysia.deployment.financial_session_runtime import capacity_workload
from polysia.domain.copytrading.copy_policy import CopyPolicy
from polysia.domain.financial_session import AccountObservation, SessionBlocked, canonical_json
from polysia.security.session_authority import SessionReceiptVerifier
from scripts import op1_bounded_read as bounded
from scripts import op1_owner_commission as owner
from scripts import op1_packet_host as host
from tests.integration.test_financial_session import NOW, authorization
from tests.integration.test_operational_session import runtime_config


@pytest.fixture
def packet(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    import socket

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return NOW

    monkeypatch.setattr(host, "datetime", Clock)
    monkeypatch.setattr(socket, "gethostname", lambda: "Hetzner-Finland-Helsinki-01")
    monkeypatch.setattr(host, "BASE", tmp_path)
    monkeypatch.setattr(host, "TEMPLATE", tmp_path / "read-config.json")
    config = runtime_config(tmp_path)
    policy = CopyPolicy(
        "op1-owner-api/v1",
        "FIXED_DEBIT",
        D("2.50"),
        D(1),
        "HYBRID",
        net_take_profit=D("0.01"),
        stop_loss=D("0.10"),
        maximum_holding_seconds=120,
        reentry=False,
    )
    opening = AccountObservation(
        config.account_mapping.account_id,
        NOW,
        D("10.213845"),
        (),
        (),
        D(0),
        True,
        "fixture-only",
        scope="ORDER_LIFECYCLE_API",
    )
    config = replace(
        config,
        policy=policy,
        opening=opening,
        account_mapping=replace(config.account_mapping, signature_type=3),
        maximum_pages=1,
        maximum_response_bytes=65536,
        maximum_queued=1,
        request_timeout_seconds=15,
        tick_interval_seconds=10,
        source_wallets=(),
        rpc_url="",
        cohort_path=None,
        follower_samples_path=None,
        cohort_file_digest="",
        follower_samples_file_digest="",
        maximum_order_shares=D(5),
        per_action_requests=(
            ("ACCOUNT", 13),
            ("SUBMIT", 16),
            ("CANCEL", 3),
            ("CANCELLATION_READ", 13),
            ("SOURCE", 1),
            ("MARKET", 2),
        ),
    )
    inert = authorization(
        version=2,
        owner_receipt="UNISSUED",
        granted=False,
        wallets=frozenset({"owner-test"}),
        strategy=policy.version,
        exit_policy=policy.version,
        fee_rate=D(0),
        max_attempts=4,
        max_requests=1000,
        max_response_bytes=64 * 1024 * 1024,
        max_storage_bytes=128 * 1024 * 1024,
        max_order_all_in=D("2.675"),
        max_total_loss=D("2.675"),
        max_daily_loss=D("2.675"),
        max_open_exposure=D("2.50"),
        max_concurrent_orders=1,
        max_holding_seconds=120,
        protective_request_reserve=200,
        protective_attempt_reserve=3,
        protective_turnover_reserve=D("2.675"),
        protective_byte_reserve=200 * 65536,
        protective_storage_reserve=2 * 200 * 65536 + 262144,
        protective_order_reserve=0,
    )
    (tmp_path / "authority-inert.json").write_text(canonical_json(asdict(inert)))
    capacity = {
        "version": "financial-session-capacity/v1",
        "workload_digest": capacity_workload(config),
        "host": config.host,
        "synthetic": False,
        "status": "PASS",
        "samples": 1,
        "observed_at": NOW.isoformat(),
        "expires_at": (NOW + timedelta(hours=1)).isoformat(),
    }
    receipt = {
        "status": "API_ACCOUNT_OBSERVED",
        "scoped_opening": asdict(opening),
        "account_mapping": asdict(config.account_mapping),
        "candidate": {
            "technically_eligible_at_observation": True,
            "best_ask": "0.08",
            "instrument": asdict(inert.instruments[0]),
        },
        "capacity_qualification": capacity,
        "aggregate_campaign": {
            "requests_charged": 27,
            "bytes_charged": 320000,
            "absolute_deadline": (NOW + timedelta(hours=2)).isoformat(),
        },
    }
    root = tmp_path / "owner-packet-r2-fixture-only"
    root.mkdir()
    built, authority, message = host.build_packet(config, receipt, root)
    config_body = {
        key: str(value) if isinstance(value, Path) else value
        for key, value in asdict(built).items()
    }
    review = json.loads(
        canonical_json(
            {
                "config": config_body,
                "message": base64.b64encode(message).decode(),
                "review_deadline": NOW + timedelta(seconds=25),
                "read_consumption": receipt["aggregate_campaign"],
            }
        )
    )
    profile = {
        "release": built.release,
        "package_tree_digest": built.package_tree_digest,
        "account_mapping": asdict(built.account_mapping),
        "instrument": asdict(authority.instruments[0]),
        "config_invariants": owner.invariants(review["config"], owner.CONFIG_VARIABLE_FIELDS),
        "authority_invariants": owner.invariants(
            json.loads(message)["authorization"], owner.AUTHORITY_VARIABLE_FIELDS
        ),
    }
    return built, authority, message, review, profile, config, receipt


def test_external_receipt_preserves_consumption_and_STOP(packet):
    config, authority, message, review, profile, *_ = packet
    assert authority.max_requests == 941
    assert authority.max_response_bytes == 64 * 1024 * 1024 - 846858 - 320000
    assert owner.validate_review(review, profile, now=NOW) == message
    assert owner.config_digest(review["config"]) == config.fingerprint
    assert not config.financial_path.exists()
    assert not config.custody_path.exists()
    key = Ed25519PrivateKey.generate()  # Isolated fixture, never installed as a real issuer.
    signed = replace(
        authority,
        owner_receipt=canonical_json(
            {
                "key_id": owner.KEY_ID,
                "receipt_id": authority.run_id,
                "signature": base64.b64encode(key.sign(message)).decode(),
            }
        ),
    )
    verifier = SessionReceiptVerifier({owner.KEY_ID: key.public_key().public_bytes_raw()})
    assert verifier.verify(signed, signed.binding, now=NOW).receipt_id == authority.run_id
    with pytest.raises(SessionBlocked, match="untrusted"):
        verifier.verify_signature(replace(signed, max_attempts=5))


@pytest.mark.parametrize(
    "change", ["issuer", "receipt", "attempts", "loss", "fees", "budget", "window"]
)
def test_owner_refuses_modified_scope_even_with_canonical_message(packet, change):
    _, _, _, review, profile, *_ = packet
    review = copy.deepcopy(review)
    body = json.loads(base64.b64decode(review["message"]))
    auth = body["authorization"]
    if change == "issuer":
        body["key_id"] = "another-issuer"
    if change == "receipt":
        body["receipt_id"] = "another-receipt"
    if change == "attempts":
        auth["max_attempts"] = 5
    if change == "loss":
        auth["max_total_loss"] = "2.676"
    if change == "fees":
        auth["fee_rate"] = "0.01"
    if change == "budget":
        auth["max_requests"] = 1000
    if change == "window":
        auth["expires_at"] = (NOW + timedelta(hours=1)).isoformat()
    review["message"] = base64.b64encode(owner.canonical(body)).decode()
    with pytest.raises(ValueError):
        owner.validate_review(review, profile, now=NOW)


def test_owner_refuses_stale_or_changed_config(packet):
    _, _, _, review, profile, *_ = packet
    with pytest.raises(ValueError, match="fresh_review"):
        owner.validate_review(review, profile, now=NOW + timedelta(seconds=25))
    review = copy.deepcopy(review)
    review["config"]["exact_entry"]["shares"] = "6"
    with pytest.raises(ValueError, match="binding"):
        owner.validate_review(review, profile, now=NOW)


def test_owner_refuses_changed_risk_even_with_recomputed_binding(packet):
    _, _, _, review, profile, *_ = packet
    review = copy.deepcopy(review)
    review["config"]["risk_limits"]["max_order_notional"] = "100"
    body = json.loads(base64.b64decode(review["message"]))
    body["authorization"]["binding"]["configuration"] = owner.config_digest(review["config"])
    review["message"] = base64.b64encode(owner.canonical(body)).decode()
    with pytest.raises(ValueError, match="binding"):
        owner.validate_review(review, profile, now=NOW)


def test_read_grant_retains_counts_and_original_absolute_deadline():
    grant = {
        "scope": "GET_ONLY",
        "maximum_requests": 100,
        "maximum_bytes": 12 * 1024 * 1024,
        "starts_at": NOW.isoformat(),
    }
    continuation = {"requests_charged": 14, "bytes_charged": 305378}
    values = bounded.read_bounds(grant, continuation, now=NOW + timedelta(hours=1, minutes=59))
    assert values[:2] == (14, 305378)
    assert values[2] == NOW
    assert values[3] == NOW + timedelta(hours=2)
    assert values[4:] == (100, 12 * 1024 * 1024)
    with pytest.raises(ValueError):
        bounded.read_bounds(grant, continuation, now=NOW + timedelta(hours=2))
    with pytest.raises(ValueError):
        bounded.read_bounds(grant, {"requests_charged": 100, "bytes_charged": 305378}, now=NOW)
    with pytest.raises(ValueError):
        bounded.read_bounds({**grant, "maximum_requests": 101}, continuation, now=NOW)


def test_manual_owner_workflow_transports_only_receipt_signature(packet, tmp_path, monkeypatch):
    import dotenv
    from cryptography.hazmat.primitives import serialization

    _, _, message, review, profile, *_ = packet
    key = Ed25519PrivateKey.generate()
    public = key.public_key().public_bytes_raw()
    issuer = tmp_path / "Documents/PolySia-Owner"
    issuer.mkdir(parents=True)
    password = b"fixture-only-passphrase"
    (issuer / "op1-owner-v1.encrypted.pem").write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.BestAvailableEncryption(password),
        )
    )
    (issuer / "op1-owner-v1.public.b64").write_bytes(base64.b64encode(public))
    profile = {
        **profile,
        "owner_public_sha256": hashlib.sha256(public).hexdigest(),
        "helper_sha256": ["host-helper-sha", "read-helper-sha"],
    }
    path = tmp_path / "profile.json"
    path.write_text(json.dumps(profile))

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return NOW

    class Pipe(io.StringIO):
        saved = ""

        def close(self):
            self.saved = self.getvalue()
            super().close()

    class Process:
        stdin = Pipe()
        stdout = io.StringIO(
            json.dumps({"stage": "REVIEW", **review})
            + "\n"
            + json.dumps({"stage": "PROVISIONED_STOPPED", "root": "fixture-only"})
            + "\n"
        )

        def poll(self):
            return 0

        def wait(self, timeout):
            return 0

    uploads = []
    monkeypatch.setattr(owner, "datetime", Clock)
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.setattr(owner.sys, "argv", ["op1_owner_commission", "--profile", str(path)])
    monkeypatch.setattr(owner.sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr(owner.getpass, "getpass", lambda _: password.decode())
    monkeypatch.setattr("builtins.input", lambda _: "SIGN")
    monkeypatch.setattr(
        dotenv,
        "dotenv_values",
        lambda _: dict(
            POLYMARKET_PRIVATE_KEY="fixture-wallet-credential",
            POLYMARKET_FUNDER_ADDRESS=profile["account_mapping"]["funder"],
            POLYMARKET_SIGNATURE_TYPE="3",
        ),
    )
    monkeypatch.setattr(
        owner.subprocess,
        "check_output",
        lambda *a, **kw: "host-helper-sha file1\nread-helper-sha file2\n",
    )
    monkeypatch.setattr(owner.subprocess, "Popen", lambda *a, **kw: Process())
    monkeypatch.setattr(owner.subprocess, "run", lambda *a, **kw: uploads.append(kw["input"]))
    owner.main()
    assert len(uploads) == 1
    key.public_key().verify(base64.b64decode(uploads[0]), message)
    assert password.decode() not in Process.stdin.saved
    assert "ENCRYPTED PRIVATE KEY" not in Process.stdin.saved
    assert "fixture-wallet-credential" in Process.stdin.saved


def test_authorization_files_cannot_be_overwritten(tmp_path):
    path = tmp_path / "signature.bin"
    host.write_new(path, b"first")
    with pytest.raises(FileExistsError):
        host.write_new(path, b"replay")
    assert path.read_bytes() == b"first"


@pytest.mark.parametrize("change", ["account", "price", "stale", "capacity"])
def test_builder_rejects_unusable_evidence_without_consuming_custody(packet, tmp_path, change):
    *_, template, receipt = packet
    receipt = copy.deepcopy(receipt)
    if change == "account":
        receipt["account_mapping"]["funder"] = "another-account"
    if change == "price":
        receipt["candidate"]["best_ask"] = "0.09"
    if change == "stale":
        receipt["scoped_opening"]["observed_at"] = NOW - timedelta(seconds=31)
    if change == "capacity":
        receipt["capacity_qualification"]["status"] = "BLOCKED"
    root = tmp_path / ("rejected-" + change)
    root.mkdir()
    with pytest.raises((ValueError, SessionBlocked)):
        host.build_packet(template, receipt, root)
    assert not (tmp_path / "control/custody.sqlite3").exists()
