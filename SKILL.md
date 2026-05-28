---
name: omnara-manage
description: Steve's Omnara fleet butler. Read all sessions across all machines, triage which ones need Steve's input, send messages into existing sessions, dispatch new sessions ("派活"), manage workspaces. Use when the user says "omnara triage", "omnara 看下", "哪些 session 在等我", "派个活 to omnara", "send a message to session X", "list my omnara sessions", "open this omnara link", or any Omnara fleet-management operation. TRIGGER also when the user gives an `https://www.omnara.com/dashboard/sessions/...` URL and wants something done with it.
argument-hint: "[action] e.g. 'triage' / 'send <usid> <text>' / 'launch <path> <prompt>'"
---

# omnara-manage — Steve's Omnara Fleet Butler

Read, triage, dispatch, and reply across all of Steve's Omnara conversations on every machine, using the (undocumented) `api.omnara.com` REST surface.

## Why this skill exists

Steve runs many concurrent Claude/Codex sessions through Omnara across multiple machines. Built-in Omnara dashboard shows them as a flat list with no signal on "who is waiting for me". This skill solves three jobs:

1. **Triage** — "Who needs Steve's input right now?"
2. **Dispatch** — "Run this on machine X in workspace Y" (one-shot or fire-and-forget)
3. **Reply** — Send a message into any existing session without opening the dashboard

End goal: one Omnara controlling Steve's fleet of Omnara chats.

## Prerequisites

- Token: `~/.omnara/creds.json` → `pat` field (long-lived JWT, set up by `omnara auth login`)
- Python 3.10+ with stdlib only (no extra deps)
- Optional: `report` CLI on PATH (from report-skill) for publishing the triage HTML

## Quickstart (CLI)

```bash
~/.claude/skills/omnara-manage/bin/omnara-mgr <action> [args...]
```

Actions:

| action | what it does |
|---|---|
| `me` | show your user info & token health |
| `machines` | list registered daemons + online status |
| `list [--limit N]` | list recent sessions, one line each |
| `show <usid>` | print last 20 messages of a session |
| `triage` | scan everything, score by "needs Steve", print buckets |
| `triage --html [--publish]` | also build/publish the triage HTML report |
| `send <usid> <text>` | inject a message into an existing session |
| `launch <wid> <directory> <prompt>` | spawn a fresh session with initial prompt |
| `ensure-workspace <local_path>` | create-or-fetch a workspace on this machine |
| `delete <usid>` | delete a session |
| `raw <METHOD> <path> [json-body]` | escape hatch — call any endpoint |

## How it works (short)

The public docs (`docs.omnara.com`) describe the legacy v0 "agent SDK" endpoints — most of those URLs don't even resolve any more. The real product talks to `https://api.omnara.com` with a different shape (workspaces / user-sessions / agent-sessions / messages).

The endpoints used here were reverse-engineered from `strings ~/.omnara/bin/omnara` (the Bun-compiled CLI). See `docs/api-reference.md` for the full path list and discovery story.

Key routes:

```
GET    /api/v1/auth/me
GET    /api/v1/user-sessions                       — list ALL sessions
GET    /api/v1/user-sessions/{usid}                — session detail
GET    /api/v1/user-sessions/{usid}/agent-sessions/{asid}/messages
POST   /api/v1/user-sessions/{usid}/agent-sessions/{asid}/messages   ← inject!
POST   /api/v1/workspaces/{wid}/sessions           — launch new session ("派活")
POST   /api/v1/workspaces/ensure
GET    /api/v1/machines
DELETE /api/v1/user-sessions/{usid}
```

PAT auth is `Authorization: Bearer <pat>`. Always send `User-Agent` (Cloudflare 403s requests without one).

## Triage scoring

Omnara only marks a session `AWAITING_INPUT` when the agent calls a permission prompt — but Claude Code agents almost never do that, so Omnara's own status is useless for "who's waiting for Steve". This skill scores by reading the most recent message:

```
+100  if work_status == AWAITING_INPUT
+10   if last sender is the agent (so it's their turn no longer)
+2 × strong question-signal hits ("?", "?", "你拍", "should I", "要不要", "let me know", ...)
+1 × soft hits ("review", "选", "决定", "想", ...)
+15 if last_msg_at < 30m,  +8 if <1h, +3 if <4h
-50 if last sender is user (agent should still be working/done)
```

