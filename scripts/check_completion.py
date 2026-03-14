#!/usr/bin/env python3
"""
Checks whether a submitted PR review meets requirements:
  - formal review (approve / request_changes / comment)
  - at least MIN_COMMENTS inline comments

Triggered by pull_request_review event.

Usage:
    python check_completion.py --hw hw2 --reviewer bob --author alice --pr 1

Environment variables:
    GH_TOKEN, ORG_NAME, HUB_REPO  (same as assign.py)
"""

import argparse
import json
import os
from pathlib import Path

import requests

GH_TOKEN = os.environ["GH_TOKEN"]
HUB_REPO = os.environ["HUB_REPO"]

HEADERS = {
    "Authorization": f"Bearer {GH_TOKEN}",
    "Accept": "application/vnd.github+json",
    "X-GitHub-Api-Version": "2022-11-28",
}

MIN_COMMENTS_REQUIRED = 2


def gh_get(path: str) -> dict | list:
    r = requests.get(f"https://api.github.com{path}", headers=HEADERS)
    r.raise_for_status()
    return r.json()


def gh_post(path: str, payload: dict) -> dict:
    r = requests.post(f"https://api.github.com{path}", headers=HEADERS, json=payload)
    r.raise_for_status()
    return r.json()


def add_label(pr_number: int, label: str) -> None:
    gh_post(f"/repos/{HUB_REPO}/issues/{pr_number}/labels", {"labels": [label]})


def post_comment(pr_number: int, body: str) -> None:
    gh_post(f"/repos/{HUB_REPO}/issues/{pr_number}/comments", {"body": body})


def load_state(hw: str) -> dict:
    path = Path(f"state/{hw}.json")
    if path.exists():
        return json.loads(path.read_text())
    return {"students": {}, "pending": []}


def save_state(hw: str, state: dict) -> None:
    path = Path(f"state/{hw}.json")
    path.write_text(json.dumps(state, indent=2, ensure_ascii=False))


def count_review_comments(pr_number: int, reviewer: str) -> int:
    """Count inline review comments left by reviewer on this PR."""
    # per_page=100 avoids the default 30-item page cap; enough for any student PR.
    comments = gh_get(f"/repos/{HUB_REPO}/pulls/{pr_number}/comments?per_page=100")
    return sum(1 for c in comments if c["user"]["login"] == reviewer)


def check_formal_review(pr_number: int, reviewer: str) -> bool:
    """Check that reviewer submitted a formal review (not just inline comments)."""
    reviews = gh_get(f"/repos/{HUB_REPO}/pulls/{pr_number}/reviews?per_page=100")
    valid_states = {"APPROVED", "CHANGES_REQUESTED", "COMMENTED"}
    return any(
        r["user"]["login"] == reviewer and r["state"] in valid_states
        for r in reviews
    )


def process_review(hw: str, reviewer: str, author: str, pr_number: int) -> None:
    state = load_state(hw)
    students = state["students"]

    if reviewer not in students or author not in students:
        print(f"Unknown reviewer={reviewer} or author={author}, skipping.")
        return

    reviewer_data = students[reviewer]
    author_data = students[author]

    if reviewer not in author_data.get("reviewers_assigned", []):
        print(f"{reviewer} was not assigned to review {author}, skipping.")
        return

    # Check requirements
    has_formal_review = check_formal_review(pr_number, reviewer)
    comment_count = count_review_comments(pr_number, reviewer)
    meets_requirements = has_formal_review and comment_count >= MIN_COMMENTS_REQUIRED

    if not meets_requirements:
        missing = []
        if not has_formal_review:
            missing.append("formal review (Approve / Request changes / Comment через кнопку Review)")
        if comment_count < MIN_COMMENTS_REQUIRED:
            missing.append(f"минимум {MIN_COMMENTS_REQUIRED} inline-комментария (сейчас: {comment_count})")

        post_comment(
            pr_number,
            f"⚠️ @{reviewer}, рецензия пока не засчитана. Не хватает:\n"
            + "\n".join(f"- {m}" for m in missing),
        )
        return

    # Mark review as counted (idempotent)
    review_key = f"{reviewer}->{author}"
    counted = state.setdefault("counted_reviews", [])
    if review_key in counted:
        print(f"Review {review_key} already counted, skipping.")
        return

    counted.append(review_key)
    reviewer_data["reviews_given"] = reviewer_data.get("reviews_given", 0) + 1
    author_data["reviews_received"] = author_data.get("reviews_received", 0) + 1

    post_comment(
        pr_number,
        f"✅ @{reviewer}, рецензия засчитана! "
        f"(выдано рецензий: {reviewer_data['reviews_given']}/2)",
    )

    # Check if author's PR is fully reviewed
    if author_data["reviews_received"] >= 2:
        add_label(pr_number, "peer-review-complete")
        post_comment(
            pr_number,
            f"🎉 @{author}, работа получила 2 рецензии — peer review завершён!",
        )
        author_data["completed"] = True

    save_state(hw, state)

    # Print summary for instructor (visible in Actions log)
    print(f"Review counted: {reviewer} → {author}")
    print(f"  {reviewer} reviews given: {reviewer_data['reviews_given']}")
    print(f"  {author} reviews received: {author_data['reviews_received']}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--hw", required=True)
    parser.add_argument("--reviewer", required=True)
    parser.add_argument("--author", required=True)
    parser.add_argument("--pr", required=True, type=int)
    args = parser.parse_args()

    process_review(args.hw, args.reviewer, args.author, args.pr)


if __name__ == "__main__":
    main()
