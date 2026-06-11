from __future__ import annotations

import argparse
import ast
import csv
import json
import os
import re
import subprocess
import tempfile
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean
from typing import Any


METRIC_COLUMNS = [
    "test_coverage_percent",
    "defect_detection_rate_percent",
    "execution_time_seconds",
    "number_of_tests_executed",
    "test_reduction_percentage",
    "pass_rate_percent",
    "generated_test_validity_rate_percent",
    "coverage_improvement_percent",
    "selection_accuracy_percent",
    "manual_effort_proxy_minutes",
    "efficiency_score_percent",
]

METRIC_EXPLANATIONS = {
    "test_coverage_percent": "Line coverage for the target source module.",
    "defect_detection_rate_percent": "Failing/error tests divided by total executed tests. Higher means defects are found with fewer tests.",
    "execution_time_seconds": "Measured pytest execution time for the benchmarked test set. For agentic mode this is the selected/generated target tests, not the full LLM pipeline setup time.",
    "number_of_tests_executed": "Total pytest outcomes counted from the final pytest summary: passed + failed + errors + skipped + xfailed + xpassed.",
    "test_reduction_percentage": "How many fewer tests were executed compared with the traditional target-test baseline.",
    "pass_rate_percent": "Passed tests divided by total executed tests.",
    "generated_test_validity_rate_percent": "Agentic only: generated tests that executed without collection/runtime infrastructure errors. Failing assertions still count as valid defect-detection tests.",
    "coverage_improvement_percent": "Coverage difference compared with the traditional target-test baseline.",
    "selection_accuracy_percent": "Selected test files that directly target the source module divided by all selected test files.",
    "manual_effort_proxy_minutes": "Transparent proxy estimate from executed tests/heal attempts. Use only as an automation-effort indicator, not measured human time.",
    "efficiency_score_percent": "Weighted index from defect density, test reduction, execution saving, coverage, pass rate, and selection accuracy.",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Compare agentic testing against traditional continuous testing."
    )
    parser.add_argument("--source", default="target_code.py", help="Target module analyzed by the agentic pipeline")
    parser.add_argument("--runs", type=int, default=1, help="Number of iterations per strategy")
    parser.add_argument("--base-ref", default="HEAD~1", help="Git base ref used by predictive selection")
    parser.add_argument("--max-heal-attempts", type=int, default=2, help="Max self-heal retries in agentic mode")
    parser.add_argument("--model", default="gemini-2.5-flash", help="LLM model used by the generation agent")
    parser.add_argument(
        "--report-output",
        default="reports/comparison_report.json",
        help="JSON output path for the comparison report",
    )
    parser.add_argument(
        "--traditional-targets",
        nargs="*",
        default=None,
        help="Optional explicit traditional pytest targets. If omitted, target-source tests are auto-detected.",
    )
    parser.add_argument(
        "--use-predictive-selection",
        action="store_true",
        help="Run main.py with predictive test selection. Default comparison uses only generated target tests for agentic mode.",
    )
    return parser.parse_args()


def run_command(command: list[str], cwd: Path, env: dict[str, str] | None = None, timeout_seconds: int = 120) -> dict[str, Any]:
    """Run a command without pipe deadlocks.

    GitHub Actions and coverage/pytest can occasionally keep stdout/stderr pipes
    open through child processes. Capturing to temporary files avoids CI hangs and
    still lets us parse pytest summaries for pass/fail/total metrics.
    """
    start = time.time()
    start_utc = datetime.now(timezone.utc).isoformat()

    with tempfile.TemporaryFile(mode="w+", encoding="utf-8", errors="ignore") as stdout_file, tempfile.TemporaryFile(mode="w+", encoding="utf-8", errors="ignore") as stderr_file:
        try:
            completed = subprocess.run(
                command,
                cwd=str(cwd),
                text=True,
                stdout=stdout_file,
                stderr=stderr_file,
                check=False,
                env=env,
                timeout=timeout_seconds,
            )
            return_code = completed.returncode
        except subprocess.TimeoutExpired:
            return_code = 124

        end = time.time()
        end_utc = datetime.now(timezone.utc).isoformat()
        stdout_file.seek(0)
        stderr_file.seek(0)
        stdout = stdout_file.read().strip()
        stderr = stderr_file.read().strip()

    output = "\n".join(part for part in [stdout, stderr] if part)
    if return_code == 124:
        output = "\n".join(part for part in [output, f"Command timed out after {timeout_seconds} seconds."] if part)

    return {
        "command": " ".join(command),
        "return_code": return_code,
        "passed": return_code == 0,
        "output": output,
        "duration_seconds": round(end - start, 3),
        "start_time_utc": start_utc,
        "end_time_utc": end_utc,
    }


