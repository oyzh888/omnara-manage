# How these endpoints were found

A short writeup so future-Steve (or future-Claude) can replay the discovery if Omnara renames things.

## v1 — dead ends from the public docs

The published docs (`docs.omnara.com`) describe a pre-pivot agent-SDK API:

```
POST https://agent.omnara.com/api/v1/messages/agent
GET  https://agent.omnara.com/api/v1/messages/pending
POST https://agent.omnara.com/api/v1/sessions/end
GET  https://agent.omnara.com/api/v1/auth/verify
```

Every one of those returns `Could not resolve host: agent.omnara.com` — DNS for that subdomain has been removed. Cloudflare DoH confirms (Status: 3 NXDOMAIN). The docs are essentially abandoned.

Trying the same paths on `api.omnara.com` returns 404. Probing the open-source backend code at `github.com/omnara-ai/omnara/src/backend/api/agents.py` shows endpoints like `/api/v1/agent-instances`, `/api/v1/agent-types`, `/api/v1/agent-summary` — but those also return 404 on the production host. That repo seems to track a different/older surface.

## v2 — strings the binary

The CLI shipped to my machine is `~/.omnara/bin/omnara` — a 108MB Bun-compiled blob. All endpoint URLs are baked into it. So:

```bash
strings ~/.omnara/bin/omnara | grep -oE "/api/v[0-9]/[a-zA-Z0-9_/-]+" | sort -u
```

→ 25 distinct paths, including:

```
/api/v1/auth/me
/api/v1/auth/pat
/api/v1/cli-auth/session
/api/v1/machines
/api/v1/user-sessions
/api/v1/user-sessions/import-provider-session
/api/v1/workspaces/by-path
/api/v1/workspaces/ensure
/api/v1/worktrees/...
```

Probing each one against `api.omnara.com` with a real PAT confirmed they're all live.

## v3 — templated paths (the deeper dig)

The flat strings don't show templated paths like `/api/v1/foo/${id}/bar`. So:

```bash
strings ~/.omnara/bin/omnara | grep -oE '/api/v[0-9]/[a-zA-Z0-9_/-]+\$\{[^}]+\}/[a-z-]+'
```

→ found `/api/v1/user-sessions/${y}/agent-sessions/${f}/messages` inside a function called `fetchSessionMessages` that paginates by `before_id`. That gave us the read endpoint. POSTing the same URL with `{}` returned a 422 listing the required field (`text`) — done.

## How to redo this when the API changes

1. Re-extract: `strings ~/.omnara/bin/omnara > /tmp/oms.txt`
2. Diff against the previous dump (commit it on each version bump): `diff /tmp/oms.txt docs/strings-snapshot.txt`
3. For any new path, hit it with `omnara-mgr raw GET /...` and watch for 422s — they print the schema.
4. Update `docs/api-reference.md` and `docs/CHANGELOG.md`.

## Why this matters

These endpoints are **not in any public schema**. There is no `openapi.json`, no `/docs`, no Swagger. If Omnara ships a refactor and renames `/user-sessions` to `/conversations`, this whole skill stops working silently with 404s. The defense is:

- pin assertions on response shapes (`session_summary` validates the keys it expects)
- log every API surprise to `docs/CHANGELOG.md`
- keep the `strings` snapshot in git so the next discovery is a `diff` not a from-scratch hunt
