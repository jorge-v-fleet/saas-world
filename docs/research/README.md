# Research

Prior art + a starting architecture for the PM-first-week simulation (see `../problem-def.md`).

- `01-landscape.md` — how comparable environments are built, what to borrow, references.
- `02-architecture-proposal.md` — brief proposed design.
- `03-eval-example.md` — worked scoring example (two runs vs. ground truth) + parser injection resistance.
- `04-seeding-engine.md` — build-time engine that turns a template + seed into a frozen scenario (world + co-generated eval).
- `05-action-space.md` — how the agent changes the world (three clock classes) and how actions drive world evolution.
- `06-trajectory-store.md` — replay-grade rollout logging (JSONL canonical + derived index) + any-POV reconstruction for cross-trajectory observability.

Status: exploratory. Nothing here is committed to yet.
