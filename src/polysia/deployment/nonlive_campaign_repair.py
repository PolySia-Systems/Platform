"""Explicit, idempotent acceptance repair under an existing stopped finite grant."""
from __future__ import annotations

import argparse
import hashlib
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from polysia.cli_commands.platform_discovery import load_policy
from polysia.cli_support.wallet_intelligence_workflow import workflow_lock
from polysia.monitoring.nonlive_campaign import (
    READINESS_MARGIN_SECONDS,
    REPAIR_RECEIPT,
    effective_plan,
    validate_repair_receipt,
)
from polysia.storage.acquisition_authority import AcquisitionAuthority
from polysia.storage.console_commands import ConsoleCommandStore
from polysia.storage.continuous_shadow import ContinuousShadowRepository


def begin_repair(config: Path, *, now: datetime) -> dict[str, Any]:
    """Never resume authority, change its policy, or erase a failed attempt."""
    from polysia.cli_commands.platform_worker import atomic_json

    value = json.loads(config.read_bytes())
    database = Path(value["database"])
    with workflow_lock(database.with_suffix(".worker.lock")):
        plan_path = Path(value["campaign"])
        if plan_path.is_symlink() or plan_path.stat().st_size > 16_384:
            raise ValueError("invalid original campaign plan")
        original = plan_path.read_bytes()
        plan = effective_plan(value, original)
        if "repair_attempt_id" not in plan:
            raise ValueError("explicit root-owned repair definition required")
        policy = load_policy(Path(value["manifest"]))
        authority = AcquisitionAuthority(Path(value["authority"]), policy)
        accounting = authority.status()
        if ConsoleCommandStore(Path(value["commands"])).pending():
            raise ValueError("repair requires a reconciled control command queue")
        if (now.utcoffset() != timedelta(0) or not policy.starts_at <= now < policy.expires_at
                or accounting["stopped"] is not True
                or accounting["policy_digest"] != plan["policy_digest"]
                or not isinstance(accounting.get("campaign"), dict)
                or accounting["uncertain_requests"] != 0
                or now + timedelta(seconds=2 * policy.window_seconds + 172800
                                   + READINESS_MARGIN_SECONDS) >= policy.expires_at):
            raise ValueError("repair requires stopped original authority and enough real time")
        active = ContinuousShadowRepository(database).active_experiment("polymarket-native")
        if (active is None or active.config.code_sha != value["release_commit"]
                or active.config.selection_preflight_digest != plan["cohort_digest"]
                or active.config.capacity_evidence != value["admission"]):
            raise ValueError("repair requires the supported retained-session source transition")
        state_path = database.with_name("nonlive-campaign-status.json")
        receipt_path = database.with_name(REPAIR_RECEIPT)
        for path in (state_path, receipt_path):
            if path.is_symlink() or path.exists() and path.stat().st_size > 16_384:
                raise ValueError("invalid retained campaign evidence")
        prior_raw = state_path.read_bytes()
        prior = json.loads(prior_raw)
        if receipt_path.exists():
            receipt = json.loads(receipt_path.read_bytes())
            validate_repair_receipt(receipt, value, plan)
            if receipt["attempt_id"] != plan["repair_attempt_id"]:
                raise ValueError("a different campaign repair is already recorded")
            if prior.get("attempt_id") == receipt["attempt_id"]:
                return receipt  # A retry cannot reset CANARY, OBSERVING, or FAILED.
            if hashlib.sha256(prior_raw).hexdigest() != receipt["prior_status_sha256"]:
                raise ValueError("interrupted repair does not match retained prior evidence")
        else:
            expected = value["campaign_repair"]["previous_status_sha256"]
            if (prior.get("phase") != "FAILED"
                    or hashlib.sha256(prior_raw).hexdigest() != expected):
                raise ValueError("repair must retain the exact failed attempt")
            receipt = {
                "contract": "nonlive-campaign-repair-receipt/v1",
                "attempt_id": plan["repair_attempt_id"], "started_at": now.isoformat(),
                "authorization_reference": value["campaign_repair"]["authorization_reference"],
                "reason": value["campaign_repair"]["reason"],
                "original_plan_sha256": hashlib.sha256(original).hexdigest(),
                "prior_status_sha256": expected, "prior_status": prior,
                "prior_status_raw": prior_raw.decode(),
                "authority_before": accounting, "financial_authority": False,
            }
            atomic_json(receipt_path, receipt)
        state = {
            "campaign_id": plan["campaign_id"], "attempt_id": receipt["attempt_id"],
            "attempt_started_at": receipt["started_at"], "phase": "PREPARING",
            "reason": "audited_readiness_repair_original_grant",
            "final_review": "REQUIRED", "financial_authority": False,
        }
        atomic_json(state_path, state)
        if authority.status() != accounting:
            authority.stop()
            raise ValueError("authority changed during repair; remain stopped")
        return receipt


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    args = parser.parse_args()
    value = json.loads(args.config.read_bytes())
    if Path("/opt/polysia/BUILD_COMMIT").read_text().strip() != value["release_commit"]:
        raise ValueError("installed repair source mismatch")
    print(json.dumps(begin_repair(args.config, now=datetime.now(UTC)), sort_keys=True))


if __name__ == "__main__":
    main()
