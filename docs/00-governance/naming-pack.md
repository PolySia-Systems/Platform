# PolySia Naming Pack

| Item | Canonical value |
|---|---|
| Official name | PolySia |
| Repository slug | `polysia` |
| Python distribution | `polysia` |
| Python namespace | `polysia` |
| CLI | `polysia` |
| Service prefix | `polysia-` |
| Operations console | PolySia Console |
| Technical language | English |
| First venue adapter | Polymarket |

Generic runtime variables use `POLYSIA_` as they are introduced. Venue-specific
variables retain `POLYMARKET_`. Existing generic variables remain supported only
until a tested migration provides aliases and rollback notes.

`pm_trader`, `pm-trader`, and `polymarket-trading-system` are legacy identities.
No compatibility shim is planned because repository and environment inspection
found no available external consumer; the preserved delivery folder and backup
provide rollback. If a verified consumer appears, a time-bounded shim requires a
new ADR amendment and removal gate.

