#!/usr/bin/env python3
"""
Assigns a reviewer to a student who opened a PR for peer review.

Usage:
    python assign.py --hw hw2 --author alice --repo org/hw2-alice --pr 1

Environment variables:
    GH_TOKEN       GitHub token with repo + org write access
    ORG_NAME       GitHub organization name
    HUB_REPO       e.g. "my-org/peer-review-hub"
"""

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import requests

GH_TOKEN = os.environ["GH_TOKEN"]
ORG_NAME = os.environ["ORG_NAME"]
HUB_REPO = os.environ["HUB_REPO"]

HEADERS = {
    "Authorization": f"Bearer {GH_TOKEN}",
    "Accept": "application/vnd.github+json",
    "X-GitHub-Api-Version": "2022-11-28",
}

MAX_REVIEWS_PER_STUDENT = 4  # max outgoing reviews per student per HW
MIN_COMMENTS_REQUIRED = 2


# ---------------------------------------------------------------------------
# GitHub API helpers
# ---------------------------------------------------------------------------

def gh_get(path: str) -> dict | list:
    r = requests.get(f"https://api.github.com{path}", headers=HEADERS)
    r.raise_for_status()
    return r.json()


def gh_post(path: str, payload: dict) -> dict:
    r = requests.post(f"https://api.github.com{path}", headers=HEADERS, json=payload)
    r.raise_for_status()
    return r.json()


def gh_put(path: str, payload: dict = None) -> dict:
    r = requests.put(f"https://api.github.com{path}", headers=HEADERS, json=payload or {})
    r.raise_for_status()
    return r.json()


def post_pr_comment(hub_repo: str, pr_number: int, body: str) -> None:
    gh_post(f"/repos/{hub_repo}/issues/{pr_number}/comments", {"body": body})


def request_reviewer(hub_repo: str, pr_number: int, reviewer: str) -> None:
    gh_post(
        f"/repos/{hub_repo}/pulls/{pr_number}/requested_reviewers",
        {"reviewers": [reviewer]},
    )


# ---------------------------------------------------------------------------
# State helpers
# ---------------------------------------------------------------------------

def load_state(hw: str) -> dict:
    path = Path(f"state/{hw}.json")
    if path.exists():
        return json.loads(path.read_text())
    return {"students": {}, "pending": []}


def save_state(hw: str, state: dict) -> None:
    path = Path(f"state/{hw}.json")
    path.parent.mkdir(exist_ok=True)
    path.write_text(json.dumps(state, indent=2, ensure_ascii=False))


def ensure_student(state: dict, login: str) -> dict:
    if login not in state["students"]:
        state["students"][login] = {
            "pr_url": None,
            "pr_number": None,
            "submitted_at": None,
            "reviewers_assigned": [],   # incoming: who reviews this student
            "reviewer_assigned_at": {}, # incoming: when each reviewer was assigned
            "reviews_received": 0,
            "reviewing": [],            # outgoing: who this student reviews
            "reviews_given": 0,
            "completed": False,
        }
    return state["students"][login]


# ---------------------------------------------------------------------------
# Reviewer selection
# ---------------------------------------------------------------------------

def find_reviewer(submitter: str, state: dict) -> str | None:
    students = state["students"]
    submitter_data = students[submitter]

    candidates = []
    for login, data in students.items():
        if login == submitter:
            continue
        if data["pr_url"] is None:
            continue  # hasn't submitted yet
        if login in submitter_data["reviewers_assigned"]:
            continue  # already assigned to review this student
        if submitter in data["reviewers_assigned"]:
            continue  # A↔B prevention: login already reviews submitter
        if len(data["reviewing"]) >= MAX_REVIEWS_PER_STUDENT:
            continue  # overloaded (count assigned, not completed)
        # Primary key: current assigned load (assigned but not yet completed).
        # Secondary key: completed reviews — tie-break in favour of less experienced reviewers.
        candidates.append((login, len(data["reviewing"]), data.get("reviews_given", 0)))

    if not candidates:
        return None

    candidates.sort(key=lambda x: (x[1], x[2]))
    return candidates[0][0]


# ---------------------------------------------------------------------------
# Main logic
# ---------------------------------------------------------------------------

