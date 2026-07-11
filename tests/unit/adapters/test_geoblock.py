from __future__ import annotations

from urllib.error import URLError

import pytest

from pm_trader.adapters.geoblock import (
    GeoblockClient,
    GeoblockClientError,
    PreLiveOrderGeoblockCheck,
    PreLiveOrderGeoblockError,
)


class FakeResponse:
    def __init__(self, payload: bytes) -> None:
        self._payload = payload

    def __enter__(self) -> FakeResponse:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def read(self) -> bytes:
        return self._payload


def test_geoblock_client_reads_blocked_false(monkeypatch) -> None:
    monkeypatch.setattr(
        "pm_trader.adapters.geoblock.urlopen",
        lambda *_args, **_kwargs: FakeResponse(b'{"blocked": false}'),
    )

    status = GeoblockClient().check_sync()

    assert status.status == "allowed"
    assert status.blocked is False
    assert "country" not in str(status.to_safe_dict()).lower()


def test_geoblock_client_reads_blocked_true(monkeypatch) -> None:
    monkeypatch.setattr(
        "pm_trader.adapters.geoblock.urlopen",
        lambda *_args, **_kwargs: FakeResponse(b'{"blocked": true}'),
    )

    status = GeoblockClient().check_sync()

    assert status.status == "blocked"
    assert status.blocked is True


def test_geoblock_client_rejects_endpoint_errors(monkeypatch) -> None:
    def fail(*_args: object, **_kwargs: object) -> object:
        raise URLError("offline")

    monkeypatch.setattr("pm_trader.adapters.geoblock.urlopen", fail)

    with pytest.raises(GeoblockClientError):
        GeoblockClient().check_sync()


@pytest.mark.asyncio
async def test_pre_live_geoblock_check_fails_closed_on_error(monkeypatch) -> None:
    def fail(*_args: object, **_kwargs: object) -> object:
        raise URLError("offline")

    monkeypatch.setattr("pm_trader.adapters.geoblock.urlopen", fail)

    check = PreLiveOrderGeoblockCheck(GeoblockClient())

    with pytest.raises(PreLiveOrderGeoblockError, match="failed closed"):
        await check.assert_allowed()


@pytest.mark.asyncio
async def test_pre_live_geoblock_check_blocks_when_endpoint_blocks(monkeypatch) -> None:
    monkeypatch.setattr(
        "pm_trader.adapters.geoblock.urlopen",
        lambda *_args, **_kwargs: FakeResponse(b'{"blocked": true}'),
    )

    check = PreLiveOrderGeoblockCheck(GeoblockClient())

    with pytest.raises(PreLiveOrderGeoblockError, match="blocked"):
        await check.assert_allowed()
