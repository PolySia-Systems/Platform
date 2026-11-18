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
VISIBLE_PNL_DEPTH = 1000
V1_DISCOVERY_DEPTH = 3000
MAX_DISCOVERY_DEPTH = 5000


@dataclass(frozen=True, slots=True)
class Board:
    venue: str
    period: Period
    ranking: Ranking
    category: str = "overall"
    discovery_only: bool = False
    discovery_depth: int = V1_DISCOVERY_DEPTH

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
        if (
            type(self.discovery_depth) is not int
            or not VISIBLE_PNL_DEPTH < self.discovery_depth <= MAX_DISCOVERY_DEPTH
            or (not self.discovery_only and self.discovery_depth != V1_DISCOVERY_DEPTH)
        ):
            raise ValueError("unsupported_discovery_depth")

    @property
    def depth(self) -> int:
        if self.discovery_only:
            return self.discovery_depth
        if self.category == "overall" and self.ranking == "PNL" and self.period in ("month", "all"):
            return VISIBLE_PNL_DEPTH
        return 100

    @property
    def query_key(self) -> str:
        return f"{self.venue}:traders:v1:{self.category}:{self.period}:{self.ranking}"

    @property
    def discovery_prefix(self) -> str:
        return f"{self.query_key}:discovery:"

    @property
    def key(self) -> str:
        # Keep the original 3,000-row series readable in existing evidence databases.
        if self.discovery_only and self.depth != V1_DISCOVERY_DEPTH:
            return f"{self.discovery_prefix}{self.depth}"
        return f"{self.query_key}:{self.depth}"


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
