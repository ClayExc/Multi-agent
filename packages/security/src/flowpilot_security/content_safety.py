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
        "analysis",
        "api_key",
        "approval",
        "approvals",
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
        "thinking",
        "tool_arguments",
        "tool_output",
        "token",
        "traceback",
        "user_token",
        "workload_token",
    }
)
WORKING_MEMORY_FORBIDDEN_FIELD_FAMILIES: frozenset[str] = frozenset(
    {
        "analysis",
        "approval",
        "approvals",
        "authorization",
        "capabilities",
        "capability",
        "chain_of_thought",
        "hidden_reasoning",
        "policy_decision",
        "private_reasoning",
        "provider_session",
        "reasoning",
        "role",
        "roles",
        "scope",
        "scopes",
        "security_context",
        "thinking",
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
    if surface is ContentSurface.WORKING_MEMORY:
        rule_ids = {
            rule.rule_id
            for rule, _pattern in _COMPILED_RULES
            if surface in rule.surfaces
        }
        return tuple(
            finding
            for finding in _inspect_working_memory(value, field=field).findings
            if finding.rule_id in rule_ids
        )
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
    padded = f"_{normalized}_"
    return (
        normalized in WORKING_MEMORY_FORBIDDEN_FIELDS
        or normalized.endswith(_WORKING_MEMORY_FORBIDDEN_SUFFIXES)
        or any(
            f"_{family}_" in padded
            for family in WORKING_MEMORY_FORBIDDEN_FIELD_FAMILIES
        )
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


@dataclass(frozen=True, slots=True)
class _WorkingMemoryInspection:
    snapshot: object
    findings: tuple[ContentFinding, ...]


def _working_memory_text_findings(
    value: str,
    *,
    path: str,
) -> tuple[ContentFinding, ...]:
    return tuple(
        ContentFinding(rule.rule_id, path, ContentSurface.WORKING_MEMORY)
        for rule, pattern in _COMPILED_RULES
        if ContentSurface.WORKING_MEMORY in rule.surfaces
        and pattern.search(value) is not None
    )


def _snapshot_working_memory_value(
    value: object,
    *,
    path: str,
    depth: int,
    ancestors: frozenset[int],
    memo: dict[int, _WorkingMemoryInspection],
) -> _WorkingMemoryInspection:
    if depth > WORKING_MEMORY_MAX_DEPTH:
        return _WorkingMemoryInspection(
            snapshot=None,
            findings=(
                ContentFinding(
                    "working_memory_nesting_limit",
                    path,
                    ContentSurface.WORKING_MEMORY,
                ),
            ),
        )
    if isinstance(value, str):
        return _WorkingMemoryInspection(snapshot=value, findings=())
    if value is None or isinstance(value, (bool, int, float)):
        return _WorkingMemoryInspection(snapshot=value, findings=())
    if isinstance(value, Mapping):
        identity = id(value)
        if identity in ancestors:
            return _WorkingMemoryInspection(
                snapshot=None,
                findings=(
                    ContentFinding(
                        "working_memory_cycle",
                        path,
                        ContentSurface.WORKING_MEMORY,
                    ),
                ),
            )
        if identity in memo:
            return memo[identity]
        try:
            items = tuple(value.items())
        except Exception:
            inspection = _WorkingMemoryInspection(
                snapshot=None,
                findings=(
                    ContentFinding(
                        "working_memory_unreadable_container",
                        path,
                        ContentSurface.WORKING_MEMORY,
                    ),
                ),
            )
            memo[identity] = inspection
            return inspection
        child_ancestors = ancestors | {identity}
        snapshot: dict[str, object] = {}
        findings: list[ContentFinding] = []
        for index, (key, child) in enumerate(items):
            key_path = f"{path}.keys[{index}]"
            child_path = f"{path}.values[{index}]"
            if type(key) is not str:
                findings.append(
                    ContentFinding(
                        "working_memory_non_string_field",
                        key_path,
                        ContentSurface.WORKING_MEMORY,
                    )
                )
            else:
                if key in snapshot:
                    findings.append(
                        ContentFinding(
                            "working_memory_duplicate_field",
                            key_path,
                            ContentSurface.WORKING_MEMORY,
                        )
                    )
            child_inspection = _snapshot_working_memory_value(
                child,
                path=child_path,
                depth=depth + 1,
                ancestors=child_ancestors,
                memo=memo,
            )
            findings.extend(child_inspection.findings)
            if type(key) is str:
                snapshot[key] = child_inspection.snapshot
        inspection = _WorkingMemoryInspection(
            snapshot=snapshot,
            findings=tuple(findings),
        )
        memo[identity] = inspection
        return inspection
    if isinstance(value, Sequence) and not isinstance(
        value, (str, bytes, bytearray, memoryview)
    ):
        identity = id(value)
        if identity in ancestors:
            return _WorkingMemoryInspection(
                snapshot=None,
                findings=(
                    ContentFinding(
                        "working_memory_cycle",
                        path,
                        ContentSurface.WORKING_MEMORY,
                    ),
                ),
            )
        if identity in memo:
            return memo[identity]
        try:
            items = tuple(value)
        except Exception:
            inspection = _WorkingMemoryInspection(
                snapshot=None,
                findings=(
                    ContentFinding(
                        "working_memory_unreadable_container",
                        path,
                        ContentSurface.WORKING_MEMORY,
                    ),
                ),
            )
            memo[identity] = inspection
            return inspection
        child_ancestors = ancestors | {identity}
        snapshot_items: list[object] = []
        findings = []
        for index, child in enumerate(items):
            child_inspection = _snapshot_working_memory_value(
                child,
                path=f"{path}[{index}]",
                depth=depth + 1,
                ancestors=child_ancestors,
                memo=memo,
            )
            findings.extend(child_inspection.findings)
            snapshot_items.append(child_inspection.snapshot)
        inspection = _WorkingMemoryInspection(
            snapshot=tuple(snapshot_items),
            findings=tuple(findings),
        )
        memo[identity] = inspection
        return inspection
    return _WorkingMemoryInspection(
        snapshot=None,
        findings=(
            ContentFinding(
                "working_memory_unsupported_type",
                path,
                ContentSurface.WORKING_MEMORY,
            ),
        ),
    )


def _inspect_working_memory_snapshot(
    value: object,
    *,
    path: str,
    depth: int,
    ancestors: frozenset[int],
) -> tuple[ContentFinding, ...]:
    if depth > WORKING_MEMORY_MAX_DEPTH:
        return (
            ContentFinding(
                "working_memory_nesting_limit",
                path,
                ContentSurface.WORKING_MEMORY,
            ),
        )
    if isinstance(value, str):
        return _working_memory_text_findings(value, path=path)
    if value is None or isinstance(value, (bool, int, float)):
        return ()
    if isinstance(value, dict):
        identity = id(value)
        if identity in ancestors:
            return (
                ContentFinding(
                    "working_memory_cycle",
                    path,
                    ContentSurface.WORKING_MEMORY,
                ),
            )
        child_ancestors = ancestors | {identity}
        findings: list[ContentFinding] = []
        for index, (key, child) in enumerate(value.items()):
            key_path = f"{path}.keys[{index}]"
            if _working_memory_field_is_forbidden(key):
                findings.append(
                    ContentFinding(
                        "working_memory_forbidden_field",
                        key_path,
                        ContentSurface.WORKING_MEMORY,
                    )
                )
            findings.extend(_working_memory_text_findings(key, path=key_path))
            findings.extend(
                _inspect_working_memory_snapshot(
                    child,
                    path=f"{path}.values[{index}]",
                    depth=depth + 1,
                    ancestors=child_ancestors,
                )
            )
        return tuple(findings)
    if isinstance(value, tuple):
        identity = id(value)
        if identity in ancestors:
            return (
                ContentFinding(
                    "working_memory_cycle",
                    path,
                    ContentSurface.WORKING_MEMORY,
                ),
            )
        child_ancestors = ancestors | {identity}
        findings = []
        for index, child in enumerate(value):
            findings.extend(
                _inspect_working_memory_snapshot(
                    child,
                    path=f"{path}[{index}]",
                    depth=depth + 1,
                    ancestors=child_ancestors,
                )
            )
        return tuple(findings)
    return (
        ContentFinding(
            "working_memory_unsupported_type",
            path,
            ContentSurface.WORKING_MEMORY,
        ),
    )


def _inspect_working_memory(value: object, *, field: str) -> _WorkingMemoryInspection:
    root = _working_memory_safe_root_path(field)
    snapshot = _snapshot_working_memory_value(
        value,
        path=root,
        depth=0,
        ancestors=frozenset(),
        memo={},
    )
    policy_findings = _inspect_working_memory_snapshot(
        snapshot.snapshot,
        path=root,
        depth=0,
        ancestors=frozenset(),
    )
    return _WorkingMemoryInspection(
        snapshot=snapshot.snapshot,
        findings=(*snapshot.findings, *policy_findings),
    )


def scan_working_memory_content(
    value: object,
    *,
    field: str = "working_memory",
) -> tuple[ContentFinding, ...]:
    """Find unsafe memory structure or text without retaining original content."""

    return _inspect_working_memory(value, field=field).findings


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
    memory_inspection = (
        _inspect_working_memory(value, field=safe_field)
        if surface is ContentSurface.WORKING_MEMORY
        else None
    )
    inspected_value = (
        memory_inspection.snapshot if memory_inspection is not None else value
    )
    secret_findings = scan_secret_material(inspected_value, field=safe_field)
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
        assert memory_inspection is not None
        if memory_inspection.findings:
            memory_finding = memory_inspection.findings[0]
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
