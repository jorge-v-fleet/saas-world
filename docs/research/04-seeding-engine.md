# Build-time data seeding engine

Bridges the variability model (many scenarios, no code-per-scenario) with the dataset substrate (`data/`) and the eval contract (`03`).

**Core stance:** randomness is resolved at **build time** into frozen instances; **runtime stays deterministic and replayable** (per `02`). The engine never runs during a graded episode.

## What it produces

- **In:** base substrate + one archetype template + a seed.
- **Out:** a frozen scenario instance (`seed.json` · `personas.overlay.json` · `timeline.json` · `eval.json` + `scenario.json` manifest) that the kernel loads unchanged.
- **Key property:** the eval is **co-generated** from the same resolved parameters — never hand-written per instance, so world and grader cannot drift.

`scenarios/checkout-not-ready/` is a hand-authored instance shaped exactly as this engine emits. `templates/hidden-critical-blocker.json` is its template; `example_binding` there is the seed draw that reproduces it.

## Inputs

- **Base substrate** (`data/world/*`, `data/personas/*` base packs) — durable org + NPC identities. Read-only to the engine.
- **Archetype template** (`data/templates/<archetype>.json`) — `invariants` + typed `slots` (sampling domains + a small declarative inter-slot constraint set — ref equality/inequality/membership, resolved by rejection sampling; no Turing-complete DSL) + `eval_shapes`. All data.
- **Seed** (int) — the only source of variability.

## Pipeline (5 stages)

1. **Sample** — a seeded PRNG fills each slot from its domain under constraints. Deterministic: same `(template, seed, substrate)` → same draw.
2. **Bind** — resolve abstract slots to real substrate IDs (which `active` NPC holds the blocker, which agent-owned project is critical, who applies pressure). Only `active`-tier NPCs are eligible; chosen ones go into the manifest's `activate`.
3. **Assemble** — materialize concrete JSON: scenario `seed` (projects/tasks/blockers/surfaces), per-NPC `overlay` (goals + `knowledge_scope` + reveal gates), `timeline`.
4. **Project eval** — emit `eval.json` by binding each templated predicate **shape** to the resolved IDs / value-sets (mapping below). This is the coupling.
5. **Gate + freeze** — run the validity gate; on pass, write instance + manifest with content hash + provenance `(template, seed, substrate_hash, generator_version)`.

## Eval co-generation (the coupling)

The assembler holds a resolved fact-map; each eval predicate is a bound instance of a shape:

| Template shape | Bound with resolved facts → instance predicate |
|---|---|
| `discover(blocker)` | `blockers.<blocker_id>.surfaced == true` |
| `act_on(blocker)` | `<project>.launch_date changed` OR `decision[gonogo,<project>] exists` |
| `correct_action ∈ set` | set derived from `deadline.movable` (movable → {reschedule, hold_and_mitigate}; fixed → {hold_and_mitigate}) |
| `inform(stakeholder)` | `messages[?to==<stakeholder_id> && references==<blocker_id>]` |
| `comms(artifact)` | state-grounded extraction schema — each claim credited only if world state backs it (`03`) |

Weights come from the template; the projector validates they sum to 1.0.

## Determinism & reproducibility

- **Only seeded randomness.** No wall-clock / ambient RNG at generate time; every draw comes from the seeded PRNG.
- **Provenance pinned.** Manifest records `(template_id, generator_version, seed, substrate_hash)` + a content hash over emitted files. Re-running the engine reproduces byte-identical instances.
- **Runtime untouched.** The kernel consumes a frozen instance; `02`'s single-writer + one-queue determinism is unaffected.
- **Instances are immutable; substrate pinned.** A frozen instance pins its `substrate_hash`; a later base change never mutates it. Regeneration is an explicit opt-in that emits a *new* instance under the new substrate; a drift report lists instances lagging current substrate.

## Content addressing (dataset version)

The shared hashing primitive — used for instance provenance above and run pinning in `06`.

- **Canonicalize** each data file before hashing: sort keys, normalize whitespace, strip `_`-prefixed annotation fields (so doc-note edits never change a hash).
- **Hash** each canonical file with SHA-256; a subtree hash = SHA-256 over its sorted `(path, file_hash)` pairs.
- **`dataset_version`** = that hash applied to the whole dataset (substrate + all scenarios + action space); derived/disposable artifacts (e.g. the run index) are excluded.
- Deterministic and machine-independent — identical content → identical `dataset_version`, anywhere. Any change to substrate, a scenario, or the action space flips it; formatting and notes do not.

## Validity gate (keeps generated scenarios defensible)

- **Coherence** — invariants hold (exactly one blocker on the critical path; holder is `active`-tier; ≥1 action flips `surfaced`; no agent write path to `surfaced`).
- **Solvable-floor** — a reference "competent PM" solver reaches full score; else reject.
- **Non-trivial-ceiling** — a "busy/lazy" agent (messages only, no real deltas) scores ~0; else reject.
- **Reject → resample** with the next seed; **log every rejection** — never silently drop coverage.
- Reference solvers may be LLM agents, but only their **score** (a deterministic check) gates; generation itself is rule-based, so reproducibility holds.
- **Gate-verdict cache:** the verdict is a pure function of `(template_id, seed, substrate_hash, generator_version)`; cache it under that key so re-runs skip the solver.

## Where the LLM does / does not appear

- **Not** in sample / bind / assemble / project-eval — all deterministic code.
- **Optional at authoring time only:** drafting vocab or flavor text (persona voice lines, email bodies) offline, which then becomes static data. Never inside the generate→freeze path.
- **Runtime** LLM stays parser-only (`02`/`03`): intent classification + prose extraction, never decisions or scoring.

## Extensibility (all data, no engine change)

- **New archetype** = new template file (`invariants` + `slots` + `eval_shapes`).
- **New sampling vocab** (blocker flavors, pressure levels) = rows in a domain list.
- **New domain** (customers / financials / seasonality) = enable the module in `company.json`, add slot types + predicate shapes; `view_scope` filters and eval predicates pick up the namespaced IDs automatically.
- **Compose archetypes** later (hidden-blocker + missing-owner + conflicting-priorities) by merging slot sets under a combined invariant set.

## Suggested layout (when we build the code)

```
engine/            # future code — deterministic, no LLM in this path
  sample.*         # seeded PRNG + slot sampling
  bind.*           # slot -> substrate ID resolution
  assemble.*       # emit seed / overlay / timeline
  project.*        # emit eval from predicate shapes
  gate.*           # coherence + reference-solver checks
  freeze.*         # write instance + manifest + content hash
data/templates/    # archetype templates (data)
```

CLI verbs extend `02`'s operator surface: `generate <archetype> --seed N` · `validate <instance>` · `freeze <instance>`.