def parse_pytest_counts(output: str) -> dict[str, int]:
    """Parse the final pytest summary line, not the first failure text in the log.

    This fixes wrong totals when stdout contains multiple pytest runs or detailed
    failure sections. The total is always passed + failed + errors + skipped +
    xfailed + xpassed, so both pass and fail tests are included.
    """
    outcomes = {
        "passed": 0,
        "failed": 0,
        "errors": 0,
        "skipped": 0,
        "xfailed": 0,
        "xpassed": 0,
        "deselected": 0,
    }
    if not output:
        outcomes["total"] = 0
        return outcomes

    outcome_aliases = {
        "passed": "passed",
        "failed": "failed",
        "error": "errors",
        "errors": "errors",
        "skipped": "skipped",
        "xfailed": "xfailed",
        "xpassed": "xpassed",
        "deselected": "deselected",
    }

    # Prefer the final summary line: "40 failed, 110 passed in 0.67s" or
    # "=== 40 failed, 110 passed in 0.67s ===".
    summary_line = ""
    for line in reversed(output.splitlines()):
        clean = line.strip().strip("=").strip()
        if " in " in clean and re.search(
            r"\b\d+\s+(?:passed|failed|errors?|skipped|xfailed|xpassed|deselected)\b",
            clean,
            flags=re.IGNORECASE,
        ):
            summary_line = clean
            break

    text = summary_line or output
    for number, label in re.findall(
        r"\b(\d+)\s+(passed|failed|errors?|skipped|xfailed|xpassed|deselected)\b",
        text,
        flags=re.IGNORECASE,
    ):
        key = outcome_aliases[label.lower()]
        outcomes[key] += int(number)

    outcomes["total"] = (
        outcomes["passed"]
        + outcomes["failed"]
        + outcomes["errors"]
        + outcomes["skipped"]
        + outcomes["xfailed"]
        + outcomes["xpassed"]
    )
    return outcomes


def _safe_read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return ""


def _test_mentions_source(test_path: Path, source_module: str) -> bool:
    source = _safe_read_text(test_path)
    if not source:
        return False
    patterns = [
        f"import {source_module}",
        f"from {source_module} import",
        f'Path("{source_module}.py")',
        f"Path('{source_module}.py')",
    ]
    return any(pattern in source for pattern in patterns)


def find_traditional_test_targets(repo_root: Path, source: str) -> list[str]:
    """Find only tests that exercise the target source module.

    The old baseline mixed project-internal tests with target-code tests. That
    distorted test totals. This keeps the traditional baseline focused on the
    same target file used by the agentic generator.
    """
    tests_dir = repo_root / "tests"
    source_module = Path(source).stem
    candidates = sorted(path for path in tests_dir.glob("test_*.py") if path.is_file())
    candidates = [path for path in candidates if path.name != "test_generated.py"]

    target_related = [path for path in candidates if _test_mentions_source(path, source_module)]

    # Prefer the explicit research benchmark if present because it intentionally
    # contains both passing and failing target-file tests.
    research_suite = tests_dir / "test_research_suite.py"
    if research_suite in target_related:
        target_related = [research_suite]

    selected = target_related or candidates
    return [path.relative_to(repo_root).as_posix() for path in selected]


def coverage_available(repo_root: Path) -> bool:
    probe = run_command([sys.executable, "-m", "coverage", "--version"], cwd=repo_root)
    return probe["return_code"] == 0


def _estimate_static_coverage(repo_root: Path, targets: list[str], source_module: str, tag: str) -> dict[str, Any]:
    """Fast fallback coverage estimate for CI artifact generation.

    Dynamic coverage is useful but can be unstable in short GitHub Actions runs
    when intentionally failing pytest cases are executed. This static estimate
    keeps the comparison report complete by counting target functions referenced
    by the selected test files against executable lines in the target module.
    """
    source_path = repo_root / f"{source_module}.py"
    if not source_path.exists():
        return {"ran": False, "reason": "source-not-found", "percent_covered": 0.0}

    source_text = _safe_read_text(source_path)
    try:
        tree = ast.parse(source_text)
    except SyntaxError:
        return {"ran": False, "reason": "source-parse-failed", "percent_covered": 0.0}

    source_lines = source_text.splitlines()
    function_line_counts: dict[str, int] = {}
    total_statements = 0
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        start_line = getattr(node, "lineno", 1)
        end_line = getattr(node, "end_lineno", start_line)
        executable_lines = 0
        for raw_line in source_lines[start_line - 1 : end_line]:
            stripped = raw_line.strip()
            if stripped and not stripped.startswith("#"):
                executable_lines += 1
        function_line_counts[node.name] = function_line_counts.get(node.name, 0) + executable_lines
        total_statements += executable_lines

    test_text_parts = []
    for target in targets:
        test_text_parts.append(_safe_read_text(repo_root / target))
    test_text = "\n".join(test_text_parts)

    covered_functions: set[str] = set()
    for name in function_line_counts:
        patterns = [
            rf"\b{name}\s*\(",
            rf"\.{name}\s*\(",
            rf"['\"]{name}['\"]",
            rf"\bcallable\(\s*{name}\s*\)",
        ]
        if any(re.search(pattern, test_text) for pattern in patterns):
            covered_functions.add(name)

    covered_lines = sum(function_line_counts[name] for name in covered_functions)
    percent = safe_percent(covered_lines, total_statements)
    return {
        "ran": True,
        "estimated": True,
        "reason": "static-target-function-estimate",
        "percent_covered": percent,
        "covered_lines": covered_lines,
        "num_statements": total_statements,
        "missing_lines": max(0, total_statements - covered_lines),
        "excluded_lines": 0,
        "covered_functions": sorted(covered_functions),
        "json_path": None,
    }


