from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
COMPOSE = (ROOT / "infra" / "compose" / "compose.yaml").read_text(
    encoding="utf-8"
)
ENV_EXAMPLE = (ROOT / ".env.example").read_text(encoding="utf-8")


def test_compose_declares_required_data_and_control_services() -> None:
    for service in (
        "postgres:",
        "redis:",
        "keycloak:",
        "opa:",
        "otel-collector:",
    ):
        assert f"  {service}" in COMPOSE
    assert COMPOSE.count("healthcheck:") == 5
    assert COMPOSE.count("127.0.0.1:") == 6
    assert "0.0.0.0:" not in COMPOSE


def test_redis_is_explicitly_rebuildable_not_durable() -> None:
    assert "--appendonly" in COMPOSE
    assert '"no"' in COMPOSE
    assert "--save" in COMPOSE
    assert "redis-data" not in COMPOSE


def test_forward_migration_only_is_mounted() -> None:
    for migration in (
        "0001_persistence_baseline.sql:",
        "0002_checkpoint_sequence_cas.sql:",
        "0003_api_task_initialization.sql:",
    ):
        assert migration in COMPOSE
    assert ".down.sql" not in COMPOSE


def test_environment_file_contains_only_local_placeholders() -> None:
    assert "local-dev-postgres-change-me" in ENV_EXAMPLE
    assert "local-dev-redis-change-me" in ENV_EXAMPLE
    assert "local-dev-keycloak-change-me" in ENV_EXAMPLE
    for forbidden in ("BEGIN PRIVATE KEY", "AKIA", "sk-proj-", "Bearer "):
        assert forbidden not in ENV_EXAMPLE
