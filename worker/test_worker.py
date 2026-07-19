"""Unit tests for clickup_api.py and clickup_worker.py.

Run with: cd .../worker && python3 -m pytest test_worker.py -v
No real network or subprocess calls are made; urlopen/run_claude/grade are mocked.
"""
import datetime as dt
import json
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

import clickup_api
from clickup_api import ClickUp, ClickUpError, task_status_name, task_tag_names

import clickup_worker as w


# ------------------------------------------------------------------
# 1. task_tag_names / task_status_name
# ------------------------------------------------------------------
def test_task_tag_names_basic():
    task = {"tags": [{"name": "agent-ready"}, {"name": "agent-claimed"}]}
    assert task_tag_names(task) == {"agent-ready", "agent-claimed"}


def test_task_tag_names_missing_tags_key():
    assert task_tag_names({}) == set()


def test_task_tag_names_empty_list():
    assert task_tag_names({"tags": []}) == set()


def test_task_tag_names_tag_missing_name():
    task = {"tags": [{"color": "#fff"}, {"name": ""}, {"name": "ok"}]}
    assert task_tag_names(task) == {"ok"}


def test_task_status_name_basic():
    task = {"status": {"status": "Next", "color": "#000"}}
    assert task_status_name(task) == "Next"


def test_task_status_name_missing_status_key():
    assert task_status_name({}) is None


def test_task_status_name_status_is_none():
    assert task_status_name({"status": None}) is None


def test_task_status_name_status_missing_inner_field():
    assert task_status_name({"status": {}}) is None


# ------------------------------------------------------------------
# 2. ClickUp._retry_after
# ------------------------------------------------------------------
def test_retry_after_future_reset():
    future = time.time() + 10
    wait = ClickUp._retry_after({"X-RateLimit-Reset": str(future)})
    assert 0 < wait <= 60
    assert wait == pytest.approx(11, abs=1)


def test_retry_after_far_future_capped_at_60():
    future = time.time() + 1000
    wait = ClickUp._retry_after({"X-RateLimit-Reset": str(future)})
    assert wait == 60


def test_retry_after_past_reset_falls_back_default():
    past = time.time() - 100
    wait = ClickUp._retry_after({"X-RateLimit-Reset": str(past)})
    assert wait == 5


def test_retry_after_missing_header():
    wait = ClickUp._retry_after({})
    assert wait == 5


def test_retry_after_non_numeric_header():
    wait = ClickUp._retry_after({"X-RateLimit-Reset": "not-a-number"})
    assert wait == 5


def test_retry_after_bounded_positive():
    # sanity: for a range of resets, wait is always in (0, 60]
    for delta in (-50, -1, 0, 1, 30, 500):
        wait = ClickUp._retry_after({"X-RateLimit-Reset": str(time.time() + delta)})
        assert 0 < wait <= 60


# ------------------------------------------------------------------
# 3. ClickUp.list_tasks pagination
# ------------------------------------------------------------------
def make_task(i):
    return {"id": str(i), "name": f"task-{i}"}


def test_list_tasks_pagination_two_pages(monkeypatch):
    cu = ClickUp("tok")
    calls = []

    def fake_request(method, path, params=None, body=None):
        calls.append((method, path, dict(params or {})))
        page = params["page"]
        if page == 0:
            return {"tasks": [make_task(i) for i in range(100)]}
        elif page == 1:
            return {"tasks": [make_task(i) for i in range(100, 130)]}
        raise AssertionError("should not request a third page")

    monkeypatch.setattr(cu, "_request", fake_request)
    result = cu.list_tasks("list123", statuses=["Next"], tags=["agent-ready"])

    assert len(result) == 130
    assert [t["id"] for t in result] == [str(i) for i in range(130)]
    assert len(calls) == 2
    # statuses[] and tags[] must be passed through on every page
    for method, path, params in calls:
        assert method == "GET"
        assert path == "/list/list123/task"
        assert params["statuses[]"] == ["Next"]
        assert params["tags[]"] == ["agent-ready"]
    assert calls[0][2]["page"] == 0
    assert calls[1][2]["page"] == 1


