# Gemini Output Format

Return output in exactly two parts.

## Part 1: Markdown report

File name:
agent/reports/gemini_root_cause_review.md

Sections:

1. Executive summary
2. Most likely primary bottleneck
3. Top 5 root-cause findings
4. File-level inspection priority
5. Recommended fixes in order
6. Risks / possible misreads in current docs

## Part 2: JSON

File name:
agent/reports/gemini_root_cause_review.json

Shape:
{
"primary_bottleneck": "",
"confidence": "",
"top_findings": [
{
"rank": 1,
"title": "",
"stage": "",
"files": [],
"why_it_matters": "",
"suggested_fix": ""
}
],
"priority_files": [],
"recommended_fix_order": [],
"docs_that_may_be_overconfident": []
}
