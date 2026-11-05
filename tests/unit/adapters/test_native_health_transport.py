from __future__ import annotations

import asyncio
import io
import time
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from email.message import Message
from urllib.error import HTTPError

import pytest

from polysia.adapters.polymarket import bounded_transport as transport
from polysia.application.ports.copytrading import LeaderReadPurpose
from polysia.domain.copytrading.native_health import PURPOSE
from polysia.storage.acquisition_authority import AcquisitionAuthority, AcquisitionBlockedError
from tests.unit.storage.test_acquisition_authority import ENDPOINT, policy


@pytest.mark.parametrize("purpose,declared,expected", [
    (PURPOSE, "2", 2), (PURPOSE, "20", 1024), ("PUBLIC_RESEARCH", "2", 1024),
])
def test_complete_http_error_settles_only_health_purpose(tmp_path, monkeypatch,
                                                      purpose, declared, expected):
    now = datetime.now(UTC)
    authority = AcquisitionAuthority(tmp_path / "authority.sqlite3", replace(
        policy(), starts_at=now - timedelta(seconds=1), expires_at=now + timedelta(hours=1),
        purpose=purpose,
    ))
    authority.initialize()
    headers = Message()
    headers["Content-Length"] = declared

    class Opener:
        def open(self, *args, **kwargs):
            raise HTTPError("redacted", 404, "missing", headers, io.BytesIO(b"{}"))

    monkeypatch.setattr(transport, "build_opener", lambda *_: Opener())
    monkeypatch.setattr(transport.socket, "gethostname", lambda: "host")
    reader = transport.BoundedPublicTransport(authority)
    with pytest.raises(AcquisitionBlockedError, match="provider_http_404"):
        reader._read_with_purpose(ENDPOINT.rsplit("/v2", 1)[0], "/v2/activity", {},
                                  LeaderReadPurpose.BASELINE)
    status = authority.status()
    assert status["requests_charged"] == 1
    assert status["bytes_charged"] == expected
    assert status["uncertain_requests"] == (expected == 1024)
    assert list(authority.evidence_root.glob("*.failure.json"))
    restarted = AcquisitionAuthority(authority.path, authority.policy)
    assert restarted.status() == status
    if purpose == PURPOSE and expected == 1024:
        with pytest.raises(AcquisitionBlockedError, match="accounting_uncertain"):
            restarted.reserve(ENDPOINT, now=now, host="host")


@pytest.mark.asyncio
async def test_health_metadata_fanout_settles_serially_without_false_uncertainty(
    tmp_path, monkeypatch,
):
    now = datetime.now(UTC)
    authority = AcquisitionAuthority(tmp_path / "authority.sqlite3", replace(
        policy(), starts_at=now - timedelta(seconds=1), expires_at=now + timedelta(hours=1),
        purpose=PURPOSE,
    ))
    authority.initialize()

    class Reply:
        headers = {}
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def read(self, limit):
            time.sleep(0.02)  # overlap attempts before settlement without the health lock
            return b"{}"

    class Opener:
        def open(self, *args, **kwargs): return Reply()

    monkeypatch.setattr(transport, "build_opener", lambda *_: Opener())
    monkeypatch.setattr(transport.socket, "gethostname", lambda: "host")
    reader = transport.BoundedPublicTransport(authority)
    results = await asyncio.gather(*[reader.get_json(
        ENDPOINT.rsplit("/v2", 1)[0], "/v2/activity", {},
    ) for _ in range(3)])
    assert results == [{}, {}, {}]
    assert authority.status()["requests_charged"] == 3
    assert authority.status()["bytes_charged"] == 6
    assert authority.status()["uncertain_requests"] == 0
