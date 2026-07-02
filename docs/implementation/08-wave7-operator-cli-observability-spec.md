# Wave 7 spec — Operator CLI + Observability

Final buildable slice (`01-systems.md` system 9, driving 1–8 + 10). Goal: **a reviewer-facing CLI that ties every system together** — build a scenario offline (`generate/validate/freeze`), drive a live episode (`load/step/advance/observe/run-eval`), then inspect and replay the persisted trajectory (`traj ls/show/replay/pov/query`). This is the interface the problem brief asks for: documented commands to start the system, drive the main flows, and run the evaluation.

- **Stack:** Python 3.12+, on top of Waves 1–6 (Kernel, World State, Tool API, Scenario Loader, NPC Engine, Evaluator, Seeding Engine, Trajectory Store). Still **single process, no Docker.** DuckDB (Trajectory Store wave) is embedded/file-based — no server.
- **CLI framework:** **Typer** (thin Click wrapper) — declarative subcommands, auto `--help`, typed args, minimal boilerplate. Falls back cleanly to stdlib `argparse` if we choose to avoid the dep; only one small lib either way. No other new runtime deps.
- **Owns/mutates:** nothing — the CLI is **control + read only**. Build-time verbs write frozen instances (that is the Seeding Engine's job, invoked offline); runtime verbs drive the existing single-writer Kernel; observability verbs read the Trajectory Store.
- **Out of scope:** a web UI (the brief says a lightweight interface is fine — CLI only); any new simulation semantics (the CLI orchestrates existing systems, it does not add world behavior).

## Design rules carried from research

- **The CLI adds no authority.** It never mutates world state directly — every runtime verb routes through the Tool API / Kernel single-writer path. Observability verbs are pure reads over the canonical log (`06`). No parallel record, no second writer.
- **Build-time vs runtime boundary is a hard line** (`04`). `generate/validate/freeze` run **offline, with no running service and no episode** — they are the Seeding Engine's `generate <archetype> --seed N` / `validate <instance>` / `freeze <instance>` verbs surfaced on the operator surface. Runtime verbs never generate.
- **Everything the CLI prints is derivable.** POV views are on-demand projections of the log through each actor's `view_scope` (`06`), never materialized copies. `traj query` reads the **derived, rebuildable** DuckDB index — authoritative source stays the JSONL.
- **Determinism is observable.** `traj replay` reconstructs an episode byte-exactly from the JSONL + cached LLM calls (no model calls); a golden CLI session proves the whole flow is reproducible.
- **Scriptable by construction.** Every command supports `--json` (machine output) alongside the default human-readable rendering, so the CLI is both a reviewer UX and a test/automation surface.

## Contracts (the shapes the CLI speaks)

- **Backend selector** — how a runtime command reaches the app:
  - **embedded (default):** construct Kernel + WorldState + app in-process; run the command; tear down. Best for one-shot commands and tests (no port, deterministic).
  - **http:** talk to a running `saasworld.serve` JSON-RPC service over `POST /rpc` (Wave 1 transport). Best for a long-running interactive session where state persists across commands.
  - Selected by `--backend {embedded,http}` (default `embedded`) or `SAASWORLD_BACKEND` env; `--url` sets the HTTP endpoint (default `http://127.0.0.1:8080`).
- **Session handle** — embedded runtime state must persist across CLI invocations, so a session is keyed by `run_id` and its live state snapshot is checkpointed to the Trajectory Store between commands; the next command restores from it. (HTTP backend keeps state in the running process — no checkpoint dance.)
- **CLI result envelope** (what `--json` emits, uniform across verbs):
  ```
  { "ok": bool, "command": str, "run_id"?: str, "sim_time"?: int, "data": <any>, "error"?: {code, msg} }
  ```
  Human mode renders the same fields as a compact table/text; `--json` emits the envelope verbatim (stable key order).
- **Exit codes:** `0` ok · `1` runtime/precondition error (maps a JSON-RPC error) · `2` usage error (bad args, unknown verb — Typer/argparse) · `3` integrity failure (`dataset_version` mismatch, gate reject, replay divergence).

## Command surface (grouped by layer)

### build-time (offline — no running service, no episode)
- `saasworld generate <archetype> --seed N [--out DIR]` — Seeding Engine `sample→bind→assemble→project-eval`; writes a candidate instance. `--json` returns the resolved fact-map summary + output path.
- `saasworld validate <instance>` — runs the **validity gate** (coherence · solvable-floor · non-trivial-ceiling) + schema + `eval` weights-sum-to-1.0 check. Exit `3` on reject; `--json` lists each gate verdict.
- `saasworld freeze <instance>` — content-hash + provenance `(template_id, seed, substrate_hash, generator_version)`, writes manifest, marks immutable. `--json` returns `instance_hash` + provenance.
- (These three delegate straight to the Seeding Engine `engine/*` modules — the CLI is a thin front. No Kernel, no service.)

### runtime (drive the sim)
- `saasworld load <instance> [--agent-version V]` — Scenario Loader: validate `dataset_version`, seed world, register NPCs, schedule timeline, hand ground truth to the Evaluator; opens a Trajectory Store run. Prints `run_id`. Refuses on `dataset_version` mismatch (exit `3`).
- `saasworld step --run <run_id> --verb <v> [--args JSON]` — one agent action through the **Agent Harness → Tool API** (`step()`); returns the observation. This is a *mutate*/*observe* action.
- `saasworld advance --run <run_id> --to <sim_time> | --by <minutes>` — release the clock (`advance_until`); returns every event that fired, time-ordered (NPC replies, autonomous wake-ups, timeline pressure).
- `saasworld observe --run <run_id> [--actor agent|operator] [--path P]` — inspect current state: agent-scoped view (default) or operator/omniscient (`--path` reads a specific path). No event emitted (read).
- `saasworld run-eval --run <run_id>` — invoke the Evaluator over the trajectory at its checkpoints; appends score records to the trajectory; prints the weighted breakdown. `--json` returns per-checkpoint predicate results + total.
- Backend note: default **embedded** (one-shot, deterministic, no port). For a persistent interactive session, start `saasworld serve` (Wave 1 entrypoint) and pass `--backend http` so state lives in the running process across commands.

### observability (read the Trajectory Store — `06`)
- `saasworld traj ls [--scenario S] [--agent-version V]` — list runs from the DuckDB index (run_id, scenario, seed, agent_version, total score, #actions).
- `saasworld traj show <run_id> [--from SEQ] [--to SEQ]` — the canonical event log (operator POV): ordered records `{seq, sim_time, actor, kind, payload, delta, caused_by}`, with the `caused_by` chain.
- `saasworld traj replay <run_id>` — deterministically reconstruct the episode from `trajectory.jsonl` + cached LLM calls (**no model calls**); asserts the reconstruction matches persisted snapshots; exit `3` on divergence. `--json` emits the reconstructed final state hash.
- `saasworld traj pov <run_id> --actor <agent|npc|operator|grader> [--npc ID] --at <sim_time>` — project the log through that actor's `view_scope` at `sim_time`: agent = what it could see; npc = scoped view + intents/reveals; operator = full log; grader = the eval fact-view each predicate read + score derivation.
- `saasworld traj query <expr>` — cross-trajectory queries over the index. Named presets on the analyses from `06`:
  - `--regression --instance-hash H` — same `(instance_hash, action_space_version)`, varying `agent_version` → score trend.
  - `--failure-clusters` — group low scores by which checkpoint dropped.
  - `--reward-hack` — high `#messages`, `#real_deltas ≈ 0`, low score → activity without outcomes.
  - `--sql '<SELECT …>'` — escape hatch: raw read-only SQL over the index columns.

## How it works (the full reviewer arc)

1. **Build offline:** `generate hidden-critical-blocker --seed 7` → `validate <inst>` (gate green) → `freeze <inst>` → an immutable instance in `data/scenarios/` with a pinned `instance_hash`. No service running.
2. **Load:** `load data/scenarios/<inst>` → `dataset_version` re-hashed and matched, world seeded, NPCs registered, timeline scheduled, a `run_id` opened in `runs/<run_id>/`.
3. **Drive:** `step --verb send_message --args '{"to":"npc.be_b2","intent":"ask_status","...":"..."}'` → `advance --by 60` drains the NPC `deliver_reply` and any timeline pressure → `observe` shows `blockers.psp_cert.surfaced == true` (discovered). Repeat `step`/`advance` through the scripted resolution (record decision, inform stakeholder).
4. **Score:** `run-eval --run <run_id>` → Evaluator reads the trajectory, checks predicates at checkpoints, appends score records, prints the weighted breakdown (discover · act_on · correct_action · inform).
5. **Inspect / replay:** `traj show <run_id>` (causal log) → `traj pov <run_id> --actor grader --at <t>` (why each predicate scored) → `traj replay <run_id>` (byte-exact reconstruction, no model calls) → `traj query --regression` across agent versions.
6. Every step above prints human-readable by default and the same data under `--json` for scripting/tests.

## How it maps to the README main flows

- This wave **delivers/expands the top-level `README.md`** "start / drive / run eval / inspect" sections — the documented-commands deliverable the brief requires.
  - **Setup / start** → `Setup` block + `saasworld serve` (long-running) or nothing (embedded one-shots).
  - **Build a scenario** → `generate` / `validate` / `freeze`.
  - **Drive the main flow** → `load` → `step` → `advance` → `observe`.
  - **Run the evaluation** → `run-eval`, with the score-component explanation the brief wants inspectable.
  - **Inspect outcomes** → `traj show` / `pov` / `replay` (reward-hack resistance visible via `traj query --reward-hack`).
- README stays authoritative for commands; this spec is the design behind them. Interface stays lightweight — CLI only, no web UI.

## Testing strategy

Two new markers (`cli`, `observability`) join the Wave 1–6 suite. CLI tests invoke commands via Typer's `CliRunner` (in-process, no subprocess) against the **embedded** backend, so they stay deterministic and portless.

- **Unit — `-m cli`** (`tests/cli/`): per-verb arg parsing + dispatch (each `generate/validate/freeze/load/step/advance/observe/run-eval` routes to the right handler with parsed args); `--json` envelope shape (keys, stable order, `ok`/`error`); exit codes (`0/1/2/3`) for success, runtime error, usage error, integrity failure; `--backend` selection resolves embedded vs http; unknown verb / bad `--args` JSON → usage error. Neighbors faked where cheap (fake Seeding Engine for `generate`, fake Store for `traj`).
- **Unit — `-m observability`** (`tests/observability/`): `traj ls/show/query` render from a seeded index fixture; **POV projections correct** — agent POV excludes out-of-scope paths, grader POV surfaces exactly the eval fact-view, operator POV = full log (table over the four actors at several `sim_time`s); `query` presets emit the expected SQL/filters; `--reward-hack` flags the high-messages/zero-delta fixture.
- **Integration — `-m integration`** (`tests/integration/`): **drive a FULL episode via the CLI end-to-end** — `generate → validate → freeze` a scenario, `load` it, `step`+`advance` through the scripted discovery (message NPC, advance, discover blocker, record decision, inform stakeholder), `run-eval`, then `traj show` / `replay` / `pov` / `query`. Assert: `run-eval` breakdown matches the direct-Evaluator score; `traj replay` reproduces the final snapshot byte-for-byte; `traj pov --actor grader` derivation equals the eval records; `traj query` finds the run.
- **Golden — `-m golden`** (`tests/golden/`): a **scripted CLI session** (a fixed list of commands against a fixed seed) → capture concatenated `--json` output + the resulting `trajectory.jsonl` → assert **byte-identical** to a stored golden. Extends the Wave 1/2 golden up to the operator surface. Regenerate with `pytest --update-golden`.
- **Cross-backend check** — a subset of the integration flow runs against the **http** backend (spin up `serve` on a test port) to prove embedded and http produce the same observations/trajectory.
- Register `cli` and `observability` in `pyproject.toml` `[tool.pytest.ini_options].markers` (same convention as Wave 1).

## How to run

```
# build a scenario offline (no service running)
saasworld generate hidden-critical-blocker --seed 7 --out data/scenarios/gen-7
saasworld validate data/scenarios/gen-7
saasworld freeze   data/scenarios/gen-7

# drive an episode (embedded, one-shot — default backend)
saasworld load data/scenarios/checkout-not-ready            # prints RUN_ID
saasworld step    --run RUN_ID --verb send_message \
                  --args '{"to":"npc.be_b2","intent":"ask_status","body":"payments status?"}'
saasworld advance --run RUN_ID --by 60
saasworld observe --run RUN_ID --actor agent
saasworld run-eval --run RUN_ID                             # weighted breakdown

# inspect / replay the trajectory
saasworld traj ls
saasworld traj show   RUN_ID
saasworld traj replay RUN_ID                                # byte-exact, no model calls
saasworld traj pov    RUN_ID --actor grader --at 480
saasworld traj query  --regression --instance-hash <H>
saasworld traj query  --reward-hack

# any command, machine-readable
saasworld run-eval --run RUN_ID --json

# long-running interactive session (state persists in the process)
saasworld serve &                                           # JSON-RPC on :8080
saasworld load ... --backend http && saasworld step ... --backend http

# tests
pytest -m cli             # arg parsing + dispatch + exit codes
pytest -m observability   # traj views + POV projections
pytest -m integration     # full CLI-driven episode
pytest -m golden          # scripted-session determinism
pytest                    # all waves
ruff check . && mypy src
```

## Single service vs Docker

- **Unchanged: single process, no Docker, no external server.** DuckDB (from the Trajectory Store wave) is **embedded/file-based** (`index.duckdb`) — no daemon to run.
- **Build-time verbs run fully offline** — `generate/validate/freeze` need no service and no episode; they read the substrate and write `data/scenarios/`.
- **Runtime verbs default to embedded** (construct the app in-process per command) — no port, deterministic, ideal for tests and one-shots. The **http** backend is opt-in for a persistent session and reuses the Wave 1 `serve` entrypoint.
- **Tests never bind a port** except the one cross-backend check; the rest use Typer's `CliRunner` + embedded backend, so the whole suite runs with just a venv.

## Project layout (additions)

```
src/saasworld/
  cli/
    __init__.py
    main.py            # Typer app root; global --json/--backend/--url; exit-code mapping
    build.py           # generate / validate / freeze  -> Seeding Engine (engine/*)
    runtime.py         # load / step / advance / observe / run-eval -> Harness/Kernel/Evaluator
    traj.py            # traj ls/show/replay/pov/query -> Trajectory Store + DuckDB index
    backend.py         # embedded vs http selector; session restore/checkpoint
    render.py          # human table/text <-> --json envelope (shared)
tests/
  cli/                 # -m cli   : arg parsing, dispatch, --json shape, exit codes
  observability/       # -m observability : traj views + POV projections + query presets
  # integration/ + golden/ extended to the CLI-driven full episode
pyproject.toml         # + [project.scripts] saasworld = "saasworld.cli.main:app"
                       # + markers: cli, observability ; dep: typer
README.md              # start / drive / run-eval / inspect sections filled from this wave
```

## Definition of done (Wave 7)

- From a **clean checkout**, a reviewer runs documented commands to: **generate** a scenario, **validate + freeze** it, **load** and **drive** it (`step`/`advance`/`observe`), **score** it (`run-eval`), and **inspect/replay** the trajectory (`traj show`/`replay`/`pov`/`query`) — all via the CLI.
- Every command has a human-readable and a `--json` mode; exit codes distinguish ok / runtime / usage / integrity failures.
- Build-time verbs run **offline** (no service); runtime verbs default to **embedded**, with **http** working against `serve`.
- `traj replay` reproduces the episode byte-exactly (no model calls); `traj pov` projections are correct for all four actors.
- Full **CLI-driven integration** episode passes; **golden scripted session** is byte-identical; `cli` + `observability` markers green; all prior-wave markers still green; `ruff` + `mypy` clean.
- `README.md` start/drive/run-eval/inspect sections match the working commands.

## Milestones

1. `cli/main.py` + `backend.py` (Typer root, global flags, embedded/http selector, exit-code mapping) → `-m cli` skeleton green.
2. `cli/build.py` wiring `generate/validate/freeze` to the Seeding Engine → offline build works end-to-end.
3. `cli/runtime.py` (`load/step/advance/observe/run-eval`) over Harness/Kernel/Evaluator, with session checkpoint/restore → drive + score an episode.
4. `cli/traj.py` (`ls/show/replay/pov/query`) over the Trajectory Store + DuckDB index → `-m observability` green.
5. Full CLI-driven `-m integration` episode + golden scripted session + README sections → `-m golden` green; **DoD met** (final wave).
