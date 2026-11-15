"""Interactive local owner approval; only --start requests the bounded real test."""

from __future__ import annotations

import argparse
import base64
import copy
import getpass
import hashlib
import json
import shlex
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

KEY_ID = "op1-owner-v1"
HOST_SCRIPT = "/etc/polysia-op1/op1_packet_host.py"
SSH = [
    "ssh",
    "-oBatchMode=yes",
    "-oStrictHostKeyChecking=yes",
    "-oHostKeyAlgorithms=ssh-ed25519",
    "-oConnectTimeout=8",
    "-oServerAliveInterval=5",
    "-oServerAliveCountMax=3",
    "Hetzner-Finland-Helsinki-01",
]

CONFIG_VARIABLE_FIELDS = frozenset(
    {
        "opening",
        "financial_path",
        "witness_root",
        "custody_path",
        "outbox_path",
        "incident_path",
        "publication_path",
        "commands_path",
        "capacity_evidence_path",
        "capacity_evidence_digest",
        "exact_entry",
    }
)
AUTHORITY_VARIABLE_FIELDS = frozenset(
    {
        "run_id",
        "owner_receipt",
        "granted",
        "binding",
        "starts_at",
        "expires_at",
        "protective_until",
        "max_requests",
        "max_response_bytes",
    }
)


def invariants(value: dict[str, Any], variable: frozenset[str]) -> dict[str, Any]:
    return {key: item for key, item in value.items() if key not in variable}


def canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def config_digest(config: dict[str, Any]) -> str:
    """Keep remote POSIX paths opaque on Windows; mirror the contract fingerprint."""
    value = copy.deepcopy(config)
    if value["opening"]["scope"] == "ACCOUNT":
        del value["opening"]["scope"]
    for key in (
        "historical_instruments",
        "rpc_log_block_span",
        "rpc_checkpoint_path",
        "rpc_bearer_token_reference",
    ):
        if not value.get(key):
            value.pop(key, None)
    if value.get("exact_entry") is None:
        value.pop("exact_entry", None)
    elif value["exact_entry"].get("order_expires_at") is None:
        value["exact_entry"].pop("order_expires_at", None)
    return hashlib.sha256(canonical(value)).hexdigest()


