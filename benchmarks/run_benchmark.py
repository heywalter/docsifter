#!/usr/bin/env python3
"""Benchmark runner for the DocSifter review engine.

Evaluates the review pipeline against the annotated corpus in cases.json and
reports precision/recall per category.

Usage:
    python3 benchmarks/run_benchmark.py                 # rule-preview path
    python3 benchmarks/run_benchmark.py --model NAME    # local small-model path
    python3 benchmarks/run_benchmark.py --backend ollama \
        --base-url http://127.0.0.1:11434 --model qwen2.5:1.5b
    python3 benchmarks/run_benchmark.py --json out.json # also write JSON results
"""

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

# Allow running from a source checkout without installing the package.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from docsifter.config import ConfigManager  # noqa: E402
from docsifter.corrector import (  # noqa: E402
    ModelExecutionError,
    ModelReviewError,
    TextCorrector,
)


def load_cases(cases_file: Path) -> list:
    with open(cases_file, encoding="utf-8") as f:
        data = json.load(f)
    return data["cases"]


def build_corrector(
    model_name: str | None,
    backend: str | None = None,
    base_url: str | None = None,
) -> TextCorrector:
    config = ConfigManager().get_default_config()
    if model_name:
        config["ai_correction_enabled"] = True
        config["default_model"] = model_name
        config["model_backend"] = backend or "local"
        if base_url:
            if config["model_backend"] == "ollama":
                config["ollama_base_url"] = base_url
            else:
                # OpenAI-compatible endpoint; the key comes from OPENAI_API_KEY.
                config["openai_base_url"] = base_url
    corrector = TextCorrector(config)
    if model_name:
        # Fail the benchmark instead of silently downgrading to rules-only.
        if not corrector.init_corrector(model_name):
            raise SystemExit(
                f"Benchmark aborted: model '{model_name}' could not be initialized. "
                'Install it with pip install "docsifter[model]", or omit --model.'
            )
    return corrector


def evaluate(corrector: TextCorrector, cases: list) -> dict:
    stats = defaultdict(lambda: {"tp": 0, "fp": 0, "fn": 0, "tn": 0})
    failures = []

    for case in cases:
        category = case["category"]
        expected = case["expected"]
        needs_fix = expected != case["text"]

        try:
            corrected = corrector.correct_text(case["text"])
        except ModelExecutionError as exc:
            # One unreachable case must not abort the whole benchmark run.
            failures.append({"case": case, "got": str(exc), "kind": "error"})
            if needs_fix:
                stats[category]["fn"] += 1
            continue

        if not needs_fix:
            if corrected is None:
                stats[category]["tn"] += 1
            else:
                stats[category]["fp"] += 1
                failures.append({"case": case, "got": corrected, "kind": "false-positive"})
            continue

        if corrected == expected:
            stats[category]["tp"] += 1
        elif corrected is None:
            stats[category]["fn"] += 1
            failures.append({"case": case, "got": None, "kind": "missed"})
        else:
            stats[category]["fp"] += 1
            stats[category]["fn"] += 1
            failures.append({"case": case, "got": corrected, "kind": "wrong-fix"})

    return {"stats": dict(stats), "failures": failures}


def precision_recall(entry: dict) -> tuple:
    tp, fp, fn = entry["tp"], entry["fp"], entry["fn"]
    precision = tp / (tp + fp) if (tp + fp) else None
    recall = tp / (tp + fn) if (tp + fn) else None
    return precision, recall


def f1(precision: float | None, recall: float | None) -> float | None:
    if precision is None or recall is None or (precision + recall) == 0:
        return None
    return 2 * precision * recall / (precision + recall)


def fmt(value: float | None) -> str:
    return f"{value:.1%}" if value is not None else "n/a"


