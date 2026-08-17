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
    WORKING_MEMORY = "working_memory"


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
                ContentSurface.WORKING_MEMORY,
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
                ContentSurface.WORKING_MEMORY,
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
                ContentSurface.WORKING_MEMORY,
            }
        ),
    ),
)

WORKING_MEMORY_RULES: tuple[ContentSafetyRule, ...] = (
    ContentSafetyRule(
        rule_id="working_memory_hidden_reasoning",
        description="hidden model reasoning marker or serialized field",
        pattern=(
            r"(?is)(?:<\s*/?\s*(?:analysis|thinking|reasoning|"
            r"chain[_ -]?of[_ -]?thought)\s*>|"
            r"(?:chain[_ -]?of[_ -]?thought|hidden[_ -]?reasoning|"
            r"private[_ -]?reasoning)\s*[:=])"
        ),
        surfaces=frozenset({ContentSurface.WORKING_MEMORY}),
    ),
    ContentSafetyRule(
        rule_id="working_memory_raw_exception",
        description="raw exception or stack trace projection",
        pattern=(
            r"(?im)(?:^|\n)\s*(?:Traceback \(most recent call last\):|"
            r"Exception in thread\b|Caused by:\s+|"
            r"[A-Za-z_][A-Za-z0-9_.]*(?:Error|Exception):\s+\S)"
        ),
        surfaces=frozenset({ContentSurface.WORKING_MEMORY}),
    ),
)

WORKING_MEMORY_MAX_DEPTH = 12
WORKING_MEMORY_FORBIDDEN_FIELDS: frozenset[str] = frozenset(
    {
        "access_token",
        "api_key",
        "approval",
        "authorization",
        "capabilities",
        "capability",
        "capability_handle",
        "chain_of_thought",
        "client_secret",
        "cookie",
        "credential",
        "exception",
        "hidden_reasoning",
        "messages",
        "password",
        "payload",
        "policy_decision",
        "private_key",
        "prompt",
        "provider_session",
        "provider_session_id",
        "raw",
        "raw_exception",
        "reasoning",
        "refresh_token",
        "role",
        "roles",
        "scope",
        "scopes",
        "secret",
        "security_context",
        "security_context_ref",
        "session_token",
        "stack_trace",
        "tool_arguments",
        "tool_output",
        "token",
        "traceback",
        "user_token",
        "workload_token",
    }
)
_WORKING_MEMORY_FORBIDDEN_SUFFIXES: tuple[str, ...] = tuple(
    f"_{field}" for field in sorted(WORKING_MEMORY_FORBIDDEN_FIELDS)
)

