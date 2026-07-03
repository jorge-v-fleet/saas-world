# Library APIs

The systems the [CLI](cli.md) and [Agent SDK](agent-sdk.md) drive are usable directly.

## Evaluator

```python
from saasworld.eval import score
result = score(trajectory, ground_truth)   # deterministic, state-grounded; re-scoring is byte-identical
print(result.final)                         # weighted sum in [0,1]
```

## Trajectory store

```python
from saasworld.trajectory import open_run, replay, project, TrajectoryIndex
store = open_run(manifest, state=world, base_dir="runs")   # manifest + opening snapshot
kernel.add_sink(store.record)                              # tap the single-writer event stream
store.close_run(score)                                     # final snapshot + score.json
replay("run-id", "runs")                                   # byte-exact log + final snapshot, 0 model calls
idx = TrajectoryIndex("index.duckdb"); idx.rebuild("runs")
idx.reward_hack(); idx.regression("inst-abc"); idx.failure_clusters()
```

The DuckDB index is disposable — drop `index.duckdb` and `rebuild`.
