UV ?= uv
STUDIO_CONFIG ?= langgraph.json
STUDIO_HOST ?= 127.0.0.1
STUDIO_PORT ?= 2024
MYPY_SOURCES := apps/api/src apps/mcp-gateway/src apps/worker/src \
	mcp-servers/knowledge/src mcp-servers/ticket/src \
	packages/agent-runtime/src packages/application/src packages/context/src \
	packages/domain/src packages/engineering-control/src packages/graph/src \
	packages/model-gateway/src \
	packages/persistence/src packages/policy/src packages/security/src \
	packages/tool-contracts/src web/src

.PHONY: bootstrap studio studio-smoke engineering-control-test \
	engineering-control-smoke lint test test-all test-contract test-security \
	test-identity test-coverage audit ci acceptance

bootstrap:
	$(UV) sync --all-packages --all-groups --locked

studio:
	PYTHONUTF8=1 LANGSMITH_TRACING=false $(UV) run --all-packages --all-groups --locked langgraph dev --config $(STUDIO_CONFIG) --host $(STUDIO_HOST) --port $(STUDIO_PORT) --no-browser

studio-smoke:
	PYTHONUTF8=1 LANGSMITH_TRACING=false $(UV) run --all-packages --all-groups --locked langgraph --version
	PYTHONUTF8=1 LANGSMITH_TRACING=false $(UV) run --all-packages --all-groups --locked langgraph dev --help

engineering-control-test:
	$(UV) run --locked pytest -q tests/core/engineering_control

engineering-control-smoke:
	$(UV) run --locked flowpilot-eng --help

test:
	$(UV) run --all-packages --all-groups --locked python -B -m pytest

test-all: test test-contract

lint:
	$(UV) run --all-packages --all-groups --locked ruff check apps packages mcp-servers domain-packs scripts tests web
	$(UV) run --all-packages --all-groups --locked mypy --strict $(MYPY_SOURCES)

test-contract:
	$(UV) run --all-packages --all-groups --locked python -B contracts/conformance/validate.py

test-security:
	$(UV) run --all-packages --all-groups --locked python -B -m pytest tests/core/test_security.py tests/core/test_oidc_api.py tests/runtime/security tests/data/security tests/platform/security tests/platform/test_gateway_security.py tests/platform/test_identity_boundary.py tests/acceptance/platform_security tests/experience/test_secret_scan.py

test-identity:
	$(UV) run --all-packages --all-groups --locked python -B -m pytest tests/core/test_oidc_api.py tests/platform/test_identity_boundary.py

test-coverage:
	$(UV) run --all-packages --all-groups --locked python -B -m pytest --cov --cov-report=term-missing:skip-covered --cov-report=xml:coverage.xml

audit:
	$(UV) run --all-packages --all-groups --locked pip-audit --local --skip-editable --progress-spinner off

ci: lint test-coverage test-contract test-security audit

acceptance:
	$(UV) run --frozen python -B scripts/acceptance/run_acceptance.py
