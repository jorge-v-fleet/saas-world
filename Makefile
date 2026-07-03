# Convenience targets. All run inside the uv-managed venv (uv must be on PATH).
.PHONY: test lint typecheck check replay-check serve record-cassette

CASSETTE ?= /tmp/saasworld-cassette.jsonl

test:          ## run the full test suite
	uv run pytest -q

lint:          ## ruff lint
	uv run ruff check .

typecheck:     ## mypy (strict) over src
	uv run mypy src

check: lint typecheck test  ## the full gate: lint + types + tests

replay-check:  ## run two trajectories with the same seed; verify byte-identical replay
	uv run python scripts/replay_determinism.py

serve:         ## start the JSON-RPC service on 127.0.0.1:8080
	uv run python -m saasworld.serve

record-cassette:  ## record NPC replies: start the env server in record mode (needs ANTHROPIC_API_KEY), then drive your agent — novel messages append to CASSETTE (default /tmp/saasworld-cassette.jsonl)
	@test -n "$$ANTHROPIC_API_KEY" || { echo "record-cassette needs ANTHROPIC_API_KEY set"; exit 1; }
	SAASWORLD_LLM_MODE=record SAASWORLD_CASSETTE=$(CASSETTE) uv run python -m saasworld.openenv.serve
