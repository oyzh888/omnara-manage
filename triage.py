"""triage.py — score Omnara sessions by "is this waiting on Steve?"

Pure functions over an OmnaraClient. Outputs the bucket structure that triage.html.tmpl renders.
"""

from __future__ import annotations

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
    """Returns a triage record or None if session is too stale / disconnected to bother."""
    if not s.get("agent_sessions"):
        return None
    summary = c.session_summary(s)
    work = summary["work_status"]
    conn = summary["connection_status"]
    age = _age_min(summary["last_msg"] or summary["created_at"], now)

    # Drop very old or actively disconnected ones to keep triage page focused
    if work == "WORKING":
        return None
    if conn == "DISCONNECTED" and (age is None or age > 60 * 24 * 2):
        return None
    if age is None or age > 60 * 48:
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
                score += 15
            elif age < 60:
                score += 8
            elif age < 60 * 4:
                score += 3
    elif last_sender == "user":
        score = max(0, score - 50)

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


def triage(c: OmnaraClient) -> dict[str, Any]:
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
    for s in sessions:
        rec = score_session(c, s, now)
        if rec is None:
            continue
        buckets[bucket_of(rec)].append(rec)

    for k in buckets:
        buckets[k].sort(key=lambda r: -r["score"])

    return {
        "snapshot_at": now.isoformat(),
        "machines": machines,
        "total_sessions": len(sessions),
        "buckets": buckets,
    }