def process_submission(hw: str, author: str, pr_number: int, pr_url: str) -> None:
    state = load_state(hw)

    author_data = ensure_student(state, author)

    # Block re-submission: a PR for this HW already exists in state.
    # Automatic reset is unsafe: we cannot distinguish an accidental duplicate
    # PR from an intentional re-submission, and either way the correct workflow
    # is to push changes to the existing branch (which updates the open PR).
    # Manual instructor reset: edit state/{hw}.json directly.
    if author_data["pr_url"] is not None and author_data["pr_url"] != pr_url:
        post_pr_comment(
            HUB_REPO,
            pr_number,
            f"❌ @{author}, для **{hw}** уже существует активный PR: {author_data['pr_url']}\n\n"
            f"Пожалуйста, закройте этот PR и внесите изменения в существующий:\n"
            f"```\n"
            f"git checkout {author}/{hw}\n"
            f"# внесите правки\n"
            f"git push origin {author}/{hw}\n"
            f"```\n"
            f"Если вам нужно сбросить состояние рецензирования — обратитесь к преподавателю.",
        )
        print(f"Blocked re-submission for {author}: existing PR {author_data['pr_url']}")
        sys.exit(1)

    author_data["pr_url"] = pr_url
    author_data["pr_number"] = pr_number
    author_data["submitted_at"] = datetime.now(timezone.utc).isoformat()

    # Process pending students first: they submitted earlier and waited longest.
    # Doing this before assigning reviewers for the new author means the new
    # submitter (B) becomes a candidate for pending students (A), not the other
    # way around. Early submission is rewarded, not penalised.
    still_pending = []
    for pending_author in state.get("pending", []):
        if pending_author == author:
            continue
        pending_data = state["students"][pending_author]
        while len(pending_data["reviewers_assigned"]) < 2:
            reviewer = find_reviewer(pending_author, state)
            if reviewer is None:
                break
            reviewer_data = ensure_student(state, reviewer)
            pending_data["reviewers_assigned"].append(reviewer)
            pending_data.setdefault("reviewer_assigned_at", {})[reviewer] = (
                datetime.now(timezone.utc).isoformat()
            )
            reviewer_data["reviewing"].append(pending_author)
            request_reviewer(HUB_REPO, pending_data["pr_number"], reviewer)
            print(f"(pending) Assigned {reviewer} to review {pending_author}")

        if len(pending_data["reviewers_assigned"]) < 2:
            still_pending.append(pending_author)

    state["pending"] = still_pending

    # Now find reviewers for the new author from whoever is still available
    assigned_now = []
    while len(author_data["reviewers_assigned"]) < 2:
        reviewer = find_reviewer(author, state)
        if reviewer is None:
            break
        reviewer_data = ensure_student(state, reviewer)
        author_data["reviewers_assigned"].append(reviewer)
        author_data.setdefault("reviewer_assigned_at", {})[reviewer] = (
            datetime.now(timezone.utc).isoformat()
        )
        reviewer_data["reviewing"].append(author)

        request_reviewer(HUB_REPO, pr_number, reviewer)
        assigned_now.append(reviewer)
        print(f"Assigned {reviewer} to review {author}")

    # If author still needs reviewers, add to pending
    if len(author_data["reviewers_assigned"]) < 2:
        state["pending"].append(author)
        missing = 2 - len(author_data["reviewers_assigned"])
        comment = (
            f"👋 @{author}, ваша работа принята на peer review.\n\n"
            + (f"Назначен рецензент: {', '.join('@' + r for r in assigned_now)}.\n" if assigned_now else "")
            + f"⏳ Ещё {missing} рецензент(а) будет назначен(ы) позже — недостаточно сдавших работу.\n\n"
            f"**Напоминание:** для получения зачёта вам нужно самому проверить 2 чужие работы "
            f"(оставить рецензию + минимум {MIN_COMMENTS_REQUIRED} комментария)."
        )
    else:
        comment = (
            f"👋 @{author}, ваша работа принята на peer review.\n\n"
            f"Назначены рецензенты: {', '.join('@' + r for r in author_data['reviewers_assigned'])}.\n\n"
            f"**Напоминание:** для получения зачёта вам нужно самому проверить 2 чужие работы "
            f"(оставить рецензию + минимум {MIN_COMMENTS_REQUIRED} комментария)."
        )

    post_pr_comment(HUB_REPO, pr_number, comment)
    save_state(hw, state)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--hw", required=True, help="e.g. hw2")
    parser.add_argument("--author", required=True, help="GitHub login of PR author")
    parser.add_argument("--pr", required=True, type=int, help="PR number in peer-review-hub")
    parser.add_argument("--pr-url", required=True, help="PR HTML URL")
    args = parser.parse_args()

    process_submission(args.hw, args.author, args.pr, args.pr_url)


if __name__ == "__main__":
    main()
