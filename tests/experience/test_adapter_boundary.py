"""API adapter boundary tests.

正常=任务投影成功解析；失败=404/503/500/畸形响应映射为类型化错误，外壳
据此渲染错误面板与重试入口而不渲染假数据；安全=适配层无审批写方法、
无 PostgreSQL/MCP/领域依赖（依赖图断言）、命令构建器只产生非审批命令。
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

import pytest


def _transport_with(responses: list[tuple[int, Any]], calls: list) -> Any:
    def transport(
        method: str, url: str, headers: dict[str, str], body: bytes | None
    ) -> tuple[int, dict[str, str], bytes]:
        calls.append((method, url, dict(headers), body))
        status, payload = responses.pop(0)
        raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        return status, {"content-type": "application/json"}, raw

    return transport


def _client(responses: list[tuple[int, Any]]) -> tuple[Any, list]:
    from flowpilot_shell.api_client import ApiClient

    calls: list = []
    return ApiClient(transport=_transport_with(responses, calls)), calls


def test_get_task_success(fixture_files) -> None:
    """正常: 200 任务投影解析为 TaskView。"""
    from flowpilot_shell.api_client import ApiClient

    task = fixture_files["tasks.v1.json"]["tasks"][0]
    client = ApiClient(transport=_transport_with([(200, task)], []))
    view = client.get_task(task["task_id"])
    assert view.task_id == task["task_id"]
    assert view.status == task["status"]
    assert view.purpose == task["purpose"]


def test_adapter_forwards_only_opaque_cookie_not_browser_authority(
    fixture_files,
) -> None:
    """安全: 上游身份只来自不透明 Cookie，不发送 tenant/role Header。"""
    from flowpilot_shell.api_client import ApiClient

    task = fixture_files["tasks.v1.json"]["tasks"][0]
    calls: list = []
    client = ApiClient(transport=_transport_with([(200, task)], calls))

    client.get_task(task["task_id"], cookie_header="__Host-flowpilot-session=sess_x")

    _method, _path, headers, _body = calls[0]
    assert headers == {
        "Accept": "application/json",
        "Cookie": "__Host-flowpilot-session=sess_x",
    }
    assert all("tenant" not in name.lower() for name in headers)
    assert all("role" not in name.lower() for name in headers)


def test_adapter_rejects_cookie_header_injection(fixture_files) -> None:
    from flowpilot_shell.api_client import ApiClient
    from flowpilot_shell.models import ShellContractError

    task = fixture_files["tasks.v1.json"]["tasks"][0]
    client = ApiClient(transport=_transport_with([(200, task)], []))

    with pytest.raises(ShellContractError, match="cookie header"):
        client.get_task(task["task_id"], cookie_header="sess=x\r\nX-Tenant: forged")


def test_adapter_rejects_duplicate_browser_session_cookie(fixture_files) -> None:
    from flowpilot_shell.api_client import ApiClient
    from flowpilot_shell.models import ShellContractError

    task = fixture_files["tasks.v1.json"]["tasks"][0]
    client = ApiClient(transport=_transport_with([(200, task)], []))

    with pytest.raises(ShellContractError, match="ambiguous"):
        client.get_task(
            task["task_id"],
            cookie_header=(
                "__Host-flowpilot-session=first; "
                "__Host-flowpilot-session=second"
            ),
        )


def test_get_task_404_maps_to_not_found(fixture_files) -> None:
    """失败: 404 映射为 ShellNotFoundError（渲染 404 面板，不渲染假数据）。"""
    from flowpilot_shell.api_client import ApiClient
    from flowpilot_shell.models import ShellNotFoundError

    envelope = {
        "error": {"code": "TASK_NOT_FOUND", "message": "not found", "retryable": False}
    }
    client = ApiClient(transport=_transport_with([(404, envelope)], []))
    with pytest.raises(ShellNotFoundError):
        client.get_task("task_missing_9999")


def test_get_task_503_maps_to_unavailable_retryable(fixture_files) -> None:
    """失败: 503 映射为可重试的 ShellUnavailableError（错误面板 + 重试入口）。"""
    from flowpilot_shell.api_client import ApiClient
    from flowpilot_shell.models import ShellUnavailableError

    envelope = {
        "error": {
            "code": "REPOSITORY_UNAVAILABLE",
            "message": "unavailable",
            "retryable": True,
        }
    }
    client = ApiClient(transport=_transport_with([(503, envelope)], []))
    with pytest.raises(ShellUnavailableError):
        client.get_task("task_onboard_001")


def test_get_task_500_maps_to_server_error(fixture_files) -> None:
    """失败: 500 映射为 ShellServerError（不可盲目重试的语义）。"""
    from flowpilot_shell.api_client import ApiClient
    from flowpilot_shell.models import ShellServerError

    envelope = {
        "error": {"code": "INTERNAL_ERROR", "message": "boom", "retryable": False}
    }
    client = ApiClient(transport=_transport_with([(500, envelope)], []))
    with pytest.raises(ShellServerError):
        client.get_task("task_onboard_001")


def test_get_task_malformed_body_maps_to_contract_error(fixture_files) -> None:
    """失败: 缺失必填字段的响应体映射为 ShellContractError（不渲染假数据）。"""
    from flowpilot_shell.api_client import ApiClient
    from flowpilot_shell.models import ShellContractError

    bad = dict(fixture_files["tasks.v1.json"]["tasks"][0])
    del bad["status"]
    client = ApiClient(transport=_transport_with([(200, bad)], []))
    with pytest.raises(ShellContractError):
        client.get_task("task_onboard_001")


def test_get_task_rejects_null_required_datetime(fixture_files) -> None:
    """边界: 非 Optional 时间字段收到 null 时失败关闭。"""
    from flowpilot_shell.api_client import ApiClient
    from flowpilot_shell.models import ShellContractError

    bad = dict(fixture_files["tasks.v1.json"]["tasks"][0])
    bad["created_at"] = None
    client = ApiClient(transport=_transport_with([(200, bad)], []))
    with pytest.raises(ShellContractError, match="created_at must be a date-time"):
        client.get_task("task_onboard_001")


def test_get_task_non_json_body_maps_to_contract_error(fixture_files) -> None:
    """失败: 非 JSON 响应体映射为 ShellContractError。"""

    def transport(method, url, headers, body):
        return 200, {"content-type": "text/html"}, b"<html>not json</html>"

    from flowpilot_shell.api_client import ApiClient
    from flowpilot_shell.models import ShellContractError

    client = ApiClient(transport=transport)
    with pytest.raises(ShellContractError):
        client.get_task("task_onboard_001")


def test_submit_command_rejects_non_object_success_body() -> None:
    """边界: 2xx 命令响应也必须是 JSON object，不能把 list 当作字典传播。"""
    from flowpilot_shell.api_client import ApiClient
    from flowpilot_shell.models import ShellContractError

    client = ApiClient(transport=_transport_with([(202, ["unexpected"])], []))
    with pytest.raises(ShellContractError, match="must be a JSON object"):
        client.submit_command({})


@pytest.mark.parametrize(
    "envelope",
    [
        {"error": []},
        {"error": None},
        {"error": {"code": "INTERNAL_ERROR", "retryable": "false"}},
    ],
)
def test_error_response_rejects_invalid_nested_types(envelope) -> None:
    """失败: 畸形 error object 不得通过 truthiness 或默认值伪装成类型化错误。"""
    from flowpilot_shell.api_client import ApiClient
    from flowpilot_shell.models import ShellContractError

    client = ApiClient(transport=_transport_with([(500, envelope)], []))
    with pytest.raises(ShellContractError):
        client.get_task("task_onboard_001")


def test_transport_unreachable_maps_to_unavailable() -> None:
    """失败: 连接失败映射为可重试的 ShellUnavailableError。"""
    from flowpilot_shell.api_client import ApiClient
    from flowpilot_shell.models import ShellUnavailableError

    client = ApiClient(base_url="http://127.0.0.1:1", timeout=0.5)
    with pytest.raises(ShellUnavailableError):
        client.get_task("task_onboard_001")


def test_adapter_has_no_approval_write_capability() -> None:
    """安全: 适配层暴露的方法里没有审批写（不推断审批成功）。"""
    from flowpilot_shell.api_client import ApiClient

    methods = {name for name in dir(ApiClient) if not name.startswith("_")}
    assert methods == {
        "get_audit_events",
        "get_governance_correlation",
        "get_knowledge_diagnostic",
        "get_knowledge_document",
        "get_policy_decisions",
        "get_policy_versions",
        "get_security_events",
        "get_task",
        "get_task_mapping",
        "submit_command",
        "submit_knowledge_operation",
    }
    assert not any("approv" in name.lower() for name in methods)


def test_commands_builder_has_no_approval_command() -> None:
    """安全: 命令构建器只产生 message.submit 与 retry，无审批命令。"""
    import pathlib

    import flowpilot_shell.commands as commands_module

    source = pathlib.Path(commands_module.__file__).read_text(encoding="utf-8")
    assert "task.approval.decide.v1" not in source
    public = {
        name
        for name in dir(commands_module)
        if name.startswith("build_") and callable(getattr(commands_module, name))
    }
    assert public == {"build_retry_command", "build_submit_message_command"}


def test_submit_command_digest_matches_fixture_golden(fixture_files) -> None:
    """正常: 外壳构建的提交命令与 fixture 黄金样本同构（契约一致）。"""
    from flowpilot_shell.commands import build_submit_message_command

    golden = fixture_files["commands.v1.json"]["commands"][0]
    built = build_submit_message_command(
        tenant_id=golden["tenant_id"],
        task_id=golden["task_id"],
        actor=golden["actor"],
        security_context=golden["security_context"],
        expected_task_version=golden["expected_task_version"],
        message_id=golden["payload"]["message_id"],
        message_ref=golden["payload"]["message_ref"],
        attachment_refs=golden["payload"]["attachment_refs"],
        issued_at=datetime.fromisoformat(golden["issued_at"].replace("Z", "+00:00")),
    )
    assert built["command_type"] == golden["command_type"]
    assert built["command_digest"] == golden["command_digest"]
    assert built["idempotency_key"] == golden["idempotency_key"]
    assert built["payload"] == golden["payload"]


def test_dependency_graph_is_stdlib_only() -> None:
    """安全: web/src 运行期只依赖标准库（无 PostgreSQL/MCP/领域包直连）。"""
    import ast
    import pathlib

    forbidden_prefixes = (
        "flowpilot_",
        "psycopg",
        "redis",
        "sqlalchemy",
        "langgraph",
        "fastapi",
        "pydantic",
        "httpx",
        "uvicorn",
        "rfc8785",
    )
    src_root = pathlib.Path(__file__).resolve().parents[2] / "web" / "src"
    offenders: list[str] = []
    for path in src_root.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name.split(".")[0].startswith(forbidden_prefixes):
                        offenders.append(f"{path}: import {alias.name}")
            elif (
                isinstance(node, ast.ImportFrom)
                and node.module
                and node.module.split(".")[0].startswith(forbidden_prefixes)
            ):
                offenders.append(f"{path}: from {node.module} import")
    assert not offenders, f"web/src must stay stdlib-only: {offenders}"
