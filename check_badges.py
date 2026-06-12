#!/usr/bin/env python3
"""Check your GitHub Achievements progress from the command line.

Usage:
    python3 check_badges.py [username]

Scrapes the public achievements tab for the given user (default: erickyy29),
prints each earned badge with its tier, and shows how far the next tier is.
If the `gh` CLI is installed and authenticated, also shows your exact merged
PR count for Pull Shark progress.

No tokens or dependencies required — stdlib only.
"""

from __future__ import annotations

import re
import subprocess
import sys
import urllib.request

# tier thresholds per badge: counts needed for base, x2, x3, x4
TIERS = {
    "Pull Shark": [2, 16, 128, 1024],
    "Pair Extraordinaire": [1, 10, 24, 48],
    "Galaxy Brain": [2, 8, 16, 32],
    "Starstruck": [16, 128, 512, 4096],
    "Quickdraw": [1],
    "YOLO": [1],
    "Public Sponsor": [1],
}

# badges shown as missing if not earned yet (the realistically obtainable set)
OBTAINABLE = list(TIERS)


def fetch_achievements(user: str) -> dict[str, int]:
    """Return {badge name: tier} for earned badges. Tier 1 = base, 2 = x2, ..."""
    url = f"https://github.com/{user}?tab=achievements"
    req = urllib.request.Request(url, headers={"User-Agent": "badge-quest"})
    html = urllib.request.urlopen(req, timeout=15).read().decode()

    earned: dict[str, int] = {}
    # each card: alt="Achievement: <name>" ... optional "x<multiplier>" label
    for name, mult in re.findall(
        r'alt="Achievement: ([^"]+)".{0,600}?(?:x(\d+))?</', html, re.S
    ):
        tier = int(mult) if mult else 1
        earned[name] = max(earned.get(name, 0), tier)
    return earned


def merged_pr_count(user: str) -> int | None:
    """Exact merged-PR count via gh CLI, or None if gh is unavailable."""
    try:
        out = subprocess.run(
            ["gh", "api", f"search/issues?q=author:{user}+type:pr+is:merged",
             "--jq", ".total_count"],
            capture_output=True, text=True, timeout=30,
        )
        return int(out.stdout.strip()) if out.returncode == 0 else None
    except (FileNotFoundError, ValueError, subprocess.TimeoutExpired):
        return None


def main() -> None:
    user = sys.argv[1] if len(sys.argv) > 1 else "erickyy29"
    earned = fetch_achievements(user)
    prs = merged_pr_count(user)

    print(f"\nGitHub Achievements — {user}\n" + "=" * 40)

    for badge in OBTAINABLE:
        thresholds = TIERS[badge]
        tier = earned.get(badge, 0)
        maxed = tier >= len(thresholds)

        if tier == 0:
            status, progress = "✗ not earned", f"first tier at {thresholds[0]}"
        elif maxed:
            status, progress = f"✓ x{tier} (MAXED)", ""
        else:
            status = f"✓ x{tier}"
            progress = f"next tier at {thresholds[tier]}"

        line = f"  {badge:<22} {status}"
        if badge == "Pull Shark" and prs is not None and not maxed:
            line += f"  ({prs} merged PRs, {progress})"
        elif progress:
            line += f"  ({progress})"
        print(line)

    unknown = sorted(set(earned) - set(TIERS))
    if unknown:
        print(f"\n  also earned: {', '.join(unknown)}")
    print()


if __name__ == "__main__":
    main()
