"""Revalidate the admitted native cohort without resetting its financial session."""

from __future__ import annotations

import json
import os
from collections.abc import Callable
from contextlib import nullcontext
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from polysia.adapters.polymarket.bounded_market import BoundedMarketAdapter
from polysia.adapters.polymarket.bounded_transport import BoundedPublicTransport
from polysia.adapters.polymarket.data_api_v2 import (
    IncompleteWalletWindowError,
    MalformedWalletWindowError,
)
from polysia.adapters.polymarket.native_discovery import (
    revalidate_native_cohort,
    revalidate_native_watch,
)
from polysia.application.ports.continuous_shadow import ContinuousPollOutcome
from polysia.cli_support.native_research import (
    NativeSnapshotPort,
    native_shadow_service,
    publish_native_health,
)
from polysia.domain.copytrading.continuous_shadow import ContinuousShadowLifecycle
from polysia.domain.copytrading.native_health import (
    PURPOSE as HEALTH_PURPOSE,
)
from polysia.domain.copytrading.native_health import (
    RUNTIME as HEALTH_RUNTIME,
)
from polysia.domain.copytrading.native_health import (
    WATCH_PROFILE,
    validate_health_admission,
)
from polysia.domain.copytrading.native_run_limits import NativeRunLimits
from polysia.monitoring.latency_intelligence.identity import load_runtime_identity
from polysia.monitoring.latency_intelligence.recorder import LatencyRecorder
from polysia.monitoring.process_capacity import ProcessCapacity
from polysia.storage.acquisition_authority import AcquisitionAuthority, AcquisitionBlockedError
from polysia.storage.continuous_shadow import ContinuousShadowRepository
from polysia.storage.latency_telemetry import LatencyTelemetryStore


def validate_native_admission(
    discovery: dict[str, Any],
    admission: dict[str, Any],
    *,
    code_sha: str,
    now: datetime,
    authority: AcquisitionAuthority,
) -> None:
    if now.utcoffset() != timedelta(0):
        raise AcquisitionBlockedError("clock_not_UTC")
    if (
        authority.status()["stopped"]
        or not authority.policy.starts_at <= now < authority.policy.expires_at
    ):
        raise AcquisitionBlockedError("authority_not_current")
    if discovery.get("profile") == WATCH_PROFILE:
        try:
            validate_health_admission(
                admission,
                code_sha=code_sha,
                watch_digest=discovery.get("digest"),
                now=now,
            )
            if (
                authority.policy.purpose != HEALTH_PURPOSE
                or admission.get("policy_digest") != authority.policy.digest
                or datetime.fromisoformat(admission["expires_at"]) > authority.policy.expires_at
            ):
                raise ValueError("native health authority purpose or expiry mismatch")
            NativeRunLimits.from_admission(admission)
        except (ValueError, KeyError, TypeError) as error:
            raise AcquisitionBlockedError("native_health_admission_invalid") from error
        return
    if authority.policy.purpose == HEALTH_PURPOSE:
        raise AcquisitionBlockedError("native_health_cannot_admit_legacy_research")
    if (
        admission.get("contract") != "native-research-admission/v1"
        or admission.get("mode") != "CONTINUOUS"
        or admission.get("code_sha") != code_sha
        or admission.get("cohort_digest") != discovery.get("digest")
        or type(admission.get("persisted_simulations")) is not int
        or admission["persisted_simulations"] < 1
        or admission.get("resource_admitted") is not True
    ):
        raise AcquisitionBlockedError("native_admission_mismatched_or_insufficient")
    try:
        expires = datetime.fromisoformat(admission["expires_at"])
    except (KeyError, TypeError, ValueError) as error:
        raise AcquisitionBlockedError("native_admission_expiry_required") from error
    if expires.utcoffset() != timedelta(0) or expires <= now:
        raise AcquisitionBlockedError("native_admission_expired")
    try:
        NativeRunLimits.from_admission(admission)
    except ValueError as error:
        raise AcquisitionBlockedError("native_run_limits_invalid") from error


