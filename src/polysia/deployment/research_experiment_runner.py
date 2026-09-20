"""Bounded, resumable research-experiment Runner.

Orchestrates existing collection, read-only analysis, and finalization.
Not a generic workflow engine and not a Live/Risk/Execution path.
"""

from __future__ import annotations

import asyncio
import inspect
import json
import os
import shutil
import sqlite3
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Protocol
from uuid import uuid4

from polysia.application.ports.research_evidence import ResearchObservationSource
from polysia.application.services.persistent_prospective_collector import (
    SERVICE_POLICY_VERSION,
    PersistentCollectorConfig,
    PersistentProspectiveCollector,
)
from polysia.backtesting.prospective_analysis import open_recorded_experiment_store
from polysia.backtesting.replay_report import (
    COMPACT_STDOUT_LIMIT,
    compact_replay_payload,
    detailed_replay_payload,
)
from polysia.config.settings import AppSettings, TradingMode
from polysia.deployment.research_experiment_bundle import finalize_research_experiment
from polysia.deployment.research_run_commands import (
    STOP_KIND,
    ResearchCommandJournal,
    ResearchRunCommandError,
)
from polysia.deployment.research_run_contract import (
    ResearchRunContractError,
    ResearchRunPlan,
    ResearchRunSpec,
    load_run_plan,
    parse_research_run_spec,
    plans_semantically_equal,
    resolve_run_plan,
    spec_from_legacy,
)
from polysia.deployment.research_run_profiles import (
    RUNNER_MANIFEST_VERSION,
    SAFETY_MARGIN_BYTES,
    RunnerProfile,
    resolve_profile,
)
from polysia.deployment.research_wallet_selection import ResearchWalletSelectionError
from polysia.domain.research_evidence.collector import COLLECTOR_POLICY_VERSION
from polysia.domain.research_evidence.economic_contract import CONTRACT_V1
from polysia.domain.research_evidence.models import RESEARCH_EVIDENCE_SCHEMA_VERSION
from polysia.domain.research_evidence.replay import REPLAY_ENGINE_VERSION
from polysia.storage.immutable_sqlite import sha256_file
from polysia.storage.research_evidence import (
    ExclusiveWriterLock,
    ResearchEvidenceStore,
    ResearchWriterLockError,
)

Clock = Callable[[], datetime]
Sleeper = Callable[[float], Awaitable[None]]
PreparedSources = tuple[tuple[ResearchObservationSource, ...], Mapping[str, object]]
SourceRebuilder = Callable[
    [Mapping[str, str]],
    Awaitable[PreparedSources],
]
SettingsFactory = Callable[[], AppSettings]


class SelectionAwareSourceFactory(Protocol):
    """Factory that can honor a frozen Polycop wallet count and policy."""

    def __call__(
        self,
        *,
        wallet_count: int | None = None,
        selection_policy: str | None = None,
    ) -> Awaitable[PreparedSources]:
        ...


SourceFactory = Callable[..., Awaitable[PreparedSources]]

PHASES = ("PREPARED", "COLLECTING", "COLLECTED", "VERIFYING", "CLOSED")
MANIFEST_NAME = "run-manifest.json"
PLAN_NAME = "run-plan.json"
STOP_REQUEST_NAME = "stop-request.json"
RESULT_NAME = "result.json"
STOP_POLL_SECONDS = 0.1
ADMISSION_LOCK_ENV = "POLYSIA_RESEARCH_ADMISSION_LOCK"
HOST_ADMISSION_LOCK = Path("/var/lib/polysia/research-runner-admission")


def resolve_admission_lock_path(
    *,
    configured: Path | None = None,
    environment: Mapping[str, str] | None = None,
) -> Path:
    """Return the host-wide admission lock stem, independent of workspace parent."""
    if configured is not None:
        return Path(configured)
    env = os.environ if environment is None else environment
    override = str(env.get(ADMISSION_LOCK_ENV) or "").strip()
    if override:
        return Path(override)
    return HOST_ADMISSION_LOCK


def source_factory_accepts_selection(factory: Callable[..., Any]) -> bool:
    """Return True when the factory declares wallet_count and selection_policy."""
    try:
        parameters = inspect.signature(factory).parameters
    except (TypeError, ValueError):
        return False
    return "wallet_count" in parameters and "selection_policy" in parameters


def selection_source_kwargs(plan: ResearchRunPlan) -> dict[str, object]:
    kwargs: dict[str, object] = {}
    policy = plan.selection.get("policy")
    count = plan.selection.get("wallet_count")
    if isinstance(policy, str) and policy.startswith("polycop-"):
        kwargs["selection_policy"] = policy
        if isinstance(count, int) and not isinstance(count, bool):
            kwargs["wallet_count"] = count
    return kwargs


class ResearchRunnerError(RuntimeError):
    """Sanitized runner failure."""


class ResearchRunnerConflictError(ResearchRunnerError):
    def __init__(self, message: str, payload: Mapping[str, object]) -> None:
        super().__init__(message)
        self.payload = dict(payload)


@dataclass(frozen=True, slots=True)
class ResearchRunWorkspace:
    root: Path

    @property
    def manifest_path(self) -> Path:
        return self.root / MANIFEST_NAME

    @property
    def database_path(self) -> Path:
        return self.root / "research-evidence.sqlite3"

    @property
    def health_path(self) -> Path:
        return self.root / "reports" / "health.json"

    @property
    def window_report_dir(self) -> Path:
        return self.root / "reports" / "windows"

    @property
    def receipt_dir(self) -> Path:
        return self.root / "receipts"

    @property
    def bundle_root(self) -> Path:
        return self.root / "bundles"

    @property
    def result_path(self) -> Path:
        return self.root / RESULT_NAME

    @property
    def plan_path(self) -> Path:
        return self.root / PLAN_NAME

    @property
    def stop_request_path(self) -> Path:
        return self.root / STOP_REQUEST_NAME

    @property
    def selection_reconstruction_path(self) -> Path:
        return self.root / "selection-reconstruction.json"

    def lock(self) -> ExclusiveWriterLock:
        return ExclusiveWriterLock(
            self.root / "runner",
            rejected_message="second runner rejected for research run workspace",
        )


