# ClickUp Board Contract

The worker expects one ClickUp **list** configured exactly like this. Run `setup_board.py` to create it automatically, or set it up by hand below.

## Automated

```bash
python3 clickup/setup_board.py --token YOUR_CLICKUP_TOKEN --list YOUR_LIST_ID
```
Creates the statuses and tags, and prints your Team ID + Space ID.

## Manual

### Statuses (on the list)
| Status | Meaning |
|---|---|
| **Next** | Ready to be worked (the agent picks these up when also tagged `agent-ready`) |
| **Doing** | The agent has claimed it and is working |
| **Waiting** | The agent needs your input (paired with `waiting-on-you`) |
| **Done** | Finished |

> ClickUp stores status names lowercased; the worker compares case-insensitively, so "Next" and "next" are the same.

### Tags (Space-level)
| Tag | Set by | Purpose |
|---|---|---|
| `agent-ready` | you / capture flow | Marks a `Next` task as fair game for the agent |
| `agent-claimed` | worker | The agent has taken it (prevents double-claims) |
| `waiting-on-you` | worker | Paired with `Waiting` status; a human reply re-dispatches |
| `agent-stalled` | watchdog | Flags a task that sat unworked 15+ min (drives the alert) |

## How the worker reads the board each cycle
1. **Recover** any task stuck `agent-claimed` past `STALE_MINUTES` (crash recovery).
2. **Collaboration:** for each `waiting-on-you` task, if the newest comment is a real human reply (not the agent's `🤖` and not from ClickBot), re-dispatch it.
3. **New work:** claim tasks that are **Next** + **agent-ready** + not `agent-claimed`, up to `MAX_PER_CYCLE`.

For each claimed task it: tags `agent-claimed`, moves to **Doing**, comments "starting", runs `claude -p`, grades the output (one revision on fail), runs a publish-safety check, then moves to **Done** with a result comment — or to **Waiting** + `waiting-on-you` with an honest note.
