#!/usr/bin/env python3
"""
Prints a summary table of peer review status for all students.

Usage:
    python scripts/report.py --hw hw2

The "Submitted" and "Complete" columns show dates (YYYY-MM-DD).
Dates are read from state/*.json; if a date is missing (e.g. for students
who completed before date tracking was added), the script falls back to
the GitHub API to reconstruct them.

Optional environment variables (required only for the API fallback):
    GH_TOKEN    GitHub personal access token
    HUB_REPO    e.g. "my-org/peer-review-hub"
"""

import argparse
import json
import os
from pathlib import Path

try:
    import requests as _requests
    _REQUESTS_AVAILABLE = True
except ImportError:
    _REQUESTS_AVAILABLE = False

_GH_TOKEN = os.environ.get("GH_TOKEN", "")
_HUB_REPO = os.environ.get("HUB_REPO", "")

_HEADERS = {
    "Authorization": f"Bearer {_GH_TOKEN}",
    "Accept": "application/vnd.github+json",
    "X-GitHub-Api-Version": "2022-11-28",
}

_VALID_STATES = {"APPROVED", "CHANGES_REQUESTED", "COMMENTED"}

# Cache PR reviews to avoid duplicate API calls when multiple students
# reviewed the same PR (e.g. author received 2 reviews → 2 lookups same PR).
_reviews_cache: dict[int, list] = {}


def _fetch_reviews(pr_number: int) -> list:
    """Fetch formal reviews for a PR from the GitHub API (per-run cache)."""
    if pr_number in _reviews_cache:
        return _reviews_cache[pr_number]
    result = []
    if _REQUESTS_AVAILABLE and _GH_TOKEN and _HUB_REPO:
        try:
            r = _requests.get(
                f"https://api.github.com/repos/{_HUB_REPO}/pulls/{pr_number}/reviews?per_page=100",
                headers=_HEADERS,
                timeout=10,
            )
            if r.ok:
                result = r.json()
        except Exception:
            pass
    _reviews_cache[pr_number] = result
    return result


def _first_review_ts(pr_number: int, reviewer: str) -> str | None:
    """Timestamp of reviewer's earliest formal review on this PR."""
    timestamps = [
        r["submitted_at"]
        for r in _fetch_reviews(pr_number)
        if r["user"]["login"] == reviewer and r["state"] in _VALID_STATES
    ]
    return min(timestamps) if timestamps else None


# ---------------------------------------------------------------------------
# Date extraction: state-first, API fallback
# ---------------------------------------------------------------------------

def _received_completed_at(login: str, data: dict, state: dict) -> str | None:
    """When did this student receive their 2nd counted review?"""
    # State-first
    if ts := data.get("received_completed_at"):
        return ts
    # API fallback: find 2nd formal review among counted reviewers on author's PR
    pr_number = data.get("pr_number")
    if not pr_number:
        return None
    counted = state.get("counted_reviews", [])
    reviewers = [k.split("->")[0] for k in counted if k.endswith(f"->{login}")]
    if len(reviewers) < 2:
        return None
    timestamps = sorted(filter(None, (_first_review_ts(pr_number, r) for r in reviewers)))
    return timestamps[1] if len(timestamps) >= 2 else None


def _given_completed_at(login: str, state: dict) -> str | None:
    """When did this student submit their 2nd counted review?"""
    # State-first
    if ts := state["students"][login].get("given_completed_at"):
        return ts
    # API fallback: for each author this student has a counted review for,
    # find the timestamp of their formal review on that author's PR.
    counted = state.get("counted_reviews", [])
    targets = [k.split("->")[1] for k in counted if k.startswith(f"{login}->")]
    if len(targets) < 2:
        return None
    timestamps = []
    for target in targets:
        td = state["students"].get(target, {})
        if pr := td.get("pr_number"):
            if ts := _first_review_ts(pr, login):
                timestamps.append(ts)
    timestamps.sort()
    return timestamps[1] if len(timestamps) >= 2 else None


def _complete_date(login: str, data: dict, state: dict) -> str | None:
    """
    Date when the student fully completed peer review (both conditions met):
      - received 2 reviews on their own work
      - gave 2 counted reviews themselves
    Returns the later of the two timestamps (the moment both were satisfied).
    """
    if data.get("reviews_received", 0) < 2 or data.get("reviews_given", 0) < 2:
        return None
    t1 = _received_completed_at(login, data, state)
    t2 = _given_completed_at(login, state)
    both = [t for t in (t1, t2) if t]
    return max(both) if len(both) == 2 else (both[0] if both else None)


def _fmt(ts: str | None) -> str:
    """Format ISO timestamp as YYYY-MM-DD, or return empty string."""
    return ts[:10] if ts else ""


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--hw", required=True)
    args = parser.parse_args()

    path = Path(f"state/{args.hw}.json")
    if not path.exists():
        print("No state file found.")
        return

    state = json.loads(path.read_text())
    students = state["students"]
    pending = state.get("pending", [])

    if _HUB_REPO and "/" not in _HUB_REPO:
        print(f"Warning: HUB_REPO='{_HUB_REPO}' looks wrong — expected 'org/repo' "
              f"(e.g. 'itmo-nn-2026/peer-review-hub'). API fallback disabled.\n")

    api_active = _REQUESTS_AVAILABLE and bool(_GH_TOKEN) and "/" in (_HUB_REPO or "")
    if not api_active and not _HUB_REPO:
        print("Note: API fallback inactive — set GH_TOKEN and HUB_REPO to fill in "
              "historical completion dates.\n")

    print(f"\n{'Login':<20} {'Submitted':<12} {'Rev.received':<14} {'Rev.given':<11} {'Waiting':<9} {'Complete'}")
    print("-" * 79)

    for login, d in sorted(students.items()):
        # Submitted: date from state (always present for processed PRs)
        submitted = _fmt(d.get("submitted_at")) or ("✓" if d.get("pr_url") else "✗")

        received = f"{d.get('reviews_received', 0)}/2"
        given    = f"{d.get('reviews_given', 0)}/2"
        waiting  = "wait" if login in pending else ""

        # Complete: date when both conditions were met; "✓" if done but date unknown
        if d.get("reviews_received", 0) >= 2 and d.get("reviews_given", 0) >= 2:
            complete = _fmt(_complete_date(login, d, state)) or "✓"
        else:
            complete = ""

        print(f"{login:<20} {submitted:<12} {received:<14} {given:<11} {waiting:<9} {complete}")


if __name__ == "__main__":
    main()
