#!/usr/bin/env python3
"""ClickUp agent worker (flagship, subscription-first).

Polls one ClickUp list, claims tasks that are (status Next + tag agent-ready),
runs them via headless `claude -p`, grades the output against the evals, and
writes the result back to the board. Also handles the collaboration loop:
a human comment on a waiting-on-you task re-dispatches it.

Board contract: ../template/board-contract.md
Config: worker/.env (see .env.example). Standard library only.

Usage:
  python3 clickup_worker.py            # loop forever, POLL_SECONDS apart
  python3 clickup_worker.py --once     # a single cycle then exit
  python3 clickup_worker.py --dry-run  # log intended actions, write nothing
"""

import argparse
import datetime as dt
import fcntl
import json
import os
import select
import subprocess
import sys
import time
from pathlib import Path

from clickup_api import ClickUp, ClickUpError, task_status_name, task_tag_names

HERE = Path(__file__).resolve().parent
EVALS_DIR = HERE.parent / "evals"
KB_DIR_DEFAULT = HERE.parent / "knowledge-base"
STATE_FILE = HERE / "state" / "seen.json"
LOCK_FILE = HERE / "state" / "worker.lock"
# Event-driven wake: the webhook bridge pokes this FIFO to run a cycle immediately
# instead of waiting for the next poll. Absent/unpokable → plain timed poll (fallback).
WAKE_FIFO = HERE / "state" / "wake.fifo"

# Board contract constants (must match the ClickUp list setup). ClickUp accepts
# these names when setting status but stores/returns them lowercased, so compare
# status names case-insensitively via status_is().
S_NEXT, S_DOING, S_WAITING, S_DONE = "Next", "Doing", "Waiting", "Done"


def status_is(task, name):
    s = task_status_name(task)
    return s is not None and s.lower() == name.lower()
T_READY, T_CLAIMED, T_WAIT_YOU = "agent-ready", "agent-claimed", "waiting-on-you"
AGENT_MARKER = "🤖"  # every agent comment starts with this; human replies do not
CLICKBOT_USER_ID = "-1"  # ClickUp Automations post comments as ClickBot (user id -1)


def is_agent_or_bot(c):
    """A comment from our worker (🤖 prefix) or from ClickUp Automations/ClickBot
    (user id -1). Neither counts as a human reply on a waiting task, so the
    'needs input' automation comment can never re-trigger a dispatch by itself."""
    if str(c.get("user", {}).get("id")) == CLICKBOT_USER_ID:
        return True
    return c.get("comment_text", "").startswith(AGENT_MARKER)


def now_iso():
    return dt.datetime.now(dt.timezone.utc).isoformat()


def log(msg):
    print(f"{now_iso()} {msg}", flush=True)


# --------------------------- config ---------------------------
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
                v = v[1:-1]  # strip only a matched surrounding quote pair
            env[k.strip()] = v
    return env


def load_config(dry_run):
    env = load_env(HERE / ".env")

    def get(key, default=None):
        return os.environ.get(key) or env.get(key) or default

    cfg = {
        "token": get("CLICKUP_TOKEN", ""),
        "list_id": get("CLICKUP_LIST_ID", ""),
        "auth_mode": (get("AUTH_MODE", "subscription")).lower(),
        "api_key": get("ANTHROPIC_API_KEY", ""),
        "poll_seconds": int(get("POLL_SECONDS", "90")),
        "max_per_cycle": int(get("MAX_PER_CYCLE", "3")),
        "stale_minutes": int(get("STALE_MINUTES", "120")),
        "model": get("CLAUDE_MODEL", "claude-opus-4-8"),
        "max_turns": int(get("MAX_TURNS", "40")),
        "task_timeout": int(get("TASK_TIMEOUT_SECONDS", "1500")),
        "eval_timeout": int(get("EVAL_TIMEOUT_SECONDS", "300")),
        "permission_mode": get("PERMISSION_MODE", "acceptEdits"),
        "work_dir": get("WORK_DIR", str(HERE / "workspace")),
        "kb_dir": get("KB_DIR", str(KB_DIR_DEFAULT)),
        "publish_safety": (get("PUBLISH_SAFETY", "on")).lower() != "off",
        "dry_run": dry_run,
    }
    if not cfg["token"] or not cfg["list_id"]:
        sys.exit("CLICKUP_TOKEN and CLICKUP_LIST_ID are required (see .env.example)")
    if cfg["auth_mode"] not in ("subscription", "api"):
        sys.exit("AUTH_MODE must be 'subscription' or 'api'")
    if cfg["auth_mode"] == "api" and not cfg["api_key"]:
        sys.exit("AUTH_MODE=api requires ANTHROPIC_API_KEY")
    return cfg