def test_list_tasks_single_page_under_100(monkeypatch):
    cu = ClickUp("tok")
    calls = []

    def fake_request(method, path, params=None, body=None):
        calls.append(params)
        return {"tasks": [make_task(i) for i in range(5)]}

    monkeypatch.setattr(cu, "_request", fake_request)
    result = cu.list_tasks("list123")
    assert len(result) == 5
    assert len(calls) == 1  # stops immediately since batch < 100


def test_list_tasks_exact_100_then_empty(monkeypatch):
    cu = ClickUp("tok")
    pages = [{"tasks": [make_task(i) for i in range(100)]}, {"tasks": []}]
    calls = []

    def fake_request(method, path, params=None, body=None):
        calls.append(params["page"])
        return pages.pop(0)

    monkeypatch.setattr(cu, "_request", fake_request)
    result = cu.list_tasks("list123")
    assert len(result) == 100
    assert calls == [0, 1]


def test_list_tasks_no_statuses_or_tags_omits_params(monkeypatch):
    cu = ClickUp("tok")
    seen = {}

    def fake_request(method, path, params=None, body=None):
        seen.update(params or {})
        return {"tasks": []}

    monkeypatch.setattr(cu, "_request", fake_request)
    cu.list_tasks("list123")
    assert "statuses[]" not in seen
    assert "tags[]" not in seen


# ------------------------------------------------------------------
# 4. add_tag / remove_tag URL encoding
# ------------------------------------------------------------------
def test_add_tag_url_encodes_special_chars(monkeypatch):
    cu = ClickUp("tok")
    captured = {}

    def fake_request(method, path, params=None, body=None):
        captured["method"] = method
        captured["path"] = path
        return {}

    monkeypatch.setattr(cu, "_request", fake_request)
    cu.add_tag("t1", "waiting on you")
    assert captured["method"] == "POST"
    assert captured["path"] == "/task/t1/tag/waiting%20on%20you"


def test_remove_tag_url_encodes_special_chars(monkeypatch):
    cu = ClickUp("tok")
    captured = {}

    def fake_request(method, path, params=None, body=None):
        captured["method"] = method
        captured["path"] = path
        return {}

    monkeypatch.setattr(cu, "_request", fake_request)
    cu.remove_tag("t1", "agent/claimed & done")
    assert captured["method"] == "DELETE"
    # "/" and "&" and spaces must all be percent-encoded (safe="")
    assert captured["path"] == "/task/t1/tag/agent%2Fclaimed%20%26%20done"
    assert "/" not in captured["path"].split("/tag/", 1)[1]


# ------------------------------------------------------------------
# 5. clickup_worker.thread_text
# ------------------------------------------------------------------
def test_thread_text_reorders_oldest_first_and_labels():
    # ClickUp returns newest-first
    comments = [
        {"comment_text": "third and newest, human"},
        {"comment_text": "🤖 second, agent reply"},
        {"comment_text": "first and oldest, human"},
    ]
    text = w.thread_text(comments)
    lines = text.splitlines()
    assert lines == [
        "[HUMAN] first and oldest, human",
        "[AGENT] 🤖 second, agent reply",
        "[HUMAN] third and newest, human",
    ]


def test_thread_text_empty():
    assert w.thread_text([]) == "(no comments yet)"


def test_thread_text_skips_blank_comments():
    comments = [{"comment_text": "  "}, {"comment_text": "real one"}]
    text = w.thread_text(comments)
    assert text == "[HUMAN] real one"


# ------------------------------------------------------------------
# 6. clickup_worker.newest_is_human
# ------------------------------------------------------------------
def test_newest_is_human_true():
    comments = [{"comment_text": "just a human reply"}]
    assert w.newest_is_human(comments) is True


def test_newest_is_human_false_when_agent():
    comments = [{"comment_text": "🤖 agent status update"}]
    assert w.newest_is_human(comments) is False


