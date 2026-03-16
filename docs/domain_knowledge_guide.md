# CASForge — Domain Knowledge Guide

`config/domain_knowledge.json` is the single place you edit to teach CASForge about
your business domain. No code changes are required when you add new values here.

---

## What Is It?

Think of it as a vocabulary file for the CAS world. It tells CASForge:

- What loan products exist (HL, PL, LAP, etc.)
- What stages the application moves through (DDE, Recommendation, etc.)
- What UI concepts are important (decision checkbox, decision column, etc.)
- How to categorise test intents into logical groups

---

## Top-Level Nodes

### `lob_aliases` — Loan Product Codes

**What it does:** Maps human-readable names to the short canonical code used in Gherkin tags and Examples tables.

```json
{ "canonical": "HL", "phrases": ["home loan"] }
```

- `canonical` — the code used in feature files (e.g. `HL`, `PL`, `LAP`)
- `phrases` — any text that means the same thing; used during JIRA story parsing and intent extraction

**When to add a new LOB:**
Copy any existing entry, change `canonical` to your new code, and list all the phrases a JIRA story might use to refer to it.

```json
{ "canonical": "TWO_W", "phrases": ["two wheeler", "two-wheeler", "2w loan"] }
```

---

### `stages` — CAS Application Stages

**What it does:** Lists the stages an application passes through, with aliases so the text matcher can recognise informal references.

```json
{ "canonical": "Recommendation", "aliases": ["recommendation"] }
```

- `canonical` — the display name used in feature file headers
- `aliases` — lowercase variations used in text matching

**When to add a stage:**
Add an entry with the stage name as `canonical` and all lowercase spellings as `aliases`.

---

### `entities` — Named UI Concepts

**What it does:** Tells the intent extractor about specific UI components and what test behaviour family they belong to.

```json
{
  "canonical": "decision checkbox",
  "aliases": ["decision check box", "checkbox in decision column"],
  "family": "default_state",
  "screens": []
}
```

- `canonical` — the preferred, clean name for the UI element
- `aliases` — all the different ways a JIRA author might write the same thing (typos, abbreviations, variations)
- `family` — what category of test behaviour this entity triggers (see `families` section below)
- `screens` — optional: specific screen names this entity appears on (informational only for now)

**When to add an entity:**
Add entries for new UI components that appear frequently in stories. Each alias you add means the LLM will recognise that variation and know it refers to the same concept.

Example:
```json
{
  "canonical": "disbursement amount field",
  "aliases": ["disbursement amount", "disbursal amount field", "disbursement amt"],
  "family": "field_enablement",
  "screens": ["Disbursal Initiation"]
}
```

---

### `families` — Test Behaviour Categories

**What it does:** Defines how test intents are classified. Each family has a set of trigger words — if these words appear in an intent, it gets that family label.

```json
{
  "key": "validation",
  "terms": ["validation", "mandatory", "required", "invalid", "error", "reject", "prevent", "zero"]
}
```

- `key` — the internal family name used in intent objects
- `terms` — words that signal this type of test behaviour

**Existing families and what they mean:**

| Family | Meaning | Example intent |
|--------|---------|----------------|
| `ui_structure` | Is a UI element visible/shown? | "Display decision column at Recommendation" |
| `default_state` | What is the default value of a field/checkbox? | "Decision checkbox unchecked by default" |
| `dependency` | Does value A depend on value B? | "App level decision derived from sub loan decisions" |
| `field_enablement` | Is a field editable or read-only? | "Recommended amount field disabled at Credit Approval" |
| `derived_decision` | Is a value calculated automatically? | "Application decision derived from sub loan decisions" |
| `validation` | Error messages, mandatory checks | "Validation error when amount is zero" |
| `state_movement` | Moving to next stage | "Move to next stage when all decisions filled" |
| `persistence` | Save and reopen behaviour | "Values retained on reopening the application" |
| `data_combination` | All/any/none/mixed scenarios | "Behaviour when some sub loans are approved and some rejected" |
| `edge` | Blank, null, duplicate edge cases | "Behaviour when recommended amount is blank" |

---

### `sections` — Intent Section Groups (UI Display)

**What it does:** Groups intents into sections shown in the web UI after extraction. Similar to `families` but used for display grouping.

Each section has:
- `key` — internal identifier
- `display_name` — the heading shown in the UI
- `terms` — words that route an intent into this section

You do not usually need to edit sections unless you are adding a completely new type of test behaviour that has no existing section.

---

### `matrix_terms` — Data Combination Keywords

**What it does:** Helps the intent extractor recognise matrix-style conditions — where the test should cover multiple data combinations (all approved, some approved, none approved, etc.).

```json
{ "key": "any",  "terms": ["if any", "any subloan", "at least one"] }
{ "key": "none", "terms": ["if none", "no subloan", "none selected"] }
```

Used when generating intents for stories that say things like "if all sub loans are recommended" or "if none are recommended".

You rarely need to edit this unless a new type of data matrix emerges.

---

### `state_transition_terms` — Stage Transition Keywords

**What it does:** A simple list of words that signal a "move to next stage" test. When these appear in a story, the intent extractor knows to generate state-transition intents.

```json
["credit approval", "committee approval", "disbursal", "recommendation", "stage"]
```

---

## Practical Guide: What to Edit When

| You want to... | Edit this node |
|----------------|----------------|
| Add a new loan product (LOB) | `lob_aliases` |
| Add a new CAS stage | `stages` |
| Teach the tool a new UI component name/alias | `entities` |
| Add a new alias for an existing component | `entities` → find entry → add to `aliases` |
| Change how intents are categorised | `families` → find family → add/remove `terms` |
| Add a completely new test behaviour type | `families` (new entry) + `sections` (new entry) |

---

## Important Rules

1. **Lowercase for matching.** All `phrases`, `aliases`, and `terms` should be lowercase. The matcher lowercases input before comparing.
2. **`canonical` is case-sensitive.** Use the exact casing you want in feature files (e.g. `"HL"` not `"hl"`).
3. **No code restart needed for most changes** — the config is loaded fresh per generation request. Server restart is required only for changes to `.env`.
4. **JSON must be valid** — a stray trailing comma will crash the server. Use a JSON validator if unsure.

---

## Full Example: Adding a New LOB

Say your team now handles "Tractor Loans" under the code `TL`:

```json
"lob_aliases": [
  ...existing entries...,
  { "canonical": "TL", "phrases": ["tractor loan", "tractor", "agri tractor"] }
]
```

After saving, the next generation request will:
- Recognise "tractor loan" in JIRA stories
- Map it to code `TL` in `#${ProductType:[...]}` headers and Examples tables
- Include `TL` in the UI LOB chip cloud