# --------------------------- state ---------------------------
PRUNE_AFTER_MINUTES = 7 * 24 * 60  # drop terminal entries after a week


def load_state():
    if STATE_FILE.exists():
        try:
            state = json.loads(STATE_FILE.read_text())
        except json.JSONDecodeError:
            log("[state] corrupt seen.json, starting fresh")
            return {}
        # Bound growth: terminal (done/waiting) entries are never needed for
        # recovery, so drop old ones. 'claimed' entries are always kept.
        for tid in [t for t, e in state.items()
                    if e.get("phase") in ("done", "waiting")
                    and age_minutes(e.get("updated", "")) > PRUNE_AFTER_MINUTES]:
            del state[tid]
        return state
    return {}


def save_state(state):
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = STATE_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=2))
    tmp.replace(STATE_FILE)  # atomic on POSIX


def mark(state, task_id, phase, cfg, bump_attempts=False):
    # In dry-run we never touch the shared state file: a phantom "claimed"
    # entry could otherwise be re-driven by a later real run.
    entry = state.get(task_id, {"attempts": 0})
    entry["phase"] = phase
    entry["updated"] = now_iso()
    if bump_attempts:
        entry["attempts"] = entry.get("attempts", 0) + 1
    state[task_id] = entry
    if not cfg["dry_run"]:
        save_state(state)


def age_minutes(iso):
    try:
        then = dt.datetime.fromisoformat(iso)
        return (dt.datetime.now(dt.timezone.utc) - then).total_seconds() / 60
    except (TypeError, ValueError):
        return 1e9


# --------------------------- claude ---------------------------
def run_claude(prompt, cfg, max_turns=None, timeout=None, edits=True):
    """Run headless claude -p. Returns (ok, text)."""
    turns = max_turns if max_turns is not None else cfg["max_turns"]
    args = ["claude", "-p", prompt, "--model", cfg["model"],
            "--max-turns", str(turns)]
    if edits:
        args += ["--permission-mode", cfg["permission_mode"]]
    env = os.environ.copy()
    if cfg["auth_mode"] == "subscription":
        env.pop("ANTHROPIC_API_KEY", None)  # draw the buyer's plan, $0 marginal
    else:
        env["ANTHROPIC_API_KEY"] = cfg["api_key"]
        args.append("--bare")  # skip OAuth/keychain, force API-key mode
    Path(cfg["work_dir"]).mkdir(parents=True, exist_ok=True)
    try:
        proc = subprocess.run(
            args, capture_output=True, text=True, env=env,
            cwd=cfg["work_dir"], timeout=timeout or cfg["task_timeout"],
        )
    except subprocess.TimeoutExpired:
        return False, f"claude -p timed out after {timeout or cfg['task_timeout']}s"
    except FileNotFoundError:
        return False, "claude CLI not found on PATH (install Claude Code)"
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "").strip()[:1000]
        return False, f"claude -p exited {proc.returncode}: {detail}"
    return True, (proc.stdout or "").strip()


def read_eval(name):
    return (EVALS_DIR / name).read_text()


def grade(eval_name, deliverable, cfg, verdict_true, verdict_false):
    """Run an eval as a grading call. Returns (passed: bool, report: str)."""
    spec = read_eval(eval_name)
    prompt = (
        "You are an eval grader. Grade the DELIVERABLE strictly against the EVAL "
        "SPEC. Follow the spec's output contract exactly. Be harsh; a borderline "
        f"case is {verdict_false}.\n\n=== EVAL SPEC ===\n{spec}\n\n"
        f"=== DELIVERABLE ===\n{deliverable}"
    )
    ok, report = run_claude(prompt, cfg, max_turns=3, timeout=cfg["eval_timeout"], edits=False)
    if not ok:
        # If the grader itself fails, do not silently pass: treat as not-passed.
        return False, f"grader error: {report}"
    line = _verdict_line(report)
    passed = verdict_true in line and verdict_false not in line
    return passed, report


def _verdict_line(report):
    """The grader's actual verdict is the LAST line mentioning VERDICT (the
    prompt echoes the spec's own 'VERDICT' wording earlier). Fall back to the
    whole report if none is found."""
    found = None
    for line in report.splitlines():
        if "VERDICT" in line.upper():
            found = line.upper()
    return found if found is not None else report.upper()


