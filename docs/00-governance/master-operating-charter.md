# Master Project Operating Charter and AI Execution Protocol

## For a Professional, Reality-First, Multi-Market Algorithmic Trading, Copy-Trading, Web3 and DeFi Platform

**Version:** 1.0  
**Date:** 11 July 2026  
**Status:** Baseline operating charter  
**Primary language:** English for technical artifacts and executable prompts  
**Conversation language:** Persian may be used between the project owner and the coordinating AI  

---

## Document Purpose

This document is the governing operating charter for designing, building, validating, deploying, operating, and continuously improving a professional algorithmic trading platform. It is also the source from which phase prompts, task prompts, architecture briefs, implementation packets, review packets, and handoff packages shall be generated.

It is not a promise of profitability and it is not a substitute for legal, tax, regulatory, security, or investment advice. It requires evidence, controlled experiments, independent risk controls, human approval at sensitive gates, and continuous reconciliation with real systems.

The platform may ultimately support traditional markets, crypto markets, prediction and event markets, wallet intelligence, copy trading, Web3 execution, DeFi yield opportunities, liquidity provision, and multi-strategy portfolio management. Not every capability must be implemented. The complete taxonomy provides the target picture; delivery must remain incremental, risk-controlled, and economically justified.

---

## How to Use This Charter

1. Treat this document as the project constitution and single operating baseline.
2. Store it in the repository, version it, review it, and update it through an approved change process.
3. Do not paste the entire charter into every coding request. Generate a compact, task-specific execution packet that cites the relevant sections and repository files.
4. Keep discussions with the project owner in Persian when helpful. Produce technical documents, source code, file names, schemas, commits, ADRs, RFCs, task prompts, tool instructions, and handoff packages in English.
5. Keep all AI tool interactions vendor-neutral. Codex, Claude Code, Gemini, OpenCode, open-source agents, or other tools must receive the same standardized task packet and return the same standardized delivery package.
6. The repository and approved artifacts are the source of truth, not any single chat transcript or model memory.

---

# Part I — Mission, Roles and Non-Negotiable Principles

## 1. Mission

Design and build a professional algorithmic trading platform that can evolve safely from discovery and research to controlled real-world execution. The objective is not merely to create a strategy or trading bot. The objective is a complete, modular, testable, reproducible, secure, observable, auditable, portable, maintainable, and operationally viable system.

The platform must clearly separate:

- software quality;
- data quality;
- statistical validity;
- execution quality;
- risk control quality;
- operational readiness;
- legal and regulatory suitability; and
- actual economic performance.

A profitable backtest is not proof of a profitable live system. A technically correct system is not proof of a valid trading strategy. A valid strategy is not proof of operational readiness.

## 2. Coordinating Roles

The coordinating AI shall reason from the relevant perspectives, without pretending that one model replaces qualified specialists:

- Software Architect;
- Quantitative Researcher;
- Quant Systems Engineer;
- Trading Systems Engineer;
- Portfolio and Risk Engineer;
- Data Engineer;
- ML/MLOps Engineer;
- Security Architect;
- DevSecOps and Site Reliability Engineer;
- Test and Validation Engineer;
- UX and Operations Console Designer;
- Technical Product Manager;
- Technical Program Manager;
- Compliance and Operational-Risk Analyst;
- FinOps and Capacity Planning Analyst; and
- AI Workflow and Tool-Handoff Coordinator.

When expert sign-off is materially required, state it explicitly. Legal, tax, regulated market access, smart-contract audits, and high-value security decisions require competent human review.

## 3. Core Operating Principles

The project shall follow these principles:

- Blueprint-first, but not blueprint-only;
- Architecture-driven, but resistant to architecture astronautics;
- Reality-first and vertical-slice delivery;
- Risk-first and fail-safe controls;
- Evidence-driven technology and strategy decisions;
- Security-by-design and least privilege;
- Documentation-as-code and infrastructure-as-code;
- Reproducible research and deterministic replay where feasible;
- Stage-gated delivery with explicit entry and exit criteria;
- Progressive exposure to real systems and real capital;
- Human-in-the-loop for sensitive transitions;
- Vendor-neutral, broker-neutral, exchange-neutral, chain-neutral, data-provider-neutral, and AI-tool-neutral design;
- Single source of truth in version control;
- Economics-first prioritization;
- Explicit deprecation and sunset policies;
- Continuous learning from incidents, failed experiments, and live feedback.

## 4. Reality-First Delivery Rule

Every meaningful delivery cycle must produce a small but complete, observable, usable vertical slice. A vertical slice should traverse the relevant path from input data to decision, risk approval, execution or simulation, state update, reconciliation, monitoring, and user-visible output.

Research and backtesting are mandatory controls, not permanent destinations. The preferred maturity path is:

`Research → Focused Backtest → Out-of-Sample Check → Paper → Shadow Live → Micro-Capital Live → Controlled Scaling`

The platform must avoid endless optimization. Each experiment shall have:

- a hypothesis;
- a timebox;
- a budget;
- success criteria;
- failure criteria;
- stop conditions;
- a maximum number of refinement cycles; and
- a decision: promote, revise once, defer, or terminate.

A weak strategy or feature must be killed rather than repaired indefinitely. Real execution data must feed back into cost models, simulations, risk assumptions, architecture decisions, and product priorities.

## 5. Simplicity and Evolution

Choose the simplest architecture that satisfies current quality attributes and leaves a credible migration path. For a small team, a modular monolith is the default candidate. Adopt microservices or distributed subsystems only when justified by scale, independent deployment, fault isolation, security boundaries, ownership, latency, availability, or regulatory needs. Record the decision in an Architecture Decision Record.

Machine learning, online learning, alternative data, colocation, FPGA/GPU acceleration, and complex execution algorithms are not status symbols. Introduce them only when a simpler baseline has been measured and the incremental value is demonstrated.

---

# Part II — Interaction, Discovery and Project Identity

## 6. Conversation and Artifact Language

- The project owner and coordinating AI may communicate in Persian.
- All technical artifacts shall be written in English unless a specific local-language artifact is required.
- All generated prompts for Codex, Claude Code, Gemini, OpenCode, open-source coding agents, design tools, testing agents, and review agents shall be in English.
- Code, comments, identifiers, schemas, file names, commits, pull requests, ADRs, RFCs, runbooks, dashboards, and alerts shall use English.
- User-facing localization may be added separately and must not alter internal canonical identifiers.

## 7. Incremental Discovery Protocol

Discovery shall be conducted through short questionnaires. Ask no more than five high-impact questions per round. Explain why each answer matters and offer a recommended default where appropriate. Do not expect the owner to know technical terminology. Record non-critical assumptions rather than blocking progress.

### 7.1 Questionnaire A — Project Identity

Cover:

- official name and codename;
- purpose and value proposition;
- personal, team, commercial, or institutional use;
- target maturity: research, paper, limited live, production, or institutional;
- near-term value objective: learning, infrastructure, research, revenue, product, or a combination.

Produce a Project Naming Pack containing:

- official name;
- codename;
- repository slug;
- package namespace;
- service prefix;
- environment names;
- module naming rules;
- dashboard and product naming; and
- naming rationale.

### 7.2 Questionnaire B — Markets and Trading Style

Cover:

- crypto, equities, FX, futures, options, prediction/event markets, DeFi, or multi-asset;
- instrument universe;
- spot, margin, perpetual, futures, options, pools, vaults, or event shares;
- holding period and decision frequency;
- strategy families;
- long, short, neutral, or both;
- latency sensitivity;
- market sessions and geographic constraints.

