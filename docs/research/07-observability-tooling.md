# Observability tooling — what to adopt, what to build

Landscape scan for the trajectory store (`06`): can an existing tool give us readable, debuggable, multi-POV trajectory observability without violating our constraints — **single process, offline, no Docker, no server, embedded/file-based deps only** — and if not, what's the lightest thing to build. This is the tooling companion to `06`'s design.

## Verdict (up front)

- **No off-the-shelf tool fits as our store.** Every hosted-style observability platform (Langfuse, Phoenix, LangSmith, Weave, Braintrust) is a **running service with a DB backend** — the exact infra our brief forbids. They also don't model our two differentiators: **on-demand POV projection** and **replay-grade record→replay with zero model calls**.
- **Adopt, don't host:** borrow **Inspect AI's** viewer *pattern* (static, bundle-to-HTML, transcript event model), align our envelope to **OTel GenAI semantic conventions** for vocabulary, and get the cross-run analysis UI **for free from the DuckDB UI extension** we already depend on.
- **Build one small thing:** a local trajectory viewer with a **POV toggle**, **causal-chain navigation**, and **state-diff-over-time** — because no tool does POV projection. Keep it a static bundle + a TUI, never a service.

## Tool landscape (scored against our constraints)

| Tool | Runs offline / no server | Storage model | Record→replay | Multi-POV of one episode | Cross-run diff | Fit |
|---|---|---|---|---|---|---|
| **Inspect AI** (UK AISI) | ✅ `inspect view`; `inspect view bundle` → static site, no server | `.eval` log files on disk/S3 | partial (re-run, not byte-replay) | ❌ single transcript | ✅ epochs/samples compared | **Borrow the viewer pattern** |
| **Arize Phoenix** | ⚠️ local but a **server** (UI :6006 + OTLP :4317) | SQLite (trial; loses data on restart) / Postgres (prod) | ❌ | ❌ | ✅ | Borrow **OpenInference span schema** only |
| **Langfuse** (self-host) | ❌ **6 services** (Postgres+ClickHouse+Redis+MinIO+web+worker) | ClickHouse OLAP + Postgres | ❌ | ❌ | ✅ | Rejected — infra violates brief |
| **LangSmith / Weave / Braintrust** | ❌ cloud-first (self-host = enterprise/heavy) | vendor DB | ❌ | ❌ | ✅ | Rejected — hosted |
| **Traceloop / OpenLLMetry** | ⚠️ OTel SDK → needs a collector/backend | OTel spans | ❌ | ❌ | via backend | Borrow **gen_ai.* attribute names** |
| **Perfetto / Chrome Trace** | ✅ `ui.perfetto.dev` runs client-side; self-hostable | JSON trace-event array | ❌ | ❌ | ❌ | **Export target** for the timeline lens |
| **DuckDB UI** (MotherDuck ext) | ✅ fully local, `localhost:4213`, data never leaves | our `index.duckdb` | n/a | n/a | ✅ SQL notebook + column stats | **Adopt as-is** for cross-run |

Takeaways:
- The **eval-native** tools (Inspect AI) are far closer to us than the **ops-native** platforms (Langfuse/Phoenix/LangSmith) — they think in *samples/transcripts/scores*, not *production spans/latency dashboards*.
- Everything mature enough to be useful is a **server with a database**. Our JSONL-canonical + disposable-DuckDB-index stance is deliberately lighter and is the right call; the cost is we own the viewer.

## What to borrow (schema & UX), not host

- **Inspect AI viewer pattern** — the single most transferable idea:
  - `inspect view bundle` packages logs + viewer into a **self-contained static directory** servable from any static host (or opened locally). No daemon. This is exactly our "lightweight UI, no web app" target — mirror it: `traj bundle <run_id>` → static HTML reading the JSONL.
  - Its **transcript event model** (user/assistant msg, tool call, tool result, score, log entry, metadata) maps almost 1:1 onto our `kind` field. Reuse the taxonomy so our records read like a familiar transcript.
  - Live sample list + incremental metrics + per-sample tabs (messages · scoring · metadata) = a proven layout to copy for `traj show`.
- **OpenInference span schema (Phoenix)** — for the *shape* of an LLM/tool/retrieval step (input, output, tokens, tool name/args). Borrow field names so a record is legible to anyone who's seen OpenInference.
- **DuckDB UI extension** — we already ship `index.duckdb`; `duckdb -ui` opens a local SQL notebook (catalog browse, column distributions, null %) at `localhost:4213`, data stays local. This **is** our cross-run analysis GUI (regression / failure-cluster / reward-hack queries) with zero code — document it as the "power user" surface behind `traj query`.

## Standard to align the envelope to

Align **vocabulary**, not transport — stay JSONL, borrow names so we're interoperable and legible without lock-in.

