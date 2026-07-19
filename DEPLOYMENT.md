# Choose your deployment

There are two ways to run this, and the choice comes down to one question: **do you mind the agent only working while your Mac is awake?**

| | **A · Local + Subscription** | **B · Server + API** |
|---|---|---|
| Runs on | Your Mac | Any always-on box (cloud VM, home server, Raspberry Pi, container) |
| Auth | Your Claude Code login (`claude login`) | `ANTHROPIC_API_KEY` |
| Marginal cost | **$0** (uses your Claude plan) | **Metered** per token (Anthropic API bill) |
| Availability | Only when your Mac is **awake + online** | **24/7**, independent of any personal device |
| "Is my machine awake?" | A real concern — that's why the wake webhook + watchdog exist | Not a concern — it never sleeps |
| Permission mode | `auto` (safety classifier; needs a Claude plan) + deny-list | `bypassPermissions` in an isolated VM/container + deny-list |
| Process manager | `launchd` (macOS) | `systemd` (Linux) / Docker / `nohup` |
| Best for | Personal use, cost-sensitive, you keep a Mac on anyway | Teams, hands-off reliability, capturing tasks on the go |

**Rule of thumb:**
- Want **$0 cost** and you're usually at your Mac → **Profile A**.
- Want it to **just work 24/7** regardless of your devices (e.g. you dictate tasks while out and expect them done) → **Profile B**.

> Two combinations to avoid: **API on your own Mac** (you pay per token *and* it's still tied to your Mac being awake — worst of both), and **subscription on a server** (subscription auth is meant for your interactive machine, not a shared always-on host). Match auth to where it runs: subscription↔Mac, API↔server.

---

## Profile A — Local + Subscription (the default)

Follow `SETUP.md` as written. Config:
```
AUTH_MODE=subscription
PERMISSION_MODE=auto
```
The wake webhook (Phase 3) and watchdog (Phase 6) matter here, because your Mac sleeps. Nothing else to do.

---

## Profile B — Server + API (always-on)

Run the exact same worker on a small always-on Linux box. Because the server never sleeps, the "Mac awake" problem disappears — the watchdog and even the wake webhook become optional (a server can just poll cheaply).

### 1. Get a box
Any always-on Linux host works: a $4-6/mo cloud VM (Hetzner, DigitalOcean, Lightsail…), a home server, or a Raspberry Pi. You need Python 3.9+ and the Claude Code CLI installed.

### 2. Configure for API
```
AUTH_MODE=api
ANTHROPIC_API_KEY=sk-ant-...        # your Anthropic API key
PERMISSION_MODE=bypassPermissions   # safe here: it's an isolated throwaway box, and the
                                    # deny-list still hard-blocks rm/sudo/etc. in every mode
CLAUDE_MODEL=claude-opus-4-8        # any current API model id
POLL_SECONDS=60                     # a server can poll often; the wake webhook is optional
```
> Why `bypassPermissions` here instead of `auto`? `auto` mode's safety classifier requires a Claude **subscription plan**, which an API-only setup doesn't have. On an isolated server, `bypassPermissions` + the deny-list is the standard headless config. Keep the deny-list at `worker/workspace/.claude/settings.json` — deny rules apply in *every* mode, including bypass. If you want a stricter posture, use `PERMISSION_MODE=dontAsk` plus an `allow` list (see Claude Code's permissions docs).

### 3. Run it 24/7 with systemd
```bash
sudo cp linux/clickup-worker.service.template /etc/systemd/system/clickup-worker.service
sudo nano /etc/systemd/system/clickup-worker.service   # set User= and the WorkingDirectory/ExecStart paths
sudo systemctl daemon-reload
sudo systemctl enable --now clickup-worker
journalctl -u clickup-worker -f                        # watch the log
```
Or run it in Docker / under `nohup`/`tmux` if you prefer.

### 4. Wake path is optional on a server
With `POLL_SECONDS=60` a server picks up tasks within a minute with zero extra infrastructure — skip Phases 3 (wake webhook) and 6 (watchdog) entirely if you like. Want instant (~2s) pickup anyway? The ntfy bridge works on Linux too (it's just `curl` + a FIFO); run `wake/kick_bridge.sh` under its own systemd unit.

### 5. Voice capture + notifications still work
Phases 4 (voice capture) and 5 (needs-input notifications) are unchanged — they live in n8n and ClickUp, not on the worker box.

---

## Switching later
The mode is just config. To move from A to B (or back), copy your `worker/.env`, change `AUTH_MODE` + `PERMISSION_MODE` (+ `ANTHROPIC_API_KEY` for API), and start the worker on the new host. The board, n8n workflows, and Shortcut don't change.