### 7.3 Questionnaire C — Capital and Risk

Cover:

- research budget;
- initial test capital;
- possible live capital;
- maximum risk per trade or position;
- maximum tolerated drawdown;
- leverage constraints;
- daily, weekly, and monthly loss limits;
- manual approval thresholds;
- shutdown conditions;
- protected reserve capital.

Suggested values are design assumptions, not financial advice.

### 7.4 Questionnaire D — Technology, Team and Operations

Cover:

- preferred languages and existing skills;
- operating systems;
- local, VPS, cloud, bare metal, colocated, or hybrid deployment;
- data and infrastructure budget;
- team size and roles;
- broker, exchange, chain, wallet, or protocol candidates;
- open-source versus commercial constraints;
- UI, API, CLI, mobile, and reporting needs;
- availability and support expectations.

### 7.5 Questionnaire E — Jurisdiction, Security and Custody

Cover:

- residence and operating jurisdictions;
- personal versus legal-entity accounts;
- tax and accounting requirements;
- market-access restrictions;
- custody model;
- signing and key management;
- audit requirements;
- record retention;
- data privacy and licensing.

Never generalize one jurisdiction’s rules to another.

### 7.6 Questionnaire F — First Revenue-Oriented Vertical Slice

Define the first narrow capability that can produce real evidence and potentially economic value. Examples include:

- one simple, transparent strategy on one venue;
- one prediction-market opportunity scanner;
- one wallet-following analysis workflow;
- one low-risk copy-signal shadow system;
- one DeFi opportunity dashboard without automatic execution;
- one liquidity-pool risk and yield monitor.

The objective is not guaranteed revenue. The objective is early, controlled, measurable contact with reality.

---

# Part III — Evidence, Research and Decision Governance

## 8. Evidence Hierarchy

Before selecting a technology, broker, exchange, chain, data source, protocol, library, model, or operational method, research it in proportion to the decision’s risk.

Use this hierarchy:

1. official documentation and normative specifications;
2. release notes, changelogs, deprecation notices, and migration guides;
3. standards and regulatory publications;
4. official source repositories and test suites;
5. security advisories, CVEs, audits, and incident reports;
6. official issue trackers and maintainers’ discussions;
7. credible postmortems and engineering studies;
8. peer-reviewed or technically rigorous research;
9. user experience from forums, communities, and practitioner reports;
10. tutorials, comparisons, and secondary summaries.

User experience is valuable for discovering hidden operational problems. It is not sufficient as the final basis for architecture or security decisions.

## 9. Research Evidence Register

Create `docs/02-research/research-evidence-register.md` with:

- evidence ID;
- topic and research question;
- source and source type;
- version and publication date;
- review date;
- finding;
- limitation;
- confidence level;
- architectural or product impact;
- related decision;
- required validation experiment;
- next review trigger.

## 10. Technology Evaluation Matrix

For each material candidate evaluate:

- functional fit;
- current version and maintenance health;
- API stability;
- compatibility;
- licensing and usage rights;
- security history;
- performance and capacity;
- reliability;
- operational complexity;
- observability;
- community and vendor maturity;
- direct and indirect cost;
- lock-in;
- migration path and exit strategy;
- quality of official documentation;
- quality of real user experience;
- fit for the project’s team and maturity stage.

## 11. Spike and Proof-of-Concept Policy

Use a timeboxed spike or proof of concept for high-risk unknowns. Define:

- hypothesis;
- scope;
- success metrics;
- representative workload;
- failure conditions;
- security and operational tests;
- results;
- cost;
- limitations;
- decision;
- revisit conditions.

## 12. Continuous Revalidation

Revisit decisions when any of these occur:

- major version release;
- API or protocol change;
- deprecation;
- license change;
- security incident;
- maintenance decline;
- cost change;
- broker, exchange, chain, or data-provider change;
- regulatory change;
- production incident;
- material performance or capacity change;
- transition to a higher stage.

---

# Part IV — Scope, Capability Governance and Economics

## 13. Capability Inventory Rules

Treat all requested features as a capability inventory, not as a commitment to build everything. Each capability shall have:

- unique ID;
- description;
- target user and value;
- requirement type;
- priority;
- target stage;
- dependencies;
- complexity;
- security and financial risk;
- estimated build and maintenance cost;
- measurable acceptance criteria;
- owner;
- status;
- rationale for implementation, deferral, or rejection.

Use statuses:

- Foundation;
- MVP;
- Production-Ready;
- Professional;
- Institutional;
- Experimental;
- Future Research;
- Deferred;
- Rejected;
- Deprecated;
- Retired.

## 14. Traceability

Maintain this traceability chain:

`Capability → Requirement → Architecture Component → Risk Control → Test → Metric → Stage Gate → Release`

No critical capability may exist without an owner, acceptance criteria, risk controls, and a verification method.

## 15. Economics-First Governance

Assess every major capability against:

- expected user or trading value;
- opportunity cost;
- implementation effort;
- ongoing maintenance burden;
- infrastructure and data cost;
- operational risk;
- security exposure;
- regulatory burden;
- time to first evidence;
- reversibility;
- probability of becoming obsolete.

Maintain a Technology and Strategy Cost Ledger. Include build cost, run cost, data cost, model/API cost, cloud cost, support cost, and expected benefit. Do not maintain a complex subsystem merely because significant effort has already been spent on it.

## 16. Sunset Policy

Every strategy, dependency, data source, broker adapter, protocol integration, model, and infrastructure component shall define:

- deprecation criteria;
- replacement or migration path;
- archive requirements;
- user and operator notification;
- data retention;
- final reconciliation;
- rollback window;
- removal date;
- post-retirement monitoring.

---

# Part V — Complete Platform Capability Taxonomy

## 17. Product, Governance and Program Management

- Project charter, vision, scope, goals, and non-goals;
- stakeholder map, personas, use cases, KPIs, and KRIs;
- assumption, decision, risk, issue, dependency, and technical-debt registers;
- roadmap, milestones, stage gates, RACI, Definition of Ready, and Definition of Done;
- change management, release governance, budget governance, and audit calendar;
- single source of truth and document ownership;
- lessons-learned register and postmortem knowledge base.

## 18. Market and Reference Data

- real-time and historical tick, trade, quote, bar, order-book, options, funding, borrow, and reference data;
- corporate actions, splits, dividends, delistings, contract rolls, and symbol changes;
- trading calendars, sessions, holidays, time zones, and daylight-saving rules;
- instrument master, identifiers, tick sizes, lot sizes, minimum notionals, multipliers, currencies, precision, and settlement rules;
- multi-vendor ingestion, entitlements, licensing, retention, replay, and provenance.

## 19. Data Quality, Lineage and Governance

- data contracts, schemas, schema registry, catalog, lineage, and source provenance;
- completeness, freshness, duplication, gap, outlier, bad-tick, and cross-source checks;
- point-in-time correctness, look-ahead prevention, survivorship and delisting handling;
- quarantine, correction, reprocessing, replay, retention, and versioning;
- time synchronization, sequence numbers, event time, receive time, and processing time.

## 20. Research and Experimentation Platform

- reproducible environments, notebooks, experiment tracking, dataset snapshots, and feature definitions;
- hypothesis register, negative-result recording, parameter registry, seed control, code commit, config hash, and environment lock;
- strategy registry, model registry, model cards, and research reports;
- controlled promotion from research to production;
- leakage detection and research/live parity testing.

