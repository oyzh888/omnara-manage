"""cf_deploys.py — manage Cloudflare Pages deployment history for omnara-tracker.

Each `wrangler pages deploy` creates a new immutable deployment URL like
  https://<8-char-hash>.<project>.pages.dev
The production alias `<project>.pages.dev` always points at the latest one.
Old hash URLs **stay alive forever** until explicitly deleted via the API.

Usage:
  python3 -m cf_deploys list
  python3 -m cf_deploys prune --keep 3        # delete all but the 3 newest
  python3 -m cf_deploys delete <deployment_id_or_hash>

ENV: CLOUDFLARE_API_TOKEN
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request


ACCOUNT_ID = "962646ca76cefd64bd6be92080b6f080"  # Steve's CF account
PROJECT = "omnara-tracker-steve"
BASE = f"https://api.cloudflare.com/client/v4/accounts/{ACCOUNT_ID}/pages/projects/{PROJECT}"


def _request(method: str, path: str, body: dict | None = None) -> dict:
    token = os.environ.get("CLOUDFLARE_API_TOKEN")
    if not token:
        raise SystemExit("CLOUDFLARE_API_TOKEN not set")
    req = urllib.request.Request(
        BASE + path,
        method=method,
        data=json.dumps(body).encode() if body else None,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "User-Agent": "omnara-manage/cf_deploys",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "replace")
        raise SystemExit(f"{method} {path} -> HTTP {e.code}: {body[:300]}")


def list_deployments() -> list[dict]:
    """Returns deployments newest-first."""
    out = _request("GET", "/deployments?per_page=25")
    return out.get("result") or []


def cmd_list(args):
    deps = list_deployments()
    print(f"{len(deps)} deployments\n")
    for d in deps:
        alias = ", ".join(d.get("aliases") or []) or "-"
        print(f"  {d['id'][:8]}  {d['created_on'][:19]}  {d.get('url',''):<55}  alias={alias}")


def cmd_prune(args):
    deps = list_deployments()  # newest-first
    keep = max(args.keep, 1)
    targets = [d for d in deps[keep:] if not d.get("aliases")]  # never delete the aliased one
    print(f"keeping {min(keep, len(deps))} newest, deleting {len(targets)} older deployments")
    for d in targets:
        url = d.get("url", "?")
        print(f"  DELETE {d['id'][:8]}  {url}")
        if not args.dry_run:
            _request("DELETE", f"/deployments/{d['id']}?force=true")
    if args.dry_run:
        print("\n(dry run — pass --apply to actually delete)")


def cmd_delete(args):
    # Resolve short hash or full id
    deps = list_deployments()
    target = None
    for d in deps:
        if d["id"] == args.deployment or d["id"].startswith(args.deployment):
            target = d
            break
    if not target:
        raise SystemExit(f"no deployment matches {args.deployment}")
    if target.get("aliases"):
        raise SystemExit(f"{target['id']} carries production alias — refuse to delete (would take site down)")
    print(f"DELETE {target['id']}  {target.get('url')}")
    _request("DELETE", f"/deployments/{target['id']}?force=true")
    print("✅ deleted")


def main():
    p = argparse.ArgumentParser(prog="cf_deploys", description="Manage CF Pages deployment history.")
    sp = p.add_subparsers(dest="action", required=True)

    sp.add_parser("list")

    pp = sp.add_parser("prune", help="delete old non-aliased deployments")
    pp.add_argument("--keep", type=int, default=3, help="keep N newest")
    pp.add_argument("--apply", dest="dry_run", action="store_false", help="actually delete (default is dry-run)")
    pp.set_defaults(dry_run=True)

    pd = sp.add_parser("delete")
    pd.add_argument("deployment", help="deployment id or short hash")

    args = p.parse_args()
    {"list": cmd_list, "prune": cmd_prune, "delete": cmd_delete}[args.action](args)


if __name__ == "__main__":
    main()
