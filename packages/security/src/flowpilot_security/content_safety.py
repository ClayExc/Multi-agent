from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum

from .credentials import _safe_root_path, scan_secret_material
from .errors import SecurityError, SecurityErrorCode


class ContentSurface(StrEnum):
    TOOL_ARGUMENTS = "tool_arguments"
    MCP_CONTENT = "mcp_content"
    TOOL_RESULT = "tool_result"
    SIGNAL = "signal"


@dataclass(frozen=True, slots=True)
class ContentSafetyRule:
    rule_id: str
    description: str
    pattern: str
    surfaces: frozenset[ContentSurface]


@dataclass(frozen=True, slots=True)
class ContentFinding:
    rule_id: str
    path: str
    surface: ContentSurface


PROMPT_INJECTION_RULES: tuple[ContentSafetyRule, ...] = (
    ContentSafetyRule(
        rule_id="prompt_instruction_override_exfiltration",
        description="instruction override combined with protected-data exfiltration",
        pattern=(
            r"(?is)ignore\s+(?:all\s+)?(?:prior|previous|system|developer)\s+"
            r"instructions?.{0,120}(?:reveal|print|return|send|dump|exfiltrat\w*)"
            r".{0,120}(?:system\s+prompt|developer\s+message|credential|secret|token)"
        ),
        surfaces=frozenset(
            {
                ContentSurface.TOOL_ARGUMENTS,
                ContentSurface.MCP_CONTENT,
                ContentSurface.TOOL_RESULT,
            }
        ),
    ),
    ContentSafetyRule(
        rule_id="prompt_control_token",
        description="serialized model control token in untrusted content",
        pattern=r"(?i)<\|(?:system|developer|assistant)\|>",
        surfaces=frozenset(
            {
                ContentSurface.TOOL_ARGUMENTS,
                ContentSurface.MCP_CONTENT,
                ContentSurface.TOOL_RESULT,
                ContentSurface.SIGNAL,
            }
        ),
    ),
    ContentSafetyRule(
        rule_id="prompt_boundary_forgery",
        description="forged system or developer prompt boundary",
        pattern=r"(?i)-----BEGIN (?:SYSTEM|DEVELOPER) (?:PROMPT|MESSAGE)-----",
        surfaces=frozenset(
            {
                ContentSurface.TOOL_ARGUMENTS,
                ContentSurface.MCP_CONTENT,
                ContentSurface.TOOL_RESULT,
                ContentSurface.SIGNAL,
            }
        ),
    ),
)

_COMPILED_RULES: tuple[tuple[ContentSafetyRule, re.Pattern[str]], ...] = tuple(
    (rule, re.compile(rule.pattern)) for rule in PROMPT_INJECTION_RULES
)


def _text(value: object) -> str | None:
    if isinstance(value, str):
        return value
    if isinstance(value, (bytes, bytearray, memoryview)):
        return bytes(value).decode("utf-8", errors="ignore")
    return None


def scan_prompt_injection(
    value: object,
    *,
    surface: ContentSurface,
    field: str = "content",
) -> tuple[ContentFinding, ...]:
    root = _safe_root_path(field)
    findings: list[ContentFinding] = []
    seen: set[int] = set()
    stack: list[tuple[object, str]] = [(value, root)]
    while stack:
        current, path = stack.pop()
        text = _text(current)
        if text is not None:
            findings.extend(
                ContentFinding(rule.rule_id, path, surface)
                for rule, pattern in _COMPILED_RULES
                if surface in rule.surfaces and pattern.search(text) is not None
            )
            continue
        if isinstance(current, Mapping):
            identity = id(current)
            if identity in seen:
                continue
            seen.add(identity)
            items = tuple(current.items())
            for index in range(len(items) - 1, -1, -1):
                key, child = items[index]
                stack.append((child, f"{path}.values[{index}]"))
                stack.append((key, f"{path}.keys[{index}]"))
            continue
        if isinstance(current, Sequence) and not isinstance(
            current, (str, bytes, bytearray, memoryview)
        ):
            identity = id(current)
            if identity in seen:
                continue
            seen.add(identity)
            for index in range(len(current) - 1, -1, -1):
                stack.append((current[index], f"{path}[{index}]"))
    return tuple(findings)


def assert_content_safe(
    value: object,
    *,
    surface: ContentSurface,
    field: str = "content",
) -> None:
    secret_findings = scan_secret_material(value, field=field)
    if secret_findings:
        secret_finding = secret_findings[0]
        raise SecurityError(
            SecurityErrorCode.DLP_BLOCKED,
            (
                "DLP blocked secret-like material at "
                f"{secret_finding.path} ({secret_finding.family_id})"
            ),
        )
    prompt_findings = scan_prompt_injection(
        value,
        surface=surface,
        field=field,
    )
    if prompt_findings:
        prompt_finding = prompt_findings[0]
        raise SecurityError(
            SecurityErrorCode.PROMPT_INJECTION_BLOCKED,
            (
                "content safety blocked a prompt-injection rule at "
                f"{prompt_finding.path} ({prompt_finding.rule_id})"
            ),
        )
