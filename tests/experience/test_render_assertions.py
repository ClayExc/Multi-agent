"""Render assertions: task list/detail, timeline states, approval card,
completion form, error/retry panels, citations, escaping.

正常=运行/等待/失败状态渲染；审批卡展示影响/参数/依据/摘要/过期时间（与
M5-1 数据契约同构）；信息补全表单与恢复入口；失败=错误面板与重试入口且
不渲染假数据；安全=审批卡无审批写控件、文本全部转义。
"""

from __future__ import annotations

from flowpilot_shell.models import (
    ShellContractError,
    ShellUnavailableError,
)
from flowpilot_shell.render import (
    render_approval_card,
    render_completion_form,
    render_error_panel,
    render_result_artifact,
    render_task_detail,
    render_task_error_panel,
    render_task_list,
    render_timeline,
)


def test_task_list_renders_statuses(store_with_fixtures) -> None:
    """正常: 任务列表渲染运行/等待/失败状态徽标。"""
    html = render_task_list(store_with_fixtures.tasks())
    assert "task_onboard_004" in html
    assert "运行中" in html or "等待审批" in html or "等待信息补全" in html
    assert "失败" in html
    assert "已完成" in html
    # 列表包含任务链接（可进入详情）
    assert 'href="/views/tasks/task_onboard_004"' in html


def test_task_detail_renders_timeline_states(store_with_fixtures) -> None:
    """正常: 详情页时间线渲染运行/等待/失败事件。"""
    store = store_with_fixtures
    detail = render_task_detail(store.task("task_repair_003"), store)
    assert "信息补全" in detail
    assert "input.required" in detail or "req_repair_0001" in detail
    failed = render_task_detail(store.task("task_inventory_005"), store)
    assert "任务失败" in failed
    assert "INVENTORY_INSUFFICIENT" in failed
    running = render_task_detail(store.task("task_vpn_perm_002"), store)
    assert "运行中" in running


def test_timeline_renders_gap_marker(store_with_fixtures) -> None:
    """恢复: 序列缺口在时间线渲染为缺口条目与重建入口。"""
    html = render_timeline(
        store_with_fixtures.timeline_events("task_vpn_perm_002"),
        store_with_fixtures.timeline_gaps("task_vpn_perm_002"),
        task_id="task_vpn_perm_002",
    )
    assert "事件缺口" in html
    assert "序列 3 缺失" in html
    assert "重建" in html


def test_approval_card_renders_m5_isomorphic_fields(store_with_fixtures) -> None:
    """正常: 审批卡渲染影响/参数/依据/摘要/过期时间（M5-1 同构字段）。"""
    store = store_with_fixtures
    approval, action = store.approval_card("apr_00000004")
    html = render_approval_card(approval, action)
    # 摘要 = tool + action_id + agent
    assert "itsm.permission.grant.v1" in html
    assert "act_permission_004" in html
    assert "agent-ops" in html
    # 影响 = resource + purpose
    assert "entitlement" in html and "ent_vpn_0008" in html
    assert "新员工入职权限授予" in html
    # 参数 = arguments
    assert "permission_set" in html and "vpn_standard" in html
    assert "expires_days" in html
    # 依据 = policy_version + policy_decision_id
    assert "policy.v1.3" in html
    assert "pd_0004apr04" in html
    # 过期时间
    assert "2026-08-02" in html


def test_approval_card_never_renders_write_controls(store_with_fixtures) -> None:
    """安全: 审批卡不含任何审批写控件（不推断审批成功）。"""
    store = store_with_fixtures
    for approval_id in ("apr_00000001", "apr_00000004"):
        approval, action = store.approval_card(approval_id)
        html = render_approval_card(approval, action)
        assert "approve" not in html.lower()
        assert "reject" not in html.lower()
        assert "<form" not in html
        assert "<button" not in html
        assert 'name="decision"' not in html
        # 明确声明展示边界
        assert "不发起审批写调用" in html


