# NPC replies & novel messages

By default the NPC parser runs **offline in replay mode**: it classifies each message body by looking
it up in a committed cassette (`tests/cassettes/default.jsonl`). The documented scenario bodies (the
ones in the [Agent SDK](agent-sdk.md) and [CLI](cli.md) walkthroughs) are recorded, so coworkers
reply for real, key-free.

## Novel messages fail closed

A **novel** free-text body the cassette doesn't cover (any agent that phrases things its own way)
can't be classified offline. The engine then **fails closed** — it bypasses the decision core so no
gated fact can leak on an unclassifiable message — and the coworker replies with a bare
acknowledgement (`"Ack."`). The sim stays live; this is by design, not an error.

It's logged **once per process** as a single `INFO` line (not a traceback); raise
`saasworld.npc.engine` to `WARNING` to silence it entirely. A genuinely unexpected error (e.g. a real
API failure in record mode) stays loud with a full traceback, so an expected replay miss can never
masquerade as a crash — and a real crash can never hide in the noise.

This fail-closed degradation is the anti-gaming guarantee, not a stopgap: there is deliberately **no
heuristic fallback classifier**, because guessing an intent from an unrecognized body could leak a
gated blocker the agent didn't earn.

## Recording real replies to novel messages

Record them against a live model once (needs a key only at record time), then replay against the
enriched cassette key-free:

```
# record: drive your agent against the env in record mode; novel messages append to the cassette
make record-cassette CASSETTE=/tmp/agent.jsonl           # needs ANTHROPIC_API_KEY
#   (or: SAASWORLD_LLM_MODE=record SAASWORLD_CASSETTE=/tmp/agent.jsonl saasworld-env-serve)

# replay: subsequent offline runs now classify those bodies for real
SAASWORLD_CASSETTE=/tmp/agent.jsonl saasworld-env-serve
```

The decision core owns every reveal/mutation (system-sourced); the parser can only *request* an
intent. So even a recorded reply can't fabricate a blocker — it can only trigger the core to disclose
one the scenario already gates on that intent.
