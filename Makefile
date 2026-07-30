UV ?= uv
STUDIO_CONFIG ?= langgraph.json
STUDIO_HOST ?= 127.0.0.1
STUDIO_PORT ?= 2024

.PHONY: bootstrap studio studio-smoke test test-contract test-security

bootstrap:
	$(UV) sync --all-packages --all-groups --locked

studio:
	PYTHONUTF8=1 LANGSMITH_TRACING=false $(UV) run --all-packages --all-groups --locked langgraph dev --config $(STUDIO_CONFIG) --host $(STUDIO_HOST) --port $(STUDIO_PORT) --no-browser

studio-smoke:
	PYTHONUTF8=1 LANGSMITH_TRACING=false $(UV) run --all-packages --all-groups --locked langgraph --version
	PYTHONUTF8=1 LANGSMITH_TRACING=false $(UV) run --all-packages --all-groups --locked langgraph dev --help

test:
	$(UV) run --all-packages --all-groups --locked python -B -m pytest

test-contract:
	$(UV) run --all-packages --all-groups --locked python -B contracts/conformance/validate.py

test-security:
	$(UV) run --all-packages --all-groups --locked python -B -m pytest tests/platform
