from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from emporio.auth import UserRole

FailureCategory = Literal[
    "catalog_grounding",
    "availability_boundary",
    "payment_and_shipping_math",
    "scope_boundary",
    "lgpd_verification",
    "policy_grounding",
    "tool_failure_honesty",
    "role_isolation",
    "guardrail_safety",
]

BinaryVerdict = Literal["PASS", "FAIL"]


class TurnExpectation(BaseModel):
    model_config = ConfigDict(frozen=True)

    required_tools: list[str] = Field(default_factory=list)
    forbidden_tools: list[str] = Field(default_factory=list)
    required_tool_args: dict[str, dict[str, Any]] = Field(default_factory=dict)
    must_contain_all: list[str] = Field(default_factory=list)
    must_contain_any: list[str] = Field(default_factory=list)
    must_not_contain: list[str] = Field(default_factory=list)
    forbid_emojis: bool = True
    min_chars: int = 20


class EvalTurn(BaseModel):
    model_config = ConfigDict(frozen=True)

    user_message: str
    expect: TurnExpectation = Field(default_factory=TurnExpectation)


class EvalCase(BaseModel):
    model_config = ConfigDict(frozen=True)

    case_id: str
    category: FailureCategory
    description: str
    rubric: str
    turns: list[EvalTurn]
    load_csvs: bool = True
    load_pdf: bool = True
    user_role: UserRole = "customer"
    enabled_tools: list[str] | None = None
    reference_time_iso: str | None = None


class CheckResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    name: str
    passed: bool
    detail: str


class TurnRecord(BaseModel):
    model_config = ConfigDict(frozen=True)

    turn_index: int
    user_message: str
    assistant_response: str
    observed_tools: list[dict[str, Any]]
    latency_ms: int
    checks: list[CheckResult]
    passed: bool


class JudgeVerdict(BaseModel):
    model_config = ConfigDict(frozen=True)

    verdict: BinaryVerdict
    reason: str
    failure_category: FailureCategory | None = None


class CaseRunResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    case_id: str
    category: FailureCategory
    model: str
    turns: list[TurnRecord]
    deterministic_passed: bool
    total_latency_ms: int
    judge_verdict: JudgeVerdict | None = None


class HumanLabel(BaseModel):
    model_config = ConfigDict(frozen=True)

    label_id: str
    case_id: str
    category: FailureCategory
    rubric: str
    user_turns: list[str]
    observed_tools: list[dict[str, Any]]
    assistant_response: str
    human_verdict: BinaryVerdict
    notes: str


class AlignmentDisagreement(BaseModel):
    model_config = ConfigDict(frozen=True)

    label_id: str
    case_id: str
    human_verdict: BinaryVerdict
    judge_verdict: BinaryVerdict
    human_notes: str
    judge_reason: str


class AlignmentReport(BaseModel):
    model_config = ConfigDict(frozen=True)

    total: int
    tp: int
    tn: int
    fp: int
    fn: int
    agreement: float
    tpr: float
    tnr: float
    cohens_kappa: float
    disagreements: list[AlignmentDisagreement] = Field(default_factory=list)
