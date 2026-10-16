"""Numeric authority for new Platform public-data acquisition only."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import datetime
from urllib.parse import urlsplit


@dataclass(frozen=True, slots=True)
class AcquisitionPolicy:
    policy_id: str
    host: str
    starts_at: datetime
    expires_at: datetime
    endpoints: tuple[str, ...]
    maximum_requests: int
    maximum_bytes: int
    maximum_response_bytes: int
    timeout_seconds: int
    minimum_free_disk_bytes: int
    cohort_limit: int
    cadence_seconds: int
    retention_days: int
    backup_generations: int
    memory_max_bytes: int
    cpu_quota_percent: int
    window_seconds: int = 3600
    window_maximum_requests: int = 300
    window_maximum_bytes: int = 16_777_216
    closure_request_reserve: int = 0
    closure_byte_reserve: int = 0

    def __post_init__(self) -> None:
        if not self.policy_id or not self.host or not self.endpoints:
            raise ValueError("policy identity, host and endpoints are required")
        for value in (self.starts_at, self.expires_at):
            offset = value.utcoffset()
            if value.tzinfo is None or offset is None:
                raise ValueError("policy timestamps must be UTC")
            if offset.total_seconds() != 0:
                raise ValueError("policy timestamps must be UTC")
        if self.expires_at <= self.starts_at:
            raise ValueError("policy expiry must follow start")
        limits = (
            self.maximum_requests, self.maximum_bytes, self.maximum_response_bytes,
            self.timeout_seconds, self.minimum_free_disk_bytes, self.cohort_limit,
            self.cadence_seconds, self.retention_days, self.backup_generations,
            self.memory_max_bytes, self.cpu_quota_percent,
            self.window_seconds, self.window_maximum_requests, self.window_maximum_bytes,
        )
        if any(type(value) is not int or value <= 0 for value in limits):
            raise ValueError("all policy limits must be positive integers")
        if self.maximum_response_bytes > self.maximum_bytes or self.backup_generations < 2:
            raise ValueError("invalid byte reserve or backup generations")
        if (type(self.closure_request_reserve) is not int
                or type(self.closure_byte_reserve) is not int
                or not 0 <= self.closure_request_reserve < self.maximum_requests
                or not 0 <= self.closure_byte_reserve < self.maximum_bytes):
            raise ValueError("closure reserves must fit inside total authority")
        if self.timeout_seconds > 30 or self.cpu_quota_percent > 100:
            raise ValueError("policy exceeds conservative process ceilings")
        if len(set(self.endpoints)) != len(self.endpoints):
            raise ValueError("duplicate endpoint")
        for endpoint in self.endpoints:
            parsed = urlsplit(endpoint)
            if (parsed.scheme != "https" or not parsed.hostname or parsed.query
                    or parsed.fragment or parsed.username or parsed.password):
                raise ValueError("policy endpoints must be exact public HTTPS paths")

    def to_dict(self) -> dict[str, object]:
        result = asdict(self)
        result["starts_at"] = self.starts_at.isoformat()
        result["expires_at"] = self.expires_at.isoformat()
        return result

    @property
    def digest(self) -> str:
        raw = json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(raw.encode()).hexdigest()