## 21. Alpha and Signal Generation

Potential signal families include:

- price action, market structure, statistical factors, technical indicators, custom factors, ML models, ensembles, and alternative data;
- multi-timeframe confirmation and alignment;
- trend, momentum, volatility, liquidity, order-flow, and structural filters;
- swing structure, volume profile, order blocks, fair value gaps, liquidity voids, and market microstructure features;
- confidence, calibration, quality, expiry, invalidation, and explainability.

No indicator or threshold shall be accepted as universal. Parameters must be validated for the specific market, horizon, regime, and cost structure.

## 22. Market Regime and Context Detection

- trend, range, chop, high/low volatility, crisis, liquidity stress, correlation, macro, funding, and session regimes;
- rule-based, statistical, HMM, Bayesian, and ML regime models;
- transition detection, confidence, stability, and uncertainty;
- strategy enable/disable policies and regime-aware risk limits.

## 23. Direction, Bias and Context

- long-only, short-only, both, neutral, and hedged modes;
- higher-timeframe, daily, weekly, funding, carry, borrow, market-neutral, and macro overrides;
- net and gross exposure targets;
- explicit governance of overrides and conflicts.

## 24. Strategy Lifecycle and Orchestration

- registration, versioning, activation, suspension, retirement, and rollback;
- single and multi-strategy orchestration;
- conflict resolution, priority, capital reservation, correlation, and strategy health;
- re-entry, cooldown, pyramiding, scaling in, and scaling out;
- regime-based activation and champion/challenger deployment.

Martingale, grid, and aggressive DCA must be disabled by default, isolated as experimental, hard-capped, independently stress-tested, and unable to bypass global risk controls.

## 25. Portfolio Construction and Allocation

- equal weight, risk parity, volatility targeting, HRP, maximum diversification, and correlation-aware allocation;
- strategy, asset, sector, venue, chain, currency, protocol, counterparty, and jurisdiction limits;
- net/gross exposure, beta, concentration, collateral, margin, cash buffers, and liquidity reserves;
- dynamic allocation based on regime, health, capacity, and execution quality.

## 26. Position Sizing and Risk Management

- fixed dollar, fixed fractional, volatility-adjusted, ATR/IV-based, margin-aware, liquidity-aware, and impact-aware sizing;
- fractional Kelly and constrained optimal-f only with estimation-error controls and shrinkage;
- drawdown-sensitive, equity-curve-sensitive, and strategy-health-sensitive risk scaling;
- portfolio heat, probability of touch, risk of ruin, and anti-fragile reduction after losses.

## 27. Hard Risk Limits and Emergency Controls

- per-trade, daily, weekly, monthly, portfolio, strategy, leader, protocol, and venue loss limits;
- soft pause, hard lockout, and full shutdown;
- maximum drawdown, leverage, open risk, position count, order rate, cancel rate, and price deviation;
- fat-finger protection, price collars, stale-data guards, clock-drift guards, and abnormal-P&L guards;
- independent kill switch, manual override, physical or separate emergency path;
- CUSUM/EWMA or similar process monitoring on performance and risk metrics.

Hard risk controls shall be independent of strategy code and shall have final authority to reject, reduce, pause, close, or shut down.

## 28. Position, Cash, P&L and Accounting

- position, cash, collateral, margin, and tax-lot ledgers;
- realized/unrealized P&L, fees, commissions, spread, slippage, funding, borrow, swap, interest, and FX conversion;
- exact decimal or fixed-point arithmetic and explicit rounding rules;
- internal versus external reconciliation;
- break detection, correction workflow, and immutable audit events.

## 29. Order Management System

- canonical order model and explicit state machine;
- client order IDs, idempotency, duplicate prevention, parent/child relationships, replace/cancel, expiry, and time-in-force;
- partial fills, rejections, recovery after restart, and open-order reconciliation;
- strategy attribution, risk approval reference, position intent, and audit trail.

## 30. Execution Management System

- market, limit, stop, stop-limit, post-only, reduce-only, iceberg, TWAP, VWAP, POV, and custom execution;
- venue selection and smart routing where justified;
- slippage, spread, depth, participation, queue, partial-fill, latency, and impact controls;
- microprice, fair value, toxic flow, VPIN, cumulative delta, footprint, and quote-behavior analytics where data supports them;
- execution quality scoring and feedback to simulation.

## 31. Entry, Exit and Position Management

Entry controls may include signal validity, risk approval, liquidity, spread, session, event blackout, regime, correlation, position, and cost-adjusted edge.

Exit controls may include fixed or structural stops, ATR or volatility stops, trailing stops, break-even rules, staged exits, time exits, session exits, maximum holding periods, cost-adjusted targets, and emergency liquidation.

## 32. Broker, Exchange, Venue and Market Connectivity

- adapter architecture for REST, WebSocket, FIX, RPC, and protocol-specific interfaces;
- authentication, rate limits, backoff, retries, heartbeats, sequencing, reconnect, recovery, and time synchronization;
- sandbox and testnet support;
- capability discovery and venue-rule enforcement;
- broker/venue redundancy, failover, mirror or shadow accounts where suitable;
- order, trade, position, balance, and transaction reconciliation.

Strategies shall never call a broker, exchange, wallet, or protocol directly.

## 33. Transaction Cost, Capacity and Liquidity

- commission, half-spread, slippage, impact, latency, opportunity cost, funding, borrow, gas, and bridge costs;
- annual cost forecast and cost attribution;
- AUM capacity, ADV participation, depth, liquidity score, saturation, and exit capacity;
- minimum execution-quality threshold before scaling.

## 34. Backtesting and Simulation

- vectorized research where appropriate and event-driven simulation for realistic lifecycle behavior;
- tick, bar, order-book, order-state, queue, latency, partial-fill, cost, margin, liquidation, corporate-action, and session modeling;
- multi-asset and multi-strategy simulation;
- deterministic replay and shared production domain logic through adapters where feasible.

Backtesting shall be deliberately bounded. It is used to reject weak ideas, identify gross defects, and establish risk estimates—not to delay contact with real systems indefinitely.

## 35. Statistical Validation and Overfit Protection

- train/validation/test separation, in-sample/out-of-sample, forward testing, walk-forward, anchored walk-forward;
- purged and embargoed cross-validation, combinatorial purged CV where justified;
- bootstrap, Monte Carlo, reshuffling, noise injection, and cost/delay/missing-data stress;
- parameter sensitivity and stability maps;
- multiple-testing correction, probabilistic and deflated Sharpe ratios;
- confidence intervals, subperiod, instrument, and regime analysis;
- maximum acceptable IS/OOS degradation, strategy half-life, concept drift, and automatic suspension.

## 36. Real-World Validation Ladder

For each strategy or critical feature, define promotion gates through:

- unit and component tests;
- focused historical validation;
- independent OOS check;
- paper execution against live data;
- shadow live decisions without real orders;
- micro-capital live execution;
- limited capital and limited instruments;
- controlled scaling.

Each stage must produce observable evidence. Use real money only after kill switches, reconciliation, monitoring, and loss caps have been tested. Initial live exposure shall be intentionally small enough that complete loss is tolerable.

## 37. Stress Testing and Tail Risk

- historical and synthetic crises;
- gap, volatility, correlation, liquidity, margin, collateral, funding, stablecoin, counterparty, exchange, chain, bridge, and cloud failures;
- sequence risk, path dependency, contagion, and exit bottlenecks;
- internet outage, region outage, sanctions/access restrictions, and manual recovery;
- tail hedging only after cost, carry, basis risk, and operational feasibility are assessed.

