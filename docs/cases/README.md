# Scenario cases (data only)

Narrative designs for **archetypes authored purely as template data** — one file per case, matching
a `data/templates/<archetype>.json`. These are *not* engine specs: authoring a case adds a template
and a frozen scenario, and changes **no `src/` code**. The engine is a generic interpreter of
template data (see `docs/implementation/09-archetype-release-triage-spec.md` for the one-time
generalization that made that true); every case here rides it for free.

Each case describes the world, the graded outcomes + weights, the anti-gaming mechanics
(denied paths, gated system effects), and the two reference solvers the validity gate runs. It ends
with the authoring constraints the generic engine expects, so the template stays data-only.

Flow per case: agree on the shape here → author `data/templates/<archetype>.json` (scenario-author
agent) → `generate` → `validate` (gate: coherence + competent 1.0 + lazy 0.0) → `freeze` → add an
integration test. `hidden-critical-blocker` seed 1206 must stay byte-identical throughout.

## Cases

- [`delivery-slip`](delivery-slip.md) — long-horizon delivery under an internal execution slip.
