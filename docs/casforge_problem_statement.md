# CASForge --- Problem Statement

## 1. Overview

CASForge is an internal engineering tool designed to convert **JIRA
feature descriptions** into **ATDD-ready Gherkin `.feature` files** for
the CAS (Customer Acquisition System) testing repository.

The tool operates locally on a tester's machine and analyzes existing
test scenarios in the repository to generate new scenarios that reuse
existing automation steps.

The critical requirement is that **every generated step must already
exist in the ATDD repository**. If a step does not exist, the automation
framework fails to compile.

Therefore, CASForge must retrieve real steps from the repository instead
of inventing new ones.

---

## 4. Target Output Quality

CASForge is designed with the following expectations:

Outcome Target

---

Correct steps on first generation \~80%
Remaining steps flagged as NEW
Manual correction required minimal

The system does not attempt to generate fully correct test cases
automatically.

Instead it provides **a high‑quality draft built from real repository
steps**.

---

## 5. Constraints

CASForge must operate under strict constraints:

- No external APIs
- No cloud models
- All computation runs **locally**
- All repository data remains **on‑premises**

Technology constraints:

- PostgreSQL full‑text search for retrieval
- llama‑cpp for local LLM inference
- FastAPI backend
- Plain HTML + JavaScript frontend
