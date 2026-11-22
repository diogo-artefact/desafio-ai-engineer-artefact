from __future__ import annotations

import argparse
import asyncio
import statistics
import tempfile
import time
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic_ai.models import Model

from emporio.agent import ALLOWED_MODEL_IDS, DEFAULT_MODEL_ID
from emporio.api import AppContainer
from emporio.etl.embeddings import Embedder, get_default_embedder
from emporio.etl.loader import ingest_policy_pdf, ingest_store_csvs
from emporio.evals.graders import extract_observed_tools, grade_turn
from emporio.evals.judge import BinaryTraceJudge, compute_alignment
from emporio.evals.schema import (
    AlignmentReport,
    CaseRunResult,
    EvalCase,
    HumanLabel,
    JudgeVerdict,
    TurnRecord,
)

DEFAULT_DATASET_PATH = Path("evals/dataset.jsonl")
DEFAULT_LABELS_PATH = Path("evals/human_labels.jsonl")
DEFAULT_RAW_DIR = Path("data/raw")


def load_dataset(path: Path = DEFAULT_DATASET_PATH) -> list[EvalCase]:
    cases: list[EvalCase] = []
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        cases.append(EvalCase.model_validate_json(line))
    return cases


def load_human_labels(path: Path = DEFAULT_LABELS_PATH) -> list[HumanLabel]:
    labels: list[HumanLabel] = []
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        labels.append(HumanLabel.model_validate_json(line))
    return labels


def _read_raw_dir(raw_dir: Path) -> tuple[dict[str, bytes], tuple[str, bytes] | None]:
    csv_files = {p.name: p.read_bytes() for p in sorted(raw_dir.glob("*.csv"))}
    pdfs = sorted(raw_dir.glob("*.pdf"))
    pdf_entry = (pdfs[0].name, pdfs[0].read_bytes()) if pdfs else None
    return csv_files, pdf_entry


def _prepare_db_for_case(
    *,
    db_path: Path,
    raw_csvs: dict[str, bytes],
    raw_pdf: tuple[str, bytes] | None,
    load_csvs: bool,
    load_pdf: bool,
    embedder: Embedder | None,
) -> None:
    if load_csvs:
        ingest_store_csvs(raw_csvs, db_path)
    if load_pdf and raw_pdf is not None:
        pdf_name, pdf_bytes = raw_pdf
        ingest_policy_pdf(pdf_bytes, db_path, filename=pdf_name, embedder=embedder)


async def run_case(
    case: EvalCase,
    *,
    container: AppContainer,
    model_name: str,
    judge: BinaryTraceJudge | None = None,
) -> CaseRunResult:
    reference_time = (
        datetime.fromisoformat(case.reference_time_iso) if case.reference_time_iso else None
    )
    enabled = frozenset(case.enabled_tools) if case.enabled_tools is not None else None
    session_id = f"eval-{case.case_id}"

    turn_records: list[TurnRecord] = []
    total_ms = 0

    for idx, turn in enumerate(case.turns, start=1):
        started = time.perf_counter()
        result = await container.conversations.send_message(
            session_id=session_id,
            message=turn.user_message,
            enabled_tools=enabled,
            user_role=case.user_role,
            reference_time=reference_time,
        )
        elapsed_ms = int((time.perf_counter() - started) * 1000)
        total_ms += elapsed_ms

        observed = extract_observed_tools(result.trace)
        checks = grade_turn(result.text, observed, turn.expect)
        turn_passed = all(c.passed for c in checks)
        turn_records.append(
            TurnRecord(
                turn_index=idx,
                user_message=turn.user_message,
                assistant_response=result.text,
                observed_tools=observed,
                latency_ms=elapsed_ms,
                checks=checks,
                passed=turn_passed,
            )
        )

    deterministic_passed = all(t.passed for t in turn_records)
    judge_verdict: JudgeVerdict | None = None
    if judge is not None and turn_records:
        all_tools = [step for record in turn_records for step in record.observed_tools]
        judge_verdict = await judge.evaluate(
            category=case.category,
            rubric=case.rubric,
            user_turns=[record.user_message for record in turn_records],
            observed_tools=all_tools,
            assistant_response=turn_records[-1].assistant_response,
        )

    return CaseRunResult(
        case_id=case.case_id,
        category=case.category,
        model=model_name,
        turns=turn_records,
        deterministic_passed=deterministic_passed,
        total_latency_ms=total_ms,
        judge_verdict=judge_verdict,
    )


