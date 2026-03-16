# CASForge — Problem Statement

## What is this tool?

CASForge converts JIRA user stories into ready-to-use Gherkin `.feature` files for
the CAS (Customer Acquisition System) test automation repository.

A tester used to write these files manually. Each file describes a set of test
scenarios in plain English with a strict structure (Given/When/Then). Writing them
takes hours per story, and they must use steps that already exist in the test
automation framework — you cannot invent new steps or the framework won't compile.

CASForge automates that draft.

---

## The Core Constraint

**Every step in a generated scenario must already exist in the repository.**

The CAS ATDD repository has ~15,000+ unique step definitions built up over years.
If a generated step does not exist verbatim, the automation framework throws a
compile error. CASForge must find real steps from the repository, not invent them.

---

## What CASForge Does

1. Reads a JIRA story (exported as CSV)
2. Uses a local LLM to extract testable behaviours from the story text
3. For each behaviour, searches the repository for matching real scenarios
4. Uses the LLM again to pick the most relevant scenario and prune it to fit
5. Assembles a complete `.feature` file with proper tags, Background, and Examples tables

---

## Target Quality

| Outcome | Target |
|---------|--------|
| Steps correctly retrieved from repo | ~80% |
| New/unresolved steps flagged clearly | Yes — marked `# [NEW_STEP_NOT_IN_REPO]` |
| Manual correction needed | Minimal — review and fix flagged steps only |

CASForge does not claim to produce a 100% correct file automatically.
It produces a high-quality draft. The tester reviews, fixes the flagged steps, and commits.

---

## Constraints

- Runs completely locally — no cloud APIs, no external services
- LLM runs on-device using `llama.cpp` (GGUF model file)
- All repository data stays on-premises
- Works on a standard developer laptop (8GB RAM minimum)