def validate_review(review: dict[str, Any], profile: dict[str, Any], *, now: datetime) -> bytes:
    message = base64.b64decode(review["message"], validate=True)
    body = json.loads(message)
    if canonical(body) != message or body["version"] != "session-owner-receipt/v1":
        raise ValueError("canonical_owner_receipt_required")
    config, authority = review["config"], body["authorization"]
    exact, opening = config["exact_entry"], config["opening"]
    at = datetime.fromisoformat(opening["observed_at"])
    ends = datetime.fromisoformat(review["review_deadline"])
    if not at <= now < ends <= at + timedelta(minutes=5):
        raise ValueError("fresh_review_window_required")
    if (
        body["key_id"] != KEY_ID
        or body["receipt_id"] != authority["run_id"]
        or "owner_receipt" in authority
    ):
        raise ValueError("external_issuer_identity_required")
    binding = authority["binding"]
    if (
        invariants(config, CONFIG_VARIABLE_FIELDS) != profile["config_invariants"]
        or invariants(authority, AUTHORITY_VARIABLE_FIELDS) != profile["authority_invariants"]
        or binding["configuration"] != config_digest(config)
        or binding["policy"] != hashlib.sha256(canonical(config["policy"])).hexdigest()
        or binding["release"] != profile["release"]
        or config["release"] != profile["release"]
        or config["package_tree_digest"] != profile["package_tree_digest"]
        or binding["host"] != "Hetzner-Finland-Helsinki-01"
        or config["account_mapping"] != profile["account_mapping"]
        or authority["instruments"] != [profile["instrument"]]
    ):
        raise ValueError("reviewed_account_instrument_release_binding_required")

    def amount(value: object) -> Decimal:
        result = Decimal(str(value))
        if not result.is_finite() or result < 0:
            raise ValueError("finite_nonnegative_amount_required")
        return result

    if (
        amount(exact["shares"]) != 5
        or not 0 < amount(exact["price_ceiling"]) <= Decimal("0.50")
        or config["account_mapping"]["signature_type"] != 3
        or opening["scope"] != "ORDER_LIFECYCLE_API"
        or opening["complete"] is not True
        or opening["positions"]
        or opening["open_order_ids"]
        or amount(opening["cumulative_fees"])
        or amount(opening["cash"]) < 5 * amount(exact["price_ceiling"])
        or authority["granted"] is not True
        or authority["version"] != 2
        or authority["wallets"] != ["owner-test"]
        or authority["max_attempts"] != 4
        or authority["max_positions"] != 1
        or authority["max_concurrent_orders"] != 1
        or amount(authority["fee_rate"]) != 0
        or amount(authority["max_source_cost"]) != 0
        or amount(authority["max_order_all_in"]) > Decimal("2.675")
        or amount(authority["max_total_loss"]) > Decimal("2.675")
        or amount(authority["max_daily_loss"]) > Decimal("2.675")
        or amount(authority["max_open_exposure"]) > Decimal("2.50")
        or config["policy"]["reentry"] is not False
        or authority["max_holding_seconds"] != 120
        or authority["protective_actions"] != ["CANCEL", "REDUCE"]
        or authority["max_evidence_age_seconds"] != 30
    ):
        raise ValueError("bounded_financial_proposal_required")
    spent = review["read_consumption"]
    if (
        not 0 < spent["requests_charged"] <= 100
        or authority["max_requests"] != 1000 - 32 - spent["requests_charged"] - 14
        or authority["max_response_bytes"]
        != 64 * 1024 * 1024 - 846858 - spent["bytes_charged"] - 14 * 65536
        or datetime.fromisoformat(authority["starts_at"]) != at
        or datetime.fromisoformat(authority["expires_at"]) != at + timedelta(minutes=20)
        or datetime.fromisoformat(authority["protective_until"]) != at + timedelta(minutes=30)
        or datetime.fromisoformat(exact["order_expires_at"]) != at + timedelta(seconds=1335)
        or datetime.fromisoformat(authority["protective_until"])
        >= datetime.fromisoformat(spent["absolute_deadline"])
    ):
        raise ValueError("finite_window_and_prior_consumption_required")
    return message


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", type=Path, required=True)
    parser.add_argument("--renew-reads", action="store_true")
    parser.add_argument("--start", action="store_true")
    args = parser.parse_args()
    if not sys.stdin.isatty():
        parser.error("Run manually in the owner terminal; redirected passphrases are forbidden.")
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from dotenv import dotenv_values

    profile = json.loads(args.profile.read_text())
    approved = profile.get("approved_helpers") or [
        HOST_SCRIPT,
        "/etc/polysia-op1/op1_bounded_read.py",
    ]
    if any(not x.startswith("/etc/polysia-op1/op1_") or not x.endswith(".py") for x in approved):
        raise ValueError("approved_operator_helper_paths_required")
    # Check installed helpers before decrypting the local external issuer.
    hashes = subprocess.check_output(
        SSH + ["sha256sum " + " ".join(shlex.quote(x) for x in approved)],
        text=True,
        timeout=20,
    )
    if [row.split()[0] for row in hashes.splitlines()] != profile["helper_sha256"]:
        raise ValueError("reviewed_host_helpers_changed")
    if args.start:
        print(
            "This OWNER action can place ONE real five-share test after all independent gates pass."
        )
        print("Confirm receipt of the existing redacted email test; no second email is sent.")
        if (
            input("Type RECEIVED only if you actually received the alert test: ").strip()
            != "RECEIVED"
        ):
            raise ValueError("human_alert_receipt_not_confirmed")
        subprocess.run(
            SSH + ["python3 " + shlex.quote(HOST_SCRIPT) + " ack-alert"],
            input="RECEIVED",
            text=True,
            check=True,
            timeout=15,
        )
    if args.renew_reads:
        print("Approve GET-only reads: at most 100 carried/new attempts within two hours.")
        if input("Type READ100 to approve those finite reads: ").strip() != "READ100":
            raise ValueError("read_renewal_not_authorized")
        subprocess.run(
            SSH + ["python3 " + shlex.quote(HOST_SCRIPT) + " renew-read"],
            input="READ100",
            text=True,
            check=True,
            timeout=45,
        )
    issuer = Path.home() / "Documents/PolySia-Owner"
    private_path = issuer / "op1-owner-v1.encrypted.pem"
    public_path = issuer / "op1-owner-v1.public.b64"
    if issuer.is_symlink() or any(p.is_symlink() for p in (private_path, public_path)):
        raise ValueError("regular_local_issuer_files_required")
    public = base64.b64decode(public_path.read_bytes().strip(), validate=True)
    if hashlib.sha256(public).hexdigest() != profile["owner_public_sha256"]:
        raise ValueError("enrolled_owner_key_required")
    print("This prepares and signs one exact authorization receipt.")
    print("Read the proposal before confirming; issuer private key remains on this laptop.")
    password = getpass.getpass("Local issuer passphrase: ").encode()
    key = serialization.load_pem_private_key(private_path.read_bytes(), password=password)
    del password
    if not isinstance(key, Ed25519PrivateKey) or key.public_key().public_bytes_raw() != public:
        raise ValueError("matching_external_owner_issuer_required")
    project = Path(__file__).resolve().parents[1]
    values = dotenv_values(project / ".env")
    secret = {
        name: values[name]
        for name in (
            "POLYMARKET_PRIVATE_KEY",
            "POLYMARKET_FUNDER_ADDRESS",
            "POLYMARKET_SIGNATURE_TYPE",
        )
    }
    if (
        secret["POLYMARKET_SIGNATURE_TYPE"] != "3"
        or str(secret["POLYMARKET_FUNDER_ADDRESS"]).lower()
        != profile["account_mapping"]["funder"].lower()
    ):
        raise ValueError("existing_designated_type_3_credentials_required")
    process = subprocess.Popen(
        SSH + ["python3 " + shlex.quote(HOST_SCRIPT) + " launch"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
    )
    assert process.stdin is not None and process.stdout is not None
    process.stdin.write(json.dumps(secret))
    process.stdin.close()
    del secret
    completed = False
    try:
        for line in process.stdout:
            event = json.loads(line)
            if event.get("stage") == "REVIEW":
                message = validate_review(event, profile, now=datetime.now(UTC))
                # An immutable, exact local copy is available for inspection.
                review_path = issuer / (
                    "op1-reviewed-" + json.loads(message)["receipt_id"] + ".json"
                )
                with review_path.open("xb") as stream:
                    stream.write(message)
                authorization = json.loads(message)["authorization"]
                price = Decimal(event["config"]["exact_entry"]["price_ceiling"])
                print(f"Five shares; limit {price} pUSD; gross at most {5 * price} pUSD; fee 0.")
                print("Total loss/debit cap 2.675 pUSD; four mutation slots; holding limit 120 s.")
                print("Entry window 20 min; protective deadline 30 min; GTD T0+1335 s.")
                print("Receipt:", review_path)
                print("Remaining run HTTP allowance:", authorization["max_requests"])
                print("Confirm before the review deadline to authorize this exact packet.")
                from datetime import timezone

                tehran = timezone(timedelta(hours=3, minutes=30))
                print(
                    "Review deadline (Tehran):",
                    datetime.fromisoformat(event["review_deadline"])
                    .astimezone(tehran)
                    .strftime("%H:%M:%S"),
                )
                confirmation = "SIGN AND START" if args.start else "SIGN"
                print("Required confirmation:", confirmation)
                if input("Confirmation: ").strip() != confirmation:
                    raise ValueError("owner_did_not_sign")
                validate_review(event, profile, now=datetime.now(UTC))
                signature = key.sign(message)
                subprocess.run(
                    SSH + ["python3 " + shlex.quote(HOST_SCRIPT) + " accept-signature"],
                    input=base64.b64encode(signature).decode(),
                    text=True,
                    check=True,
                    timeout=10,
                )
                del key
            elif event.get("stage") == "PROVISIONED_STOPPED":
                completed = True
                print("PROVISIONED_STOPPED:", event["root"])
                if args.start:
                    print("Owner start: verifying automatic offsite backups and supervision.")
                    root = event["root"]
                    if not root.startswith("/var/lib/polysia-op1/owner-packet-"):
                        raise ValueError("isolated_owner_packet_required")
                    subprocess.run(
                        SSH
                        + [
                            "python3 /etc/polysia-op1/op1_session_host.py start --profile "
                            + shlex.quote(root + "/host-run-profile.json")
                            + " --execute-owner-test"
                        ],
                        check=True,
                        timeout=1900,
                    )
                else:
                    print("No trade occurred. STOP retained; independent controls still apply.")
            elif event.get("stage") == "BLOCKED":
                print("Host result:", event.get("reason", "inspect_protected_receipt"))
                raise ValueError("host_blocked_inspect_existing_packet_do_not_repeat_blindly")
        if process.wait(timeout=20) != 0 or not completed:
            raise ValueError("outcome_requires_inspection_do_not_repeat_blindly")
    finally:
        # The remote bridge has its own finite wait and never starts a worker.
        if process.poll() is None:
            process.wait(timeout=620)


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print("Inspect the existing result before retrying; a requested start may have acted.")
        print("Failure type:", type(error).__name__)
        raise SystemExit(1) from None
