# 🎙️ Voice-to-Agent Board

**Speak a task into your phone → an AI agent does the work → the result lands on your board. Runs on your Claude subscription, so $0 in API costs.**

A self-hosted system that turns one ClickUp list into a shared human + AI task board. You (or Siri, or a Back Tap) drop a task on the board; a local worker running headless Claude Code claims it, does the work, grades its own output, and writes the result back as a comment. If it needs your input, you get a **native ClickUp notification** on every device. If your Mac is asleep and a task is waiting, a **watchdog** pings you. When your Mac wakes, queued work runs automatically.

Built by **[WinflowAI](https://winflowai.com)** — simple automation for complex work.

---

## Why it's interesting

- **$0 marginal cost.** The agent runs through your local `claude -p` CLI on your Claude subscription. No Anthropic API bill, no per-token metering.
- **Voice capture from anywhere.** An iPhone Shortcut (Back Tap / "Hey Siri" / icon) dictates a task straight onto the board.
- **Event-driven, not polling.** A ClickUp webhook → n8n → ntfy → your Mac wakes the worker in ~1-2 seconds. A slow poll stays on purely as a backstop.
- **Native two-way collaboration.** When the agent needs you, a ClickUp Automation (via ClickBot) @mentions you so it shows on phone + desktop. You reply in a comment; the agent continues.
- **Self-healing.** A cloud watchdog alerts you if a task sits unworked (Mac asleep / worker down), and queued tasks auto-run the moment your Mac wakes.
- **Safe by default.** The worker runs in Claude Code's `auto` permission mode (a safety classifier reviews every action) plus a hard deny-list for destructive commands.

## Architecture

```
 iPhone (Dictate) ─┐
                   ├─► n8n Cloud ─► creates ClickUp task (Next + agent-ready)
 ClickUp UI ───────┘                        │
                                            ├─► ntfy (content-free "kick")
                                            ▼
                              your Mac: kick_bridge.sh ─► wake FIFO
                                            ▼
                              clickup_worker.py  ── claude -p (your subscription)
                                            │        grades + safety-checks output
                                            ▼
                              result comment on the task  ── or ──►  needs input?
                                                                      status → Waiting
                                                                      ClickBot @mentions you
                                                                      (native push, all devices)

 Cloud watchdog (n8n schedule): task stuck 15+ min → tag agent-stalled → ClickBot @mentions you
```

## Two ways to run it

Pick based on one question: **do you mind the agent only working while your Mac is awake?**

- **Local + Subscription** — runs on your Mac via Claude Code login. **$0 API cost**, but only works while the Mac is awake. Best for personal, cost-sensitive use.
- **Server + API** — runs on any always-on box (cloud VM, home server, Pi) via an Anthropic API key. **Metered cost**, but works **24/7** regardless of your devices — dictate a task on the go and it's done whether your Mac is on or not.

Full tradeoff table and the always-on server setup are in **[`DEPLOYMENT.md`](./DEPLOYMENT.md)**. The interactive `./configure.sh` sets either up.

## What you need

- **Local mode:** a **Mac** that's on when you want work to run. **Server mode:** any always-on Linux box.
- **[Claude Code](https://claude.com/claude-code)** installed. Local mode also needs `claude login` on a **Pro/Max plan** (for `auto` mode). Server mode needs an **Anthropic API key**.
- A **ClickUp** account (Free Forever works) + a personal API token.
- An **n8n** instance with a public webhook URL (n8n Cloud is easiest).
- An **iPhone/iPad** (optional — only for voice capture).

## Get started

1. **Choose a mode:** read [`DEPLOYMENT.md`](./DEPLOYMENT.md).
2. **Configure:** run `./configure.sh` (it asks which mode and writes your config), or copy `worker/.env.example`.
3. **Build it:** follow 👉 **[`SETUP.md`](./SETUP.md)** step by step.

Doing it with Claude Code? Open this folder in Claude Code and see **[`USE-WITH-CLAUDE.md`](./USE-WITH-CLAUDE.md)** for a prompt that walks it through for you.

## Layout

| Path | What's in it |
|---|---|
| `worker/` | The local worker: `clickup_worker.py`, `clickup_api.py`, evals, knowledge-base templates |
| `wake/` | Event-driven wake: `kick_bridge.sh` (ntfy listener), `register_webhook.py` |
| `n8n/` | Three importable workflow templates: wake ping, voice capture, watchdog |
| `clickup/` | `setup_board.py` (creates the board) + `automations.md` (the two ClickUp Automations) |
| `phone/` | iOS Shortcut build guide |
| `launchd/` | `install.sh` / `uninstall.sh` for the always-on macOS jobs |

---

<sub>Built by Keith Uy · [WinflowAI](https://winflowai.com) · If you want this set up for your team, or a custom agent workflow, reach out.</sub>
