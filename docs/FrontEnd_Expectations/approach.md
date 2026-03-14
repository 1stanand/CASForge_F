A better approach is to make generation more constrained and staged, not “more powerful.” For this problem, better usually means less freedom for the model.

**What Will Improve Accuracy**
The biggest gain will likely come from turning CASForge into a retrieval-first composer instead of a retrieval-assisted writer.

1. Make the LLM plan, not write.
   The LLM should produce:

- short intents
- family labels
- scope
- action target
- expected outcome type

Then deterministic code should do most of the actual scenario assembly from repo material.

2. Retrieve whole scenario chains, not individual steps.
   Right now even with good retrieval, assembly still has room to mix unrelated pieces.
   A stronger strategy is:

- pick one anchor scenario
- keep its setup chain
- keep its action chain
- only swap assertion if needed
  That will make output look more like real repo writing.

3. Add stricter “scenario eligibility” filters before assembly.
   Before a candidate scenario can contribute steps, require enough overlap on:

- stage
- module/screen
- entity
- action family
- business vocabulary from intent
  This will remove a lot of semantically wrong but syntactically valid matches.

4. Score scenarios, not just steps.
   For CAS, scenario coherence matters more than isolated step similarity.
   A good candidate scenario should score on:

- anchor action similarity
- setup relevance
- assertion relevance
- scope match
- annotation/dictionary compatibility

5. Use a “do not mix domains” rule.
   If anchor is from committee/recommendation/omni-decision context, do not pull setup/assertion from unrelated domains like collateral, liability, CERSAI, etc.
   That one rule alone could cut a lot of bad output.

**Faster And Better Workflow**
Your earlier idea was good, and I think it is the right long-term workflow:

1. Test parser separately.
2. Test intent planner separately.
3. Test anchor selection separately.
4. Test assertion retrieval separately.
5. Test scenario assembly on 2-3 intents only.
6. Run one full JIRA only after those pass.

That is faster and usually improves quality faster than repeated full end-to-end runs.

**Best Practical Upgrade**
If I had to choose one next design improvement, I would do this:

- LLM only creates a compact scenario plan JSON
- code retrieves 1 primary anchor scenario per intent
- code assembles from that scenario with very limited substitution
- code rejects cross-domain/cross-stage contamination
- unresolved parts stay explicitly marked

That is much more controllable than asking the model to “generate a feature.”

So yes, there is a better approach:
more constraints, more deterministic assembly, more scenario-level scoring, less freeform generation.

If you want, I can take the next pass specifically in that direction and rework the assembler around “anchor scenario eligibility + domain lock + minimal substitution.” : YES
