# Accuracy Progress

This file tracks incremental real-run quality checks for CASForge.

Run output convention:
- `workspace/generated/run1`
- `workspace/generated/run2`
- `workspace/generated/run3`

Comparison rule:
- compare each run against the previous tracked run
- treat the first tracked run as the baseline
- prefer raw quality signals over a single inflated "accuracy" number

## Run 1

Date:
2026-03-15

Output folder:
`workspace/generated/run1`

Checks run:
- `python -m unittest discover -s test`
- `python tools/cli/smoke_small_chunks.py`
- real sample generation for `CAS-264757` and `CAS-270826`
- `python tools/cli/validate_generated_features.py --dir workspace/generated/run1`

Repo test status:
- unit tests: `45/45` passed
- smoke: `PASS`
- generated feature validation: `2/2` files passed

Run 1 sample metrics:

| Story | Intents | Scenarios | Coverage gaps | Unresolved steps | Grounded steps | Grounding rate |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| `CAS-264757` | 9 | 7 | 3 | 11 | 41 / 52 | 78.8% |
| `CAS-270826` | 8 | 6 | 2 | 28 | 35 / 63 | 55.6% |

Aggregate:
- planned scenario yield: `13 / 17` = `76.5%`
- overall grounding rate: `76 / 115` = `66.1%`
- `NEW_STEP_NOT_IN_REPO` markers:
  - `CAS-264757`: `11`
  - `CAS-270826`: `22`
  - total: `33`

Observed outcome:
- `CAS-264757` is reasonably strong and conservative.
- `CAS-270826` is still weak: too many unresolved/new steps and too much generic committee-verdict planning.
- current changes improved conservative behavior and reduced obvious generic fact pollution, but accuracy is still mixed across stories.

Improvement vs previous run:
- baseline run, no prior tracked entry

Next thing to watch:
- committee-verdict target/effect extraction still needs deeper semantic separation
- generic validation/dependency planning around committee stories is still a major weak spot

## Run 2

Date:
2026-03-15

Output folder:
`workspace/generated/run2`

Checks run:
- `python -m unittest discover -s test -p 'test_generation_planning.py'`
- real sample generation for `CAS-264757` and `CAS-270826`
- `python tools/cli/validate_generated_features.py --dir workspace/generated/run2`

Repo test status:
- targeted planning tests: `32/32` passed
- generated feature validation: `2/2` files passed

Run 2 sample metrics:

| Story | Intents | Scenarios | Coverage gaps | Unresolved steps | Grounded steps | Grounding rate |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| `CAS-264757` | 9 | 7 | 3 | 11 | 41 / 52 | 78.8% |
| `CAS-270826` | 5 | 3 | 2 | 13 | 20 / 33 | 60.6% |

Aggregate:
- planned scenario yield: `10 / 14` = `71.4%`
- overall grounding rate: `61 / 85` = `71.8%`
- `NEW_STEP_NOT_IN_REPO` markers:
  - `CAS-264757`: `11`
  - `CAS-270826`: `13`
  - total: `24`

Improvement vs previous run:
- strongest gain is on `CAS-270826`, where overly generic validation/dependency extraction was reduced before planning
- `CAS-270826` scenarios dropped from `6` to `3`, which removed weak speculative coverage rather than cutting grounded scenarios
- `CAS-270826` unresolved steps dropped from `28` to `13`
- `CAS-270826` grounding rate improved from `55.6%` to `60.6%`
- aggregate unresolved/new-step markers improved from `33` to `24`
- aggregate grounding rate improved from `66.1%` to `71.8%`
- `CAS-264757` stayed effectively unchanged, which suggests the change was conservative rather than sample-specific retuning

Observed outcome:
- the main accuracy issue was still brittle story-fact normalization, especially generic `validation`, `default_state`, and family labeling that created weak downstream plans
- tightening those signals improved conservative accuracy on the weaker committee-style story without changing the stronger story
- the system is still precision-first: fewer scenarios, fewer fabricated steps, more trustworthy coverage gaps
