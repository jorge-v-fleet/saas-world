# Wave 5 spec — Seeding Engine: templates + seeds → frozen instances (co-generated eval + validity gate)

Implementation spec for the **build-time** slice (`01-systems.md` system 6). Goal: **turn one archetype template + a seed into a frozen scenario instance whose `eval.json` is co-generated from the same resolved facts**, then gate it and freeze it with content hash + provenance — replacing hand-authoring as the scaling path. Deterministic, offline, **never runs during a graded episode**.

- **Stack:** Python 3.12+, on top of Waves 1–4. Reuses Wave 2's `content_hash` primitive and Wave 4's LLM record/replay cache (gate solvers only). **Single process, no Docker, build-time/offline.**
- **Emits exactly what Wave 2 loads:** `data/scenarios/<id>/` = `seed.json` · `personas.overlay.json` · `timeline.json` · `eval.json` + `scenario.json` manifest — consumed unchanged by the Scenario Loader.
- **Out of scope:** any runtime system (Kernel/Loader/NPC/Evaluator run *after* freeze, on the output); LLM in the generate path (the generate→freeze path is pure code); the Operator CLI front (Wave 7 surfaces these verbs — this wave ships the `engine/*` library + a thin offline entrypoint).

## The one property that shapes this wave

- **Randomness is resolved at build time into a frozen, immutable instance; runtime stays deterministic and replayable** (`02`/`04`). The engine is the *only* place a seed is drawn; once frozen, the instance pins its `substrate_hash` and never mutates.
- **Eval is co-generated, not authored.** The assembler holds a single resolved fact-map; `seed/overlay/timeline` **and** `eval.json` are both projected from it. World and grader are bound to the same facts, so they cannot drift per instance.

## Design rules carried from research

- **Only seeded randomness** (`04`): no wall-clock, no ambient RNG in the generate path. `(template_id, seed, substrate_hash, generator_version)` → **byte-identical** instance, anywhere.
- **No LLM in sample/bind/assemble/project-eval** (`04`): all four are deterministic code. The LLM appears **only** as a validity-gate reference solver, and only its deterministic *score* gates.
- **Substrate is read-only; instances are immutable** (`04`): the engine reads `data/world` · `data/personas` · `data/templates`; it writes only to `data/scenarios/<id>/`. A later base edit never mutates a frozen instance — regeneration is an explicit opt-in that emits a *new* instance.
- **Content-addressing is reused, not reinvented** (`03` builds it in Wave 2): `content_hash.canonicalize → sha256 → subtree → instance_hash / substrate_hash`. Wave 5 imports it.
- **Coupling is enforced, not trusted:** the projector reads the *same* resolved fact-map the assembler emitted; a shape can only bind to IDs that already exist in the assembled world. Weights are validated to sum to 1.0.
- **Never silently drop coverage** (`04`): a gate reject → resample with the next seed and **log the rejection** with its reason.

## Contracts (the shared shapes)

- **Template** (`data/templates/<archetype>.json`, all data): `invariants` + typed `slots` (sampling domains + declarative inter-slot constraints) + `eval_shapes` (weighted predicate shapes) + `time` + an illustrative `example_binding`.
  ```
  Slot        { name, sample:[…] | sample_from:<selector> | sample_int:[lo,hi], weights?:[…], constraint?:<expr> }
  EvalShape   { id, w:float, shape:<templated predicate>, reads_real_field?:bool }
  ```
