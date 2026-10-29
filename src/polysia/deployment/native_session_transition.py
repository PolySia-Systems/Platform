"""Audited non-Live release transition preserving the complete virtual session.

Run only with the supervised writer disabled and durable acquisition STOP. The
economic configuration and every event/ledger row remain untouched. Historical
opportunity bindings remain verifiable through the append-only configuration journal.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
from contextlib import closing
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from polysia.cli_support.wallet_intelligence_workflow import workflow_lock


def config_digest(value: dict[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def transition_native_session(
    database: Path,
    *,
    authority: Path,
    expected_source: str,
    target_source: str,
    admission: dict[str, Any],
    authorization_reference: str,
    now: datetime,
) -> dict[str, Any]:
    if (
        len(authorization_reference) < 8
        or now.utcoffset() is None
        or now.utcoffset() != timedelta(0)
        or any(
            len(value) != 40 or any(c not in "0123456789abcdef" for c in value)
            for value in (expected_source, target_source)
        )
    ):
        raise ValueError("explicit release transition identity required")
    if (
        admission.get("code_sha") != target_source
        or admission.get("mode") != "CONTINUOUS"
        or admission.get("contract") != "native-research-admission/v1"
        or admission.get("resource_admitted") is not True
        or type(admission.get("persisted_simulations")) is not int
        or admission["persisted_simulations"] < 1
        or datetime.fromisoformat(admission["expires_at"]) <= now
    ):
        raise ValueError("candidate needs current nonempty nonfinancial admission")
    with workflow_lock(database.with_suffix(".worker.lock")):
        identity_path = database.with_suffix(database.suffix + ".session.json")
        if identity_path.is_symlink() or identity_path.stat().st_size > 4096:
            raise ValueError("invalid retained identity; remain STOPPED")
        identity = json.loads(identity_path.read_text())
        if (identity.get("schema") != "native-financial-session/v1"
                or identity.get("code_sha") not in {expected_source, target_source}
                or identity.get("cohort_digest") != admission["cohort_digest"]):
            raise ValueError("retained identity mismatch; remain STOPPED")
        with closing(sqlite3.connect(authority.as_uri() + "?mode=ro", uri=True)) as control:
            if control.execute("SELECT stopped FROM authority").fetchone() != (1,):
                raise ValueError("durable acquisition STOP required")
        with closing(sqlite3.connect(database)) as connection, connection:
            connection.execute("BEGIN IMMEDIATE")
            if connection.execute(
                "SELECT schema_version FROM continuous_shadow_metadata"
            ).fetchall() != [(9,)]:
                raise ValueError("only verified schema v9 transition is supported")
            rows = connection.execute(
                "SELECT experiment_id,config_json FROM continuous_shadow_experiments "
                "WHERE source_id='polymarket-native' AND lifecycle IN ('RUNNING','DRAINING')"
            ).fetchall()
            if len(rows) != 1:
                raise ValueError("one retained native session required")
            experiment, raw = rows[0]
            if identity.get("experiment_id") != experiment:
                raise ValueError("retained experiment identity mismatch; remain STOPPED")
            before = json.loads(raw)
            if before.get(
                "runtime_version"
            ) != "continuous-shadow-native-research-v2" or before.get(
                "selection_preflight_digest"
            ) != admission.get("cohort_digest"):
                raise ValueError("native session/cohort transition mismatch")
            if connection.execute(
                "SELECT COUNT(*) FROM continuous_shadow_poll_runs WHERE status='running'"
            ).fetchone()[0]:
                raise ValueError("in-progress poll requires recovery before transition")
            connection.execute(
                "CREATE TABLE IF NOT EXISTS continuous_shadow_release_transitions ("
                "target_source TEXT PRIMARY KEY,experiment_id TEXT NOT NULL,"
                "old_config TEXT NOT NULL,new_config TEXT NOT NULL,"
                "old_digest TEXT NOT NULL,new_digest TEXT NOT NULL,"
                "authorization_reference TEXT NOT NULL,transitioned_at TEXT NOT NULL)"
            )
            existing = connection.execute(
                "SELECT old_config,new_config,authorization_reference FROM "
                "continuous_shadow_release_transitions WHERE target_source=?",
                (target_source,),
            ).fetchone()
            if existing:
                if (
                    before != json.loads(existing[1])
                    or before["capacity_evidence"] != admission
                    or existing[2] != authorization_reference
                    or json.loads(existing[0])["code_sha"] != expected_source
                ):
                    raise ValueError("conflicting release transition retry")
                after = before
            else:
                if before.get("code_sha") != expected_source:
                    raise ValueError("retained source differs from expected predecessor")
                after = {**before, "code_sha": target_source, "capacity_evidence": admission}
                connection.execute(
                    "INSERT INTO continuous_shadow_release_transitions VALUES(?,?,?,?,?,?,?,?)",
                    (
                        target_source,
                        experiment,
                        raw,
                        json.dumps(after, sort_keys=True),
                        config_digest(before),
                        config_digest(after),
                        authorization_reference,
                        now.isoformat(),
                    ),
                )
                connection.execute(
                    "UPDATE continuous_shadow_experiments SET config_json=? WHERE experiment_id=?",
                    (json.dumps(after, sort_keys=True), experiment),
                )
        # Recoverable second phase: an identical retry completes the sidecar if
        # interrupted after SQLite commit. The worker rejects a mismatch meanwhile.
        if (
            identity.get("experiment_id") != experiment
            or identity.get("code_sha")
            not in {
                expected_source,
                target_source,
            }
            or identity.get("cohort_digest") != admission["cohort_digest"]
        ):
            raise ValueError("retained identity mismatch; remain STOPPED")
        identity["code_sha"] = target_source
        from polysia.cli_commands.platform_worker import atomic_json

        atomic_json(identity_path, identity)
        return {
            "status": "TRANSITIONED_STOPPED",
            "experiment_id": experiment,
            "target_source": target_source,
            "config_digest": config_digest(after),
            "economic_rows_preserved": True,
            "code_rollback_requires_checkpoint": True,
        }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    for field in ("database", "authority", "admission"):
        parser.add_argument("--" + field, type=Path, required=True)
    for field in ("expected-source", "target-source", "authorization-reference"):
        parser.add_argument("--" + field, required=True)
    args = parser.parse_args()
    print(
        json.dumps(
            transition_native_session(
                args.database.resolve(),
                authority=args.authority.resolve(),
                expected_source=args.expected_source,
                target_source=args.target_source,
                admission=json.loads(args.admission.read_text()),
                authorization_reference=args.authorization_reference,
                now=datetime.now(UTC),
            )
        )
    )


if __name__ == "__main__":
    main()