## 38. Filters and Safety Layers

- macro and high-impact event blackouts;
- session, holiday, weekend, rollover, earnings, expiration, and seasonality filters;
- liquidity, spread, volatility, correlation, concentration, and market-integrity filters;
- flash-crash and black-swan circuit breakers;
- anti-loop, maximum order rate, stale data, and heartbeat protection.

## 39. Observability and Post-Trade Analytics

- structured logs, metrics, traces, profiles where useful, and correlation IDs;
- end-to-end signal-to-order-to-fill tracing;
- data freshness, latency, fill, reject, slippage, impact, P&L attribution, risk utilization, strategy health, and model drift;
- SLIs, SLOs, alert policies, dashboards, and escalation routes;
- daily post-trade analysis, mistake classification, and incident correlation;
- sensitive-data redaction.

## 40. Reliability, Resilience and Disaster Recovery

- failure-mode analysis for feeds, APIs, brokers, exchanges, chains, nodes, databases, queues, storage, servers, networks, regions, and processes;
- automatic restart, graceful degradation, backpressure, circuit breakers, retries, and dead-letter handling;
- high availability only where justified;
- backups, restore tests, RPO, RTO, failover, disaster-recovery drills, and runbooks;
- incident command, communication, postmortems, and corrective-action tracking.

## 41. Security, Identity and Software Supply Chain

- threat modeling, trust boundaries, attack-surface review, authentication, authorization, RBAC, least privilege, and separation of duties;
- secret management, rotation, 2FA, hardware keys, IP restrictions, and read-only access where possible;
- encryption in transit and at rest;
- dependency, secret, static, dynamic, container, and infrastructure scanning;
- SBOM, build provenance, signed artifacts, protected branches, isolated build identities, and controlled production approval;
- patch management, vulnerability disclosure, incident response, and audit logs.

Trading credentials should not have withdrawal rights unless strictly necessary. Secrets and tokens must never appear in source code, notebooks, logs, or ordinary configuration files.

## 42. Counterparty, Custody and Centralization Risk

- concentration by broker, exchange, custodian, chain, protocol, bridge, stablecoin, and jurisdiction;
- CeFi, DeFi, and self-custody allocation;
- withdrawal controls, allowlists, balance thresholds, and emergency evacuation;
- counterparty score, solvency indicators, legal-entity analysis, and operational history;
- proof of reserves as one signal, not proof of total solvency.

## 43. Compliance, Tax, Licensing and Audit

- jurisdiction profile, trading permissions, algorithmic-trading obligations, record retention, and best-execution evidence where applicable;
- market-abuse controls and audit trail;
- tax-lot tracking and reports according to relevant jurisdiction;
- data licensing, API terms, redistribution rights, privacy, and vendor obligations;
- legal and tax review checkpoints.

## 44. Alternative Data, ML and Model Governance

- news, social, on-chain, macro, COT, options flow, and other alternative data;
- feature validation, leakage checks, explainability, calibration, model cards, and model registry;
- drift, staleness, training-serving skew, adversarial robustness, and champion/challenger deployment;
- shadow deployment, rollback, human approval, and controlled updates;
- online learning shall not modify live models without guardrails, versioning, evaluation, approval, and rollback.

## 45. Operational and Psychological Safeguards

- unusual trading time, abnormal size, revenge behavior, loss chasing, and P&L volatility detection;
- mandatory cooldown and rest periods;
- manual-trading restrictions and dual confirmation for sensitive actions;
- reserve capital and margin buffers;
- profit withdrawal policy;
- quarterly strategy and operational reviews;
- complete audit of human overrides.

## 46. UI, UX and Operations Console

Build an operations-focused interface rather than a decorative dashboard. Define role-based views for owner, operator, researcher, risk reviewer, and auditor.

Required capability areas:

- system health and environment status;
- current capital, cash, collateral, exposure, leverage, and drawdown;
- positions, orders, fills, transactions, wallet balances, and reconciliation breaks;
- strategy states, confidence, regime, leader or wallet signals, and opportunity scores;
- hard risk limits and remaining risk budget;
- alerts, incidents, degraded dependencies, and pending approvals;
- P&L and cost attribution;
- execution quality, slippage, latency, and data quality;
- live/paper/shadow mode visibility with unmistakable visual distinction;
- manual pause, close, disable, and kill-switch controls;
- audit timeline and reason capture for every intervention.

UX requirements:

- prevent accidental live actions;
- require confirmation for irreversible or high-risk operations;
- show source, timestamp, freshness, confidence, and uncertainty;
- support accessibility and keyboard operation;
- use progressive disclosure;
- preserve a complete audit trail;
- design first in low-fidelity flows, then component prototypes, then production UI.

A design tool may be used for flows and prototypes, but design files must map to versioned requirements and acceptance criteria.

## 47. Infrastructure Architecture and Capacity Planning

Create a dedicated infrastructure architecture covering:

- compute, network, storage, databases, caches, queues, streams, secrets, and observability;
- development, research, test, sandbox, paper, shadow, staging, limited live, production, and disaster-recovery environments;
- local, VPS, public cloud, private cloud, bare metal, colocation, and hybrid options;
- CPU, memory, disk, IOPS, bandwidth, event rate, retention, concurrency, and latency budgets;
- high availability, scaling, failover, backup, restore, and region strategy;
- network segmentation, firewalls, private connectivity, identity, and access;
- capacity headroom and overload behavior;
- cost allocation, budgets, alerts, unit economics, and FinOps reviews;
- vendor exit and migration plan.

Do not provision institutional infrastructure before it is justified. Define capacity tiers and migration triggers:

- local development;
- low-cost VPS MVP;
- production single-region;
- high-availability multi-zone;
- multi-region or colocated only when measured needs justify it.

## 48. Web3 and On-Chain Infrastructure

- chain registry and capability matrix;
- RPC abstraction, primary/backup providers, node or archive-node evaluation;
- block, transaction, log, event, and mempool ingestion where relevant;
- ABI, contract, token, protocol, and address registries;
- finality, confirmation, reorganization, duplicate, replay, and fork handling;
- gas and fee estimation, nonce management, replacement, simulation, receipt reconciliation, and stuck-transaction recovery;
- upgrade and proxy monitoring;
- network congestion, sequencer, and chain-health monitoring.

## 49. Wallet, Key and Transaction Security

- hot, warm, cold, watch-only, multisig, smart accounts, MPC/HSM, and hardware wallet evaluation;
- dedicated execution, treasury, strategy, chain, and protocol wallets;
- role-based permissions, spending limits, allowlists, function restrictions, and approval limits;
- transaction simulation and human approval for high-risk actions;
- proposer/signer separation, key rotation, recovery, compromise response, and emergency evacuation;
- phishing, address poisoning, malicious signatures, blind signing, and suspicious contract interaction controls.

Unlimited approvals are prohibited by default.

## 50. On-Chain Data and Wallet Intelligence

- transaction, internal call, transfer, swap, LP, lending, borrowing, staking, bridge, governance, derivatives, event-market, and fee activity;
- wallet labeling with source, confidence, and review date;
- entity resolution, clustering, funding sources, counterparty, timing, behavioral similarity, exchange flows, bridge paths, smart-account detection, bot and Sybil analysis;
- realized and unrealized P&L reconstruction net of gas, fees, slippage, funding, and transfers;
- cost-basis, airdrop, vesting, OTC, deposit, withdrawal, bridge, and internal-transfer treatment;
- performance by regime, strategy, asset, chain, protocol, and holding period.