async def run_suite(
    cases: list[EvalCase],
    *,
    model: str | Model = DEFAULT_MODEL_ID,
    raw_dir: Path = DEFAULT_RAW_DIR,
    embedder: Embedder | None = None,
    with_judge: bool = False,
    judge_model: str | Model | None = None,
) -> list[CaseRunResult]:
    model_name = model if isinstance(model, str) else type(model).__name__
    resolved_embedder = embedder if embedder is not None else get_default_embedder()
    raw_csvs, raw_pdf = _read_raw_dir(raw_dir)
    judge = BinaryTraceJudge(model=judge_model or model) if with_judge else None

    results: list[CaseRunResult] = []
    with tempfile.TemporaryDirectory(prefix="emporio_evals_") as tmp:
        tmp_root = Path(tmp)
        full_db = tmp_root / "full.db"
        _prepare_db_for_case(
            db_path=full_db,
            raw_csvs=raw_csvs,
            raw_pdf=raw_pdf,
            load_csvs=True,
            load_pdf=True,
            embedder=resolved_embedder,
        )
        full_container = AppContainer.build(
            db_path=full_db,
            embedder=resolved_embedder,
            model=model,
        )

        for case in cases:
            if case.load_csvs and case.load_pdf:
                container = full_container
            else:
                case_db = tmp_root / f"{case.case_id}.db"
                _prepare_db_for_case(
                    db_path=case_db,
                    raw_csvs=raw_csvs,
                    raw_pdf=raw_pdf,
                    load_csvs=case.load_csvs,
                    load_pdf=case.load_pdf,
                    embedder=resolved_embedder,
                )
                container = AppContainer.build(
                    db_path=case_db,
                    embedder=resolved_embedder,
                    model=model,
                )

            case_result = await run_case(
                case,
                container=container,
                model_name=model_name,
                judge=judge,
            )
            results.append(case_result)

    return results


async def validate_judge(
    labels: list[HumanLabel],
    *,
    model: str | Model = DEFAULT_MODEL_ID,
) -> AlignmentReport:
    judge = BinaryTraceJudge(model=model)
    verdicts: dict[str, JudgeVerdict] = {}
    for label in labels:
        verdicts[label.label_id] = await judge.evaluate(
            category=label.category,
            rubric=label.rubric,
            user_turns=label.user_turns,
            observed_tools=label.observed_tools,
            assistant_response=label.assistant_response,
        )
    return compute_alignment(labels, verdicts)


def summarize_results(results: list[CaseRunResult]) -> dict[str, Any]:
    total = len(results)
    passed = sum(1 for r in results if r.deterministic_passed)
    latencies = [r.total_latency_ms for r in results]
    by_category: dict[str, dict[str, int]] = defaultdict(lambda: {"passed": 0, "total": 0})
    for r in results:
        by_category[r.category]["total"] += 1
        if r.deterministic_passed:
            by_category[r.category]["passed"] += 1

    summary: dict[str, Any] = {
        "total": total,
        "deterministic_passed": passed,
        "deterministic_rate": round(passed / total, 4) if total else 0.0,
        "median_latency_ms": int(statistics.median(latencies)) if latencies else 0,
        "by_category": dict(by_category),
    }
    judged = [r for r in results if r.judge_verdict is not None]
    if judged:
        j_passed = sum(1 for r in judged if r.judge_verdict and r.judge_verdict.verdict == "PASS")
        summary["judge_passed"] = j_passed
        summary["judge_total"] = len(judged)
        summary["judge_rate"] = round(j_passed / len(judged), 4)
    return summary


