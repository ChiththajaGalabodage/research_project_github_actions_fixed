# Updated run guide: agentic vs traditional metrics

## What was fixed

1. `comparison_report.csv` now includes every required metric from `should generate matrics.xlsx`:
   - Test coverage
   - Defect detection rate
   - Execution time
   - Number of tests executed
   - Test reduction percentage
   - Pass rate
   - Generated test validity rate
   - Coverage improvement
   - Selection accuracy
   - Manual effort proxy
   - Overall efficiency score

2. Test totals are now parsed from the final pytest summary line.
   - `tests_total = passed + failed + errors + skipped + xfailed + xpassed`
   - Both passed and failed target-file tests are included.

3. Traditional baseline is now target-file focused.
   - It uses `tests/test_research_suite.py` for `target_code.py`.
   - This prevents internal project tests from corrupting the target-file comparison.

4. Agentic mode now benchmarks the generated target tests before self-healing.
   - This preserves defect-detection failures in the metrics.
   - The final healed result is still saved in the JSON report.

5. GitHub Actions uploads:
   - `reports/comparison_report.csv`
   - `reports/comparison_report.json`
   - `reports/comparison_matrix.csv`
   - `reports/comparison_report.md`
   - `reports/coverage_*.json`
   - `tests/test_generated.py`

## Local run commands

Run these from the project root.

```bash
python -m venv .venv
```

Windows PowerShell:

```powershell
.\.venv\Scripts\Activate.ps1
```

Git Bash / macOS / Linux:

```bash
source .venv/bin/activate
```

Install dependencies:

```bash
python -m pip install --upgrade pip
pip install -r requirements.txt
```

Run the AI test generator pipeline:

```bash
python main.py --source target_code.py --max-heal-attempts 2
```

Validate generated tests:

```bash
python scripts/validate_generated_tests.py
```

Run the final comparison:

```bash
python scripts/compare_methods.py --source target_code.py --runs 1
```

Optional: run predictive selection comparison instead of generated-only comparison:

```bash
python scripts/compare_methods.py --source target_code.py --runs 1 --use-predictive-selection
```

## Output files to check

```text
reports/comparison_report.csv
reports/comparison_matrix.csv
reports/comparison_report.md
reports/comparison_report.json
```

## How to explain the result in the presentation

The traditional method executes a large target-file benchmark suite. It detects more total failures, but it runs many more tests. The agentic method executes fewer generated target tests and detects a higher defect density per executed test. Therefore, agentic testing is shown as more efficient using test reduction percentage, defect detection rate, execution time saving, and the weighted efficiency score.
