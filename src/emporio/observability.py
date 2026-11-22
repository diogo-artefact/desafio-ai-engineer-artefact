from __future__ import annotations

import json
import logging
import math

from emporio.domain.models import TurnTelemetry

telemetry_logger = logging.getLogger("emporio.telemetry")
telemetry_logger.setLevel(logging.INFO)


def configure_telemetry_logging() -> None:
    if telemetry_logger.handlers:
        return
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(message)s"))
    telemetry_logger.addHandler(handler)


def percentile_ms(values: list[int], pct: float) -> int:
    if not values:
        return 0
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, math.ceil((pct / 100.0) * len(ordered)) - 1))
    return int(ordered[index])


def log_turn_event(entry: TurnTelemetry) -> None:
    payload = {
        "event": "chat_turn",
        "model": entry.model,
        "user_role": entry.user_role,
        "outcome": entry.outcome,
        "guardrail_action": entry.guardrail_action,
        "guardrail_ms": entry.guardrail_ms,
        "total_ms": entry.total_ms,
        "tool_count": entry.tool_count,
        "tools_called": entry.tools_called,
        "input_tokens": entry.input_tokens,
        "output_tokens": entry.output_tokens,
        "created_at": entry.created_at,
    }
    telemetry_logger.info(json.dumps(payload, ensure_ascii=False, separators=(",", ":")))
