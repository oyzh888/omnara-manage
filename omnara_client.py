"""omnara_client.py — minimal Python client for Omnara's (undocumented) REST API.

Stdlib-only. Loads PAT from ~/.omnara/creds.json by default.

Key endpoints used:
    GET    /api/v1/auth/me
    GET    /api/v1/machines
    GET    /api/v1/user-sessions
    GET    /api/v1/user-sessions/{usid}
    DELETE /api/v1/user-sessions/{usid}
    GET    /api/v1/user-sessions/{usid}/agent-sessions/{asid}/messages
    POST   /api/v1/user-sessions/{usid}/agent-sessions/{asid}/messages
    POST   /api/v1/workspaces/{wid}/sessions          ("派活")
    POST   /api/v1/workspaces/ensure
    GET    /api/v1/workspaces/{wid}
    GET    /api/v1/workspaces/by-path

These were reverse-engineered from `strings ~/.omnara/bin/omnara` (the bun-compiled CLI).
The public docs at docs.omnara.com describe a different (legacy v0) surface that no
longer resolves; do not trust them.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Optional

DEFAULT_BASE = "https://api.omnara.com"
DEFAULT_CREDS = os.path.expanduser("~/.omnara/creds.json")
DEFAULT_UA = "omnara-manage/0.1 (+https://github.com/oyzh888/omnara-manage)"


class OmnaraError(RuntimeError):
    def __init__(self, status: int, body: str, method: str, url: str):
        super().__init__(f"{method} {url} -> HTTP {status}: {body[:200]}")
        self.status = status
        self.body = body
        self.method = method
        self.url = url


class OmnaraClient:
    def __init__(
        self,
        pat: Optional[str] = None,
        base_url: str = DEFAULT_BASE,
        creds_path: str = DEFAULT_CREDS,
        user_agent: str = DEFAULT_UA,
        timeout: float = 30.0,
    ):
        if pat is None:
            pat = os.environ.get("OMNARA_PAT")
        if pat is None:
            try:
                with open(creds_path) as f:
                    pat = json.load(f).get("pat")
            except FileNotFoundError:
                raise OmnaraError(0, f"no creds at {creds_path}", "GET", "")
        if not pat:
            raise OmnaraError(0, "PAT is empty", "GET", "")
        self.pat = pat
        self.base = base_url.rstrip("/")
        self.user_agent = user_agent
        self.timeout = timeout

    # ---------- low-level ----------

    def request(
        self,
        method: str,
        path: str,
        body: Optional[Any] = None,
        query: Optional[dict] = None,
    ) -> Any:
        url = self.base + path
        if query:
            url += ("&" if "?" in path else "?") + urllib.parse.urlencode(query)
        data = None
        headers = {
            "Authorization": f"Bearer {self.pat}",
            "User-Agent": self.user_agent,
            "Accept": "application/json",
        }
        if body is not None:
            data = json.dumps(body).encode()
            headers["Content-Type"] = "application/json"
        req = urllib.request.Request(url, data=data, method=method, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                raw = r.read()
                if r.status == 204 or not raw:
                    return None
                return json.loads(raw)
        except urllib.error.HTTPError as e:
            raise OmnaraError(e.code, e.read().decode("utf-8", "replace"), method, url) from None

    # ---------- auth / fleet ----------

    def me(self) -> dict:
        return self.request("GET", "/api/v1/auth/me")

    def machines(self) -> list[dict]:
        d = self.request("GET", "/api/v1/machines")
        return d.get("machines", d) if isinstance(d, dict) else d

    def settings(self) -> dict:
        return self.request("GET", "/api/v1/user/settings")

    # ---------- sessions ----------

    def list_sessions(self) -> list[dict]:
        d = self.request("GET", "/api/v1/user-sessions")
        return d.get("sessions", []) if isinstance(d, dict) else d

    def get_session(self, usid: str) -> dict:
        return self.request("GET", f"/api/v1/user-sessions/{usid}")

    def delete_session(self, usid: str) -> None:
        self.request("DELETE", f"/api/v1/user-sessions/{usid}")

    # ---------- messages ----------

    def get_messages(
        self, usid: str, asid: str, limit: int = 20, before_id: Optional[str] = None
    ) -> list[dict]:
        q = {"limit": limit}
        if before_id:
            q["before_id"] = before_id
        d = self.request(
            "GET",
            f"/api/v1/user-sessions/{usid}/agent-sessions/{asid}/messages",
            query=q,
        )
        return d.get("messages", []) if isinstance(d, dict) else d

    def get_all_messages(self, usid: str, asid: str, hard_cap: int = 1000) -> list[dict]:
        """Walk back through pagination. Returns oldest-first."""
        out: list[dict] = []
        before: Optional[str] = None
        while len(out) < hard_cap:
            page = self.get_messages(usid, asid, limit=200, before_id=before)
            if not page:
                break
            out = page + out  # API returns newest-first per page; reverse
            mid = page[0].get("message_id")
            if not mid or mid == before:
                break
            before = mid
            if len(page) < 200:
                break
        return out

    def send_message(self, usid: str, asid: str, text: str) -> dict:
        return self.request(
            "POST",
            f"/api/v1/user-sessions/{usid}/agent-sessions/{asid}/messages",
            body={"text": text},
        )

    # ---------- workspaces / launch ----------

    def get_workspace(self, wid: str) -> dict:
        return self.request("GET", f"/api/v1/workspaces/{wid}")

    def workspace_by_path(self, machine_id: str, local_path: str) -> Optional[dict]:
        try:
            return self.request(
                "GET",
                "/api/v1/workspaces/by-path",
                query={"machine_id": machine_id, "path": local_path},
            )
        except OmnaraError as e:
            if e.status == 404:
                return None
            raise

    def ensure_workspace(
        self,
        local_path: str,
        machine_id: Optional[str] = None,
        workspace_type: str = "LOCAL",
    ) -> dict:
        """Create-or-fetch a workspace. machine_id auto-resolves to the only online machine if None."""
        if machine_id is None:
            mids = [m["id"] for m in self.machines() if m.get("status") == "ONLINE"]
            if not mids:
                raise OmnaraError(0, "no online machines and no machine_id given", "POST", "/workspaces/ensure")
            if len(mids) > 1:
                raise OmnaraError(
                    0,
                    f"multiple online machines, please specify machine_id ({mids})",
                    "POST",
                    "/workspaces/ensure",
                )
            machine_id = mids[0]
        body = {
            "machine_id": machine_id,
            "user_machine_id": machine_id,
            "local_path": local_path,
            "workspace_type": workspace_type,
        }
        return self.request("POST", "/api/v1/workspaces/ensure", body=body)

    def launch_session(
        self,
        wid: str,
        directory: str,
        initial_message: Optional[str] = None,
        provider: str = "claude_code",
        model: str = "opus[1m]",
        effort: str = "medium",
        thinking: str = "medium",
        metadata: Optional[dict] = None,
        start_sandbox: bool = False,
    ) -> dict:
        body: dict[str, Any] = {
            "directory": directory,
            "session_settings": {
                "code": {
                    "default_provider": provider,
                    "providers": {
                        provider: {"model": model, "effort": effort, "thinking": thinking},
                    },
                }
            },
            "start_sandbox": start_sandbox,
        }
        if initial_message:
            body["initial_message"] = initial_message
        if metadata:
            body["metadata"] = metadata
        return self.request("POST", f"/api/v1/workspaces/{wid}/sessions", body=body)

    # ---------- helpers ----------

    @staticmethod
    def dashboard_url(usid: str) -> str:
        return f"https://www.omnara.com/dashboard/sessions/{usid}"

    @staticmethod
    def session_summary(s: dict) -> dict:
        """Flatten a session dict into something printable."""
        ag = (s.get("agent_sessions") or [{}])[0]
        code = (s.get("settings") or {}).get("code", {}) or {}
        prov = code.get("default_provider")
        return {
            "usid": s.get("session_id"),
            "asid": ag.get("session_id"),
            "name": s.get("name") or "(unnamed)",
            "created_at": s.get("created_at"),
            "status": s.get("status"),
            "work_status": ag.get("work_status"),
            "connection_status": ag.get("connection_status"),
            "branch": (ag.get("metadata") or {}).get("branch"),
            "last_msg": (ag.get("metadata") or {}).get("last_message_at"),
            "model": code.get("providers", {}).get(prov, {}).get("model") if prov else None,
            "pinned": s.get("is_pinned"),
        }