- **Resolved draw** (sample output — the seed's whole footprint):
  ```
  Draw { <slot_name>: <primitive value>, ... }   # only literals/enums; no substrate IDs yet
  ```
- **Fact-map** (bind + assemble output — the single source both world and eval project from):
  ```
  FactMap { draw:Draw, ids:{<abstract_slot>: <substrate_id>}, world:{projects,tasks,blockers,surfaces}, activate:[id] }
  ```
- **Instance** (freeze output): the five files above, plus manifest provenance:
  ```
  scenario.json { id, archetype, activate:[id], time,
                  provenance:{ template_id, seed:int, substrate_hash, generator_version, instance_hash } }
  ```
- **Gate verdict** (pure function of the provenance key; cached):
  ```
  Verdict { pass:bool, coherence:bool, solvable_floor:bool, nontrivial_ceiling:bool, reason?:str }
  Key     = (template_id, seed, substrate_hash, generator_version)
  ```
- **Rejection log record** (append-only, never dropped):
  ```
  Reject { key:Key, stage:"coherence|solvable_floor|nontrivial_ceiling", reason:str, next_seed:int }
  ```

## System specs — the 5 pipeline stages

Each stage is a concrete pure function; the pipeline is their composition. Only `gate` may reach the (cached) LLM.

### 1. `sample(template, seed, substrate) -> Draw`  (`engine/sample.py`)
- **Seeded PRNG only:** a single `random.Random(derive(template_id, seed, substrate_hash, generator_version))` — the seed is mixed with the provenance key so the same seed under a different substrate/version draws differently, and drift is impossible.
- Fills each `slot` from its domain: `sample` (uniform/`weights`), `sample_int` (inclusive range). Enum + weight draws only — no IDs resolved here (IDs are `bind`'s job).
- **Inter-slot constraints by rejection sampling:** the small declarative set (ref equality/inequality/membership — e.g. `holder != agent`) is evaluated against the partial draw; on violation, re-draw the offending slot from the *same* PRNG stream (bounded attempts → raise `Unsatisfiable`, never loop forever). No Turing-complete DSL.
- **Guarantee:** `sample(t, seed, sub)` is a pure function of its args → identical `Draw` across machines/runs.

### 2. `bind(draw, template, substrate) -> {ids, activate}`  (`engine/bind.py`)
- Resolves each abstract slot to a **real substrate ID** via its `sample_from` selector against the base packs: `blocker.holder` → an `active`-tier NPC whose role ∈ the selector's set; `critical_project` → a project `owned_by agent`; `stakeholder` → an `active` NPC (cto/pm).
- **Eligibility rules (hard):** only `active`-tier NPCs are bindable; enforced constraints re-checked against real IDs (`holder != agent`, holder ∈ the required role set, distinct roles where the template demands). A selector with no eligible candidate → `Unsatisfiable` (bubbles to a resample).
- Chosen NPC IDs collect into `activate` (the manifest's active set). Selection among eligible candidates is itself a **seeded** draw from the same stream — deterministic, no ambient order dependence.

### 3. `assemble(draw, ids, template, substrate) -> FactMap`  (`engine/assemble.py`)
- Materializes the concrete world JSON from `draw`+`ids`:
  - `seed.json` — projects/tasks/blockers/surfaces (blocker `known_to: [holder]`, `surfaced: false`; critical path wired task→task→blocker; `distractor_blockers` as red herrings; deadline offsets from `draw`).
  - `personas.overlay.json` — per active NPC: `goals` + `knowledge_scope` (the gated fact keyed to the blocker, `reveal_when`/`reveal_gate` from `draw`) + escalation triggers; 2-hop discovery adds the pointer-holder overlay when `discovery.hops == 2`.
  - `timeline.json` — only scripted background events (stakeholder pressure cadence from `draw`); reactive replies/wake-ups are self-scheduled at runtime, never listed.
- Returns the **FactMap** — the resolved fact-map the projector will read. Assemble and project share this object; that shared read is the coupling.

### 4. `project_eval(factmap, template) -> eval.json`  (`engine/project.py`)
- Binds **each templated predicate shape** to concrete IDs/value-sets **from the FactMap** — never from a second source. The mapping (`04`):
  | Template shape | Bound predicate (resolved facts) |
  |---|---|
  | `blockers.<blocker>.surfaced == true` | `blockers.blocker.<id>.surfaced == true` (`reads_real_field`) |
  | `<critical_project>.launch_date changed OR decision[gonogo,<critical_project>]` | bound to the assembled `proj.<id>` |
  | `correct_action ∈ set` | set derived from `draw["deadline.movable"]` (movable → `{reschedule, hold_and_mitigate}`; fixed → `{hold_and_mitigate}`) |
  | `inform(<stakeholder>)` | `messages[?to==<stakeholder_id> && references==<blocker_id>]` |
  | `comms(artifact)` | state-grounded `extract_schema` — each claim credited only if world state backs it (`03`/Wave 4) |
- **Weights:** copied from `eval_shapes[].w`; the projector asserts they sum to **1.0** (exact, on canonicalized floats) → else raise `WeightsError`. Emits `checkpoints` + `artifact_predicates` shaped exactly as Wave 2's hand-authored `eval.json`.
- **Guarantee:** every emitted predicate references only IDs present in the assembled `world` — a shape cannot bind to a non-existent entity.

### 5. `gate(factmap, eval, key) + freeze(...)` (`engine/gate.py`, `engine/freeze.py`)
- **`gate` — validity gate** (verdict cached by `Key`; a cache hit skips the solvers entirely):
  - **Coherence** (pure, no solver): invariants hold — exactly one blocker on the critical path; holder is `active`-tier; ≥1 action sequence can flip `surfaced`; **no agent write path** to `surfaced`; schema well-formed; eval weights sum to 1.0.
  - **Solvable-floor:** a reference **"competent PM"** solver drives the (just-assembled) instance through the runtime loop and must reach **full score** → else reject `solvable_floor`.
  - **Non-trivial-ceiling:** a **"busy/lazy"** solver (messages only, no real deltas) must score **~0** (≤ ε) → else reject `nontrivial_ceiling`.
  - **Reject → resample:** on any failure, log a `Reject` record and retry `sample→…→gate` with `seed := next_seed(seed)` (bounded budget → raise `NoValidSeed` after N attempts). Every rejection is logged; coverage is never silently dropped.
- **Reference solvers:** rule-scripted PM actions, or **may be LLM agents** — but **only their deterministic score gates**. If a solver calls the LLM it uses the config-driven model (`config/settings.toml [llm].model`, default `claude-sonnet-5`) **through the Wave 4 record/replay cache** in replay mode → **no live calls in tests**; generation itself stays rule-based, so reproducibility holds. The solver's *transcript* is discarded; only the score (a deterministic predicate check) gates.
- **`freeze`** (only on `pass`): write the five files to `data/scenarios/<id>/`, compute `instance_hash` (Wave 2 `content_hash` over the canonical emitted files), and write `scenario.json` with provenance `(template_id, seed, substrate_hash, generator_version, instance_hash)`. Marks the instance immutable.
- **Guarantee:** re-running `generate → freeze` with the same `Key` reproduces byte-identical files and the same `instance_hash`.

### Determinism & content-addressing (reused)
- `substrate_hash` = `content_hash.subtree_hash(data/world + data/personas)` (Wave 2). `generator_version` = a pinned engine version string. Both enter the PRNG derivation *and* the provenance/gate-cache key.
- `instance_hash` = `content_hash.instance_hash(scenario_dir)` — canonicalize (sort keys, normalize whitespace, strip `_`-prefixed notes) → sha256 per file → subtree hash. Doc-note edits never change it.

## How it works (generate → freeze)

1. `generate hidden-critical-blocker --seed 7`: load template + read-only substrate; compute `substrate_hash`.
2. `sample` → `Draw` (blocker.type, gate, movable, hops, pressure…), constraints satisfied by rejection sampling.
3. `bind` → resolve `blocker.holder`/`critical_project`/`stakeholder` to real `active` IDs; collect `activate`; enforce `holder != agent`.
4. `assemble` → `FactMap` (+ `seed`/`overlay`/`timeline` JSON).
5. `project_eval` → `eval.json` from the FactMap; weights validated to 1.0.
6. `gate`: coherence → solvable-floor (competent-PM full score) → non-trivial-ceiling (lazy ≈ 0), verdict cached by `Key`. On reject: log, `seed := next_seed`, back to step 2.
7. `freeze`: write files + `scenario.json` with `instance_hash` + provenance. Done — the Scenario Loader (Wave 2) can now load it unchanged.

## CLI verbs (offline — extend the operator surface)

- `generate <archetype> --seed N [--out DIR]` — `sample→bind→assemble→project_eval`; writes a candidate instance (unfrozen). No running service, no episode.
- `validate <instance>` — run the validity gate (coherence · solvable-floor · non-trivial-ceiling) + schema + eval-weights-sum-to-1.0; report each verdict; non-zero exit on reject.
- `freeze <instance>` — content-hash + provenance, write manifest, mark immutable; report `instance_hash`.
- These delegate straight to `engine/*`; Wave 7 surfaces them on `saasworld …`. Build-time only — they never construct a Kernel or touch a graded run.

## Testing strategy

Each stage has an isolated suite (own marker) plus a golden integration proof. Stages are pure functions → each is unit-testable without its neighbors; the gate injects the Wave 4 `LLMClientProto` fake / replay cassette so no live call ever fires.

- **Property — `-m property`** (`tests/property/`, hypothesis): **sampler determinism** — for random `(seed)` over a fixed `(template, substrate)`, two `sample` calls → **identical `Draw`**; all inter-slot constraints hold on every accepted draw (`holder != agent`, role-set membership, distinct-role); a change to `seed` *or* `substrate_hash` *or* `generator_version` re-derives a different stream (no cross-key collision).
- **Unit — `-m seeding`** (`tests/seeding/`): bind/assemble/project units —
  - `bind`: only `active`-tier NPCs eligible; selectors resolve to real IDs; `holder != agent`; empty candidate set → `Unsatisfiable`.
  - `assemble`: FactMap wires the critical path (task→task→blocker), `surfaced:false`, `known_to:[holder]`; 2-hop adds the pointer overlay; distractors emitted; timeline holds only scripted events.
  - `project_eval`: **eval weights sum to 1.0** (else `WeightsError`); **each templated shape binds to the resolved IDs** in the FactMap; `correct_action` set derives from `deadline.movable`; no predicate references a non-existent entity.
- **Gate — `-m seeding`** (`tests/seeding/gate/`): coherence **rejects malformed** (two blockers on the path; holder not `active`; an agent write path to `surfaced`; weights ≠ 1.0); **solvable-floor** passes only when the competent-PM solver hits full score, **non-trivial-ceiling** passes only when the lazy solver ≈ 0 (both drive a fake/replay solver — deterministic scores, no live LLM); **reject → resample** advances to `next_seed` and **writes a `Reject` log record** (assert the log, assert coverage not dropped); **verdict cache** keyed by `Key` → a second call skips the solver (assert solver invoked once).
- **Golden — `-m golden`** (`tests/golden/`): **the flagship correctness test.** `generate` from `data/templates/hidden-critical-blocker.json` with the seed that reproduces `example_binding` → the five emitted files are **byte-identical** to the hand-authored `data/scenarios/checkout-not-ready/` (after canonicalization of `_`-note fields), and `instance_hash` matches. A companion assertion pins that this seed's `sample→bind` yields exactly the template's `example_binding` draw. Regenerate with `pytest --update-golden`.
  - *Seed pinning:* the seed that resolves to `example_binding` is discovered once and recorded (in the template's `example_binding._seed` / the golden fixture); the golden runs the *full* pipeline from it, so the test proves the engine emits the authored instance from a plain `(template, seed)`.
- **Validation — `-m validation`** (`tests/validation/`): every template in `data/templates/` is well-formed — `invariants`/`slots`/`eval_shapes` present, `eval_shapes[].w` sum to 1.0, `sample_from` selectors reference resolvable role/tier sets, `example_binding` satisfies the declared constraints.
- **Markers:** reuse the `-m` convention; add **`seeding`** to `pyproject.toml [tool.pytest.ini_options].markers` alongside Wave 1's (`kernel/state/toolapi/integration/golden/property/validation`) and Wave 4's (`npc_parser/extractor/llm`). `property`/`golden`/`validation` are reused as-is.

## How to run

```
# setup (no Docker, no services; deps already include anthropic from Wave 4)
uv venv && source .venv/bin/activate
uv pip install -e ".[dev]"

# all tests — fully offline (replay cassette + fakes), no API key
pytest

# a single stage, in isolation
pytest -m property            # sampler determinism + constraints
pytest -m seeding             # bind / assemble / project-eval + gate units
pytest -m golden              # reproduce checkout-not-ready byte-identically (flagship)
pytest -m validation          # templates well-formed

# generate → validate → freeze, offline (no running service)
python -m saasworld.engine generate hidden-critical-blocker --seed 7 --out /tmp/cand
python -m saasworld.engine validate /tmp/cand
python -m saasworld.engine freeze   /tmp/cand      # writes scenario.json + instance_hash

# refresh the gate's solver cassette against the live API (opt-in; needs a key)
export ANTHROPIC_API_KEY=sk-ant-...
pytest -m seeding --record

# lint + types
ruff check . && mypy src
```

## Single service vs Docker (the answer)

- **Single process, no Docker, build-time/offline.** The Seeding Engine is a library + a thin offline entrypoint — it runs to completion and exits, writing files. No server, broker, or DB; no port bound.
- **No new runtime dependency.** It reuses Wave 2's `content_hash` and Wave 4's `anthropic`/cassette layer; the gate's solvers run in **replay** mode against a committed cassette, so the default suite is fully offline and key-free (asserted). The API key is read only under `--record`.
- **Never runs during a graded episode.** Output is frozen, immutable data the runtime consumes unchanged; the build-time↔runtime boundary is a hard line (`04`).
- **Docker remains optional, later** — one Dockerfile for reviewer reproducibility if wanted; never `compose` (nothing to orchestrate).

## Project layout (additions)

```
pyproject.toml            # + marker: seeding  (property/golden/validation reused)
src/saasworld/
  engine/
    __init__.py           # pipeline composition: sample→bind→assemble→project→gate→freeze
    sample.py             # seeded PRNG + slot sampling + rejection-sampled constraints
    bind.py               # abstract slot -> real active-tier substrate ID resolution
    assemble.py           # emit FactMap: seed / overlay / timeline
    project.py            # project_eval: predicate shapes -> eval.json (weights == 1.0)
    gate.py               # coherence + reference-solver score gates + reject/resample + verdict cache
    freeze.py             # write instance + scenario.json manifest (content_hash + provenance)
    solvers.py            # competent-PM + busy/lazy reference solvers (score-only; replay-cached LLM)
    __main__.py           # offline entrypoint: generate / validate / freeze
  content_hash.py         # (Wave 2) reused: canonicalize + sha256 + subtree + instance_hash
tests/
  seeding/                # bind / assemble / project units + gate/ subdir
  property/ golden/ validation/    # sampler determinism / flagship byte-identity / template lint
  conftest.py             # fixtures: substrate loader, template loader, FakeLLM/replay solver, seed-pin
```

## Definition of done (Wave 5)

- `generate hidden-critical-blocker --seed N` runs the pure `sample→bind→assemble→project_eval` pipeline and writes a candidate instance offline.
- **`eval.json` is co-generated** from the same FactMap as the world; weights validated to sum to 1.0; every predicate binds to a resolved ID.
- **Validity gate** rejects malformed (coherence), enforces solvable-floor (competent-PM full score) + non-trivial-ceiling (lazy ≈ 0), and on reject **resamples with the next seed and logs the rejection**; verdicts cached by `(template_id, seed, substrate_hash, generator_version)`.
- Reference solvers gate on **score only**; any LLM use goes through the Wave 4 replay cassette → **the default suite makes zero live calls, needs no key**.
- **Golden byte-identity passes:** the recorded `example_binding` seed reproduces `data/scenarios/checkout-not-ready/` exactly, `instance_hash` matches — the flagship proof the engine emits what was hand-authored.
- `freeze` writes `scenario.json` with `instance_hash` + full provenance; re-running the same `Key` is byte-identical (determinism).
- New marker (`seeding`) green; `property`/`golden`/`validation` green; prior waves' markers still green; `ruff` + `mypy` clean; **How to run** works from a clean checkout with only a venv (no key) except `--record`.

## Milestones

1. `engine/sample.py` (seeded PRNG + rejection-sampled constraints) → `-m property` green: determinism + constraints hold.
2. `engine/bind.py` + `engine/assemble.py` (active-tier resolution + FactMap) → `-m seeding` bind/assemble units green.
3. `engine/project.py` (predicate-shape projection + weights == 1.0) → `-m seeding` project units green.
4. `engine/gate.py` + `engine/solvers.py` (coherence + solver score gates + reject/resample + verdict cache, solvers on the replay cassette) → `-m seeding` gate units green.
5. `engine/freeze.py` + `engine/__main__.py` (write + provenance + CLI verbs) + the `example_binding` seed pin → `-m golden` byte-identical to `checkout-not-ready`; **DoD met**.
```

## As built (deltas from spec)

Real divergences from the spec above; everything else landed as written.

- **Data-driven assembler/projector (substitution blueprints).** The template carries authored `world` / `blockers` / `timeline` blueprints and enriched `eval_shapes`, with `$name` (whole-value) / `${name}` (in-string) tokens resolved against the FactMap bindings. `assemble` and `project_eval` are pure substitution over those blueprints — the leanest path to byte-identity and genuinely data-driven scenario authoring. `eval_shapes` *is* the predicate list projected into `eval.json` (weights copied from it); the illustrative-only `shape` string was dropped so no extra key leaks into the emitted grader.
- **Critical-blocker id is archetype-stable (`blocker.psp_cert`) across all `blocker.type` flavors.** The Wave 4 Evaluator's `decision_comms` grounding path is hardcoded (`eval/predicates.py: _BLOCKER_SURFACED = "blockers.blocker.psp_cert.surfaced"`), and this wave must not modify runtime code. So the structural id is stable and `blocker.type` varies only the flavor prose/label/fact. A generic `blockers._default` block keeps every non-`pci_cert` draw coherent and full-scoring, so the gate accepts the whole type space (no coverage lost).
- **Golden scope.** Byte-identity (after `content_hash` canonicalization) holds for the four content files — `seed` / `personas.overlay` / `timeline` / `eval` — and `instance_hash` matches the hand-authored `checkout-not-ready` (`sha256:1991bbdb…`). `scenario.json` is generated fresh (provenance + `dataset_version` + `frozen`) with id `"<archetype>-<seed>"`, so it is intentionally *not* byte-identical to the hand-authored manifest (which carries a human id + `authored: by-hand`). Pinned golden seed: **1206**, recorded in `example_binding._seed`.
- **Reference solvers are rule-scripted at the Kernel/event level** (system-sourced reveal = the exact delta an NPC reveal produces), so the gate is deterministic and robust for arbitrary seeds with zero LLM. The competent solver *optionally* drives discovery through the NPC engine's parser in replay mode; a gate test (`tests/seeding/gate/test_solver_replay.py`) exercises that seam against the committed `tests/cassettes/seeding.jsonl`, proving the solver's LLM path is replay-only (full score, key unset, unseen request → `CacheMiss`, never a live call). The solver's trajectory sink records the deltas the Kernel actually *applied* (handler events keep their effect off the event payload) so projection-based scoring sees NPC reveals.
- **Frozen-seam split.** `generate(archetype, seed, out_dir)` runs the pure pipeline and writes an unfrozen candidate (input seed, no gate); `validate(instance_dir)` re-derives the FactMap from the manifest provenance and runs the gate; `freeze` stamps `instance_hash` + `dataset_version`, marks the dir read-only. Reject→resample+log lives in `gate.find_valid_seed` (bounded → `NoValidSeed`), tested directly rather than wired into the fixed `generate` signature.
- **Determinism details.** `substrate_hash = sha256(subtree_hash(data/world) ++ subtree_hash(data/personas))`; `generator_version = "seed-engine/1"`. `bind` draws from a bind-salted stream (`archetype + ":bind"`) rather than literally continuing `sample`'s stream — same determinism and key-sensitivity, cleaner decoupling. The 2-hop pointer NPC is the active, persona-backed NPC reporting to the agent.
