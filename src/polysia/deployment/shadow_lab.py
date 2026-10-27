"""Small bounded Lab on the existing Shadow repository, lifecycle and engine."""

from __future__ import annotations

import sqlite3
from collections.abc import Callable, Mapping
from contextlib import closing
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx
from pydantic import TypeAdapter

from polysia.adapters.polymarket.bounded_market import BoundedMarketAdapter
from polysia.adapters.polymarket.bounded_transport import BoundedPublicTransport
from polysia.adapters.polymarket.corroborated_leader import CorroboratedLeaderSource
from polysia.adapters.polymarket.research_rpc import BoundedResearchRPC
from polysia.adapters.polymarket.session_chain import CTFChainReader, ReadOnlyRPC
from polysia.adapters.polymarket.session_source import CorroboratedSessionSource
from polysia.application.ports.continuous_shadow import ContinuousSelectionSnapshot
from polysia.application.services.continuous_shadow import ContinuousShadowService
from polysia.control.scoped_operations import ScopedPreview
from polysia.domain.copytrading.continuous_shadow import (
    ContinuousShadowConfig,
)
from polysia.domain.financial_session import InstrumentScope, SessionBlocked, digest
from polysia.domain.research_evidence.acquisition_policy import AcquisitionPolicy
from polysia.monitoring.session_incidents import SessionIncidents
from polysia.storage.acquisition_authority import AcquisitionAuthority
from polysia.storage.continuous_shadow import (
    ContinuousShadowLeaseRepository,
    ContinuousShadowRepository,
)


class _FrozenCandidates:
    def __init__(self, selection: ContinuousSelectionSnapshot) -> None:
        self.selection = selection

    def current_snapshot(self, source_id: str) -> ContinuousSelectionSnapshot:
        if source_id != self.selection.source_id:
            raise SessionBlocked("shadow_lab_target_mismatch")
        return self.selection


@dataclass(frozen=True, slots=True)
class ShadowSourcePlan:
    rpc_url: str
    exchange: str
    ctf: str
    collateral: str
    instruments: tuple[InstrumentScope, ...]
    wallets: tuple[tuple[str, str], ...]


@dataclass(frozen=True, slots=True)
class ShadowLabConfiguration:
    store: Path
    acquisition_path: Path
    acquisition_policy: AcquisitionPolicy
    selection: ContinuousSelectionSnapshot
    templates: tuple[ContinuousShadowConfig, ...]
    targets: frozenset[str]
    source: ShadowSourcePlan


def load_shadow_lab(path: Path, *, clock: Callable[[], datetime]) -> ShadowLab:
    if path.is_symlink() or path.stat().st_size > 1_000_000:
        raise SessionBlocked("bounded_shadow_lab_configuration_required")
    config = TypeAdapter(ShadowLabConfiguration).validate_json(path.read_bytes(), extra="forbid")
    return ShadowLab(
        ContinuousShadowRepository(config.store),
        AcquisitionAuthority(config.acquisition_path, config.acquisition_policy),
        selection=config.selection,
        templates={
            item.copy_policy.fingerprint: item
            for item in config.templates
            if item.copy_policy is not None
        },
        allowed_targets=config.targets,
        clock=clock,
        source_plan=config.source,
    )


