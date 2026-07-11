# Polymarket Adapter

## Boundary

All official `polymarket` SDK imports are confined to
`src/polysia/adapters/polymarket/`. The package contains:

- `public.py`: public market catalog reads;
- `secure.py`: authenticated account and execution operations;
- `stream.py`: realtime market ingestion and reconnect policy;
- `geoblock.py`: mandatory fail-closed eligibility check;
- `mappers.py`: SDK objects to canonical domain models;
- `capabilities.py`: explicit venue capability profile.

Domain and application modules do not import the SDK or adapter. Strategy and
storage layers consume canonical models. Architecture tests enforce these
directions.

## Capability profile

The current adapter supports public streaming, authenticated reads, limit and
market order operations, cancellation, FAK/FOK and post-only workflows. Live
execution requires the existing environment, risk, allowlist, cap,
acknowledgement, one-attempt, kill-switch, and geoblock controls.

Polymarket-specific token/condition identifiers and signer/funder semantics are
adapter metadata; they are not forced into generic domain contracts.

## SDK contract

The verified baseline is `polymarket-client==0.1.0b11`. Contract tests assert
the exact installed version and every SDK method called by public, secure, and
stream adapters. Official b12 is known but intentionally deferred until a
separate compatibility change.

