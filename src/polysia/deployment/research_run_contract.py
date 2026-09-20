"""Versioned research-run Spec, immutable Plan, and admission.

Not a generic workflow engine. Safety cannot be overridden by a Spec.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal

from polysia.application.services.persistent_prospective_collector import (
    SERVICE_POLICY_VERSION,
)
from polysia.config.settings import TradingMode
from polysia.deployment.research_run_profiles import (
    PROFILE_CANARY,
    PROFILE_MAIN,
    RunnerProfile,
    resolve_profile,
)
from polysia.domain.research_evidence.collector import COLLECTOR_POLICY_VERSION
from polysia.domain.research_evidence.economic_contract import CONTRACT_V1
from polysia.domain.research_evidence.models import RESEARCH_EVIDENCE_SCHEMA_VERSION
from polysia.domain.research_evidence.replay import REPLAY_ENGINE_VERSION

SPEC_VERSION = "research-run-spec-v1"
PLAN_VERSION = "research-run-plan-v1"
DEFAULT_SELECTION_POLICY = "polycop-shadow-alpha-top3-v1"
CONFIGURED_SELECTION_POLICY = "polycop-shadow-alpha-configured-v1"
ACTIVE_SELECTION_POLICY = "polycop-shadow-alpha-active-top3-v1"
DEFAULT_WALLET_COUNT = 3
OPERATIONAL_WALLET_COUNT_BOUND = 3
LEGACY_SELECTION_POLICY = "legacy-cli-sources"
EXECUTABLE_EXPRESSION_RE = re.compile(
    r"(?is)(__import__|\beval\s*\(|\bexec\s*\(|\$\{|\{\{)"
)
IMMUTABLE_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
SPEC_FIELDS = frozenset(
    {
        "code_sha",
        "image_sha",
        "profile",
        "run_id",
        "selection_policy",
        "spec_version",
        "wallet_count",
    }
)
PLAN_SEMANTIC_KEYS = (
    "budgets",
    "code_sha",
    "collector_policy_version",
    "dynamic_market_discovery",
    "economic_contract",
    "image_sha",
    "plan_version",
    "profile",
    "profile_version",
    "replay_engine_version",
    "research_schema_version",
    "safety",
    "selection",
    "service_policy_version",
)


class ResearchRunContractError(ValueError):
    """Actionable Spec/Plan validation failure."""


@dataclass(frozen=True, slots=True)
class ResearchRunSpec:
    profile: str
    code_sha: str
    image_sha: str | None = None
    run_id: str | None = None
    wallet_count: int | None = None
    selection_policy: str | None = None
    spec_version: str = SPEC_VERSION


@dataclass(frozen=True, slots=True)
class ResearchRunPlan:
    profile: str
    profile_version: str
    code_sha: str
    image_sha: str
    budgets: dict[str, int]
    selection: dict[str, object]
    versions: dict[str, str]
    dynamic_market_discovery: dict[str, object]
    safety: dict[str, object]
    economic_contract: dict[str, object]
    run_id: str | None = None
    generated_at: str | None = None
    plan_version: str = PLAN_VERSION

    def semantic_payload(self) -> dict[str, object]:
        return {
            "budgets": dict(self.budgets),
            "code_sha": self.code_sha,
            "collector_policy_version": self.versions["collector_policy_version"],
            "dynamic_market_discovery": dict(self.dynamic_market_discovery),
            "economic_contract": dict(self.economic_contract),
            "image_sha": self.image_sha,
            "plan_version": self.plan_version,
            "profile": self.profile,
            "profile_version": self.profile_version,
            "replay_engine_version": self.versions["replay_engine_version"],
            "research_schema_version": self.versions["research_schema_version"],
            "safety": dict(self.safety),
            "selection": dict(self.selection),
            "service_policy_version": self.versions["service_policy_version"],
        }

    def semantic_digest(self) -> str:
        return canonical_digest(self.semantic_payload())

    def to_dict(self) -> dict[str, object]:
        payload = self.semantic_payload()
        payload["generated_at"] = self.generated_at
        payload["run_id"] = self.run_id
        payload["semantic_digest"] = self.semantic_digest()
        return payload


def parse_research_run_spec(payload: Mapping[str, object]) -> ResearchRunSpec:
    unknown = sorted(set(payload) - SPEC_FIELDS)
    if unknown:
        raise ResearchRunContractError(
            "unsupported research-run Spec field: " + ", ".join(unknown)
        )
    version = _require_text(payload.get("spec_version"), "spec_version")
    if version != SPEC_VERSION:
        raise ResearchRunContractError("research-run Spec version is not supported")
    _reject_executable(payload)
    profile = _require_text(payload.get("profile"), "profile")
    if profile not in {PROFILE_CANARY, PROFILE_MAIN}:
        raise ResearchRunContractError("research-run Spec profile is not supported")
    code_sha = _require_sha(payload.get("code_sha"), "code_sha")
    image_sha = payload.get("image_sha")
    run_id = payload.get("run_id")
    return ResearchRunSpec(
        profile=profile,
        code_sha=code_sha,
        image_sha=None if image_sha is None else _require_sha(image_sha, "image_sha"),
        run_id=None if run_id is None else _require_text(run_id, "run_id"),
        wallet_count=_optional_wallet_count(payload.get("wallet_count")),
        selection_policy=_optional_selection_policy(payload.get("selection_policy")),
    )


def spec_from_legacy(
    profile: str | RunnerProfile,
    *,
    code_sha: str,
    image_sha: str | None = None,
    run_id: str | None = None,
) -> tuple[ResearchRunSpec, RunnerProfile | None]:
    if isinstance(profile, RunnerProfile):
        return (
            ResearchRunSpec(
                profile=profile.name,
                code_sha=code_sha,
                image_sha=image_sha,
                run_id=run_id,
            ),
            profile,
        )
    return (
        ResearchRunSpec(
            profile=profile,
            code_sha=code_sha,
            image_sha=image_sha,
            run_id=run_id,
        ),
        None,
    )


def resolve_run_plan(
    spec: ResearchRunSpec,
    *,
    profile: RunnerProfile | None = None,
    observed: datetime | None = None,
) -> ResearchRunPlan:
    code_sha = _require_sha(spec.code_sha, "code_sha")
    image_sha = code_sha if spec.image_sha is None else _require_sha(spec.image_sha, "image_sha")
    if profile is None:
        resolved = _profile_for_spec(spec)
    else:
        if spec.profile != profile.name:
            raise ResearchRunContractError(
                "research-run Spec profile does not match the supplied profile"
            )
        resolved = profile
    generated = (observed or datetime.now(UTC)).astimezone(UTC)
    official = resolved.name in {PROFILE_CANARY, PROFILE_MAIN}
    selection = _selection_contract(spec, official=official)
    return ResearchRunPlan(
        profile=resolved.name,
        profile_version=resolved.version,
        code_sha=code_sha,
        image_sha=image_sha,
        budgets={
            "duration_seconds": int(resolved.duration.total_seconds()),
            "max_bytes": resolved.max_bytes,
            "max_events": resolved.max_events,
            "memory_bytes": resolved.memory_bytes,
            "window_count": resolved.window_count,
        },
        selection=selection,
        versions={
            "collector_policy_version": COLLECTOR_POLICY_VERSION,
            "replay_engine_version": REPLAY_ENGINE_VERSION,
            "research_schema_version": RESEARCH_EVIDENCE_SCHEMA_VERSION,
            "service_policy_version": SERVICE_POLICY_VERSION,
        },
        dynamic_market_discovery={
            "lookback_seconds": 1800,
            "policy": "followed-wallet-token-refresh-v1",
            "refresh_seconds": 1,
            "token_limit": 500,
            "warmup_seconds": 30,
        },
        safety={
            "live_token_allowlist": [],
            "live_trading_enabled": False,
            "overridable": False,
            "trading_mode": TradingMode.DATA_ONLY.value,
        },
        economic_contract=_decimal_safe(CONTRACT_V1.to_dict()),
        run_id=spec.run_id,
        generated_at=_utc_text(generated),
    )


def load_run_plan(payload: Mapping[str, object]) -> ResearchRunPlan:
    extra = {"generated_at", "run_id", "semantic_digest"}
    unknown = sorted(set(payload) - set(PLAN_SEMANTIC_KEYS) - extra)
    if unknown:
        raise ResearchRunContractError(
            "unsupported research-run Plan field: " + ", ".join(unknown)
        )
    _reject_executable(payload)
    if str(payload.get("plan_version")) != PLAN_VERSION:
        raise ResearchRunContractError("research-run Plan version is not supported")
    versions = {
        "collector_policy_version": _require_text(
            payload.get("collector_policy_version"), "collector_policy_version"
        ),
        "replay_engine_version": _require_text(
            payload.get("replay_engine_version"), "replay_engine_version"
        ),
        "research_schema_version": _require_text(
            payload.get("research_schema_version"), "research_schema_version"
        ),
        "service_policy_version": _require_text(
            payload.get("service_policy_version"), "service_policy_version"
        ),
    }
    budgets = _int_map(payload.get("budgets"), "budgets")
    plan = ResearchRunPlan(
        profile=_require_text(payload.get("profile"), "profile"),
        profile_version=_require_text(payload.get("profile_version"), "profile_version"),
        code_sha=_require_sha(payload.get("code_sha"), "code_sha"),
        image_sha=_require_sha(payload.get("image_sha"), "image_sha"),
        budgets=budgets,
        selection=_object_map(payload.get("selection"), "selection"),
        versions=versions,
        dynamic_market_discovery=_object_map(
            payload.get("dynamic_market_discovery"), "dynamic_market_discovery"
        ),
        safety=_object_map(payload.get("safety"), "safety"),
        economic_contract=_object_map(payload.get("economic_contract"), "economic_contract"),
        run_id=None if payload.get("run_id") is None else str(payload.get("run_id")),
        generated_at=None
        if payload.get("generated_at") is None
        else str(payload.get("generated_at")),
    )
    declared = payload.get("semantic_digest")
    if declared is not None and str(declared) != plan.semantic_digest():
        raise ResearchRunContractError("research-run Plan digest mismatch")
    return plan


def plans_semantically_equal(left: ResearchRunPlan, right: ResearchRunPlan) -> bool:
    return left.semantic_digest() == right.semantic_digest()


def canonical_dumps(payload: Mapping[str, object]) -> str:
    return json.dumps(
        _canonical(payload),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    )


def canonical_digest(payload: Mapping[str, object]) -> str:
    return hashlib.sha256(canonical_dumps(payload).encode("utf-8")).hexdigest()


def _selection_contract(spec: ResearchRunSpec, *, official: bool) -> dict[str, object]:
    if not official:
        if spec.wallet_count is not None or spec.selection_policy is not None:
            raise ResearchRunContractError(
                "wallet selection is only supported for canary and main research-run profiles"
            )
        return {
            "capacity": {
                "declared_operational_count": OPERATIONAL_WALLET_COUNT_BOUND,
                "operational_status": "not-applicable",
                "requested_count": None,
            },
            "policy": LEGACY_SELECTION_POLICY,
            "reasons_policy": "operator-supplied-sources",
            "reconstruction_required": False,
            "wallet_count": None,
        }
    count = DEFAULT_WALLET_COUNT if spec.wallet_count is None else spec.wallet_count
    requested_policy = spec.selection_policy
    if requested_policy == ACTIVE_SELECTION_POLICY and count != DEFAULT_WALLET_COUNT:
        raise ResearchRunContractError(
            "activity-aware selection currently requires exactly three wallets"
        )
    legacy_top3 = spec.wallet_count is None or count == DEFAULT_WALLET_COUNT
    policy = (
        requested_policy
        or (DEFAULT_SELECTION_POLICY if legacy_top3 else CONFIGURED_SELECTION_POLICY)
    )
    return {
        "capacity": {
            "declared_operational_count": OPERATIONAL_WALLET_COUNT_BOUND,
            "operational_status": "validated" if count == DEFAULT_WALLET_COUNT else "unverified",
            "requested_count": count,
        },
        "policy": policy,
        "reasons_policy": (
            "highest-recent-activity-within-shadow-alpha"
            if policy == ACTIVE_SELECTION_POLICY
            else "highest-ranked-distinct-shadow-alpha"
        ),
        "reconstruction_required": True,
        "wallet_count": count,
        **(
            {
                "activity_preflight": {
                    "candidate_limit": 50,
                    "lookback_seconds": 14_400,
                    "minimum_event_count": 1,
                    "source": "polymarket:data-api-v2:trades",
                }
            }
            if policy == ACTIVE_SELECTION_POLICY
            else {}
        ),
    }


def _optional_wallet_count(value: object) -> int | None:
    if value is None:
        return None
    count = _require_int(value, "wallet_count")
    if count < 1:
        raise ResearchRunContractError("wallet_count must be a positive integer")
    if count > OPERATIONAL_WALLET_COUNT_BOUND:
        raise ResearchRunContractError(
            "wallet_count is not an operationally supported capacity; "
            f"declared bound is {OPERATIONAL_WALLET_COUNT_BOUND}"
        )
    return count


def _optional_selection_policy(value: object) -> str | None:
    if value is None:
        return None
    policy = _require_text(value, "selection_policy")
    allowed = {
        ACTIVE_SELECTION_POLICY,
        CONFIGURED_SELECTION_POLICY,
        DEFAULT_SELECTION_POLICY,
    }
    if policy not in allowed:
        raise ResearchRunContractError("research-run selection_policy is not supported")
    return policy


def _profile_for_spec(spec: ResearchRunSpec) -> RunnerProfile:
    try:
        return resolve_profile(spec.profile)
    except ValueError as error:
        raise ResearchRunContractError("research-run Spec profile is not supported") from error


def _canonical(value: object) -> object:
    if isinstance(value, Mapping):
        return {
            str(key): _canonical(item)
            for key, item in sorted(value.items(), key=lambda row: str(row[0]))
        }
    if isinstance(value, list | tuple):
        return [_canonical(item) for item in value]
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, datetime):
        return _utc_text(value)
    if isinstance(value, bool) or value is None:
        return value
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    if isinstance(value, float):
        raise ResearchRunContractError(
            "binary floating-point is not allowed in research-run contracts"
        )
    return str(value)


def _decimal_safe(payload: Mapping[str, object]) -> dict[str, object]:
    converted = _canonical(payload)
    if not isinstance(converted, dict):
        raise ResearchRunContractError("economic contract serialization is invalid")
    return converted


def _reject_executable(payload: object) -> None:
    if isinstance(payload, Mapping):
        for item in payload.values():
            _reject_executable(item)
        return
    if isinstance(payload, list | tuple):
        for item in payload:
            _reject_executable(item)
        return
    if isinstance(payload, str) and EXECUTABLE_EXPRESSION_RE.search(payload):
        raise ResearchRunContractError("research-run Spec contains an executable expression")


def _require_text(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ResearchRunContractError(f"research-run field {field} is required")
    return value.strip()


def _require_sha(value: object, field: str) -> str:
    text = _require_text(value, field)
    if IMMUTABLE_SHA_RE.fullmatch(text) is None:
        raise ResearchRunContractError(
            f"research-run field {field} must be a lowercase 40-character Git SHA"
        )
    return text


def _int_map(value: object, field: str) -> dict[str, int]:
    mapping = _object_map(value, field)
    return {key: _require_int(item, f"{field}.{key}") for key, item in mapping.items()}


def _object_map(value: object, field: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise ResearchRunContractError(f"research-run field {field} must be an object")
    return {str(key): item for key, item in value.items()}


def _require_int(value: object, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ResearchRunContractError(f"research-run field {field} must be an integer")
    return value


def _utc_text(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")
