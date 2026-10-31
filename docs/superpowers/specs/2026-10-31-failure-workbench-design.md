# Keel failure-discovery workbench

The user approved building failure discovery, reduction, and mutation testing end to end,
then requested suitable languages for different responsibilities.

## Design

Go owns seeded schedule generation, bounded search, one-event-at-a-time reduction,
and baseline comparisons. A long-lived Python JSON-lines subprocess executes each
schedule against a fresh in-memory SQLite database and the real payment domain,
outbox publisher, and provider simulator. JavaScript presents results in the existing
FastAPI application. No extra third-party Go or JavaScript dependencies are required.

Four deliberately faulty lab adapters omit durable intent, acknowledge prematurely,
bypass stale-lease fencing, or change the provider idempotency key. They never modify
the application implementation or connect to its broker/database. The broker and
clock boundaries are controlled in-process; this is not a distributed chaos test.

Every replay checks independently specified invariants and captures per-event state.
Search includes structured recovery schedules and seeded shuffled schedules. A killed
mutant must reproduce a violation that does not occur in the correct implementation.
Reduction preserves the same invariant and finishes only when deleting any single
remaining event no longer reproduces it. This is 1-minimal, not globally shortest.
An unobserved failure is reported as survived, never as proof of correctness.

API requests validate seed, budget, trace length, mutation names and concurrency.
Go uses a deadline-bound child process. Python bounds subprocess duration and report
size. Saved runs use an additive database table; exports are JSON, Markdown and an
executable pytest regression test. A standalone local server uses a separate SQLite
file so the feature can be demonstrated without Docker, PostgreSQL or RabbitMQ.

## Alternatives

A pure Python implementation would be simpler but would not implement the requested
language split. Reimplementing payments in Go would test a second model instead of
the application. The selected design keeps one payment implementation and an explicit
versioned JSON contract. Rust or more services would add complexity without a present need.

## Interface and acceptance

`/lab` offers mutation selection, seed and search budget, saved campaigns, failure
details, original/reduced sequences, state snapshots, baseline evidence and exports.
`python -m payops.lab` supports build, run and serve. Docker builds the Go executable
in a separate stage. Jenkins runs Go checks and the full Python/JS suites.

Acceptance: all four faults are detected with the documented seed; each reduced
sequence reproduces its reported invariant; every single-event deletion removes that
invariant; the baseline passes; exported tests pass normally and fail with their
mutant selected; reports survive reload; browser flows work on desktop and mobile.

No assertion of worldwide novelty, exhaustive exploration, network-failure fidelity,
PostgreSQL concurrency correctness, production readiness or historical replay is made.