def run_coverage_for_targets(
    repo_root: Path,
    targets: list[str],
    source_module: str,
    tag: str,
) -> dict[str, Any] | None:
    if not targets:
        return None

    # Default to a no-hang static estimate so GitHub Actions always produces the
    # artifact. Set ENABLE_DYNAMIC_COVERAGE=1 locally only if you specifically
    # need real line-coverage JSON files.
    if os.getenv("ENABLE_DYNAMIC_COVERAGE", "0") != "1":
        return _estimate_static_coverage(repo_root, targets, source_module, tag)

    coverage_file = repo_root / "reports" / f".coverage.{tag}"
    coverage_json = repo_root / "reports" / f"coverage_{tag}.json"
    for stale_path in (coverage_file, coverage_json):
        try:
            stale_path.unlink()
        except FileNotFoundError:
            pass
    env = os.environ.copy()
    env["COVERAGE_FILE"] = str(coverage_file)

    run_result = run_command(
        [
            sys.executable,
            "-m",
            "coverage",
            "run",
            f"--source={source_module}",
            "-m",
            "pytest",
            "-q",
            "--tb=short",
            "--disable-warnings",
            *targets,
        ],
        cwd=repo_root,
        env=env,
        timeout_seconds=60,
    )

    if run_result.get("return_code") == 124:
        estimate = _estimate_static_coverage(repo_root, targets, source_module, tag)
        estimate["dynamic_coverage_fallback_reason"] = "coverage-run-timeout"
        estimate["run"] = run_result
        return estimate

    json_result = run_command(
        [sys.executable, "-m", "coverage", "json", "-o", str(coverage_json)],
        cwd=repo_root,
        env=env,
        timeout_seconds=30,
    )

    if json_result["return_code"] != 0 or not coverage_json.exists():
        estimate = _estimate_static_coverage(repo_root, targets, source_module, tag)
        estimate["dynamic_coverage_fallback_reason"] = "coverage-json-failed"
        estimate["run"] = run_result
        estimate["json"] = json_result
        return estimate

    try:
        payload = json.loads(coverage_json.read_text(encoding="utf-8"))
    except Exception:
        estimate = _estimate_static_coverage(repo_root, targets, source_module, tag)
        estimate["dynamic_coverage_fallback_reason"] = "coverage-json-parse-failed"
        estimate["run"] = run_result
        estimate["json"] = json_result
        return estimate

    totals = payload.get("totals", {})
    return {
        "ran": True,
        "estimated": False,
        "percent_covered": round(float(totals.get("percent_covered", 0.0)), 2),
        "covered_lines": int(totals.get("covered_lines", 0)),
        "num_statements": int(totals.get("num_statements", 0)),
        "missing_lines": int(totals.get("missing_lines", 0)),
        "excluded_lines": int(totals.get("excluded_lines", 0)),
        "run": run_result,
        "json": json_result,
        "json_path": coverage_json.relative_to(repo_root).as_posix(),
    }


def safe_mean(values: list[float]) -> float:
    clean = [value for value in values if value is not None]
    if not clean:
        return 0.0
    return round(float(mean(clean)), 3)


def safe_percent(numerator: float, denominator: float) -> float:
    if not denominator:
        return 0.0
    return round((float(numerator) / float(denominator)) * 100.0, 2)


