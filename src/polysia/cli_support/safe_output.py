from datetime import datetime
from decimal import Decimal, InvalidOperation

from polysia.adapters.polymarket.secure import (
    PolymarketSecureAdapter,
    PolymarketSecureAdapterError,
)
from polysia.reconciliation import OrderSnapshot, PositionSnapshot


def safe_open_order_to_dict(order: object) -> dict[str, object]:
    return {
        "created_at": _safe_order_value(_read_field(order, "created_at")),
        "expires_at": _safe_order_value(
            _read_field(order, "expires_at") or _read_field(order, "expiration")
        ),
        "id": _safe_order_value(_read_field(order, "id")),
        "market": _safe_order_value(_read_field(order, "market")),
        "order_type": _safe_order_value(_read_field(order, "order_type")),
        "original_size": _safe_order_value(_read_field(order, "original_size")),
        "outcome": _safe_order_value(_read_field(order, "outcome")),
        "price": _safe_order_value(_read_field(order, "price")),
        "side": _safe_order_value(_read_field(order, "side")),
        "size_matched": _safe_order_value(_read_field(order, "size_matched")),
        "status": _safe_order_value(_read_field(order, "status")),
        "token_id": _safe_order_value(_read_field(order, "token_id")),
    }


def safe_position_to_dict(position: object) -> dict[str, object]:
    return {
        "avg_price": _safe_order_value(_read_field(position, "avg_price")),
        "condition_id": _safe_order_value(_read_field(position, "condition_id")),
        "current_value": _safe_order_value(_read_field(position, "current_value")),
        "outcome": _safe_order_value(_read_field(position, "outcome")),
        "size": _safe_order_value(_read_field(position, "size")),
        "token_id": _safe_order_value(_read_field(position, "token_id")),
    }


def order_snapshots_from_external(orders: list[object]) -> tuple[OrderSnapshot, ...]:
    snapshots: list[OrderSnapshot] = []
    for index, order in enumerate(orders):
        order_id = _optional_external_text(
            _read_field(order, "id") or _read_field(order, "order_id")
        )
        snapshots.append(
            OrderSnapshot(
                order_id=order_id or f"external-order-{index}",
                status=_optional_external_text(_read_field(order, "status")),
                token_id=_optional_external_text(_read_field(order, "token_id")),
                created_by_system=False,
            )
        )
    return tuple(snapshots)


def position_snapshots_from_external(
    positions: list[object],
) -> tuple[PositionSnapshot, ...]:
    snapshots: list[PositionSnapshot] = []
    for index, position in enumerate(positions):
        token_id = _optional_external_text(_read_field(position, "token_id"))
        size = parse_optional_decimal(_read_field(position, "size")) or Decimal("0")
        snapshots.append(
            PositionSnapshot(
                token_id=token_id or f"external-position-{index}",
                size=size,
            )
        )
    return tuple(snapshots)


async def read_safe_balance_allowance(
    adapter: PolymarketSecureAdapter,
) -> dict[str, object]:
    try:
        collateral = await adapter.get_balance_allowance(asset_type="COLLATERAL")
    except PolymarketSecureAdapterError as error:
        return {
            "allowance_count": 0,
            "approval_readable": False,
            "balance_configured": False,
            "balance_readable": False,
            "error_type": type(error).__name__,
            "positive_approval_count": 0,
        }
    return safe_balance_allowance(collateral)


async def read_safe_positions(adapter: PolymarketSecureAdapter) -> dict[str, object]:
    preview_limit = 5
    try:
        positions = await adapter.list_positions(size_threshold=0)
    except PolymarketSecureAdapterError as error:
        return {
            "count": 0,
            "error_type": type(error).__name__,
            "positions_preview": [],
            "readable": False,
            "truncated": False,
        }
    preview = positions[:preview_limit]
    return {
        "count": len(positions),
        "positions_preview": [safe_position_to_dict(position) for position in preview],
        "readable": True,
        "truncated": len(positions) > preview_limit,
    }


async def read_safe_open_orders(adapter: PolymarketSecureAdapter) -> dict[str, object]:
    try:
        open_orders = await adapter.get_open_orders()
    except PolymarketSecureAdapterError as error:
        return {
            "count": 0,
            "error_type": type(error).__name__,
            "readable": False,
        }
    return {
        "count": len(open_orders),
        "readable": True,
    }


def safe_balance_allowance(balance_allowance: object) -> dict[str, object]:
    data = _model_or_mapping_to_dict(balance_allowance)
    allowances = data.get("allowances")
    allowance_count = len(allowances) if isinstance(allowances, dict) else 0
    positive_allowance_count = 0
    if isinstance(allowances, dict):
        for value in allowances.values():
            parsed = parse_optional_decimal(value)
            if parsed is not None and parsed > 0:
                positive_allowance_count += 1
    return {
        "allowance_count": allowance_count,
        "approval_readable": isinstance(allowances, dict),
        "balance_configured": data.get("balance") is not None,
        "balance_readable": data.get("balance") is not None,
        "positive_allowance_count": positive_allowance_count,
        "positive_approval_count": positive_allowance_count,
    }


def parse_optional_decimal(value: object) -> Decimal | None:
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except InvalidOperation:
        return None


def safe_cancel_response(response: object) -> dict[str, object] | None:
    if response is None:
        return None
    if hasattr(response, "model_dump"):
        data = response.model_dump(mode="json")
        return {
            "canceled": list(data.get("canceled", ())),
            "not_canceled": data.get("not_canceled", {}),
        }
    if isinstance(response, dict):
        return {
            "canceled": list(response.get("canceled", ())),
            "not_canceled": response.get("not_canceled", {}),
        }
    return {
        "canceled": list(getattr(response, "canceled", ())),
        "not_canceled": getattr(response, "not_canceled", {}),
    }


def safe_order_response(response: object) -> dict[str, object] | None:
    if response is None:
        return None
    data = _model_or_mapping_to_dict(response)
    payload: dict[str, object] = {}
    for field_name in (
        "ok",
        "order_id",
        "status",
        "code",
        "message",
        "making_amount",
        "taking_amount",
    ):
        if field_name in data:
            payload[field_name] = _safe_order_value(data[field_name])
    if "trade_ids" in data:
        payload["trade_count"] = _safe_sequence_count(data["trade_ids"])
    if "transactions_hashes" in data:
        payload["transaction_count"] = _safe_sequence_count(data["transactions_hashes"])
    return payload


def _optional_external_text(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _safe_sequence_count(value: object) -> int:
    if isinstance(value, (dict, list, set, tuple)):
        return len(value)
    return 0


def _model_or_mapping_to_dict(source: object) -> dict[str, object]:
    if hasattr(source, "model_dump"):
        return source.model_dump(mode="python")
    if isinstance(source, dict):
        return dict(source)
    return {
        field_name: getattr(source, field_name)
        for field_name in dir(source)
        if not field_name.startswith("_") and not callable(getattr(source, field_name))
    }


def _read_field(source: object, field_name: str) -> object:
    if hasattr(source, "model_dump"):
        data = source.model_dump(mode="python")
        return data.get(field_name)
    if isinstance(source, dict):
        return source.get(field_name)
    return getattr(source, field_name, None)


def _safe_order_value(value: object) -> object:
    if value is None:
        return None
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, (bool, int, str)):
        return value
    return str(value)
