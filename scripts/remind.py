#!/usr/bin/env python3
"""
Posts a reminder comment on PRs where assigned reviewer hasn't submitted
a review within REMINDER_DAYS days.

Environment variables:
    GH_TOKEN, HUB_REPO, REMINDER_DAYS
"""

import json
import os
from datetime import datetime, timezone, timedelta
from pathlib import Path

import requests

GH_TOKEN = os.environ["GH_TOKEN"]
HUB_REPO = os.environ["HUB_REPO"]
REMINDER_DAYS = int(os.environ.get("REMINDER_DAYS", "3"))

HEADERS = {
    "Authorization": f"Bearer {GH_TOKEN}",
    "Accept": "application/vnd.github+json",
    "X-GitHub-Api-Version": "2022-11-28",
}


def post_comment(pr_number, body):
    requests.post(
        f"https://api.github.com/repos/{HUB_REPO}/issues/{pr_number}/comments",
        headers=HEADERS,
        json={"body": body},
    ).raise_for_status()


def is_review_counted(state: dict, reviewer: str, author: str) -> bool:
    """Check if this review was already counted (passed all requirements)."""
    return f"{reviewer}->{author}" in state.get("counted_reviews", [])


def main():
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=REMINDER_DAYS)

    for state_file in Path("state").glob("*.json"):
        hw = state_file.stem
        state = json.loads(state_file.read_text())

        for author, data in state["students"].items():
            if data.get("completed"):
                continue
            if not data.get("pr_number"):
                continue

            pr_number = data["pr_number"]
            reviewer_assigned_at = data.get("reviewer_assigned_at", {})

            for reviewer in data.get("reviewers_assigned", []):
                # Skip if already counted (review met all requirements)
                if is_review_counted(state, reviewer, author):
                    continue

                # Use per-reviewer assignment time; fall back to submission time
                assigned_at_str = reviewer_assigned_at.get(reviewer) or data.get("submitted_at")
                if not assigned_at_str:
                    continue
                if datetime.fromisoformat(assigned_at_str) > cutoff:
                    continue  # assigned too recently

                print(f"Reminding {reviewer} to review {author} ({hw})")
                post_comment(
                    pr_number,
                    f"⏰ @{reviewer}, напоминание: вам назначена рецензия на эту работу. "
                    f"Пожалуйста, оставьте review (Approve / Request changes) "
                    f"и минимум 2 inline-комментария.",
                )


if __name__ == "__main__":
    main()
