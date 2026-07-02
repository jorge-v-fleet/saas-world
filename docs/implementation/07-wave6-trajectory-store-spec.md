# Wave 6 spec — Trajectory Store (persist · replay · POV · cross-run index)

Implementation spec for `01-systems.md` **system 10**. Goal: **make the canonical event log durable and queryable** — persist each rollout as a replay-grade `trajectory.jsonl` + snapshots + manifest, reconstruct the episode byte-exactly (`replay`) and any actor's view (`project`) with **zero model calls**, and maintain a **derived, rebuildable** DuckDB index over `runs/` for cross-trajectory queries. This wave **is** the replay mechanism: determinism is a property (already enforced in Waves 1/4); replay lives here, not in a separate layer. Full design: `../research/06-trajectory-store.md`.

- **Stack:** Python 3.12+, on top of Waves 1–5 (Kernel, World State, Tool API, Scenario Loader, NPC Engine, Evaluator, LLM cache). **Single process, no Docker.** New runtime dep: **`duckdb`** (embedded/file-based — no server).
- **Out of scope (later waves):** the Operator CLI surface over these (`traj ls/show/replay/pov/query` — Wave 7); any new simulation semantics. This wave adds **persistence + read APIs only**, never a second writer.

## Design rules carried from research

- **The trajectory *is* the canonical event log, made durable** (`06`). The store persists the same one-queue log the Kernel already emits — **no new source of truth**, no parallel record to drift. Every viewpoint and score derives from it.
- **JSONL canonical + derived index** (`06`). One append-only `trajectory.jsonl` per run = source of truth (replay-grade, git-friendly); a DuckDB **index over many runs** = cross-trajectory queries. The index is **rebuildable from the JSONL — never authoritative** (drop it, rebuild, identical results).
- **POV views are on-demand projections, never copies** (`06`, matches `05` "views are derived projections"). Store only the canonical log; project through each actor's `view_scope` at a timestamp at query time. No materialized per-POV duplicates.
- **Replay-grade / determinism is record-replay** (`04`, `05`). Every LLM parser/extractor call was logged by the Wave 4 cache with its cache key + output; replay reads those, so re-observing an episode makes **zero model calls**. State at any `seq` = replay the deltas from the last snapshot.
- **Comparability is a hash contract, integrity is another** (`04`, `06`). Two hash roles, never conflated: `dataset_version` (whole-dataset hash) is load-time integrity only; `(instance_hash, action_space_version)` is the comparability key.

## Contracts (the shared shapes)

- **Record envelope** (one JSONL line per state-changing moment — a superset of the Wave 1 kernel `Event`, adding `run_id` + applied `delta`):
  ```
  Record { run_id:str, seq:int, sim_time:int, actor:str, kind:str,
           payload:dict, delta:[DeltaOp]|null, caused_by:int|null }
  ```
  `seq` = the Kernel's monotonic order; `caused_by` links a follow-up to its trigger → a causal chain (NPC reply ← agent message). `delta` = the applied delta-DSL ops (`05`), so state is reconstructable without a per-event snapshot.
- **Snapshot record** (replay checkpoint; periodic + final): `{ seq:int, sim_time:int, state:<WorldState.snapshot()> }` — order-stable, round-trippable (Wave 1 `restore(snapshot())` identity).
- **Manifest** (`runs/<run_id>/manifest.json`) — one per run, written at open:
  ```
  { run_id, scenario_id, instance_hash, action_space_version,
    dataset_version, seed, agent_version, sim_t0,
    llm_models: { npc_parser, evaluator },   # resolved per-role models (config/settings.toml)
    started_at_seq }          # provenance; NOT wall-clock
  ```
  - `dataset_version` — **integrity only** (Scenario Loader re-hashes on load, refuses on mismatch; `04`).
  - `(instance_hash, action_space_version)` — the **comparability key**.
  - `llm_models` — the **resolved model per LLM role** (`npc_parser` = env `SAASWORLD_NPC_PARSER_MODEL` > `[llm.npc_parser].model` > `[llm].model`; `evaluator` = env `SAASWORLD_EVALUATOR_MODEL` > `[llm.evaluator].model` > `[llm].model`; both default `claude-sonnet-5`). Cassettes are keyed per role+model (`05`), so replay must know which model each role's log was recorded under.
