"""triage.py — score Omnara sessions by "is this waiting on Steve?"

Pure functions over an OmnaraClient. Outputs the bucket structure that triage.html.tmpl renders.
Message fetching parallelized via ThreadPoolExecutor.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from typing import Any, Optional

from omnara_client import OmnaraClient


# Question-signal vocabulary, expanded over time. Strong = explicit ask, soft = topic for review.
STRONG_SIGNALS = [
    "?",
    "？",
    "你拍",
    "请你",
    "你确认",
    "要不要",
    "你看",
    "需要你",
    "你觉得",
    "你想",
    "should i",
    "do you want",
    "please confirm",
    "let me know",
    "y/n",
    "can you",
    "哪一个",
    "哪个",
    "哪一",
    "approve",
    "approval",
    "what would you like",
]
SOFT_SIGNALS = [
    "choose",
    "pick",
    "决定",
    "review",
    "需要",
    "想",
    "选",
    "go ahead",
    "next step",
]


def fmt_age(m: Optional[float]) -> str:
    if m is None:
        return "?"
    if m < 60:
        return f"{m:.0f}m"
    if m < 60 * 24:
        return f"{m/60:.1f}h"
    return f"{m/(60*24):.1f}d"


def detect_question(text: str) -> tuple[int, list[str]]:
    """Returns (score, hits). Looks at the last ~500 chars."""
    t = (text or "")[-500:].lower()
    score = 0
    hits: list[str] = []
    for w in STRONG_SIGNALS:
        if w.lower() in t:
            score += 2
            hits.append(w)
    for w in SOFT_SIGNALS:
        if w.lower() in t:
            score += 1
            hits.append(w)
    return score, hits


def _age_min(iso: Optional[str], now: datetime) -> Optional[float]:
    if not iso:
        return None
    try:
        d = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    except Exception:
        return None
    return (now - d).total_seconds() / 60


def score_session(c: OmnaraClient, s: dict, now: datetime, peek_limit: int = 5) -> Optional[dict]:
    """Returns a triage record or None if session is too stale / disconnected to bother.
    Pinned sessions are NEVER filtered out by age — Steve pinned them on purpose.
    """
    if not s.get("agent_sessions"):
        return None
    summary = c.session_summary(s)
    work = summary["work_status"]
    conn = summary["connection_status"]
    age = _age_min(summary["last_msg"] or summary["created_at"], now)
    pinned = bool(summary.get("pinned"))

    # Filtering: pinned bypasses all age/disconnect filters.
    if not pinned:
        if work == "WORKING":
            return None
        if conn == "DISCONNECTED" and (age is None or age > 60 * 24 * 7):
            return None
        if age is None or age > 60 * 24 * 7:  # was 48h, now 7d for non-pinned
            return None

    # Peek last messages
    last_text = None
    last_sender = None
    try:
        msgs = c.get_messages(summary["usid"], summary["asid"], limit=peek_limit)
        for m in reversed(msgs):
            content = (m.get("payload") or {}).get("content") or {}
            if content.get("type") == "text" and (content.get("text") or "").strip():
                last_text = content["text"]
                last_sender = (m.get("sender") or {}).get("kind")
                break
    except Exception:
        pass

    if not last_text:
        # Pinned session with no readable text yet — keep a stub so it shows up
        if pinned:
            last_text = "(no text yet — open in dashboard to see content)"
            last_sender = "agent_session"
        else:
            return None

    base = 0
    if work == "AWAITING_INPUT":
        base = 100
    elif work == "IDLE" and age is not None and age < 60 * 4:
        base = 20
    elif work == "IDLE" and age is not None and age < 60 * 24:
        base = 5

    score = base
    hits: list[str] = []
    if last_sender == "agent_session":
        score += 10
        q, h = detect_question(last_text)
        score += q * 2  # double weight on question signals
        hits.extend(h)
        if age is not None:
            if age < 30:
                score += 20
            elif age < 60:
                score += 12
            elif age < 60 * 4:
                score += 5
            elif age < 60 * 12:
                score += 2
    elif last_sender == "user":
        score = max(0, score - 50)

    # Pinned bonus — Omnara users only pin sessions they actively care about
    if summary.get("pinned"):
        score += 25
        hits.insert(0, "📌pinned")

    return {
        **summary,
        "age_min": age,
        "age_str": fmt_age(age),
        "last_text": (last_text or "")[-600:],
        "last_sender": last_sender,
        "score": score,
        "hits": hits[:8],
    }


def bucket_of(rec: dict) -> str:
    if rec["work_status"] == "AWAITING_INPUT":
        return "awaiting"
    if rec["score"] >= 30:
        return "likely_question"
    if rec["score"] >= 15 and rec["last_sender"] == "agent_session":
        return "maybe_question"
    if rec["last_sender"] == "user":
        return "agent_should_respond"
    return "idle"


def triage(c: OmnaraClient, max_workers: int = 16) -> dict[str, Any]:
    now = datetime.now(timezone.utc)
    sessions = c.list_sessions()
    machines = {"machines": c.machines()}

    buckets: dict[str, list[dict]] = {
        "awaiting": [],
        "likely_question": [],
        "maybe_question": [],
        "agent_should_respond": [],
        "idle": [],
    }

    def _score(s):
        try:
            return score_session(c, s, now)
        except Exception:
            return None

    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        for rec in ex.map(_score, sessions):
            if rec is None:
                continue
            rec["account"] = c.alias
            buckets[bucket_of(rec)].append(rec)

    for k in buckets:
        buckets[k].sort(key=lambda r: -r["score"])

    return {
        "snapshot_at": now.isoformat(),
        "account": c.alias,
        "machines": machines,
        "total_sessions": len(sessions),
        "buckets": buckets,
    }


def triage_multi(clients: list[OmnaraClient], max_workers: int = 16) -> dict[str, Any]:
    """Run triage across multiple accounts in parallel, merge into one bucketed view."""
    now = datetime.now(timezone.utc)
    merged: dict[str, list[dict]] = {
        "awaiting": [],
        "likely_question": [],
        "maybe_question": [],
        "agent_should_respond": [],
        "idle": [],
    }
    per_account = []
    all_machines = []
    total_sessions = 0

    # Run accounts in parallel — each one already parallelizes internally
    with ThreadPoolExecutor(max_workers=len(clients) or 1) as ex:
        futures = {ex.submit(triage, c, max_workers): c for c in clients}
        for fut in as_completed(futures):
            c = futures[fut]
            try:
                d = fut.result()
            except Exception as e:
                per_account.append({"account": c.alias, "error": str(e)})
                continue
            per_account.append({
                "account": c.alias,
                "total_sessions": d["total_sessions"],
                "counts": {k: len(v) for k, v in d["buckets"].items()},
            })
            all_machines.extend(d["machines"]["machines"])
            total_sessions += d["total_sessions"]
            for k, v in d["buckets"].items():
                merged[k].extend(v)

    for k in merged:
        merged[k].sort(key=lambda r: -r["score"])
    # Stable account ordering for UI
    per_account.sort(key=lambda x: x.get("account", ""))
    return {
        "snapshot_at": now.isoformat(),
        "accounts": per_account,
        "total_sessions": total_sessions,
        "machines": {"machines": all_machines},
        "buckets": merged,
    }