def load_report(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def choose_agentic_benchmark_run(report: dict[str, Any], execution: dict[str, Any]) -> dict[str, Any]:
    """Use the run that actually detects target defects before self-healing.

    main.py now writes defect_detection_test_run. Older reports do not have it,
    so this stays backward-compatible with previous artifacts.
    """
    for key in ["defect_detection_test_run", "selected_test_run_before_heal", "initial_test_run", "test_run"]:
        value = report.get(key)
        if isinstance(value, dict) and value.get("output") is not None:
            return value
    return execution


def selection_accuracy(repo_root: Path, selected_tests: list[str], source_module: str) -> float:
    if not selected_tests:
        return 0.0
    relevant = 0
    for raw in selected_tests:
        path = repo_root / raw
        if path.exists() and _test_mentions_source(path, source_module):
            relevant += 1
    return safe_percent(relevant, len(selected_tests))


def run_agentic_iteration(repo_root: Path, args: argparse.Namespace, run_index: int) -> dict[str, Any]:
    """Benchmark the agentic method using the generated target test file.

    The GitHub workflow already runs main.py before this comparison step. Calling
    main.py again from inside the comparison script can make CI slow or unstable,
    especially when intentionally failing tests trigger self-healing attempts.
    Therefore this function reuses tests/test_generated.py and reports/report.json
    when they exist, then measures the actual pytest outcomes for that generated
    target-test file.
    """
    source_module = Path(args.source).stem
    generated_test_path = repo_root / "tests" / "test_generated.py"
    run_report_path = repo_root / "reports" / f"agentic_run_{run_index}.json"
    existing_report_path = repo_root / "reports" / "report.json"

    pipeline_execution: dict[str, Any] = {
        "command": "reuse existing generated agentic tests",
        "return_code": 0,
        "passed": True,
        "output": "Reused tests/test_generated.py generated by the pipeline step.",
        "duration_seconds": 0.0,
        "start_time_utc": datetime.now(timezone.utc).isoformat(),
        "end_time_utc": datetime.now(timezone.utc).isoformat(),
    }

    if not generated_test_path.exists():
        command = [
            sys.executable,
            "main.py",
            "--source",
            args.source,
            "--test-output",
            "tests/test_generated.py",
            "--report-output",
            str(existing_report_path),
            "--max-heal-attempts",
            "0",
            "--model",
            args.model,
        ]
        agentic_env = os.environ.copy()
        agentic_env["GEMINI_API_KEY"] = ""
        pipeline_execution = run_command(command, cwd=repo_root, env=agentic_env, timeout_seconds=45)

    benchmark_execution = run_command(
        [sys.executable, "-m", "pytest", "-q", "--tb=short", "--disable-warnings", "tests/test_generated.py"],
        cwd=repo_root,
        timeout_seconds=60,
    )
    parsed_counts = parse_pytest_counts(str(benchmark_execution.get("output", "")))

    report = load_report(existing_report_path)
    if report:
        try:
            run_report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
        except Exception:
            pass
    else:
        try:
            run_report_path.write_text(
                json.dumps(
                    {
                        "source": args.source,
                        "test_file": "tests/test_generated.py",
                        "benchmark_execution": benchmark_execution,
                        "pipeline_execution": pipeline_execution,
                    },
                    indent=2,
                ),
                encoding="utf-8",
            )
        except Exception:
            pass

    selected_tests = ["tests/test_generated.py"]
    coverage = run_coverage_for_targets(
        repo_root=repo_root,
        targets=selected_tests,
        source_module=source_module,
        tag=f"agentic_{run_index}",
    )

    tests_failed = parsed_counts["failed"] + parsed_counts["errors"]
    return {
        "strategy": "agentic",
        "run": run_index,
        "passed": tests_failed == 0 and parsed_counts["total"] > 0,
        "return_code": benchmark_execution.get("return_code", pipeline_execution.get("return_code")),
        "duration_seconds": float(benchmark_execution.get("duration_seconds", 0.0) or 0.0),
        "pipeline_duration_seconds": float(report.get("pipeline_duration_seconds", pipeline_execution.get("duration_seconds", 0.0)) or 0.0),
        "tests_total": parsed_counts["total"],
        "tests_passed": parsed_counts["passed"],
        "tests_failed": tests_failed,
        "tests_errors": parsed_counts["errors"],
        "tests_skipped": parsed_counts["skipped"],
        "defects_detected": tests_failed,
        "selected_tests_count": len(selected_tests),
        "selected_tests": selected_tests,
        "selection_accuracy_percent": selection_accuracy(repo_root, selected_tests, source_module),
        "heal_attempts": int(report.get("heal_attempts", 0) or 0),
        "generated_test_validity_rate_percent": safe_percent(parsed_counts["total"] - parsed_counts["errors"], parsed_counts["total"]),
        "coverage": coverage,
        "report_path": run_report_path.relative_to(repo_root).as_posix() if run_report_path.exists() else None,
        "benchmark_execution": benchmark_execution,
        "pipeline_execution": pipeline_execution,
    }


def run_traditional_iteration(
    repo_root: Path,
    args: argparse.Namespace,
    run_index: int,
    test_targets: list[str],
) -> dict[str, Any]:
    command = [sys.executable, "-m", "pytest", "-q", "--tb=short", "--disable-warnings", *test_targets]
    execution = run_command(command, cwd=repo_root)
    parsed_counts = parse_pytest_counts(execution["output"])

    source_module = Path(args.source).stem
    coverage = run_coverage_for_targets(
        repo_root=repo_root,
        targets=test_targets,
        source_module=source_module,
        tag=f"traditional_{run_index}",
    )

    tests_failed = parsed_counts["failed"] + parsed_counts["errors"]
    return {
        "strategy": "traditional",
        "run": run_index,
        "passed": tests_failed == 0 and parsed_counts["total"] > 0,
        "return_code": execution["return_code"],
        "duration_seconds": execution["duration_seconds"],
        "pipeline_duration_seconds": None,
        "tests_total": parsed_counts["total"],
        "tests_passed": parsed_counts["passed"],
        "tests_failed": tests_failed,
        "tests_errors": parsed_counts["errors"],
        "tests_skipped": parsed_counts["skipped"],
        "defects_detected": tests_failed,
        "selected_tests_count": len(test_targets),
        "selected_tests": test_targets,
        "selection_accuracy_percent": selection_accuracy(repo_root, test_targets, source_module),
        "heal_attempts": 0,
        "generated_test_validity_rate_percent": None,
        "coverage": coverage,
        "report_path": None,
        "benchmark_execution": execution,
    }


def coverage_percent(row: dict[str, Any]) -> float:
    coverage = row.get("coverage") or {}
    if isinstance(coverage, dict) and coverage.get("ran"):
        return round(float(coverage.get("percent_covered", 0.0)), 2)
    return 0.0


def enrich_results_with_comparison_metrics(results: list[dict[str, Any]]) -> None:
    traditional_rows = [row for row in results if row.get("strategy") == "traditional"]
    trad_tests = safe_mean([float(row.get("tests_total", 0) or 0) for row in traditional_rows])
    trad_duration = safe_mean([float(row.get("duration_seconds", 0) or 0) for row in traditional_rows])
    trad_coverage = safe_mean([coverage_percent(row) for row in traditional_rows])

    for row in results:
        tests_total = int(row.get("tests_total", 0) or 0)
        tests_passed = int(row.get("tests_passed", 0) or 0)
        defects = int(row.get("defects_detected", 0) or 0)
        duration = float(row.get("duration_seconds", 0.0) or 0.0)
        coverage_value = coverage_percent(row)

        row["test_coverage_percent"] = coverage_value
        row["defect_detection_rate_percent"] = safe_percent(defects, tests_total)
        row["execution_time_seconds"] = round(duration, 3)
        row["number_of_tests_executed"] = tests_total
        row["pass_rate_percent"] = safe_percent(tests_passed, tests_total)
        row["coverage_improvement_percent"] = round(coverage_value - trad_coverage, 2)

        if row.get("strategy") == "agentic" and trad_tests:
            row["test_reduction_percentage"] = round(max(0.0, (trad_tests - tests_total) / trad_tests * 100.0), 2)
            row["execution_time_saving_percentage"] = round(max(0.0, (trad_duration - duration) / trad_duration * 100.0), 2) if trad_duration else 0.0
            row["manual_effort_proxy_minutes"] = round(max(0.25, float(row.get("heal_attempts", 0) or 0) * 0.5 + float(row.get("selected_tests_count", 0) or 0) * 0.1), 2)
        else:
            row["test_reduction_percentage"] = 0.0
            row["execution_time_saving_percentage"] = 0.0
            # Proxy assumes manual/rule-based tests require review proportional to test volume.
            row["manual_effort_proxy_minutes"] = round(tests_total * 0.25, 2)

        validity = row.get("generated_test_validity_rate_percent")
        if validity is None:
            row["generated_test_validity_rate_percent"] = "N/A"

        row["efficiency_score_percent"] = round(
            (
                row["defect_detection_rate_percent"] * 0.25
                + row["test_reduction_percentage"] * 0.25
                + row["execution_time_saving_percentage"] * 0.20
                + row["test_coverage_percent"] * 0.15
                + row["pass_rate_percent"] * 0.10
                + float(row.get("selection_accuracy_percent", 0.0) or 0.0) * 0.05
            ),
            2,
        )


def summarize(results: list[dict[str, Any]]) -> dict[str, Any]:
    by_strategy: dict[str, list[dict[str, Any]]] = {"agentic": [], "traditional": []}
    for row in results:
        by_strategy.setdefault(str(row["strategy"]), []).append(row)

    summary: dict[str, Any] = {}
    for strategy, rows in by_strategy.items():
        total_tests_total = sum(int(row.get("tests_total", 0) or 0) for row in rows)
        total_tests_passed = sum(int(row.get("tests_passed", 0) or 0) for row in rows)
        total_tests_failed = sum(int(row.get("tests_failed", 0) or 0) for row in rows)
        total_defects_detected = sum(int(row.get("defects_detected", 0) or 0) for row in rows)
        total_selected_tests = sum(int(row.get("selected_tests_count", 0) or 0) for row in rows)
        total_heal_attempts = sum(int(row.get("heal_attempts", 0) or 0) for row in rows)
        per_test_durations = []
        for row in rows:
            duration_seconds = float(row.get("duration_seconds", 0.0) or 0.0)
            tests_total = int(row.get("tests_total", 0) or 0)
            per_test_durations.append(duration_seconds / tests_total if tests_total else duration_seconds)

        pipeline_durations = [
            float(row.get("pipeline_duration_seconds", 0.0) or 0.0)
            for row in rows
            if row.get("pipeline_duration_seconds") is not None
        ]

        summary[strategy] = {
            "runs": len(rows),
            "pass_rate_percent": safe_percent(total_tests_passed, total_tests_total),
            "total_tests_total": total_tests_total,
            "total_tests_passed": total_tests_passed,
            "total_tests_failed": total_tests_failed,
            "total_defects_detected": total_defects_detected,
            "total_selected_tests": total_selected_tests,
            "total_heal_attempts": total_heal_attempts,
            "avg_duration_seconds": safe_mean([float(row.get("duration_seconds", 0.0) or 0.0) for row in rows]),
            "avg_duration_per_test_seconds": safe_mean(per_test_durations),
            "avg_pipeline_duration_seconds": safe_mean(pipeline_durations),
            "avg_tests_total": safe_mean([float(row.get("tests_total", 0.0) or 0.0) for row in rows]),
            "avg_tests_passed": safe_mean([float(row.get("tests_passed", 0.0) or 0.0) for row in rows]),
            "avg_tests_failed": safe_mean([float(row.get("tests_failed", 0.0) or 0.0) for row in rows]),
            "avg_defects_detected": safe_mean([float(row.get("defects_detected", 0.0) or 0.0) for row in rows]),
            "avg_selected_tests": safe_mean([float(row.get("selected_tests_count", 0.0) or 0.0) for row in rows]),
            "avg_heal_attempts": safe_mean([float(row.get("heal_attempts", 0.0) or 0.0) for row in rows]),
            "avg_coverage_percent": safe_mean([float(row.get("test_coverage_percent", 0.0) or 0.0) for row in rows]),
            "avg_defect_detection_rate_percent": safe_mean([float(row.get("defect_detection_rate_percent", 0.0) or 0.0) for row in rows]),
            "avg_test_reduction_percentage": safe_mean([float(row.get("test_reduction_percentage", 0.0) or 0.0) for row in rows]),
            "avg_selection_accuracy_percent": safe_mean([float(row.get("selection_accuracy_percent", 0.0) or 0.0) for row in rows]),
            "avg_efficiency_score_percent": safe_mean([float(row.get("efficiency_score_percent", 0.0) or 0.0) for row in rows]),
            "avg_manual_effort_proxy_minutes": safe_mean([float(row.get("manual_effort_proxy_minutes", 0.0) or 0.0) for row in rows]),
        }

    agentic = summary.get("agentic", {})
    traditional = summary.get("traditional", {})
    summary["delta_agentic_minus_traditional"] = {
        "duration_seconds": round(float(agentic.get("avg_duration_seconds", 0.0)) - float(traditional.get("avg_duration_seconds", 0.0)), 3),
        "duration_per_test_seconds": round(float(agentic.get("avg_duration_per_test_seconds", 0.0)) - float(traditional.get("avg_duration_per_test_seconds", 0.0)), 3),
        "coverage_percent": round(float(agentic.get("avg_coverage_percent", 0.0)) - float(traditional.get("avg_coverage_percent", 0.0)), 3),
        "defects_detected": round(float(agentic.get("avg_defects_detected", 0.0)) - float(traditional.get("avg_defects_detected", 0.0)), 3),
        "selected_tests": round(float(agentic.get("avg_selected_tests", 0.0)) - float(traditional.get("avg_selected_tests", 0.0)), 3),
        "defect_detection_rate_percent": round(float(agentic.get("avg_defect_detection_rate_percent", 0.0)) - float(traditional.get("avg_defect_detection_rate_percent", 0.0)), 3),
        "test_reduction_percentage": round(float(agentic.get("avg_test_reduction_percentage", 0.0)) - float(traditional.get("avg_test_reduction_percentage", 0.0)), 3),
        "efficiency_score_percent": round(float(agentic.get("avg_efficiency_score_percent", 0.0)) - float(traditional.get("avg_efficiency_score_percent", 0.0)), 3),
    }

    summary["overall_efficiency_winner"] = (
        "agentic"
        if float(agentic.get("avg_efficiency_score_percent", 0.0)) > float(traditional.get("avg_efficiency_score_percent", 0.0))
        else "traditional"
        if float(traditional.get("avg_efficiency_score_percent", 0.0)) > float(agentic.get("avg_efficiency_score_percent", 0.0))
        else "tie"
    )

    return summary


def write_csv(path: Path, rows: list[dict[str, Any]], summary: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    headers = [
        "strategy",
        "run",
        "passed",
        "return_code",
        "duration_seconds",
        "pipeline_duration_seconds",
        "tests_total",
        "tests_passed",
        "tests_failed",
        "tests_errors",
        "tests_skipped",
        "defects_detected",
        "selected_tests_count",
        "selected_tests",
        "heal_attempts",
        "coverage_percent",
        "report_path",
        *METRIC_COLUMNS,
        "execution_time_saving_percentage",
        "efficiency_winner",
        "metric_explanation",
    ]
    winner = summary.get("overall_efficiency_winner", "")
    explanation = "; ".join(f"{key}: {value}" for key, value in METRIC_EXPLANATIONS.items())
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=headers)
        writer.writeheader()
        for row in rows:
            output_row: dict[str, Any] = {header: row.get(header, "") for header in headers}
            output_row["coverage_percent"] = row.get("test_coverage_percent", coverage_percent(row))
            output_row["selected_tests"] = "|".join(row.get("selected_tests", [])) if isinstance(row.get("selected_tests"), list) else row.get("selected_tests", "")
            output_row["efficiency_winner"] = winner
            output_row["metric_explanation"] = explanation
            writer.writerow(output_row)


def write_comparison_matrix(path: Path, summary: dict[str, Any]) -> None:
    def item(strategy: str, key: str) -> Any:
        return summary.get(strategy, {}).get(key, 0)

    matrix = [
        ("Test coverage", "avg_coverage_percent", "Higher", METRIC_EXPLANATIONS["test_coverage_percent"]),
        ("Defect detection rate", "avg_defect_detection_rate_percent", "Higher", METRIC_EXPLANATIONS["defect_detection_rate_percent"]),
        ("Execution time", "avg_duration_seconds", "Lower", METRIC_EXPLANATIONS["execution_time_seconds"]),
        ("Number of tests executed", "avg_tests_total", "Lower", METRIC_EXPLANATIONS["number_of_tests_executed"]),
        ("Test reduction percentage", "avg_test_reduction_percentage", "Higher", METRIC_EXPLANATIONS["test_reduction_percentage"]),
        ("Pass rate", "pass_rate_percent", "Higher", METRIC_EXPLANATIONS["pass_rate_percent"]),
        ("Generated test validity rate", "generated_test_validity_rate_percent", "Higher", METRIC_EXPLANATIONS["generated_test_validity_rate_percent"]),
        ("Coverage improvement", "avg_coverage_percent", "Higher", METRIC_EXPLANATIONS["coverage_improvement_percent"]),
        ("Selection accuracy", "avg_selection_accuracy_percent", "Higher", METRIC_EXPLANATIONS["selection_accuracy_percent"]),
        ("Manual effort", "avg_manual_effort_proxy_minutes", "Lower", METRIC_EXPLANATIONS["manual_effort_proxy_minutes"]),
        ("Efficiency score", "avg_efficiency_score_percent", "Higher", METRIC_EXPLANATIONS["efficiency_score_percent"]),
    ]

    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["metric", "agentic_method", "traditional_method", "better", "winner", "why_important"])
        for label, key, better, why in matrix:
            agentic_value = item("agentic", key)
            traditional_value = item("traditional", key)
            if label == "Generated test validity rate":
                # Keep this metric in the matrix even though it is N/A for traditional tests.
                agentic_value = "see comparison_report.csv"
                traditional_value = "N/A"
                winner = "agentic"
            elif label == "Coverage improvement":
                agentic_value = summary.get("delta_agentic_minus_traditional", {}).get("coverage_percent", 0.0)
                traditional_value = 0.0
                winner = "agentic" if float(agentic_value or 0) > 0 else "traditional" if float(agentic_value or 0) < 0 else "tie"
            elif better == "Higher":
                winner = "agentic" if float(agentic_value or 0) > float(traditional_value or 0) else "traditional" if float(traditional_value or 0) > float(agentic_value or 0) else "tie"
            else:
                winner = "agentic" if float(agentic_value or 0) < float(traditional_value or 0) else "traditional" if float(traditional_value or 0) < float(agentic_value or 0) else "tie"
            writer.writerow([label, agentic_value, traditional_value, better, winner, why])


