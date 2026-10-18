"""Revalidate the admitted native cohort without resetting its financial session."""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from polysia.adapters.polymarket.bounded_market import BoundedMarketAdapter
from polysia.adapters.polymarket.bounded_transport import BoundedPublicTransport
from polysia.adapters.polymarket.data_api_v2 import IncompleteWalletWindowError
from polysia.adapters.polymarket.native_discovery import revalidate_native_cohort
from polysia.application.ports.continuous_shadow import ContinuousPollOutcome
from polysia.cli_support.native_research import NativeSnapshotPort, native_shadow_service
from polysia.domain.copytrading.continuous_shadow import ContinuousShadowLifecycle
from polysia.storage.acquisition_authority import AcquisitionAuthority, AcquisitionBlockedError
from polysia.storage.continuous_shadow import ContinuousShadowRepository


def validate_native_admission(
    discovery: dict[str, Any], admission: dict[str, Any], *,
    code_sha: str, now: datetime, authority: AcquisitionAuthority,
) -> None:
    if now.utcoffset() != timedelta(0):
        raise AcquisitionBlockedError("clock_not_UTC")
    if (authority.status()["stopped"]
            or not authority.policy.starts_at <= now < authority.policy.expires_at):
        raise AcquisitionBlockedError("authority_not_current")
    if (admission.get("contract") != "native-research-admission/v1"
            or admission.get("mode") != "CONTINUOUS"
            or admission.get("code_sha") != code_sha
            or admission.get("cohort_digest") != discovery.get("digest")
            or type(admission.get("persisted_simulations")) is not int
            or admission["persisted_simulations"] < 1
            or admission.get("resource_admitted") is not True):
        raise AcquisitionBlockedError("native_admission_mismatched_or_insufficient")
    try:
        expires = datetime.fromisoformat(admission["expires_at"])
    except (KeyError, TypeError, ValueError) as error:
        raise AcquisitionBlockedError("native_admission_expiry_required") from error
    if expires.utcoffset() != timedelta(0) or expires <= now:
        raise AcquisitionBlockedError("native_admission_expired")


async def native_lifecycle_poll(
    database: Path, discovery: dict[str, Any], *, authority: AcquisitionAuthority,
    code_sha: str, admission: dict[str, Any], refresh_path: Path,
    clock: Callable[[], datetime],
) -> ContinuousPollOutcome:
    """One bounded due slot. No rollover, implicit funding or manufactured admission."""
    validate_native_admission(discovery, admission, code_sha=code_sha,
                              now=clock(), authority=authority)
    initial = NativeSnapshotPort(discovery)
    if len(initial.snapshot.candidates) > authority.policy.cohort_limit:
        raise AcquisitionBlockedError("native_cohort_exceeds_policy")
    store = ContinuousShadowRepository(database)
    store.initialize()
    active = store.active_experiment("polymarket-native")
    if active is not None and (active.config.code_sha != code_sha
                              or active.config.runtime_version
                              != "continuous-shadow-native-research-v2"
                              or active.config.selection_preflight_digest != discovery["digest"]
                              or active.config.capacity_evidence != admission):
        raise AcquisitionBlockedError("active_financial_session_requires_pinned_release")
    close_only = active is not None and active.lifecycle is ContinuousShadowLifecycle.DRAINING
    refreshed = None
    if refresh_path.exists():
        if refresh_path.stat().st_size > 1_048_576:
            raise AcquisitionBlockedError("native_refresh_receipt_too_large")
        retained = json.loads(refresh_path.read_text(encoding="utf-8"))
        if (retained.get("code_sha") != code_sha
                or retained.get("original_cohort_digest") != discovery["digest"]):
            raise AcquisitionBlockedError("native_refresh_identity_mismatch")
        refreshed = retained["discovery"]
    current = initial if refreshed is None else NativeSnapshotPort(refreshed)
    age = clock() - current.snapshot.published_at
    if age < timedelta(0):
        raise AcquisitionBlockedError("native_cohort_clock_regressed")
    # Revalidation is charged to the same standing authority, at most once per
    # three hours when successful, and only in an already durable due slot.
    # Entry eligibility is unnecessary for the retained cohort's close-only work.
    # Never spend the closure reserve rediscovering whether new exposure is eligible;
    # the service still requires complete source and current market evidence to close.
    if age >= timedelta(hours=3) and not close_only:
        transport = BoundedPublicTransport(authority)
        try:
            refreshed = await revalidate_native_cohort(
                discovery, transport, BoundedMarketAdapter(transport), clock=clock,
            )
        except IncompleteWalletWindowError as error:
            raise AcquisitionBlockedError("native_cohort_revalidation_incomplete") from error
        except (TypeError, ValueError) as error:
            raise AcquisitionBlockedError("native_cohort_revalidation_invalid") from error
        if any(c["execution_eligibility"] != "ELIGIBLE_FOR_RESEARCH"
               for c in refreshed["candidates"]):
            raise AcquisitionBlockedError("native_cohort_revalidation_insufficient")
        payload = {"code_sha": code_sha, "original_cohort_digest": discovery["digest"],
                   "discovery": refreshed}
        refresh_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = refresh_path.with_suffix(".partial")
        temporary.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
        temporary.replace(refresh_path)
    service = native_shadow_service(
        database, discovery, authority=authority, code_sha=code_sha, admission=admission,
        persistent=True, refreshed_discovery=refreshed, clock=clock,
        closure=close_only,
    )
    if active is None:
        service.start("polymarket-native")
    return await service.poll("polymarket-native")