# --------------------------- prompt assembly ---------------------------
def read_kb(kb_dir):
    parts = []
    p = Path(kb_dir)
    if p.exists():
        for f in sorted(p.glob("*.md")):
            if f.name.endswith(".example.md"):
                continue  # placeholders, not real buyer content
            parts.append(f"--- {f.name} ---\n{f.read_text()}")
    return "\n\n".join(parts) if parts else "(no knowledge base configured yet)"


def thread_text(comments):
    """Comments oldest-first as 'AGENT'/'HUMAN' lines."""
    lines = []
    for c in reversed(comments):  # API returns newest-first
        if str(c.get("user", {}).get("id")) == CLICKBOT_USER_ID:
            continue  # automation/ClickBot notification, no task-relevant content
        text = c.get("comment_text", "").strip()
        who = "AGENT" if text.startswith(AGENT_MARKER) else "HUMAN"
        if text:
            lines.append(f"[{who}] {text}")
    return "\n".join(lines) if lines else "(no comments yet)"


# Keep the assembled prompt well under OS ARG_MAX (it is passed as one argv
# element). Long KBs / comment threads are truncated rather than risking E2BIG.
KB_MAX = 40000
THREAD_MAX = 20000


def build_prompt(task, comments, cfg, feedback=None):
    kb = read_kb(cfg["kb_dir"])[:KB_MAX]
    desc = (task.get("description") or task.get("text_content") or "(no description)")[:20000]
    prompt = (
        "You are an AI agent working a task from a shared ClickUp board. Do the "
        "work described below, following the buyer's knowledge base. Your final "
        "message is posted verbatim as the result comment on the task, so make it "
        "a clear, self-contained handback: what you did, and absolute paths or "
        "links to any artifacts. State anything skipped or uncertain plainly.\n\n"
        f"=== KNOWLEDGE BASE ===\n{kb}\n\n"
        f"=== TASK ===\nTitle: {task.get('name','')}\n\nDescription:\n{desc}\n\n"
        f"=== COMMENT THREAD ===\n{thread_text(comments)[:THREAD_MAX]}\n"
    )
    if feedback:
        prompt += f"\n=== REVISION REQUESTED ===\n{feedback}\n"
    return prompt


# --------------------------- core task handling ---------------------------
def newest_is_human(comments):
    if not comments:
        return False
    return not is_agent_or_bot(comments[0])


def process_task(cu, task, cfg, state, already_claimed=False):
    tid = task["id"]
    name = task.get("name", "")[:60]

    if not already_claimed:
        if T_CLAIMED in task_tag_names(task):
            log(f"[skip] {tid} '{name}' already agent-claimed")
            return
        # A claim that keeps failing (e.g. the agent-claimed tag is missing from
        # the Space) never sets the board tag, so the ready-loop re-picks it every
        # cycle and starves recover_stale's timer. Escalate directly here instead
        # of relying on staleness, before spending any Claude run.
        if state.get(tid, {}).get("attempts", 0) >= 2:
            log(f"[escalate] {tid} failed to start twice, handing back")
            return _to_waiting(cu, tid, cfg, state,
                               "This task could not be started after two attempts and "
                               "needs your input. Check that the board tags and statuses "
                               "exist and the token has access.")
        log(f"[claim] {tid} '{name}'")
        # Record the claim in state BEFORE mutating the board, so a failure
        # mid-claim still leaves a recoverable entry (never an orphaned task).
        mark(state, tid, "claimed", cfg, bump_attempts=True)
        if cfg["dry_run"]:
            log("  (dry-run) would add agent-claimed, set Doing, comment starting")
        else:
            try:
                cu.add_tag(tid, T_CLAIMED)
                cu.set_status(tid, S_DOING)
                cu.comment(tid, f"{AGENT_MARKER} Starting on this now.")
            except ClickUpError as e:
                log(f"[claim-error] {tid}: {e}; leaving for retry")
                return

    comments = [] if cfg["dry_run"] else cu.list_comments(tid)

    # 1) work
    ok, output = run_claude(build_prompt(task, comments, cfg), cfg)
    if not ok:
        return _to_waiting(cu, tid, cfg, state, f"The run did not complete: {output}")

    # 2) completeness eval, with one revision on FAIL
    passed, report = grade("completeness-eval.md", f"TASK: {task.get('name')}\n\nOUTPUT:\n{output}",
                           cfg, "DONE", "NOT DONE")
    if not passed:
        log(f"[eval] completeness NOT DONE for {tid}, one revision")
        ok, output = run_claude(build_prompt(task, comments, cfg, feedback=report), cfg)
        if not ok:
            return _to_waiting(cu, tid, cfg, state, f"Revision did not complete: {output}")
        passed, report = grade("completeness-eval.md", f"TASK: {task.get('name')}\n\nOUTPUT:\n{output}",
                               cfg, "DONE", "NOT DONE")
        if not passed:
            return _to_waiting(cu, tid, cfg, state,
                               "Completeness eval still failing after one revision. "
                               f"What is incomplete:\n{report}")

    # 3) publish-safety gate (last)
    if cfg["publish_safety"]:
        cleared, safety = grade("publish-safety-eval.md", output, cfg, "CLEARED", "HOLD")
        if not cleared:
            return _to_waiting(cu, tid, cfg, state,
                               f"Held for your review before anything goes out:\n{safety}\n\n"
                               f"Draft:\n{output}")

    # 4) done
    log(f"[done] {tid} '{name}'")
    if cfg["dry_run"]:
        log("  (dry-run) would comment result, remove agent-claimed, set Done")
        mark(state, tid, "done", cfg)
        return
    try:
        cu.comment(tid, f"{AGENT_MARKER} Done.\n\n{output[:9000]}")
    except ClickUpError as e:
        # Result not posted yet: leave state 'claimed' so recovery retries.
        # Nothing landed on the board, so there is no double-comment risk.
        log(f"[done-error] posting result failed for {tid}: {e}; will retry")
        return
    # Result landed. Mark done immediately so a retry can never re-post it,
    # then best-effort cleanup of tag + status.
    mark(state, tid, "done", cfg)
    _best_effort(tid, [lambda: cu.remove_tag(tid, T_CLAIMED),
                       lambda: cu.set_status(tid, S_DONE)])


