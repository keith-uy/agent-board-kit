#!/usr/bin/env bash
# Interactive first-time setup: pick a deployment mode and write worker/.env
# plus the destructive-command deny-list. Safe to re-run. Works on macOS + Linux.
set -euo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"; cd "$DIR"

echo "== Agent Board setup =="
echo
echo "Which deployment? (see DEPLOYMENT.md for the full tradeoffs)"
echo "  1) Local + Subscription  — runs on THIS Mac, \$0 API cost, works only while the Mac is awake"
echo "  2) Server + API          — runs on any always-on box, metered API cost, 24/7 device-independent"
read -rp "Choose 1 or 2: " MODE

read -rp "ClickUp personal token (pk_...): " TOKEN
read -rp "ClickUp List ID: " LIST

if [ "$MODE" = "2" ]; then
  AUTH=api;          PMODE=bypassPermissions; POLL=60
  read -rp "Anthropic API key (sk-ant-...): " APIKEY
else
  AUTH=subscription; PMODE=auto;              POLL=600; APIKEY=""
fi

python3 - "$AUTH" "$TOKEN" "$LIST" "$APIKEY" "$PMODE" "$POLL" <<'PY'
import sys, re, pathlib
auth, token, lst, apikey, pmode, poll = sys.argv[1:7]
t = pathlib.Path("worker/.env.example").read_text()
def setk(t,k,v):
    return re.sub(rf'(?m)^{k}=.*', f'{k}={v}', t) if re.search(rf'(?m)^{k}=', t) else t.rstrip()+f'\n{k}={v}\n'
for k,v in [('CLICKUP_TOKEN',token),('CLICKUP_LIST_ID',lst),('AUTH_MODE',auth),
            ('PERMISSION_MODE',pmode),('POLL_SECONDS',poll)]:
    t=setk(t,k,v)
if auth=='api':
    t=setk(t,'ANTHROPIC_API_KEY',apikey)
pathlib.Path("worker/.env").write_text(t)
print("wrote worker/.env  (AUTH_MODE=%s, PERMISSION_MODE=%s, POLL_SECONDS=%s)" % (auth,pmode,poll))
PY

mkdir -p worker/workspace/.claude
cat > worker/workspace/.claude/settings.json <<'JSON'
{ "permissions": { "deny": [
  "Bash(rm:*)","Bash(sudo:*)","Bash(shutdown:*)",
  "Bash(reboot:*)","Bash(dd:*)","Bash(mkfs:*)","Bash(diskutil:*)"
] } }
JSON
echo "wrote worker/workspace/.claude/settings.json (destructive-command deny-list)"
echo
if [ "$MODE" = "2" ]; then
  echo "Next: deploy on your always-on server -> see DEPLOYMENT.md (Profile B / systemd)."
else
  echo "Next: zsh launchd/install.sh    # loads the worker + wake bridge on this Mac"
fi