async def native_lifecycle_poll(
    database: Path,
    discovery: dict[str, Any],
    *,
    authority: AcquisitionAuthority,
    code_sha: str,
    admission: dict[str, Any],
    refresh_path: Path,
    clock: Callable[[], datetime],
) -> ContinuousPollOutcome:
    """One bounded due slot. No rollover, implicit funding or manufactured admission."""
    validate_native_admission(
        discovery, admission, code_sha=code_sha, now=clock(), authority=authority
    )
    health = discovery.get("profile") == WATCH_PROFILE
    initial = NativeSnapshotPort(discovery)
    if len(initial.snapshot.candidates) > authority.policy.cohort_limit:
        raise AcquisitionBlockedError("native_cohort_exceeds_policy")
    identity_path = database.with_suffix(database.suffix + ".session.json")
    retained_identity = None
    if identity_path.exists():
        if identity_path.is_symlink() or identity_path.stat().st_size > 4096:
            raise AcquisitionBlockedError("native_financial_identity_invalid")
        retained_identity = json.loads(identity_path.read_text(encoding="utf-8"))
        if not database.is_file() or database.is_symlink():
            raise AcquisitionBlockedError("retained_financial_session_missing")
    store = ContinuousShadowRepository(database)
    store.initialize()
    active = store.active_experiment("polymarket-native")
    if retained_identity is not None and (
        active is None
        or retained_identity
        != {
            "schema": "native-financial-session/v1",
            "experiment_id": active.experiment_id,
            "code_sha": code_sha,
            "cohort_digest": discovery["digest"],
        }
    ):
        raise AcquisitionBlockedError("native_financial_identity_mismatch")
    if active is not None and (
        active.config.code_sha != code_sha
        or active.config.runtime_version
        != (HEALTH_RUNTIME if health else "continuous-shadow-native-research-v2")
        or active.config.selection_preflight_digest != discovery["digest"]
        or active.config.capacity_evidence != admission
    ):
        raise AcquisitionBlockedError("active_financial_session_requires_pinned_release")
    close_only = active is not None and active.lifecycle is ContinuousShadowLifecycle.DRAINING
    refreshed = None
    last_checked = None
    if refresh_path.exists():
        if refresh_path.is_symlink() or refresh_path.stat().st_size > 1_048_576:
            raise AcquisitionBlockedError("native_refresh_receipt_too_large")
        retained = json.loads(refresh_path.read_text(encoding="utf-8"))
        if (
            retained.get("code_sha") != code_sha
            or retained.get("original_cohort_digest") != discovery["digest"]
        ):
            raise AcquisitionBlockedError("native_refresh_identity_mismatch")
        if health:
            if retained.get("contract") != "native-health-revalidation/v1":
                raise AcquisitionBlockedError("native_health_refresh_contract_mismatch")
            last_checked = datetime.fromisoformat(retained["checked_at"])
            if last_checked.utcoffset() != timedelta(0) or last_checked > clock():
                raise AcquisitionBlockedError("native_health_refresh_clock_invalid")
            refreshed = retained.get("eligibility")
        else:
            refreshed = retained["discovery"]
    current = initial if health or refreshed is None else NativeSnapshotPort(refreshed)
    age = clock() - current.snapshot.published_at
    if age < timedelta(0):
        raise AcquisitionBlockedError("native_cohort_clock_regressed")
    # Revalidation is charged to the same standing authority, at most once per
    # three hours when successful, and only in an already durable due slot.
    # Entry eligibility is unnecessary for the retained cohort's close-only work.
    # Never spend the closure reserve rediscovering whether new exposure is eligible;
    # the service still requires complete source and current market evidence to close.
    due = (
        (last_checked is None or clock() - last_checked >= timedelta(hours=3))
        if health
        else (age >= timedelta(hours=3))
    )

    def retain_health(outcome: str, detail: str | None = None) -> None:
        payload = {
            "contract": "native-health-revalidation/v1",
            "code_sha": code_sha,
            "original_cohort_digest": discovery["digest"],
            "checked_at": clock().isoformat(),
            "outcome": outcome,
            "detail": detail,
            "eligibility": refreshed,
        }
        refresh_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = refresh_path.with_suffix(".partial")
        temporary.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
        temporary.replace(refresh_path)

    if due and not close_only:
        transport = BoundedPublicTransport(authority)
        recorder = None
        capacity = None
        try:
            recorder = LatencyRecorder(
                LatencyTelemetryStore(database.with_name("native-latency.sqlite3")),
                load_runtime_identity(venue_id="polymarket"),
            )
            recorder.begin_trace(operation="cohort_revalidation")
            recorder.bind_poll(
                poll_run_id=None, experiment_id=(None if active is None else active.experiment_id)
            )
            capacity = ProcessCapacity()
        except Exception:
            pass  # Optional instrumentation cannot grant or block economic work.
        try:
            with (
                recorder.span(component="native", operation="cohort_revalidation")
                if (recorder is not None)
                else nullcontext()
            ):
                candidate = await (revalidate_native_watch if health else revalidate_native_cohort)(
                    discovery,
                    transport,
                    BoundedMarketAdapter(transport),
                    clock=clock,
                )
            invalid = [
                c
                for c in candidate["candidates"]
                if c["execution_eligibility"] != "ELIGIBLE_FOR_RESEARCH"
            ]
            quiet = bool(invalid) and all(
                c.get("state") == "NO_COMPLETE_ACTIVITY"
                and c.get("complete_activity_rows") == c.get("window_filtered_rows", 0)
                for c in invalid
            )
            if health:
                if len(invalid) < len(candidate["candidates"]):
                    refreshed = candidate  # Only actual qualified evidence can renew entry.
                retain_health(
                    "HEALTHY_EMPTY"
                    if quiet
                    else "ENTRY_UNQUALIFIED"
                    if invalid
                    else "ENTRY_QUALIFIED"
                )
            elif quiet:
                if age >= timedelta(hours=4):
                    raise AcquisitionBlockedError("native_cohort_no_recent_activity")
                # Existing evidence still has its ORIGINAL observation time. It
                # never becomes a refreshed selection; the four-hour bound holds.
            elif invalid:
                raise AcquisitionBlockedError("native_cohort_revalidation_insufficient")
            else:
                refreshed = candidate
                payload = {
                    "code_sha": code_sha,
                    "original_cohort_digest": discovery["digest"],
                    "discovery": refreshed,
                }
                refresh_path.parent.mkdir(parents=True, exist_ok=True)
                temporary = refresh_path.with_suffix(".partial")
                temporary.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
                temporary.replace(refresh_path)
        except IncompleteWalletWindowError as error:
            if health:
                retain_health("SOURCE_INCOMPLETE", type(error).__name__)
            else:
                raise AcquisitionBlockedError("native_cohort_revalidation_incomplete") from error
        except MalformedWalletWindowError as error:
            if health:
                retain_health("SOURCE_INVALID", type(error).__name__)
            else:
                raise AcquisitionBlockedError("native_cohort_revalidation_invalid") from error
        except (TypeError, ValueError) as error:
            if health:
                if isinstance(error, TypeError):
                    raise AcquisitionBlockedError(
                        "native_health_revalidation_processing_fault",
                    ) from error
                retain_health("SOURCE_INVALID", type(error).__name__)
            else:
                raise AcquisitionBlockedError("native_cohort_revalidation_invalid") from error
        except AcquisitionBlockedError as error:
            if health:
                retain_health("SOURCE_UNAVAILABLE", error.error_code)
            raise
        finally:
            publish_native_health(recorder, capacity, stage="cohort_revalidation")
    if health and authority.status()["uncertain_requests"]:
        authority.stop()
        raise AcquisitionBlockedError("native_health_shared_accounting_uncertain")
    service = native_shadow_service(
        database,
        discovery,
        authority=authority,
        code_sha=code_sha,
        admission=admission,
        persistent=True,
        refreshed_discovery=refreshed,
        clock=clock,
        closure=close_only,
    )
    if active is None:
        active = service.start("polymarket-native")
    if retained_identity is None:
        identity = {
            "schema": "native-financial-session/v1",
            "experiment_id": active.experiment_id,
            "code_sha": code_sha,
            "cohort_digest": discovery["digest"],
        }
        temporary = identity_path.with_suffix(identity_path.suffix + ".partial")
        if temporary.is_symlink() or temporary.exists() and temporary.stat().st_nlink != 1:
            raise AcquisitionBlockedError("native_financial_identity_staging_invalid")
        descriptor = os.open(
            temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | getattr(os, "O_NOFOLLOW", 0), 0o600
        )
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(json.dumps(identity, sort_keys=True))
            stream.flush()
            os.fsync(stream.fileno())
        if os.name != "nt":
            temporary.chmod(0o600)
        temporary.replace(identity_path)
        if os.name != "nt":
            parent = os.open(identity_path.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
            try:
                os.fsync(parent)
            finally:
                os.close(parent)
    outcome = await service.poll("polymarket-native")
    if health and authority.status()["uncertain_requests"]:
        authority.stop()
        raise AcquisitionBlockedError("native_health_shared_accounting_uncertain")
    if health and authority.status()["stopped"]:
        raise AcquisitionBlockedError("native_health_authority_stopped_during_poll")
    return outcome