- **Index row** (derived, one per run — columns from `06`): `run_id, scenario_id, scenario_archetype, instance_hash, action_space_version, dataset_version, seed, agent_version, <per_checkpoint_scores…>, total, n_actions, n_real_deltas, n_messages, sim_duration, wall_duration`.
- **Store API** (system 10 interface): `record(event)` · `replay(run_id)` · `project(run_id, actor, at)` · `query(...)`.

## System spec (system 10 — Trajectory Store)

One system, four cooperating modules. All read the canonical log; only `store.record` writes, and only appends.

### Record (`trajectory/store.py`)
- **Owns/mutates:** `runs/<run_id>/` files (`manifest.json`, `trajectory.jsonl`, `snapshots/`, `score.json`). Nothing in the world.
- **API:**
  - `open_run(manifest) -> TrajectoryStore` — create `runs/<run_id>/`, write `manifest.json` (fields above, incl. resolved `llm_models`).
  - `record(event) -> None` — serialize the kernel event (+ applied `delta`, `caused_by`) as one canonical-JSON line appended to `trajectory.jsonl`. Append-only; never rewrites a prior line.
  - `snapshot(seq, sim_time, state) -> None` — write a replay checkpoint to `snapshots/<seq>.json`. Cadence = **per-checkpoint or every N events** (config knob, default per-eval-checkpoint + final).
  - `close_run(score) -> None` — final snapshot + `score.json` (also derivable from the log; stored for convenience).
- **Capture point:** the store is registered as a Kernel **sink** — the Kernel already produces the ordered event stream (single writer); the store taps it. The Evaluator's checkpoint/score records (`07` system 7) arrive as normal events and are appended like any other (append-only, not a cycle: reads `seq < checkpoint`, appends new).
- **Guarantees:** canonical-JSON serialization (sorted keys, stable separators) → byte-stable lines; append order == kernel `seq` order; no wall-clock written (provenance timestamps are sim-time / seq).

### Replay (`trajectory/replay.py`)
- **API:** `replay(run_id) -> ReplayResult` — reconstruct the episode from `trajectory.jsonl` + `snapshots/` + the Wave 4 LLM cassette. **Zero model calls.**
  - `state_at(run_id, seq) -> WorldState` — restore the nearest snapshot with `snap.seq <= seq`, then apply each record's `delta` forward to `seq`. (State at any `seq` = last snapshot + replayed deltas.)
  - Re-emits the event log deterministically; any LLM-touching event (NPC reply, extractor) resolves through the **replay-mode** LLM client → cassette hit, byte-identical output; a cassette miss is a hard error, never a live call (`05`).
- **Guarantees:** replaying `trajectory.jsonl` reproduces a **byte-identical event log + final snapshot**; **zero** model calls (assertable against a network-forbidding fake). The store adds no new randomness — determinism is inherited (Kernel single-writer + Wave 4 cache), the store just persists the inputs.

### POV projection (`trajectory/project.py`)
- **API:** `project(run_id, actor, at) -> View` — a **pure function** of the canonical log at `sim_time == at`; no stored duplicates.
  - Reconstruct `state_at` the last event with `sim_time <= at`, then apply the actor's `view_scope` (`05`):
    - **agent** — the agent's scoped view: exactly what it could see, and when.
    - **npc `<id>`** — that NPC's scoped view + its intents / knowledge reveals.
    - **operator / omniscient** — the full canonical log (no scoping).
    - **grader** — the eval fact-view (the fields each predicate read) + score derivation.
- **Guarantees:** deterministic and idempotent; identical to what the actor saw live (same `view_scope` code path as runtime); never materialized — recomputed per call.

### Index + query (`trajectory/index.py`)
- **Owns/mutates:** `index.duckdb` (derived, disposable).
- **API:**
  - `rebuild(runs_dir) -> None` — scan every `runs/<run_id>/` (manifest + JSONL + score), derive the index row (aggregate `n_actions`, `n_real_deltas`, `n_messages`, durations, per-checkpoint scores), write to DuckDB. `refresh(run_id)` = incremental single-run upsert.
  - `query(...)` — cross-trajectory reads. Named analyses (`06`):
    - **`regression(instance_hash)`** — filter same `(instance_hash, action_space_version)`, vary `agent_version` → score trend (robust to unrelated dataset edits, which only move `dataset_version`, not the comparability key).
    - **`failure_clusters()`** — group low `total` by which checkpoint dropped.
    - **`reward_hack()`** — high `n_messages` + `n_real_deltas ≈ 0` + low `total` → activity without outcomes.
    - **`sql(<SELECT…>)`** — read-only escape hatch over the index columns.