## 51. Wallet Ranking and Smart-Money Scoring

Rank wallets using a multi-dimensional, explainable model:

- profitability and risk-adjusted return;
- drawdown and recovery;
- consistency, longevity, sample size, and capital efficiency;
- liquidity awareness, concentration, turnover, gas and execution quality;
- repeatability, regime robustness, exit discipline, and copyability;
- data completeness, identity confidence, survivorship risk, and manipulation risk.

Anti-gaming controls shall cover wash trading, self trading, circular flows, hidden losses, abandoned wallets, airdrop distortion, illiquid marks, token transfers disguised as profit, coordinated wallets, insider-like access, and pump-and-dump behavior.

## 52. Copy-Trading and Strategy Replication

Copy trading is a signal source, never a direct execution command.

Required flow:

`On-Chain or Venue Data → Wallet/Leader Intelligence → Copy Signal → Portfolio Engine → Independent Risk Engine → OMS/Transaction Manager → Execution`

Capabilities:

- leader selection, baskets, consensus, regime-specific leaders, activation, suspension, retirement, and score decay;
- entry, exit, increase, reduction, reversal, liquidity, borrowing, collateral, staking, bridge, hedge, and multi-leg reconstruction;
- fixed, proportional, risk-normalized, volatility-adjusted, confidence-weighted, and consensus copying;
- maximum delay, price divergence, slippage, gas, impact, liquidity, capacity, and minimum net edge;
- partial copy, duplicate prevention, failed-copy handling, independent exits, and do-not-chase rules;
- risk limits per leader, cluster, asset, market, protocol, chain, and portfolio;
- leader-specific and global kill switches.

Past leader performance is not proof of repeatable or copyable edge.

## 53. Prediction and Event Markets

Provide a general capability layer for prediction and event markets:

- market discovery, categorization, liquidity, spread, order book, and expiry;
- outcome definitions, resolution rules, oracle or adjudication source, dispute process, and settlement timing;
- event correlation, mutually exclusive outcomes, conditional dependencies, and portfolio exposure;
- probability calibration, implied probability, expected value, fees, slippage, capital lockup, and resolution risk;
- wallet and participant behavior analysis;
- copyability and latency analysis;
- geographic, legal, account, and market-access restrictions;
- conservative position limits per event, category, resolution source, and correlated cluster;
- explicit handling of ambiguous, revised, canceled, or disputed markets.

## 54. DeFi Opportunity and Yield Intelligence

Evaluate AMMs, concentrated-liquidity pools, stable pools, lending, borrowing, staking, liquid staking, restaking, vaults, aggregators, perpetual liquidity, options vaults, basis, funding, delta-neutral structures, fixed-rate markets, RWAs, incentives, and fee-sharing protocols.

Decompose yield:

`Expected Net Yield = Gross Yield − Fees − Gas − Slippage − Hedging Cost − Borrow Cost − Expected Loss − Required Risk Premium`

Assess:

- source and sustainability of yield;
- organic revenue versus emissions;
- TVL, volume, fee-to-TVL, depth, capital utilization, concentration, range occupancy, and exit capacity;
- token dilution, incentive expiry, treasury runway, protocol profitability, user retention, and demand;
- impermanent loss, loss-versus-rebalancing, adverse selection, toxic flow, range risk, de-peg, oracle, smart-contract, governance, admin-key, upgrade, insolvency, composability, MEV, bridge, and liquidity risk.

## 55. Protocol and Smart-Contract Risk

For each protocol or contract record:

- verified source, audit history and scope, unresolved findings, formal verification, bug bounty, test quality, upgradeability, proxy structure, admin power, pause controls, timelocks, multisig thresholds, governance, dependencies, oracle design, and incident history;
- economic security, collateral, utilization, bad debt, liquidation, insurance/safety modules, bank-run exposure, reflexivity, governance capture, and attack cost;
- team transparency, development activity, documentation, incident response, monitoring, and centralized dependencies;
- risk tier, maximum allocation, approved addresses, holding period, required monitoring, suspension triggers, emergency exit, and blacklist conditions.

An audit is not a guarantee of safety.

## 56. Oracle, Bridge, Cross-Chain and MEV Risk

- oracle diversity, freshness, heartbeat, deviation, sequencer health, fallback, manipulation resistance, circuit breakers, and low-liquidity handling;
- bridge model, validators, messages, finality, relayers, guardians, upgrade authority, transfer caps, delays, incident history, and alternative exits;
- in-flight capital, replay protection, timeouts, wrapped-asset de-peg, destination validation, and cross-chain reconciliation;
- sandwich, front-running, back-running, private routing, protected RPCs, slippage, deadline, minimum output, bundle, mempool, revert, honeypot, tax-token, blacklist, pause, mint, and upgrade-event controls.

## 57. On-Chain Opportunity Scanner

The scanner may discover new pools, incentives, rates, spreads, funding, de-pegs, governance changes, upgrades, liquidations, unusual wallet behavior, and cross-venue or cross-chain discrepancies.

Discovery and execution must remain separate. Each opportunity shall have:

- expected gross and net return;
- confidence;
- duration;
- capacity;
- execution cost;
- liquidity;
- smart-contract, oracle, bridge, counterparty, regulatory, and exit risk;
- crowding and copyability;
- expected tail loss.

## 58. Web3 Validation

- historical chain-state replay and mainnet-fork testing;
- transaction simulation and event replay;
- gas, failed transaction, reorg, oracle delay/manipulation, de-peg, liquidity drain, withdrawal, impermanent loss, range, MEV, bridge delay, contract pause, governance attack, reward collapse, and exit-capacity tests;
- copy latency, leader behavior change, cluster misclassification, and wallet compromise scenarios.

---

# Part VI — Architecture and System Boundaries

## 59. Canonical Trading Flow

Allowed forward flow:

`Market/On-Chain Data → Normalization → Feature Pipeline → Strategy or Opportunity Source → Signal → Portfolio Engine → Risk Engine → OMS or Transaction Manager → EMS/Execution Router → Broker, Exchange, Wallet or Protocol Adapter`

Return flow:

`External Venue or Chain → Execution/Receipt/Event → OMS/Transaction Manager → Position and Ledger → Reconciliation → Risk, Portfolio, Monitoring and UI`

Emergency Control shall be independent of strategy code and preferably independent of the normal execution path.

## 60. Bounded Contexts

Define explicit boundaries for:

- market and reference data;
- on-chain data;
- research and experimentation;
- feature engineering;
- strategy and signal generation;
- regime detection;
- wallet and leader intelligence;
- opportunity discovery;
- portfolio construction;
- risk;
- position and ledger;
- OMS and transaction management;
- EMS and routing;
- broker, venue, chain, wallet, and protocol adapters;
- reconciliation;
- compliance and audit;
- identity and security;
- observability;
- UI and administration;
- emergency control.

## 61. Architectural Patterns to Evaluate

- modular monolith;
- hexagonal architecture and ports/adapters;
- clean architecture;
- domain-driven boundaries;
- event-driven patterns;
- command/query separation where useful;
- contract-first APIs and schema versioning;
- plugin architecture;
- dependency inversion;
- idempotency and explicit state machines;
- replayable and immutable event records where justified.

Do not adopt a pattern without describing the problem it solves and its operational cost.

## 62. Time and Event Semantics

Define:

- UTC internal time;
- exchange and chain local calendars;
- timestamp precision;
- clock synchronization;
- event, receive, and processing time;
- sequence numbers;
- duplicates, out-of-order, late, reverted, and replayed events;
- deterministic clock abstraction for testing;
- chain confirmations and finality;
- time-source failure behavior.

## 63. Environment Separation

Separate:

- local development;
- research;
- backtest;
- integration test;
- broker sandbox/testnet;
- paper trading;
- shadow live;
- staging;
- limited live;
- production live;
- disaster recovery.

Define per environment:

- data sources;
- accounts and credentials;
- endpoints;
- configuration;
- secrets;
- risk limits;
- logging and retention;
- access policy;
- deployment policy;
- UI labeling;
- reconciliation behavior.

Live credentials must never be available in research, notebooks, or ordinary CI jobs.

## 64. Required Architecture Views

Produce only useful views, including:

- system landscape;
- C4 system context;
- C4 container view;
- component views for critical domains;
- deployment view;
- data and event flows;
- signal-to-execution sequence;
- order and transaction state machines;
- position lifecycle;
- reconciliation flow;
- failure and recovery sequences;
- security trust boundaries;
- network and environment boundaries;
- module dependency graph;
- capability taxonomy;
- research-to-live promotion flow;
- CI/CD flow;
- incident response flow.

Diagrams shall be version-controlled, titled, scoped, legended, understandable without a long oral explanation, and consistent with the written architecture.

---

# Part VII — Repository, Documentation and Engineering Standards

## 65. Suggested Repository Structure

```text
/
├── README.md
├── LICENSE
├── CONTRIBUTING.md
├── SECURITY.md
├── CODE_OF_CONDUCT.md
├── CHANGELOG.md
├── CODEOWNERS
├── .editorconfig
├── .gitignore
├── docs/
│   ├── 00-governance/
│   ├── 01-discovery/
│   ├── 02-research/
│   ├── 03-requirements/
│   ├── 04-taxonomy/
│   ├── 05-architecture/
│   ├── 06-security/
│   ├── 07-risk/
│   ├── 08-data/
│   ├── 09-quant-validation/
│   ├── 10-testing/
│   ├── 11-infrastructure/
│   ├── 12-operations/
│   ├── 13-ui-ux/
│   ├── 14-compliance/
│   ├── 15-runbooks/
│   ├── 16-adrs/
│   ├── 17-rfcs/
│   ├── 18-ai-handoffs/
│   ├── 19-web3/
│   ├── 20-copy-trading/
│   ├── 21-defi/
│   └── 22-roadmap/
├── src/
├── tests/
├── configs/
├── schemas/
├── scripts/
├── infrastructure/
├── deployments/
├── monitoring/
├── dashboards/
├── notebooks/
├── data-contracts/
├── prompts/
└── tools/
```

The actual structure shall be selected after architecture and language decisions.

## 66. Core Documents

Maintain:

- Project Charter;
- Vision, Scope, Goals, and Non-Goals;
- Glossary;
- Stakeholder Map;
- Assumption, Decision, Risk, Issue, Dependency, Open Question, and Technical Debt Registers;
- Functional and Non-Functional Requirements;
- Capability Catalog and Taxonomy;
- Traceability Matrix;
- Domain Model and C4 Architecture;
- Data, Security, Infrastructure, UI, and Operations Architecture;
- Threat Model and Failure-Mode Analysis;
- Technology Evaluation Matrix and Watchlist;
- Testing Strategy and Quant Validation Protocol;
- Data Quality and Observability Strategies;
- Deployment, Incident Response, and Disaster Recovery Plans;
- Compliance Profile;
- Roadmap, Stage Gates, Definition of Done, and Live Readiness Checklist;
- AI Task Packets, Handoff Packages, and Review Reports.

Each document shall state owner, status, version, audience, inputs, outputs, dependencies, completion criteria, and next review date.

## 67. Git and Change Management

Evaluate monorepo versus polyrepo and trunk-based versus another branching model. Define:

- branch naming;
- Conventional Commits;
- commit scopes;
- pull request and issue templates;
- protected branches;
- required checks;
- code review policy;
- CODEOWNERS;
- release and hotfix process;
- Semantic Versioning for public contracts;
- changelog and release notes;
- rollback and deprecation policy.

## 68. Architecture Decision Records

Each material decision shall include:

- context;
- problem;
- constraints;
- options;
- evaluation criteria;
- decision and rationale;
- positive and negative consequences;
- risks;
- migration plan;
- revisit triggers;
- status: proposed, accepted, superseded, rejected, or retired.

## 69. RFC Process

Use RFCs for major architecture, broker, data, schema, risk, model, deployment, security-boundary, or production changes. An RFC shall include alternatives, compatibility, migration, rollback, testing, security, operations, cost, and decision owner.

---

# Part VIII — Tool-Agnostic AI Execution and Handoff Protocol

## 70. Purpose

The project shall not depend on the behavior, memory, proprietary format, or hidden conventions of one AI model or coding tool. Every tool receives a standard execution packet and returns a standard delivery package. The repository is authoritative.

## 71. Tool Roles

Possible tools include:

- coordinating and architecture model;
- coding agent;
- test-generation agent;
- security-review agent;
- documentation agent;
- data/quant review agent;
- UI design tool;
- CI and static analysis tools;
- open-source local models for repetitive tasks.

Tool selection is a replaceable implementation detail. Critical decisions require evidence and review, not model brand loyalty.

## 72. Standard AI Task Packet

Every executable task prompt shall be in English and contain:

1. Task ID and title;
2. objective and business/technical value;
3. relevant charter, ADR, RFC, issue, and requirement references;
4. current repository state and commit;
5. allowed files and forbidden files;
6. inputs, contracts, schemas, and assumptions;
7. functional requirements;
8. non-functional requirements;
9. security and risk constraints;
10. implementation boundaries;
11. tests to add or update;
12. acceptance criteria;
13. required commands to run;
14. expected output format;
15. rollback or recovery expectations;
16. explicit stop conditions and escalation questions.

## 73. Standard Execution Rules for AI Coding Tools

The tool must:

- read the task packet and referenced repository files before editing;
- restate the plan briefly;
- avoid unrelated refactoring;
- modify only authorized files;
- preserve public contracts unless change is approved;
- never invent secrets or production credentials;
- use official documentation for version-sensitive behavior;
- add tests before claiming completion;
- run specified validation commands;
- report failures honestly;
- produce a concise delivery package;
- stop when requirements conflict or a critical unknown makes safe implementation impossible.

## 74. Standard Delivery Package

Every tool shall return:

- summary of work;
- assumptions made;
- files created, changed, and deleted;
- important design decisions;
- commands executed;
- test results;
- lint/type/security/build results;
- acceptance criteria status;
- known limitations;
- risks introduced or mitigated;
- migration or configuration actions;
- rollback instructions;
- remaining work;
- suggested reviewer focus;
- exact repository status or commit if available.

## 75. Handoff Between Tools

Create a machine- and human-readable handoff file under `docs/18-ai-handoffs/` or the issue/PR. It must contain enough context for another tool to continue without relying on the previous chat.

Handoffs shall include:

- task and state;
- source-of-truth links;
- decisions already approved;
- unresolved questions;
- modified files;
- test state;
- risks;
- next action;
- prohibited changes;
- owner or approval required.

## 76. Independent Review Protocol

A different tool or human reviewer should verify critical changes. Review dimensions:

- requirement compliance;
- architecture compliance;
- correctness;
- tests and edge cases;
- risk-control integrity;
- security;
- data leakage and statistical validity;
- production safety;
- observability;
- maintainability;
- documentation and rollback.

The reviewer must distinguish blocking findings, non-blocking findings, and suggestions.

## 77. Prompt and Context Management

- Store reusable prompts in `prompts/` with version and owner.
- Prefer compact task packets over enormous repeated prompts.
- Reference canonical files rather than duplicating them.
- Include only relevant context and a context manifest.
- Record model/tool name and version for reproducibility when material.
- Do not treat model output as evidence until tests or reviews confirm it.
- Sensitive data must be redacted before being sent to third-party tools.

---

# Part IX — Testing, Delivery, Security and Operations

## 78. Test Strategy

Use a risk-based pyramid including:

- unit;
- property-based;
- state-machine;
- schema and contract;
- component;
- integration;
- sandbox/testnet;
- end-to-end;
- replay and golden datasets;
- regression and backtest/live parity;
- performance, load, stress, and soak;
- chaos and failure injection;
- fuzz and security;
- backup, restore, failover, and disaster recovery.

Prioritize order and transaction states, duplicate prevention, partial fills, cancel/replace races, restart recovery, reconciliation, stale data, rate limits, clocks, rounding, fees, funding, gas, margin, liquidation, risk limits, kill switches, and idempotency.

## 79. Quantitative Validation Protocol

For each strategy define:

- hypothesis and economic mechanism;
- market and regime applicability;
- data provenance;
- baseline and benchmark;
- costs and capacity;
- validation split;
- sensitivity;
- multiple-testing controls;
- risk and tail behavior;
- paper/shadow/live promotion criteria;
- termination criteria;
- expected decay and review cadence.

## 80. CI/CD and Software Supply Chain

Pipeline stages should include, as relevant:

1. formatting;
2. linting;
3. type checking;
4. unit and property tests;
5. dependency and license checks;
6. secret scanning;
7. static security analysis;
8. SBOM;
9. reproducible build;
10. artifact provenance and signing;
11. integration and contract tests;
12. container and IaC scanning;
13. quant regression and data tests;
14. performance tests;
15. staging deployment;
16. smoke and canary checks;
17. manual approval for sensitive environments;
18. controlled production deployment;
19. post-deployment verification;
20. automated rollback criteria.

A normal push or merge shall never directly activate live trading.

## 81. Operational Metrics

Track:

- availability, latency, error rates, saturation, and data freshness;
- order and transaction lifecycle metrics;
- execution quality and reconciliation health;
- strategy and model health;
- risk-limit utilization and incidents;
- deployment frequency, change lead time, failed deployment recovery, change failure rate, and reliability indicators;
- infrastructure and data cost per strategy, venue, environment, and unit of work.

## 82. Incident and Learning Process

- detect, classify, contain, recover, reconcile, and communicate;
- preserve evidence and audit trail;
- conduct blameless but accountable postmortems;
- create corrective actions with owners and deadlines;
- update tests, runbooks, assumptions, architecture, and training;
- maintain a searchable lessons-learned register.

---

# Part X — Roadmap and Stage Gates

## 83. Phase 0 — Project Identity and Discovery

Deliver:

- Project Naming Pack;
- Project Charter;
- Vision, Scope, Goals, and Non-Goals;
- stakeholder map;
- initial assumptions, glossary, and risks;
- first revenue-oriented vertical-slice hypothesis.

## 84. Phase 1 — Evidence and Feasibility

Deliver:

- official-document and practitioner research;
- Research Evidence Register;
- capability inventory;
- technology landscape;
- initial economic and legal feasibility;
- candidate first vertical slice.

## 85. Phase 2 — Blueprint and Taxonomy

Deliver:

- capability catalog and complete taxonomy;
- domain decomposition;
- C4 context and container views;
- primary data, signal, order, transaction, risk, and reconciliation flows;
- roadmap and stage gates;
- build/defer/reject decisions.

## 86. Phase 3 — Architecture and Standards

Deliver:

- component and deployment architecture;
- infrastructure and capacity plan;
- security architecture and threat model;
- UI/UX information architecture and critical flows;
- repository, Git, ADR, RFC, testing, CI/CD, observability, and AI handoff standards.

## 87. Phase 4 — Foundation Vertical Slice

Deliver a working path with:

- repository skeleton;
- core domain contracts;
- configuration;
- telemetry;
- data input;
- one strategy or opportunity source;
- independent risk check;
- simulated execution;
- ledger and reconciliation;
- basic dashboard;
- automated tests and CI.

This is the first proof that the architecture produces a usable system.

## 88. Phase 5 — Live-Data Paper Slice

- live data;
- paper or sandbox execution;
- full state lifecycle;
- real latency and cost observations;
- alerts and operational dashboard;
- daily review;
- comparison against simulation.

## 89. Phase 6 — Shadow Live

- real decisions and timestamps;
- no real orders;
- expected-versus-observed fills and costs;
- data, latency, and reliability report;
- operational readiness assessment.

## 90. Phase 7 — Micro-Capital Live

- tiny, pre-approved capital;
- one limited strategy or use case;
- limited instruments, markets, wallets, chains, or protocols;
- hard loss caps;
- manual supervision;
- tested kill switch;
- daily reconciliation and review;
- no automatic scaling.

## 91. Phase 8 — Controlled Product and Strategy Expansion

Add capabilities only after the first vertical slice operates reliably. Possible expansions:

- second strategy;
- prediction/event-market module;
- wallet intelligence;
- copy trading in shadow or micro-capital mode;
- DeFi scanner and later controlled execution;
- additional broker, exchange, chain, or data source;
- improved UI and automation.

## 92. Phase 9 — Controlled Scaling

Scale only after explicit criteria for:

- net performance;
- drawdown;
- execution quality;
- cost-model accuracy;
- capacity;
- data quality;
- reconciliation;
- operational reliability;
- security;
- incident history;
- legal suitability.

## 93. Phase 10 — Professional and Institutional Hardening

- multiple strategies and venues;
- advanced allocation and execution;
- redundancy and failover;
- capacity and market-impact modeling;
- automated compliance evidence;
- advanced security and key management;
- model governance;
- formal operational service levels;
- independent audits and disaster-recovery exercises.

---

# Part XI — Live Readiness and Quality Gates

## 94. Minimum Live Readiness Checklist

Before any real capital:

- clear hypothesis and bounded scope;
- point-in-time-correct data;
- major biases controlled;
- realistic costs and capacity;
- focused OOS and sensitivity evidence;
- paper/shadow evidence;
- OMS/transaction manager and adapters tested;
- independent risk limits active;
- kill switch tested;
- ledger and reconciliation working;
- monitoring, alerts, and dashboard working;
- incident and emergency runbooks;
- backup and restore tested;
- credentials secured;
- rollback available;
- live configuration reviewed;
- legal and access constraints reviewed;
- explicit human approval recorded;
- initial loss fully tolerable.

## 95. Definition of Done for a Vertical Slice

A vertical slice is done only when:

- behavior and acceptance criteria are documented;
- code and contracts are versioned;
- tests pass;
- security and risk controls are active;
- data lineage is known;
- execution state is observable;
- ledger and reconciliation are included;
- UI or operational output is usable;
- runbook and rollback exist;
- costs are measured;
- results are reviewed;
- open limitations are recorded.

## 96. Blueprint Pack Completion Criteria

The Blueprint Pack is complete when:

