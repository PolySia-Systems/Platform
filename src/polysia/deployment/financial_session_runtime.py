"""Default-disabled composition entry point. No injected production collaborators.

Live construction is deliberately lazy, after exact receipt/custody/config/code
checks. Tests may replace HTTP transport; all normalization, Risk, accounting,
receipt verification and persistence remain production owners.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from pydantic import TypeAdapter

from polysia.config.settings import TradingMode
from polysia.domain.copytrading.copy_policy import CopyPolicy
from polysia.domain.financial_session import (
    AccountObservation,
    RuntimeBinding,
    SessionAccountIdentity,
    SessionAuthorization,
    SessionBlocked,
    canonical_json,
    digest,
)
from polysia.risk.limits import RiskLimits
from polysia.security.session_authority import SessionCustody, SessionReceiptVerifier
from polysia.storage.atomic_files import read_publication_bytes
from polysia.storage.console_commands import ConsoleCommandStore
from polysia.storage.financial_session import FinancialSessionJournal


@dataclass(frozen=True, slots=True)
class SessionRuntimeConfig:
    version: int
    release: str
    package_tree_digest: str
    host: str
    policy: CopyPolicy
    account_mapping: SessionAccountIdentity
    financial_path: Path
    witness_root: Path
    custody_path: Path
    outbox_path: Path
    publication_path: Path
    cohort_path: Path
    follower_samples_path: Path
    cohort_file_digest: str
    follower_samples_file_digest: str
    source_wallets: tuple[tuple[str, str], ...]
    rpc_url: str
    exchange: str
    ctf: str
    collateral_adapter: str
    maximum_pages: int
    maximum_response_bytes: int
    maximum_queued: int
    request_timeout_seconds: int
    per_action_requests: tuple[tuple[str, int], ...]
    private_key_reference: str
    api_credentials_reference: str
    minimum_free_disk_bytes: int
    egress_allocation_receipt: str
    opening: AccountObservation
    risk_limits: RiskLimits
    maximum_order_shares: Decimal
    estimator_confidence: Decimal
    incident_path: Path
    commands_path: Path
    capacity_evidence_path: Path
    capacity_evidence_digest: str
    maximum_backup_age_seconds: int
    checkpoint_handshake_seconds: int
    tick_interval_seconds: int

    def __post_init__(self) -> None:
        if (
            self.version != 1
            or not self.release
            or not self.host
            or not self.egress_allocation_receipt
            or not 1 <= self.maximum_pages <= 100
            or not self.source_wallets
            or not 0 < self.maximum_queued <= 16
            or not 0 < self.request_timeout_seconds <= 30
            or not 0 < self.maximum_response_bytes <= 4_000_000
            or self.minimum_free_disk_bytes <= 0
        ):
            raise SessionBlocked("invalid_operational_configuration")
        if self.maximum_backup_age_seconds <= 0 or not 0 < self.checkpoint_handshake_seconds <= 5:
            raise SessionBlocked("bounded_supervision_configuration_required")
        if type(self.tick_interval_seconds) is not int or not 1 <= self.tick_interval_seconds <= 30:
            raise SessionBlocked("bounded_fixed_poll_cadence_required")
        if len(dict(self.source_wallets)) != len(self.source_wallets):
            raise SessionBlocked("duplicate_source_wallet_mapping")
        if len({wallet.lower() for _, wallet in self.source_wallets}) != len(
            self.source_wallets
        ) or any(
            re.fullmatch(r"[A-Za-z0-9._-]{1,64}", alias) is None
            or re.fullmatch(r"0x[0-9a-fA-F]{40}", wallet) is None
            for alias, wallet in self.source_wallets
        ):
            raise SessionBlocked("canonical_unique_source_mapping_required")
        if any(
            re.fullmatch(r"POLYSIA_[A-Z0-9_]{1,80}", reference) is None
            for reference in (self.private_key_reference, self.api_credentials_reference)
        ):
            raise SessionBlocked("protected_secret_reference_names_required")
        rpc = urlsplit(self.rpc_url)
        if (
            rpc.scheme != "https"
            or not rpc.hostname
            or rpc.username
            or rpc.password
            or rpc.query
            or rpc.fragment
        ):
            raise SessionBlocked("exact_nonsecret_HTTPS_RPC_required")
        paths = [
            self.financial_path,
            self.witness_root,
            self.custody_path,
            self.outbox_path,
            self.publication_path,
            self.cohort_path,
            self.follower_samples_path,
            self.commands_path,
            self.incident_path,
            self.capacity_evidence_path,
        ]
        if (
            any(
                not path.is_absolute() or any(part.is_symlink() for part in (path, *path.parents))
                for path in paths
            )
            or len({path.resolve() for path in paths}) != len(paths)
            or any(
                path.resolve().is_relative_to(self.publication_path.parent.resolve())
                for path in paths
                if path != self.publication_path
            )
            or self.custody_path.parent.resolve() == self.commands_path.parent.resolve()
        ):
            raise SessionBlocked("separate_absolute_protected_state_paths_required")
        if set(dict(self.per_action_requests)) != {
            "ACCOUNT",
            "SUBMIT",
            "CANCEL",
            "CANCELLATION_READ",
            "SOURCE",
            "MARKET",
        } or any(type(value) is not int or value <= 0 for _, value in self.per_action_requests):
            raise SessionBlocked("explicit_underlying_request_bounds_required")
        if not 0 < self.estimator_confidence < 1 or self.maximum_order_shares <= 0:
            raise SessionBlocked("explicit_policy_and_order_bounds_required")

    @property
    def fingerprint(self) -> str:
        value = asdict(self)
        for key, item in value.items():
            if isinstance(item, Path):
                value[key] = str(item)
        return digest(value)


def package_tree_digest(root: Path | None = None) -> str:
    root = root or Path(__file__).parents[1]
    hasher = hashlib.sha256()
    for path in sorted(root.rglob("*")):
        if path.is_file() and (path.suffix in {".py", ".sql", ".html", ".js", ".css"}
                               or "human_console_assets" in path.parts):
            hasher.update(path.relative_to(root).as_posix().encode())
            hasher.update(hashlib.sha256(path.read_bytes()).digest())
    return hasher.hexdigest()


def inspect_configuration(config: SessionRuntimeConfig) -> dict[str, Any]:
    return {
        "version": "operational-session/v1",
        "default_mode": "DATA_ONLY",
        "live_trading_enabled": False,
        "configuration_digest": config.fingerprint,
        "release": config.release,
        "policy_digest": config.policy.fingerprint,
        "package_tree_matches": config.package_tree_digest == package_tree_digest(),
        "authority": "NOT_VERIFIED_BY_INSPECTION",
        "account": "NOT_READ",
        "secret_references": {
            "signer": config.private_key_reference,
            "api": config.api_credentials_reference,
        },
        "commissioning": "PENDING",
        "financial_adapter": "NOT_CONSTRUCTED",
    }


def capacity_workload(config: SessionRuntimeConfig) -> str:
    return digest(
        {
            "package": config.package_tree_digest,
            "policy": config.policy.fingerprint,
            "wallets": len(config.source_wallets),
            "pages": config.maximum_pages,
            "response_bytes": config.maximum_response_bytes,
            "queue": config.maximum_queued,
            "timeout": config.request_timeout_seconds,
            "requests": config.per_action_requests,
            "egress": config.egress_allocation_receipt,
            "tick_interval_seconds": config.tick_interval_seconds,
        }
    )


def validate_capacity_record(config: SessionRuntimeConfig, *, now: datetime) -> dict[str, Any]:
    record = read_bound_json(
        config.capacity_evidence_path,
        config.capacity_evidence_digest,
        maximum_bytes=100_000,
        reason="capacity_qualification_evidence_changed",
    )
    if (
        record.get("version") != "financial-session-capacity/v1"
        or record.get("workload_digest") != capacity_workload(config)
        or record.get("host") != config.host
        or record.get("synthetic") is not False
        or record.get("status") != "PASS"
        or type(record.get("samples")) is not int
        or record["samples"] < 1
        or not datetime.fromisoformat(record["observed_at"])
        <= now
        < datetime.fromisoformat(record["expires_at"])
    ):
        raise SessionBlocked("operational_capacity_qualification_missing_or_inapplicable")
    return record


def binding_for(config: SessionRuntimeConfig) -> RuntimeBinding:
    return RuntimeBinding(
        config.release,
        config.fingerprint,
        config.policy.fingerprint,
        config.account_mapping.account_id,
        config.host,
    )


def validate_runtime_binding(config: SessionRuntimeConfig, authority: SessionAuthorization) -> None:
    if (
        authority.binding != binding_for(config)
        or config.package_tree_digest != package_tree_digest()
    ):
        raise SessionBlocked("operational_release_configuration_or_policy_changed")
    if (
        authority.version != 2
        or config.policy.quantity_quantum != Decimal("0.01")
        or authority.strategy != config.policy.version
        or authority.exit_policy != config.policy.version
        or authority.wallets != frozenset(dict(config.source_wallets))
        or config.opening.account != authority.binding.account
        or min(
            authority.protective_attempt_reserve,
            authority.protective_byte_reserve,
            authority.protective_storage_reserve,
            authority.protective_request_reserve,
            authority.protective_order_reserve,
        )
        <= 0
        or authority.protective_turnover_reserve <= 0
    ):
        raise SessionBlocked("composed_scope_or_protective_headroom_missing")
    if authority.binding.host != __import__("socket").gethostname():
        raise SessionBlocked("active_host_identity_mismatch")
    if config.tick_interval_seconds * 2 > authority.max_evidence_age_seconds:
        raise SessionBlocked("poll_cadence_exceeds_fresh_source_window")
    # Fixed conservative reserve for one complete bounded protective cycle:
    # account refreshes, quote/exit per position, cancellation and two four-read
    # finality observations per possible open order. No promise of market fill.
    bounds = dict(config.per_action_requests)
    protective_requests = (
        bounds["ACCOUNT"]
        + authority.max_positions * (3 * bounds["ACCOUNT"] + bounds["MARKET"] + bounds["SUBMIT"])
        + authority.max_concurrent_orders
        * (bounds["CANCEL"] + 8 * bounds["CANCELLATION_READ"] + bounds["ACCOUNT"])
    )
    protective_bytes = protective_requests * config.maximum_response_bytes
    if (
        authority.protective_request_reserve < protective_requests
        or authority.protective_byte_reserve < protective_bytes
        or authority.protective_storage_reserve < protective_bytes * 2 + 262144
        or authority.protective_attempt_reserve < authority.max_positions
        or authority.protective_turnover_reserve
        < authority.max_order_all_in * authority.max_positions
    ):
        raise SessionBlocked("protective_reserve_below_composed_bounded_cycle")


def provision_session(
    config: SessionRuntimeConfig,
    authority: SessionAuthorization,
    verifier: SessionReceiptVerifier,
    custody: SessionCustody,
    *,
    now: datetime,
) -> None:
    """Privileged local commissioning step, never called by the worker/browser.

    The opening read is a protected, signed-config observation acquired under a
    separate explicit account-read run. Provisioning cannot create that evidence.
    A claimed receipt remains consumed if this step crashes or fails.
    """
    validate_runtime_binding(config, authority)
    receipt = verifier.verify(authority, binding_for(config), now=now)
    config.opening.require_complete(
        authority.binding.account, now=now, max_age=authority.max_evidence_age_seconds
    )
    custody.claim(receipt, authority)
    journal = FinancialSessionJournal(config.financial_path, config.witness_root, authority)
    journal.provision(config.opening)
    ConsoleCommandStore(config.commands_path).initialize()


async def compose_session(
    config: SessionRuntimeConfig,
    *,
    authority: SessionAuthorization | None = None,
    verifier: SessionReceiptVerifier | None = None,
    mode: TradingMode = TradingMode.DATA_ONLY,
    live_enabled: bool = False,
    clock: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> Any:
    # This return precedes signer, SDK, custody, financial-store and network
    # construction, including in PAPER mode. A rehearsal uses Shadow separately.
    if mode is not TradingMode.LIVE or live_enabled is not True:
        return inspect_configuration(config)
    if authority is None or verifier is None:
        raise SessionBlocked("verified_owner_receipt_required_before_live_construction")
    validate_runtime_binding(config, authority)
    now = clock()
    action = (
        "ENTRY"
        if now < authority.expires_at
        else ("CANCEL" if "CANCEL" in authority.protective_actions else "REDUCE")
    )
    verifier.verify(authority, binding_for(config), now=now, action=action)
    custody = SessionCustody(config.custody_path)
    custody.require_current(authority, now=clock())
    from polysia.adapters.polymarket.session_composition import create_live_session

    return await create_live_session(config, authority, custody, clock=clock)


def load_runtime_config(path: Path) -> SessionRuntimeConfig:
    if path.is_symlink() or path.stat().st_size > 1_000_000:
        raise SessionBlocked("invalid_operational_configuration_file")
    return TypeAdapter(SessionRuntimeConfig).validate_json(path.read_bytes(), extra="forbid")


def load_authority(path: Path) -> SessionAuthorization:
    if path.is_symlink() or path.stat().st_size > 100_000:
        raise SessionBlocked("invalid_authority_file")
    return TypeAdapter(SessionAuthorization).validate_json(path.read_bytes(), extra="forbid")


def publish_redacted(path: Path, value: dict[str, Any]) -> None:
    if path.is_symlink():
        raise SessionBlocked("publication_symlink_denied")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".pending")
    temporary.write_text(canonical_json(value), encoding="utf-8")
    temporary.replace(path)


def read_small_json(path: Path) -> Any:
    if path.is_symlink() or path.stat().st_size > 4_000_000:
        raise SessionBlocked("retained_input_outside_bound")
    return json.loads(path.read_text(encoding="utf-8"))


def read_bound_json(
    path: Path,
    expected_sha256: str,
    *,
    maximum_bytes: int = 4_000_000,
    reason: str = "frozen_retained_input_changed",
) -> Any:
    """Hash and interpret the same bounded snapshot, including during rotation."""
    if path.is_symlink():
        raise SessionBlocked(reason)
    raw = read_publication_bytes(path, maximum_bytes=maximum_bytes)
    if hashlib.sha256(raw).hexdigest() != expected_sha256:
        raise SessionBlocked(reason)
    return json.loads(raw)
