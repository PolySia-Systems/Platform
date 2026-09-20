"""Versioned Polycop follow-set selection for prospective Canary/Main runs.

Reuses the current Stage 3 copyability snapshot. It does not rank wallets
and does not fall back to public trade discovery.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from polysia.adapters.polymarket.research_sources import public_wallet_alias
from polysia.application.ports.continuous_shadow import (
    ContinuousSelectionSnapshot,
    ContinuousSelectionUnavailableError,
)
from polysia.application.ports.dynamic_shadow import ProtectedShadowCandidate
from polysia.storage.dynamic_shadow import DynamicShadowRepository

POLYCOP_SHADOW_ALPHA_TOP3_V1 = "polycop-shadow-alpha-top3-v1"
POLYCOP_SHADOW_ALPHA_CONFIGURED_V1 = "polycop-shadow-alpha-configured-v1"
POLYCOP_SHADOW_ALPHA_ACTIVE_TOP3_V1 = "polycop-shadow-alpha-active-top3-v1"
POLYCOP_SOURCE_ID = "polycop"
SHADOW_ALPHA_POOL = "SHADOW_ALPHA"
DEFAULT_WALLET_LIMIT = 3
MAXIMUM_SELECTION_AGE = timedelta(hours=36)
FRESHNESS_BOUND = "PT36H"
DEFAULT_SELECTION_DATABASE = Path("/var/lib/polysia/data/wallet-intelligence.sqlite3")
RECONSTRUCTION_NAME = "selection-reconstruction.json"


class ResearchWalletSelectionError(RuntimeError):
    """Fail-closed Polycop follow-set resolution failure."""


@dataclass(frozen=True, slots=True)
class FrozenPolycopFollowSet:
    policy_version: str
    selection_run_id: str
    source_id: str
    source_snapshot_id: str
    published_at: datetime
    feature_set_version: str
    selection_policy_id: str
    selection_policy_version: str
    ranking_version: str
    selected_pools: tuple[str, ...]
    selected_ranks: tuple[int, ...]
    wallet_ids: tuple[str, ...]
    aliases: tuple[str, ...]
    ranked_aliases: tuple[str, ...]
    snapshot_digest: str
    selection_digest: str
    reconstruction_digest: str
    addresses_by_alias: dict[str, str]
    reasons: tuple[str, ...]


def load_current_polycop_snapshot(
    database: Path,
    *,
    source_id: str = POLYCOP_SOURCE_ID,
) -> ContinuousSelectionSnapshot:
    try:
        return DynamicShadowRepository(database).current_snapshot(source_id)
    except ContinuousSelectionUnavailableError as error:
        raise ResearchWalletSelectionError("current Polycop selection is unavailable") from error
    except (OSError, sqlite3.Error) as error:
        raise ResearchWalletSelectionError("current Polycop selection is unavailable") from error


def resolve_polycop_shadow_alpha_top3(
    snapshot: ContinuousSelectionSnapshot,
    *,
    now: datetime | None = None,
    wallet_limit: int = DEFAULT_WALLET_LIMIT,
    maximum_age: timedelta = MAXIMUM_SELECTION_AGE,
) -> FrozenPolycopFollowSet:
    """Select the highest-ranked distinct SHADOW_ALPHA wallets fail-closed."""

    return resolve_polycop_follow_set(
        snapshot,
        now=now,
        wallet_limit=wallet_limit,
        maximum_age=maximum_age,
        policy_version=POLYCOP_SHADOW_ALPHA_TOP3_V1,
    )


def resolve_polycop_follow_set(
    snapshot: ContinuousSelectionSnapshot,
    *,
    now: datetime | None = None,
    wallet_limit: int = DEFAULT_WALLET_LIMIT,
    maximum_age: timedelta = MAXIMUM_SELECTION_AGE,
    policy_version: str | None = None,
) -> FrozenPolycopFollowSet:
    """Select highest-ranked distinct SHADOW_ALPHA wallets for a frozen policy."""

    if wallet_limit < 1:
        raise ResearchWalletSelectionError("wallet limit must be positive")
    policy = policy_version or (
        POLYCOP_SHADOW_ALPHA_TOP3_V1
        if wallet_limit == DEFAULT_WALLET_LIMIT
        else POLYCOP_SHADOW_ALPHA_CONFIGURED_V1
    )
    _validate_snapshot(snapshot, observed=now or datetime.now(UTC), maximum_age=maximum_age)
    selected = _top_alpha_wallets(snapshot.candidates, wallet_limit=wallet_limit)
    if len(selected) < wallet_limit:
        raise ResearchWalletSelectionError("Polycop SHADOW_ALPHA selection is insufficient")
    ranks = tuple(int(candidate.alpha_rank or 0) for candidate in selected)
    reasons = tuple(
        f"highest-ranked distinct SHADOW_ALPHA at alpha_rank={rank}" for rank in ranks
    )
    return _freeze_follow_set(
        snapshot,
        selected=selected,
        policy=policy,
        reasons=reasons,
    )


def resolve_polycop_active_follow_set(
    snapshot: ContinuousSelectionSnapshot,
    activity_counts: Mapping[str, int],
    *,
    now: datetime | None = None,
    wallet_limit: int = DEFAULT_WALLET_LIMIT,
    maximum_age: timedelta = MAXIMUM_SELECTION_AGE,
) -> FrozenPolycopFollowSet:
    """Select recent-active SHADOW_ALPHA wallets without using economic outcomes."""

    if wallet_limit != DEFAULT_WALLET_LIMIT:
        raise ResearchWalletSelectionError(
            "activity-aware Polycop selection currently requires three wallets"
        )
    _validate_snapshot(snapshot, observed=now or datetime.now(UTC), maximum_age=maximum_age)
    eligible = [
        candidate
        for candidate in snapshot.candidates
        if SHADOW_ALPHA_POOL in candidate.pools
        and candidate.alpha_rank is not None
        and activity_counts.get(candidate.wallet_id, 0) > 0
    ]
    eligible.sort(
        key=lambda item: (
            -activity_counts.get(item.wallet_id, 0),
            int(item.alpha_rank or 0),
            item.wallet_id,
        )
    )
    selected: list[ProtectedShadowCandidate] = []
    seen: set[str] = set()
    for candidate in eligible:
        if candidate.wallet_id in seen:
            continue
        if not candidate.address:
            raise ResearchWalletSelectionError("Polycop selected wallet is missing an address")
        seen.add(candidate.wallet_id)
        selected.append(candidate)
        if len(selected) == wallet_limit:
            break
    if len(selected) < wallet_limit:
        raise ResearchWalletSelectionError(
            "recent-active Polycop SHADOW_ALPHA selection is insufficient"
        )
    reasons = tuple(
        "recent-active SHADOW_ALPHA "
        f"event_count={activity_counts[candidate.wallet_id]} "
        f"alpha_rank={int(candidate.alpha_rank or 0)}"
        for candidate in selected
    )
    return _freeze_follow_set(
        snapshot,
        selected=tuple(selected),
        policy=POLYCOP_SHADOW_ALPHA_ACTIVE_TOP3_V1,
        reasons=reasons,
    )


def _validate_snapshot(
    snapshot: ContinuousSelectionSnapshot,
    *,
    observed: datetime,
    maximum_age: timedelta,
) -> None:
    if observed.tzinfo is None or observed.utcoffset() != timedelta(0):
        raise ResearchWalletSelectionError("selection clock must be timezone-aware UTC")
    expected = ContinuousSelectionSnapshot.create(
        source_id=snapshot.source_id,
        selection_run_id=snapshot.selection_run_id,
        source_snapshot_id=snapshot.source_snapshot_id,
        feature_set_version=snapshot.feature_set_version,
        policy_id=snapshot.policy_id,
        policy_version=snapshot.policy_version,
        ranking_version=snapshot.ranking_version,
        published_at=snapshot.published_at,
        candidates=snapshot.candidates,
    )
    if expected.digest != snapshot.digest:
        raise ResearchWalletSelectionError("Polycop selection digest mismatch")
    if snapshot.source_id != POLYCOP_SOURCE_ID:
        raise ResearchWalletSelectionError("Polycop selection source is inconsistent")
    if snapshot.published_at > observed:
        raise ResearchWalletSelectionError("Polycop selection is from the future")
    if observed - snapshot.published_at > maximum_age:
        raise ResearchWalletSelectionError("Polycop selection is stale")


def _freeze_follow_set(
    snapshot: ContinuousSelectionSnapshot,
    *,
    selected: tuple[ProtectedShadowCandidate, ...],
    policy: str,
    reasons: tuple[str, ...],
) -> FrozenPolycopFollowSet:
    ranked_aliases = tuple(public_wallet_alias(candidate.address) for candidate in selected)
    addresses_by_alias = {
        alias: candidate.address for alias, candidate in zip(ranked_aliases, selected, strict=True)
    }
    if len(addresses_by_alias) != len(selected):
        raise ResearchWalletSelectionError("Polycop selected aliases are not distinct")
    aliases = tuple(sorted(addresses_by_alias))
    wallet_ids = tuple(candidate.wallet_id for candidate in selected)
    ranks = tuple(int(candidate.alpha_rank or 0) for candidate in selected)
    public = _canonical_public_payload(
        aliases=aliases,
        feature_set_version=snapshot.feature_set_version,
        policy_id=snapshot.policy_id,
        policy_version=snapshot.policy_version,
        published_at=snapshot.published_at,
        ranking_version=snapshot.ranking_version,
        selected_ranks=ranks,
        selection_run_id=snapshot.selection_run_id,
        snapshot_digest=snapshot.digest,
        source_id=snapshot.source_id,
        source_snapshot_id=snapshot.source_snapshot_id,
        wallet_ids=wallet_ids,
        wallet_limit=len(selected),
        selection_policy_version=policy,
    )
    reconstruction = _canonical_reconstruction_payload(
        selected_wallets=_selected_wallets(selected, ranked_aliases),
        wallet_ids=wallet_ids,
    )
    return FrozenPolycopFollowSet(
        policy_version=policy,
        selection_run_id=snapshot.selection_run_id,
        source_id=snapshot.source_id,
        source_snapshot_id=snapshot.source_snapshot_id,
        published_at=snapshot.published_at,
        feature_set_version=snapshot.feature_set_version,
        selection_policy_id=snapshot.policy_id,
        selection_policy_version=snapshot.policy_version,
        ranking_version=snapshot.ranking_version,
        selected_pools=(SHADOW_ALPHA_POOL,),
        selected_ranks=ranks,
        wallet_ids=wallet_ids,
        aliases=aliases,
        ranked_aliases=ranked_aliases,
        snapshot_digest=snapshot.digest,
        selection_digest=_digest(public),
        reconstruction_digest=_digest(reconstruction),
        addresses_by_alias=dict(addresses_by_alias),
        reasons=reasons,
    )


def public_selection_payload(selection: FrozenPolycopFollowSet) -> dict[str, object]:
    payload = _canonical_public_payload(
        aliases=selection.aliases,
        feature_set_version=selection.feature_set_version,
        policy_id=selection.selection_policy_id,
        policy_version=selection.selection_policy_version,
        published_at=selection.published_at,
        ranking_version=selection.ranking_version,
        selected_ranks=selection.selected_ranks,
        selection_run_id=selection.selection_run_id,
        snapshot_digest=selection.snapshot_digest,
        source_id=selection.source_id,
        source_snapshot_id=selection.source_snapshot_id,
        wallet_ids=selection.wallet_ids,
        wallet_limit=len(selection.wallet_ids),
        selection_policy_version=selection.policy_version,
    )
    payload["reconstruction_digest"] = selection.reconstruction_digest
    payload["selection_digest"] = selection.selection_digest
    payload["selection_policy"] = selection.policy_version
    payload["wallet_count"] = len(selection.wallet_ids)
    payload["selection_reasons"] = list(selection.reasons)
    return payload


def reconstruction_payload(selection: FrozenPolycopFollowSet) -> dict[str, object]:
    selected_wallets = [
        {
            "alpha_rank": selection.selected_ranks[index],
            "wallet_address": selection.addresses_by_alias[alias],
            "wallet_alias": alias,
            "wallet_id": selection.wallet_ids[index],
        }
        for index, alias in enumerate(selection.ranked_aliases)
    ]
    payload = _canonical_reconstruction_payload(
        selected_wallets=selected_wallets,
        wallet_ids=selection.wallet_ids,
    )
    payload["digest"] = selection.reconstruction_digest
    payload["selection_digest"] = selection.selection_digest
    payload["selection_reasons"] = list(selection.reasons)
    return payload


def verify_reconstruction(
    payload: Mapping[str, object],
    public: Mapping[str, object],
) -> dict[str, str]:
    wallets = payload.get("selected_wallets")
    wallet_ids = payload.get("wallet_ids")
    if not isinstance(wallets, list) or not isinstance(wallet_ids, list):
        raise ResearchWalletSelectionError("frozen selection reconstruction is invalid")
    selected_wallets: list[dict[str, object]] = []
    addresses: dict[str, str] = {}
    ranked_ids: list[str] = []
    for row in wallets:
        if not isinstance(row, Mapping):
            raise ResearchWalletSelectionError("frozen selection reconstruction is invalid")
        alias = str(row.get("wallet_alias") or "")
        address = str(row.get("wallet_address") or "")
        wallet_id = str(row.get("wallet_id") or "")
        rank = row.get("alpha_rank")
        if not alias or not address or not wallet_id or not isinstance(rank, int):
            raise ResearchWalletSelectionError("frozen selection reconstruction is invalid")
        if public_wallet_alias(address) != alias:
            raise ResearchWalletSelectionError("frozen selection alias does not match address")
        selected_wallets.append(
            {
                "alpha_rank": rank,
                "wallet_address": address,
                "wallet_alias": alias,
                "wallet_id": wallet_id,
            }
        )
        addresses[alias] = address
        ranked_ids.append(wallet_id)
    if ranked_ids != [str(item) for item in wallet_ids]:
        raise ResearchWalletSelectionError("frozen selection wallet identity is inconsistent")
    reconstructed = _canonical_reconstruction_payload(
        selected_wallets=selected_wallets,
        wallet_ids=tuple(ranked_ids),
    )
    digest = _digest(reconstructed)
    recorded = str(payload.get("digest") or "")
    expected = str(public.get("reconstruction_digest") or "")
    if digest != recorded or digest != expected:
        raise ResearchWalletSelectionError("frozen selection reconstruction digest mismatch")
    limit_value = public.get("wallet_limit")
    wallet_limit = len(ranked_ids)
    if isinstance(limit_value, int) and not isinstance(limit_value, bool):
        wallet_limit = limit_value
    elif isinstance(limit_value, str) and limit_value.isdigit():
        wallet_limit = int(limit_value)
    canonical = _canonical_public_payload(
        aliases=tuple(sorted(addresses)),
        feature_set_version=str(public.get("feature_set_version") or ""),
        policy_id=str(public.get("policy_id") or ""),
        policy_version=str(public.get("policy_version") or ""),
        published_at=_published_at(public.get("published_at")),
        ranking_version=str(public.get("ranking_version") or ""),
        selected_ranks=tuple(int(item) for item in _ints(public.get("selected_ranks"))),
        selection_run_id=str(public.get("selection_run_id") or ""),
        snapshot_digest=str(public.get("snapshot_digest") or ""),
        source_id=str(public.get("source_id") or ""),
        source_snapshot_id=str(public.get("source_snapshot_id") or ""),
        wallet_ids=tuple(ranked_ids),
        wallet_limit=wallet_limit,
        selection_policy_version=str(
            public.get("selection_policy_version") or POLYCOP_SHADOW_ALPHA_TOP3_V1
        ),
    )
    if _string_list(canonical["aliases"]) != _string_list(public.get("aliases")):
        raise ResearchWalletSelectionError("frozen selection aliases are inconsistent")
    if _digest(canonical) != str(public.get("selection_digest") or ""):
        raise ResearchWalletSelectionError("frozen selection digest mismatch")
    if str(payload.get("selection_digest") or "") != str(public.get("selection_digest") or ""):
        raise ResearchWalletSelectionError("frozen selection digest mismatch")
    return addresses


def _top_alpha_wallets(
    candidates: tuple[ProtectedShadowCandidate, ...],
    *,
    wallet_limit: int,
) -> tuple[ProtectedShadowCandidate, ...]:
    ranked = [
        candidate
        for candidate in candidates
        if SHADOW_ALPHA_POOL in candidate.pools and candidate.alpha_rank is not None
    ]
    ranked.sort(key=lambda item: (int(item.alpha_rank or 0), item.wallet_id))
    selected: list[ProtectedShadowCandidate] = []
    seen: set[str] = set()
    for candidate in ranked:
        if candidate.wallet_id in seen:
            continue
        if SHADOW_ALPHA_POOL not in candidate.pools:
            continue
        if not candidate.address:
            raise ResearchWalletSelectionError("Polycop selected wallet is missing an address")
        seen.add(candidate.wallet_id)
        selected.append(candidate)
        if len(selected) >= wallet_limit:
            break
    return tuple(selected)


def _selected_wallets(
    selected: tuple[ProtectedShadowCandidate, ...],
    ranked_aliases: tuple[str, ...],
) -> list[dict[str, object]]:
    return [
        {
            "alpha_rank": int(candidate.alpha_rank or 0),
            "wallet_address": candidate.address,
            "wallet_alias": alias,
            "wallet_id": candidate.wallet_id,
        }
        for alias, candidate in zip(ranked_aliases, selected, strict=True)
    ]


def _canonical_public_payload(
    *,
    aliases: tuple[str, ...],
    feature_set_version: str,
    policy_id: str,
    policy_version: str,
    published_at: datetime,
    ranking_version: str,
    selected_ranks: tuple[int, ...],
    selection_run_id: str,
    snapshot_digest: str,
    source_id: str,
    source_snapshot_id: str,
    wallet_ids: tuple[str, ...],
    wallet_limit: int,
    selection_policy_version: str,
) -> dict[str, object]:
    return {
        "aliases": list(aliases),
        "feature_set_version": feature_set_version,
        "freshness_bound": FRESHNESS_BOUND,
        "policy_id": policy_id,
        "policy_version": policy_version,
        "published_at": published_at.isoformat(),
        "ranking_version": ranking_version,
        "selected_pools": [SHADOW_ALPHA_POOL],
        "selected_ranks": list(selected_ranks),
        "selection_policy_version": selection_policy_version,
        "selection_run_id": selection_run_id,
        "snapshot_digest": snapshot_digest,
        "source_id": source_id,
        "source_snapshot_id": source_snapshot_id,
        "wallet_ids": list(wallet_ids),
        "wallet_limit": wallet_limit,
    }


def _canonical_reconstruction_payload(
    *,
    selected_wallets: list[dict[str, object]],
    wallet_ids: tuple[str, ...],
) -> dict[str, object]:
    return {
        "selected_wallets": selected_wallets,
        "wallet_ids": list(wallet_ids),
    }


def _published_at(value: object) -> datetime:
    observed = value if isinstance(value, datetime) else datetime.fromisoformat(str(value))
    if observed.tzinfo is None or observed.utcoffset() != timedelta(0):
        raise ResearchWalletSelectionError("frozen selection published_at is invalid")
    return observed


def _ints(value: object) -> list[int]:
    if not isinstance(value, list):
        return []
    return [int(item) for item in value]


def _string_list(value: object) -> list[str]:
    if isinstance(value, list | tuple):
        return [str(item) for item in value]
    return []


def _digest(payload: dict[str, object]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(encoded.encode()).hexdigest()
