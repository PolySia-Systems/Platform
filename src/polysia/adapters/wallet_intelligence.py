"""Read the independent producer's public JSON artifact, never its database."""

from __future__ import annotations

import hashlib
import json
import math
from collections import Counter
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

from pydantic import ValidationError

from polysia.adapters.wallet_intelligence_contract import Publication, SourceReference
from polysia.application.ports.wallet_intelligence_research import ResearchPublicationError
from polysia.domain.wallet_intelligence.research_intake import (
    ResearchWalletPublication,
    ResearchWalletRecord,
)

MAX_ARTIFACT_BYTES = 8_388_608


def canonical(value: object) -> str:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    )


def _unique_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ResearchPublicationError("duplicate_json_key")
        result[key] = value
    return result


def _invalid_constant(value: str) -> Any:
    raise ResearchPublicationError("nonfinite_json_number")


def _finite_json_number(value: str) -> float:
    result = float(value)
    if not math.isfinite(result):
        raise ResearchPublicationError("nonfinite_json_number")
    return result


def _utc(value: str) -> datetime:
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ResearchPublicationError("invalid_timestamp") from exc
    if result.tzinfo is None or result.utcoffset() != timedelta(0):
        raise ResearchPublicationError("non_utc_timestamp")
    return result


def _money(value: str | None) -> Decimal | None:
    if value is None:
        return None
    try:
        result = Decimal(value)
    except InvalidOperation as exc:
        raise ResearchPublicationError("invalid_decimal") from exc
    if not result.is_finite():
        raise ResearchPublicationError("nonfinite_decimal")
    return result


def _reference_key(ref: SourceReference) -> tuple[object, ...]:
    return (ref.run_id, ref.query_id, ref.page, ref.fetched_at, ref.url, ref.body_digest)


def _validate_semantics(source: Publication) -> None:
    cutoff, decision, generated, expiry = map(
        _utc,
        (source.data_cutoff, source.evaluation_at, source.generated_at, source.expires_at),
    )
    if not cutoff <= decision <= generated < expiry or expiry - generated > timedelta(hours=24):
        raise ResearchPublicationError("publication_clock_order")
    if _utc(source.coverage.discovery_at) > cutoff:
        raise ResearchPublicationError("discovery_from_future")
    if source.status == "COMPLETE_FOR_SCOPE" and source.coverage.missing_partitions:
        raise ResearchPublicationError("hidden_partial_coverage")
    references = {_reference_key(ref) for ref in source.source_references}
    for ref in source.source_references:
        if ref.run_id != source.run_id:
            raise ResearchPublicationError("foreign_run_evidence")
        if _utc(ref.fetched_at) > generated:
            raise ResearchPublicationError("reference_from_future")
    ids: list[str] = []
    ranks: list[tuple[int, str]] = []
    for record in source.records:
        account = record.identity.account_wallet.lower()
        expected = f"{record.identity.venue}:{record.identity.chain_id}:{account}"
        if record.wallet_id != expected or expected in ids:
            raise ResearchPublicationError("conflicting_wallet_identity")
        ids.append(expected)
        if _utc(record.computed_at) != decision:
            raise ResearchPublicationError("record_clock_mismatch")
        record_expiry = _utc(record.expires_at)
        if record.fetched_at is not None and _utc(record.fetched_at) > generated:
            raise ResearchPublicationError("record_fetch_from_future")
        for ref in record.evidence_references:
            if _reference_key(ref) not in references:
                raise ResearchPublicationError("unlinked_record_evidence")
            url = urlsplit(ref.url)
            if url.path in {"/v2/activity", "/v2/user-pnl", "/v2/user-stats"} and parse_qs(
                url.query
            ).get("user") != [record.identity.account_wallet]:
                raise ResearchPublicationError("foreign_wallet_evidence")
        perf, activity = record.performance, record.activity
        value = _money(perf.value)
        for component in perf.components.values():
            _money(component.value)
        if (
            (perf.state == "POSITIVE" and (value is None or value <= 0))
            or (perf.state == "NON_POSITIVE" and (value is None or value > 0))
            or (perf.state == "UNKNOWN" and value is not None)
        ):
            raise ResearchPublicationError("performance_state_mismatch")
        if _utc(activity.window_end) != cutoff or cutoff - _utc(activity.window_start) != timedelta(
            days=activity.window_days,
        ):
            raise ResearchPublicationError("activity_window_mismatch")
        if record.observed_at != perf.source_observed_at:
            raise ResearchPublicationError("source_observation_mismatch")
        if record.observed_at is not None and _utc(record.observed_at) > cutoff:
            raise ResearchPublicationError("source_observation_from_future")
        if activity.state == "INACTIVE" and (
            activity.acquisition != "COMPLETE_FOR_QUERY"
            or activity.source_rows != 0
            or activity.last_trade_at is not None
            or activity.issues
        ):
            raise ResearchPublicationError("unsupported_inactive_claim")
        if record.outcome != "CANDIDATE":
            if record.candidate_rank is not None:
                raise ResearchPublicationError("ineligible_candidate_rank")
            continue
        if (
            activity.state != "ACTIVE"
            or activity.issues
            or activity.source_rows < 1
            or perf.state != "POSITIVE"
            or perf.freshness != "FRESH"
            or record.freshness != "FRESH"
            or record.quality.descriptive != "AVAILABLE"
            or perf.source_fidelity != "1d"
            or record.data_validity != "VALID"
            or record.candidate_rank is None
            or not record.evidence_references
            or record_expiry <= generated
            or record_expiry < expiry
            or perf.start is None
            or perf.end is None
            or activity.last_trade_at is None
        ):
            raise ResearchPublicationError("unsupported_candidate")
        start, end, trade = map(_utc, (perf.start, perf.end, activity.last_trade_at))
        start_anchor = cutoff - timedelta(days=perf.target_days)
        if (
            not start < end <= cutoff
            or perf.source_observed_at != perf.end
            or decision - end > timedelta(hours=24)
            or not start_anchor - timedelta(days=1) <= start <= start_anchor
            or not cutoff - timedelta(days=1) <= end
            or not _utc(activity.window_start) <= trade <= cutoff
            or perf.span_seconds != int((end - start).total_seconds())
            or record_expiry > end + timedelta(hours=24)
            or record_expiry > trade + timedelta(days=activity.window_days)
        ):
            raise ResearchPublicationError("unsupported_candidate_window")
        position = perf.components.get("position_pnl")
        if position is None or _money(position.value) != value:
            raise ResearchPublicationError("primary_component_mismatch")
        ranks.append((record.candidate_rank, expected))
    if ids != sorted(ids):
        raise ResearchPublicationError("noncanonical_record_order")
    ranks.sort()
    if [rank for rank, _ in ranks] != list(range(1, len(ranks) + 1)) or source.candidates != [
        wallet for _, wallet in ranks
    ]:
        raise ResearchPublicationError("candidate_projection_mismatch")
    coverage = source.coverage
    actual = Counter(record.outcome for record in source.records)
    expected_counts = {
        key: actual[key] for key in ("CANDIDATE", "WATCHLIST", "EXCLUDED", "DATA_HOLD")
    }
    if (
        coverage.examined != len(source.records)
        or coverage.discovered < coverage.examined
        or coverage.unexamined != coverage.discovered - coverage.examined
        or coverage.published != len(ranks)
        or coverage.outcomes != expected_counts
        or sum(coverage.outcomes.values()) != coverage.examined
        or coverage.active != sum(r.activity.state == "ACTIVE" for r in source.records)
        or coverage.performance_supported
        != sum(r.performance.state != "UNKNOWN" for r in source.records)
    ):
        raise ResearchPublicationError("coverage_counts_mismatch")


