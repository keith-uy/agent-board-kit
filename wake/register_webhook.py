#!/usr/bin/env python3
"""Register (or inspect) the ClickUp developer webhook for the agent board.

Creates a webhook scoped to CLICKUP_LIST_ID that fires on taskStatusUpdated +
taskTagUpdated and POSTs to your n8n Production URL. Prints the webhook `secret`
you must paste into n8n for X-Signature verification.

  python3 register_webhook.py            # create the webhook, print the secret
  python3 register_webhook.py --list     # list existing webhooks + health status
  python3 register_webhook.py --delete <webhook_id>

Config comes from webhook/.env (see .env.example). Standard library only.

Docs: developer.clickup.com/reference/createwebhook, /docs/webhooks
"""
import argparse
import json
import ssl
import sys
import urllib.error
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
API = "https://api.clickup.com/api/v2"
EVENTS = ["taskStatusUpdated", "taskTagUpdated"]


def _ssl_context():
    """Prefer certifi's CA bundle; python.org macOS builds ship an empty system
    CA store. Matches clickup_api.py so this script works wherever the worker does."""
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except Exception:  # noqa: BLE001
        return ssl.create_default_context()


_SSL = _ssl_context()


def load_env(path):
    env = {}
    if path.exists():
        for line in path.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            v = v.strip()
            if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'":
                v = v[1:-1]
            env[k.strip()] = v
    return env


def call(method, url, token, body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Authorization", token)
    req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=30, context=_SSL) as r:
            raw = r.read().decode()
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as e:
        sys.exit(f"ClickUp API {e.code}: {e.read().decode()[:500]}")
    except urllib.error.URLError as e:
        sys.exit(f"network error: {e}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--list", action="store_true", help="list webhooks + health")
    ap.add_argument("--delete", metavar="WEBHOOK_ID", help="delete a webhook by id")
    args = ap.parse_args()

    env = load_env(HERE / ".env")
    token = env.get("CLICKUP_TOKEN")
    team = env.get("CLICKUP_TEAM_ID")
    if not token or not team:
        sys.exit("CLICKUP_TOKEN and CLICKUP_TEAM_ID required in webhook/.env")

    if args.delete:
        call("DELETE", f"{API}/webhook/{args.delete}", token)
        print(f"deleted webhook {args.delete}")
        return

    if args.list:
        res = call("GET", f"{API}/team/{team}/webhook", token)
        hooks = res.get("webhooks", [])
        if not hooks:
            print("(no webhooks registered)")
            return
        for h in hooks:
            health = h.get("health") or {}
            print(f"- {h.get('id')}  status={health.get('status')} "
                  f"fail_count={health.get('fail_count')}  events={h.get('events')}")
            print(f"    endpoint: {h.get('endpoint')}")
        return

    list_id = env.get("CLICKUP_LIST_ID")
    endpoint = env.get("N8N_WEBHOOK_URL")
    if not list_id or not endpoint:
        sys.exit("CLICKUP_LIST_ID and N8N_WEBHOOK_URL required in webhook/.env")

    body = {"endpoint": endpoint, "events": EVENTS, "list_id": list_id}
    res = call("POST", f"{API}/team/{team}/webhook", token, body)
    hook = res.get("webhook", res)
    print("webhook created:")
    print(f"  id:     {hook.get('id')}")
    print(f"  events: {hook.get('events')}")
    print(f"  list:   {list_id}")
    print()
    print("  >>> PASTE THIS SECRET into the n8n workflow (WEBHOOK_SECRET):")
    print(f"      {hook.get('secret')}")


if __name__ == "__main__":
    main()
