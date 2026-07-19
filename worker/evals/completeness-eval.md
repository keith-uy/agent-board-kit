# EVAL: Completeness — "Did the deliverable meet the spec?"

**Applies to:** any deliverable claiming to be done. This runs before an agent moves a ClickUp task to **Done**. FAIL means loop and fix, never ship.

## Checks

1. **Every stated requirement met.** Walk the task title + description + comment thread line by line. Each constraint gets a ✓ or ✗ with evidence (a quote, a file path, a link). One unaddressed requirement = FAIL.
2. **Claimed artifacts exist.** Every file path, URL, and ID in the result comment actually resolves. "Saved to X" where X does not exist = instant FAIL.
3. **Tested, not just built.** If it is code or automation, was it run once end to end? Include the output of that run.
4. **QA-able in under 2 minutes.** The result comment includes absolute paths, direct links, and a short preview so the buyer can verify without reconstructing context.
5. **Failure honesty.** Anything skipped, partial, or flaky is stated plainly at the top of the result comment, not buried or omitted.

## Output contract

```
VERDICT: DONE | NOT DONE
REQUIREMENTS TABLE: [requirement -> ✓/✗ -> evidence]
UNVERIFIED CLAIMS: [anything asserted but not demonstrated]
```

Grade strictly. A borderline case is NOT DONE.
