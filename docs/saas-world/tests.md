# Tests

The full suite is offline & key-free — the LLM parser replays from `tests/cassettes/`.

```
pytest                       # full suite
pytest -m <marker>           # one system in isolation; markers:
#   kernel state toolapi content scenario npc evaluator npc_parser extractor llm
#   seeding cli observability   integration golden property validation
ruff check . && mypy src
```

Or via the convenience targets:

```
make check                   # the full gate: ruff + mypy (strict, over src) + pytest
make test                    # pytest only
make replay-check            # two trajectories, same seed; assert byte-identical replay
```

No `ANTHROPIC_API_KEY` is needed; set one only to record new cassette entries — see
[NPC replies & novel messages](npc-replies.md).
