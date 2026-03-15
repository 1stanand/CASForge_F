You are not doing a generic repo review.

Read only these first:

1. .agent/PROJECT_STATUS.md
2. .agent/gemini/REVIEW_SCOPE.md
3. .agent/gemini/INPUTS.md
4. CodeManual.md
5. Continuation_Guide.md
6. NextSteps.md
7. skills.md

Task:
Identify the most likely root cause(s) of low business-faithful output quality in CASForge.

Important context:

- End-to-end pipeline works
- Retrieval is already strong
- Tests, smoke, retrieval benchmark, and output validation are passing
- The main issue is semantic/business accuracy on hard stories

Focus especially on:

- story_facts.py
- scenario_planner.py
- feature_assembler.py

Judge using:

- scope correctness
- LOB/stage correctness
- polarity correctness
- scenario family correctness
- repo-authentic chain quality
- assertion relevance
- cross-domain leakage
- whether omitted gaps are honest and useful

Do not spend time on:

- README polish
- generic code quality commentary
- folder naming
- style cleanup
- broad architecture praise

Output required:

1. top 5 root-cause findings
2. which single stage is most responsible
3. exact files most worth inspecting
4. concrete next fixes in priority order
5. anything in the current docs that seems overconfident or misleading
