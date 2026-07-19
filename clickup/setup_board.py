#!/usr/bin/env python3
"""Idempotent ClickUp board installer for the agent system.

Creates (or reuses) the "Agent Board" Space + List, the four tags, tries to set
the five custom statuses, runs a live smoke test (create -> set status by name ->
tag -> comment -> read -> delete), and prints the List ID for the worker `.env`.

Reads the token from CLICKUP_API_KEY or CLICKUP_TOKEN in the environment.
Re-running is safe: existing space/list/tags are reused, not duplicated.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "worker"))
from clickup_api import ClickUp, ClickUpError, task_status_name, task_tag_names  # noqa: E402

SPACE_NAME = "Agent Board"
LIST_NAME = "Agent Board"
STATUSES = [
    {"status": "Inbox", "type": "open", "color": "#87909e"},
    {"status": "Next", "type": "custom", "color": "#2EC4B6"},
    {"status": "Doing", "type": "custom", "color": "#FFB800"},
    {"status": "Waiting", "type": "custom", "color": "#e65100"},
    {"status": "Done", "type": "closed", "color": "#6bc950"},
]
STATUS_NAMES = [s["status"] for s in STATUSES]
TAGS = ["agent-ready", "agent-claimed", "waiting-on-you", "waiting-external"]


def token():
    for k in ("CLICKUP_API_KEY", "CLICKUP_TOKEN"):
        if os.environ.get(k):
            return os.environ[k]
    sys.exit("Set CLICKUP_API_KEY (or CLICKUP_TOKEN) in the environment.")


def find_by_name(items, name, key="name"):
    for it in items:
        if it.get(key) == name:
            return it
    return None


def main():
    cu = ClickUp(token(), log=lambda m: print("  ..", m))
    team = cu._request("GET", "/team")["teams"][0]
    tid = team["id"]
    print(f"Workspace: {team.get('name')!r} ({tid})")

    # 1) Space (try to create with our statuses in one shot).
    spaces = cu._request("GET", f"/team/{tid}/space?archived=false")["spaces"]
    space = find_by_name(spaces, SPACE_NAME)
    if space:
        print(f"Space exists: {SPACE_NAME!r} ({space['id']})")
    else:
        print(f"Creating Space {SPACE_NAME!r} ...")
        space = cu._request("POST", f"/team/{tid}/space",
                            body={"name": SPACE_NAME, "multiple_assignees": False,
                                  "statuses": STATUSES})
        print(f"  created ({space['id']})")
    sid = space["id"]
    space = cu._request("GET", f"/space/{sid}")  # refresh
    have = [s.get("status") for s in (space.get("statuses") or [])]
    print(f"Space statuses now: {have}")

    # 2) List (folderless in the space). Try to pass statuses too.
    lists = cu._request("GET", f"/space/{sid}/list?archived=false")["lists"]
    lst = find_by_name(lists, LIST_NAME)
    if lst:
        print(f"List exists: {LIST_NAME!r} ({lst['id']})")
    else:
        print(f"Creating List {LIST_NAME!r} ...")
        lst = cu._request("POST", f"/space/{sid}/list", body={"name": LIST_NAME})
        print(f"  created ({lst['id']})")
    lid = lst["id"]

    def list_status_names():
        got = cu._request("GET", f"/list/{lid}")
        return [s.get("status") for s in (got.get("statuses") or [])]

    list_statuses = list_status_names()
    statuses_ok = all(n.lower() in [s.lower() for s in list_statuses] for n in STATUS_NAMES)
    if not statuses_ok:
        # ClickUp ignores custom statuses on space/list create, but a list can
        # override its statuses via PUT with override_statuses=True.
        print("Setting the five custom statuses on the list (override) ...")
        cu._request("PUT", f"/list/{lid}",
                    body={"name": LIST_NAME, "override_statuses": True, "statuses": STATUSES})
        list_statuses = list_status_names()
        statuses_ok = all(n.lower() in [s.lower() for s in list_statuses] for n in STATUS_NAMES)
    print(f"List statuses: {list_statuses}")

    # 3) Tags.
    existing_tags = [t.get("name") for t in cu._request("GET", f"/space/{sid}/tag").get("tags", [])]
    for tag in TAGS:
        if tag in existing_tags:
            print(f"Tag exists: {tag}")
        else:
            try:
                cu._request("POST", f"/space/{sid}/tag",
                            body={"tag": {"name": tag, "tag_fg": "#ffffff", "tag_bg": "#2EC4B6"}})
                print(f"Tag created: {tag}")
            except ClickUpError as e:
                print(f"Tag FAILED {tag}: {e}")

    # 4) Live smoke test (only if the required statuses exist).
    print("\n--- smoke test ---")
    if not statuses_ok:
        print("SKIPPED: the five custom statuses are not on the list yet (see below).")
    else:
        t = cu._request("POST", f"/list/{lid}/task",
                        body={"name": "agent smoke test (safe to ignore)", "status": "Next"})
        tid_task = t["id"]
        try:
            got = cu.get_task(tid_task)
            print(f"  create+read: status={task_status_name(got)!r}")
            cu.set_status(tid_task, "Doing")
            print(f"  set status by NAME 'Doing': {task_status_name(cu.get_task(tid_task))!r}")
            cu.add_tag(tid_task, "agent-ready")
            print(f"  add tag: {sorted(task_tag_names(cu.get_task(tid_task)))}")
            cu.comment(tid_task, "\U0001f916 smoke test comment")
            cmts = cu.list_comments(tid_task)
            newest = cmts[0] if cmts else {}
            user = newest.get("user") or {}
            print(f"  comment read back: text={newest.get('comment_text','')!r} "
                  f"author_keys={sorted(user.keys())}")
        finally:
            cu._request("DELETE", f"/task/{tid_task}")
            print("  deleted test task")

    # 5) Report.
    print("\n=== RESULT ===")
    print(f"CLICKUP_LIST_ID={lid}")
    if statuses_ok:
        print("Statuses: all five present. Board is ready to run.")
    else:
        print("Statuses: NOT set via API (ClickUp manages custom statuses in the UI).")
        print("Do this once in ClickUp: open the Agent Board list -> status dropdown ->")
        print("edit statuses -> set exactly: Inbox, Next, Doing, Waiting, Done.")


if __name__ == "__main__":
    main()
