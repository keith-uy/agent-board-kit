# Building this with Claude Code

You can hand the whole build to Claude Code. Open this folder in your terminal, run `claude`, and paste the prompt below. Claude will handle every `[machine]` step and walk you through the `[you]` steps (ClickUp, n8n, phone) as it reaches them.

> ⚠️ You still create the ClickUp token, click through the n8n imports, and build the iOS Shortcut yourself — those are outside the machine. Claude will tell you exactly what to do at each and wait for you.

---

## Prompt to paste into Claude Code

```
You're helping me install the Voice-to-Agent Board in this repo. First read
DEPLOYMENT.md and ask me which mode I want: A (local Mac + Claude subscription, $0 API
but tied to my Mac being awake) or B (always-on server + Anthropic API, metered but
24/7). Briefly give me the tradeoff, then configure that mode (you can run ./configure.sh).
Then read SETUP.md and implement it with me, phase by phase, in order. Rules:

- Do every [machine] step yourself (edit .env files, run scripts, install launchd jobs,
  register the ClickUp webhook). Never print my secrets back to the chat.
- For every [you] step (ClickUp UI, n8n import, iOS Shortcut), give me the exact clicks
  and values, then STOP and wait until I confirm before continuing.
- Ask me for my ClickUp token, list ID, ntfy topic, and n8n Production URLs when you
  need them — one at a time, as each phase requires.
- After each phase, run its verification step and show me the result before moving on.
- Do not skip the safety config: PERMISSION_MODE=auto and the deny-list in
  worker/workspace/.claude/settings.json.

Start with Phase 0 and confirm my prerequisites.
```

---

## What Claude will need from you (have these ready)

| When | You provide |
|---|---|
| Phase 1 | ClickUp personal API token, and a List ID for the board |
| Phase 3 | An ntfy topic name; the n8n Production URL for the wake workflow |
| Phase 4 | The n8n Production URL for the capture workflow |
| Phase 5-6 | You'll click through two ClickUp Automations and enable notifications |

Everything else (config files, scripts, launchd jobs, the ClickUp webhook registration) Claude does for you.
