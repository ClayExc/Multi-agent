"""Secret scan over the whole web tree (FP-SEC-006 style, 0 findings)."""

from __future__ import annotations

import re
from pathlib import Path

WEB = Path(__file__).resolve().parents[2] / "web"

_PATTERNS = [
    re.compile(r"sk-[A-Za-z0-9]{16,}"),  # OpenAI-style API keys
    re.compile(r"(?i)api[_-]?key\s*[:=]\s*[\"'][^\"']{8,}[\"']"),
    re.compile(r"(?i)password\s*[:=]\s*[\"'][^\"']{6,}[\"']"),
    re.compile(r"-----BEGIN (RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    re.compile(r"(?i)secret\s*[:=]\s*[\"'][^\"']{12,}[\"']"),
    re.compile(r"Bearer [A-Za-z0-9._-]{20,}"),
]


def test_secret_scan_zero_findings() -> None:
    """安全: web/** 渲染与数据均无明文密钥（Secret Scan 0）。"""
    offenders: list[str] = []
    for path in sorted(WEB.rglob("*")):
        if not path.is_file() or path.name == "py.typed":
            continue
        if path.suffix not in {".py", ".js", ".css", ".html", ".json", ".md"}:
            continue
        text = path.read_text(encoding="utf-8")
        for pattern in _PATTERNS:
            if pattern.search(text):
                offenders.append(f"{path.relative_to(WEB)}: {pattern.pattern!r}")
    assert not offenders, (
        f"secret scan found {len(offenders)} candidate(s): {offenders[:5]}"
    )


def test_fixture_action_digests_are_derived_from_synthetic_data() -> None:
    """安全: 审批 digest 由合成计划动作的规范摘要派生（非真实凭据派生值）。"""
    import json

    from flowpilot_shell.canonical import canonical_digest

    approvals = json.loads(
        (WEB / "fixtures" / "approvals.v1.json").read_text(encoding="utf-8")
    )["approvals"]
    actions = json.loads(
        (WEB / "fixtures" / "planned-actions.v1.json").read_text(encoding="utf-8")
    )["planned_actions"]
    actions_by_id = {action["action_id"]: action for action in actions}
    for approval in approvals:
        action = actions_by_id[approval["action_id"]]
        assert approval["action_digest"] == canonical_digest(action)
        # 合成约束：动作参数不含任何凭据形态值
        rendered = json.dumps(action, ensure_ascii=False)
        assert "password" not in rendered.lower()
        assert "api_key" not in rendered.lower()
