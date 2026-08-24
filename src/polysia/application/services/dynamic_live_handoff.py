from __future__ import annotations

import hashlib
import json
import os
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

from polysia.application.ports.dynamic_shadow import (
    DynamicShadowStorePort,
    DynamicShadowWalletResult,
    ProtectedShadowCandidate,
)
from polysia.domain.copytrading.dynamic_shadow import DynamicShadowMode
from polysia.domain.copytrading.live_experiment import (
    EXPECTED_CANDIDATE_COUNT,
    load_candidate_bank,
)

HANDOFF_POLICY_VERSION = "dynamic-live-handoff-v0.1"


class DynamicLiveHandoffError(RuntimeError):
    def __init__(self, error_code: str, message: str) -> None:
        super().__init__(message)
        self.error_code = error_code


@dataclass(frozen=True, slots=True)
class DynamicLiveHandoffConfig:
    candidate_count: int = EXPECTED_CANDIDATE_COUNT
    minimum_simulated_events: int = 1
    maximum_unknown_ratio: Decimal = Decimal("0.50")
    maximum_historical_age: timedelta = timedelta(days=8)

    def __post_init__(self) -> None:
        if self.candidate_count != EXPECTED_CANDIDATE_COUNT:
            raise ValueError("the bounded Tiny Live Copy contract requires exactly 102 candidates")
        if self.minimum_simulated_events < 1:
            raise ValueError("minimum_simulated_events must be positive")
        if not Decimal("0") <= self.maximum_unknown_ratio <= Decimal("1"):
            raise ValueError("maximum_unknown_ratio must be within [0, 1]")
        if self.maximum_historical_age <= timedelta(0):
            raise ValueError("maximum_historical_age must be positive")


@dataclass(frozen=True, slots=True)
class DynamicLiveHandoffOutcome:
    source_id: str
    selection_run_id: str
    historical_run_id: str
    candidate_count: int
    qualified_count: int
    alpha_count: int
    stress_count: int
    overlap_count: int
    source_digest: str
    policy_version: str
    shadow_policy_version: str
    cost_model_version: str
    generated_at: datetime
    candidate_file: Path
    manifest_file: Path

    def to_dict(self) -> dict[str, object]:
        return {
            "alpha_count": self.alpha_count,
            "candidate_count": self.candidate_count,
            "candidate_file": str(self.candidate_file),
            "cost_model_version": self.cost_model_version,
            "generated_at": self.generated_at.isoformat(),
            "historical_run_id": self.historical_run_id,
            "manifest_file": str(self.manifest_file),
            "operation_scope": "DATA_ONLY_PRELIVE_HANDOFF",
            "overlap_count": self.overlap_count,
            "policy_version": self.policy_version,
            "qualified_count": self.qualified_count,
            "selection_run_id": self.selection_run_id,
            "shadow_policy_version": self.shadow_policy_version,
            "source_digest": self.source_digest,
            "source_id": self.source_id,
            "status": "succeeded",
            "stress_count": self.stress_count,
            "values_redacted": True,
        }