def test_completion_form_renders_fields_and_recovery(store_with_fixtures) -> None:
    """正常: 信息补全表单渲染缺失字段与恢复入口。"""
    store = store_with_fixtures
    task = store.task("task_repair_003")
    fields = tuple(
        event.payload["missing_fields"]
        for event in store.timeline_events("task_repair_003")
        if event.event_type == "task.input.required.v1"
    )[0]
    html = render_completion_form(task, tuple(fields))
    assert (
        "contact_phone" in html
        and "asset_location" in html
        and "preferred_window" in html
    )
    assert 'action="/shell/commands/submit"' in html
    assert "提交补全信息" in html
    assert "恢复入口" in html
    assert "从事件流重建本任务视图" in html


def test_error_panel_renders_retry_entry() -> None:
    """失败: API 不可用渲染错误面板与重试入口，不渲染假数据。"""
    html = render_error_panel(
        ShellUnavailableError("模拟后端不可用（503）"),
        retry_href="/views/tasks/task_onboard_001",
    )
    assert "加载失败" in html
    assert "模拟后端不可用" in html
    assert "可重试" in html
    assert 'data-action="retry"' in html
    assert "task_onboard_001" in html
    # 不渲染任何任务行/状态（无假数据）
    assert "task-row" not in html
    assert "task-status" not in html


def test_contract_error_panel_renders() -> None:
    """失败: 契约错误渲染错误面板。"""
    html = render_error_panel(ShellContractError("body violates the v1 contract"))
    assert "加载失败" in html
    assert "不可重试" in html


def test_task_error_panel_renders_retry_form_when_retryable(
    store_with_fixtures,
) -> None:
    """失败: 可重试的失败任务渲染重试入口。"""
    store = store_with_fixtures
    task = store.task("task_inventory_005")
    html = render_task_error_panel(task)
    assert "任务失败" in html
    assert "INVENTORY_INSUFFICIENT" in html
    assert 'action="/shell/commands/retry"' in html
    assert "重试该任务" in html


def test_result_artifact_renders_citations(store_with_fixtures) -> None:
    """正常: 结果引用与引用来源渲染。"""
    store = store_with_fixtures
    artifact = store.artifact("ref://artifacts/res_onboard_001")
    html = render_result_artifact(artifact)
    assert "ref://artifacts/res_onboard_001" in html
    assert "ref://knowledge/device-standards" in html
    assert "4.2 新员工设备标准" in html
    assert "doc.v1.4" in html


def test_xss_escaping_in_render() -> None:
    """安全: 不可信文本（purpose/字段值）渲染时被转义。"""
    from flowpilot_shell.models import TaskView
    from flowpilot_shell.store import ShellStore

    base = {
        "task_id": "task_evil_00001",
        "thread_id": "thread_evil_00001",
        "tenant_id": "tenant-it",
        "status": "RUNNING",
        "version": 1,
        "run_generation": 1,
        "purpose": '<script>alert("xss")</script>',
        "data_classification": "internal",
        "security_context": {
            "context_id": "secctx_evil_0001",
            "context_ref": "ref://security/contexts/secctx_evil_0001",
            "context_hash": (
                "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
            ),
            "tenant_id": "tenant-it",
            "subject_id": "u_evil",
            "subject_type": "user",
            "purpose": '<script>alert("xss")</script>',
            "authentication": {
                "method": "oidc",
                "assurance_level": "substantial",
                "session_id_hash": (
                    "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
                ),
            },
            "delegation_id": None,
            "data_classification_ceiling": "internal",
            "issued_at": "2026-08-01T08:00:00Z",
            "expires_at": "2026-08-01T20:00:00Z",
        },
        "release": {
            "graph_version": "v1",
            "domain_pack_version": "v1",
            "context_policy_version": "v1",
            "policy_version": "v1",
            "tool_schema_set": "v1",
        },
        "waiting_on": None,
        "result_ref": None,
        "error": None,
        "created_at": "2026-08-01T08:00:00Z",
        "updated_at": "2026-08-01T08:01:00Z",
        "completed_at": None,
    }
    store = ShellStore()
    store.register_task(TaskView.from_mapping(base))
    html = render_task_list(store.tasks())
    assert "<script>" not in html
    assert "&lt;script&gt;" in html
