#!/bin/zsh
# Stops and removes both launchd jobs. Your code and config stay put.
set -uo pipefail
LABEL_PREFIX="com.youragency"
UID_N="$(id -u)"
for name in clickup-worker clickup-webhook-bridge; do
  label="$LABEL_PREFIX.$name"
  launchctl bootout "gui/$UID_N/$label" 2>/dev/null && echo "stopped $label" || echo "($label not loaded)"
  rm -f "$HOME/Library/LaunchAgents/$label.plist"
done
echo "removed. (n8n workflows + ClickUp automations are separate — disable those in their UIs.)"
