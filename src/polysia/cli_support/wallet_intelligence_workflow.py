"""Finite operations composition of the producer CLI and existing research intake."""

from __future__ import annotations

import importlib
import json
import os
import re
import subprocess
import uuid
from collections import Counter
from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from polysia.adapters.wallet_intelligence import (
    MAX_ARTIFACT_BYTES,
    WalletIntelligenceArtifactSource,
)
from polysia.application.ports.wallet_intelligence_research import ResearchPublicationError
from polysia.application.services.wallet_intelligence_research import (
    WalletIntelligenceResearchService,
)
from polysia.cli_support.wallet_intelligence_research import report_payload, write_report


@dataclass(frozen=True)
class WorkflowPaths:
    producer_dir: Path
    executable: Path
    config: Path
    data_root: Path
    output_root: Path


Runner = Callable[[Sequence[str], Path, int], subprocess.CompletedProcess[str]]


def run_command(
    command: Sequence[str], cwd: Path, timeout: int
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=cwd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=timeout,
        check=False,
    )


@contextmanager
def workflow_lock(path: Path) -> Iterator[None]:
    """Nonblocking OS lock: crashes release ownership; never steal or unlink it."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+b") as handle:
        if path.stat().st_size == 0:
            handle.write(b"0")
            handle.flush()
        handle.seek(0)
        module = importlib.import_module("msvcrt" if os.name == "nt" else "fcntl")
        try:
            if os.name == "nt":
                module.locking(handle.fileno(), module.LK_NBLCK, 1)
            else:
                module.flock(handle, module.LOCK_EX | module.LOCK_NB)
        except OSError as exc:
            raise ResearchPublicationError("workflow_already_running") from exc
        try:
            yield
        finally:
            handle.seek(0)
            if os.name == "nt":
                module.locking(handle.fileno(), module.LK_UNLCK, 1)
            else:
                module.flock(handle, module.LOCK_UN)


def _producer_command(paths: WorkflowPaths, *args: str) -> list[str]:
    return [
        str(paths.executable),
        "--config",
        str(paths.config),
        "--root",
        str(paths.data_root),
        *args,
    ]


def _freeze_snapshot(paths: WorkflowPaths, announcement: dict[str, Any], destination: Path) -> None:
    run_id = announcement["run_id"]
    if not isinstance(run_id, str) or not re.fullmatch(r"[a-f0-9]{32}", run_id):
        raise ResearchPublicationError("invalid_producer_run_id")
    expected = paths.data_root / "snapshots" / run_id / "wallet-intelligence.json"
    if Path(announcement["artifact"]).resolve() != expected.resolve():
        raise ResearchPublicationError("unexpected_producer_snapshot_path")
    with expected.open("rb") as handle:
        raw = handle.read(MAX_ARTIFACT_BYTES + 1)
    if len(raw) > MAX_ARTIFACT_BYTES:
        raise ResearchPublicationError("artifact_size_limit")
    destination.write_bytes(raw)
    publication = WalletIntelligenceArtifactSource(destination).read_publication()
    if (publication.run_id, publication.snapshot_digest) != (
        run_id,
        announcement["snapshot_digest"],
    ):
        raise ResearchPublicationError("producer_snapshot_identity_mismatch")


def execute_workflow(
    paths: WorkflowPaths,
    *,
    force: bool = False,
    allow_partial: bool = False,
    render_view: bool = True,
    runner: Runner = run_command,
    clock: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> dict[str, Any]:
    """Pin one announced snapshot, render it optionally, and assess it at current UTC."""
    with workflow_lock(paths.output_root / "workflow.lock"):
        attempt = paths.output_root / "runs" / uuid.uuid4().hex
        attempt.mkdir(parents=True)
        current = paths.output_root / "current.json"
        result: dict[str, Any] = {
            "schema_version": "wallet-intelligence-local-workflow/v1",
            "status": "IN_PROGRESS",
            "started_at": clock().isoformat(),
            "attempt": str(attempt),
            "warnings": [],
            "provider_resources": "UNKNOWN",
        }
        write_report(current, result)
        try:
            args = ["run", "--no-render", *([] if force else ["--if-due"])]
            produced = runner(_producer_command(paths, *args), paths.producer_dir, 930)
            (attempt / "producer-stdout.json").write_text(produced.stdout, encoding="utf-8")
            (attempt / "producer-stderr.txt").write_text(produced.stderr, encoding="utf-8")
            if produced.returncode:
                try:
                    result["provider_resources"] = json.loads(produced.stderr).get(
                        "invocation_resources", "UNKNOWN"
                    )
                except ValueError, AttributeError:
                    result["provider_resources"] = "UNKNOWN"
                raise ResearchPublicationError("producer_failed")
            announcement = json.loads(produced.stdout)
            result["provider_resources"] = announcement["invocation_resources"]
            result["refresh_action"] = announcement["refresh_action"]
            artifact = attempt / "wallet-intelligence.json"
            _freeze_snapshot(paths, announcement, artifact)
            result.update(
                run_id=announcement["run_id"],
                snapshot_digest=announcement["snapshot_digest"],
                artifact=str(artifact),
                human_view=None,
                consumer_report=None,
            )
            if render_view:
                view = attempt / "human-view.html"
                try:
                    rendered = runner(
                        _producer_command(paths, "render", str(artifact), str(view)),
                        paths.producer_dir,
                        30,
                    )
                    if rendered.returncode or not view.is_file():
                        raise ResearchPublicationError("renderer_failed")
                    # The renderer's inert JSON proves this view belongs to the selected snapshot.
                    match = re.search(
                        r'<script id="artifact" type="application/json">(.*?)</script>',
                        view.read_text(encoding="utf-8"),
                        re.DOTALL,
                    )
                    embedded = json.loads(match.group(1)) if match else {}
                    if (embedded.get("run_id"), embedded.get("snapshot_digest")) != (
                        result["run_id"],
                        result["snapshot_digest"],
                    ):
                        raise ResearchPublicationError("renderer_snapshot_mismatch")
                    result["human_view"] = str(view)
                except OSError, ValueError, ResearchPublicationError, subprocess.TimeoutExpired:
                    result["warnings"].append(
                        "Human View unavailable; machine publication remains usable"
                    )
            report = WalletIntelligenceResearchService(
                WalletIntelligenceArtifactSource(artifact),
                clock=clock,
            ).intake(allow_partial=allow_partial)
            if (report.publication.run_id, report.publication.snapshot_digest) != (
                result["run_id"],
                result["snapshot_digest"],
            ):
                raise ResearchPublicationError("intake_snapshot_identity_mismatch")
            payload: Any = report_payload(report)
            output = attempt / "research-intake.json"
            # A rejected report remains diagnostic, separate from earlier accepted reports.
            write_report(output, payload)
            result.update(
                status=report.status,
                assessed_at=report.assessed_at.isoformat(),
                expires_at=report.publication.expires_at.isoformat(),
                data_cutoff=report.publication.data_cutoff.isoformat(),
                producer_status=report.publication.status,
                examined=len(report.publication.records),
                candidates=len(payload["producer_candidate_refs"]),
                counts=payload["counts"],
                consumer_report=str(output),
                reasons=payload["reasons"],
                freshness=(
                    "EXPIRED"
                    if "publication_expired" in report.reasons
                    else "FUTURE"
                    if "publication_from_future" in report.reasons
                    else "FRESH"
                ),
            )
            reasons = Counter(
                reason
                for row in payload["rows"]
                if row["research_disposition"] == "REJECTED"
                for reason in row["research_reasons"]
            )
            result["principal_rejection_reasons"] = dict(reasons.most_common(3))
        except (
            ResearchPublicationError,
            OSError,
            ValueError,
            KeyError,
            TypeError,
            subprocess.TimeoutExpired,
        ) as exc:
            result.update(
                status="FAILED",
                error_code=(
                    exc.code
                    if isinstance(exc, ResearchPublicationError)
                    else "workflow_command_or_artifact_failed"
                ),
            )
        result["completed_at"] = clock().isoformat()
        write_report(attempt / "workflow.json", result)
        write_report(current, result)
        return result


def human_summary(result: dict[str, Any]) -> str:
    lines = [
        f"Wallet Intelligence: {result['status']} ({result.get('refresh_action', 'UNAVAILABLE')})"
    ]
    if "counts" in result:
        counts = result["counts"]
        lines.append(
            f"Examined {result['examined']}; candidates {result['candidates']}; "
            f"accepted {counts['ACCEPTED']}; watchlist {counts['WATCHLIST']}; "
            f"rejected {counts['REJECTED']}"
        )
        lines.append(
            f"Freshness {result['freshness']}; source {result['producer_status']}; "
            f"cutoff {result['data_cutoff']}; "
            f"expires {result['expires_at']}"
        )
    reasons = result.get("reasons") or result.get("principal_rejection_reasons")
    if reasons:
        lines.append("Rejection reasons: " + ", ".join(reasons))
    if "error_code" in result:
        lines.append("Failure: " + result["error_code"] + "; earlier reports are not this result")
    for warning in result["warnings"]:
        lines.append("Warning: " + warning)
    for label, key in (
        ("Artifact", "artifact"),
        ("Human View", "human_view"),
        ("Research report", "consumer_report"),
    ):
        lines.append(f"{label}: {result.get(key) or 'UNAVAILABLE'}")
    lines.append("Research only; copyability and trading admission remain unavailable.")
    return "\n".join(lines)