Output buckets: 🚨 urgent (AWAITING_INPUT) / 🔥 likely (score≥30) / 💭 maybe (15≤score<30) / ✅ idle.

The HTML triage page renders cards with the agent's last message inline so Steve can decide in <5 seconds whether to open the session.

## Send-message safety note

The send-message endpoint has **no client-source check** — server only verifies `JWT.sub == user.id`. So injecting a message looks identical to one Steve typed in the dashboard. **Convention used by this skill**: prefix injected text with `[from omnara-manage]` so the agent (and Steve) can distinguish.

Live test (2026-05-28): a sonnet agent in session `322780f9` correctly identified an unprefixed injection as a prompt-injection attempt and refused to act on it. Treat agents as untrusted recipients of injected user-turn content.

## Examples

```bash
# 1. Quick triage — who needs me?
~/.claude/skills/omnara-manage/bin/omnara-mgr triage

# 2. Same, but build & publish HTML page (uses report-skill)
~/.claude/skills/omnara-manage/bin/omnara-mgr triage --html --publish

# 3. Read the most recent 20 messages of a session
~/.claude/skills/omnara-manage/bin/omnara-mgr show 062df342-7207-4e6d-bef7-fa09d229c81d

# 4. Send a follow-up to an idle session
~/.claude/skills/omnara-manage/bin/omnara-mgr send 062df342-... "Pick approach A. Proceed."

# 5. Dispatch a new session in a fresh workspace
~/.claude/skills/omnara-manage/bin/omnara-mgr ensure-workspace /sensei-fs-3/users/zouyang/workspace/code/foo
~/.claude/skills/omnara-manage/bin/omnara-mgr launch <wid> /sensei-fs-3/.../foo "Run tests; fix; commit each fix."

# 6. Hard-mode: any endpoint
~/.claude/skills/omnara-manage/bin/omnara-mgr raw GET /api/v1/user/settings
```

## Library (Python)

For programmatic use, import directly:

```python
import sys
sys.path.insert(0, '~/.claude/skills/omnara-manage')
from omnara_client import OmnaraClient

c = OmnaraClient()                       # uses ~/.omnara/creds.json
print(c.me())
sessions = c.list_sessions()
msgs = c.get_messages(usid, asid, limit=20)
c.send_message(usid, asid, "[from omnara-manage] hello")
ws = c.ensure_workspace(local_path="/tmp/foo")
c.launch_session(ws['id'], "/tmp/foo", initial_message="say hi")
```

## Files in this skill

```
SKILL.md                this file (Claude reads it on activation)
README.md               human-facing readme
omnara_client.py        the REST client — the heart
bin/omnara-mgr          CLI entry point (runs omnara_client + triage logic)
triage.py               scoring + HTML rendering
templates/
  triage.html.tmpl      triage page template
  recon.html.tmpl       full API recon page template
examples/
  triage-output.txt     example terminal output
docs/
  api-reference.md      every endpoint, request/response shapes
  discovery-story.md    how the endpoints were reverse-engineered
  CHANGELOG.md
VERSION
```

## Iteration & change tracking

This skill is git-tracked at https://github.com/oyzh888/omnara-manage and symlinked into `~/.claude/skills/omnara-manage`. Update flow:

```bash
cd ~/.claude/skills/omnara-manage
# edit
git commit -am "..." && git push
# bump VERSION + add note to docs/CHANGELOG.md
```

Always write changes to `docs/CHANGELOG.md` so Steve can review the diff. Schema drift on the (undocumented!) Omnara API is the #1 source of breakage — log every API surprise there.

## Watch out

- PAT in `~/.omnara/creds.json` is a long-lived JWT (no `exp`). Treat like `~/.ssh/id_rsa`. Rotate via Omnara dashboard if leaked.
- Endpoints are **not public**. Wrap version assertions on response shapes; bail loudly on schema drift.
- Cloudflare 403s requests without a `User-Agent` header — always send one.
- Send-message has zero authorship signal server-side. Use the `[from omnara-manage]` prefix convention.
- Auto-dispatch only into trusted directories or `start_sandbox: true` sessions.
