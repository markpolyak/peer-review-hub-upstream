#!/usr/bin/env python3
"""
Adds all Outside Collaborators in the organization to the peer-review-students Team.
Safe to run repeatedly — skips already-added members.

For users with expired invitations (failed invitations), cancels the old
invitation and sends a new one so they can accept it.

Usage:
    python scripts/add_students_to_hub.py --org my-org

Environment variables:
    GH_TOKEN    GitHub token with read:org and write:org scopes
"""

import argparse
import subprocess
import json
import sys
import re


def gh_api(path: str, method: str = "GET", fields: dict = None) -> list | dict | None:
    cmd = ["gh", "api", "--paginate", path]
    if method != "GET":
        cmd = ["gh", "api", path, "-X", method]
        for k, v in (fields or {}).items():
            cmd += ["-f", f"{k}={v}"]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"  API error [{method} {path}]: {result.stderr.strip()}", file=sys.stderr)
        return None
    text = result.stdout.strip()
    if not text:
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        # --paginate concatenates JSON arrays without separator: [][]\n[]
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


def get_team_membership_state(org: str, team: str, login: str) -> str | None:
    """Returns 'active', 'pending', or None if not a team member at all."""
    result = subprocess.run([
        "gh", "api",
        f"/orgs/{org}/teams/{team}/memberships/{login}",
        "--jq", ".state"
    ], capture_output=True, text=True)
    state = result.stdout.strip()
    if state in ("active", "pending"):
        return state
    return None


def get_org_membership_state(org: str, login: str) -> str | None:
    """Returns 'active', 'pending', or None if not an org member."""
    result = subprocess.run([
        "gh", "api",
        f"/orgs/{org}/memberships/{login}",
        "--jq", ".state"
    ], capture_output=True, text=True)
    state = result.stdout.strip()
    if state in ("active", "pending"):
        return state
    return None


def get_failed_invitation_id(org: str, login: str) -> int | None:
    """Returns the invitation_id of a failed org invitation for this user, or None."""
    data = gh_api(f"/orgs/{org}/failed_invitations")
    if not data:
        return None
    for inv in data:
        if inv.get("login") == login:
            return inv.get("id")
    return None


def get_pending_invitation_id(org: str, login: str) -> int | None:
    """Returns the invitation_id of a pending org invitation for this user, or None."""
    data = gh_api(f"/orgs/{org}/invitations")
    if not data:
        return None
    for inv in data:
        if inv.get("login") == login:
            return inv.get("id")
    return None


def cancel_invitation(org: str, invitation_id: int) -> bool:
    result = subprocess.run([
        "gh", "api",
        f"/orgs/{org}/invitations/{invitation_id}",
        "-X", "DELETE"
    ], capture_output=True, text=True)
    return result.returncode == 0


def add_to_team(org: str, team: str, login: str) -> bool:
    result = subprocess.run([
        "gh", "api",
        f"/orgs/{org}/teams/{team}/memberships/{login}",
        "-X", "PUT", "-f", "role=member"
    ], capture_output=True, text=True)
    if result.returncode != 0:
        print(f"    PUT error: {result.stderr.strip()}", file=sys.stderr)
    return result.returncode == 0


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--org", required=True, help="GitHub organization name")
    parser.add_argument("--team", default="peer-review-students", help="Team slug")
    args = parser.parse_args()

    org = args.org
    team = args.team

    collaborators = get_outside_collaborators(org)
    if not collaborators:
        print("No outside collaborators found.")
        return

    print(f"Found {len(collaborators)} outside collaborator(s)\n")

    # Pre-fetch failed and pending invitations once to avoid N API calls per user
    failed_invitations: dict[str, int] = {}
    failed_data = gh_api(f"/orgs/{org}/failed_invitations") or []
    for inv in failed_data:
        login = inv.get("login")
        if login:
            failed_invitations[login] = inv["id"]

    pending_invitations: dict[str, int] = {}
    pending_data = gh_api(f"/orgs/{org}/invitations") or []
    for inv in pending_data:
        login = inv.get("login")
        if login:
            pending_invitations[login] = inv["id"]

    print(f"Org pending invitations: {len(pending_invitations)}")
    print(f"Org failed invitations:  {len(failed_invitations)}\n")

    added = 0
    skipped = 0
    reinvited = 0
    failed = 0

    for login in collaborators:
        team_state = get_team_membership_state(org, team, login)
        org_state = get_org_membership_state(org, login)

        # Build a human-readable status line
        if org_state == "active":
            org_label = "org=active"
        elif login in pending_invitations:
            org_label = "org=invitation-pending"
        elif login in failed_invitations:
            org_label = "org=invitation-FAILED/EXPIRED"
        else:
            org_label = "org=not-member"

        if team_state == "active":
            team_label = "team=active"
        elif team_state == "pending":
            team_label = "team=pending"
        else:
            team_label = "team=not-member"

        print(f"  {login}: {org_label}, {team_label}")

        if team_state == "active":
            print(f"    → skip (already active team member)")
            skipped += 1
            continue

        if login in failed_invitations:
            # Expired invitation blocks re-invitation — cancel it first
            inv_id = failed_invitations[login]
            print(f"    → cancelling expired invitation (id={inv_id})...")
            if cancel_invitation(org, inv_id):
                print(f"    → cancelled. Sending fresh invitation...")
                if add_to_team(org, team, login):
                    print(f"    → re-invited successfully")
                    reinvited += 1
                else:
                    print(f"    → FAILED to re-invite after cancellation", file=sys.stderr)
                    failed += 1
            else:
                print(f"    → FAILED to cancel expired invitation", file=sys.stderr)
                failed += 1
            continue

        if team_state == "pending" or login in pending_invitations:
            # Invitation already sent and not yet expired — nothing to do.
            # Covers both: team membership pending AND org invitation pending via
            # another route. GitHub would return 422 if we tried to re-invite.
            print(f"    → skip (invitation already pending, waiting for user to accept)")
            skipped += 1
            continue

        # Not in team at all — send invitation
        if add_to_team(org, team, login):
            print(f"    → invited")
            added += 1
        else:
            print(f"    → FAILED", file=sys.stderr)
            failed += 1

    print(f"\nDone: {added} invited, {reinvited} re-invited (expired), {skipped} skipped, {failed} failed")
    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
