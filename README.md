# saas-world

Simulation environment for a project manager's first week at a small-to-medium SaaS company. Design docs in `docs/` (`docs/problem-def.md`, `docs/research/`, `docs/implementation/`).

**Status:** implementing **Wave 1** — the core loop (Kernel + World State + Tool API). Spec: `docs/implementation/02-wave1-core-spec.md`. The scaffold ships **TDD-red**: implement Wave 1 to turn the suite green.

## Requirements

- Python 3.12+. No Docker, no external services in Wave 1 (single local process).

## Setup

```
uv venv && source .venv/bin/activate     # or: python3.12 -m venv .venv && source .venv/bin/activate
uv pip install -e ".[dev]"               # or: pip install -e ".[dev]"
```

## Tests

```
pytest                 # everything
pytest -m kernel       # one system in isolation (also: state, toolapi)
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