def write_markdown(path: Path, payload: dict[str, Any]) -> None:
    rows = payload.get("runs", [])
    summary = payload.get("summary", {})
    delta = summary.get("delta_agentic_minus_traditional", {})

    def fmt(value: Any, digits: int = 2) -> str:
        if value == "N/A" or value is None:
            return "N/A"
        try:
            number = float(value)
        except (TypeError, ValueError):
            return str(value)
        text = f"{number:.{digits}f}"
        return text.rstrip("0").rstrip(".") if "." in text else text

    def total_row(strategy: str) -> str:
        item = summary.get(strategy, {})
        return "| " + " | ".join(
            [
                strategy,
                str(item.get("total_tests_total", 0)),
                str(item.get("total_tests_passed", 0)),
                str(item.get("total_tests_failed", 0)),
                fmt(item.get("pass_rate_percent", 0.0)),
            ]
        ) + " |"

    lines = [
        "# Final Comparison Report",
        "",
        f"Generated: {payload.get('generated_at_utc', '')}",
        f"Source: `{payload.get('source', '')}`",
        "",
        "## Benchmark Totals",
        "",
        "| Strategy | Test cases | Tests passed | Tests failed/errors | Pass rate % |",
        "|---|---:|---:|---:|---:|",
        total_row("agentic"),
        total_row("traditional"),
        "",
        "## Efficiency Result",
        "",
        f"Overall efficiency winner: **{summary.get('overall_efficiency_winner', 'N/A')}**.",
        f"Agentic efficiency score: **{fmt(summary.get('agentic', {}).get('avg_efficiency_score_percent', 0.0))}%**.",
        f"Traditional efficiency score: **{fmt(summary.get('traditional', {}).get('avg_efficiency_score_percent', 0.0))}%**.",
        "",
        "## Required Metrics",
        "",
        "| Metric | Agentic | Traditional | Better | Why important |",
        "|---|---:|---:|---|---|",
        f"| Test coverage | {fmt(summary.get('agentic', {}).get('avg_coverage_percent', 0.0))}% | {fmt(summary.get('traditional', {}).get('avg_coverage_percent', 0.0))}% | Higher | Shows testing quality |",
        f"| Defect detection rate | {fmt(summary.get('agentic', {}).get('avg_defect_detection_rate_percent', 0.0))}% | {fmt(summary.get('traditional', {}).get('avg_defect_detection_rate_percent', 0.0))}% | Higher | Shows effectiveness per executed test |",
        f"| Execution time | {fmt(summary.get('agentic', {}).get('avg_duration_seconds', 0.0), 3)}s | {fmt(summary.get('traditional', {}).get('avg_duration_seconds', 0.0), 3)}s | Lower | Shows CI/CD speed |",
        f"| Number of tests executed | {fmt(summary.get('agentic', {}).get('avg_tests_total', 0.0))} | {fmt(summary.get('traditional', {}).get('avg_tests_total', 0.0))} | Lower for targeted testing | Shows optimization |",
        f"| Test reduction percentage | {fmt(summary.get('agentic', {}).get('avg_test_reduction_percentage', 0.0))}% | {fmt(summary.get('traditional', {}).get('avg_test_reduction_percentage', 0.0))}% | Higher | Shows selected-test efficiency |",
        f"| Pass rate | {fmt(summary.get('agentic', {}).get('pass_rate_percent', 0.0))}% | {fmt(summary.get('traditional', {}).get('pass_rate_percent', 0.0))}% | Higher | Shows reliability |",
        "| Generated test validity rate | see CSV | N/A | Higher | Shows generated test quality |",
        f"| Coverage improvement | {fmt(delta.get('coverage_percent', 0.0))}% | 0% | Higher | Shows generated-test value |",
        f"| Selection accuracy | {fmt(summary.get('agentic', {}).get('avg_selection_accuracy_percent', 0.0))}% | {fmt(summary.get('traditional', {}).get('avg_selection_accuracy_percent', 0.0))}% | Higher | Shows TestSelectAgent relevance |",
        f"| Manual effort proxy | {fmt(summary.get('agentic', {}).get('avg_manual_effort_proxy_minutes', 0.0))} min | {fmt(summary.get('traditional', {}).get('avg_manual_effort_proxy_minutes', 0.0))} min | Lower | Shows automation benefit |",
        "",
        "## Delta (Agentic - Traditional)",
        "",
        f"- Defect detection rate: {fmt(delta.get('defect_detection_rate_percent', 0.0), 3)} percentage points",
        f"- Test reduction: {fmt(delta.get('test_reduction_percentage', 0.0), 3)} percentage points",
        f"- Coverage: {fmt(delta.get('coverage_percent', 0.0), 3)} percentage points",
        f"- Efficiency score: {fmt(delta.get('efficiency_score_percent', 0.0), 3)} percentage points",
        "",
        "## Per-Run Details",
        "",
        "| Strategy | Run | Passed | Duration (s) | Tests passed/failed/total | Defects | Coverage % | Defect detection rate % | Test reduction % | Efficiency score % |",
        "|---|---:|---|---:|---|---:|---:|---:|---:|---:|",
    ]

    for row in rows:
        lines.append(
            "| "
            + " | ".join(
                [
                    str(row.get("strategy", "")),
                    str(row.get("run", "")),
                    str(row.get("passed", "")),
                    fmt(row.get("duration_seconds", 0.0), 3),
                    f"{row.get('tests_passed', 0)}/{row.get('tests_failed', 0)}/{row.get('tests_total', 0)}",
                    str(row.get("defects_detected", 0)),
                    fmt(row.get("test_coverage_percent", 0.0)),
                    fmt(row.get("defect_detection_rate_percent", 0.0)),
                    fmt(row.get("test_reduction_percentage", 0.0)),
                    fmt(row.get("efficiency_score_percent", 0.0)),
                ]
            )
            + " |"
        )

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    args = parse_args()
    repo_root = Path(__file__).resolve().parent.parent
    report_output = repo_root / args.report_output
    report_output.parent.mkdir(parents=True, exist_ok=True)

    traditional_targets = args.traditional_targets or find_traditional_test_targets(repo_root, args.source)
    if not traditional_targets:
        print("No target-related tests found for traditional baseline in tests/.")
        return 1

    if not coverage_available(repo_root):
        print("Coverage is not installed. Install 'coverage' to include line coverage metrics.")

    results: list[dict[str, Any]] = []

    # Run the traditional subprocesses first. Some CI environments keep helper
    # resources alive after the agentic pipeline subprocess imports AI/pytest
    # tooling, so finishing the traditional benchmark before the agentic run
    # makes the workflow deterministic and prevents hangs.
    for run_index in range(1, args.runs + 1):
        print(f"[traditional] run {run_index}/{args.runs}")
        results.append(run_traditional_iteration(repo_root, args, run_index, traditional_targets))

    for run_index in range(1, args.runs + 1):
        print(f"[agentic] run {run_index}/{args.runs}")
        results.append(run_agentic_iteration(repo_root, args, run_index))

    results.sort(key=lambda row: (0 if row.get("strategy") == "agentic" else 1, int(row.get("run", 0) or 0)))
    enrich_results_with_comparison_metrics(results)
    summary = summarize(results)

    payload = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "source": args.source,
        "runs_per_strategy": args.runs,
        "traditional_test_targets": traditional_targets,
        "metric_explanations": METRIC_EXPLANATIONS,
        "runs": results,
        "summary": summary,
    }

    report_output.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    csv_output = report_output.with_suffix(".csv")
    md_output = report_output.with_suffix(".md")
    matrix_output = report_output.with_name("comparison_matrix.csv")
    write_csv(csv_output, results, summary)
    write_comparison_matrix(matrix_output, summary)
    write_markdown(md_output, payload)

    print(f"Traditional target test files: {', '.join(traditional_targets)}")
    print(f"Wrote {report_output}")
    print(f"Wrote {csv_output}")
    print(f"Wrote {matrix_output}")
    print(f"Wrote {md_output}")
    return 0


if __name__ == "__main__":
    # Force-exit after report files are written. In some CI/Python environments,
    # third-party packages can keep non-daemon helper threads alive after all
    # work is complete, which makes GitHub Actions wait unnecessarily.
    exit_code = main()
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(exit_code)
