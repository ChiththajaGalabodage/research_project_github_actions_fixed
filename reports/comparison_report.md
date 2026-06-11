# Final Comparison Report

Generated: 2026-06-10T18:02:05.662208+00:00
Source: `target_code.py`

## Benchmark Totals

| Strategy | Test cases | Tests passed | Tests failed/errors | Pass rate % |
|---|---:|---:|---:|---:|
| agentic | 8 | 6 | 2 | 75 |
| traditional | 150 | 110 | 40 | 73.33 |

## Efficiency Result

Overall efficiency winner: **agentic**.
Agentic efficiency score: **57.42%**.
Traditional efficiency score: **24.75%**.

## Required Metrics

| Metric | Agentic | Traditional | Better | Why important |
|---|---:|---:|---|---|
| Test coverage | 100% | 38.3% | Higher | Shows testing quality |
| Defect detection rate | 25% | 26.67% | Higher | Shows effectiveness per executed test |
| Execution time | 5.656s | 5.285s | Lower | Shows CI/CD speed |
| Number of tests executed | 8 | 150 | Lower for targeted testing | Shows optimization |
| Test reduction percentage | 94.67% | 0% | Higher | Shows selected-test efficiency |
| Pass rate | 75% | 73.33% | Higher | Shows reliability |
| Generated test validity rate | see CSV | N/A | Higher | Shows generated test quality |
| Coverage improvement | 61.7% | 0% | Higher | Shows generated-test value |
| Selection accuracy | 100% | 100% | Higher | Shows TestSelectAgent relevance |
| Manual effort proxy | 1.1 min | 37.5 min | Lower | Shows automation benefit |

## Delta (Agentic - Traditional)

- Defect detection rate: -1.67 percentage points
- Test reduction: 94.67 percentage points
- Coverage: 61.7 percentage points
- Efficiency score: 32.67 percentage points

## Per-Run Details

| Strategy | Run | Passed | Duration (s) | Tests passed/failed/total | Defects | Coverage % | Defect detection rate % | Test reduction % | Efficiency score % |
|---|---:|---|---:|---|---:|---:|---:|---:|---:|
| agentic | 1 | False | 5.656 | 6/2/8 | 2 | 100 | 25 | 94.67 | 57.42 |
| traditional | 1 | False | 5.285 | 110/40/150 | 40 | 38.3 | 26.67 | 0 | 24.75 |
