# Scenario authoring & generation

Only needed to add *new* cases to the dataset; the pre-built scenarios under `data/scenarios/` need
none of this. Build-time is offline, no service (the Seeding Engine):

```
saasworld generate <archetype> --seed N --out DIR   # template + seed -> candidate (sample->bind->assemble->project-eval)
saasworld validate DIR                              # the gate: coherence · solvable-floor · non-trivial-ceiling
saasworld freeze   DIR                              # content-hash + provenance -> immutable instance
```

- **generate** samples a template's slots into a candidate instance (the 5 files) under `--out`
  (default `data/candidates/`, gitignored & regenerable). Same `(archetype, seed)` is byte-identical.
- **validate** is the promotion filter: a candidate is freezable only if it passes all three
  sub-gates (a *competent* solver scores ~1.0, a *lazy* one ~0). Failing candidates are rejected,
  never frozen.
- **freeze** stamps the passing instance immutable. To add it to the committed dataset, place/freeze
  it under `data/scenarios/` and commit that — candidates and `runs/` stay ignored.

Hand-authoring (like `checkout-not-ready`, `"authored": "by-hand"`) writes the same 5 files directly.
The `scenario-author` agent (`.claude/agents/`) interviews you and drives this whole loop.

See `docs/implementation/06-wave5-seeding-engine-spec.md` for the engine internals and
`docs/research/04-seeding-engine.md` for the design rationale.
