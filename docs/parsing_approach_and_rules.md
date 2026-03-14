# CASForge â€” Parsing Approach and Rules

## What Gets Parsed

CASForge parses CAS ATDD Gherkin `.feature` files from the features repository
(`FEATURES_REPO_PATH` in `.env`). The parser is purpose-built for CAS-specific extensions
to standard Gherkin â€” it handles patterns that no generic Gherkin parser would survive.

**Key files**:
- `src/casforge/parsing/feature_parser.py` â€” core parser
- `src/casforge/parsing/screen_context.py` â€” navigation anchor â†’ canonical screen name
- `src/casforge/shared/normalisation.py` â€” `SCREEN_NAME_MAP` (182+ entries), `LOB_MAP`, `STAGE_MAP`

---

## Running the Parser

```bat
# Incremental (only new/changed files)
ingest_incremental.bat

# Full rebuild (drops all data, re-parses everything)
ingest_full_rebuild.bat
```

Both bat files also rebuild the FAISS vector index after parsing.

---

## Incremental Parsing

**How it works**:

1. Load all `{file_path: file_mtime}` from the `features` table
2. Scan all `.feature` files on disk under `FEATURES_REPO_PATH`
3. For each file on disk:
   - **Not in DB** (new): parse and insert
   - **In DB, same mtime**: skip (unchanged)
   - **In DB, different mtime**: DELETE the features row (cascade removes all scenarios + steps), then re-parse
4. For each file in DB that is no longer on disk (deleted): DELETE the features row

**Why mtime**: Faster than hashing file contents. If the file hasn't changed since last
parse, `os.path.getmtime()` returns the same float. Any save, even touching the file,
updates the mtime and triggers re-parse.

**Result**: Safe to run daily or after every `git pull` â€” only real changes are processed.
A full run on an unchanged repo completes in seconds.

---

## CAS-Specific Gherkin Extensions

CAS `.feature` files contain several non-standard constructs that break generic parsers:

### 1. Dictionary Entries (`#${Key=[...]}`)

```gherkin
#${LoanType=["Home Loan", "Personal Loan"]}
#${Status=['Active', 'Pending']}
```

These appear as comments but carry structured data. The parser extracts them into JSONB.

**Pattern**: `\$\{(\w+)\s*=\s*\[([^\]]*)\]\}`
Handles both `"` and `'` delimiters. Values are comma-split and stripped.

### 2. Annotations (`@Tag`)

Standard in Gherkin but CAS uses many more than typical:
- File-level: before `Feature:` keyword
- Scenario-level: before `Scenario:` or `Scenario Outline:`
- Block-level: before `Examples:` inside a Scenario Outline

Stage tags like `@Recommendation`, `@DDE`, `@CreditApproval` appear on **Examples blocks**,
not on Scenarios. This is a critical CAS convention that must be handled correctly.

Special CAS annotations:
- `@Order` / `@E2EOrder` â€” marks workflow-ordering files
- `@AuthoredBy: Name` â€” annotation with colon, stored as full string
- Annotations with spaces: `@ Tag` â€” whitespace stripped after `@`

### 3. Annotations on Examples Blocks

```gherkin
Scenario Outline: Guarantor edit at Recommendation stage
    Given prerequisite steps...
    When user fills in guarantor details
    Then details should be saved

    @Recommendation @AppInfo @Guarantor
    Examples:
      | header1 | header2 |
      | value1  | value2  |
```

The `@Recommendation @AppInfo @Guarantor` line belongs to the `Examples:` block,
stored in `example_blocks.block_annotations`.

---

## Parser Edge Cases Handled

| Edge Case | Handling |
|---|---|
| BOM (`\ufeff`) at file start | Stripped before any processing |
| CRLF line endings | `line.rstrip('\r\n')` consistently applied |
| Non-UTF-8 encoding | `open(path, encoding='utf-8', errors='replace')` |
| `@Order` + dicts in same file | `has_conflict=TRUE`, warning logged, both still parsed |
| Empty feature file | Insert features row with `parse_error='empty file'` |
| No scenarios in file | Insert features row only (no scenarios/steps) |
| Background: section | Parsed as scenario with title `__background__`, steps injected into all other scenarios in file |
| `And` / `But` at start of file | Treated as `Given` defensively |
| Doc strings (`"""..."""`) | Captured as part of step text |
| Blank scenarios (title only, no steps) | Inserted with empty steps list |
| Duplicate `Feature:` in one file | First occurrence wins, warning logged |
| Annotation with spaces (`@ Tag`) | Whitespace stripped after `@` |
| `@AuthoredBy: name` | Stored as full string including colon |
| Scenario with no title | Stored as NULL |
| Steps with no keyword | Appended to previous step text |

---

## Screen Context Inference

After parsing all steps in a scenario, the parser infers `screen_context` by scanning
for navigation anchor steps.

**Anchor patterns** (from `src/casforge/parsing/screen_context.py`):

```
opens [the] <name> [screen|page|tab|accordion|drawer]
navigates to [the] <name> [screen|page|tab|accordion|drawer]
moves to [the] <name> [...]
selects [the] <name> [tab|accordion|drawer|screen|page]
clicks on [the] <name> [tab|accordion|drawer|screen|page]
```

**Assignment**: Once an anchor is found, all subsequent steps in the scenario inherit
that screen context until a new anchor is encountered.

**Normalisation**: The extracted phrase is lowercased, articles stripped, whitespace
collapsed, then looked up in `SCREEN_NAME_MAP` (182+ entries in `src/casforge/shared/normalisation.py`).

Examples:
- `"applicant info"` â†’ `"Applicant Information"`
- `"kyc screen"` â†’ `"KYC"`
- `"credit approval"` â†’ `"Credit Approval"`

Steps before any navigation anchor have `screen_context = NULL`.

---

## Data Storage Structure

For each `.feature` file, the parser produces:

```
features (1 row)
  â””â”€â”€ scenarios (N rows, one per Scenario/Scenario Outline)
        â”œâ”€â”€ example_blocks (M rows, only for Outlines)
        â””â”€â”€ steps (P rows, includes background steps)
```

Background steps are duplicated into each scenario's step list so that every scenario
is self-contained â€” retrieval returns the full runnable scenario context.

---

## Error Handling

If any step of parsing fails:
- The `features.parse_error` column records the exception message
- The partially-parsed data is still inserted (scenarios/steps up to the error point)
- Parsing continues with the next file â€” one bad file doesn't stop the batch

Check `SELECT * FROM v_parse_errors;` after any ingest to review failures.

---

## Incremental Build Flow

```
tools/cli/ingest.py
â”‚
â”œâ”€â”€ Compare disk mtimes vs DB mtimes
â”œâ”€â”€ Delete changed/removed files from DB (cascade)
â”œâ”€â”€ Parse new/changed files â†’ insert features/scenarios/steps
â””â”€â”€ Report: N new, M changed, P deleted, Q unchanged

tools/cli/build_index.py (always run after ingest)
â”‚
â”œâ”€â”€ SELECT id, step_text FROM unique_steps
â”œâ”€â”€ Embed in batches of 256 (all-MiniLM-L6-v2)
â”œâ”€â”€ L2-normalise
â”œâ”€â”€ Build FAISS IndexFlatIP
â””â”€â”€ Save workspace/index/faiss_index.bin + workspace/index/step_id_map.npy
```






