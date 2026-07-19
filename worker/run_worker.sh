#!/bin/zsh
# launchd wrapper for the ClickUp agent worker. The plist
# (~/Library/LaunchAgents/com.winflowai.clickup-worker.plist) runs this with
# RunAtLoad + KeepAlive, so the worker polls whenever the Mac is awake and
# restarts if it dies. Safe to run by hand too.
#
# The worker itself is a long-running loop (polls every POLL_SECONDS); it reads
# CLICKUP_TOKEN / AUTH_MODE / PERMISSION_MODE from worker/.env. In subscription
# mode it draws Keith's Claude plan (ANTHROPIC_API_KEY stays unset).

set -uo pipefail
# Explicit PATH so launchd (minimal env) can find python3 and the claude CLI.
export PATH="/usr/local/bin:$HOME/.local/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin"

DIR="${0:A:h}"          # .../active/clickup-agent-system/worker
cd "$DIR" || exit 1
exec python3 clickup_worker.py
