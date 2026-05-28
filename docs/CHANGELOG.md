# Changelog

All notable changes to omnara-manage. The Omnara backend is undocumented; log every API surprise here.

## [0.1.0] - 2026-05-28

Initial release. Reverse-engineered from `~/.omnara/bin/omnara` strings dump.

### Added
- `omnara_client.py` — stdlib-only REST client. Loads PAT from `~/.omnara/creds.json` or `$OMNARA_PAT`.
- `triage.py` — pure scoring module. Question-signal vocabulary tuned on Steve's actual sessions (Tesco research, ML training, trading, Whisper, etc.).
- `bin/omnara-mgr` — CLI: `me / machines / list / show / triage [--html --publish] / send / launch / ensure-workspace / delete / raw`.
- `templates/triage.html.tmpl` — rendered triage page with score bands & inline question quotes.
- `templates/recon.html.tmpl` — full API recon page (kept for reference/onboarding).
- `SKILL.md` — Claude skill activation manifest.

### API endpoints in use (verified working as of 2026-05-28)
- `GET    /api/v1/auth/me`
- `GET    /api/v1/auth/session`
- `GET    /api/v1/machines`
- `GET    /api/v1/user-sessions`
- `GET    /api/v1/user-sessions/{usid}`
- `DELETE /api/v1/user-sessions/{usid}`
- `GET    /api/v1/user-sessions/{usid}/agent-sessions/{asid}/messages?limit=N&before_id=…`
- `POST   /api/v1/user-sessions/{usid}/agent-sessions/{asid}/messages` body `{"text": "..."}`
- `POST   /api/v1/workspaces/ensure` body `{machine_id, user_machine_id, local_path, workspace_type:"LOCAL"}`
- `GET    /api/v1/workspaces/{wid}`
- `POST   /api/v1/workspaces/{wid}/sessions` body `{directory, initial_message?, session_settings, metadata?, start_sandbox?}`
- `GET    /api/v1/user/settings`

### Known quirks
- Cloudflare 403s requests without a `User-Agent` header. Always send one.
- `workspaces/ensure` requires both `machine_id` AND `user_machine_id` (same value); 422 if you only send one.
- `workspaces/ensure` requires the directory to physically exist on the daemon machine — `mkdir -p` first or get `ENOENT`.
- `initial_message` on `POST /workspaces/{wid}/sessions` was accepted by the API but did NOT propagate into the agent's transcript on first test (`launch_flow: chat_first`). Use `send_message` immediately after launch as a workaround.
- Sending into an in-progress session has no client-source check server-side. The `[from omnara-manage]` prefix is a convention to help the receiving agent (and Steve) distinguish injections.
- Steve's account had 389 sessions / 9 machines (4 online) on first scan. `list_sessions()` returns ALL of them (paged inside one response); no obvious cap observed.

### Things that didn't work / dead ends
- `agent.omnara.com` host doesn't resolve any more — public docs are stale.
- `/api/v1/agent-instances` (mentioned in the open-source backend code at github.com/omnara-ai/omnara) — 404 on api.omnara.com. Likely the old/v0 dashboard surface; current product uses the user-sessions resource model instead.
- `/api/v1/auth/api-keys` — 404. Probably gated to a different host or removed.
