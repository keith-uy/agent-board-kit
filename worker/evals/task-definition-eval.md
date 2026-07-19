# EVAL: Task Definition — "Is this task actually delegatable?"

**Applies to:** the TASK ITSELF, at dispatch (status `Next` + tag `agent-ready`), before the agent claims it. Being productive with agents is mostly defining constraints well; this eval enforces that.

## Checklist

1. **Done-state is testable.** A stranger could look at the output and say yes or no, it is done. "Improve the landing page" fails. "Rewrite the hero to lead with the $250K case study, under 40 words" passes.
2. **Constraints stated.** What must not change, what tools to use or avoid, budget / length / format limits.
3. **Context linked.** The task names its inputs (files, URLs, prior tasks) instead of assuming the agent will guess.
4. **Escalation defined.** What to do when blocked: comment and move to Waiting, never silently stall or improvise around a paywall or a permission.
5. **Right-sized.** Completable in one agent session (under ~2h equivalent). Bigger should be split.

## Adaptation for low-friction capture

Short one-line tasks (dictated on the fly) get **attempted** with `ASSUMPTION:` tags in the result comment rather than bounced. Only bounce a task when it is genuinely ambiguous or a wrong guess would be costly. Over-bouncing kills the system, so the default is attempt-with-assumptions.

## Output contract

```
VERDICT: DELEGATABLE | BOUNCE
MISSING: [numbered list of what the task needs before an agent can run it]
SHARPENED REWRITE: [the task rewritten to pass, with best guesses flagged ASSUMPTION:]
```

On BOUNCE, the runner posts MISSING + SHARPENED REWRITE as a comment, tags `waiting-on-you`, and moves the task to Waiting.