class ResearchExperimentRunner:
    """Prepare, collect, verify, and close one isolated research run."""

    def __init__(
        self,
        *,
        source_factory: SourceFactory,
        clock: Clock | None = None,
        sleep: Sleeper | None = None,
        settings_factory: SettingsFactory | None = None,
        source_rebuilder: SourceRebuilder | None = None,
        admission_lock_path: Path | None = None,
    ) -> None:
        self._source_factory = source_factory
        self._source_rebuilder = source_rebuilder
        self._clock = clock or (lambda: datetime.now(UTC))
        self._sleep = sleep or asyncio.sleep
        self._settings_factory = settings_factory or AppSettings
        self._admission_lock_path = admission_lock_path

    def status(self, state_root: Path) -> dict[str, object]:
        workspace = ResearchRunWorkspace(state_root)
        manifest = _read_manifest(workspace.manifest_path)
        health = _read_json(workspace.health_path)
        stale = _health_is_stale(workspace.health_path, health, self._clock())
        return _compact_status(manifest, health=health, stale_health=stale)

    def result(self, state_root: Path) -> dict[str, object]:
        workspace = ResearchRunWorkspace(state_root)
        manifest = _read_manifest(workspace.manifest_path)
        if str(manifest.get("phase")) != "CLOSED":
            raise ResearchRunnerError("research run is not closed")
        payload = _read_json(workspace.result_path)
        if payload is None:
            raise ResearchRunnerError("closed research result is missing")
        return _compact_result(manifest, payload)

    def request_stop(
        self,
        state_root: Path,
        *,
        reason: str = "operator_stop",
        command_id: str = "stop",
        expected_revision: int | None = None,
    ) -> dict[str, object]:
        workspace = ResearchRunWorkspace(state_root)
        manifest = _read_manifest(workspace.manifest_path)
        current_revision = _int_config(manifest.get("revision"), 0)
        expected = current_revision if expected_revision is None else expected_revision
        journal = ResearchCommandJournal(workspace.root)
        try:
            command = journal.record(
                command_id=command_id,
                kind=STOP_KIND,
                payload={"reason": reason},
                expected_revision=expected,
                current_revision=current_revision,
                clock=self._clock(),
            )
        except ResearchRunCommandError as error:
            raise ResearchRunnerError(str(error)) from error
        _atomic_json(
            workspace.stop_request_path,
            {
                "command_id": command.command_id,
                "disposition": command.disposition,
                "reason": reason,
                "requested_at": command.requested_at,
            },
        )
        return _compact_status(
            manifest,
            stop_requested=True,
            command=command.to_dict(),
        )

    async def start(
        self,
        state_root: Path,
        *,
        profile: str | RunnerProfile,
        code_sha: str,
        run_id: str | None = None,
        image_sha: str | None = None,
        spec: ResearchRunSpec | Mapping[str, object] | None = None,
    ) -> dict[str, object]:
        return await self._advance(
            state_root,
            profile=profile,
            code_sha=code_sha,
            run_id=run_id,
            image_sha=image_sha,
            spec=spec,
            validate_existing=False,
        )

    async def resume(
        self,
        state_root: Path,
        *,
        profile: str | RunnerProfile,
        code_sha: str,
        run_id: str | None = None,
        image_sha: str | None = None,
        spec: ResearchRunSpec | Mapping[str, object] | None = None,
    ) -> dict[str, object]:
        return await self._advance(
            state_root,
            profile=profile,
            code_sha=code_sha,
            run_id=run_id,
            image_sha=image_sha,
            spec=spec,
            validate_existing=True,
        )

    async def verify(
        self,
        state_root: Path,
        *,
        finalization_code_sha: str | None = None,
    ) -> dict[str, object]:
        workspace = ResearchRunWorkspace(state_root)
        admission = self._admission_lock(state_root)
        try:
            admission.acquire()
        except ResearchWriterLockError as error:
            raise self._conflict(state_root, error) from error
        try:
            try:
                workspace.lock().acquire()
            except ResearchWriterLockError as error:
                raise self._conflict(state_root, error) from error
            try:
                manifest = _read_manifest(workspace.manifest_path)
                phase = str(manifest.get("phase"))
                if phase == "CLOSED":
                    return self.result(state_root)
                if phase not in {"COLLECTED", "VERIFYING"}:
                    raise ResearchRunnerError("verification requires collected evidence")
                return await self._verify_and_close(
                    workspace,
                    manifest,
                    finalization_code_sha=finalization_code_sha,
                )
            finally:
                workspace.lock().release()
        finally:
            admission.release()

    async def _advance(
        self,
        state_root: Path,
        *,
        profile: str | RunnerProfile,
        code_sha: str,
        run_id: str | None,
        image_sha: str | None,
        spec: ResearchRunSpec | Mapping[str, object] | None,
        validate_existing: bool,
    ) -> dict[str, object]:
        resolved_profile = (
            profile if isinstance(profile, RunnerProfile) else resolve_profile(profile)
        )
        workspace = ResearchRunWorkspace(state_root)
        existing = _read_json(workspace.manifest_path)
        plan_code_sha = code_sha
        plan_image_sha = image_sha
        if existing is not None and str(existing.get("phase")) not in {"PREPARED", "COLLECTING"}:
            plan_code_sha = str(existing.get("code_sha") or code_sha)
            plan_image_sha = str(existing.get("image_sha") or plan_code_sha)
        try:
            plan = self._resolve_plan(
                profile=profile,
                resolved_profile=resolved_profile,
                code_sha=plan_code_sha,
                run_id=run_id or (str(existing.get("run_id")) if existing else None),
                image_sha=plan_image_sha,
                spec=spec,
            )
        except ResearchRunContractError as error:
            raise ResearchRunnerError(str(error)) from error
        prepared_sources: PreparedSources | None = None
        self._preflight(workspace, resolved_profile, plan=plan)
        admission = self._admission_lock(state_root)
        try:
            admission.acquire()
        except ResearchWriterLockError as error:
            raise self._conflict(state_root, error) from error
        try:
            try:
                workspace.lock().acquire()
            except ResearchWriterLockError as error:
                raise self._conflict(state_root, error) from error
            try:
                if workspace.manifest_path.is_file():
                    manifest = _read_manifest(workspace.manifest_path)
                    self._validate_existing(
                        manifest,
                        workspace=workspace,
                        profile=resolved_profile,
                        code_sha=code_sha,
                        image_sha=image_sha,
                        run_id=run_id,
                        strict=validate_existing,
                    )
                    self._freeze_plan(workspace, plan, existing=manifest)
                    if str(manifest.get("phase")) == "CLOSED":
                        return self.result(state_root)
                    if str(manifest.get("phase")) in {"PREPARED", "COLLECTING"}:
                        prepared_sources = await self._restore_sources(workspace, manifest)
                else:
                    if validate_existing:
                        raise ResearchRunnerError("research run manifest is missing")
                    self._freeze_plan(workspace, plan, existing=None)
                    try:
                        sources, discovery = await self._open_sources(plan)
                    except ResearchWalletSelectionError as error:
                        raise ResearchRunnerError(str(error)) from error
                    prepared_sources = (sources, discovery)
                    manifest = self._prepare(
                        workspace,
                        profile=resolved_profile,
                        code_sha=code_sha,
                        image_sha=image_sha or code_sha,
                        run_id=run_id or uuid4().hex,
                        discovery=discovery,
                        plan=plan,
                    )
                return await self._continue(
                    workspace,
                    manifest,
                    prepared_sources=prepared_sources,
                    finalization_code_sha=code_sha,
                )
            finally:
                workspace.lock().release()
        finally:
            admission.release()

    def _preflight(
        self,
        workspace: ResearchRunWorkspace,
        profile: RunnerProfile,
        *,
        plan: ResearchRunPlan,
    ) -> None:
        settings = self._settings_factory()
        if settings.trading_mode is not TradingMode.DATA_ONLY:
            raise ResearchRunnerError("TRADING_MODE must be DATA_ONLY")
        if settings.live_trading_enabled:
            raise ResearchRunnerError("LIVE_TRADING_ENABLED must be false")
        if settings.polymarket_live_token_allowlist:
            raise ResearchRunnerError("live token allowlist must be empty")
        if plan.safety.get("trading_mode") != TradingMode.DATA_ONLY.value:
            raise ResearchRunnerError("research-run Plan cannot override DATA_ONLY")
        if plan.safety.get("live_trading_enabled") is not False:
            raise ResearchRunnerError("research-run Plan cannot enable Live")
        if plan.safety.get("overridable") is not False:
            raise ResearchRunnerError("research-run Plan cannot make safety overridable")
        workspace.root.mkdir(parents=True, exist_ok=True)
        for path in (
            workspace.window_report_dir,
            workspace.receipt_dir,
            workspace.bundle_root,
            workspace.health_path.parent,
        ):
            path.mkdir(parents=True, exist_ok=True)
        usage = shutil.disk_usage(workspace.root)
        needed = profile.max_bytes * 3 + SAFETY_MARGIN_BYTES
        if usage.free < needed:
            raise ResearchRunnerError("insufficient disk capacity for research run")
        available_memory = _cgroup_memory_limit_bytes()
        if available_memory is not None and available_memory < profile.memory_bytes:
            raise ResearchRunnerError("insufficient memory for research finalization")

    def _prepare(
        self,
        workspace: ResearchRunWorkspace,
        *,
        profile: RunnerProfile,
        code_sha: str,
        image_sha: str,
        run_id: str,
        discovery: Mapping[str, object],
        plan: ResearchRunPlan,
    ) -> dict[str, object]:
        prepared_at = self._clock()
        thresholds = profile.to_dict()["acceptance_thresholds"]
        if not isinstance(thresholds, dict):
            raise ResearchRunnerError("profile acceptance thresholds are invalid")
        manifest: dict[str, object] = {
            "acceptance_thresholds": thresholds,
            "artifacts": {
                "bundle": None,
                "bundle_sha256": None,
                "collected_database_sha256": None,
                "database": str(workspace.database_path),
                "database_sha256": None,
                "health": str(workspace.health_path),
                "manifest": str(workspace.manifest_path),
                "result": str(workspace.result_path),
            },
            "budgets": {
                "duration_seconds": int(profile.duration.total_seconds()),
                "max_bytes": profile.max_bytes,
                "max_events": profile.max_events,
                "memory_bytes": profile.memory_bytes,
                "finalization_memory_bytes": profile.memory_bytes,
                "window_count": profile.window_count,
            },
            "clocks": {
                "collection_deadline": None,
                "finalization_deadline": None,
                "prepared_at": _utc_text(prepared_at),
                "t0": None,
                "valuation_cutoff": None,
                "warmup_seconds": int(profile.warmup.total_seconds()),
            },
            "code_sha": code_sha,
            "collector_policy_version": COLLECTOR_POLICY_VERSION,
            "configuration_digest": None,
            "contract_digest": CONTRACT_V1.digest,
            "economic_contract_version": CONTRACT_V1.version,
            "effective_configuration": profile.to_dict(),
            "followed_wallet_selection": _discovery_selection(discovery),
            "image_sha": image_sha,
            "live_token_allowlist": [],
            "live_trading_enabled": False,
            "manifest_version": RUNNER_MANIFEST_VERSION,
            "outcome": {
                "economic": None,
                "evidence": None,
                "lifecycle": "PREPARED",
                "stop_reason": None,
                "technical": None,
            },
            "phase": "PREPARED",
            "profile": profile.name,
            "profile_version": profile.version,
            "receipts": [],
            "replay_engine_version": REPLAY_ENGINE_VERSION,
            "research_schema_version": RESEARCH_EVIDENCE_SCHEMA_VERSION,
            "revision": 0,
            "run_id": run_id,
            "run_plan_digest": plan.semantic_digest(),
            "service_policy_version": SERVICE_POLICY_VERSION,
            "trading_mode": TradingMode.DATA_ONLY.value,
        }
        _append_receipt(manifest, "prepare", "ok", prepared_at)
        reconstruction = discovery.get("_reconstruction")
        if isinstance(reconstruction, Mapping):
            _atomic_json(workspace.selection_reconstruction_path, reconstruction)
        _write_manifest(workspace.manifest_path, manifest)
        return manifest

    async def _restore_sources(
        self,
        workspace: ResearchRunWorkspace,
        manifest: Mapping[str, object],
    ) -> PreparedSources:
        reconstruction = _read_reconstruction(workspace)
        public = _mapping(manifest.get("followed_wallet_selection"))
        if reconstruction is None:
            if str(public.get("selection_policy", "")).startswith("polycop-"):
                raise ResearchRunnerError("frozen Polycop reconstruction is missing")
            sources, discovery = await self._source_factory()
            return sources, discovery
        from polysia.deployment.research_wallet_selection import verify_reconstruction

        try:
            aliases = verify_reconstruction(reconstruction, public)
        except ResearchWalletSelectionError as error:
            raise ResearchRunnerError(str(error)) from error
        if self._source_rebuilder is None:
            raise ResearchRunnerError("frozen wallet source rebuilder is missing")
        sources, discovery = await self._source_rebuilder(aliases)
        return sources, discovery

    async def _continue(
        self,
        workspace: ResearchRunWorkspace,
        manifest: dict[str, object],
        *,
        prepared_sources: PreparedSources | None = None,
        finalization_code_sha: str | None = None,
    ) -> dict[str, object]:
        phase = str(manifest.get("phase"))
        if phase in {"PREPARED", "COLLECTING"}:
            manifest = await self._collect(
                workspace,
                manifest,
                prepared_sources=prepared_sources,
            )
            phase = str(manifest.get("phase"))
        if phase in {"COLLECTED", "VERIFYING"}:
            return await self._verify_and_close(
                workspace,
                manifest,
                finalization_code_sha=finalization_code_sha,
            )
        if phase == "CLOSED":
            return self.result(workspace.root)
        raise ResearchRunnerError("research run phase is not resumable")

    async def _collect(
        self,
        workspace: ResearchRunWorkspace,
        manifest: dict[str, object],
        *,
        prepared_sources: PreparedSources | None = None,
    ) -> dict[str, object]:
        profile = _profile_from_manifest(manifest)
        if prepared_sources is None:
            sources, discovery = await self._source_factory()
        else:
            sources, discovery = prepared_sources
        frozen = _mapping(manifest.get("followed_wallet_selection"))
        identity = _source_identity(discovery)
        for key in (
            "aliases",
            "required_source_ids",
            "optional_source_ids",
            "unavailable_sources",
        ):
            if identity.get(key) != sorted(_strings(frozen.get(key))):
                raise ResearchRunnerError("research run source selection mismatch")
        required = tuple(_strings(frozen.get("required_source_ids")))
        optional = tuple(_strings(frozen.get("optional_source_ids")))
        aliases = tuple(_strings(frozen.get("aliases")))
        tokens = tuple(_strings(frozen.get("market_tokens") or identity.get("market_tokens")))
        store = ResearchEvidenceStore(workspace.database_path, clock=self._clock)
        collector = PersistentProspectiveCollector(
            store,
            sources,
            config=PersistentCollectorConfig(
                window=profile.window,
                health_path=workspace.health_path,
                report_dir=workspace.window_report_dir,
                required_source_ids=required,
                optional_source_ids=optional,
                tracked_wallet_aliases=aliases,
                tracked_market_tokens=tokens,
                code_sha=str(manifest["code_sha"]),
                experiment_duration=profile.duration,
                experiment_max_events=profile.max_events,
                experiment_max_bytes=profile.max_bytes,
            ),
            clock=self._clock,
            sleep=self._sleep,
            run_id=str(manifest["run_id"]),
        )
        if manifest.get("configuration_digest") not in {None, collector.configuration_digest}:
            raise ResearchRunnerError("research run configuration digest mismatch")
        manifest["configuration_digest"] = collector.configuration_digest
        clocks = _mapping(manifest.get("clocks"))
        if clocks.get("t0") is None and profile.warmup.total_seconds() > 0:
            await self._sleep(profile.warmup.total_seconds())
        store.initialize()
        store.acquire_writer()
        try:
            experiment = store.start_or_resume_experiment(
                requested_run_id=str(manifest["run_id"]),
                duration=profile.duration,
                max_events=profile.max_events,
                max_bytes=profile.max_bytes,
                code_sha=str(manifest["code_sha"]),
                configuration_digest=collector.configuration_digest,
            )
        finally:
            store.release_writer()
        clocks = _mapping(manifest.get("clocks"))
        manifest["clocks"] = clocks
        t0_text = _utc_text(experiment.started_at)
        if clocks.get("t0") is None:
            clocks["t0"] = t0_text
            clocks["collection_deadline"] = _utc_text(experiment.collection_ends_at)
            clocks["valuation_cutoff"] = _utc_text(experiment.collection_ends_at)
            clocks["finalization_deadline"] = _utc_text(
                experiment.started_at + profile.finalization_deadline_offset
            )
        elif clocks.get("t0") != t0_text:
            raise ResearchRunnerError("research run T0 cannot be reset")
        manifest["phase"] = "COLLECTING"
        outcome = _outcome(manifest)
        outcome["lifecycle"] = "COLLECTING"
        _append_receipt(manifest, "collect", "started", self._clock())
        _write_manifest(workspace.manifest_path, manifest)
        watcher = asyncio.create_task(self._watch_stop(collector, workspace))
        try:
            await collector.run(cycles=profile.window_count)
        finally:
            watcher.cancel()
            await asyncio.gather(watcher, return_exceptions=True)
        collected = store.load_experiment(str(manifest["run_id"]))
        if collected is None:
            raise ResearchRunnerError("research experiment disappeared during collection")
        if _utc_text(collected.started_at) != str(clocks.get("t0")):
            raise ResearchRunnerError("research run T0 cannot be reset")
        stop = _read_json(workspace.stop_request_path)
        artifacts = _mapping(manifest.get("artifacts"))
        collected_hash = _stable_database_sha256(workspace.database_path)
        artifacts["collected_database_sha256"] = collected_hash
        artifacts["database_sha256"] = collected_hash
        manifest["phase"] = "COLLECTED"
        lifecycle = "STOPPED" if stop is not None else "COLLECTED"
        outcome["lifecycle"] = lifecycle
        if stop is not None:
            outcome["stop_reason"] = str(stop.get("reason") or "operator_stop")
            self._apply_stop_command(workspace, stop, lifecycle=lifecycle)
        _append_receipt(manifest, "collect", lifecycle, self._clock())
        _write_manifest(workspace.manifest_path, manifest)
        return manifest

    async def _verify_and_close(
        self,
        workspace: ResearchRunWorkspace,
        manifest: dict[str, object],
        *,
        finalization_code_sha: str | None = None,
    ) -> dict[str, object]:
        manifest["phase"] = "VERIFYING"
        outcome = _outcome(manifest)
        _append_receipt(manifest, "verify", "started", self._clock())
        _write_manifest(workspace.manifest_path, manifest)
        run_id = str(manifest["run_id"])
        artifacts = _mapping(manifest.get("artifacts"))
        collected_hash = str(
            artifacts.get("collected_database_sha256") or artifacts.get("database_sha256") or ""
        )
        published = _published_bundle_database(
            artifacts,
            workspace=workspace,
            run_id=run_id,
        )
        if collected_hash and published is None:
            actual = _stable_database_sha256(workspace.database_path)
            if actual.casefold() != collected_hash.casefold():
                raise ResearchRunnerError("research database hash mismatch")
        analysis_sha = finalization_code_sha or str(manifest.get("code_sha"))
        manifest["finalization_code_sha"] = analysis_sha
        bundle = finalize_research_experiment(
            workspace.database_path,
            workspace.bundle_root,
            run_id=run_id,
        )
        replay = bundle.replay
        if replay is None:
            raise ResearchRunnerError("finalized experiment analysis is missing")
        with open_recorded_experiment_store(
            bundle.database_path,
            bundle_root=bundle.path,
            expected_database_sha256=bundle.sha256,
        ) as replica:
            experiment = replica.load_experiment(run_id)
        if experiment is None:
            raise ResearchRunnerError("finalized experiment record is missing")
        detailed = detailed_replay_payload(
            replay,
            experiment=experiment,
            run_id=run_id,
            source_database_sha256=bundle.sha256,
            include_decision_rows=False,
        )
        compact = compact_replay_payload(detailed)
        artifacts = _mapping(manifest.get("artifacts"))
        artifacts["bundle"] = str(bundle.path)
        artifacts["bundle_sha256"] = bundle.sha256
        artifacts["database_sha256"] = bundle.sha256
        artifacts["result"] = str(workspace.result_path)
        outcome["technical"] = "PASS" if bundle.verified else "FAIL"
        economic = detailed.get("economic")
        economic_map = economic if isinstance(economic, dict) else {}
        outcome["evidence"] = economic_map.get("data_canary_status")
        outcome["economic"] = economic_map.get("economic_classification")
        if outcome.get("lifecycle") != "STOPPED":
            outcome["lifecycle"] = "COMPLETED"
        manifest["phase"] = "CLOSED"
        result = {
            "bundle_outcome": bundle.outcome,
            "bundle_verified": bundle.verified,
            "compact": compact,
            "run_id": run_id,
        }
        _atomic_json(workspace.result_path, result)
        _append_receipt(manifest, "close", str(outcome["technical"]), self._clock())
        _write_manifest(workspace.manifest_path, manifest)
        return _compact_result(manifest, result)

    async def _watch_stop(
        self,
        collector: PersistentProspectiveCollector,
        workspace: ResearchRunWorkspace,
    ) -> None:
        while True:
            if workspace.stop_request_path.is_file():
                collector.request_stop()
                return
            await asyncio.sleep(STOP_POLL_SECONDS)

    def _validate_existing(
        self,
        manifest: dict[str, object],
        *,
        workspace: ResearchRunWorkspace,
        profile: RunnerProfile,
        code_sha: str,
        image_sha: str | None,
        run_id: str | None,
        strict: bool,
    ) -> None:
        if str(manifest.get("manifest_version")) != RUNNER_MANIFEST_VERSION:
            raise ResearchRunnerError("research run manifest version mismatch")
        if run_id is not None and str(manifest.get("run_id")) != run_id:
            raise ResearchRunnerError("research run identity mismatch")
        phase = str(manifest.get("phase"))
        collection_locked = phase in {"PREPARED", "COLLECTING"}
        if collection_locked and str(manifest.get("code_sha")) != code_sha:
            raise ResearchRunnerError("research run code SHA mismatch")
        expected_image = image_sha or code_sha
        if collection_locked and str(manifest.get("image_sha")) != expected_image:
            raise ResearchRunnerError("research run image SHA mismatch")
        if str(manifest.get("profile")) != profile.name:
            raise ResearchRunnerError("research run profile mismatch")
        if str(manifest.get("profile_version")) != profile.version:
            raise ResearchRunnerError("research run profile mismatch")
        if str(manifest.get("contract_digest")) != CONTRACT_V1.digest:
            raise ResearchRunnerError("research run contract digest mismatch")
        if str(manifest.get("replay_engine_version")) != REPLAY_ENGINE_VERSION:
            raise ResearchRunnerError("research run engine version mismatch")
        artifacts = _mapping(manifest.get("artifacts"))
        published = _published_bundle_database(
            artifacts,
            workspace=workspace,
            run_id=str(manifest.get("run_id") or ""),
        )
        collected_hash = artifacts.get("collected_database_sha256")
        recorded_db = artifacts.get("database_sha256")
        recorded_bundle = artifacts.get("bundle_sha256")
        if published is not None:
            published_hash = sha256_file(published)
            if (
                recorded_bundle
                and str(recorded_bundle).casefold() != published_hash.casefold()
            ):
                raise ResearchRunnerError("research bundle hash mismatch")
            if phase == "CLOSED" and recorded_db:
                if str(recorded_db).casefold() != published_hash.casefold():
                    raise ResearchRunnerError("research database hash mismatch")
            elif phase == "VERIFYING" and recorded_db:
                allowed = {published_hash.casefold()}
                if collected_hash:
                    allowed.add(str(collected_hash).casefold())
                if str(recorded_db).casefold() not in allowed:
                    raise ResearchRunnerError("research database hash mismatch")
        elif phase == "COLLECTED":
            expected = collected_hash or recorded_db
            if expected:
                actual = _stable_database_sha256(workspace.database_path)
                if actual.casefold() != str(expected).casefold():
                    raise ResearchRunnerError("research database hash mismatch")
            elif strict:
                raise ResearchRunnerError("research database hash mismatch")
        recorded_plan = _recorded_run_plan_digest(manifest)
        if recorded_plan is not None:
            if not workspace.plan_path.is_file():
                raise ResearchRunnerError("research-run Plan is missing")
            stored = load_run_plan(_read_json(workspace.plan_path) or {})
            if stored.semantic_digest() != recorded_plan:
                raise ResearchRunnerError("research-run Plan digest mismatch")

    def _resolve_plan(
        self,
        *,
        profile: str | RunnerProfile,
        resolved_profile: RunnerProfile,
        code_sha: str,
        run_id: str | None,
        image_sha: str | None,
        spec: ResearchRunSpec | Mapping[str, object] | None,
    ) -> ResearchRunPlan:
        supplied_profile = resolved_profile if isinstance(profile, RunnerProfile) else None
        if spec is None:
            parsed, legacy_profile = spec_from_legacy(
                profile,
                code_sha=code_sha,
                image_sha=image_sha,
                run_id=run_id,
            )
            return resolve_run_plan(
                parsed,
                profile=legacy_profile or supplied_profile,
                observed=self._clock(),
            )
        parsed = spec if isinstance(spec, ResearchRunSpec) else parse_research_run_spec(spec)
        parsed = ResearchRunSpec(
            profile=parsed.profile,
            code_sha=code_sha,
            image_sha=image_sha or parsed.image_sha,
            run_id=run_id or parsed.run_id,
            wallet_count=parsed.wallet_count,
        )
        return resolve_run_plan(
            parsed,
            profile=supplied_profile if parsed.profile == resolved_profile.name else None,
            observed=self._clock(),
        )

    def _freeze_plan(
        self,
        workspace: ResearchRunWorkspace,
        plan: ResearchRunPlan,
        *,
        existing: dict[str, object] | None,
    ) -> None:
        stored_payload = _read_json(workspace.plan_path)
        recorded_digest = _recorded_run_plan_digest(existing)
        if stored_payload is not None:
            stored = load_run_plan(stored_payload)
            if not plans_semantically_equal(stored, plan):
                raise ResearchRunnerError("stale or tampered research-run Plan")
        elif recorded_digest is not None:
            raise ResearchRunnerError("research-run Plan is missing")
        else:
            _atomic_json(workspace.plan_path, plan.to_dict())
            if existing is not None:
                existing["run_plan_digest"] = plan.semantic_digest()
        if existing is not None:
            budgets = _mapping(existing.get("budgets"))
            for key, allowed in plan.budgets.items():
                recorded = budgets.get(key)
                if isinstance(recorded, int) and allowed > recorded:
                    raise ResearchRunnerError("research-run Plan cannot expand budgets")
            frozen_count = _mapping(existing.get("followed_wallet_selection")).get("wallet_count")
            planned_count = plan.selection.get("wallet_count")
            if (
                isinstance(frozen_count, int)
                and isinstance(planned_count, int)
                and planned_count != frozen_count
            ):
                raise ResearchRunnerError("research-run Plan cannot change frozen wallet count")

    def _apply_stop_command(
        self,
        workspace: ResearchRunWorkspace,
        stop: Mapping[str, object],
        *,
        lifecycle: str,
    ) -> None:
        command_id = str(stop.get("command_id") or "stop")
        try:
            ResearchCommandJournal(workspace.root).mark_applied(
                command_id,
                observed_result={"lifecycle": lifecycle, "phase": "COLLECTED"},
                clock=self._clock(),
            )
        except ResearchRunCommandError as error:
            raise ResearchRunnerError(str(error)) from error

    async def _open_sources(self, plan: ResearchRunPlan) -> PreparedSources:
        kwargs = selection_source_kwargs(plan)
        if not kwargs:
            return await self._source_factory()
        if not source_factory_accepts_selection(self._source_factory):
            raise ResearchRunnerError(
                "research source factory cannot honor the frozen Polycop selection"
            )
        return await self._source_factory(**kwargs)

    def _admission_lock(self, state_root: Path) -> ExclusiveWriterLock:
        del state_root
        return ExclusiveWriterLock(
            resolve_admission_lock_path(configured=self._admission_lock_path),
            rejected_message="second resource-consuming research run rejected",
        )

    def _conflict(
        self, state_root: Path, error: ResearchWriterLockError
    ) -> ResearchRunnerConflictError:
        try:
            payload = self.status(state_root)
        except ResearchRunnerError:
            payload = {
                "actionable_failure": str(error),
                "command": "prospective-run",
                "live_trading_enabled": False,
                "phase": None,
                "trading_mode": TradingMode.DATA_ONLY.value,
            }
        return ResearchRunnerConflictError(str(error), payload)


