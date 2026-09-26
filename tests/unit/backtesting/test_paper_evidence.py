from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

import pytest

from polysia.backtesting.paper_evidence import (
    PAPER_EVIDENCE_VERSION,
    PaperEvidenceError,
    load_paper_replay_evidence,
)
from polysia.backtesting.replay import market_data_event_from_dict


def _event(at: str = "2026-01-01T00:00:00+00:00"):
    return market_data_event_from_dict(
        {
            "event_type": "book",
            "payload": {"asks": [{"price": "0.50", "size": "1"}], "bids": []},
            "raw_payload": {},
            "received_at": at,
            "source": "polymarket",
            "token_id": "token-1",
        }
    )


def _manifest() -> dict[str, object]:
    return {
        "schema_version": PAPER_EVIDENCE_VERSION,
        "market_id": "market-1",
        "token_ids": ["token-1", "token-2"],
        "cutoff_at": "2026-01-03T00:00:00+00:00",
        "fee_snapshots": [
            {
                "market_id": "market-1",
                "token_id": "token-1",
                "observed_at": "2025-12-31T23:59:59+00:00",
                "source_id": "fee-record-1",
                "fee_schedule": {"enabled": False},
            }
        ],
        "terminal": {
            "market_id": "market-1",
            "observed_at": "2026-01-02T00:00:00+00:00",
            "source_id": "terminal-record-1",
            "closed": True,
            "outcomes": [
                {"token_id": "token-1", "label": "Yes", "price": "1"},
                {"token_id": "token-2", "label": "No", "price": "0"},
            ],
        },
    }


def _load(tmp_path: Path, manifest: dict[str, object]):
    path = tmp_path / "evidence.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    return load_paper_replay_evidence(path, [_event()])


def test_recorded_fee_and_terminal_are_bound_to_market_token_and_time(tmp_path: Path) -> None:
    evidence = _load(tmp_path, _manifest())

    assert evidence.market_at("token-1", _event().received_at).fee_schedule.enabled is False
    assert evidence.market_at("token-2", _event().received_at) is None
    assert evidence.terminal_market is not None
    assert evidence.terminal_market.id == "market-1"


@pytest.mark.parametrize(
    ("change", "error"),
    [
        (lambda m: m.pop("fee_snapshots"), "fields are missing"),
        (lambda m: m["fee_snapshots"].clear(), "non-empty"),
        (lambda m: m["fee_snapshots"][0].update(market_id="other"), "market_id"),
        (lambda m: m["fee_snapshots"][0].update(token_id="other"), "token_id"),
        (lambda m: m["fee_snapshots"][0].update(observed_at="2026-01-02T00:00:00+00:00"), "future"),
        (lambda m: m["fee_snapshots"][0].update(observed_at="2026-01-01T00:00:00+00:00"), "future"),
        (lambda m: m["fee_snapshots"].append(deepcopy(m["fee_snapshots"][0])), "ambiguous"),
        (lambda m: m["fee_snapshots"][0].update(fee_schedule={"enabled": True}), "ambiguous"),
        (lambda m: m["terminal"].update(market_id="other"), "market_id"),
        (lambda m: m["terminal"].update(observed_at="2025-12-31T00:00:00+00:00"), "outside"),
        (lambda m: m["terminal"].update(observed_at="2026-01-01T00:00:00+00:00"), "outside"),
        (lambda m: m["terminal"].update(observed_at="2026-01-04T00:00:00+00:00"), "outside"),
        (lambda m: m["terminal"]["outcomes"][1].update(token_id="other"), "mismatched"),
        (lambda m: m["terminal"]["outcomes"][1].update(price="1"), "ambiguous"),
    ],
)
def test_invalid_or_noncausal_evidence_is_rejected(tmp_path: Path, change, error: str) -> None:
    manifest = _manifest()
    change(manifest)
    with pytest.raises(PaperEvidenceError, match=error):
        _load(tmp_path, manifest)


def test_explicit_missing_terminal_stays_unresolved(tmp_path: Path) -> None:
    manifest = _manifest()
    manifest["terminal"] = None

    evidence = _load(tmp_path, manifest)

    assert evidence.terminal_market is None


def test_later_fee_snapshot_never_applies_to_earlier_event(tmp_path: Path) -> None:
    manifest = _manifest()
    later = deepcopy(manifest["fee_snapshots"][0])
    later["observed_at"] = "2026-01-01T12:00:00+00:00"
    later["fee_schedule"] = {
        "enabled": True, "rate": "0.10", "exponent": "1", "taker_only": True,
    }
    manifest["fee_snapshots"].append(later)

    evidence = _load(tmp_path, manifest)

    assert evidence.market_at("token-1", _event().received_at).fee_schedule.enabled is False
    later_at = _event("2026-01-02T00:00:00+00:00").received_at
    assert evidence.market_at("token-1", later_at).fee_schedule.enabled is True


def test_recorded_economics_rejects_out_of_order_events(tmp_path: Path) -> None:
    path = tmp_path / "evidence.json"
    path.write_text(json.dumps(_manifest()), encoding="utf-8")

    with pytest.raises(PaperEvidenceError, match="ordered"):
        load_paper_replay_evidence(
            path,
            [_event("2026-01-02T00:00:00+00:00"), _event()],
        )