class WalletIntelligenceArtifactSource:
    """Platform-owned file adapter with bounded reads and validated provenance."""

    def __init__(self, path: Path) -> None:
        self.path = path

    def read_publication(self) -> ResearchWalletPublication:
        try:
            with self.path.open("rb") as handle:
                raw = handle.read(MAX_ARTIFACT_BYTES + 1)
        except OSError as exc:
            raise ResearchPublicationError("artifact_unavailable") from exc
        if len(raw) > MAX_ARTIFACT_BYTES:
            raise ResearchPublicationError("artifact_size_limit")
        try:
            data = json.loads(
                raw,
                object_pairs_hook=_unique_pairs,
                parse_constant=_invalid_constant,
                parse_float=_finite_json_number,
            )
            source = Publication.model_validate(data)
            analytical = {
                key: value
                for key, value in data.items()
                if key not in {"snapshot_digest", "diagnostics"}
            }
            encoded = canonical(analytical)
            if hashlib.sha256(encoded.encode("utf-8")).hexdigest() != source.snapshot_digest:
                raise ResearchPublicationError("snapshot_digest_mismatch")
            _validate_semantics(source)
        except ResearchPublicationError:
            raise
        except (ValidationError, ValueError, TypeError, OverflowError, RecursionError) as exc:
            raise ResearchPublicationError("invalid_artifact_schema") from exc
        records = tuple(
            ResearchWalletRecord(
                record.wallet_id,
                record.identity.account_wallet.lower(),
                record.candidate_rank,
                record.outcome,
                record.data_validity,
                record.activity.state,
                record.performance.state,
                _money(record.performance.value),
                _utc(record.observed_at) if record.observed_at else None,
                _utc(record.expires_at),
                tuple(record.reasons),
                canonical(original),
            )
            for record, original in zip(source.records, data["records"], strict=True)
        )
        return ResearchWalletPublication(
            "wallet-intelligence",
            source.schema_version,
            source.run_id,
            source.snapshot_digest,
            _utc(source.data_cutoff),
            _utc(source.evaluation_at),
            _utc(source.generated_at),
            _utc(source.expires_at),
            source.status,
            tuple(sorted(data["capabilities"].items())),
            records,
            encoded,
        )
