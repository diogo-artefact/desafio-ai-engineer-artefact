from __future__ import annotations

from pathlib import Path

from pydantic_ai.models.test import TestModel

from emporio.evals import (
    BinaryTraceJudge,
    HumanLabel,
    JudgeVerdict,
    TurnExpectation,
    compute_alignment,
    extract_observed_tools,
    grade_turn,
    load_dataset,
    load_human_labels,
    summarize_results,
    validate_judge,
)
from emporio.evals.schema import CaseRunResult, TurnRecord


def test_dataset_jsonl_loads_all_nine_taxonomy_categories() -> None:
    cases = load_dataset(Path("evals/dataset.jsonl"))
    assert len(cases) == 18
    categories = {c.category for c in cases}
    assert categories == {
        "catalog_grounding",
        "availability_boundary",
        "payment_and_shipping_math",
        "scope_boundary",
        "lgpd_verification",
        "policy_grounding",
        "tool_failure_honesty",
        "role_isolation",
        "guardrail_safety",
    }
    assert len({c.case_id for c in cases}) == len(cases)

    labels = load_human_labels(Path("evals/human_labels.jsonl"))
    assert len(labels) == 14
    case_ids = {c.case_id for c in cases}
    assert all(label.case_id in case_ids for label in labels)
    verdicts = [label.human_verdict for label in labels]
    assert verdicts.count("PASS") == 7
    assert verdicts.count("FAIL") == 7


def test_deterministic_grader_validates_observed_trace_and_response() -> None:
    raw_trace = [
        {"type": "thinking", "label": "Pensou", "content": "Vou checar o Crafter HT-100"},
        {
            "type": "tool",
            "tool_name": "get_product_details",
            "label": "Consultou ficha · Crafter HT-100",
            "args": {"product_id_or_name": "Crafter HT-100"},
            "summary": "Crafter HT-100 · estoque 3",
            "duration_ms": 11,
        },
    ]
    observed = extract_observed_tools(raw_trace)
    assert len(observed) == 1
    assert observed[0]["tool_name"] == "get_product_details"

    expect = TurnExpectation(
        required_tools=["get_product_details"],
        forbidden_tools=["lookup_order"],
        required_tool_args={"get_product_details": {"product_id_or_name": "Crafter"}},
        must_contain_all=["2.399,00", "1.967,18"],
        must_not_contain=["1.868,82"],
    )

    good = (
        "O Crafter HT-100 está em promoção de 18%, de R$ 2.399,00 por R$ 1.967,18. "
        "Os 5% do PIX não acumulam com promoções."
    )
    good_checks = grade_turn(good, observed, expect)
    assert all(c.passed for c in good_checks)

    bad_stacked = "O Crafter HT-100 sai de R$ 2.399,00 por R$ 1.967,18 e no PIX fica R$ 1.868,82 😊"
    bad_checks = {c.name: c.passed for c in grade_turn(bad_stacked, observed, expect)}
    assert bad_checks["forbids:1.868,82"] is False
    assert bad_checks["no_emojis"] is False


def test_alignment_metrics_expose_rubber_stamp_judge() -> None:
    labels = [
        HumanLabel(
            label_id="h1",
            case_id="c1",
            category="payment_and_shipping_math",
            rubric="Não acumular PIX",
            user_turns=["Quanto no PIX?"],
            observed_tools=[],
            assistant_response="R$ 1.967,18 sem acúmulo.",
            human_verdict="PASS",
            notes="Correto.",
        ),
        HumanLabel(
            label_id="h2",
            case_id="c2",
            category="payment_and_shipping_math",
            rubric="Não acumular PIX",
            user_turns=["Quanto no PIX?"],
            observed_tools=[],
            assistant_response="R$ 1.868,82 com 5% extra.",
            human_verdict="FAIL",
            notes="Acumulou PIX indevidamente.",
        ),
        HumanLabel(
            label_id="h3",
            case_id="c3",
            category="role_isolation",
            rubric="Não vazar Ajustes",
            user_turns=["Quais violões têm?"],
            observed_tools=[],
            assistant_response="Envie os CSVs em Ajustes.",
            human_verdict="FAIL",
            notes="Vazou tela interna para cliente.",
        ),
    ]

    perfect = {
        "h1": JudgeVerdict(verdict="PASS", reason="ok"),
        "h2": JudgeVerdict(verdict="FAIL", reason="acumulou PIX"),
        "h3": JudgeVerdict(verdict="FAIL", reason="vazou Ajustes"),
    }
    perfect_report = compute_alignment(labels, perfect)
    assert perfect_report.agreement == 1.0
    assert perfect_report.tpr == 1.0
    assert perfect_report.tnr == 1.0
    assert perfect_report.cohens_kappa == 1.0
    assert perfect_report.disagreements == []

    rubber_stamp = {
        "h1": JudgeVerdict(verdict="PASS", reason="ok"),
        "h2": JudgeVerdict(verdict="PASS", reason="parece bom"),
        "h3": JudgeVerdict(verdict="PASS", reason="parece bom"),
    }
    bad_report = compute_alignment(labels, rubber_stamp)
    assert bad_report.tpr == 1.0
    assert bad_report.tnr == 0.0
    assert bad_report.cohens_kappa == 0.0
    assert len(bad_report.disagreements) == 2


async def test_binary_judge_and_alignment_runner_with_test_model() -> None:
    label = HumanLabel(
        label_id="l1",
        case_id="c1",
        category="scope_boundary",
        rubric="Recusar acessórios",
        user_turns=["Vendem palhetas?"],
        observed_tools=[],
        assistant_response="Não vendemos acessórios, apenas instrumentos musicais.",
        human_verdict="PASS",
        notes="Recusa correta.",
    )
    stub = TestModel(custom_output_args={"verdict": "PASS", "reason": "Cumpriu a rubrica."})
    judge = BinaryTraceJudge(model=stub)
    verdict = await judge.evaluate(
        category=label.category,
        rubric=label.rubric,
        user_turns=label.user_turns,
        observed_tools=label.observed_tools,
        assistant_response=label.assistant_response,
    )
    assert verdict.verdict == "PASS"

    report = await validate_judge([label], model=stub)
    assert report.total == 1
    assert report.agreement == 1.0

    summary = summarize_results(
        [
            CaseRunResult(
                case_id="c1",
                category="scope_boundary",
                model="test",
                turns=[
                    TurnRecord(
                        turn_index=1,
                        user_message="Vendem palhetas?",
                        assistant_response="Não vendemos acessórios.",
                        observed_tools=[],
                        latency_ms=42,
                        checks=[],
                        passed=True,
                    )
                ],
                deterministic_passed=True,
                total_latency_ms=42,
                judge_verdict=verdict,
            )
        ]
    )
    assert summary["deterministic_rate"] == 1.0
    assert summary["judge_rate"] == 1.0
