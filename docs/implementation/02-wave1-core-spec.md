# Wave 1 spec — Core loop: Kernel + World State + Tool API

Implementation spec for the first buildable slice (`01-systems.md` systems 1–3). Goal: the **smallest loop that advances simulated time and mutates world state through actions**, fully deterministic and testable, with no LLM and no external services.

- **Stack:** Python 3.12+. Tool API = **local HTTP JSON-RPC** service. **Single process, no Docker.**
- **Out of scope (later waves):** NPC Engine, Evaluator, full Scenario Loader + `dataset_version` validation, Seeding Engine, Trajectory Store. Wave 1 uses a **minimal bootstrap seed**, not the frozen-instance loader.

## Design rules carried from research

- **Single writer:** only the Kernel applies state changes. Everything else reads.
- **Three clock classes** (`05`): `observe` (read, clock still), `mutate` (zero-duration event), `advance` (carries duration, releases the clock). No privileged advance-time verb — `wait` is just an `advance` action.
- **Constrained write surface** (`05`): no agent action may write derived/graded paths (`blockers.*.surfaced`, `tasks.*.blocked_by`, decision correctness). Enforced in one place (the writer).
- **Effects are data:** each action's effect is a delta-DSL op list bound from args (`data/actions.json`), not a per-verb code path.
- **No wall-clock:** sim-time is an integer; the Kernel never reads the OS clock.

## Contracts (the shared shapes)

- **Event** (internal, kernel-owned):
  ```
  Event { seq:int, sim_time:int, actor:str, kind:str, payload:dict, caused_by:int|null }
  ```
  `seq` = monotonic enqueue order; queue ordered by `(sim_time, seq)`. `sim_time` = integer sim-minutes from `t0`.
- **Delta-DSL op** (the only way state changes):
  ```
  { op:"set|append|inc|link|unlink", path:"tasks.T1.status", value:<any> }
  ```
- **Action envelope** (Tool API in): `{ verb:str, args:dict }`.
- **Observation** (Tool API out): `{ ok:bool, sim_time:int, ack:dict, events_since:[Event view], error?:{code,msg} }`.

## System specs

### 1. Simulation Kernel
- **State owned:** `SimClock` (int `now`), `EventQueue` (heap by `(sim_time, seq)`), monotonic `seq` counter.
- **API:**
  - `now() -> int`
  - `schedule(sim_time, actor, kind, payload, caused_by=None) -> seq`
  - `advance_until(t) -> list[Event]` — pop+apply every event with `sim_time <= t` in order; returns applied events.
  - `apply(event)` (internal) — look up the effect (from the action catalog / a system-event handler), bind args → deltas, call `state.apply(deltas, source=actor)`, then enqueue any follow-up events.
- **Guarantees:** `now()` non-decreasing; `seq` strictly increasing; applying is synchronous and single-threaded (one in-flight event at a time).
- **Depends on:** a `StateWriter` protocol (injected) — so the Kernel is testable against a fake state.

### 2. World State Store
- **State owned:** namespaced partitions — **core (on):** `org · projects · tasks · blockers · surfaces`; per-surface stores (chat/email/calendar/docs). Reserved partitions off in Wave 1.
- **API:**
  - `read(path) -> value` / `view(scope) -> dict` (scoped projection via `view_scope`)
  - `apply(deltas, source) -> None` — applies delta-DSL ops; **enforces the constrained-write guard** (rejects denied paths when `source != "system"`).
  - `snapshot() -> dict` / `restore(snap)` — deep, order-stable, round-trippable.
- **Guarantees:** mutation happens only inside `apply`; reads between events are stable; `restore(snapshot())` is identity.
- **Denied-path guard:** a static denylist (glob paths) checked per op; violation → raise, never silently drop.

### 3. Tool API (Action Space) — local HTTP JSON-RPC
- **Transport:** JSON-RPC 2.0 over `POST /rpc`; single process; one worker (requests serialized through the Kernel to preserve single-writer determinism). `GET /health` for liveness.
- **Methods:**
  - `action({verb, args}) -> Observation` — validate against `data/actions.json` (arg schema + preconditions + actor scope) → route by clock class:
    - `observe` → return scoped view, no event
    - `mutate` → `schedule(now, …)` + apply, return ack + events since last observation
    - `advance` → `advance_until(now + duration)`, return all events that fired, time-ordered
  - `observe({actor})`, `get_state({path})` (operator/debug, omniscient), `now()`, `load_bootstrap({name})`, `snapshot()` / `restore({snap})`.
- **Validation errors:** JSON-RPC error object (`-32602` invalid params / bad args, `-32601` unknown verb, custom `1001` precondition failed, `1002` denied write).
- **Depends on:** a `Kernel` protocol + read access to World State — both injected, so the API is testable with fakes and via `TestClient` (no real port).

## Testing strategy

Each system has an isolated suite (own directory + pytest marker) plus cross-system integration suites. Isolation is enabled by the injected `StateWriter` / `Kernel` protocols — fakes stand in for neighbors.

