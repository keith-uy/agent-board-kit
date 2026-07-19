#!/bin/zsh
# Generates and loads the two launchd jobs (worker + wake bridge) with correct
# absolute paths for THIS machine, so you never hand-edit a plist. Re-run any time
# to reload after a code change. macOS only.
set -euo pipefail

KIT="${0:A:h:h}"                 # repo root (this script is in launchd/)
LABEL_PREFIX="com.youragency"    # <-- change to your own reverse-domain prefix if you like
UID_N="$(id -u)"
LA="$HOME/Library/LaunchAgents"
mkdir -p "$LA" "$KIT/worker/state" "$KIT/wake/state"

# Resolve real interpreter paths on this machine.
PY="$(command -v python3)"
ZSH="$(command -v zsh)"

gen() {  # gen <label> <script-path> <logfile> <keepalive-dict>
  local label="$1" script="$2" logf="$3" keep="$4"
  cat > "$LA/$label.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>$label</string>
  <key>ProgramArguments</key>
  <array><string>$ZSH</string><string>$script</string></array>
  <key>RunAtLoad</key><true/>
  $keep
  <key>ThrottleInterval</key><integer>30</integer>
  <key>StandardOutPath</key><string>$logf</string>
  <key>StandardErrorPath</key><string>$logf</string>
</dict>
</plist>
PLIST
  launchctl bootout "gui/$UID_N/$label" 2>/dev/null || true
  launchctl bootstrap "gui/$UID_N" "$LA/$label.plist"
  echo "loaded $label"
}

KEEP='<key>KeepAlive</key><true/>'
gen "$LABEL_PREFIX.clickup-worker"         "$KIT/worker/run_worker.sh" "$KIT/worker/state/launchd.log" "$KEEP"
gen "$LABEL_PREFIX.clickup-webhook-bridge" "$KIT/wake/kick_bridge.sh"  "$KIT/wake/state/bridge.log"    "$KEEP"

echo "done. tail logs: tail -f $KIT/worker/state/launchd.log"
