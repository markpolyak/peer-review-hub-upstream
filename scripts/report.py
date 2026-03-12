#!/usr/bin/env python3
"""
Prints a summary table of peer review status for all students.

Usage:
    python scripts/report.py --hw hw2
"""

import argparse
import json
from pathlib import Path


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

    print(f"\n{'Login':<20} {'Submitted':<6} {'Rev.received':<14} {'Rev.given':<11} {'Waiting':<9} {'Complete'}")
    print("-" * 75)

    for login, d in sorted(students.items()):
        submitted = "✓" if d.get("pr_url") else "✗"
        received = f"{d.get('reviews_received', 0)}/2"
        given = f"{d.get('reviews_given', 0)}/2"
        waiting = "⏳" if login in pending else ""
        complete = "✓" if d.get("completed") else ""
        print(f"{login:<20} {submitted:<6} {received:<14} {given:<11} {waiting:<9} {complete}")


if __name__ == "__main__":
    main()