- **OTel GenAI semantic conventions** (`gen_ai.*`, SIG-maintained, ~v1.41, actively adding **agent/task/tool/memory** span types) — the emerging lingua franca. Map our fields:
  - our `actor` → `gen_ai.agent.*` / operation source
  - our `kind` → the span/operation type (`gen_ai.tool.call`, agent step, etc.)
  - our `payload` LLM sub-fields → `gen_ai.request.*` / `gen_ai.response.*`
  - Caveat: the spec **moves fast** — pin a version, treat it as a naming guide for `payload` keys, don't couple our record structure to it.
- **Event-sourcing correlation/causation** — our `caused_by` **is** the *causation id* (immediate predecessor). Standard practice pairs it with a **correlation id** (first event of the causal saga) so tooling can show both "what directly caused this" *and* "the whole conversation this belongs to."
  - **Concrete extension:** add optional `corr:int` (root seq of the chain) alongside `caused_by`. `caused_by` → causal DAG edges; `corr` → one-click "show this entire interaction thread." Cheap to emit, unlocks both causal views.
- **Chrome Trace Event format** — a JSON array of `{ts, ph, name, cat, args, pid/tid}`. Not our source of truth (legacy, best-effort), but a trivial **export lens**: project the log to trace-events, open in Perfetto for a scrubbing timeline — free, local, zero UI code for the "when did things happen" question.

## The one thing to build — a local trajectory viewer

Because no tool does **POV projection**, this is ours. Keep it to thin surfaces over the store's existing `replay`/`project`/`query` APIs — no new authority.

**Where the work actually is — build the projection layer, then skin it.** The effort is *not* TUI-vs-HTML; it's the shared, pure logic underneath both: **POV projection · causal-chain walking · state-diff-over-time** (all pure functions of the log — `project`/`replay`/`state_at` from `06`). TUI and HTML are *skins* over that layer, not a fork. HTML can render richer (real timelines, side-by-side diffs, causal DAG, activity/outcome scatter are cheaper in SVG/CSS than terminal layout), but the render medium is the last 20%.

**Sequencing (decided):** *(superseded 2026-07-03 — see "Plan — carry into the live UI" below. We built the live HTML inspector on the OpenEnv server, so the Phase-2b "opt-in live HTML" is now the primary surface; the TUI-first path is not being pursued.)*
- **Phase 1 — `traj` TUI first.** Fastest path to something *usable*: build the projection layer + a thin Textual/Rich skin. Proves the POV/causal/diff logic end-to-end in the terminal, stays strictly CLI-only.
- **Phase 2 — static HTML bundle** (Inspect's `view bundle` model): the HTML reads the JSONL directly and consumes the **same projection layer** — richer visuals, still **no server**, keeps the offline stance. This is the lightest "prettier UI" and requires no rework.
- **Phase 2b (optional) — live HTML via existing `serve`.** Read-only HTML routes over the store's pure read APIs, served by the Wave 1 `serve` we already run. Cheapest *live* view, but reintroduces a running service for observability — opt-in only (like `--backend http`), defensible precisely because the reads are pure. Not the default.

- **A) `traj` TUI (Phase 1, primary — `06`/Wave 7 CLI + Textual/Rich)** — the reviewer's default:
  - **Timeline pane** — records by `seq`/`sim_time`; color by `actor`; glyph by `kind`. Scrub to any point.
  - **POV toggle** — the headline feature: cycle `agent | npc:<id> | operator | grader`; the timeline re-projects through that `view_scope` live (calls `project(run_id, actor, at)`). Same episode, four lenses, instantly.
  - **Causal navigation** — jump `caused_by` ↑ (why did this happen) and follow effects ↓; `corr` shows the whole thread. Renders the "NPC reply ← agent message" chain explicitly.
  - **State-diff-over-time** — at any `seq`, show the applied `delta` and cumulative state vs. the last snapshot (the "what actually changed" panel — directly exposes real-delta count).
  - **Score-decomposition panel** — grader POV: per-checkpoint predicate results, the fields each predicate read, weighted derivation. This *is* the "why did it score X" explanation the brief demands.
- **B) `traj bundle` static HTML (Phase 2, Inspect-style)** — one self-contained file/dir per run for sharing/archiving; reads the JSONL, no server; consumes the same projection layer as the TUI. Same panes, read-only, richer visuals.
- **C) Cross-run** — lean on **DuckDB UI** (`index.duckdb`) for interactive regression/failure-cluster/reward-hack exploration; `traj query` presets stay the scriptable path. A tiny **"activity vs outcome" scatter** (x=`n_messages`, y=`n_real_deltas`, color=`total`) makes reward-hacks pop visually — the busy-but-ineffective cluster sits bottom-right (high messages, ~0 deltas, low score).