_COMPILED_RULES: tuple[tuple[ContentSafetyRule, re.Pattern[str]], ...] = tuple(
    (rule, re.compile(rule.pattern))
    for rule in (*PROMPT_INJECTION_RULES, *WORKING_MEMORY_RULES)
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


def _normalized_field_name(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", value.casefold()).strip("_")


def _working_memory_field_is_forbidden(value: str) -> bool:
    normalized = _normalized_field_name(value)
    return normalized in WORKING_MEMORY_FORBIDDEN_FIELDS or normalized.endswith(
        _WORKING_MEMORY_FORBIDDEN_SUFFIXES
    )


def _working_memory_safe_root_path(field: str) -> str:
    root = _safe_root_path(field)
    if root == "$" or _working_memory_field_is_forbidden(field):
        return "$"
    if any(
        ContentSurface.WORKING_MEMORY in rule.surfaces
        and pattern.search(field) is not None
        for rule, pattern in _COMPILED_RULES
    ):
        return "$"
    return root


def _scan_working_memory_structure(
    value: object,
    *,
    field: str,
    policy_checks: bool = True,
) -> tuple[ContentFinding, ...]:
    root = _working_memory_safe_root_path(field)
    findings: list[ContentFinding] = []
    seen: set[int] = set()
    stack: list[tuple[object, str, int]] = [(value, root, 0)]
    while stack:
        current, path, depth = stack.pop()
        if depth > WORKING_MEMORY_MAX_DEPTH:
            findings.append(
                ContentFinding(
                    "working_memory_nesting_limit",
                    path,
                    ContentSurface.WORKING_MEMORY,
                )
            )
            continue
        if isinstance(current, str):
            if policy_checks:
                findings.extend(
                    ContentFinding(rule.rule_id, path, ContentSurface.WORKING_MEMORY)
                    for rule, pattern in _COMPILED_RULES
                    if ContentSurface.WORKING_MEMORY in rule.surfaces
                    and pattern.search(current) is not None
                )
            continue
        if current is None or isinstance(current, (bool, int, float)):
            continue
        if isinstance(current, Mapping):
            identity = id(current)
            if identity in seen:
                findings.append(
                    ContentFinding(
                        "working_memory_cycle",
                        path,
                        ContentSurface.WORKING_MEMORY,
                    )
                )
                continue
            seen.add(identity)
            try:
                items = tuple(current.items())
            except Exception:
                findings.append(
                    ContentFinding(
                        "working_memory_unreadable_container",
                        path,
                        ContentSurface.WORKING_MEMORY,
                    )
                )
                continue
            for index in range(len(items) - 1, -1, -1):
                key, child = items[index]
                key_path = f"{path}.keys[{index}]"
                if not isinstance(key, str):
                    findings.append(
                        ContentFinding(
                            "working_memory_non_string_field",
                            key_path,
                            ContentSurface.WORKING_MEMORY,
                        )
                    )
                elif policy_checks and _working_memory_field_is_forbidden(key):
                    findings.append(
                        ContentFinding(
                            "working_memory_forbidden_field",
                            key_path,
                            ContentSurface.WORKING_MEMORY,
                        )
                    )
                if policy_checks and isinstance(key, str):
                    stack.append((key, key_path, depth + 1))
                stack.append((child, f"{path}.values[{index}]", depth + 1))
            continue
        if isinstance(current, Sequence) and not isinstance(
            current, (str, bytes, bytearray, memoryview)
        ):
            identity = id(current)
            if identity in seen:
                findings.append(
                    ContentFinding(
                        "working_memory_cycle",
                        path,
                        ContentSurface.WORKING_MEMORY,
                    )
                )
                continue
            seen.add(identity)
            try:
                items = tuple(current)
            except Exception:
                findings.append(
                    ContentFinding(
                        "working_memory_unreadable_container",
                        path,
                        ContentSurface.WORKING_MEMORY,
                    )
                )
                continue
            for index in range(len(items) - 1, -1, -1):
                stack.append((items[index], f"{path}[{index}]", depth + 1))
            continue
        findings.append(
            ContentFinding(
                "working_memory_unsupported_type",
                path,
                ContentSurface.WORKING_MEMORY,
            )
        )
    return tuple(findings)


def scan_working_memory_content(
    value: object,
    *,
    field: str = "working_memory",
) -> tuple[ContentFinding, ...]:
    """Find unsafe memory structure or text without retaining original content."""

    safe_field = _working_memory_safe_root_path(field)
    return _scan_working_memory_structure(value, field=safe_field)


def assert_content_safe(
    value: object,
    *,
    surface: ContentSurface,
    field: str = "content",
) -> None:
    safe_field = (
        _working_memory_safe_root_path(field)
        if surface is ContentSurface.WORKING_MEMORY
        else field
    )
    if surface is ContentSurface.WORKING_MEMORY:
        preflight_findings = _scan_working_memory_structure(
            value,
            field=safe_field,
            policy_checks=False,
        )
        if preflight_findings:
            preflight_finding = preflight_findings[0]
            raise SecurityError(
                SecurityErrorCode.WORKING_MEMORY_BLOCKED,
                (
                    "working memory content blocked at "
                    f"{preflight_finding.path} ({preflight_finding.rule_id})"
                ),
            )
    secret_findings = scan_secret_material(value, field=safe_field)
    if secret_findings:
        secret_finding = secret_findings[0]
        raise SecurityError(
            SecurityErrorCode.DLP_BLOCKED,
            (
                "DLP blocked secret-like material at "
                f"{secret_finding.path} ({secret_finding.family_id})"
            ),
        )
    if surface is ContentSurface.WORKING_MEMORY:
        memory_findings = scan_working_memory_content(value, field=safe_field)
        if memory_findings:
            memory_finding = memory_findings[0]
            raise SecurityError(
                SecurityErrorCode.WORKING_MEMORY_BLOCKED,
                (
                    "working memory content blocked at "
                    f"{memory_finding.path} ({memory_finding.rule_id})"
                ),
            )
        return
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


def assert_working_memory_safe(
    value: object,
    *,
    field: str = "working_memory",
) -> None:
    """Fail closed for every task-local working-memory lifecycle boundary."""

    assert_content_safe(
        value,
        surface=ContentSurface.WORKING_MEMORY,
        field=field,
    )
