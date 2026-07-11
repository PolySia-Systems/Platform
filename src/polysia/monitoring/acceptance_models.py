from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Literal

from polysia.config.settings import AppSettings

AuditCheckStatus = Literal["pass", "warn", "fail"]
AcceptanceResult = Literal["READY_FOR_SHADOW", "READY_FOR_TINY_LIVE", "NOT_READY"]
ReportFormat = Literal["json", "markdown", "html"]


def utc_now() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True, slots=True)
class AcceptanceAuditConfig:
    settings: AppSettings
    project_root: Path
    duration_minutes: int = 1
    market_slug: str | None = None
    token_id: str | None = None
    strategy: str = "stale-price"
    require_clean_git: bool = False
    allow_live_readonly: bool = False

    def __post_init__(self) -> None:
        if self.duration_minutes <= 0:
            raise ValueError("duration_minutes must be positive")
        if not self.strategy:
            raise ValueError("strategy must not be empty")


@dataclass(frozen=True, slots=True)
class AcceptanceAuditCheck:
    name: str
    status: AuditCheckStatus
    message: str
    remediation: str | None = None

    def to_dict(self) -> dict[str, str | None]:
        return {
            "message": self.message,
            "name": self.name,
            "remediation": self.remediation,
            "status": self.status,
        }


@dataclass(frozen=True, slots=True)
class ShadowProductionMetrics:
    total_runtime_seconds: Decimal
    total_events_received: int
    event_rate_per_second: Decimal
    stream_reconnect_count: int
    stale_event_count: int
    orderbook_update_count: int
    strategy_intent_count: int
    risk_approved_count: int
    risk_rejected_count: int
    paper_order_count: int
    paper_fill_count: int
    paper_pnl: Decimal
    max_paper_drawdown: Decimal
    average_decision_latency_ms: Decimal
    p95_decision_latency_ms: Decimal
    p99_decision_latency_ms: Decimal

    def to_dict(self) -> dict[str, int | str]:
        return {
            "average_decision_latency_ms": _decimal_to_str(
                self.average_decision_latency_ms
            ),
            "event_rate_per_second": _decimal_to_str(self.event_rate_per_second),
            "max_paper_drawdown": _decimal_to_str(self.max_paper_drawdown),
            "orderbook_update_count": self.orderbook_update_count,
            "p95_decision_latency_ms": _decimal_to_str(self.p95_decision_latency_ms),
            "p99_decision_latency_ms": _decimal_to_str(self.p99_decision_latency_ms),
            "paper_fill_count": self.paper_fill_count,
            "paper_order_count": self.paper_order_count,
            "paper_pnl": _decimal_to_str(self.paper_pnl),
            "risk_approved_count": self.risk_approved_count,
            "risk_rejected_count": self.risk_rejected_count,
            "stale_event_count": self.stale_event_count,
            "strategy_intent_count": self.strategy_intent_count,
            "stream_reconnect_count": self.stream_reconnect_count,
            "total_events_received": self.total_events_received,
            "total_runtime_seconds": _decimal_to_str(self.total_runtime_seconds),
        }


@dataclass(frozen=True, slots=True)
class AcceptanceAuditReport:
    timestamp: datetime
    final_result: AcceptanceResult
    reasons: tuple[str, ...]
    selected_market: dict[str, str | None]
    strategy: str
    safety_checks: tuple[AcceptanceAuditCheck, ...]
    system_checks: tuple[AcceptanceAuditCheck, ...]
    shadow_checks: tuple[AcceptanceAuditCheck, ...]
    metrics: ShadowProductionMetrics

    def to_dict(self) -> dict[str, object]:
        return {
            "final_result": self.final_result,
            "metrics": self.metrics.to_dict(),
            "reasons": list(self.reasons),
            "safety_checks": [check.to_dict() for check in self.safety_checks],
            "selected_market": self.selected_market,
            "shadow_checks": [check.to_dict() for check in self.shadow_checks],
            "strategy": self.strategy,
            "summary": _summarize_checks(
                self.safety_checks + self.system_checks + self.shadow_checks
            ),
            "system_checks": [check.to_dict() for check in self.system_checks],
            "timestamp": self.timestamp.isoformat(),
        }


def _summarize_checks(checks: tuple[AcceptanceAuditCheck, ...]) -> dict[str, int]:
    summary = {"fail": 0, "pass": 0, "warn": 0}
    for check in checks:
        summary[check.status] += 1
    return summary


def _decimal_to_str(value: Decimal) -> str:
    return format(value.normalize(), "f")
