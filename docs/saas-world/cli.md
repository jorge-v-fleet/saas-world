# Operator CLI

The `saasworld` CLI drives the same systems as the [Agent SDK](agent-sdk.md), one shell command at a
time. Handy for manual exploration, scripting, and inspecting persisted trajectories.

`saasworld --help` lists every verb. Add `--json` to any command for a machine-readable envelope;
exit codes: `0` ok · `1` runtime · `2` usage · `3` integrity (gate reject / `dataset_version`
mismatch / replay divergence).

## Drive

Embedded backend, one-shot per command (state checkpointed between calls):

```
saasworld load    <instance>                        # seed world, register NPCs, open a run; prints RUN_ID
saasworld step    --run RUN_ID --verb <verb> --args '<json>'
saasworld advance --run RUN_ID --by <minutes>       # release the clock; drains NPC replies + timeline
saasworld observe --run RUN_ID --path <state.path>
saasworld run-eval --run RUN_ID                     # weighted breakdown
```

A full worked loop — load, discover the hidden blocker with a **free-text** message (the LLM parser
classifies it offline from the cassette; the coworker reveals the blocker, system-sourced), take the
PM call, and score:

```
saasworld load data/scenarios/checkout-not-ready    # prints RUN_ID = checkout-not-ready.baseline.0
saasworld step    --run RUN_ID --verb send_message \
                  --args '{"to":"org.be_b2","body":"Is the PSP ready for Friday?","refs":["task.psp_integration"]}'
saasworld advance --run RUN_ID --by 120                                    # NPC reply fires; blocker surfaces
saasworld observe --run RUN_ID --path blockers.blocker.psp_cert.surfaced   # -> true (discovered)
saasworld step    --run RUN_ID --verb record_decision \
                  --args '{"about":"proj.checkout","type":"gonogo","action":"reschedule","new_date":"D8T17:00","owner":"org.be_b2"}'
saasworld advance --run RUN_ID --by 600
saasworld run-eval --run RUN_ID                     # -> final ≈ 0.86  (discovered + acted + correct call)
```

## Inspect & replay

The persisted trajectory:

```
saasworld traj ls
saasworld traj show   RUN_ID
saasworld traj replay RUN_ID                        # byte-exact reconstruction, zero model calls
saasworld traj pov    RUN_ID --actor grader --at 480  # the fact-view each predicate read
saasworld traj query  --reward-hack                 # high activity, ~0 real outcomes
```

## Persistent session

For state living in one process across commands, start the raw JSON-RPC Tool API and pass
`--backend http`. The standalone `saasworld-serve` entrypoint is **deprecated** (the OpenEnv server
is the single service now), so start the RPC app explicitly when you need this transport:

```
python -c "import uvicorn; from saasworld.api.app import create_app; \
  uvicorn.run(create_app(), host='127.0.0.1', port=8080)"   # JSON-RPC on 127.0.0.1:8080
saasworld load data/scenarios/checkout-not-ready --backend http
```
