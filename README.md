<div align="center">

# AI Test Generator — CI/CD Experiment Version
**Earlier agentic-testing pipeline with GitHub Actions and benchmark reports**

![GitHub Actions](https://img.shields.io/badge/CI-GitHub%20Actions-2088FF?logo=githubactions&logoColor=white)
![Python](https://img.shields.io/badge/Python-pytest-3776AB?logo=python&logoColor=white)
![Status](https://img.shields.io/badge/Stage-Earlier%20CI%20experiment-orange)

[Repository](https://github.com/ChiththajaGalabodage/research_project_github_actions_fixed) · [Run guide](RUN_GUIDE_UPDATED.md) · [Research reports](reports/)

</div>

## Summary

This repository preserves an **earlier GitHub Actions-oriented version** of the AI test generation and agentic-versus-traditional testing workflow. Its purpose is to run a Python target through automated test generation, validation, comparison and artifact upload in a CI environment.

The design contributes to the *development history* of the LLM continuous-testing thesis, but **is not the final FastAPI/TestGenAgent/TestSelectAgent study**. Metrics should be cited from this repository's own artifacts rather than copied from the revised thesis.

## Components

```text
.github/workflows/pipeline.yml   GitHub Actions CI workflow
main.py                          Pipeline entry point
target_code.py                   Python program under test
src/                             Analysis, generation, selection, repair, execution
scripts/                         Validation and comparison scripts
tests/                           Test cases and generated suites
reports/                         Comparison tables, coverage and run records
requirements.txt                 Python dependencies
RUN_GUIDE_UPDATED.md             Extended experiment instructions
GITHUB_ACTIONS_FIX_STEPS.md      CI setup notes
```

## Getting started

```bash
git clone https://github.com/ChiththajaGalabodage/research_project_github_actions_fixed.git
cd research_project_github_actions_fixed
python -m venv .venv
# Windows: .venv\Scripts\Activate.ps1
# macOS / Linux: source .venv/bin/activate
pip install -r requirements.txt
```

```bash
python main.py --source target_code.py --max-heal-attempts 2
python scripts/validate_generated_tests.py
python scripts/compare_methods.py --source target_code.py --runs 1
```

Optional predictive-selection comparison is described in [`RUN_GUIDE_UPDATED.md`](RUN_GUIDE_UPDATED.md):

```bash
python scripts/compare_methods.py --source target_code.py --runs 1 --use-predictive-selection
```

## CI/CD workflow

`.github/workflows/pipeline.yml` configures the Python environment, runs the generator and comparison tools, and uploads experiment outputs. **In the inspected workflow, `GEMINI_API_KEY` is set to an empty string**; this permits local/fallback behavior but does not establish a live Gemini-based experiment. For model-backed claims, explicitly configure an authorized secret and record the actual model mode and outputs.

### Outputs to review

| Artifact | Content |
|---|---|
| `reports/comparison_report.csv` | Per-strategy comparison |
| `reports/comparison_matrix.csv` | Expanded comparison metrics |
| `reports/comparison_report.json` | Machine-readable results |
| `reports/comparison_report.md` | Human-readable report |
| `reports/coverage_*.json` | Captured coverage data |
| `tests/test_generated.py` | Generated tests |

See the run guide for the exact experiment procedure and supported flags.

## How to interpret the findings

- Keep product/test failures visible; do not silently repair away genuine defects.
- Do not interpret the number of pytest failures as a validated count of unique faults.
- Distinguish deterministic fallback runs from calls made to a hosted model.
- The repository's historical comparison metrics and the revised thesis's final **FastAPI** experiment use different subjects and evaluation controls.

## Relationship to the final thesis

This CI prototype illustrates early pipeline integration. The later, separately documented [`Fast-API-Project-main`](https://github.com/ChiththajaGalabodage/Fast-API-Project-main) uses a seeded API, strict AST gates, adaptive score safety, guarded transaction rollback, and a secret-free final suite.

**Author:** [Chiththaja Galabodage](https://github.com/ChiththajaGalabodage)
