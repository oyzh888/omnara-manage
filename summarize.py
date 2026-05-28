"""summarize.py — optional one-line "what does Steve need to decide?" extractor.

Uses Anthropic's Claude API (small model) to read the agent's last message and produce
a 12-word summary. Cached by message_id-equivalent (last_text hash) so it's cheap to
re-run on every triage.

Falls back gracefully (returns None for every record) if no API key is configured.
"""

from __future__ import annotations

import hashlib
import json
import os
import urllib.error
import urllib.request
from typing import Optional


CACHE_PATH = os.path.expanduser("~/.cache/omnara-manage/summaries.json")
ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"


def _key(text: str) -> str:
    return hashlib.sha256(text[-500:].encode()).hexdigest()[:16]


def _load_cache() -> dict:
    if os.path.exists(CACHE_PATH):
        try:
            return json.load(open(CACHE_PATH))
        except Exception:
            return {}
    return {}


def _save_cache(c: dict) -> None:
    os.makedirs(os.path.dirname(CACHE_PATH), exist_ok=True)
    json.dump(c, open(CACHE_PATH, "w"))


def _has_api_key() -> bool:
    return bool(os.environ.get("ANTHROPIC_API_KEY"))


def summarize_one(last_text: str, model: str = "claude-haiku-4-5") -> Optional[str]:
    """Returns a 12-word "Steve needs to: ..." line or None."""
    if not last_text or not _has_api_key():
        return None
    cache = _load_cache()
    k = _key(last_text)
    if k in cache:
        return cache[k]

    prompt = (
        "The text below is the most recent message from a Claude/Codex agent in one of "
        "Steve's coding sessions. In <=12 English words, summarize what Steve needs to "
        "decide or do (no preamble, just the action; start with a verb). If the agent "
        "isn't actually asking anything, say 'None'.\n\n"
        f"---\n{last_text[-1500:]}"
    )
    body = {
        "model": model,
        "max_tokens": 60,
        "messages": [{"role": "user", "content": prompt}],
    }
    req = urllib.request.Request(
        ANTHROPIC_URL,
        data=json.dumps(body).encode(),
        method="POST",
        headers={
            "x-api-key": os.environ["ANTHROPIC_API_KEY"],
            "anthropic-version": "2023-06-01",
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            data = json.loads(r.read())
        text = (data.get("content") or [{}])[0].get("text", "").strip()
        if text.lower() in {"none", "none.", "n/a"}:
            text = None
        cache[k] = text
        _save_cache(cache)
        return text
    except urllib.error.HTTPError as e:
        # Rate limit / auth error — don't poison cache, just skip
        return None
    except Exception:
        return None


def annotate_buckets(merged: dict, max_per_bucket: int = 8) -> dict:
    """Mutates `merged` in-place, adding `llm_summary` to top N cards in each bucket."""
    if not _has_api_key():
        return merged
    for bucket_name in ("awaiting", "likely_question", "maybe_question"):
        for r in merged.get("buckets", {}).get(bucket_name, [])[:max_per_bucket]:
            r["llm_summary"] = summarize_one(r.get("last_text") or "")
    return merged
