UV ?= uv

.PHONY: bootstrap test test-contract test-security

bootstrap:
	$(UV) sync --all-packages --all-groups --locked

test:
	$(UV) run --all-packages --all-groups --locked python -B -m pytest

test-contract:
	$(UV) run --all-packages --all-groups --locked python -B contracts/conformance/validate.py

test-security:
	$(UV) run --all-packages --all-groups --locked python -B -m pytest tests/platform