- **Guarantees:** the index is **never authoritative** — fully rebuildable from JSONL; `drop + rebuild == identical rows`. DuckDB is embedded/file-based — no server, no daemon.

## How it works

1. **Open:** on `load` (Scenario Loader), `open_run(manifest)` creates `runs/<run_id>/` and writes `manifest.json` with `scenario_id`, `seed`, `agent_version`, both hash roles, and the resolved `llm_models`.
2. **Record:** the store is a Kernel sink — every applied event streams to `trajectory.jsonl` as a canonical-JSON line `{run_id, seq, sim_time, actor, kind, payload, delta, caused_by}`. NPC replies / extractor calls carry their cassette-backed outputs (already in the log via Wave 4). Snapshots land at eval checkpoints (+ final).
3. **Score:** the Evaluator reads the trajectory, appends checkpoint/score records (normal appended events); `close_run` writes the final snapshot + `score.json`.
4. **Replay:** `replay(run_id)` restores from snapshots + replays deltas, resolving any LLM event through the replay-mode cassette → byte-identical event log + final snapshot, **no model calls**.
5. **Observe any POV:** `project(run_id, actor, at)` reconstructs agent/NPC/operator/grader views by projecting the log through the actor's `view_scope` at `at` — pure, on demand.
6. **Compare across runs:** `index.rebuild(runs/)` derives one row per run into `index.duckdb`; `query(...)` runs the three named analyses. Drop `index.duckdb` any time — `rebuild` reproduces it exactly.

## Testing strategy

New marker **`observability`** (`tests/observability/`) joins the Wave 1–5 suite, plus cross-system integration. Isolation via injected fakes: a **FakeLLM/replay cassette** (`05`) so no test touches the network; a scripted episode driver so record/replay tests need no live agent.

- **Unit — `-m observability`** (`tests/observability/`):
  - **record/replay:** drive a **scripted episode** → `record` each event → `replay(run_id)` produces a **byte-identical event log + final snapshot**; assert `state_at(seq)` == last-snapshot-plus-deltas for several `seq`; assert **zero model calls** (replay-mode client backed by a network-forbidding fake — any API attempt fails the test).
  - **POV projection:** at several `at` timestamps, assert agent POV **excludes out-of-scope paths**, NPC POV shows its scoped view + reveals, operator POV == full log, grader POV surfaces **exactly** the eval fact-view + score derivation. Projections are pure (same result on repeat calls).
  - **index + query:** build the index from a seeded `runs/` fixture; run all three named analyses (regression / failure-clusters / reward-hack) → asserted rows; **reward-hack** flags the high-`n_messages` / zero-`n_real_deltas` / low-score fixture; **regression** groups by `(instance_hash, action_space_version)` across `agent_version`. **Rebuildability:** `drop + rebuild` → **identical results**.
  - **manifest provenance:** all fields present incl. resolved `llm_models` (env override honored); comparability key == `(instance_hash, action_space_version)`; `dataset_version` present but **not** used as the comparability key.
- **Integration — `-m integration`** (`tests/integration/`): drive a full episode through the Kernel/Tool API (Waves 1–5, replay cassette) with the store attached → persist → `replay` reproduces the final snapshot byte-for-byte; the derived index finds the run; `project(grader)` derivation equals the Evaluator's appended score records.
- **Golden — `-m golden`** (`tests/golden/`): extend the Wave 1 golden — a fixed scripted episode → capture `trajectory.jsonl` + final snapshot → assert **byte-identical** to a stored golden; a second run replays to the same bytes. Regenerate with `pytest --update-golden`.
- Register `observability` in `pyproject.toml` `[tool.pytest.ini_options].markers` (same convention as Wave 1).

## How to run

