# Scenario authoring & generation

Scenarios are **generated from templates at setup time**, not committed. The repo ships the templates
under `data/templates/` plus one hand-authored example (`checkout-not-ready`); every other instance is
a build artifact under `data/scenarios/` (gitignored) that you regenerate from `(template, seed)`.
Build-time is offline, no service (the Seeding Engine).

## Build the scenario sets (the normal path)

```
saasworld build-set <archetype> --count N [--start S] [--scan-limit L]
```

Walks seeds from `--start`, **skips any the gate rejects**, freezes the first `N` valid instances into
`data/scenarios/<archetype>-<seed>/`, and writes `data/sets/<archetype>.json` recording exactly which
seeds back the set (plus the rejects). Deterministic: same `(substrate, template, start)` → same seed
list, so a reviewer reproduces the identical set. If a seed already has an instance dir (e.g. the
hand-authored `checkout-not-ready`), it's reused by name, never duplicated.

## Single-instance verbs (authoring / debugging one case)

```
saasworld generate <archetype> --seed N --out DIR   # template + seed -> candidate (sample->bind->assemble->project-eval)
saasworld validate DIR                              # the gate: coherence · solvable-floor · non-trivial-ceiling
saasworld freeze   DIR                              # content-hash + provenance -> immutable instance
```

- **generate** samples a template's slots into a candidate instance (the 5 files) under `--out`
  (default `data/candidates/`, gitignored & regenerable). Same `(archetype, seed)` is byte-identical.
- **validate** is the promotion filter: a candidate is freezable only if it passes all three
  sub-gates (a *competent* solver scores ~1.0, a *lazy* one ~0). Failing candidates are rejected,
  never frozen. `build-set` runs this gate on every seed automatically.
- **freeze** stamps the passing instance immutable. Instances under `data/scenarios/` are gitignored
  build outputs — do not commit them; the `data/sets/` manifest + the deterministic build reproduce them.

Hand-authoring (like `checkout-not-ready`, `"authored": "by-hand"`) writes the same 5 files directly
and *is* committed as the reference example. The `scenario-author` agent (`.claude/agents/`) interviews
you and drives the template-authoring loop.

See `docs/implementation/06-wave5-seeding-engine-spec.md` for the engine internals and
`docs/research/04-seeding-engine.md` for the design rationale.
