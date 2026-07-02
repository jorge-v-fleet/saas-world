# Convenience targets. All run inside the uv-managed venv (uv must be on PATH).
.PHONY: test lint typecheck check replay-check serve

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
