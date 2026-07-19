# Setup Guide

Build the whole system in order. Each phase is independently testable, so stop and verify before moving on. Steps are marked **[you]** (a human action in a web/phone UI) or **[machine]** (a terminal command on your Mac, which Claude Code can run).

**Legend of placeholders** you'll fill in as you go:
- `YOUR_CLICKUP_TOKEN` — a ClickUp personal API token (`pk_...`), from ClickUp → Settings → Apps → API Token.
- `YOUR_LIST_ID` — the ID of the ClickUp list you'll use as the board (it's in the list URL).
- `YOUR_TEAM_ID` / `YOUR_SPACE_ID` — your workspace and space IDs (the setup script prints them).
- `YOUR_NTFY_TOPIC` — an unguessable topic name, e.g. `agent-board-9f3a7c2e1b`.
- `YOUR_N8N_HOST` — your n8n instance host, e.g. `you.app.n8n.cloud`.

---

## Choose your deployment first

Before Phase 0, decide **[`DEPLOYMENT.md`](./DEPLOYMENT.md)**:
- **A · Local + Subscription** — on your Mac, $0 API, works while the Mac is awake. (This guide's default.)
- **B · Server + API** — on an always-on box, metered, 24/7.

The build below is written for **Profile A**. For **Profile B**, the only differences are: set `AUTH_MODE=api` + `PERMISSION_MODE=bypassPermissions` in Phase 2, run the worker under **systemd** instead of launchd (`linux/clickup-worker.service.template`), and treat the wake webhook (Phase 3) + watchdog (Phase 6) as optional (a server can just poll). See `DEPLOYMENT.md` Profile B.

---

## Phase 0 — Prerequisites [you]

1. A **Mac**, on when you want work to run.
2. **Claude Code** installed and logged in: run `claude login` once. Confirm you're on a **Pro/Max plan** (needed for `auto` permission mode + Opus). Make sure `ANTHROPIC_API_KEY` is **unset** in your shell so it draws your subscription.
3. **Python 3.9+** and **zsh** (macOS default).
4. A **ClickUp** account + personal API token.
5. An **n8n** instance with public webhooks (n8n Cloud is simplest).
6. (Optional) an **iPhone** for voice capture.

---

## Phase 1 — Create the ClickUp board

The board is one ClickUp **list** with four statuses and a few tags. See `clickup/board-setup.md` for the exact contract. Fastest path:

1. **[you]** Create a list (any Space) to be your agent board. Copy its **List ID** from the URL.
2. **[machine]** Fill `clickup/.env` isn't needed — the script reads flags. Run:
   ```bash
   python3 clickup/setup_board.py --token YOUR_CLICKUP_TOKEN --list YOUR_LIST_ID
   ```
   It creates the statuses (**Next, Doing, Waiting, Done**) and tags (**agent-ready, agent-claimed, waiting-on-you, agent-stalled**), and prints your **Team ID** and **Space ID**. Save those.

   Prefer to do it by hand? Follow `clickup/board-setup.md`.

---

## Phase 2 — The worker (local execution)

1. **[machine]** Configure the worker. Easiest: run the interactive script, which asks
   which deployment mode and writes `worker/.env` + the deny-list for you:
   ```bash
   ./configure.sh
   ```
   Or do it by hand — `cp worker/.env.example worker/.env` and set at least:
   ```
   CLICKUP_TOKEN=YOUR_CLICKUP_TOKEN
   CLICKUP_LIST_ID=YOUR_LIST_ID
   # Profile A (local + subscription):
   AUTH_MODE=subscription
   PERMISSION_MODE=auto          # safety classifier; needs a Claude plan
   POLL_SECONDS=600              # backstop; the wake webhook carries real-time
   # Profile B (server + API) instead:
   #   AUTH_MODE=api
   #   ANTHROPIC_API_KEY=sk-ant-...
   #   PERMISSION_MODE=bypassPermissions   # only on an isolated server/VM
   #   POLL_SECONDS=60
   CLAUDE_MODEL=claude-opus-4-8
   ```
   (`configure.sh` also writes step 2's deny-list, so you can skip step 2 if you used it.)
2. **[machine]** Add the destructive-command deny-list (a hard block that applies in every permission mode):
   ```bash
   mkdir -p worker/workspace/.claude
   cat > worker/workspace/.claude/settings.json <<'JSON'
   { "permissions": { "deny": [
     "Bash(rm:*)","Bash(sudo:*)","Bash(shutdown:*)",
     "Bash(reboot:*)","Bash(dd:*)","Bash(mkfs:*)","Bash(diskutil:*)"
   ] } }
   JSON
   ```
3. **[you]** Fill your knowledge base — copy `worker/knowledge-base/*.example.md` to real names and add your preferences, tone samples, and SOPs. **This is the biggest quality lever.**
4. **[machine]** Smoke-test one cycle without a daemon:
   ```bash
   cd worker && python3 clickup_worker.py --dry-run   # see intended actions
   python3 clickup_worker.py --once                   # one real cycle
   ```
   Create a task in **Next** + tag **agent-ready** and confirm the worker claims it, runs, and comments a result.
5. **[machine]** Install it as an always-on job:
   - **Profile A (Mac):** `zsh launchd/install.sh` then `tail -f worker/state/launchd.log` (look for `[start]` and `[wake] listening`).
   - **Profile B (Linux server):** use `linux/clickup-worker.service.template` with systemd — see `DEPLOYMENT.md` Profile B.

At this point you have a working agent board (poll-driven). The remaining phases add instant wakes, voice capture, notifications, and the watchdog.

---

## Phase 3 — Event-driven wake (instant pickup)

Turns polling into ~1-2s pickup, without opening any inbound port on your Mac. Full detail in `wake/` and `n8n/1-wake-ping.json`.

1. **[you]** Pick an unguessable ntfy topic (`YOUR_NTFY_TOPIC`). `cp wake/.env.example wake/.env` and set `NTFY_URL=https://ntfy.sh/YOUR_NTFY_TOPIC`.
2. **[you]** In n8n, **Import** `n8n/1-wake-ping.json`. Set the webhook node's **path** to a long random string, and the ntfy node's **url** to your `NTFY_URL`. **Save + Activate.** Copy the **Production** webhook URL.
3. **[machine]** Register the ClickUp webhook (list-scoped, fires on status/tag changes):
   Fill `wake/.env` with `CLICKUP_TOKEN`, `CLICKUP_TEAM_ID`, `CLICKUP_LIST_ID`, and `N8N_WEBHOOK_URL` (the Production URL), then:
   ```bash
   python3 wake/register_webhook.py            # creates it, prints a secret
   python3 wake/register_webhook.py --list      # confirm status=active
   ```
4. **[machine]** The bridge is already installed by `launchd/install.sh` (Phase 2). Restart it to pick up the topic:
   ```bash
   zsh launchd/install.sh
   ```
5. **Test:** move a task to **Next** + **agent-ready**. Within ~2s the worker log should show `[wake] poked by webhook bridge`. (Manual check: `curl -d kick https://ntfy.sh/YOUR_NTFY_TOPIC` → bridge logs a `kick`.)

---

## Phase 4 — Voice capture from your phone

1. **[you]** In n8n, **Import** `n8n/2-add-agent-task.json`. In the **Create ClickUp Task** node, replace `REPLACE_WITH_YOUR_LIST_ID` and paste `YOUR_CLICKUP_TOKEN` into the Authorization header. Set the ntfy node url. **Save + Activate.** Copy the Production URL.
2. **[you]** Build the iOS Shortcut per `phone/ios-shortcut.md` (Dictate Text → guard → POST `{ "task": <dictated> }` to that Production URL). Wire it to Back Tap / Siri / an icon.
3. **Test:** run the Shortcut, speak a task, watch it appear on the board and get worked.

> The n8n workflow reads `$json.body.task || $json.body.Value` — the `|| Value` tolerates a known iOS Shortcuts JSON-body quirk. Keep it.

---

## Phase 5 — "Needs your input" notifications

When the worker can't finish, it sets the task to **Waiting**. Because the worker acts as *your* ClickUp user, ClickUp won't self-notify you — so a ClickUp Automation (run by ClickBot, a separate actor) does the notifying. Details + screenshots-worth-of-steps in `clickup/automations.md`.

1. **[you]** ClickUp → your list → **Automate → Create Custom Automation**:
   - **When:** *Status changes* → To **Waiting**
   - **Then:** *Add comment* → start it with a robot emoji and @mention yourself, e.g. `🤖 @You the agent needs your input — see the note above.`
   - **Save.**
2. **[you]** Enable notifications: ClickUp → Settings → Notifications → ensure **mobile push** is on for **Mentions**, **Comments**, and **ClickBot** (ClickBot is a separate toggle).
3. **Test:** it fires automatically the next time a task can't complete. To force it, set any task's status to Waiting.

> **Critical:** the automation comment MUST start with `🤖` (or be from ClickBot). The worker ignores comments from ClickBot and any starting with `🤖`, so the alert can't be mistaken for your reply. The worker code already handles this by author (`ClickBot`, user id `-1`).

---

## Phase 6 — Watchdog (self-healing)

The worker only runs while your Mac is awake, so a task captured while you're away could sit silently. This cloud watchdog catches that (and any worker crash).

1. **[you]** In n8n, **Import** `n8n/3-watchdog.json`. Set the list ID + token in both HTTP nodes. **Save + Activate.**
2. **[you]** Create a second ClickUp Automation:
   - **When:** *Tag added* → **agent-stalled**
   - **Then:** *Add comment* → `🤖 @You ⚠️ this task has been sitting unworked for 15+ min — is your Mac awake?`
   - **Save.**
   > If `agent-stalled` isn't in the tag dropdown, apply it to any one task once (ClickUp only lists in-use tags), then refresh.
3. **How it behaves:** a task stuck 15+ min gets tagged `agent-stalled` → the automation @mentions you (once per task — the tag latches it). When your Mac wakes, the bridge pokes the worker on reconnect and the task runs within ~2s.

---

## Verify the whole loop

Speak a task on your phone → it appears on the board → the worker runs it (~seconds) → a `🤖 Done` comment lands. Put a task in Waiting → you get a native push. Let a task sit with the worker stopped → the watchdog pings you after ~15 min.

## Rollback

```bash
zsh launchd/uninstall.sh                       # stop the Mac jobs
python3 wake/register_webhook.py --list         # then --delete <id> for the ClickUp webhook
```
Disable/delete the n8n workflows and ClickUp Automations in their own UIs.