def _profile_from_manifest(manifest: Mapping[str, object]) -> RunnerProfile:
    name = str(manifest.get("profile") or "")
    if name in {"canary", "main"}:
        return resolve_profile(name)
    config = _mapping(manifest.get("effective_configuration"))
    return RunnerProfile(
        name=name or "lab",
        version=str(manifest.get("profile_version") or "lab-v1"),
        window=timedelta(seconds=_int_config(config.get("window_seconds"), 2)),
        window_count=_int_config(config.get("window_count"), 1),
        warmup=timedelta(seconds=_int_config(config.get("warmup_seconds"), 0)),
        max_events=_int_config(config.get("max_events"), 10_000),
        max_bytes=_int_config(config.get("max_bytes"), 10_000_000),
        memory_bytes=_int_config(config.get("memory_bytes"), 8_388_608),
    )


def _recorded_run_plan_digest(existing: Mapping[str, object] | None) -> str | None:
    if existing is None:
        return None
    recorded = existing.get("run_plan_digest")
    if recorded is None:
        return None
    text = str(recorded).strip()
    return text or None


def _read_manifest(path: Path) -> dict[str, object]:
    payload = _read_json(path)
    if payload is None:
        raise ResearchRunnerError("research run manifest is missing")
    return payload


def _read_json(path: Path) -> dict[str, object] | None:
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ResearchRunnerError("research run artifact is not valid JSON") from error
    if not isinstance(payload, dict):
        raise ResearchRunnerError("research run artifact must be a JSON object")
    return payload


