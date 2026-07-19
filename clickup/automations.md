# ClickUp Automations (native notifications)

Two Automations turn ClickUp itself into your alerting channel — on **both** phone and desktop, no extra app.

## Why an Automation and not just a comment?

The worker acts through **your own** ClickUp API token, and ClickUp suppresses notifications for your own actions. So the worker commenting "I need input" never notifies you. The fix: let **ClickBot** (ClickUp's automation actor, user id `-1`, a *different* identity) do the notifying. Its @mention of you is a normal cross-user notification and fires on all your devices.

> Enable it first: **Settings → Notifications** → turn on **mobile push** for **Mentions**, **Comments**, and **ClickBot** (ClickBot is a separate toggle; if it's muted, none of this reaches you).

---

## Automation 1 — Needs your input

- **When:** Status changes → **To: Waiting**
- **Then:** Add comment:
  ```
  🤖 @You the agent needs your input — see the note above.
  ```
- **Save.**

## Automation 2 — Stuck-task watchdog alert

- **When:** Tag added → **agent-stalled**
- **Then:** Add comment:
  ```
  🤖 @You ⚠️ this task has been sitting unworked for 15+ min — is your Mac awake?
  ```
- **Save.**

> If `agent-stalled` doesn't appear in the tag picker, it's because ClickUp only lists tags currently applied to a task. Apply it to any one task once, refresh, and it'll show.

---

## ⚠️ The one non-negotiable detail

**Both automation comments MUST start with `🤖`** (and are posted by ClickBot). Here's why: the worker decides "did the human reply?" by looking at the newest comment on a `waiting-on-you` task. A plain comment from ClickBot would be read as *your* reply and re-dispatch the task in a loop.

The worker code guards against this two ways — it ignores comments **from ClickBot (user id `-1`)** and any comment **starting with `🤖`**. Starting the automation comment with the robot emoji is your belt-and-suspenders. You reply with a **normal** comment (no `🤖`) and the worker correctly picks it up.
