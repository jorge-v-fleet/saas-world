# saas-world

Simulation environment for a project manager's first week at a small-to-medium SaaS company. Design docs in `docs/` (`docs/problem-def.md`, `docs/research/`, `docs/implementation/`).

**Status:** core loop (Kernel + World State + Tool API), the Scenario Loader + rule-based NPC, and the Trajectory Store are implemented and green. Specs in `docs/implementation/`.

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
pytest -m observability# Trajectory Store (persist / replay / POV / index)
pytest -m integration  # cross-system interactions
pytest -m golden       # determinism / replay
pytest -m property     # hypothesis invariants
pytest -m validation   # data/actions.json catalog
ruff check . && mypy src
```

## Run the service (single process, localhost)

```
python -m saasworld.serve   # JSON-RPC on 127.0.0.1:8080
curl -s localhost:8080/rpc -d '{"jsonrpc":"2.0","id":1,"method":"action","params":{"verb":"read_inbox","args":{}}}'
```

## Drive a scenario — discover a hidden blocker

Start the service and POST JSON-RPC to `/rpc`:

1. `load_scenario {"name": "checkout-not-ready"}` — seeds the world, registers coworker NPCs (Priya, Sam, Nadia, Rohit), schedules the week's timeline.
2. `action send_message {"to": "org.be_b2", "body": "PSP ready for Friday?", "intent": "ask_status", "refs": ["task.psp_integration"]}` — asking Priya directly satisfies her reveal gate; `blockers.blocker.psp_cert.surfaced` flips (system-sourced).
3. `action wait {"duration": 120}` — advances simulated time; her reply is delivered after her modal response delay (90 min).
4. `get_state {"path": "messages"}` — the reply from `org.be_b2` references `blocker.psp_cert`; `get_state {"path": "blockers.blocker.psp_cert.surfaced"}` is now `true`.

Determinism is proven by `pytest -m golden` (byte-identical event log + snapshot).

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
