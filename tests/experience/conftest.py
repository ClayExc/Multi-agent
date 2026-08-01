"""Shared fixtures for tests/experience (track-C web shell)."""

from __future__ import annotations

import asyncio
import inspect
import json
import sys
import threading
from pathlib import Path
from typing import Any

import pytest
from jsonschema import Draft202012Validator, FormatChecker
from referencing import Registry, Resource

ROOT = Path(__file__).resolve().parents[2]
WEB = ROOT / "web"
SRC = WEB / "src"
FIXTURES = WEB / "fixtures"
CONTRACTS = ROOT / "contracts" / "jsonschema"

for source_root in (
    SRC,
    WEB,
    ROOT / "apps" / "api" / "src",
    ROOT / "packages" / "application" / "src",
    ROOT / "packages" / "domain" / "src",
):
    sys.path.insert(0, str(source_root))


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line(
        "markers",
        "experience: track-C web shell tests "
        "(fixture contract, adapter boundary, render)",
    )


def pytest_pyfunc_call(pyfuncitem: pytest.Function) -> bool | None:
    """Run coroutine tests on a fresh deterministic event loop."""
    test_function = pyfuncitem.obj
    if not inspect.iscoroutinefunction(test_function):
        return None
    parameter_names = inspect.signature(test_function).parameters
    arguments: dict[str, Any] = {
        name: pyfuncitem.funcargs[name] for name in parameter_names
    }
    asyncio.run(test_function(**arguments))
    return True


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def contract_registry() -> Registry:
    registry = Registry()
    for path in sorted(CONTRACTS.glob("*.json")):
        schema = load_json(path)
        resource = Resource.from_contents(schema)
        registry = registry.with_resource(schema["$id"], resource)
        registry = registry.with_resource(path.resolve().as_uri(), resource)
    return registry


@pytest.fixture(scope="session")
def registry() -> Registry:
    return contract_registry()


def validate_against(registry: Registry, schema_name: str, instance: Any) -> None:
    schema = load_json(CONTRACTS / schema_name)
    Draft202012Validator(
        schema, registry=registry, format_checker=FormatChecker()
    ).validate(instance)


@pytest.fixture(scope="session")
def fixture_files() -> dict[str, dict[str, Any]]:
    return {path.name: load_json(path) for path in sorted(FIXTURES.glob("*.json"))}


@pytest.fixture()
def store_with_fixtures(fixture_files: dict[str, dict[str, Any]]) -> Any:
    from flowpilot_shell.models import (
        ApprovalView,
        EventView,
        PlannedActionView,
        ResultArtifactView,
        TaskView,
    )
    from flowpilot_shell.store import ShellStore

    store = ShellStore()
    for task in fixture_files["tasks.v1.json"]["tasks"]:
        store.register_task(TaskView.from_mapping(task))
    for event in fixture_files["events.v1.json"]["events"]:
        store.apply_event(EventView.from_mapping(event))
    for approval in fixture_files["approvals.v1.json"]["approvals"]:
        store.register_approval(ApprovalView.from_mapping(approval))
    for action in fixture_files["planned-actions.v1.json"]["planned_actions"]:
        store.register_action(PlannedActionView.from_mapping(action))
    for artifact in fixture_files["result-artifacts.v1.json"]["artifacts"]:
        store.register_artifact(ResultArtifactView.from_mapping(artifact))
    return store


@pytest.fixture()
def demo_server() -> Any:
    """Start the stdlib demo server on an ephemeral port (fixture-scoped stop)."""
    from web.server import DemoBackend, DemoServer

    server = DemoServer(DemoBackend(FIXTURES), 0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address[:2]
    base = f"http://{host}:{port}"
    try:
        yield server, base
    finally:
        server.shutdown()
        server.server_close()
