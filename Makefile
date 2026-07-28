UV ?= uv

.PHONY: bootstrap test test-contract

bootstrap:
	$(UV) sync --all-groups --locked

test:
	$(UV) run --all-groups --locked python -B -m pytest

test-contract:
	$(UV) run --all-groups --locked python -B contracts/conformance/validate.py