- scope and non-goals are clear;
- taxonomy and priorities are complete enough to guide delivery;
- domains, boundaries, flows, and dependencies are explicit;
- context and container views exist;
- risk, security, data, infrastructure, UI, and operations are designed;
- repository and engineering standards are approved;
- testing and quant validation protocols exist;
- stage gates and reality-first vertical slices are defined;
- critical decisions have ADRs;
- no unresolved question blocks the first foundation slice.

---

# Part XII — Required Output and Review Format

## 97. Output Format for Each Phase

Each phase response or document shall contain:

1. objective;
2. current state;
3. inputs;
4. facts;
5. assumptions;
6. recommendations;
7. decisions;
8. alternatives considered;
9. primary deliverable;
10. diagrams or models;
11. risks and limitations;
12. acceptance criteria;
13. completed items;
14. open questions;
15. next vertical slice;
16. files created or changed;
17. evidence and references.

Clearly label Fact, Assumption, Recommendation, Decision, Open Question, Risk, and Experimental Idea.

## 98. Prohibitions

- Do not start full production coding before the minimum blueprint and first vertical slice are defined.
- Do not produce only documents; every phase must move toward a usable system.
- Do not select core technology without current evidence.
- Do not over-engineer.
- Do not treat microservices as the default.
- Do not equate backtest with live performance.
- Do not let strategy code bypass portfolio, risk, OMS/transaction, or execution controls.
- Do not store secrets in source, notebooks, logs, or ordinary config.
- Do not use fixed trading thresholds without market-specific validation.
- Do not generalize legal rules across jurisdictions.
- Do not treat forums as the final authority.
- Do not use stale official documentation without version checking.
- Do not move experimental features into the live core without promotion gates.
- Do not introduce ML without a simpler baseline and measured incremental value.
- Do not enable unrestricted online learning.
- Do not change live systems without audit, approval, and rollback.
- Do not guarantee profitability.
- Do not conceal missing evidence with confident language.
- Do not allow an AI tool to claim completion without tests and a delivery package.

---

# Part XIII — Startup Instruction

## 99. Initial Command to the Coordinating AI

Accept this document as the Project Operating Charter and source of truth.

Do not begin full production implementation immediately.

Start by:

1. reviewing this charter for contradictions, gaps, and risks;
2. creating a document control record;
3. asking the first Project Identity questionnaire with no more than five questions;
4. offering recommended defaults in plain language;
5. recording assumptions, decisions, and open questions;
6. identifying the first small, real, end-to-end vertical slice;
7. defining the evidence, safety controls, budget, and stop criteria for that slice;
8. creating the initial repository document map;
9. generating English task packets for execution tools only after the required context and acceptance criteria are ready;
10. evaluating every stage before moving to the next.

The coordinating AI shall keep explanations to the owner clear and practical. It shall not require the owner to know the names of all professional practices in advance. Its responsibility is to identify and introduce the practices needed to reach the project’s actual objective.

---

# Appendix A — Standard AI Task Packet Template

```text
TASK ID:
TITLE:
STATUS:
PRIORITY:
OWNER:

OBJECTIVE:
BUSINESS / TECHNICAL VALUE:

SOURCE OF TRUTH:
- Charter sections:
- Requirements:
- ADRs/RFCs:
- Issue/PR:
- Repository commit:

SCOPE:
IN SCOPE:
OUT OF SCOPE:

ALLOWED FILES:
FORBIDDEN FILES:

INPUTS AND CONTRACTS:
ASSUMPTIONS:
DEPENDENCIES:

FUNCTIONAL REQUIREMENTS:
NON-FUNCTIONAL REQUIREMENTS:
SECURITY AND RISK CONSTRAINTS:
OBSERVABILITY REQUIREMENTS:

IMPLEMENTATION INSTRUCTIONS:
REQUIRED TESTS:
REQUIRED COMMANDS:

ACCEPTANCE CRITERIA:
STOP / ESCALATION CONDITIONS:

DELIVERY FORMAT:
- Summary
- Files changed
- Decisions
- Commands and tests
- Results
- Limitations and risks
- Rollback
- Remaining work
- Reviewer focus
```

# Appendix B — Standard Handoff Package Template

```text
HANDOFF ID:
FROM TOOL / AGENT:
TO TOOL / AGENT:
DATE:
REPOSITORY COMMIT:

TASK OBJECTIVE:
CURRENT STATE:
COMPLETED WORK:
FILES CHANGED:
TEST STATUS:
DECISIONS APPROVED:
ASSUMPTIONS:
OPEN QUESTIONS:
KNOWN RISKS:
BLOCKERS:
PROHIBITED CHANGES:
NEXT ACTION:
REQUIRED APPROVAL:
SOURCE-OF-TRUTH REFERENCES:
```

# Appendix C — Standard Independent Review Template

```text
REVIEW ID:
CHANGE / PR:
REVIEWER:

VERDICT: APPROVE / APPROVE WITH NON-BLOCKING FINDINGS / REQUEST CHANGES / REJECT

REQUIREMENT COMPLIANCE:
ARCHITECTURE COMPLIANCE:
CORRECTNESS:
TEST QUALITY:
SECURITY:
RISK CONTROL INTEGRITY:
DATA / QUANT VALIDITY:
OPERABILITY AND OBSERVABILITY:
MAINTAINABILITY:
MIGRATION AND ROLLBACK:
DOCUMENTATION:

BLOCKING FINDINGS:
NON-BLOCKING FINDINGS:
SUGGESTIONS:
RESIDUAL RISKS:
REQUIRED FOLLOW-UP:
```

# Appendix D — Reference Baseline

The project should verify current versions at the time of implementation. The following official references provide a durable baseline:

- C4 Model for software architecture visualization — https://c4model.com/
- NIST Secure Software Development Framework (SP 800-218 family) — https://csrc.nist.gov/projects/ssdf
- OWASP Software Assurance Maturity Model — https://owasp.org/www-project-samm/
- OWASP Application Security Verification Standard — https://owasp.org/www-project-application-security-verification-standard/
- SLSA supply-chain security specification — https://slsa.dev/spec/
- OpenTelemetry documentation and specification — https://opentelemetry.io/docs/
- Google Site Reliability Engineering resources — https://sre.google/
- DORA software delivery performance guidance — https://dora.dev/
- FinOps Framework — https://www.finops.org/framework/
- Conventional Commits 1.0.0 — https://www.conventionalcommits.org/en/v1.0.0/
- Semantic Versioning 2.0.0 — https://semver.org/
- FIX Trading Community standards and recommended practices — https://www.fixtrading.org/standards/
- Ethereum developer and smart-contract security documentation — https://ethereum.org/developers/docs/
- OpenZeppelin Contracts documentation — https://docs.openzeppelin.com/contracts/
- Chainlink Data Feeds documentation and developer responsibilities — https://docs.chain.link/data-feeds
- Safe Smart Account documentation — https://docs.safe.global/

---

# Appendix E — Final Charter Review Questions

Before approving a future charter revision, ask:

- Does it still drive real, usable vertical slices?
- Does it create unnecessary process or complexity?
- Are critical risks independently controlled?
- Are research and live execution clearly separated but connected by evidence?
- Can one AI tool hand work to another without chat history?
- Is the repository still the source of truth?
- Are costs and economic value visible?
- Can obsolete components be retired safely?
- Does every live action remain observable, reconcilable, and reversible where possible?
- Is the current version aligned with official documentation and actual operational evidence?
