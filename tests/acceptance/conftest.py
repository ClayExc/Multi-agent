from __future__ import annotations

import asyncio
import inspect
import sys
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[2]
SOURCE_ROOTS = (
    ROOT / "apps" / "mcp-gateway" / "src",
    ROOT / "packages" / "application" / "src",
    ROOT / "packages" / "domain" / "src",
    ROOT / "packages" / "persistence" / "src",
    ROOT / "packages" / "policy" / "src",
    ROOT / "packages" / "security" / "src",
    ROOT / "packages" / "tool-contracts" / "src",
)

for source_root in reversed(SOURCE_ROOTS):
    sys.path.insert(0, str(source_root))


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line(
        "markers",
        "asyncio: run this acceptance test in a fresh deterministic event loop",
    )


def pytest_pyfunc_call(pyfuncitem: pytest.Function) -> bool | None:
    test_function = pyfuncitem.obj
    if not inspect.iscoroutinefunction(test_function):
        return None
    parameter_names = inspect.signature(test_function).parameters
    arguments: dict[str, Any] = {
        name: pyfuncitem.funcargs[name] for name in parameter_names
    }
    asyncio.run(test_function(**arguments))
    return True
