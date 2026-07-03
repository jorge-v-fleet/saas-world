# Agent SDK (OpenEnv-shaped)

A decoupled client/server SDK for driving an episode from agent code, mirroring Hugging Face
[OpenEnv](https://github.com/meta-pytorch/OpenEnv)'s contract *by shape* — same `reset` / `step` /
`state` methods returning `StepResult`, same `Action` / `Observation` / `State` fields — native,
with no `openenv` dependency.

Reward is **terminal**: `None` each step until the sim clock crosses the last eval checkpoint, then
the deterministic evaluator's final score (full breakdown in `observation.metadata["score"]`,
identical to `run-eval`).

```
# the single running service (localhost:8092): episode API + trajectory inspector UI
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

`SaasWorldEnvironment` (server-side) is also usable in-process without HTTP; `env.step(...)` returns
the `SaasWorldObservation` directly. One environment = one session (single writer) — run one process
per concurrent episode.

## Trajectory inspector

The same server hosts a read-only inspector at `http://127.0.0.1:8092/inspector` — a lightweight UI
over `runs/`. First view: the **raw trajectory inspector** (per-run action stream, args, events, and
the evaluator score breakdown). It reads every run kind uniformly.

Runs are produced by two generators, both writing the standard layout the inspector reads
(`runs/<id>/manifest.json` + `trajectory.jsonl` + `score.json`, via `saasworld.trajectory.actionlog`):

- `scripts/pm_agent_llm.py` — a real LLM PM agent (Claude tool-use) driving an episode → `runs/agent-*`.
- `scripts/random_rollouts.py` — random-policy rollouts characterising the base reward distribution
  → `runs/rollouts/*` + a `rollouts-summary.json` aggregate.

## Action space

Verbs come in three clock classes (`data/actions.json`):

- **observe** — scoped reads, no time cost (`read_inbox`, `get_tasks`, `get_calendar`, …).
- **mutate** — zero-duration writes plus any follow-ups (`send_message`, `create_task`,
  `update_task`, `record_decision`, …).
- **advance** — the only verbs that move the clock: `wait` (`{"duration": <minutes>}`) and
  `attend_meeting` (`{"meeting": <id>}`, releases to the meeting's end).

NPC replies to a message you send are scheduled at the coworker's response delay and delivered when
you next advance past that time — see [NPC replies & novel messages](npc-replies.md).