class DynamicLiveHandoffService:
    """Publish a protected, evidence-backed input for a later bounded dry-run.

    This service has no strategy, Risk, Execution, signer, or venue dependency. It
    only prepares the existing fail-closed Tiny Live Copy input while Live remains
    separately gated by its run-specific authorization contract.
    """

    def __init__(
        self,
        store: DynamicShadowStorePort,
        *,
        config: DynamicLiveHandoffConfig | None = None,
    ) -> None:
        self._store = store
        self._config = config or DynamicLiveHandoffConfig()

    def prepare(
        self,
        source_id: str,
        *,
        candidate_file: Path,
        manifest_dir: Path,
        now: datetime | None = None,
    ) -> DynamicLiveHandoffOutcome:
        observed_at = now or datetime.now(UTC)
        _require_utc(observed_at)
        self._store.initialize()
        selection_run_id, candidates = self._store.current_candidates(source_id)
        historical_run = self._store.current_run(
            source_id,
            mode=DynamicShadowMode.HISTORICAL,
        )
        if historical_run is None or historical_run.completed_at is None:
            raise DynamicLiveHandoffError(
                "historical_shadow_unavailable",
                "A successful historical Dynamic Shadow run is required.",
            )
        if historical_run.selection_run_id != selection_run_id:
            raise DynamicLiveHandoffError(
                "selection_shadow_mismatch",
                "Historical Shadow evidence does not match the current Stage 3 selection.",
            )
        if historical_run.completed_at > observed_at:
            raise DynamicLiveHandoffError(
                "historical_shadow_from_future",
                "Historical Shadow evidence is ahead of the current UTC clock.",
            )
        if observed_at - historical_run.completed_at > self._config.maximum_historical_age:
            raise DynamicLiveHandoffError(
                "historical_shadow_stale",
                "Historical Shadow evidence is too old for a pre-Live handoff.",
            )
        results = self._store.current_wallet_results(
            source_id,
            mode=DynamicShadowMode.HISTORICAL,
            limit=100_000,
        )
        if (
            any(item.run_id != historical_run.run_id for item in results)
            or len({item.wallet_id for item in results}) != len(results)
        ):
            raise DynamicLiveHandoffError(
                "historical_shadow_inconsistent",
                "Historical Shadow wallet evidence is internally inconsistent.",
            )
        candidate_by_wallet = {item.wallet_id: item for item in candidates}
        qualified = [
            (candidate_by_wallet[item.wallet_id], item)
            for item in results
            if item.wallet_id in candidate_by_wallet and self._qualifies(item)
        ]
        qualified.sort(key=_candidate_sort_key)
        if len(qualified) < self._config.candidate_count:
            raise DynamicLiveHandoffError(
                "insufficient_shadow_evidence",
                "Too few current candidates have successful historical copyability evidence.",
            )
        selected = qualified[: self._config.candidate_count]
        protected_text = "".join(f"{candidate.address}\n" for candidate, _ in selected)
        bank = load_candidate_bank(protected_text)
        digest = bank.source_digest.removeprefix("sha256:")
        manifest_path = manifest_dir / f"candidate-bank-{digest}.json"
        versioned_path = manifest_dir / f"candidate-bank-{digest}.txt"
        alpha_count = sum("SHADOW_ALPHA" in candidate.pools for candidate, _ in selected)
        stress_count = sum("SHADOW_STRESS" in candidate.pools for candidate, _ in selected)
        overlap_count = sum(
            "SHADOW_ALPHA" in candidate.pools and "SHADOW_STRESS" in candidate.pools
            for candidate, _ in selected
        )
        manifest = {
            "alpha_count": alpha_count,
            "candidate_count": len(selected),
            "cost_model_version": historical_run.cost_model_version,
            "historical_completed_at": historical_run.completed_at.isoformat(),
            "historical_run_id": historical_run.run_id,
            "minimum_simulated_events": self._config.minimum_simulated_events,
            "maximum_unknown_ratio": format(self._config.maximum_unknown_ratio, "f"),
            "operation_scope": "DATA_ONLY_PRELIVE_HANDOFF",
            "overlap_count": overlap_count,
            "policy_version": HANDOFF_POLICY_VERSION,
            "qualified_count": len(qualified),
            "selection_run_id": selection_run_id,
            "shadow_policy_version": historical_run.policy_version,
            "source_digest": bank.source_digest,
            "source_id": source_id,
            "stress_count": stress_count,
            "values_redacted": True,
            "wallet_set_digest": _wallet_set_digest(selected),
        }
        try:
            _publish_protected_bank(
                candidate_file=candidate_file,
                versioned_file=versioned_path,
                manifest_file=manifest_path,
                protected_text=protected_text,
                manifest=manifest,
            )
        except OSError as error:
            raise DynamicLiveHandoffError(
                "handoff_publication_failed",
                "Protected handoff publication failed safely.",
            ) from error
        return DynamicLiveHandoffOutcome(
            source_id=source_id,
            selection_run_id=selection_run_id,
            historical_run_id=historical_run.run_id,
            candidate_count=len(selected),
            qualified_count=len(qualified),
            alpha_count=alpha_count,
            stress_count=stress_count,
            overlap_count=overlap_count,
            source_digest=bank.source_digest,
            policy_version=HANDOFF_POLICY_VERSION,
            shadow_policy_version=historical_run.policy_version,
            cost_model_version=historical_run.cost_model_version,
            generated_at=observed_at,
            candidate_file=candidate_file,
            manifest_file=manifest_path,
        )

    def _qualifies(self, item: DynamicShadowWalletResult) -> bool:
        if (
            item.event_count < 1
            or item.simulated_count < self._config.minimum_simulated_events
            or item.rejected_count != 0
        ):
            return False
        return (
            Decimal(item.unknown_count) / Decimal(item.event_count)
            <= self._config.maximum_unknown_ratio
        )


