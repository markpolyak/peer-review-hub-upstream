#!/usr/bin/env python3
"""
Adds all Outside Collaborators in the organization to the peer-review-students Team.
Safe to run repeatedly — skips already-added members.

Usage:
    python scripts/add_students_to_hub.py --org my-org

Environment variables:
    GH_TOKEN    GitHub token with read:org and write:org scopes
"""

import argparse
import subprocess
import json
import sys


def gh_api(path: str, method: str = "GET", fields: dict = None) -> list | dict | None:
    cmd = ["gh", "api", "--paginate", path]
    if method != "GET":
        cmd = ["gh", "api", path, "-X", method]
        for k, v in (fields or {}).items():
            cmd += ["-f", f"{k}={v}"]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"  API error for {path}: {result.stderr.strip()}", file=sys.stderr)
        return None
    # --paginate returns concatenated JSON arrays, need to handle that
    text = result.stdout.strip()
    if not text:
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        # --paginate concatenates JSON arrays without separator: [][]\n[]
        # Replace array boundaries with a comma to form a single valid array
        import re
        merged_text = re.sub(r'\]\s*\[', ',', text)
        try:
            return json.loads(merged_text)
        except json.JSONDecodeError:
            return []


def get_outside_collaborators(org: str) -> list[str]:
    data = gh_api(f"/orgs/{org}/outside_collaborators")
    if not data:
        return []
    return [u["login"] for u in data]


def is_team_member(org: str, team: str, login: str) -> bool:
    result = subprocess.run([
        "gh", "api",
        f"/orgs/{org}/teams/{team}/memberships/{login}",
        "--jq", ".state"
    ], capture_output=True, text=True)
    return result.stdout.strip() == "active"


def add_to_team(org: str, team: str, login: str) -> bool:
    result = subprocess.run([
        "gh", "api",
        f"/orgs/{org}/teams/{team}/memberships/{login}",
        "-X", "PUT", "-f", "role=member"
    ], capture_output=True, text=True)
    return result.returncode == 0


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--org", required=True, help="GitHub organization name")
    parser.add_argument("--team", default="peer-review-students", help="Team slug")
    args = parser.parse_args()

    collaborators = get_outside_collaborators(args.org)
    if not collaborators:
        print("No outside collaborators found.")
        return

    print(f"Found {len(collaborators)} outside collaborator(s)")

    added = 0
    skipped = 0
    failed = 0

    for login in collaborators:
        if is_team_member(args.org, args.team, login):
            print(f"  {login}: already member")
            skipped += 1
        else:
            if add_to_team(args.org, args.team, login):
                print(f"  {login}: added")
                added += 1
            else:
                print(f"  {login}: FAILED", file=sys.stderr)
                failed += 1

    print(f"\nDone: {added} added, {skipped} skipped, {failed} failed")
    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
