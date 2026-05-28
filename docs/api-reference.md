# Omnara REST API Reference (unofficial)

Reverse-engineered from `~/.omnara/bin/omnara` (the Bun-compiled CLI binary). All endpoints are at `https://api.omnara.com`.

**Auth:** every request needs `Authorization: Bearer <PAT>` where PAT comes from `~/.omnara/creds.json`. Cloudflare also requires a non-empty `User-Agent` header (otherwise 403).

> **The official docs at docs.omnara.com are stale** — they describe a v0 "agent SDK" model on `agent.omnara.com` that no longer resolves. Below is the actual product surface.

## Auth & user

```
GET    /api/v1/auth/me        → { id, email, display_name, created_at }
GET    /api/v1/auth/session
GET    /api/v1/user/settings
DELETE /api/v1/user-sessions/{usid}                       → 204
```

## Machines (your registered daemons)

```
GET    /api/v1/machines       → { machines: [{id, hostname, daemon_version, status, last_seen_at, ...}] }
```

`status` is `ONLINE` or implied OFFLINE; filter by `last_seen_at` to find truly active ones.

## Sessions

```
GET    /api/v1/user-sessions
   → { sessions: [<UserSession>, ...] }

GET    /api/v1/user-sessions/{usid}
   → { session, agent_sessions: [...], workspace, ... }
```

`UserSession` shape (key fields):
```jsonc
{
  "kind": "user_session",
  "session_id": "<uuid>",
  "user_id": "<uuid>",
  "status": "ACTIVE",
  "name": "...",                            // editable
  "is_pinned": false,
  "worktree_id": "<uuid>",
  "settings": { "code": { "default_provider":"claude_code", "providers":{"claude_code":{"model":"opus[1m]","effort":"medium",...}}}},
  "metadata": { "source":"rpc","transport":"relay" },
  "agent_sessions": [
    {
      "kind":"agent_session",
      "session_id":"<asid>",
      "user_session_id":"<usid>",
      "session_type":"CODE",
      "connection_status":"CONNECTED|DISCONNECTED",
      "work_status":"IDLE|WORKING|AWAITING_INPUT",
      "daemon_version":"0.25.x",
      "metadata":{"branch":"...","last_message_at":"..."}
    }
  ]
}
```

## Messages

```
GET    /api/v1/user-sessions/{usid}/agent-sessions/{asid}/messages
       ?limit=200&before_id=<message_id>
   → { messages: [<Envelope>, ...], has_more: bool, next_cursor: ... }

POST   /api/v1/user-sessions/{usid}/agent-sessions/{asid}/messages
       body: { "text": "your message" }
   → <Envelope>      // delivery_mode:"queued", server fills sender, delivered_at, ...
```

`Envelope` (text content):
```jsonc
{
  "frame_kind":"message_envelope",
  "type":"message_envelope",
  "message_id":"<uuid>",
  "session_id":"<asid>",                    // agent_session_id
  "sender": { "kind":"user|agent_session", "id":"<uuid>" },
  "payload": {
    "version": 0,
    "content": { "type":"text", "text":"...", "channel":null, "annotations":[], "attachments":null },
    "metadata": null
  },
  "metadata": { "client_source":"web|desktop|watch|...", "__omnara_event_seq": N },
  "created_at":"...",
  "delivered_at":"...",
  "delivery_mode":"queued"
}
```

Other content types you may see in `messages`: `agent_progress`, `tool_call`, `tool_result`, `interaction_request`, `agent_complete`, `error`. The CLI ignores non-text in triage but you can filter by `payload.content.type` for richer tooling.

## Workspaces & launch ("派活")

```
POST   /api/v1/workspaces/ensure
       body: {
         "machine_id": "<uuid>",
         "user_machine_id": "<uuid>",         // same as machine_id usually
         "local_path": "/abs/path/on/that/machine",
         "workspace_type": "LOCAL"
       }
   → <Workspace>     // { id, user_machine_paths: [...], workspace_config, ... }

GET    /api/v1/workspaces/{wid}
GET    /api/v1/workspaces/by-path?machine_id=...&path=...

POST   /api/v1/workspaces/{wid}/sessions
       body: {
         "directory": "/abs/path",
         "initial_message": "first prompt",     // optional, see CHANGELOG quirks
         "session_settings": {                 // optional
           "code": {
             "default_provider": "claude_code",
             "providers": {
               "claude_code": { "model":"opus[1m]", "effort":"high", "thinking":"medium", "fast_mode":"off" }
             }
           }
         },
         "metadata": { ... },                  // optional, free-form
         "start_sandbox": false                 // bool
       }
   → 201 { "status":"ok", "payload": { "launch_id", "user_session_id", "workspace_id" } }
```

## Worktrees

```
GET    /api/v1/worktrees/{id}
POST   /api/v1/worktrees/ensure
GET    /api/v1/worktrees/workspace/{wid}
GET    /api/v1/worktrees/session/{usid}      // 405 GET; use POST/etc.
```

## Other endpoints noted in the CLI binary (not all probed)

```
POST   /api/v1/cli-auth/exchange
GET    /api/v1/cli-auth/session
POST   /api/v1/auth/pat
POST   /api/v1/relay/register
POST   /api/v1/machines/register
POST   /api/v1/diagnostics/upload-url
GET    /api/v1/github/auth/url
GET    /api/v1/github/status?owner=...
POST   /api/v1/github/token/refresh
GET    /api/v1/github/user
POST   /api/v1/mobile-link-auth/create
GET    /api/v1/sandbox/managed-machines/{mid}/register-daemon
POST   /api/v1/attachments/...
POST   /api/v1/user-sessions/import-provider-session
POST   /api/v1/workspaces/{wid}/sync/checkpoint-upload-url
POST   /api/v1/workspaces/{wid}/sync/base-ref-upload-url
GET/PATCH /api/v1/workspaces/{wid}/sync/state
PATCH  /api/v1/workspaces/{wid}/sync/checkpoint-status
```

## WebSocket

```
wss://api.omnara.com/ws/machines       // daemon ↔ server, real-time messages flow here.
```

The HTTP message endpoints are sufficient for tracker / fleet-management use; this skill does not implement the WS protocol.

## HTTP status codes seen

| code | when |
|---|---|
| 200 | normal GET/POST success |
| 201 | created (e.g. launch session) |
| 204 | success, no body (DELETE) |
| 307 | trailing-slash redirect (`/workspaces/` → `/workspaces`) |
| 401 | bad/missing PAT |
| 403 | Cloudflare blocked you (missing/empty UA) |
| 404 | route doesn't exist on this version of the backend |
| 405 | method not allowed (try OPTIONS to see Allow header) |
| 422 | FastAPI validation error — body explains which field is wrong |