## Cohort / statistics view — variability across trajectories (multiplets)

Single-run POV answers *"what happened this episode."* Running over **multiplets** (same instance, many seeds; and across `agent_version`) demands a second surface: *"how does the agent behave across the distribution, and is a change real or noise."* All aggregates are cheap — DuckDB computes them over the existing `index.duckdb` (one row/run); **only the render is new, no new store.**

- **Separate the two variance sources** (or noise reads as signal):
  - **seed variance** — fixed `agent_version`, many seeds → intrinsic stochasticity / flakiness.
  - **version effect** — vary `agent_version` at fixed instance → real gain/regression, trustworthy **only once it clears seed variance**.
- **Measure variability of two things:**
  - **outcome variance** — spread of `total` and per-checkpoint pass.
  - **behavioral variance** — do runs take different *paths* to the same score (action-sequence divergence)? Catches "same score, different route" and distinct reward-hack routes.
- **Views** (each = one DuckDB aggregate):
  - **Score distribution** — box/violin of `total` per `agent_version` (spread, not just mean) + mean ± bootstrap CI.
  - **Regression with error bars** — `total` vs `agent_version`, mean ± CI, seeds jittered → a gain is credible **only when CIs separate** (guards against seed-noise false wins).
  - **Checkpoint funnel + run×checkpoint heatmap** — funnel discover→act_on→correct→inform (drop-off = where runs diverge); pass/fail matrix makes `failure_clusters` visible at a glance.
  - **Flakiness / stability** — `stddev`/`pass^k` across seeds at fixed (instance, version); high variance flags non-determinism or brittle policy.
  - **Population activity-vs-outcome** — the reward-hack scatter with **all** runs as density; systemic gaming shows as a *zone/cluster*, not an anecdote.
- **Stats rigor (defensible grading, per brief):** report mean **with CI/stderr**, never bare means; size seed count so CIs are tight enough to claim a delta; keep the comparability key exact `(instance_hash, action_space_version)` so a `dataset_version` edit can't merge cohorts.
- **Surface:** `traj stats --instance-hash H [--by agent_version]` → cohort dashboard (TUI table first; HTML small-multiples in Phase 2). Makes the three named analyses (`06`: regression / failure-clusters / reward-hack) **distributional** instead of single-number.

## Reward-hacking as an observability surface (prior art)

- The concern is recognized and **post-hoc / trace-based**: analyze existing trajectories for *specification gaming* and *activity without outcome* rather than trusting the score alone (rubric-RL reward-hacking studies; intervention-driven multi-agent debuggers like DoVer; async-env benchmarks like Gaia2).
- Our built-in signal (`06`): high `#messages` + `#real_deltas ≈ 0` + low `total`. Make it **visible**, not just queryable — the scatter above + a `traj query --reward-hack` preset. Outcome-vs-activity as a first-class view is the defensible, hard-to-game story the brief wants.

## Plan — carry into the live UI (decided 2026-07-03)

**Surface decision** (supersedes the TUI-first sequencing above): the **live HTML inspector on the OpenEnv server** (`/inspector`, the single process we already run; all reads are pure) is the primary observability surface — the doc's Phase-2b "opt-in live HTML" became the default. The `traj` TUI and static `traj bundle` are **not pursued now**. **DuckDB UI** stays the power-user cross-run surface, adopted as-is.

Add three tools to a left-nav shell, beside the existing **Inspector** (raw per-run navigation: Trajectory / Score / Conversation). Each reuses existing backend logic — **no new store**.

1. **Grader's fact-view (POV)** — the "why did it score X" lens.
   - Per-checkpoint predicate results + the exact state fields each predicate read + weighted derivation. Folds 07's *POV projection [grader lens]* + *score-decomposition panel*; makes grading inspectable (brief).
   - Scope: **grader POV only** — not the full `agent | npc | operator | grader` toggle.
   - Backend: `eval/project.py` + the predicate `reason`s already in `score.json`; a thin endpoint enriching the Score view. Low prerequisite.

2. **Replay timeline** — "what happened, when, and what changed."
   - Events by `seq`/`sim_time` (color by actor, glyph by kind), scrub to any point; at each step the applied `delta` + cumulative state vs. last snapshot; causal navigation `caused_by ↑ / effects ↓`. Folds 07's *timeline pane · causal nav · state-diff-over-time*.
   - **Prerequisite P1:** needs the canonical event log (`delta`, `caused_by`, snapshots), which today only cli/run-eval runs persist — the two generators write the action-stream only. Decide: **(a)** extend the shared writer (`trajectory/actionlog`) so agent/random runs also emit the canonical log + periodic snapshots (the env already taps `(event, delta)`; `WorldState.snapshot()` exists), or **(b)** scope the timeline to canonical runs. **Recommend (a).**
   - **Optional P2** (07 envelope extension): add `corr` (root seq of a causal chain) beside `caused_by` → one-click "show the whole interaction thread."
   - Optional export lens: project to Chrome-trace JSON → open in Perfetto (free scrubbing timeline, zero UI code).
   - Backend: `trajectory/replay.py` (`state_at`/`replay`) + snapshots.