def test_newest_is_human_false_when_empty():
    assert w.newest_is_human([]) is False


# ------------------------------------------------------------------
# 7. clickup_worker.load_env
# ------------------------------------------------------------------
def test_load_env_parses_and_strips(tmp_path):
    envfile = tmp_path / ".env"
    envfile.write_text(
        "\n".join([
            "# a comment",
            "",
            'CLICKUP_TOKEN="abc123"',
            "CLICKUP_LIST_ID='list-9'",
            "POLL_SECONDS=90",
            "IGNORED_LINE_NO_EQUALS",
            "  SPACED_KEY = spaced value  ",
        ])
    )
    env = w.load_env(envfile)
    assert env["CLICKUP_TOKEN"] == "abc123"
    assert env["CLICKUP_LIST_ID"] == "list-9"
    assert env["POLL_SECONDS"] == "90"
    assert "IGNORED_LINE_NO_EQUALS" not in env
    # key stripped; value stripped (note: split on first '=' only, so leading
    # space before value from "SPACED_KEY = spaced value" is retained inside)
    assert "SPACED_KEY" in env


def test_load_env_missing_file_returns_empty(tmp_path):
    missing = tmp_path / "does-not-exist.env"
    assert w.load_env(missing) == {}


def test_load_env_strips_only_matched_quote_pair(tmp_path):
    envfile = tmp_path / ".env"
    envfile.write_text(
        "\n".join([
            'A="quoted"',
            "B='x'",
            'C="unclosed',
        ])
    )
    env = w.load_env(envfile)
    assert env["A"] == "quoted"
    assert env["B"] == "x"
    # No matching trailing quote: the leading quote must NOT be stripped.
    assert env["C"] == '"unclosed'


# ------------------------------------------------------------------
# 8. clickup_worker.age_minutes
# ------------------------------------------------------------------
def test_age_minutes_recent_is_small():
    recent = dt.datetime.now(dt.timezone.utc).isoformat()
    assert w.age_minutes(recent) < 1


def test_age_minutes_bad_input_huge_sentinel():
    assert w.age_minutes("not-a-date") == 1e9
    assert w.age_minutes(None) == 1e9
    assert w.age_minutes("") == 1e9


def test_age_minutes_old_timestamp():
    old = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=3)).isoformat()
    age = w.age_minutes(old)
    assert 179 < age < 181


# ------------------------------------------------------------------
# 9. state roundtrip: save_state/load_state/mark
# ------------------------------------------------------------------
@pytest.fixture
def isolated_state_file(tmp_path, monkeypatch):
    state_file = tmp_path / "state" / "seen.json"
    monkeypatch.setattr(w, "STATE_FILE", state_file)
    return state_file


def _cfg(dry_run=False):
    return {"dry_run": dry_run}


def test_save_load_state_roundtrip(isolated_state_file):
    state = {"task1": {"phase": "claimed", "attempts": 1, "updated": "2026-07-17T00:00:00+00:00"}}
    w.save_state(state)
    loaded = w.load_state()
    assert loaded == state


def test_load_state_missing_file_returns_empty(isolated_state_file):
    assert w.load_state() == {}


def test_load_state_corrupt_json_returns_empty(isolated_state_file):
    isolated_state_file.parent.mkdir(parents=True, exist_ok=True)
    isolated_state_file.write_text("{not valid json!!")
    assert w.load_state() == {}


def test_mark_bumps_attempts_and_sets_phase(isolated_state_file):
    state = {}
    w.mark(state, "t1", "claimed", _cfg(), bump_attempts=True)
    assert state["t1"]["phase"] == "claimed"
    assert state["t1"]["attempts"] == 1
    assert "updated" in state["t1"]

    w.mark(state, "t1", "claimed", _cfg(), bump_attempts=True)
    assert state["t1"]["attempts"] == 2

    w.mark(state, "t1", "done", _cfg())  # bump_attempts defaults False
    assert state["t1"]["phase"] == "done"
    assert state["t1"]["attempts"] == 2

    # persisted to disk each call
    on_disk = json.loads(isolated_state_file.read_text())
    assert on_disk["t1"]["phase"] == "done"


