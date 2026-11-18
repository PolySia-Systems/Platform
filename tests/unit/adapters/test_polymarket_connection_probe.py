from io import BytesIO
from types import SimpleNamespace

from polysia.adapters.polymarket import connection_probe


def test_auth_probe_uses_only_get_and_returns_status_without_credentials(monkeypatch):
    monkeypatch.setattr(connection_probe, "wallet_activity", lambda *args: SimpleNamespace(
        complete=True, trade_count=0,
    ))
    reads = []

    def open_request(request, *, timeout):
        reads.append((request.get_method(), request.full_url, timeout))
        return BytesIO(b'{"apiKeys":["fixture-only"]}')

    monkeypatch.setattr(
        connection_probe, "build_opener", lambda *args: SimpleNamespace(open=open_request)
    )
    reply = connection_probe.probe({
        "wallet": "0x" + "1" * 40, "signer": "0x" + "2" * 40,
        "api_key": "fixture-only", "api_secret": "Zml4dHVyZQ==", "api_passphrase": "fixture",
    })
    assert reads == [("GET", "https://clob.polymarket.com/auth/api-keys", 10)]
    assert reply == {"public": "OBSERVED", "authenticated": "VERIFIED"}
