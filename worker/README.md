# Subscription Worker

A self-contained Python worker that turns one ClickUp list into a shared human + AI task board. It polls for tasks you have marked ready, runs them on your own Claude login, checks its own work, and writes the result back as a comment. No dependencies beyond Python 3.9+ and the Claude Code CLI.

## What it does each cycle

1. Recovers any task left half-done by a crash (stale-claim sweep).
2. Checks `waiting-on-you` tasks for a human reply and re-dispatches those.
3. Picks up tasks that are status **Next** and tag **agent-ready** (and not already claimed), up to `MAX_PER_CYCLE`.

For each task it claims it (adds `agent-claimed`, moves to **Doing**, comments "starting"), runs it via `claude -p`, grades the output with the completeness eval (one revision on fail), runs the publish-safety gate, then moves it to **Done** with a result comment or to **Waiting** + `waiting-on-you` with an honest note.

The full board contract is in `../template/board-contract.md`.

## Setup (5 steps)

1. **Stand up the board** in ClickUp per `../template/clickup-template-setup.md` (statuses, tags). Copy the **List ID** from the list URL.
2. **Get a ClickUp personal token:** ClickUp → Settings → Apps → Generate (`pk_...`).
3. **Choose auth mode:**
   - **subscription** (recommended): on this machine run `claude login` once. Make sure `ANTHROPIC_API_KEY` is not set in your shell. The worker draws your Claude plan at no marginal cost.
   - **api:** set `AUTH_MODE=api` and `ANTHROPIC_API_KEY`. Billed per token, no login needed.
4. **Configure:** `cp .env.example .env` and fill in `CLICKUP_TOKEN`, `CLICKUP_LIST_ID`, `AUTH_MODE`.
5. **Fill your knowledge base:** copy the `*.example.md` files in `../knowledge-base/` to their real names and put your preferences, tone samples, and SOPs in them. This is the biggest quality lever.

## Run

```bash
python3 clickup_worker.py --dry-run   # see what it would do, no writes
python3 clickup_worker.py --once      # one real cycle
python3 clickup_worker.py             # loop forever (POLL_SECONDS apart)
```

To keep it running, wrap it in a launchd job (macOS) or systemd service (Linux), or run it under `caffeinate`/`nohup`. Only one worker runs at a time; a second start exits on the lockfile.

## Notes

- Secrets live only in `.env` (gitignored). Never in task text or comments.
- Agent comments start with 🤖 so the worker can tell its own comments from your replies.
- `state/seen.json` tracks claim/done state for crash recovery. Safe to delete when the worker is stopped; it rebuilds from the board.
- Rate limit is 100 requests/min on ClickUp Free; the worker backs off on 429 automatically.
- The worker runs tasks with `claude -p --permission-mode acceptEdits`, and the task title, description, and comments are fed straight into the prompt. Keep the board to people you trust to write instructions for an agent that can edit files in `WORK_DIR`. Do not point this at a board that untrusted outsiders can post to.