class ShadowLab:
    def __init__(
        self,
        store: ContinuousShadowRepository,
        acquisition: AcquisitionAuthority,
        *,
        selection: ContinuousSelectionSnapshot,
        templates: Mapping[str, ContinuousShadowConfig],
        allowed_targets: frozenset[str],
        clock: Callable[[], datetime],
        maximum_experiments: int = 4,
        source_plan: ShadowSourcePlan,
    ) -> None:
        if not 1 <= maximum_experiments <= 4 or not templates or not allowed_targets:
            raise SessionBlocked("bounded_shadow_lab_configuration_required")
        if any(config.copy_policy is None for config in templates.values()):
            raise SessionBlocked("shadow_lab_requires_frozen_copy_policies")
        self.store, self.acquisition, self.selection = store, acquisition, selection
        self.templates, self.targets, self.clock = dict(templates), allowed_targets, clock
        self.maximum = maximum_experiments
        self.transport = BoundedPublicTransport(acquisition)
        if source_plan.rpc_url not in acquisition.policy.endpoints:
            raise SessionBlocked("shadow_RPC_requires_same_acquisition_budget_owner")
        if len(dict(source_plan.wallets)) != len(source_plan.wallets) or set(
            dict(source_plan.wallets)
        ) != {item.wallet_id for item in selection.candidates}:
            raise SessionBlocked("shadow_source_mapping_selection_mismatch")
        if any(
            dict(source_plan.wallets)[item.wallet_id].lower() != item.address.lower()
            for item in selection.candidates
        ):
            raise SessionBlocked("shadow_source_address_selection_mismatch")
        fields = asdict(selection)
        del fields["digest"]
        fields["candidates"] = selection.candidates
        if ContinuousSelectionSnapshot.create(**fields).digest != selection.digest:
            raise SessionBlocked("shadow_selection_digest_mismatch")
        if any(
            key != config.copy_policy.fingerprint
            for key, config in templates.items()
            if config.copy_policy is not None
        ):
            raise SessionBlocked("shadow_policy_template_digest_mismatch")
        self.source_plan = source_plan
        self.rpc_http = httpx.AsyncClient(
            transport=BoundedResearchRPC(acquisition),
            follow_redirects=False,
            timeout=acquisition.policy.timeout_seconds,
        )
        self.chain = CTFChainReader(
            ReadOnlyRPC(self.rpc_http, source_plan.rpc_url),
            exchange=source_plan.exchange,
            ctf=source_plan.ctf,
            collateral=source_plan.collateral,
            instruments=source_plan.instruments,
        )
        self.incidents = SessionIncidents(store.path.with_suffix(".incidents.sqlite3"), clock=clock)

    def initialize(self) -> None:
        self.store.initialize()
        self.acquisition.initialize()
        self.incidents.initialize()
        with closing(sqlite3.connect(self.store.path)) as connection, connection:
            connection.execute(
                "CREATE TABLE IF NOT EXISTS continuous_shadow_lab_slots("
                "target TEXT PRIMARY KEY,policy_digest TEXT NOT NULL,config_digest TEXT NOT NULL,"
                "selection_digest TEXT NOT NULL,experiment_id TEXT,phase TEXT NOT NULL,"
                "created_at TEXT NOT NULL,updated_at TEXT NOT NULL)"
            )

    def execute(self, preview: ScopedPreview) -> dict[str, Any]:
        if preview.target not in self.targets or preview.operation not in {
            "shadow.create",
            "shadow.clone",
            "shadow.start",
            "shadow.drain",
            "shadow.resume",
            "shadow.finalize",
            "shadow.archive",
            "shadow.compare",
            "policy.stage",
        }:
            raise SessionBlocked("shadow_lab_operation_or_target_denied")
        now = self.clock()
        if not preview.created_at <= now < preview.expires_at:
            raise SessionBlocked("shadow_lab_preview_expired")
        arguments = dict(preview.arguments)
        slot = self.slot(preview.target)
        if preview.operation in {"shadow.create", "shadow.clone"}:
            if slot is not None:
                raise SessionBlocked("shadow_lab_slot_already_has_history")
            policy = arguments.get("policy_digest")
            if preview.operation == "shadow.clone":
                source = self.slot(arguments["source"])
                if source is None or arguments["source"] not in self.targets:
                    raise SessionBlocked("shadow_lab_clone_source_unavailable")
                if (
                    arguments.get("source_policy_digest", source["policy_digest"])
                    != source["policy_digest"]
                ):
                    raise SessionBlocked("shadow_lab_clone_source_policy_changed")
                policy = source["policy_digest"]
            config = self.templates.get(str(policy))
            if config is None:
                raise SessionBlocked("shadow_lab_policy_not_registered")
            with closing(sqlite3.connect(self.store.path)) as connection, connection:
                connection.execute("BEGIN IMMEDIATE")
                if (
                    connection.execute(
                        "SELECT COUNT(*) FROM continuous_shadow_lab_slots"
                    ).fetchone()[0]
                    >= self.maximum
                ):
                    raise SessionBlocked("shadow_lab_experiment_budget_exhausted")
                connection.execute(
                    "INSERT INTO continuous_shadow_lab_slots VALUES(?,?,?,?,NULL,'CREATED',?,?)",
                    (
                        preview.target,
                        policy,
                        self._config_digest(config),
                        self.selection.digest,
                        now.isoformat(),
                        now.isoformat(),
                    ),
                )
        elif slot is None:
            raise SessionBlocked("shadow_lab_slot_unavailable")
        elif preview.operation == "policy.stage":
            if slot["phase"] != "CREATED" or arguments["policy_digest"] not in self.templates:
                raise SessionBlocked("running_policy_is_immutable_stage_new_experiment")
            replacement = self.templates[arguments["policy_digest"]]
            with closing(sqlite3.connect(self.store.path)) as connection, connection:
                connection.execute(
                    "UPDATE continuous_shadow_lab_slots SET policy_digest=?,"
                    "config_digest=?,updated_at=? WHERE target=?",
                    (
                        arguments["policy_digest"],
                        self._config_digest(replacement),
                        now.isoformat(),
                        preview.target,
                    ),
                )
        elif preview.operation == "shadow.start":
            if slot["phase"] != "CREATED":
                raise SessionBlocked("shadow_lab_start_requires_created_slot")
            experiment = self.service(preview.target).start(self._scope(preview.target))
            self._phase(preview.target, "RUNNING", experiment.experiment_id)
        elif preview.operation in {"shadow.drain", "shadow.finalize"}:
            service = self.service(preview.target)
            experiment = (
                service.drain(self._scope(preview.target))
                if preview.operation == "shadow.drain"
                else service.finalize(self._scope(preview.target))
            )
            self._phase(preview.target, experiment.lifecycle.value, experiment.experiment_id)
        elif preview.operation == "shadow.resume":
            if slot["phase"] != "DRAINING":
                raise SessionBlocked("shadow_lab_resume_requires_unarchived_drain")
            self.store.resume_experiment(str(slot["experiment_id"]), resumed_at=now)
            self._phase(preview.target, "RUNNING", str(slot["experiment_id"]))
        elif preview.operation == "shadow.archive":
            if slot["phase"] not in {"DRAINING", "FINALIZED"}:
                raise SessionBlocked("shadow_lab_archive_requires_drain_or_finalize")
            censored = self.store.open_position_count(str(slot["experiment_id"]))
            self._phase(
                preview.target,
                "ARCHIVED_CENSORED" if censored else "ARCHIVED",
                str(slot["experiment_id"]),
            )
        elif preview.operation == "shadow.compare":
            other = self.slot(arguments["other"])
            if other is None or arguments["other"] not in self.targets:
                raise SessionBlocked("shadow_lab_comparison_target_denied")
            return {
                "effect": "OBSERVED",
                "comparison": self.compare(preview.target, arguments["other"]),
            }
        if preview.operation in {"shadow.drain", "shadow.finalize", "shadow.archive"}:
            self.incidents.record(
                "experiment_stopped",
                scope=preview.target,
                reason_code=preview.operation,
                next_action="Inspect retained holdings and lifecycle; do not infer closure",
            )
        return {"effect": "OBSERVED", "slot": self.slot(preview.target)}

    def service(self, target: str) -> ContinuousShadowService:
        slot = self.slot(target)
        if slot is None:
            raise SessionBlocked("shadow_lab_slot_unavailable")
        config = self.templates[slot["policy_digest"]]
        if (
            self._config_digest(config) != slot["config_digest"]
            or self.selection.digest != slot["selection_digest"]
        ):
            raise SessionBlocked("frozen_shadow_config_changed")
        selected = ContinuousSelectionSnapshot.create(
            source_id=self._scope(target),
            selection_run_id=digest((target, self.selection.selection_run_id)),
            source_snapshot_id=self.selection.source_snapshot_id,
            feature_set_version=self.selection.feature_set_version,
            policy_id=self.selection.policy_id,
            policy_version=self.selection.policy_version,
            ranking_version=self.selection.ranking_version,
            published_at=self.selection.published_at,
            candidates=self.selection.candidates,
        )
        return ContinuousShadowService(
            self.store,
            _FrozenCandidates(selected),
            ContinuousShadowLeaseRepository(self.store.path),
            lambda leaders: CorroboratedLeaderSource(
                CorroboratedSessionSource(
                    self.transport,
                    self.chain,
                    maximum_pages=config.source_max_pages,
                    clock=self.clock,
                ),
                {leader: dict(self.source_plan.wallets)[leader] for leader in leaders},
                clock=self.clock,
            ),
            BoundedMarketAdapter(self.transport),
            config=config,
            clock=self.clock,
            automatic_rollover=False,
        )

    async def close(self) -> None:
        await self.rpc_http.aclose()

    def _config_digest(self, config: ContinuousShadowConfig) -> str:
        return digest((config.to_dict(), asdict(self.source_plan), self.acquisition.policy.digest))

    async def poll(self, target: str) -> dict[str, Any]:
        slot = self.slot(target)
        if slot is None or slot["phase"] not in {"RUNNING", "DRAINING"}:
            raise SessionBlocked("shadow_lab_slot_not_pollable")
        return (await self.service(target).poll(self._scope(target))).to_dict()

    def compare(self, left: str, right: str) -> dict[str, Any]:
        slots = [self.slot(target) for target in (left, right)]
        if any(slot is None or not slot["experiment_id"] for slot in slots):
            raise SessionBlocked("shadow_lab_started_experiments_required")
        actual = [slot for slot in slots if slot is not None]
        if actual[0]["selection_digest"] != actual[1]["selection_digest"]:
            raise SessionBlocked("shadow_lab_cohorts_not_comparable")
        configs = [self.templates[slot["policy_digest"]] for slot in actual]
        comparable = all(
            getattr(configs[0], name) == getattr(configs[1], name)
            for name in (
                "follower_bankroll",
                "cost_model_version",
                "bankroll_version",
                "maximum_quote_age_ms",
                "maximum_forward_delay_ms",
            )
        )
        results = [self.store.results(str(slot["experiment_id"]), limit=1000) for slot in actual]
        return {
            "version": "shadow-lab-comparison/v1",
            "common_assumptions": comparable,
            "same_frozen_input_stream": "UNKNOWN_UNLESS_TAPE_DIGEST_MATCHES",
            "targets": [left, right],
            "results": results,
            "sum_of_returns": None,
            "accuracy_percent": None,
            "acquisition_budget": self.acquisition.status(),
        }

    def slot(self, target: str) -> dict[str, Any] | None:
        if target not in self.targets:
            raise SessionBlocked("shadow_lab_target_denied")
        with closing(sqlite3.connect(self.store.path)) as connection:
            connection.row_factory = sqlite3.Row
            row = connection.execute(
                "SELECT * FROM continuous_shadow_lab_slots WHERE target=?", (target,)
            ).fetchone()
            return None if row is None else dict(row)

    def console_view(self) -> dict[str, Any]:
        """Registered public choices; excludes endpoints, credentials and private evidence."""
        return {
            "version": "shadow-lab-publication/v1",
            "published_at": self.clock().isoformat(),
            "experiments": [
                slot for target in sorted(self.targets) if (slot := self.slot(target)) is not None
            ],
            "targets": sorted(self.targets),
            "policies": [
                {
                    "digest": identity,
                    "version": template.copy_policy.version,
                    "capital": str(template.follower_bankroll),
                    "unit": None,
                    "cost_model": template.cost_model_version,
                    "cohort": self.selection.digest,
                    "window": (
                        f"{template.period_duration_seconds} seconds configured; "
                        "observed window is separate"
                    ),
                }
                for identity, template in sorted(self.templates.items())
                if template.copy_policy is not None
            ],
            "acquisition": self.acquisition.status(),
            "incidents": self.incidents.projection(),
            "financial_authority": "ABSENT",
            "virtual_capital": "ISOLATED_PER_EXPERIMENT",
        }

    def _phase(self, target: str, phase: str, experiment_id: str) -> None:
        with closing(sqlite3.connect(self.store.path)) as connection, connection:
            connection.execute(
                "UPDATE continuous_shadow_lab_slots SET phase=?,experiment_id=?,updated_at=? "
                "WHERE target=?",
                (phase, experiment_id, self.clock().isoformat(), target),
            )

    @staticmethod
    def _scope(target: str) -> str:
        return "shadow-lab:" + target