def print_report(results: dict, mode: str) -> dict:
    print(f"\nDocSifter benchmark — mode: {mode}")
    print("-" * 64)
    print(f"{'category':<14}{'precision':>12}{'recall':>10}{'f1':>8}{'cases':>8}")
    print("-" * 64)

    totals = {"tp": 0, "fp": 0, "fn": 0, "tn": 0}
    for category in sorted(results["stats"]):
        entry = results["stats"][category]
        for key in totals:
            totals[key] += entry[key]
        precision, recall = precision_recall(entry)
        count = entry["tp"] + entry["fp"] + entry["fn"] + entry["tn"]
        print(
            f"{category:<14}{fmt(precision):>12}{fmt(recall):>10}"
            f"{fmt(f1(precision, recall)):>8}{count:>8}"
        )

    overall_p, overall_r = precision_recall(totals)
    total_cases = sum(totals.values())
    print("-" * 64)
    print(
        f"{'OVERALL':<14}{fmt(overall_p):>12}{fmt(overall_r):>10}"
        f"{fmt(f1(overall_p, overall_r)):>8}{total_cases:>8}\n"
    )

    if results["failures"]:
        print(f"{len(results['failures'])} failure(s):")
        for failure in results["failures"]:
            case = failure["case"]
            print(f"  [{failure['kind']}] {case['text']}")
            print(f"      expected: {case['expected']}")
            print(f"      got:      {failure['got']}")

    summary = {
        "mode": mode,
        "overall": {
            "precision": overall_p,
            "recall": overall_r,
            "f1": f1(overall_p, overall_r),
        },
        "per_category": {
            category: {
                **entry,
                "precision": precision_recall(entry)[0],
                "recall": precision_recall(entry)[1],
                "f1": f1(*precision_recall(entry)),
            }
            for category, entry in results["stats"].items()
        },
        "failures": [
            {
                "kind": failure["kind"],
                "text": failure["case"]["text"],
                "expected": failure["case"]["expected"],
                "got": failure["got"],
            }
            for failure in results["failures"]
        ],
    }
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", help="correction model name/id")
    parser.add_argument(
        "--backend",
        choices=("local", "ollama", "openai"),
        default=None,
        help="model backend to score (default: local)",
    )
    parser.add_argument(
        "--base-url",
        dest="base_url",
        help="override the Ollama/OpenAI-compatible endpoint URL",
    )
    parser.add_argument("--json", dest="json_out", help="write machine-readable results")
    parser.add_argument(
        "--cases",
        type=Path,
        default=Path(__file__).resolve().parent / "cases.json",
        help="path to the annotated corpus",
    )
    args = parser.parse_args()

    try:
        corrector = build_corrector(args.model, args.backend, args.base_url)
    except ModelReviewError as exc:
        raise SystemExit(f"Benchmark aborted: {exc}") from exc

    cases = load_cases(args.cases)
    results = evaluate(corrector, cases)
    mode = f"{args.backend or 'local'}:{args.model}" if args.model else "rule-preview"
    summary = print_report(results, mode=mode)

    if args.json_out:
        Path(args.json_out).write_text(
            json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(f"Results written to {args.json_out}")

    return check_invariants(summary, model_mode=bool(args.model))


def check_invariants(summary: dict, model_mode: bool) -> int:
    """Fail on the two things that must never regress.

    The corpus is too small to gate on an accuracy figure, but these two hold
    regardless of sample size: a negative sample must survive, and a rule is
    deterministic so it either fixes a case correctly or leaves it alone. Model
    runs are advisory — a model may legitimately get a case wrong — so only the
    protection invariant applies there.
    """
    violations = []

    protection = summary["per_category"].get("protection", {})
    if protection.get("fp"):
        for failure in summary["failures"]:
            if failure["kind"] != "missed":
                violations.append(f"protection sample modified: {failure['text']}")

    if not model_mode:
        wrong = [f for f in summary["failures"] if f["kind"] == "wrong-fix"]
        for failure in wrong:
            violations.append(f"rule produced a wrong fix: {failure['text']} -> {failure['got']}")

    if violations:
        print("\nBenchmark invariants violated:")
        for violation in violations:
            print(f"  - {violation}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
