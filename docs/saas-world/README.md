# saas-world guide

How to work with the system, one subsystem per file. Start at the repo [`README.md`](../../README.md)
for what saas-world is and a quick-start episode.

- [Agent SDK](agent-sdk.md) — the OpenEnv-shaped client/server contract, the action space, and how to
  drive an episode from agent code. **Start here.**
- [Operator CLI](cli.md) — the `saasworld` command: load / step / advance / observe / run-eval,
  trajectory inspection & replay, and the persistent HTTP session.
- [NPC replies & novel messages](npc-replies.md) — offline replay classification, the fail-closed
  bare-ack on novel messages (the anti-gaming guarantee), and the record → replay workflow.
- [Scenario authoring & generation](scenarios.md) — the build-time Seeding Engine
  (generate · validate · freeze) and hand-authoring.
- [Tests](tests.md) — running the suite and per-system markers.
- [Library APIs](library-api.md) — the evaluator and trajectory store used directly, no CLI/HTTP.

Design docs live alongside: `../problem-def.md` (brief), `../research/` (prior art + proposals),
`../implementation/` (per-wave specs).
