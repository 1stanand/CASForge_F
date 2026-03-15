# Accuracy Tracker

This file is the short-form tracker for the latest verified test and accuracy state.

Detailed run-by-run metrics live in:
- `agent/reports/accuracychecks/accuracy_progress.md`

## Latest Verified Status

Date:
2026-03-15

Latest checks run:
- `python -m unittest discover -s test`
- `python tools/cli/smoke_small_chunks.py`
- `python -m unittest discover -s test -p 'test_generation_planning.py'`
- `python tools/cli/validate_generated_features.py --dir workspace/generated/run1`
- `python tools/cli/validate_generated_features.py --dir workspace/generated/run2`

Latest results:
- full unit suite: `64/64` passed
- targeted planning/config tests: `48/48` passed
- smoke flow: `PASS`
- generated feature validation:
  - `workspace/generated/run1`: `2/2` passed
  - `workspace/generated/run2`: `2/2` passed

## Accuracy Trend

| Run | Story | Scenarios | Unresolved steps | Grounding rate | Notes |
| --- | --- | ---: | ---: | ---: | --- |
| `run1` | `CAS-264757` | 7 | 11 | 78.8% | strong/stable |
| `run1` | `CAS-270826` | 6 | 28 | 55.6% | weak, generic planning leakage |
| `run2` | `CAS-264757` | 7 | 11 | 78.8% | unchanged |
| `run2` | `CAS-270826` | 3 | 13 | 60.6% | improved conservative accuracy |

Current aggregate comparison:
- overall grounding rate: `66.1% -> 71.8%`
- total `NEW_STEP_NOT_IN_REPO` markers: `33 -> 24`
- main gain is from removing weak speculative planning on the committee-style story rather than inflating scenario count

## Current Reading

- accuracy is improving in the conservative direction
- the stronger omni sample stayed stable
- the weaker committee-style sample improved materially after story-fact hardening
- remaining weakness is still semantic separation of target, effect, and polarity in mixed business sentences
