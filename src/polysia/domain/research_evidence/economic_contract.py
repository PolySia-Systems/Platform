"""Frozen prospective economic experiment and executable-fill contract."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from polysia.domain.copytrading.continuous_shadow import calculate_taker_fee_amount
from polysia.domain.research_evidence.models import payload_digest

ECONOMIC_EXPERIMENT_VERSION = "prospective-economic-v2"
FEE_MODEL_VERSION = "polymarket-taker-fee-v1"


@dataclass(frozen=True, slots=True)
class EconomicExperimentContract:
    """Predeclared values that must not change after an experiment starts."""

    version: str = ECONOMIC_EXPERIMENT_VERSION
    control_policy: str = "continuous-shadow-policy-v0.2"
    target_policy: str = "target-exposure-v1"
    initial_capital: Decimal = Decimal("1000")
    entry_budget: Decimal = Decimal("5")
    market_exposure_cap: Decimal = Decimal("100")
    quote_max_age_seconds: int = 30
    quote_acquisition_max_seconds: int = 30
    valuation: str = "latest-causal-executable-bid-at-cutoff"
    decision_clock: str = "causal-execution-evidence-time"
    fee_model: str = FEE_MODEL_VERSION
    wallet_population: str = "recorded-experiment-follow-set"
    data_sources: tuple[str, ...] = (
        "polymarket:data-api:trades",
        "polymarket:clob:market-stream",
    )
    order_semantics: str = "BUY-account-currency-budget;SELL-held-shares"
    partial_fill_policy: str = "accept-nonzero-depth;report-partial"
    insufficient_liquidity_policy: str = "UNKNOWN-when-zero;partial-when-nonzero"
    primary_metric: str = "target-net-pnl-after-fees-and-slippage"
    classification_rule: str = (
        "INSUFFICIENT_DATA-if-coverage-or-valuation-incomplete;"
        "POSITIVE-if-target-net-pnl-positive;otherwise-NEGATIVE"
    )
    controls: tuple[str, ...] = ("current-control", "market-only", "placebo")
    canary_min_eligible: int = 20
    canary_mapping_ratio: Decimal = Decimal("0.95")
    canary_execution_ratio: Decimal = Decimal("0.90")

    def __post_init__(self) -> None:
        if self.version != ECONOMIC_EXPERIMENT_VERSION:
            raise ValueError("economic experiment v1 version is frozen")
        if self.initial_capital <= 0 or self.entry_budget <= 0:
            raise ValueError("economic capital and entry budget must be positive")
        if self.entry_budget > self.market_exposure_cap:
            raise ValueError("entry budget must not exceed the market cap")
        if (
            self.quote_max_age_seconds <= 0
            or self.quote_acquisition_max_seconds <= 0
            or self.canary_min_eligible <= 0
        ):
            raise ValueError("economic time and count bounds must be positive")

    def to_dict(self) -> dict[str, object]:
        return {
            "canary_execution_ratio": format(self.canary_execution_ratio, "f"),
            "canary_mapping_ratio": format(self.canary_mapping_ratio, "f"),
            "canary_min_eligible": self.canary_min_eligible,
            "control_policy": self.control_policy,
            "controls": list(self.controls),
            "data_sources": list(self.data_sources),
            "decision_clock": self.decision_clock,
            "entry_budget": format(self.entry_budget, "f"),
            "fee_model": self.fee_model,
            "initial_capital": format(self.initial_capital, "f"),
            "market_exposure_cap": format(self.market_exposure_cap, "f"),
            "order_semantics": self.order_semantics,
            "partial_fill_policy": self.partial_fill_policy,
            "insufficient_liquidity_policy": self.insufficient_liquidity_policy,
            "primary_metric": self.primary_metric,
            "classification_rule": self.classification_rule,
            "quote_max_age_seconds": self.quote_max_age_seconds,
            "quote_acquisition_max_seconds": self.quote_acquisition_max_seconds,
            "target_policy": self.target_policy,
            "valuation": self.valuation,
            "version": self.version,
            "wallet_population": self.wallet_population,
        }

    @property
    def digest(self) -> str:
        return payload_digest(self.to_dict())


CONTRACT_V1 = EconomicExperimentContract()


def taker_fee(
    *,
    shares: Decimal,
    price: Decimal,
    rate: Decimal,
    exponent: Decimal,
) -> Decimal:
    """Use the same fee calculation as Continuous Shadow."""

    amount = calculate_taker_fee_amount(
        price=price,
        size=shares,
        rate=rate,
        exponent=exponent,
    )
    if amount is None:
        raise ValueError("fee inputs are outside the supported prediction-market range")
    return amount


__all__ = [
    "CONTRACT_V1",
    "ECONOMIC_EXPERIMENT_VERSION",
    "FEE_MODEL_VERSION",
    "EconomicExperimentContract",
    "taker_fee",
]
