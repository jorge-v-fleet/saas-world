# Trajectory store — rollout logging & observability

How every rollout is persisted so we can replay it, observe it from any POV, and compare across trajectories to find failures / reward-hacks / what to improve. Builds on `02`'s canonical event log + determinism guards — determinism is a property; **replay lives here, not in a separate layer**.

## Core stance

- **The trajectory *is* the canonical event log, made durable.** Same one-queue log the kernel already emits — no parallel record to drift.
- **JSONL canonical + derived index.** One append-only `trajectory.jsonl` per run = source of truth (replay-grade, git-friendly); a DuckDB/SQLite **index over many runs** = cross-trajectory queries. The index is rebuildable from the JSONL — never authoritative.
- **POV views reconstructed on demand.** Store only the canonical log; project it through each actor's `view_scope` at query time. No materialized per-POV copies (matches "views are derived projections, never copies").
- **Replay-grade.** Every LLM parser/extractor call is logged with its cache key + output, so replaying the JSONL reproduces the episode byte-exactly — no model calls needed to re-observe.

## What one trajectory captures

- **Manifest** — `run_id`, `scenario_id`, seed, **agent-under-test id + version**, sim `t0`, plus two hash roles (per `04`):
  - **`dataset_version`** (whole-dataset hash) — *integrity only*: re-hashed on load, runtime **refuses to run on mismatch**, so a pinned run can never silently drift.
  - **`(instance_hash, action_space_version)`** — the **comparability key**: the frozen instance's content hash + the action-space subtree hash, i.e. exactly what the run depended on.
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

- **Index columns**: `run_id`, `scenario_id`, `scenario_archetype`, `instance_hash`, `action_space_version`, `dataset_version`, `seed`, `agent_version`, per-checkpoint scores, total, `#actions`, `#real_deltas`, `#messages`, sim/wall durations.
- **Enables**:
  - **Version regression** — same comparability key `(instance_hash, action_space_version)`, varying `agent_version` → did we improve? (robust to unrelated dataset edits, which only move `dataset_version`.)
  - **Failure clustering** — group low scores by which checkpoint dropped.
  - **Reward-hack signal** — high `#messages`, `#real_deltas ≈ 0`, low score → activity without outcomes.
  - **NPC-interaction stats** — discovery hops taken, reveals triggered, response latencies.

## Identity & comparability

- Two trajectories are comparable **iff same `(instance_hash, action_space_version)`** — the frozen scenario's exact bytes + the action semantics it ran under. `agent_version` varies to measure improvement; `seed` is baked into the instance. `dataset_version` is **not** the comparability key (it hashes the whole dataset, so unrelated edits would falsely fragment cohorts) — it is the load-time integrity guard only.
- Trajectory + its frozen scenario instance = **self-contained and re-runnable offline**.

## Suggested layout

```
runs/<run_id>/
  manifest.json      # scenario_id, instance_hash, action_space_version, dataset_version, seed, agent_version
  trajectory.jsonl   # append-only canonical event log (source of truth)
  snapshots/         # periodic + final state snapshots (replay checkpoints)
  score.json         # final breakdown (derivable from the log)
index.duckdb         # derived cross-run index — rebuildable, disposable
```

- **Tuning knobs** (not open questions): snapshot cadence (per-checkpoint vs every N events), JSONL compression, index refresh (incremental per run).