```
# setup — adds one embedded dep (duckdb), still no Docker / no server
uv pip install -e ".[dev]"

# this system, in isolation (record/replay + POV + index, offline, no API key)
pytest -m observability

# interactions (full episode -> persist -> replay -> query)
pytest -m integration

# determinism / replay proof
pytest -m golden
pytest --update-golden          # regenerate goldens

# all waves
pytest
ruff check . && mypy src
```

- Programmatic use (until the Wave 7 CLI lands):
  ```
  store = open_run(manifest)                 # writes runs/<run_id>/manifest.json
  kernel.add_sink(store.record)              # tap the single-writer event stream
  ...                                        # drive the episode
  store.close_run(score)                     # final snapshot + score.json
  replay(run_id)                             # byte-exact reconstruction, 0 model calls
  project(run_id, "grader", at=480)          # on-demand POV
  index.rebuild("runs/"); index.query(...)   # cross-run analyses over index.duckdb
  ```

## Single service vs Docker (the answer)

- **Still single process, no Docker.** The new dep, **DuckDB, is embedded/file-based** (`index.duckdb`) — a library, not a server. There is nothing to orchestrate; no `compose`.
- **No network at runtime or in tests.** Persistence is local files under `runs/`; replay reads the local cassette (`05`) and makes **zero** model calls. The suite runs with just a venv, **no API key**.
- **The index is disposable.** `index.duckdb` can be deleted and rebuilt from JSONL at any time — it is a cache, not state to back up.

## Project layout (additions)

```
src/saasworld/
  trajectory/
    __init__.py
    store.py            # open_run / record / snapshot / close_run — append-only writer + Kernel sink
    replay.py           # replay(run_id) / state_at — snapshot + delta reconstruction, 0 model calls
    project.py          # project(run_id, actor, at) — pure POV via view_scope, never materialized
    index.py            # rebuild / refresh / query — derived DuckDB index + named analyses
tests/
  observability/        # -m observability : record/replay, POV projections, index+query, manifest
  # integration/ + golden/ extended to persist + replay + query
runs/                   # per-run output (git-ignored; goldens live under tests/golden/)
  <run_id>/
    manifest.json       # scenario_id, seed, agent_version, both hash roles, resolved llm_models (npc_parser + evaluator)
    trajectory.jsonl    # append-only canonical event log (source of truth)
    snapshots/<seq>.json# periodic + final replay checkpoints
    score.json          # final weighted breakdown (also derivable from the log)
index.duckdb            # derived cross-run index — rebuildable, disposable
pyproject.toml          # + dep: duckdb ; + marker: observability
```

## Definition of done (Wave 6)

- A scripted episode persists to `runs/<run_id>/` — `manifest.json` (incl. resolved `llm_models` + both hash roles), append-only `trajectory.jsonl`, periodic + final snapshots, `score.json`.
- **`replay(run_id)` reproduces a byte-identical event log + final snapshot with zero model calls** (asserted against a network-forbidding fake).
- `project(run_id, actor, at)` returns correct pure projections for agent / NPC / operator / grader at any `at` — no materialized duplicates.
- The DuckDB index builds from `runs/`, answers the three named analyses (regression / failure-clusters / reward-hack), and is **fully rebuildable** (drop + rebuild → identical results).
- Manifest comparability key is `(instance_hash, action_space_version)`; `dataset_version` is present as integrity-only, never the comparability key.
- `-m observability` green; `-m integration` + `-m golden` extended and green; all prior-wave markers still green; `ruff` + `mypy` clean.
- The **How to run** commands work from a clean checkout with only a Python venv (no Docker, no server, no API key).

## Milestones

1. `trajectory/store.py` — `open_run`/`record`/`snapshot`/`close_run`, canonical-JSON append + manifest (resolved model) → wired as a Kernel sink.
2. `trajectory/replay.py` — `state_at` (snapshot + delta replay) + `replay(run_id)` over the replay-mode cassette → byte-exact reconstruction, zero model calls.
3. `trajectory/project.py` — `project(run_id, actor, at)` via `view_scope` for all four actors → `-m observability` POV tests green.
4. `trajectory/index.py` — `rebuild`/`refresh`/`query` over DuckDB + the three named analyses → rebuildability + query tests green.
5. Extend `-m integration` (full episode → persist → replay → query) + `-m golden` (byte-identical trajectory); register `observability` marker + `duckdb` dep → **DoD met**.
```
