# START HERE – Gemini

You are joining an existing project where two agents have already worked:

- Claude (initial architecture and system creation)
- Codex (major implementation and tuning)

Your role is **independent diagnosis**.

Do not assume the existing design is correct.

However, do not rewrite architecture unless it directly impacts accuracy.

Your task is to identify **why CASForge produces only ~40% improvement in GWT generation when the target is ~80%+**.

Important context:

- End-to-end pipeline works
- Retrieval pipeline is already strong
- Parsing pipeline is stable
- The issue is believed to be in the **planning → assembly stage**

Primary inspection targets:

- `story_facts.py`
- `scenario_planner.py`
- `feature_assembler.py`

Your goal is **root cause identification**, not generic code review.

Follow the instructions in:

1. RUN_ORDER.md
2. REVIEW_PROMPT.md
3. OUTPUT_FORMAT.md