- **Unit — `-m kernel`** (`tests/kernel/`): queue ordering `(sim_time, seq)`; `advance_until` drains in order and stops at `t`; `now()` monotonic; `seq` strictly increasing; follow-up events enqueued; no OS-clock access (inject clock, assert not read). Uses a **fake StateWriter** recording deltas.
- **Unit — `-m state`** (`tests/state/`): each delta-DSL op; `snapshot/restore` identity; `view(scope)` projection correctness; **denied-path guard** rejects agent writes to `blockers.*.surfaced` / `tasks.*.blocked_by` but allows `system`. No Kernel needed.
- **Unit — `-m toolapi`** (`tests/api/`): action envelope validation (unknown verb, bad/missing args, precondition fail, scope violation) → correct JSON-RPC errors; clock-class routing (observe emits no event; mutate = zero-duration; advance releases clock); observation shape. Uses a **fake Kernel**; drives the app via FastAPI `TestClient`.
- **Integration — `-m integration`** (`tests/integration/`):
  - **Round trip:** `action(send_message)` over `TestClient` → event applied → `get_state` reflects it.
  - **Clock drain:** pre-schedule a future `system` event → `action(wait, {duration})` → the event fires, appears in `events_since`, state updated, order correct.
  - **Constrained-write end-to-end:** an action targeting a denied path → `1002`, grader-relevant field unchanged.
- **Determinism / golden — `-m golden`** (`tests/golden/`): a fixed scripted action sequence against a fixed bootstrap seed → capture resulting **event log + final snapshot** → assert **byte-identical** to a stored golden file. Regenerate with `pytest --update-golden`. This is the flagship proof of determinism + replay-grade behavior.
- **Property-based (hypothesis) — `-m property`**: for random *valid* action sequences + fixed seed:
  - two runs → identical event log + final state (determinism)
  - after `advance_until(t)`, all applied events have `sim_time <= t`, ordered by `(sim_time, seq)`
  - agent actions never change any denied path
- **Catalog validation — `-m validation`**: `data/actions.json` is well-formed — every entry has `id/class/args-schema/effect`, effect paths are valid partitions, no effect writes a denied path.

## How to run

```
# setup (no Docker, no services)
uv venv && source .venv/bin/activate
uv pip install -e ".[dev]"

# all tests
pytest

# a single system, in isolation
pytest -m kernel        # or: pytest tests/kernel
pytest -m state
pytest -m toolapi

# interactions only
pytest -m integration

# determinism proof
pytest -m golden

# lint + types
ruff check . && mypy src

# run the service (single process, localhost)
python -m saasworld.serve            # uvicorn app on :8080, 1 worker
curl -s localhost:8080/rpc -d '{"jsonrpc":"2.0","id":1,"method":"action","params":{"verb":"read_inbox","args":{}}}'
```

## Single service vs Docker (the answer)

- **Single process, no Docker.** Wave 1 has **no external dependencies**: no DB server (DuckDB isn't used until the Trajectory Store), no broker, no LLM. The whole system is one Python process serving JSON-RPC on localhost.
- **Tests don't bind a port** — they call the FastAPI app via `TestClient` in-process, so unit/integration/golden suites run with just a venv.
- **Docker is optional, later** — a single Dockerfile for reviewer reproducibility if wanted; never `compose`, since there's nothing to orchestrate. Revisit only if a future wave adds a real external service.

## Project layout

```
pyproject.toml            # deps: fastapi, uvicorn; dev: pytest, hypothesis, ruff, mypy
src/saasworld/
  clock.py                # SimClock (int now, no OS clock)
  events.py               # Event, EventQueue (heap by (sim_time, seq))
  kernel.py               # single-writer loop: schedule/advance_until/now/apply
  protocols.py            # StateWriter, KernelProto (for test isolation)
  state/
    store.py              # WorldState: read/view/apply/snapshot/restore
    deltas.py             # delta-DSL ops
    guard.py              # constrained-write denylist
    schema.py             # partitions + path validation
  actions/
    catalog.py            # load + validate data/actions.json
    effects.py            # bind args -> deltas + follow-up events
  api/
    rpc.py                # JSON-RPC dispatch + error mapping
    app.py                # FastAPI app (holds one Kernel+WorldState)
  serve.py                # uvicorn entrypoint (1 worker)
  bootstrap.py            # minimal world seed (org/company + a few projects/tasks)
tests/
  kernel/ state/ api/ integration/ golden/ property/ validation/
  conftest.py             # fixtures: fake StateWriter, fake Kernel, TestClient, bootstrap
  golden/*.jsonl          # stored event-log + snapshot goldens
```

## Definition of done (Wave 1)

- Scripted action sequence runs end-to-end over JSON-RPC and mutates state.
- `advance` drains scheduled events in `(sim_time, seq)` order; `now()` never reads wall-clock.
- **Golden determinism test passes** (byte-identical event log + final snapshot across runs).
- Constrained-write guard blocks agent writes to denied paths (unit + e2e).
- Each of the three systems passes its **own** suite in isolation (fakes for neighbors).
- `pytest` green; `ruff` + `mypy` clean.
- This doc's **How to run** commands work from a clean checkout with only a Python venv.

## Milestones

1. `clock` + `events` + `kernel` with fake state → `-m kernel` green.
2. `state` (store + deltas + guard + schema) → `-m state` green.
3. `actions` catalog load/validate + effects binding → `-m validation` green.
4. `api` (rpc + app) wired to real Kernel+State + `bootstrap` → `-m toolapi` + `-m integration` green.
5. `serve` entrypoint + golden + property suites → `-m golden` / `-m property` green; **DoD met**.
