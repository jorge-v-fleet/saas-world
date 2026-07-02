# Trajectory store — rollout logging & observability (v0 — to iterate)

How every rollout is persisted so we can replay it, observe it from any POV, and compare across trajectories to find failures / reward-hacks / what to improve. Builds on `02`'s Determinism & Replay.

## Core stance

- **The trajectory *is* the canonical event log, made durable.** Same one-queue log the kernel already emits — no parallel record to drift.
- **JSONL canonical + derived index.** One append-only `trajectory.jsonl` per run = source of truth (replay-grade, git-friendly); a DuckDB/SQLite **index over many runs** = cross-trajectory queries. The index is rebuildable from the JSONL — never authoritative.
- **POV views reconstructed on demand.** Store only the canonical log; project it through each actor's `view_scope` at query time. No materialized per-POV copies (matches "views are derived projections, never copies").
- **Replay-grade.** Every LLM parser/extractor call is logged with its cache key + output, so replaying the JSONL reproduces the episode byte-exactly — no model calls needed to re-observe.

## What one trajectory captures

- **Manifest** — `run_id`, scenario instance **content-hash** + seed, **agent-under-test id + version**, generator/substrate provenance, sim `t0`.
- **Ordered event records** (replay-grade) — uniform envelope, one per state-changing moment:
  - agent action (`verb + args`) + returned observation
  - fired events (NPC reply, autonomous wake-up, `meeting_start`, scheduled pressure)
  - NPC parser calls (input → chosen intent, verdict, cache key)
  - eval checkpoints (predicate results + weighted score)
  - clock advances (next-event jumps)
- **Snapshots** — periodic + final World State snapshots as replay checkpoints (not per-event; replay fills the gaps).
- **Score** — final weighted breakdown (also derivable from the log).

## Record shape (uniform envelope)

```
{ "run_id", "seq", "sim_time", "actor", "kind", "payload", "delta", "caused_by": <seq?> }
```

- `caused_by` links a follow-up to the event that triggered it → a causal chain, so tools can trace *why* something happened (e.g. this NPC reply ← that agent message).
- `delta` is the applied state change (the delta-DSL op from `05`), so state at any `seq` = replay deltas from the last snapshot.

## POV reconstruction (the observability payoff)

All are pure functions of the canonical log at a timestamp — no stored duplicates:

- **Agent POV** — project through the agent's `view_scope`: exactly what it could see, and when.
- **NPC POV** — each active NPC's scoped view + its intents / knowledge reveals.
- **Operator / omniscient POV** — the full canonical log.
- **Grader POV** — the eval fact-view (fields each predicate read) + score derivation.

## Cross-trajectory analysis (what tools build on top)

- **Index columns**: `run_id`, `scenario_archetype`, `scenario_hash`, `seed`, `agent_version`, per-checkpoint scores, total, `#actions`, `#real_deltas`, `#messages`, sim/wall durations.
- **Enables**:
  - **Version regression** — same `scenario_hash`, varying `agent_version` → did we improve?
  - **Failure clustering** — group low scores by which checkpoint dropped.
  - **Reward-hack signal** — high `#messages`, `#real_deltas ≈ 0`, low score → activity without outcomes.
  - **NPC-interaction stats** — discovery hops taken, reveals triggered, response latencies.

## Identity & comparability

- Two trajectories are comparable **iff same `scenario_hash`** (identical frozen world + eval). `agent_version` varies to measure improvement; `seed` is already inside the scenario provenance.
- Trajectory + its frozen scenario instance = **self-contained and re-runnable offline**.

## Suggested layout

```
runs/<run_id>/
  manifest.json      # provenance, scenario hash, agent version
  trajectory.jsonl   # append-only canonical event log (source of truth)
  snapshots/         # periodic + final state snapshots (replay checkpoints)
  score.json         # final breakdown (derivable from the log)
index.duckdb         # derived cross-run index — rebuildable, disposable
```

- **Tuning knobs** (not open questions): snapshot cadence (per-checkpoint vs every N events), JSONL compression, index refresh (incremental per run).
