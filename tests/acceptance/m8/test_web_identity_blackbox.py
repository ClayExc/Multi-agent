"""WP-086 browser journey over the Web proxy, independent of S5 internals."""

from __future__ import annotations

import json

import pytest

from tests.experience.test_identity_shell import (
    ACCESS_CANARY,
    CODE_CANARY,
    NONCE_CANARY,
    REFRESH_CANARY,
    _header_text,
    _request,
)

pytest_plugins = ("tests.experience.test_identity_shell",)


def _cookie(headers) -> str:
    return headers["Set-Cookie"].split(";", 1)[0]


def test_login_refresh_task_sse_logout_journey_fails_closed(
    identity_servers,
) -> None:
    state, _backend, base = identity_servers
    index_status, index_headers, index = _request(base + "/")
    assert index_status == 200
    assert b"session-status" in index and "登录".encode() in index

    login_status, login_headers, login_body = _request(
        base + "/api/v1/auth/login"
    )
    assert login_status == 302
    assert login_headers["Cache-Control"] == "no-store"
    transaction = _cookie(login_headers)

    callback_status, callback_headers, callback_body = _request(
        base + "/api/v1/auth/callback?state=opaque&code=" + CODE_CANARY,
        headers={"Cookie": transaction},
    )
    assert callback_status == 303
    session = next(
        item.split(";", 1)[0]
        for item in callback_headers.get_all("Set-Cookie")
        if item.startswith("__Host-flowpilot-session=")
    )

    refresh_status, refresh_headers, refresh_body = _request(
        base + "/api/v1/auth/refresh",
        method="POST",
        headers={"Cookie": session},
    )
    assert refresh_status == 200
    rotated = _cookie(refresh_headers)
    assert json.loads(refresh_body)["status"] == "active"

    task_status, task_headers, task_body = _request(
        base + "/api/v1/tasks/" + state.task_a["task_id"],
        headers={"Cookie": rotated},
    )
    assert task_status == 200
    assert task_headers["Cache-Control"] == "no-store"
    assert json.loads(task_body)["tenant_id"] == "tenant-a"

    sse_status, _sse_headers, sse_body = _request(
        base + "/api/v1/tasks/events",
        headers={"Cookie": rotated},
    )
    assert sse_status == 200
    assert b"event: task.event" in sse_body

    logout_status, logout_headers, logout_body = _request(
        base + "/api/v1/auth/logout",
        method="POST",
        headers={"Cookie": rotated},
    )
    assert logout_status == 204 and logout_body == b""
    assert "Max-Age=0" in logout_headers["Set-Cookie"]

    denied_status, denied_headers, denied_body = _request(
        base + "/api/v1/tasks/" + state.task_a["task_id"],
        headers={"Cookie": rotated},
    )
    assert denied_status == 401
    assert denied_headers["Cache-Control"] == "no-store"
    assert json.loads(denied_body)["error"]["code"] == (
        "API_AUTHENTICATION_INVALID"
    )

    exposed = b"".join(
        (
            index,
            login_body,
            callback_body,
            refresh_body,
            task_body,
            sse_body,
            logout_body,
            denied_body,
        )
    ).decode()
    exposed += _header_text(index_headers)
    exposed += _header_text(login_headers)
    exposed += _header_text(callback_headers)
    exposed += _header_text(refresh_headers)
    exposed += _header_text(task_headers)
    exposed += _header_text(logout_headers)
    exposed += _header_text(denied_headers)
    for canary in (ACCESS_CANARY, REFRESH_CANARY, CODE_CANARY, NONCE_CANARY):
        assert canary not in exposed


@pytest.mark.parametrize("failure", ["sess_expired", "sess_revoked", "missing"])
def test_expired_revoked_and_missing_sessions_require_reauthentication(
    identity_servers,
    failure: str,
) -> None:
    state, _backend, base = identity_servers
    cookie = (
        None
        if failure == "missing"
        else "__Host-flowpilot-session=" + failure
    )
    headers = {"Cookie": cookie} if cookie is not None else None

    refresh_status, refresh_headers, refresh_body = _request(
        base + "/api/v1/auth/refresh",
        method="POST",
        headers=headers,
    )
    assert refresh_status == 401
    assert json.loads(refresh_body)["error"]["code"] in {
        "API_AUTHENTICATION_REQUIRED",
        "API_AUTHENTICATION_INVALID",
    }
    assert "Max-Age=0" in refresh_headers["Set-Cookie"]

    task_status, _task_headers, task_body = _request(
        base + "/api/v1/tasks/" + state.task_a["task_id"],
        headers=headers,
    )
    assert task_status == 401
    expected_code = (
        "API_AUTHENTICATION_REQUIRED"
        if failure == "missing"
        else "API_AUTHENTICATION_INVALID"
    )
    assert json.loads(task_body)["error"]["code"] == expected_code


def test_cross_tenant_browser_headers_cannot_select_ui_authority(
    identity_servers,
) -> None:
    state, _backend, base = identity_servers
    status, _headers, body = _request(
        base + "/api/v1/tasks/" + state.task_a["task_id"],
        headers={
            "Cookie": "__Host-flowpilot-session=sess_a",
            "X-FlowPilot-Tenant-Id": "tenant-b",
            "X-FlowPilot-Roles": "admin",
        },
    )

    assert status == 200
    assert json.loads(body)["tenant_id"] == "tenant-a"
    upstream = state.calls[-1]
    assert upstream["forged_tenant"] is None
    assert upstream["forged_role"] is None


def test_forged_cookie_and_live_demo_query_do_not_bypass_identity(
    identity_servers,
) -> None:
    state, _backend, base = identity_servers
    forged = {"Cookie": "__Host-flowpilot-session=forged"}

    task_list = _request(base + "/views/tasks", headers=forged)
    demo_view = _request(
        base + "/views/tasks/"
        + state.task_a["task_id"]
        + "?demo=missing",
        headers=forged,
    )
    simulated_api = _request(
        base + "/api/v1/tasks/"
        + state.task_a["task_id"]
        + "?simulate=unavailable",
        headers=forged,
    )

    assert [task_list[0], demo_view[0], simulated_api[0]] == [401, 401, 401]
    assert json.loads(simulated_api[2])["error"]["code"] == (
        "API_AUTHENTICATION_INVALID"
    )


def test_malformed_cookie_and_command_error_have_no_sensitive_projection(
    identity_servers,
) -> None:
    state, _backend, base = identity_servers
    malformed = _request(base + "/api/v1/auth/login?cookie_case=comment")
    assert malformed[0] == 503
    assert malformed[1].get_all("Set-Cookie") is None

    task_id = state.task_a["task_id"]
    session_headers = {"Cookie": "__Host-flowpilot-session=sess_a"}
    assert _request(
        base + "/api/v1/tasks/" + task_id,
        headers=session_headers,
    )[0] == 200
    rejected = _request(
        base + "/shell/commands/submit",
        method="POST",
        headers={
            **session_headers,
            "Content-Type": "application/x-www-form-urlencoded",
        },
        body=("task_id=" + task_id).encode(),
    )
    assert rejected[0] == 409
    exposed = rejected[2].decode() + _header_text(rejected[1])
    for canary in (ACCESS_CANARY, REFRESH_CANARY, NONCE_CANARY):
        assert canary not in exposed
