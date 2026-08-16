# PolySia Naming Pack

| Item | Canonical value |
|---|---|
| Official name | PolySia |
| Repository slug | `Platform` |
| Python distribution | `polysia` |
| Python namespace | `polysia` |
| CLI | `polysia` |
| Service prefix | `polysia-` |
| Operations console | PolySia Console |
| Technical language | English |
| First venue adapter | Polymarket |

Canonical `APP_ENV` base values are `development`, `test`, `staging`, and
`production`. Repository-owned examples use only these tokens. At the settings
input boundary, legacy aliases remain accepted and are normalized as follows:
`local`/`dev` to `development`, `qa`/`testing` to `test`, `stage`/`stg` to
`staging`, and `server`/`prod`/`prd` to `production`. This compatibility mapping
can be removed only after verified consumers no longer send legacy values.

Generic runtime variables use `POLYSIA_` as they are introduced. Venue-specific
variables retain `POLYMARKET_`. Existing generic variables remain supported only
until a tested migration provides aliases and rollback notes.

`pm_trader`, `pm-trader`, and `polymarket-trading-system` are legacy identities.
No compatibility shim is planned because repository and environment inspection
found no available external consumer; the preserved delivery folder and backup
provide rollback. If a verified consumer appears, a time-bounded shim requires a
new ADR amendment and removal gate.