def _best_effort(tid, ops):
    for op in ops:
        try:
            op()
        except ClickUpError as e:
            log(f"[cleanup] {tid}: {e}")


def _to_waiting(cu, tid, cfg, state, note):
    log(f"[waiting] {tid}: {note[:80]}")
    if cfg["dry_run"]:
        mark(state, tid, "waiting", cfg)
        return
    try:
        cu.comment(tid, f"{AGENT_MARKER} {note}")
    except ClickUpError as e:
        # Note not posted: leave 'claimed' for recovery rather than a silent drop.
        log(f"[waiting-error] posting note failed for {tid}: {e}; will retry")
        return
    mark(state, tid, "waiting", cfg)
    _best_effort(tid, [lambda: cu.remove_tag(tid, T_CLAIMED),
                       lambda: cu.add_tag(tid, T_WAIT_YOU),
                       lambda: cu.set_status(tid, S_WAITING)])


# --------------------------- cycle ---------------------------
def recover_stale(cu, cfg, state):
    """Re-drive tasks stuck 'claimed' past STALE_MINUTES (crash recovery)."""
    for tid, entry in list(state.items()):
        if entry.get("phase") != "claimed":
            continue
        if age_minutes(entry.get("updated", "")) < cfg["stale_minutes"]:
            continue
        attempts = entry.get("attempts", 0)
        log(f"[stale] {tid} claimed for >{cfg['stale_minutes']}m, attempts={attempts}")
        try:
            task = cu.get_task(tid)
        except ClickUpError as e:
            log(f"[stale] cannot fetch {tid}: {e}")
            continue
        if status_is(task, S_DONE):
            mark(state, tid, "done", cfg)
            continue
        if attempts >= 2:
            _to_waiting(cu, tid, cfg, state,
                        "This task failed twice and needs your input. See the thread above.")
            continue
        # Count this recovery as an attempt so the escalation above eventually
        # fires (already_claimed=True skips the claim-time bump).
        mark(state, tid, "claimed", cfg, bump_attempts=True)
        process_task(cu, task, cfg, state, already_claimed=True)


def _safe_process(cu, task, cfg, state, already_claimed=False):
    """One task failing (API or unexpected) must not abort the rest of the cycle."""
    try:
        process_task(cu, task, cfg, state, already_claimed=already_claimed)
    except ClickUpError as e:
        log(f"[task-error] {task.get('id')}: {e}")
    except Exception as e:  # noqa: BLE001 keep the cycle alive
        log(f"[task-error] {task.get('id')} unexpected: {e}")


