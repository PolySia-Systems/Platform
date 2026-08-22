from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal

type JsonValue = None | bool | int | str | Decimal | tuple[JsonValue, ...] | dict[str, JsonValue]

_SOURCE_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9._:-]{0,63}$")
_DIGEST_PATTERN = re.compile(r"^[a-f0-9]{64}$")


def _require_utc(value: datetime, *, field_name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    if value.astimezone(UTC).utcoffset() != value.utcoffset():
        raise ValueError(f"{field_name} must be UTC")


@dataclass(frozen=True, slots=True)
class CandidateWalletRecord:
    """One source row; the external wallet id is protected ingestion data."""

    external_wallet_id: str
    source_rank: int
    source_page: int
    metrics: dict[str, JsonValue]
    row_digest: str

    def __post_init__(self) -> None:
        if not self.external_wallet_id:
            raise ValueError("external_wallet_id is required")
        if self.source_rank < 1:
            raise ValueError("source_rank must be positive")
        if self.source_page < 1:
            raise ValueError("source_page must be positive")
        if not _DIGEST_PATTERN.fullmatch(self.row_digest):
            raise ValueError("row_digest must be a lowercase SHA-256 digest")
        if "address" in self.metrics:
            raise ValueError("metrics must not contain the protected wallet address")


@dataclass(frozen=True, slots=True)
class CandidateWalletDataset:
    """A complete, validated point-in-time source dataset."""

    source_id: str
    schema_version: str
    fetched_at: datetime
    source_total_pages: int
    records: tuple[CandidateWalletRecord, ...]
    dataset_digest: str

    def __post_init__(self) -> None:
        if not _SOURCE_ID_PATTERN.fullmatch(self.source_id):
            raise ValueError("source_id is invalid")
        if not self.schema_version:
            raise ValueError("schema_version is required")
        _require_utc(self.fetched_at, field_name="fetched_at")
        if self.source_total_pages < 1:
            raise ValueError("source_total_pages must be positive")
        if not self.records:
            raise ValueError("records must not be empty")
        if not _DIGEST_PATTERN.fullmatch(self.dataset_digest):
            raise ValueError("dataset_digest must be a lowercase SHA-256 digest")

        external_ids = {record.external_wallet_id for record in self.records}
        ranks = {record.source_rank for record in self.records}
        if len(external_ids) != len(self.records):
            raise ValueError("dataset contains duplicate external wallet ids")
        if len(ranks) != len(self.records):
            raise ValueError("dataset contains duplicate source ranks")
        if ranks != set(range(1, len(self.records) + 1)):
            raise ValueError("source ranks must be complete and contiguous")