def test_mark_dry_run_updates_memory_but_not_disk(isolated_state_file):
    state = {}
    w.mark(state, "t1", "claimed", _cfg(dry_run=True), bump_attempts=True)
    assert state["t1"]["phase"] == "claimed"
    assert state["t1"]["attempts"] == 1
    # dry-run must never create or modify the state file
    assert not isolated_state_file.exists()


def test_mark_non_dry_run_persists_to_disk(isolated_state_file):
    state = {}
    w.mark(state, "t1", "claimed", _cfg(dry_run=False), bump_attempts=True)
    assert isolated_state_file.exists()
    on_disk = json.loads(isolated_state_file.read_text())
    assert on_disk["t1"]["phase"] == "claimed"


# ------------------------------------------------------------------
# 9b. load_state pruning of terminal entries
# ------------------------------------------------------------------
def _iso_minutes_ago(minutes):
    return (dt.datetime.now(dt.timezone.utc) - dt.timedelta(minutes=minutes)).isoformat()


def test_load_state_prunes_old_done_entries(isolated_state_file):
    old = _iso_minutes_ago(w.PRUNE_AFTER_MINUTES + 60)
    state = {"t1": {"phase": "done", "attempts": 1, "updated": old}}
    w.save_state(state)
    loaded = w.load_state()
    assert "t1" not in loaded


def test_load_state_prunes_old_waiting_entries(isolated_state_file):
    old = _iso_minutes_ago(w.PRUNE_AFTER_MINUTES + 60)
    state = {"t1": {"phase": "waiting", "attempts": 1, "updated": old}}
    w.save_state(state)
    loaded = w.load_state()
    assert "t1" not in loaded


def test_load_state_keeps_old_claimed_entries(isolated_state_file):
    old = _iso_minutes_ago(w.PRUNE_AFTER_MINUTES + 60)
    state = {"t1": {"phase": "claimed", "attempts": 1, "updated": old}}
    w.save_state(state)
    loaded = w.load_state()
    assert "t1" in loaded
    assert loaded["t1"]["phase"] == "claimed"


def test_load_state_keeps_recent_done_entries(isolated_state_file):
    recent = _iso_minutes_ago(5)
    state = {"t1": {"phase": "done", "attempts": 1, "updated": recent}}
    w.save_state(state)
    loaded = w.load_state()
    assert "t1" in loaded


# ------------------------------------------------------------------
# 10. grade() verdict parsing via _verdict_line, and pass-logic
# ------------------------------------------------------------------
def test_verdict_line_finds_last_verdict_line():
    # Simulates the prompt echoing the spec's own instruction wording (which
    # itself contains "VERDICT") before the grader's actual final verdict.
    report = (
        "Some preamble text.\n"
        "Output VERDICT: DONE or NOT DONE per the spec.\n"
        "Reasoning...\n"
        "VERDICT: DONE\n"
    )
    assert w._verdict_line(report) == "VERDICT: DONE"


def test_verdict_line_not_done_is_last_line():
    report = (
        "Instructions say VERDICT should be DONE or NOT DONE.\n"
        "Reasoning here.\n"
        "verdict: NOT DONE\n"
    )
    assert w._verdict_line(report) == "VERDICT: NOT DONE"


def test_verdict_line_no_verdict_keyword_falls_back_whole_report():
    report = "no keyword here at all"
    assert w._verdict_line(report) == report.upper()


def _fake_cfg(tmp_path):
    return {
        "eval_timeout": 10,
        "model": "claude-opus-4-8",
    }


def test_grade_passes_on_clean_done_verdict(monkeypatch, tmp_path):
    monkeypatch.setattr(w, "read_eval", lambda name: "spec")
    monkeypatch.setattr(
        w, "run_claude",
        lambda prompt, cfg, max_turns=None, timeout=None, edits=True: (True, "VERDICT: DONE"),
    )
    passed, report = w.grade("completeness-eval.md", "deliverable", _fake_cfg(tmp_path), "DONE", "NOT DONE")
    assert passed is True


