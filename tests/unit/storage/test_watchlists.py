import pytest

from polysia.storage.watchlists import WatchlistStore


def test_watchlist_is_durable_owner_scoped_and_revision_checked(tmp_path):
    path = tmp_path / "watchlists.sqlite3"
    first = WatchlistStore(path)
    item, address = "1" * 32, "0x" + "2" * 40
    first.save("alice", item, "Selection", [address, address], 0)
    first.save("alice", item, "Selection", [address], 0)
    restarted = WatchlistStore(path)
    assert restarted.lists("alice") == [{
        "id": item, "name": "Selection", "wallets": [address], "revision": 1,
    }]
    assert restarted.lists("bob") == []
    restarted.delete("bob", item, 1)
    restarted.save("alice", item, "Renamed", [address], 1)
    with pytest.raises(ValueError, match="revision_changed"):
        restarted.delete("alice", item, 1)
    assert restarted.lists("alice")[0]["name"] == "Renamed"
    restarted.delete("alice", item, 2)
    assert restarted.lists("alice") == []
