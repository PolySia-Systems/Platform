from __future__ import annotations

import json
import os
from pathlib import Path
from tempfile import NamedTemporaryFile

from polysia.application.services.candidate_wallet_sync import CandidateHealthReport


class WalletIntelligenceHealthReportError(RuntimeError):
    error_code = "health_report_unavailable"


def write_candidate_health_report(report: CandidateHealthReport, path: Path) -> None:
    """Atomically publish one sanitized health report without wallet identities."""
    write_wallet_intelligence_health_payload(report.to_dict(), path)


def write_wallet_intelligence_health_payload(
    report: dict[str, object],
    path: Path,
) -> None:
    """Atomically publish sanitized source and candidate-pool health."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if os.name != "nt":
        path.parent.chmod(0o700)
    payload = json.dumps(report, indent=2, sort_keys=True) + "\n"
    temporary_path: Path | None = None
    try:
        with NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as temporary:
            temporary.write(payload)
            temporary.flush()
            os.fsync(temporary.fileno())
            temporary_path = Path(temporary.name)
        if os.name != "nt":
            temporary_path.chmod(0o600)
        os.replace(temporary_path, path)
        if os.name != "nt":
            path.chmod(0o600)
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


def read_wallet_intelligence_health_payload(path: Path) -> dict[str, object]:
    """Read one sanitized atomic health artifact without opening SQLite."""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as error:
        raise WalletIntelligenceHealthReportError(
            "Operational health artifact is unavailable."
        ) from error
    except (OSError, json.JSONDecodeError, UnicodeError) as error:
        raise WalletIntelligenceHealthReportError(
            "Operational health artifact is unreadable."
        ) from error
    if not isinstance(payload, dict):
        raise WalletIntelligenceHealthReportError(
            "Operational health artifact is invalid."
        )
    return payload
