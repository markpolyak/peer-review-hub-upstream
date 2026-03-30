#!/usr/bin/env python3
"""
Prints a summary table of peer review status for all students.

Usage:
    python scripts/report.py           # all HWs found in state/
    python scripts/report.py --hw hw2  # single HW

In GitHub Actions the script also writes a Markdown summary to
$GITHUB_STEP_SUMMARY, which renders as a rich table in the Actions UI.

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

_GH_TOKEN      = os.environ.get("GH_TOKEN", "")
_HUB_REPO      = os.environ.get("HUB_REPO", "")
_SUMMARY_PATH  = os.environ.get("GITHUB_STEP_SUMMARY", "")  # set by GitHub Actions

_HEADERS = {
    "Authorization": f"Bearer {_GH_TOKEN}",
    "Accept": "application/vnd.github+json",
    "X-GitHub-Api-Version": "2022-11-28",
}

_VALID_STATES = {"APPROVED", "CHANGES_REQUESTED", "COMMENTED"}

# Cache PR reviews to avoid duplicate API calls within one run.
_reviews_cache: dict[int, list] = {}


# ---------------------------------------------------------------------------
# GitHub API helpers
# ---------------------------------------------------------------------------

def _fetch_reviews(pr_number: int) -> list:
    """Fetch formal reviews for a PR from the GitHub API (per-run cache)."""
    if pr_number in _reviews_cache:
        return _reviews_cache[pr_number]
    result = []
    if _REQUESTS_AVAILABLE and _GH_TOKEN and "/" in (_HUB_REPO or ""):
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
    if ts := data.get("received_completed_at"):
        return ts
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
    if ts := state["students"][login].get("given_completed_at"):
        return ts
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
    """Date when both peer-review conditions were met (later of the two timestamps)."""
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
# Row building
# ---------------------------------------------------------------------------

def _build_rows(state: dict) -> list[dict]:
    students = state["students"]
    pending  = set(state.get("pending", []))
    rows = []
    for login, d in sorted(students.items()):
        submitted = _fmt(d.get("submitted_at")) or ("✓" if d.get("pr_url") else "✗")
        received  = f"{d.get('reviews_received', 0)}/2"
        given     = f"{d.get('reviews_given', 0)}/2"
        waiting   = "wait" if login in pending else ""
        if d.get("reviews_received", 0) >= 2 and d.get("reviews_given", 0) >= 2:
            complete = _fmt(_complete_date(login, d, state)) or "✓"
        else:
            complete = ""
        rows.append(dict(login=login, submitted=submitted, received=received,
                         given=given, waiting=waiting, complete=complete))
    return rows


# ---------------------------------------------------------------------------
# Output: plain text (always) + Markdown (CI only)
# ---------------------------------------------------------------------------

def _print_text(hw: str, rows: list[dict]) -> None:
    print(f"\n=== {hw} ===")
    print(f"{'Login':<20} {'Submitted':<12} {'Rev.received':<14} {'Rev.given':<11} {'Waiting':<9} {'Complete'}")
    print("-" * 79)
    for r in rows:
        print(f"{r['login']:<20} {r['submitted']:<12} {r['received']:<14} "
              f"{r['given']:<11} {r['waiting']:<9} {r['complete']}")


def _write_markdown(hw: str, rows: list[dict]) -> None:
    """Append a Markdown table for this HW to $GITHUB_STEP_SUMMARY."""
    lines = [
        f"## {hw}\n",
        "| Login | Submitted | Rev.received | Rev.given | Waiting | Complete |",
        "|---|---|---|---|---|---|",
    ]
    for r in rows:
        lines.append(
            f"| `{r['login']}` | {r['submitted']} | {r['received']} "
            f"| {r['given']} | {r['waiting']} | {r['complete']} |"
        )
    lines.append("")
    with open(_SUMMARY_PATH, "a", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


# ---------------------------------------------------------------------------
# Per-HW entry point
# ---------------------------------------------------------------------------

def report_hw(hw: str) -> None:
    path = Path(f"state/{hw}.json")
    if not path.exists():
        print(f"No state file found for {hw}.")
        return
    state = json.loads(path.read_text())
    rows  = _build_rows(state)
    _print_text(hw, rows)
    if _SUMMARY_PATH:
        _write_markdown(hw, rows)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--hw", default=None,
        help="ДЗ для отчёта (например hw2). Без параметра — все ДЗ из state/.",
    )
    args = parser.parse_args()

    if _HUB_REPO and "/" not in _HUB_REPO:
        print(f"Warning: HUB_REPO='{_HUB_REPO}' looks wrong — expected 'org/repo' "
              f"(e.g. 'itmo-nn-2026/peer-review-hub'). API fallback disabled.\n")

    api_active = _REQUESTS_AVAILABLE and bool(_GH_TOKEN) and "/" in (_HUB_REPO or "")
    if not api_active and not _HUB_REPO:
        print("Note: API fallback inactive — set GH_TOKEN and HUB_REPO to fill in "
              "historical completion dates.\n")

    if args.hw:
        report_hw(args.hw)
    else:
        state_files = sorted(Path("state").glob("*.json"))
        if not state_files:
            print("No state files found in state/.")
            return
        for path in state_files:
            report_hw(path.stem)


if __name__ == "__main__":
    main()