3. **Distribution (cohort stats)** — "how does it behave across the distribution, and is a change real or noise."
   - Over a cohort (a folder like `rollouts/`, or by `agent_version`): score distribution (box/violin + mean ± bootstrap CI), regression with error bars (a gain is credible only when CIs separate), checkpoint funnel + run×checkpoint heatmap, flakiness/stability across seeds, and the population **activity-vs-outcome reward-hack scatter** (x=`n_messages`, y=`n_real_deltas`, color=`total`). Folds the entire 07 *cohort/statistics* section + *reward-hack surface*.
   - Backend: `rollouts-summary.json` for the rollouts cohort (already emitted, cheap) + the DuckDB `trajectory/index.py` for cross-version regression / failure-cluster / reward-hack aggregates. Keep the exact comparability key `(instance_hash, action_space_version)`.

**Carried over as guidance (not new UI build):**
- **DuckDB UI** (`index.duckdb`) — power-user cross-run SQL surface, documented behind `traj query`.
- **Vocabulary** — keep `kind`/`payload` keys aligned to OTel `gen_ai.*` / OpenInference names.
- **Inspect AI transcript taxonomy** — already mirrored by the Conversation view.

**Explicitly deferred** (from the earlier catalog, out of this cut): Validation/health panel; Regression and Failure-clustering as *standalone* tools (they live inside Distribution for now); Reward-hack as a *standalone* monitor (folded into Distribution's scatter); Scenario/reference browser; multi-POV toggle beyond grader; `traj` TUI; static `traj bundle`.

**Implementation order (after approval, one subagent each):** scaffold the left-nav shell → **P1** (canonical log + snapshots for the generators) → **Replay timeline** → **Grader fact-view** → **Distribution**.

## Bottom line

1. **Keep our store** — JSONL canonical + disposable DuckDB index is lighter than every real tool and uniquely supports replay + POV.
2. **Borrow:** Inspect AI's bundle-to-static viewer pattern + transcript taxonomy; OpenInference/OTel `gen_ai.*` names for `payload`; DuckDB UI for cross-run GUI.
3. **Extend the envelope:** add `corr` (correlation id) beside `caused_by`; keep `kind`/`payload` keys OTel-aligned.
4. **Build small:** a `traj` TUI with POV toggle + causal nav + state-diff + score-decomposition, and a `traj bundle` static export. No server, no Docker — consistent with `06`/Wave 7.

## Sources

- Inspect AI — [log viewer](https://inspect.aisi.org.uk/log-viewer.html) · [reference](https://inspect.aisi.org.uk/reference/inspect_ai.html)
- Arize Phoenix — [site](https://arize.com/phoenix/) · [repo](https://github.com/arize-ai/phoenix) · [docs](https://arize.com/docs/phoenix)
- Langfuse self-host — [docs](https://langfuse.com/self-hosting) · [repo](https://github.com/langfuse/langfuse)
- OTel GenAI semantic conventions — [MLflow summary](https://mlflow.org/docs/latest/genai/tracing/opentelemetry/genai-semconv/) · [agentic conventions issue](https://github.com/open-telemetry/semantic-conventions-genai/issues/35) · [Greptime overview](https://greptime.com/blogs/2026-05-09-opentelemetry-genai-semantic-conventions)
- OpenInference / Phoenix agent tracing — [Arize agent observability](https://arize.com/ai-agents/agent-observability/)
- Perfetto / Chrome Trace Event — [external formats](https://perfetto.dev/docs/getting-started/other-formats) · [UI](https://perfetto.dev/docs/visualization/perfetto-ui)
- DuckDB UI — [official ui extension](https://duckdb.org/docs/current/core_extensions/ui) · [MotherDuck local UI](https://motherduck.com/blog/local-duckdb-ui-visual-data-analysis/)
- Event-sourcing correlation/causation — [Arkency](https://blog.arkency.com/correlation-id-and-causation-id-in-evented-systems/) · [Rails Event Store](https://railseventstore.org/docs/core-concepts/correlation-causation)
- Reward-hacking / trajectory debugging — [rubric-RL reward hacking](https://arxiv.org/pdf/2606.04923) · [DoVer](https://arxiv.org/pdf/2512.06749) · [Gaia2](https://arxiv.org/pdf/2602.11964)
