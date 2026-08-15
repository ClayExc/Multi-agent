from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

import pytest


@dataclass
class ExampleRepository:
    root: Path

    def git(self, *args: str) -> str:
        completed = subprocess.run(
            ["git", *args],
            cwd=self.root,
            check=True,
            shell=False,
            text=True,
            capture_output=True,
        )
        return completed.stdout.strip()

    def write(self, path: str, content: str) -> None:
        destination = self.root.joinpath(*path.split("/"))
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(content, encoding="utf-8")

    def remove(self, path: str) -> None:
        self.root.joinpath(*path.split("/")).unlink()

    def commit(self, message: str) -> str:
        self.git("add", "-A")
        self.git("commit", "-m", message)
        return self.git("rev-parse", "HEAD")


@pytest.fixture
def example_repository(tmp_path: Path) -> ExampleRepository:
    repository = ExampleRepository(tmp_path / "repository")
    repository.root.mkdir()
    repository.git("init", "-b", "main")
    repository.git("config", "user.email", "flowpilot@example.invalid")
    repository.git("config", "user.name", "FlowPilot Test")
    repository.write(
        "pyproject.toml",
        """[project]
name = "test-workspace"
version = "0.1.0"

[tool.uv.workspace]
members = ["packages/engineering-control"]

[tool.uv.sources]
flowpilot-engineering-control = { workspace = true }
""",
    )
    repository.write(
        "packages/engineering-control/pyproject.toml",
        """[project]
name = "flowpilot-engineering-control"
version = "0.1.0"
dependencies = []
""",
    )
    repository.write(
        "packages/engineering-control/src/flowpilot_engineering_control/__init__.py",
        "from .ports import PublicPort\n",
    )
    repository.write(
        "packages/engineering-control/src/flowpilot_engineering_control/ports.py",
        "class PublicPort:\n    pass\n",
    )
    repository.write(
        "packages/engineering-control/src/flowpilot_engineering_control/private.py",
        "VALUE = 'fixture-secret-that-must-not-leak'\n",
    )
    for index in range(40):
        repository.write(
            f"packages/engineering-control/src/flowpilot_engineering_control/filler_{index:02}.py",
            f"VALUE_{index} = '{index:04}'\n" * 10,
        )
    repository.write(
        "tests/core/engineering_control/test_fixture.py",
        "def test_fixture():\n    assert True\n",
    )
    repository.write("tests/core/evidence/generated.md", "generated-secret\n")
    repository.write(".idea/workspace.xml", "local-only-secret\n")
    repository.write("AGENTS.md", "# Test authority\n")
    repository.write(".gitignore", ".flowpilot-engineering/\n")
    repository.commit("baseline")
    return repository
