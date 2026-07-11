# Architecture Overview

PolySia is a modular monolith. Dependencies point inward:

`interfaces/adapters -> application -> domain`

The domain and application layers must not import `polymarket`, Polymarket
adapter modules, or SDK response models. Venue-specific identifiers and wallet,
fee, settlement, and geoblock details are translated at the adapter boundary.

The preserved forward path is:

`market data -> normalization -> features/strategy -> intent -> portfolio ->
risk -> OMS/transaction manager -> execution port -> venue adapter`

The return path is:

`venue event -> OMS -> position/ledger -> reconciliation -> risk/monitoring`

Emergency control is independent of strategy code. The first refactoring steps
are identity migration, neutral market/order models and ports, then Polymarket
adapter consolidation. Module decomposition follows only after behavior and
boundaries have characterization tests.

