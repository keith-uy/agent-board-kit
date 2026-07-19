#!/bin/zsh
# Outbound-only wake bridge.
#
# Holds a streaming connection to an ntfy topic and pokes the worker's wake FIFO
# on each message, so the worker runs a cycle immediately instead of waiting for
# its next timed poll. This Mac opens NO inbound port and needs NO tunnel: the
# only connection is this outbound stream. The ntfy message carries no task data,
# it is a content-free "something changed" ping, so the public topic leaks nothing
# even if guessed. The worker re-reads ClickUp directly to learn what changed.
#
# Run under launchd (com.winflowai.clickup-webhook-bridge.plist, KeepAlive) so it
# reconnects across sleep/wake. Safe to run by hand for testing.
set -uo pipefail
export PATH="/usr/local/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin"

DIR="${0:A:h}"                       # .../active/clickup-agent-system/webhook
ENV_FILE="$DIR/.env"
[ -f "$ENV_FILE" ] && source "$ENV_FILE"
: "${NTFY_URL:?set NTFY_URL in webhook/.env (e.g. https://ntfy.sh/winflow-clickup-<random>)}"
FIFO="$DIR/../worker/state/wake.fifo"

log() { print -r -- "$(date -u +%Y-%m-%dT%H:%M:%SZ) [bridge] $*"; }

# Non-blocking poke: if the worker (the FIFO reader) is down, ENXIO is ignored and
# the worker's own timed poll will catch the task instead. Never blocks the stream.
poke() {
  python3 - "$FIFO" <<'PY' 2>/dev/null || true
import os, sys
try:
    fd = os.open(sys.argv[1], os.O_WRONLY | os.O_NONBLOCK)
    os.write(fd, b"x"); os.close(fd)
except OSError:
    pass  # no reader / no fifo yet; timed poll covers it
PY
}

log "starting; streaming ${NTFY_URL%/}/raw"
while true; do
  # Poke once on every (re)connect: at startup, after a network blip, and
  # crucially after the Mac wakes from sleep (the stream drops while asleep).
  # This makes the worker re-check the board within ~2s of waking, so anything
  # queued while the Mac slept runs immediately instead of waiting for the poll.
  log "connect; nudging worker to catch up on anything missed while disconnected"
  poke
  # -sN: silent, unbuffered stream. ntfy /raw emits one line per message and a
  # blank keepalive line periodically. read exits when the stream drops.
  curl -sN "${NTFY_URL%/}/raw" 2>/dev/null | while IFS= read -r line; do
    [ -z "$line" ] && continue       # keepalive, not a real message
    log "kick"
    poke
  done
  log "stream ended; reconnecting in 3s"
  sleep 3
done
