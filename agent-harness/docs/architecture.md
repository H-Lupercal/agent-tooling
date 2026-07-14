# Agent Harness foundation architecture

The foundation is an event-sourced collaboration runtime. SQLite is authoritative; in-memory
queues and controller state can be reconstructed or replaced without changing history.

```text
                                 child request
                                      |
                                      v
User / CLI ---- goal ----> Run Controller ----> Child Admission
                              |   |                  |
                         prompt|   |events           | admitted adapter
                              v   v                  v
                        Fake Adapters --------> Collaboration Room
                                                   |       |
                                      persist first|       |publish
                                                   v       v
                                            SQLite Event   subscriber
                                               Store       queues
                                                   |
                                      replay / show / resume
                                                   |
                                                   v
                                            JSONL Receipt
```

## Components

| Component | Responsibility |
| --- | --- |
| Run Controller | Starts and resumes runs, limits simultaneous speakers, orders control receipts before completion, and coordinates adapters. |
| Collaboration Room | Persists every event before delivering it to bounded subscriber queues. |
| Event Store | Transactionally assigns per-run sequence numbers and replays canonical event JSON from SQLite. |
| Fake Adapter | Emits deterministic offline message streams and supports hard interruption for tests and demonstrations. |
| Child Admission | Validates lineage, selected context, participant limits, spawn depth, and reserved token budgets before adding a child. |
| Receipts | Reconstruct run state solely from events and atomically export the full history as canonical JSONL. |

## Lifecycle

1. The controller persists `run.started` and the configured root roster.
2. Participant adapters respond concurrently within the configured speaker limit. The
   initial speaker cohort persists all start events before any response continues. SQLite
   writes run off the event loop, and every started, delta, completed, or interrupted message
   is an explicit published event with recursively immutable payload data.
3. Control operations publish request and outcome receipts. Run completion waits for an
   in-flight interruption receipt, preserving causal order.
4. Dynamic children join only after admission checks and receive a separate identity and
   explicitly selected context. Their execution task is tracked through completion; adapter
   failure persists a degradation event without deleting admission or lineage.
5. A restarted process replays SQLite events to identify terminal participants, the exact
   persisted roster and lineage, selected child context, and spent budget. Resume runs only
   persisted nonterminal participants, rejects root configuration drift, and appends
   `run.resumed` to the original history.
6. Export writes all canonical events to a same-directory temporary file, flushes and syncs
   it, then atomically replaces the requested receipt path.

## Boundaries and follow-on work

The controller never stores hidden model reasoning. It persists room-visible messages,
decisions, evidence references, and lifecycle facts. This slice intentionally excludes live
provider authentication, shared repository worktrees, consensus/evidence gates, and a full
interactive console; those are separate vertical slices behind the stable event and adapter
contracts.
