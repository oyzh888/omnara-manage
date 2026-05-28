# omnara-manage

Steve's Omnara fleet butler. Read, triage, and dispatch across all of Steve's Omnara conversations from a single CLI / Python client / Claude skill.

> Public Omnara docs (docs.omnara.com) describe a legacy v0 surface that has been retired. The endpoints used here were reverse-engineered from `strings ~/.omnara/bin/omnara`. See [`docs/api-reference.md`](docs/api-reference.md) and [`docs/discovery-story.md`](docs/discovery-story.md).

## What it does

| capability | endpoint |
|---|---|
| list every session across every machine | `GET /api/v1/user-sessions` |
| read full message history of any session | `GET .../user-sessions/{usid}/agent-sessions/{asid}/messages` |
| **send a message into any existing session** | `POST .../user-sessions/{usid}/agent-sessions/{asid}/messages` |
| **launch a new session** ("派活") | `POST /api/v1/workspaces/{wid}/sessions` |
| create-or-fetch a workspace at any path | `POST /api/v1/workspaces/ensure` |
| list registered daemons (machines) | `GET /api/v1/machines` |
| delete a session | `DELETE /api/v1/user-sessions/{usid}` |

## Triage

The `triage` action is the headline feature. It scores every active session by "how likely is this waiting on Steve?" using a mix of:

- explicit `work_status == AWAITING_INPUT`
- last message sender (agent_session vs user)
- question signals in the agent's last message ("?", "你拍", "should I", ...)
- recency

Outputs four buckets (urgent / likely / maybe / idle), as a terminal table or as an interactive HTML page (publishable via [report-skill](https://github.com/oyzh888/report-skill) for instant URL-sharing).

## Install

```bash
git clone https://github.com/oyzh888/omnara-manage ~/.claude/skills/omnara-manage
chmod +x ~/.claude/skills/omnara-manage/bin/omnara-mgr
ln -sf ~/.claude/skills/omnara-manage/bin/omnara-mgr ~/.local/bin/omnara-mgr  # optional
```

Make sure `~/.omnara/creds.json` exists (run `omnara auth login` if not), or set `$OMNARA_PAT`.

## CLI

```bash
omnara-mgr me
omnara-mgr machines
omnara-mgr list --limit 20
omnara-mgr show <user_session_id>
omnara-mgr triage                           # text summary
omnara-mgr triage --html --publish          # generate HTML and publish via report-skill
omnara-mgr send <usid> "Pick approach A. Proceed."
omnara-mgr launch <wid> /path/to/dir "Initial prompt"
omnara-mgr ensure-workspace /path/to/dir
omnara-mgr delete <usid>
omnara-mgr raw GET /api/v1/user/settings    # escape hatch
```

## Python

```python
from omnara_client import OmnaraClient

c = OmnaraClient()
print(c.me())
sessions = c.list_sessions()
ws = c.ensure_workspace("/path/to/repo")
c.launch_session(ws["id"], "/path/to/repo", initial_message="say hi")
c.send_message(usid, asid, "[from omnara-manage] keep going")
```

## Conventions

- **Always prefix injected messages with `[from omnara-manage] `** (the CLI does it for you). Live agents can detect prompt-injection attempts; an explicit prefix lets them treat it as a known tool rather than a hostile actor masquerading as Steve.
- Wrap every API change in a CHANGELOG entry. The Omnara backend is undocumented and may rename routes; pin assertions where it matters.

## Status / roadmap

- [x] Read all sessions, machines, messages
- [x] Send messages, launch sessions, ensure workspaces, delete
- [x] Triage scoring + HTML report
- [x] Python client + CLI + Claude skill packaging
- [ ] Tracker daemon (poll every N min, push notifications on `work_status` changes)
- [ ] LLM-based "what's the decision needed" extraction per likely-question card
- [ ] Cross-machine dispatch demos (auto-pick online machine for new sessions)

See [`docs/CHANGELOG.md`](docs/CHANGELOG.md).

## License

MIT. Steve's tooling, Steve's PAT — but the code itself is reusable by anyone with their own Omnara account.