def cycle(cu, cfg, state):
    recover_stale(cu, cfg, state)

    # A) collaboration loop: human replies on waiting-on-you tasks
    waiting = cu.list_tasks(cfg["list_id"], tags=[T_WAIT_YOU])
    for task in waiting:
        comments = cu.list_comments(task["id"])
        if newest_is_human(comments):
            log(f"[reply] human replied on {task['id']}, re-dispatching")
            if not cfg["dry_run"]:
                # Drop the waiting tag; the claim step below moves it to Doing.
                _best_effort(task["id"], [lambda: cu.remove_tag(task["id"], T_WAIT_YOU)])
            _safe_process(cu, task, cfg, state, already_claimed=False)

    # B) new work: Next + agent-ready, not already claimed
    ready = cu.list_tasks(cfg["list_id"], statuses=[S_NEXT], tags=[T_READY])
    picked = 0
    hit_cap = False
    for task in ready:
        if T_CLAIMED in task_tag_names(task):
            continue
        _safe_process(cu, task, cfg, state)
        picked += 1
        if picked >= cfg["max_per_cycle"]:
            log(f"[cap] hit MAX_PER_CYCLE={cfg['max_per_cycle']}, draining next cycle")
            hit_cap = True
            break
    if picked == 0 and not waiting:
        log("[idle] nothing to do")
    # True when the per-cycle cap was hit and more ready work likely remains, so
    # the caller runs again immediately instead of waiting for the next poke/poll
    # (drains a burst of tasks instead of 3-per-interval).
    return hit_cap


def acquire_lock():
    """Single-flight: only one worker process runs against this checkout."""
    LOCK_FILE.parent.mkdir(parents=True, exist_ok=True)
    fh = open(LOCK_FILE, "w")
    try:
        fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        sys.exit("another worker is already running (lock held)")
    return fh


# --------------------------- event-driven wake ---------------------------
def setup_wake_fifo():
    """Create the wake FIFO and return a read fd to select() on, or None to fall
    back to plain sleep. We also open (and intentionally keep) a write end so the
    reader never sees a permanent EOF when the external poker closes its end."""
    try:
        WAKE_FIFO.parent.mkdir(parents=True, exist_ok=True)
        if not WAKE_FIFO.exists():
            os.mkfifo(WAKE_FIFO, 0o600)
        rfd = os.open(WAKE_FIFO, os.O_RDONLY | os.O_NONBLOCK)  # succeeds with no writer
        os.open(WAKE_FIFO, os.O_WRONLY | os.O_NONBLOCK)  # keep-alive writer, daemon lifetime
        log(f"[wake] listening on {WAKE_FIFO}")
        return rfd
    except OSError as e:
        log(f"[wake] FIFO unavailable ({e}); timed poll only")
        return None


def wait_for_wake(rfd, seconds):
    """Sleep up to `seconds`, returning early if the wake FIFO is poked. Multiple
    pokes coalesce into a single cycle (we drain everything pending)."""
    if rfd is None:
        time.sleep(seconds)
        return
    try:
        ready, _, _ = select.select([rfd], [], [], seconds)
    except (OSError, ValueError):
        time.sleep(seconds)
        return
    if ready:
        try:
            os.read(rfd, 65536)  # drain the poke(s)
        except (BlockingIOError, OSError):
            pass
        log("[wake] poked by webhook bridge, running a cycle now")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--once", action="store_true", help="run one cycle then exit")
    ap.add_argument("--dry-run", action="store_true", help="log actions, write nothing")
    args = ap.parse_args()

    cfg = load_config(args.dry_run)
    lock = acquire_lock()  # noqa: F841 (held for process lifetime)
    log(f"[start] list={cfg['list_id']} auth={cfg['auth_mode']} model={cfg['model']} "
        f"dry_run={cfg['dry_run']}")
    cu = ClickUp(cfg["token"], log=log)
    state = load_state()
    wake_rfd = None if args.once else setup_wake_fifo()

    while True:
        hit_cap = False
        try:
            hit_cap = cycle(cu, cfg, state)
        except ClickUpError as e:
            log(f"[error] ClickUp: {e}")  # non-fatal, retry next cycle
        except Exception as e:  # noqa: BLE001 keep the loop alive
            log(f"[error] unexpected: {e}")
        if args.once:
            break
        if hit_cap:
            continue  # more ready work remains; drain now without waiting
        wait_for_wake(wake_rfd, cfg["poll_seconds"])


if __name__ == "__main__":
    main()
