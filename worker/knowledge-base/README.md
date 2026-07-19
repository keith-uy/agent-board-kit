# Knowledge Base

The runner injects the contents of this folder into every task's context before the agent starts. This is the single biggest quality lever in the whole system: a good brief plus a good knowledge base means the agent needs far less back and forth, and you spend your time verifying instead of re-explaining.

## What goes here

Short, plain-language documents about how you and your business work:

- **`preferences.md`** — how you like work done, defaults to assume, what to never do without asking.
- **`tone-of-voice.md`** — 5 to 10 samples of your real writing, plus the rules an agent should follow to sound like you.
- **SOPs** — one file per repeatable process (how you onboard a client, how you format a proposal, your refund policy).
- **Reference facts** — your services, pricing, links, team names, anything an agent would otherwise guess at.

Keep each file focused and current. Delete anything stale. The agent reads all of it on every task, so trim ruthlessly.

## Setup

The two `.example.md` files here are placeholders. During install, WinflowAI copies each to its real name (drop the `.example`) and fills it with your details. Nothing here is secret; API keys and logins live in the worker `.env` or the n8n credential store, never in this folder.
