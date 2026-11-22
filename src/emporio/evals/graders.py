from __future__ import annotations

import re
from typing import Any

from emporio.domain.text import normalize_text
from emporio.evals.schema import CheckResult, TurnExpectation

EMOJI_PATTERN = re.compile(
    "["
    "\U0001f300-\U0001f5ff"
    "\U0001f600-\U0001f64f"
    "\U0001f680-\U0001f6ff"
    "\U0001f700-\U0001f77f"
    "\U0001f900-\U0001f9ff"
    "\U0001fa70-\U0001faff"
    "\u2600-\u26ff"
    "\u2700-\u27bf"
    "]",
    flags=re.UNICODE,
)


def extract_observed_tools(trace: list[dict[str, Any]]) -> list[dict[str, Any]]:
    observed: list[dict[str, Any]] = []
    for step in trace:
        if step.get("type") != "tool":
            continue
        observed.append(
            {
                "tool_name": step.get("tool_name", ""),
                "label": step.get("label", ""),
                "args": step.get("args", {}),
                "summary": step.get("summary", ""),
                "duration_ms": step.get("duration_ms", 0),
            }
        )
    return observed


def _contains_normalized(haystack: str, needle: str) -> bool:
    if needle.lower() in haystack.lower():
        return True
    return normalize_text(needle) in normalize_text(haystack)


def _arg_matches(actual: Any, expected: Any) -> bool:
    if isinstance(expected, (int, float)) and isinstance(actual, (int, float)):
        return float(actual) == float(expected)
    if isinstance(expected, str) and isinstance(actual, str):
        return normalize_text(expected) in normalize_text(actual)
    return actual == expected


def grade_turn(
    response: str,
    observed_tools: list[dict[str, Any]],
    expect: TurnExpectation,
) -> list[CheckResult]:
    checks: list[CheckResult] = []
    called_names = [str(step.get("tool_name", "")) for step in observed_tools]
    called_set = set(called_names)

    clean_response = response.strip()
    checks.append(
        CheckResult(
            name="min_chars",
            passed=len(clean_response) >= expect.min_chars,
            detail=f"len={len(clean_response)}, min={expect.min_chars}",
        )
    )

    if expect.forbid_emojis:
        found_emojis = EMOJI_PATTERN.findall(clean_response)
        checks.append(
            CheckResult(
                name="no_emojis",
                passed=not found_emojis,
                detail="ok" if not found_emojis else f"emojis={found_emojis[:3]}",
            )
        )

    for tool_name in expect.required_tools:
        present = tool_name in called_set
        checks.append(
            CheckResult(
                name=f"required_tool:{tool_name}",
                passed=present,
                detail="called" if present else f"missing (observed={called_names})",
            )
        )

    for tool_name in expect.forbidden_tools:
        absent = tool_name not in called_set
        checks.append(
            CheckResult(
                name=f"forbidden_tool:{tool_name}",
                passed=absent,
                detail="not_called" if absent else f"unexpectedly_called (observed={called_names})",
            )
        )

    for tool_name, expected_args in expect.required_tool_args.items():
        matching_calls = [s for s in observed_tools if s.get("tool_name") == tool_name]
        matched = False
        for call in matching_calls:
            actual_args = call.get("args", {})
            if isinstance(actual_args, dict) and all(
                key in actual_args and _arg_matches(actual_args[key], val)
                for key, val in expected_args.items()
            ):
                matched = True
                break
        checks.append(
            CheckResult(
                name=f"tool_args:{tool_name}",
                passed=matched,
                detail=(
                    f"matched {expected_args}"
                    if matched
                    else f"expected {expected_args}, got {[c.get('args') for c in matching_calls]}"
                ),
            )
        )

    for term in expect.must_contain_all:
        found = _contains_normalized(clean_response, term)
        checks.append(
            CheckResult(
                name=f"contains:{term}",
                passed=found,
                detail="found" if found else f"missing '{term}'",
            )
        )

    if expect.must_contain_any:
        matched_term = next(
            (
                term
                for term in expect.must_contain_any
                if _contains_normalized(clean_response, term)
            ),
            None,
        )
        checks.append(
            CheckResult(
                name="contains_any",
                passed=matched_term is not None,
                detail=(
                    f"matched '{matched_term}'"
                    if matched_term is not None
                    else f"none of {expect.must_contain_any}"
                ),
            )
        )

    for term in expect.must_not_contain:
        absent = not _contains_normalized(clean_response, term)
        checks.append(
            CheckResult(
                name=f"forbids:{term}",
                passed=absent,
                detail="absent" if absent else f"forbidden term '{term}' present",
            )
        )

    return checks