def _candidate_sort_key(
    item: tuple[ProtectedShadowCandidate, DynamicShadowWalletResult],
) -> tuple[object, ...]:
    candidate, result = item
    unknown_ratio = Decimal(result.unknown_count) / Decimal(result.event_count)
    return (
        0 if "SHADOW_ALPHA" in candidate.pools else 1,
        -result.simulated_count,
        unknown_ratio,
        -result.realized_pnl,
        candidate.alpha_rank if candidate.alpha_rank is not None else 2_147_483_647,
        candidate.stress_rank if candidate.stress_rank is not None else 2_147_483_647,
        candidate.wallet_id,
    )


def _wallet_set_digest(
    selected: list[tuple[ProtectedShadowCandidate, DynamicShadowWalletResult]],
) -> str:
    payload = "\n".join(candidate.wallet_id for candidate, _ in selected).encode()
    return f"sha256:{hashlib.sha256(payload).hexdigest()}"


def _publish_protected_bank(
    *,
    candidate_file: Path,
    versioned_file: Path,
    manifest_file: Path,
    protected_text: str,
    manifest: dict[str, object],
) -> None:
    candidate_file.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    versioned_file.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    _restrict_directory(candidate_file.parent)
    _restrict_directory(versioned_file.parent)
    _write_immutable(versioned_file, protected_text)
    _write_immutable(
        manifest_file,
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
    )
    temporary_link = candidate_file.with_name(
        f".{candidate_file.name}.{uuid.uuid4().hex}.tmp"
    )
    try:
        os.link(versioned_file, temporary_link)
        os.replace(temporary_link, candidate_file)
        _restrict_file(candidate_file)
    finally:
        temporary_link.unlink(missing_ok=True)


def _write_immutable(path: Path, content: str) -> None:
    if path.exists():
        if path.read_text(encoding="utf-8") != content:
            raise DynamicLiveHandoffError(
                "handoff_digest_collision",
                "A versioned handoff artifact conflicts with existing evidence.",
            )
        _restrict_file(path)
        return
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        _restrict_file(path)
    finally:
        temporary.unlink(missing_ok=True)


def _restrict_directory(path: Path) -> None:
    if os.name != "nt":
        path.chmod(0o700)


def _restrict_file(path: Path) -> None:
    if os.name != "nt":
        path.chmod(0o600)


def _require_utc(value: datetime) -> None:
    if value.tzinfo is None or value.utcoffset() != timedelta(0):
        raise ValueError("now must be timezone-aware UTC")


__all__ = [
    "DynamicLiveHandoffConfig",
    "DynamicLiveHandoffError",
    "DynamicLiveHandoffOutcome",
    "DynamicLiveHandoffService",
    "HANDOFF_POLICY_VERSION",
]
