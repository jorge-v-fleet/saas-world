# saas-world

Simulation environment for a project manager's first week at a small-to-medium SaaS company. Design docs in `docs/` (`docs/problem-def.md`, `docs/research/`, `docs/implementation/`).

**Status:** complete and green — Kernel + World State + Tool API, Scenario Loader + NPC engine, deterministic Evaluator, LLM NPC parser + eval extractor, Trajectory Store, the build-time Seeding Engine, and the `saasworld` operator CLI that ties them together. Single local process; no Docker, no external services, no API key (DuckDB is embedded; the LLM parser replays from a committed cassette).

## Quick start

Everything below is offline and key-free. From a clean checkout:

```
# 1 · install
uv venv && source .venv/bin/activate && uv pip install -e ".[dev]"

# 2 · build a scenario  (a template + seed -> a frozen, immutable instance; fully deterministic)
saasworld generate hidden-critical-blocker --seed 1206 --out /tmp/checkout
saasworld freeze   /tmp/checkout

# 3 · load it and act  (load prints a RUN_ID — use it below)
saasworld load    /tmp/checkout
saasworld step    --run RUN_ID --verb record_decision \
                  --args '{"about":"proj.checkout","type":"gonogo","action":"reschedule","new_date":"D8T17:00","owner":"org.be_b2"}'
saasworld advance --run RUN_ID --by 600

# 4 · score it
saasworld run-eval --run RUN_ID          # -> final ≈ 0.48  (acted on the blocker, correct call)
```

That's the whole loop: **generate a scenario, load it, take a PM action, get a defensible score.** Grading is pure deterministic Python over the trajectory and state-grounded — activity without real outcomes scores ~0, so the score can't be gamed by looking busy. Seed `1206` reproduces the hand-authored `checkout-not-ready` data byte-for-byte (same `instance_hash`).

## All commands

`saasworld --help` lists every verb. Add `--json` to any command for a machine-readable envelope; exit codes: `0` ok · `1` runtime · `2` usage · `3` integrity (gate reject / `dataset_version` mismatch / replay divergence).

**Build** — offline, no service (the Seeding Engine):

```
saasworld generate <archetype> --seed N --out DIR   # sample -> bind -> assemble -> project-eval
saasworld validate DIR                              # coherence · solvable-floor · non-trivial-ceiling
saasworld freeze   DIR                              # content-hash + provenance -> immutable instance
```

**Drive** — embedded backend, one-shot per command (state checkpointed between calls):

```
saasworld load    <instance>                        # seed world, register NPCs, open a run; prints RUN_ID
saasworld step    --run RUN_ID --verb <verb> --args '<json>'
saasworld advance --run RUN_ID --by <minutes>       # release the clock; drains NPC replies + timeline
saasworld observe --run RUN_ID --path <state.path>
saasworld run-eval --run RUN_ID                     # weighted breakdown
```

Discover the hidden blocker with a **free-text** message — the LLM parser classifies it offline (cassette) and the coworker reveals the blocker (system-sourced, never by the parser):

```
saasworld step    --run RUN_ID --verb send_message \
                  --args '{"to":"org.be_b2","body":"Is the PSP ready for Friday?","refs":["task.psp_integration"]}'
saasworld advance --run RUN_ID --by 180
saasworld observe --run RUN_ID --path blockers.blocker.psp_cert.surfaced   # -> true (discovered)
```

**Inspect & replay** the persisted trajectory:

```
saasworld traj ls
saasworld traj show   RUN_ID
saasworld traj replay RUN_ID                        # byte-exact reconstruction, zero model calls
saasworld traj pov    RUN_ID --actor grader --at 480  # the fact-view each predicate read
saasworld traj query  --reward-hack                 # high activity, ~0 real outcomes
```

**Persistent session** — for state living in one process across commands, start the service and pass `--backend http`:

```
python -m saasworld.serve                           # JSON-RPC on 127.0.0.1:8080
saasworld load /tmp/checkout --backend http
```

## Tests

```
pytest                       # full suite — offline & key-free (LLM replays from tests/cassettes/)
pytest -m <marker>           # one system in isolation; markers:
#   kernel state toolapi content scenario npc evaluator npc_parser extractor llm
#   seeding cli observability   integration golden property validation
ruff check . && mypy src
```

No `ANTHROPIC_API_KEY` is needed; set one only to refresh the cassette (`pytest -m llm --record`).

## Library APIs

The systems the CLI drives are usable directly.

```python
from saasworld.eval import score
result = score(trajectory, ground_truth)   # deterministic, state-grounded; re-scoring is byte-identical
print(result.final)                         # weighted sum in [0,1]
```

```python
from saasworld.trajectory import open_run, replay, project, TrajectoryIndex
store = open_run(manifest, state=world, base_dir="runs")   # manifest + opening snapshot
kernel.add_sink(store.record)                              # tap the single-writer event stream
store.close_run(score)                                     # final snapshot + score.json
replay("run-id", "runs")                                   # byte-exact log + final snapshot, 0 model calls
idx = TrajectoryIndex("index.duckdb"); idx.rebuild("runs")
idx.reward_hack(); idx.regression("inst-abc"); idx.failure_clusters()
```

The DuckDB index is disposable — drop `index.duckdb` and `rebuild`.
