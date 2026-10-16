"""Reuse SDK normalization while charging every public market GET."""

from __future__ import annotations

from polymarket.models.clob.order_book import OrderBook
from polymarket.models.gamma.market import Market

from polysia.adapters.polymarket.copytrading_source import JsonGetTransport
from polysia.adapters.polymarket.mappers import PolymarketMarketMapper
from polysia.domain.market import MarketDetails, MarketOrderBookSnapshot


class BoundedMarketAdapter:
    def __init__(self, transport: JsonGetTransport) -> None:
        self._transport, self._mapper = transport, PolymarketMarketMapper()

    async def get_market_by_condition_id(self, condition_id: str) -> MarketDetails:
        for closed in (False, True):
            payload = await self._transport.get_json(
                "https://gamma-api.polymarket.com", "/markets",
                {"condition_ids": condition_id, "closed": closed, "limit": 2},
            )
            if not isinstance(payload, list):
                raise ValueError("metadata_schema_invalid")
            if payload:
                if len(payload) != 1:
                    raise ValueError("metadata_mapping_ambiguous")
                market = self._mapper.to_details(Market.model_validate(payload[0]))
                if market.condition_id != condition_id:
                    raise ValueError("metadata_condition_mismatch")
                return market
        raise ValueError("metadata_condition_missing")

    async def get_order_book(self, token_id: str) -> MarketOrderBookSnapshot:
        payload = await self._transport.get_json(
            "https://clob.polymarket.com", "/book", {"token_id": token_id},
        )
        book = self._mapper.to_order_book(OrderBook.model_validate(payload))
        if book.token_id != token_id:
            raise ValueError("book_token_mismatch")
        return book