def save_run_jsonl(results: list[CaseRunResult], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    lines = [result.model_dump_json() for result in results]
    output_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _print_suite_report(results: list[CaseRunResult]) -> None:
    summary = summarize_results(results)
    print(
        f"\nResumo ({results[0].model if results else 'n/a'}): "
        f"{summary['deterministic_passed']}/{summary['total']} "
        f"({summary['deterministic_rate'] * 100:.1f}%) determinístico | "
        f"latência mediana {summary['median_latency_ms']}ms"
    )
    if "judge_passed" in summary:
        print(
            f"Juiz-LLM: {summary['judge_passed']}/{summary['judge_total']} "
            f"({summary['judge_rate'] * 100:.1f}%)"
        )
    print("\nPor categoria da taxonomia:")
    for category, counts in sorted(summary["by_category"].items()):
        print(f"  - {category}: {counts['passed']}/{counts['total']}")

    failures = [r for r in results if not r.deterministic_passed]
    if failures:
        print("\nFalhas determinísticas:")
        for fail in failures:
            failed_checks = [
                f"T{t.turn_index}:{c.name} ({c.detail})"
                for t in fail.turns
                for c in t.checks
                if not c.passed
            ]
            print(f"  - {fail.case_id} [{fail.category}]: {'; '.join(failed_checks)}")


def _print_alignment_report(report: AlignmentReport) -> None:
    print(
        f"\nAlinhamento do Juiz-LLM ({report.total} rótulos humanos):\n"
        f"  Concordância: {report.agreement * 100:.1f}% "
        f"(TP={report.tp}, TN={report.tn}, FP={report.fp}, FN={report.fn})\n"
        f"  TPR (PASS correto): {report.tpr * 100:.1f}%\n"
        f"  TNR (FAIL detectado): {report.tnr * 100:.1f}%\n"
        f"  Cohen's kappa: {report.cohens_kappa:.3f}"
    )
    if report.disagreements:
        print("\nDivergências para análise de erro:")
        for d in report.disagreements:
            print(
                f"  - {d.label_id} ({d.case_id}): humano={d.human_verdict}, "
                f"juiz={d.judge_verdict} | juiz: {d.judge_reason}"
            )


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Runner de evals do Empório da Música.")
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET_PATH)
    parser.add_argument("--labels", type=Path, default=DEFAULT_LABELS_PATH)
    parser.add_argument("--model", type=str, default=DEFAULT_MODEL_ID)
    parser.add_argument("--judge-model", type=str, default=None)
    parser.add_argument("--case", type=str, default=None)
    parser.add_argument("--with-judge", action="store_true")
    parser.add_argument("--validate-judge", action="store_true")
    parser.add_argument("--output", type=Path, default=None)
    return parser


def main() -> None:
    args = _build_parser().parse_args()
    if args.model not in ALLOWED_MODEL_IDS:
        allowed = ", ".join(sorted(ALLOWED_MODEL_IDS))
        raise SystemExit(f"Modelo inválido '{args.model}'. Use um modelo Gemini 4: {allowed}")

    if args.validate_judge:
        labels = load_human_labels(args.labels)
        report = asyncio.run(validate_judge(labels, model=args.judge_model or args.model))
        _print_alignment_report(report)
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(report.model_dump_json(indent=2) + "\n", encoding="utf-8")
        return

    cases = load_dataset(args.dataset)
    if args.case:
        cases = [c for c in cases if c.case_id == args.case]
        if not cases:
            raise SystemExit(f"Caso '{args.case}' não encontrado em {args.dataset}.")

    results = asyncio.run(
        run_suite(
            cases,
            model=args.model,
            with_judge=args.with_judge,
            judge_model=args.judge_model,
        )
    )
    _print_suite_report(results)

    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    model_slug = args.model.replace(":", "_")
    output_path = args.output or Path(f"evals/runs/{stamp}_{model_slug}.jsonl")
    save_run_jsonl(results, output_path)
    print(f"\nTraces salvos em {output_path}")


if __name__ == "__main__":
    main()