def _write_manifest(path: Path, payload: dict[str, object]) -> None:
    payload["revision"] = _int_config(payload.get("revision"), 0) + 1
    _atomic_json(path, payload)
    receipts_dir = path.parent / "receipts"
    receipts = payload.get("receipts")
    _atomic_json(
        receipts_dir / "receipts.json",
        {"receipts": list(receipts) if isinstance(receipts, list) else []},
    )


def _atomic_json(path: Path, payload: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    text = json.dumps(dict(payload), sort_keys=True, default=str)
    temporary.write_text(f"{text}\n", encoding="utf-8")
    if os.name != "nt":
        temporary.chmod(0o600)
    os.replace(temporary, path)
    if os.name != "nt":
        path.chmod(0o600)


def _append_receipt(
    manifest: dict[str, object],
    operation: str,
    status: str,
    observed: datetime,
) -> None:
    receipts = manifest.get("receipts")
    rows = list(receipts) if isinstance(receipts, list) else []
    rows.append(
        {
            "at": _utc_text(observed),
            "operation": operation,
            "status": status,
        }
    )
    manifest["receipts"] = rows


def _outcome(manifest: dict[str, object]) -> dict[str, object]:
    outcome = manifest.get("outcome")
    if not isinstance(outcome, dict):
        outcome = {}
        manifest["outcome"] = outcome
    return outcome


def _mapping(value: object) -> dict[str, object]:
    return value if isinstance(value, dict) else {}


def _strings(value: object) -> list[str]:
    if isinstance(value, list | tuple):
        return [str(item) for item in value]
    return []


def _source_identity(discovery: Mapping[str, object]) -> dict[str, object]:
    return {
        "aliases": sorted(_strings(discovery.get("followed_aliases"))),
        "required_source_ids": sorted(_strings(discovery.get("required_source_ids"))),
        "optional_source_ids": sorted(_strings(discovery.get("optional_source_ids"))),
        "unavailable_sources": sorted(_strings(discovery.get("unavailable"))),
        "market_tokens": sorted(_strings(discovery.get("market_tokens"))),
    }


def _discovery_selection(discovery: Mapping[str, object]) -> dict[str, object]:
    payload = _source_identity(discovery)
    for key in (
        "feature_set_version",
        "freshness_bound",
        "policy_id",
        "policy_version",
        "published_at",
        "ranking_version",
        "reconstruction_digest",
        "selected_pools",
        "selected_ranks",
        "selection_digest",
        "selection_policy",
        "selection_policy_version",
        "selection_run_id",
        "snapshot_digest",
        "source_id",
        "source_snapshot_id",
        "wallet_count",
        "wallet_ids",
        "wallet_limit",
        "selection_reasons",
    ):
        value = discovery.get(key)
        if value is not None:
            payload[key] = value
    return payload


def _read_reconstruction(workspace: ResearchRunWorkspace) -> dict[str, object] | None:
    path = workspace.selection_reconstruction_path
    if not path.is_file():
        return None
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ResearchRunnerError("frozen Polycop reconstruction is invalid")
    return payload


def _int_config(value: object, default: int) -> int:
    if isinstance(value, bool) or value is None:
        return default
    if isinstance(value, int):
        return value
    return int(str(value))


def _published_bundle_database(
    artifacts: Mapping[str, object],
    *,
    workspace: ResearchRunWorkspace | None = None,
    run_id: str = "",
) -> Path | None:
    bundle = artifacts.get("bundle")
    if isinstance(bundle, str) and bundle:
        database = Path(bundle) / "research-evidence.sqlite3"
        if database.is_file():
            return database
    if workspace is None or not run_id:
        return None
    for suffix in ("", "-failure"):
        database = (
            workspace.bundle_root
            / f"research-experiment-{run_id}{suffix}"
            / "research-evidence.sqlite3"
        )
        checksum = database.with_suffix(f"{database.suffix}.sha256")
        if not database.is_file() or not checksum.is_file():
            continue
        token = checksum.read_text(encoding="ascii").split()[0]
        if token.casefold() == sha256_file(database).casefold():
            return database
    return None


def _checkpoint_sqlite(path: Path) -> None:
    connection = sqlite3.connect(path)
    try:
        connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        connection.commit()
    finally:
        connection.close()


def _stable_database_sha256(path: Path) -> str:
    _checkpoint_sqlite(path)
    return sha256_file(path)


def _health_is_stale(
    path: Path,
    health: Mapping[str, object] | None,
    now: datetime,
) -> bool:
    if health is None or not path.is_file():
        return True
    if health.get("stale") is True:
        return True
    age = now.timestamp() - path.stat().st_mtime
    return age > 120


def _compact_status(
    manifest: Mapping[str, object],
    *,
    health: Mapping[str, object] | None = None,
    stale_health: bool = False,
    stop_requested: bool = False,
    command: Mapping[str, object] | None = None,
) -> dict[str, object]:
    clocks = _mapping(manifest.get("clocks"))
    artifacts = _mapping(manifest.get("artifacts"))
    stop_command = None
    if command is not None:
        stop_command = {
            "command_id": command.get("command_id"),
            "disposition": command.get("disposition"),
        }
    payload = {
        "actionable_failure": _actionable_failure(manifest, stale_health=stale_health),
        "bundle": artifacts.get("bundle"),
        "code_sha": manifest.get("code_sha"),
        "collection_deadline": clocks.get("collection_deadline"),
        "command": "prospective-run",
        "live_trading_enabled": False,
        "outcome": manifest.get("outcome"),
        "phase": manifest.get("phase"),
        "profile": manifest.get("profile"),
        "progress": _mapping(health).get("windows_closed") if health is not None else None,
        "revision": manifest.get("revision"),
        "run_id": manifest.get("run_id"),
        "stale_health": stale_health,
        "stop_command": stop_command,
        "stop_requested": stop_requested,
        "storage": _mapping(health).get("storage") if health is not None else None,
        "t0": clocks.get("t0"),
        "trading_mode": TradingMode.DATA_ONLY.value,
    }
    _ensure_compact(payload)
    return payload


def _compact_result(
    manifest: Mapping[str, object], result: Mapping[str, object]
) -> dict[str, object]:
    compact = result.get("compact")
    payload = {
        "bundle": _mapping(manifest.get("artifacts")).get("bundle"),
        "bundle_outcome": result.get("bundle_outcome"),
        "bundle_sha256": _mapping(manifest.get("artifacts")).get("bundle_sha256"),
        "bundle_verified": result.get("bundle_verified"),
        "command": "prospective-run",
        "finalization_code_sha": manifest.get("finalization_code_sha"),
        "live_trading_enabled": False,
        "outcome": manifest.get("outcome"),
        "phase": manifest.get("phase"),
        "profile": manifest.get("profile"),
        "replay": compact if isinstance(compact, dict) else {},
        "run_id": manifest.get("run_id"),
        "trading_mode": TradingMode.DATA_ONLY.value,
    }
    _ensure_compact(payload)
    return payload


def _actionable_failure(manifest: Mapping[str, object], *, stale_health: bool) -> str | None:
    outcome = _mapping(manifest.get("outcome"))
    if outcome.get("technical") == "FAIL":
        return "technical_fail"
    if outcome.get("stop_reason"):
        return str(outcome.get("stop_reason"))
    if stale_health and str(manifest.get("phase")) == "COLLECTING":
        return "stale_health"
    return None


def _ensure_compact(payload: Mapping[str, object]) -> None:
    encoded = json.dumps(dict(payload), sort_keys=True, default=str)
    if len(encoded.encode()) > COMPACT_STDOUT_LIMIT:
        raise ResearchRunnerError("research runner stdout exceeded 5 KiB")


def _cgroup_memory_limit_bytes() -> int | None:
    path = Path("/sys/fs/cgroup/memory.max")
    if not path.is_file():
        return None
    raw = path.read_text(encoding="ascii").strip()
    if not raw or raw == "max":
        return None
    try:
        return int(raw)
    except ValueError:
        return None


def _utc_text(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")
