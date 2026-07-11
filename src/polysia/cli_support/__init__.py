"""Reusable services kept separate from Typer command wiring."""

from polysia.cli_support.parsing import (
    parse_decimal,
    parse_order_type,
    parse_outcome,
    parse_side,
)
from polysia.cli_support.research import (
    build_research_strategy,
    intent_to_dict,
    local_market_event,
)
from polysia.cli_support.runtime import apply_secure_env_from_settings
from polysia.cli_support.safe_output import (
    order_snapshots_from_external,
    parse_optional_decimal,
    position_snapshots_from_external,
    read_safe_balance_allowance,
    read_safe_open_orders,
    read_safe_positions,
    safe_balance_allowance,
    safe_cancel_response,
    safe_open_order_to_dict,
    safe_order_response,
    safe_position_to_dict,
)

__all__ = [
    "apply_secure_env_from_settings",
    "build_research_strategy",
    "intent_to_dict",
    "local_market_event",
    "order_snapshots_from_external",
    "parse_decimal",
    "parse_optional_decimal",
    "parse_order_type",
    "parse_outcome",
    "parse_side",
    "position_snapshots_from_external",
    "read_safe_balance_allowance",
    "read_safe_open_orders",
    "read_safe_positions",
    "safe_balance_allowance",
    "safe_cancel_response",
    "safe_open_order_to_dict",
    "safe_order_response",
    "safe_position_to_dict",
]
