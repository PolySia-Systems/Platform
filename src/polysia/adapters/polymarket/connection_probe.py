"""Check an existing Polymarket connection using bounded public and authenticated reads."""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
import time
from urllib.error import HTTPError
from urllib.request import Request, build_opener

from polysia.adapters.polymarket.leaderboard import (
    WALLET,
    PublicReads,
    _NoRedirect,
    wallet_activity,
)


def probe(value: dict[str, str]) -> dict[str, str]:
    now = int(time.time())
    wallet = value["wallet"]
    activity = wallet_activity(wallet, PublicReads(max_requests=3, seconds=12), now - 86400, now)
    public_status = "OBSERVED" if activity.complete or activity.trade_count else "UNAVAILABLE"
    if "api_key" not in value:
        return {"public": public_status, "authenticated": "NOT_CONFIGURED"}
    signer = value["signer"]
    if not WALLET.fullmatch(signer.lower()):
        raise ValueError("invalid_signer_address")
    path = "/auth/api-keys"
    try:
        secret = value["api_secret"]
        key = base64.b64decode(secret + "=" * (-len(secret) % 4), altchars=b"-_", validate=True)
        if not key:
            raise ValueError("invalid secret")
    except (binascii.Error, ValueError):
        return {"public": public_status, "authenticated": "INVALID_CREDENTIAL_FORMAT"}
    now = int(time.time())
    signature = base64.urlsafe_b64encode(
        hmac.new(key, f"{now}GET{path}".encode(), hashlib.sha256).digest()
    ).decode("ascii")
    request = Request("https://clob.polymarket.com" + path, headers={
        "POLY_ADDRESS": signer,
        "POLY_API_KEY": value["api_key"],
        "POLY_PASSPHRASE": value["api_passphrase"],
        "POLY_SIGNATURE": signature,
        "POLY_TIMESTAMP": str(now),
    })
    try:
        with build_opener(_NoRedirect()).open(request, timeout=10) as response:
            raw = response.read(32769)
        payload = json.loads(raw) if len(raw) <= 32768 else None
        keys = payload.get("apiKeys") if isinstance(payload, dict) else None
        status = "VERIFIED" if isinstance(keys, list) and value["api_key"] in keys else (
            "RESPONSE_UNVERIFIED"
        )
    except HTTPError as error:
        status = "REJECTED" if error.code in {401, 403} else "UNAVAILABLE"
        error.close()
    except (OSError, ValueError):
        status = "UNAVAILABLE"
    return {"public": public_status, "authenticated": status}
