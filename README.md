# saas-world

Simulation environment for a project manager's first week at a small-to-medium SaaS company. Design docs in `docs/` (`docs/problem-def.md`, `docs/research/`, `docs/implementation/`).

**Status:** complete and green — Kernel + World State + Tool API, Scenario Loader + NPC engine, deterministic Evaluator, LLM NPC parser + eval extractor, Trajectory Store, the build-time Seeding Engine, and the `saasworld` operator CLI that ties them together. Single local process; no Docker, no external services, no API key (DuckDB is embedded; the LLM parser replays from a committed cassette).

## Quick start

The repo ships pre-built scenarios under `data/scenarios/`, so you just **load one and drive it** — no build step. Everything below is offline and key-free. From a clean checkout:

```
# 1 · install
uv venv && source .venv/bin/activate && uv pip install -e ".[dev]"

# 2 · load a pre-built scenario  (load prints RUN_ID = checkout-not-ready.baseline.0)
saasworld load data/scenarios/checkout-not-ready

# 3 · discover the hidden blocker with a free-text message, then take the PM call
saasworld step    --run RUN_ID --verb send_message \
                  --args '{"to":"org.be_b2","body":"Is the PSP ready for Friday?","refs":["task.psp_integration"]}'
saasworld advance --run RUN_ID --by 120                                    # NPC reply fires; blocker surfaces
saasworld observe --run RUN_ID --path blockers.blocker.psp_cert.surfaced   # -> true (discovered)
saasworld step    --run RUN_ID --verb record_decision \
                  --args '{"about":"proj.checkout","type":"gonogo","action":"reschedule","new_date":"D8T17:00","owner":"org.be_b2"}'
saasworld advance --run RUN_ID --by 600

# 4 · score it
saasworld run-eval --run RUN_ID          # -> final ≈ 0.86  (discovered + acted + correct call)
```

That's the whole loop: **load a scenario, discover the hidden blocker, take the right PM call, get a defensible score.** Grading is pure deterministic Python over the trajectory and state-grounded — activity without real outcomes scores ~0, so the score can't be gamed by looking busy. (Authoring or generating *new* scenarios is a separate build-time step — see [Advanced](#advanced--authoring--generating-scenarios).)

## All commands

`saasworld --help` lists every verb. Add `--json` to any command for a machine-readable envelope; exit codes: `0` ok · `1` runtime · `2` usage · `3` integrity (gate reject / `dataset_version` mismatch / replay divergence).

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
saasworld load data/scenarios/checkout-not-ready --backend http
```

## Agent SDK (OpenEnv-shaped)

A decoupled client/server SDK for driving an episode from agent code, mirroring Hugging Face [OpenEnv](https://github.com/meta-pytorch/OpenEnv)'s contract *by shape* (`reset` / `step` / `state` → `StepResult`, same `Action` / `Observation` / `State` fields) — native, no `openenv` dependency. Reward is **terminal**: `None` each step until the sim clock crosses the last eval checkpoint, then the deterministic Evaluator's final score (full breakdown in `observation.metadata["score"]`), identical to `run-eval`.

```
# server (separate process, localhost:8092 — off the Tool API's 8080)
saasworld-env-serve          # or: python -m saasworld.openenv.serve
```

```python
from saasworld.openenv import SaasWorldEnv, SaasWorldAction

with SaasWorldEnv("http://127.0.0.1:8092") as env:
    res = env.reset(scenario="checkout-not-ready")
    res = env.step(SaasWorldAction("send_message",
                   {"to": "org.be_b2", "body": "Is the PSP ready for Friday?",
                    "refs": ["task.psp_integration"]}))
    res = env.step(SaasWorldAction("wait", {"duration": 120}))         # Priya replies; blocker surfaces
    res = env.step(SaasWorldAction("record_decision",
                   {"about": "proj.checkout", "type": "gonogo", "action": "reschedule"}))
    while not res.done:                                                # advance to end-of-week
        res = env.step(SaasWorldAction("wait", {"duration": 600}))
    print(res.reward)                                                  # evaluator final in [0,1]
```

`SaasWorldEnvironment` (server-side) is also usable in-process without HTTP; `env.step(...)` returns the `SaasWorldObservation` directly. One environment = one session (single writer) — run one process per concurrent episode.

### NPC replies & novel messages

By default the NPC parser runs **offline in replay mode**: it classifies each message body by looking it up in a committed cassette (`tests/cassettes/default.jsonl`). The scenario bodies shown above are recorded, so coworkers reply for real, key-free.

A **novel** free-text body the cassette doesn't cover (any agent that phrases things its own way) can't be classified offline. The engine then **fails closed** — it bypasses the decision core so no gated fact can leak on an unclassifiable message — and the coworker replies with a bare acknowledgement (`"Ack."`). The sim stays live; this is by design, not an error. It's logged once per process as a single `INFO` line (not a traceback); raise `saasworld.npc.engine` to `WARNING` to silence it entirely.

To get real replies to novel messages, **record** them against a live model once (needs a key only at record time), then replay against the enriched cassette key-free:

```
# record: drive your agent against the env in record mode; novel messages append to the cassette
make record-cassette CASSETTE=/tmp/agent.jsonl           # needs ANTHROPIC_API_KEY
#   (or: SAASWORLD_LLM_MODE=record SAASWORLD_CASSETTE=/tmp/agent.jsonl saasworld-env-serve)

# replay: subsequent offline runs now classify those bodies for real
SAASWORLD_CASSETTE=/tmp/agent.jsonl saasworld-env-serve
```

## Advanced — authoring & generating scenarios

Only needed to add *new* cases to the dataset; the pre-built scenarios above need none of this. Build-time is offline, no service (the Seeding Engine):

```
saasworld generate <archetype> --seed N --out DIR   # template + seed -> candidate (sample->bind->assemble->project-eval)
saasworld validate DIR                              # the gate: coherence · solvable-floor · non-trivial-ceiling
saasworld freeze   DIR                              # content-hash + provenance -> immutable instance
```

- **generate** samples a template's slots into a candidate instance (the 5 files) under `--out` (default `data/candidates/`, gitignored & regenerable). Same `(archetype, seed)` is byte-identical.
- **validate** is the promotion filter: a candidate is freezable only if it passes all three sub-gates (a *competent* solver scores ~1.0, a *lazy* one ~0). Failing candidates are rejected, never frozen.
- **freeze** stamps the passing instance immutable. To add it to the committed dataset, place/freeze it under `data/scenarios/` and commit that — candidates and `runs/` stay ignored.

Hand-authoring (like `checkout-not-ready`, `"authored": "by-hand"`) writes the same 5 files directly. The `scenario-author` agent (`.claude/agents/`) interviews you and drives this whole loop.

## Tests

```
pytest                       # full suite — offline & key-free (LLM replays from tests/cassettes/)
pytest -m <marker>           # one system in isolation; markers:
#   kernel state toolapi content scenario npc evaluator npc_parser extractor llm
#   seeding cli observability   integration golden property validation
ruff check . && mypy src
```

No `ANTHROPIC_API_KEY` is needed; set one only to record new cassette entries — see [NPC replies & novel messages](#npc-replies--novel-messages).

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