def test_grade_fails_on_not_done_verdict(monkeypatch, tmp_path):
    monkeypatch.setattr(w, "read_eval", lambda name: "spec")
    monkeypatch.setattr(
        w, "run_claude",
        lambda prompt, cfg, max_turns=None, timeout=None, edits=True: (True, "Reasoning...\nVERDICT: NOT DONE"),
    )
    passed, report = w.grade("completeness-eval.md", "deliverable", _fake_cfg(tmp_path), "DONE", "NOT DONE")
    assert passed is False


def test_grade_last_verdict_line_wins_when_instruction_echoed(monkeypatch, tmp_path):
    # The grader's prompt itself contains the instruction text with the word
    # VERDICT and "DONE or NOT DONE"; only the LAST such line is authoritative.
    monkeypatch.setattr(w, "read_eval", lambda name: "spec")
    echoed = "Please respond with VERDICT: DONE or NOT DONE.\nAnalysis...\nVERDICT: DONE"
    monkeypatch.setattr(
        w, "run_claude",
        lambda prompt, cfg, max_turns=None, timeout=None, edits=True: (True, echoed),
    )
    passed, report = w.grade("completeness-eval.md", "deliverable", _fake_cfg(tmp_path), "DONE", "NOT DONE")
    assert passed is True

    echoed_fail = "Please respond with VERDICT: DONE or NOT DONE.\nAnalysis...\nVERDICT: NOT DONE"
    monkeypatch.setattr(
        w, "run_claude",
        lambda prompt, cfg, max_turns=None, timeout=None, edits=True: (True, echoed_fail),
    )
    passed, report = w.grade("completeness-eval.md", "deliverable", _fake_cfg(tmp_path), "DONE", "NOT DONE")
    assert passed is False


def test_grade_grader_error_is_not_treated_as_pass(monkeypatch, tmp_path):
    # run_claude fails (ok=False) -- e.g. claude CLI not found, or timeout.
    # The report text intentionally contains the word DONE to prove the
    # failure path short-circuits before any verdict string matching.
    monkeypatch.setattr(w, "read_eval", lambda name: "spec")
    monkeypatch.setattr(
        w, "run_claude",
        lambda prompt, cfg, max_turns=None, timeout=None, edits=True: (False, "claude -p timed out, DONE nothing"),
    )
    passed, report = w.grade("completeness-eval.md", "deliverable", _fake_cfg(tmp_path), "DONE", "NOT DONE")
    assert passed is False
    assert report.startswith("grader error:")


def test_grade_publish_safety_cleared_vs_hold(monkeypatch, tmp_path):
    monkeypatch.setattr(w, "read_eval", lambda name: "spec")
    monkeypatch.setattr(
        w, "run_claude",
        lambda prompt, cfg, max_turns=None, timeout=None, edits=True: (True, "VERDICT: CLEARED"),
    )
    passed, _ = w.grade("publish-safety-eval.md", "out", _fake_cfg(tmp_path), "CLEARED", "HOLD")
    assert passed is True

    monkeypatch.setattr(
        w, "run_claude",
        lambda prompt, cfg, max_turns=None, timeout=None, edits=True: (True, "VERDICT: HOLD"),
    )
    passed, _ = w.grade("publish-safety-eval.md", "out", _fake_cfg(tmp_path), "CLEARED", "HOLD")
    assert passed is False


# ------------------------------------------------------------------
# 11. clickup_worker._best_effort
# ------------------------------------------------------------------
def test_best_effort_runs_all_ops_and_swallows_clickup_error():
    calls = []

    def op1():
        calls.append("op1")

    def op2():
        calls.append("op2")
        raise ClickUpError("boom")

    def op3():
        calls.append("op3")

    # Must not raise, and all three ops must have been attempted.
    w._best_effort("t1", [op1, op2, op3])
    assert calls == ["op1", "op2", "op3"]
