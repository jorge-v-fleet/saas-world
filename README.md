# saas-world

Simulation environment for a project manager's first week at a small-to-medium SaaS company. An agent
is dropped into a simulated work week and must drive real PM work through internal tool surfaces —
chat, email, calendar, task tracking, docs, meeting capture. The system grades whether the agent's
actions actually **improved outcomes**, not whether it was merely busy. Full brief: `docs/problem-def.md`.

- **Single local process** — no Docker, no external services, no API key. DuckDB is embedded; the
  LLM NPC parser replays from a committed cassette.
- **Simulated time is decoupled from wall-clock** — the clock advances by simulation, never by how
  long the model takes to think.
- **Deterministic, inspectable grading** — pure Python over the trajectory, state-grounded. Activity
  without real outcomes scores ~0, so the score can't be gamed by looking busy.

## Quick start

The repo ships the scenario **templates** under `data/templates/` plus one hand-authored example
(`checkout-not-ready`). Every other scenario is **generated from a template at setup time** — offline,
deterministic, and key-free — so instances stay build artifacts, never committed. From a clean checkout:

```bash
# 1 · install
uv venv && source .venv/bin/activate && uv pip install -e ".[dev]"

# 2 · build the scenarios from templates (offline & deterministic; skips gate-rejected seeds and
#     writes valid frozen instances into data/scenarios/, which is gitignored — regenerate anytime)
saasworld build-set delivery-slip  --count 10
saasworld build-set release-triage --count 8
#     -> each writes a data/sets/<archetype>.json manifest recording exactly which seeds back the set
#     (checkout-not-ready ships hand-authored — no build needed)

# 3 · start the OpenEnv server (single process, localhost:8092)
#     hosts the episode API (/reset, /step, /state) AND the trajectory inspector UI.
saasworld-env-serve          # or: python -m saasworld.openenv.serve
#     -> episode API:  http://127.0.0.1:8092
#     -> inspector UI: http://127.0.0.1:8092/inspector   (read-only view over runs/)
```

```python
# 3 · drive an episode from agent code
from saasworld.openenv import SaasWorldEnv, SaasWorldAction

with SaasWorldEnv("http://127.0.0.1:8092") as env:
    res = env.reset(scenario="checkout-not-ready")
    res = env.step(SaasWorldAction("send_message",
                   {"to": "org.be_b2", "body": "Is the PSP ready for Friday?",
                    "refs": ["task.psp_integration"]}))
    res = env.step(SaasWorldAction("wait", {"duration": 120}))         # NPC replies; blocker surfaces
    res = env.step(SaasWorldAction("record_decision",
                   {"about": "proj.checkout", "type": "gonogo", "action": "reschedule"}))
    while not res.done:                                                # advance to end-of-week
        res = env.step(SaasWorldAction("wait", {"duration": 600}))
    print(res.reward)                                                  # evaluator final in [0,1]
```

That's the whole loop: **reset a scenario, discover the hidden blocker, take the right PM call, get a
defensible terminal score.** Reward is `None` each step until the sim clock crosses the last eval
checkpoint, then the deterministic evaluator's final score (full breakdown in
`observation.metadata["score"]`).

Prefer a shell? The `saasworld` CLI drives the same loop one command at a time — see
[Operator CLI](docs/saas-world/cli.md).

### Example: a template LLM agent

`scripts/pm_agent_llm.py` is a ready-to-run PM agent — Claude decides each action via tool-use, with
the tool set and system prompt derived from `data/actions.json`, so it tracks the catalog/scenario
automatically. It talks to the env over HTTP and maps each tool call to `env.step`; point-of-view
(hiding unsurfaced blockers) is enforced in the script, so discovery stays real.

```
# 1 · start the env with the NPC parser LIVE so novel agent messages classify, into a scratch
#     cassette (the committed one is never touched):
SAASWORLD_LLM_MODE=record SAASWORLD_CASSETTE=/tmp/agent_cassette.jsonl \
    ANTHROPIC_API_KEY=sk-... saasworld-env-serve

# 2 · run the agent (its brain also needs a key):
ANTHROPIC_API_KEY=sk-... python scripts/pm_agent_llm.py --scenario checkout-not-ready
#     -> writes runs/agent-<scenario>-<ts>/ ; open the inspector UI to replay it
```

No key handy? Two offline modes need none:

```
python scripts/pm_agent_llm.py --self-test     # fixed policy that solves the scenario — smoke the loop
python scripts/pm_agent_llm.py --print-tools   # inspect the derived tools + system prompt, no API call
```

See the [Agent SDK](docs/saas-world/agent-sdk.md) guide for the contract this script is built on and
[NPC replies & novel messages](docs/saas-world/npc-replies.md) for why the live parser + scratch
cassette are needed.

## Documentation

Subsystem guides live under [`docs/saas-world/`](docs/saas-world/):

- [Agent SDK](docs/saas-world/agent-sdk.md) — the OpenEnv-shaped contract, the action space, and
  driving an episode from agent code.
- [Operator CLI](docs/saas-world/cli.md) — the `saasworld` command: drive, inspect & replay
  trajectories, persistent HTTP session.
- [NPC replies & novel messages](docs/saas-world/npc-replies.md) — offline replay classification, the
  fail-closed bare-ack on novel messages, and the record → replay workflow.
- [Scenario authoring & generation](docs/saas-world/scenarios.md) — the build-time Seeding Engine
  (generate · validate · freeze) and hand-authoring.
- [Tests](docs/saas-world/tests.md) — running the suite and per-system markers.
- [Library APIs](docs/saas-world/library-api.md) — the evaluator and trajectory store used directly.

Design docs: `docs/problem-def.md` (brief), `docs/research/` (prior art + proposals),
`docs/implementation/` (per-wave specs).
