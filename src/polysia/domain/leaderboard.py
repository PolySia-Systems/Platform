"""Read-only ranking observations with separate provider rank and row order."""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Literal

Period = Literal["day", "week", "month", "all"]
Ranking = Literal["PNL", "VOLUME"]
PERIODS: tuple[Period, ...] = ("day", "week", "month", "all")
RANKINGS: tuple[Ranking, ...] = ("PNL", "VOLUME")
CATEGORIES = ("overall", "sports", "politics", "crypto")
REFERENCES = ("PolyCop", "Rivo", "PolyIntel")


@dataclass(frozen=True, slots=True)
class Board:
    venue: str
    period: Period
    ranking: Ranking
    category: str = "overall"
    discovery_only: bool = False

    def __post_init__(self) -> None:
        if self.period not in PERIODS or self.ranking not in RANKINGS:
            raise ValueError("unsupported_board")
        if self.category not in CATEGORIES:
            raise ValueError("unsupported_category")
        if self.discovery_only and (
            self.category != "overall"
            or self.ranking != "PNL"
            or self.period not in ("month", "all")
        ):
            raise ValueError("unsupported_discovery_scope")

    @property
    def depth(self) -> int:
        if self.discovery_only:
            return 3000
        if self.category == "overall" and self.ranking == "PNL" and self.period in ("month", "all"):
            return 1000
        return 100

    @property
    def key(self) -> str:
        return f"{self.venue}:traders:v1:{self.category}:{self.period}:{self.ranking}:{self.depth}"


@dataclass(frozen=True, slots=True)
class Standing:
    wallet: str
    name: str | None
    rank: int
    pnl: Decimal
    volume: Decimal


@dataclass(frozen=True, slots=True)
class Observation:
    board: Board
    rows: tuple[Standing, ...]
    started_at: datetime
    fetched_at: datetime
    outcome: Literal["complete", "partial", "failed"]
    reason: str | None
    has_more: bool | None
    request_count: int
    byte_count: int
    retry_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class Activity:
    wallet: str
    since: int
    through: int
    latest: int | None
    trade_count: int
    market_count: int
    complete: bool


@dataclass(frozen=True, slots=True)
class ReferenceCapture:
    source: str
    captured_at: datetime
    scope: str
    method: str
    wallets: tuple[str, ...]
    complete: bool
