"""Thin ClickUp REST (v2) wrapper. Standard library only, no pip install.

Verified endpoints and behavior are documented in ../template/board-contract.md.
Auth header is the raw personal token (no "Bearer " prefix).
"""

import json
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request

BASE = "https://api.clickup.com/api/v2"


def _ssl_context():
    """A verifying SSL context. Some Python builds (notably python.org on
    macOS) ship with an empty system CA store, so prefer certifi's bundle when
    it is importable and fall back to the system default otherwise. Verification
    is never disabled."""
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except Exception:
        return ssl.create_default_context()


_SSL = _ssl_context()


class ClickUpError(Exception):
    """Any non-retryable ClickUp API failure."""


class ClickUp:
    def __init__(self, token, max_retries=5, timeout=30, log=print):
        if not token:
            raise ClickUpError("CLICKUP_TOKEN is empty")
        self.token = token
        self.max_retries = max_retries
        self.timeout = timeout
        self.log = log

    # ---- low-level request with rate-limit + transient-error handling ----
    def _request(self, method, path, params=None, body=None):
        url = BASE + path
        if params:
            url += "?" + urllib.parse.urlencode(params, doseq=True)
        data = json.dumps(body).encode() if body is not None else None
        headers = {"Authorization": self.token}
        if data is not None:
            headers["Content-Type"] = "application/json"

        last_err = None
        for attempt in range(self.max_retries):
            req = urllib.request.Request(url, data=data, headers=headers, method=method)
            try:
                with urllib.request.urlopen(req, timeout=self.timeout, context=_SSL) as resp:
                    raw = resp.read()
                    return json.loads(raw) if raw else {}
            except urllib.error.HTTPError as e:
                body_text = e.read().decode(errors="replace")
                if e.code == 429:
                    last_err = ClickUpError(f"{method} {path} -> 429")
                    if attempt < self.max_retries - 1:
                        wait = self._retry_after(e.headers)
                        self.log(f"[clickup] 429 rate-limited, sleeping {wait}s")
                        time.sleep(wait)
                    continue
                if 500 <= e.code < 600 and attempt < self.max_retries - 1:
                    backoff = 2 ** attempt
                    self.log(f"[clickup] {e.code} server error, retry in {backoff}s")
                    time.sleep(backoff)
                    last_err = ClickUpError(f"{method} {path} -> {e.code}")
                    continue
                raise ClickUpError(f"{method} {path} -> {e.code}: {body_text}") from e
            except urllib.error.URLError as e:
                if attempt < self.max_retries - 1:
                    backoff = 2 ** attempt
                    self.log(f"[clickup] network error {e.reason}, retry in {backoff}s")
                    time.sleep(backoff)
                    last_err = ClickUpError(f"{method} {path} -> network: {e.reason}")
                    continue
                raise ClickUpError(f"{method} {path} -> network: {e.reason}") from e
        raise last_err or ClickUpError(f"{method} {path} -> exhausted retries")

    @staticmethod
    def _retry_after(headers):
        """Seconds to wait after a 429, from X-RateLimit-Reset (Unix ts)."""
        reset = headers.get("X-RateLimit-Reset")
        if reset:
            try:
                wait = float(reset) - time.time()
                if wait > 0:
                    return min(wait + 1, 60)
            except (TypeError, ValueError):
                pass
        return 5

    # ---- task reads ----
    def list_tasks(self, list_id, statuses=None, tags=None, include_closed=False):
        """All tasks in a list matching statuses[] and tags[], paging to the end."""
        out = []
        page = 0
        while True:
            params = {"page": page}
            if statuses:
                params["statuses[]"] = statuses
            if tags:
                params["tags[]"] = tags
            if include_closed:
                params["include_closed"] = "true"
            resp = self._request("GET", f"/list/{list_id}/task", params=params)
            batch = resp.get("tasks", [])
            out.extend(batch)
            if len(batch) < 100:
                return out
            page += 1

    def get_task(self, task_id):
        return self._request("GET", f"/task/{task_id}")

    def list_comments(self, task_id):
        """Comments newest-first, as ClickUp returns them."""
        resp = self._request("GET", f"/task/{task_id}/comment")
        return resp.get("comments", [])

    # ---- task writes ----
    def create_task(self, list_id, name, description="", status=None,
                    tags=None, due_date=None, due_date_time=False):
        """Create a task. `status` is the human-readable status name (e.g. "Next"),
        `tags` a list of existing tag names, `due_date` a Unix epoch in
        milliseconds. Returns the created task dict (includes its `id`)."""
        body = {"name": name}
        if description:
            body["description"] = description
        if status:
            body["status"] = status
        if tags:
            body["tags"] = list(tags)
        if due_date is not None:
            body["due_date"] = int(due_date)
            body["due_date_time"] = bool(due_date_time)
        return self._request("POST", f"/list/{list_id}/task", body=body)

    def set_status(self, task_id, status):
        return self._request("PUT", f"/task/{task_id}", body={"status": status})

    def add_tag(self, task_id, tag):
        quoted = urllib.parse.quote(tag, safe="")
        return self._request("POST", f"/task/{task_id}/tag/{quoted}")

    def remove_tag(self, task_id, tag):
        quoted = urllib.parse.quote(tag, safe="")
        return self._request("DELETE", f"/task/{task_id}/tag/{quoted}")

    def comment(self, task_id, text, notify_all=False):
        return self._request(
            "POST",
            f"/task/{task_id}/comment",
            body={"comment_text": text, "notify_all": notify_all},
        )


# ---- helpers that operate on a task dict ----
def task_tag_names(task):
    return {t.get("name") for t in task.get("tags", []) if t.get("name")}


def task_status_name(task):
    status = task.get("status") or {}
    return status.get("status")
