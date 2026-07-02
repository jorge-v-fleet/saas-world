# saas-world

Simulation environment for a project manager's first week at a small-to-medium SaaS company. Design docs in `docs/` (`docs/problem-def.md`, `docs/research/`, `docs/implementation/`).

**Status:** core loop (Kernel + World State + Tool API), the Scenario Loader + NPC engine, the deterministic Evaluator, the LLM NPC parser + eval extractor, and the Trajectory Store are implemented and green. Specs in `docs/implementation/`.

## Requirements

- Python 3.12+. No Docker, no external services, no API key (single local process; DuckDB is embedded).

## Setup

```
uv venv && source .venv/bin/activate     # or: python3.12 -m venv .venv && source .venv/bin/activate
uv pip install -e ".[dev]"               # or: pip install -e ".[dev]"
```

## Tests

```
pytest                 # everything
pytest -m kernel       # one system in isolation (also: state, toolapi)
pytest -m content      # content-addressed hashing
pytest -m scenario     # Scenario Loader (validate + seed + register + schedule)
pytest -m npc          # NPC decision core + reply rendering
pytest -m evaluator    # deterministic-predicate scoring (grade == replayable)
pytest -m npc_parser   # LLM NPC parser (intent classification + voice)
pytest -m extractor    # LLM eval extractor (prose -> structured claims)
pytest -m llm          # LLM client determinism layer (cache / replay, offline)
pytest -m observability# Trajectory Store (persist / replay / POV / index)
pytest -m integration  # cross-system interactions
pytest -m golden       # determinism / replay
pytest -m property     # hypothesis invariants
pytest -m validation   # data/actions.json catalog + eval.json rubric
ruff check . && mypy src
```

The full suite is **offline and key-free** — the LLM parser/extractor run in replay mode against a committed cassette (`tests/cassettes/`). No `ANTHROPIC_API_KEY` is needed except to refresh the cassette (`pytest -m llm --record`).

## Run the service (single process, localhost)

```
python -m saasworld.serve   # JSON-RPC on 127.0.0.1:8080
curl -s localhost:8080/rpc -d '{"jsonrpc":"2.0","id":1,"method":"action","params":{"verb":"read_inbox","args":{}}}'
```

## Drive a scenario — discover a hidden blocker

Start the service and POST JSON-RPC to `/rpc`:

1. `load_scenario {"name": "checkout-not-ready"}` — seeds the world, registers coworker NPCs (Priya, Sam, Nadia, Rohit), schedules the week's timeline.
2. `action send_message {"to": "org.be_b2", "body": "Is the PSP ready for Friday?", "refs": ["task.psp_integration"]}` — a **free-text** body (no intent arg); the LLM parser classifies it (offline, via cassette) to an intent the decision core acts on. The core reveals the blocker: `blockers.blocker.psp_cert.surfaced` flips (system-sourced, never by the parser).
3. `action wait {"duration": 120}` — advances simulated time; Priya's voiced reply is delivered after her modal response delay (90 min).
4. `get_state {"path": "messages"}` — the reply from `org.be_b2` references `blocker.psp_cert`; `get_state {"path": "blockers.blocker.psp_cert.surfaced"}` is now `true`.

Determinism is proven by `pytest -m golden` (byte-identical event log + snapshot); the parser call replays from the committed cassette, so no model is called.

## Score a run — deterministic Evaluator

Grading is pure deterministic Python over a trajectory — no LLM, state-grounded so activity padding scores 0.

```python
from saasworld.eval import score

result = score(trajectory, ground_truth)   # trajectory = {events, snapshots}; ground_truth = eval.json
print(result.final)                         # weighted sum in [0,1]
```

`score` projects world state at each checkpoint, grades every ground-truth predicate against real fields (never prose), and appends `checkpoint_score`/`final_score` records — read-only over the world, append-only records. Re-scoring the same trajectory is byte-identical (**grade == replayable**). A real-work run scores ~1.0; an activity-only run (messages + hand-set fields, no reveal, no decision) scores ~0.0.

## Trajectory Store — persist · replay · POV · cross-run index

Persist a rollout as a replay-grade log, reconstruct it byte-for-byte, project any actor's view, and query across runs — offline, no server (DuckDB is embedded).

```python
from saasworld.trajectory import open_run, replay, project, TrajectoryIndex

store = open_run(manifest, state=world, base_dir="runs")  # manifest.json + opening snapshot
kernel.add_sink(store.record)                             # tap the single-writer event stream
...                                                       # drive the episode
store.close_run(score)                                    # final snapshot + score.json

replay("run-id", "runs")                                  # byte-exact log + final snapshot, 0 model calls
project("run-id", "grader", at=30, scopes=scopes, base_dir="runs")   # pure on-demand POV
idx = TrajectoryIndex("index.duckdb"); idx.rebuild("runs")
idx.reward_hack(); idx.regression("inst-abc"); idx.failure_clusters() # named analyses
```

The index is disposable — drop `index.duckdb` and `rebuild`.
