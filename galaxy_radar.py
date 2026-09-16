#!/usr/bin/env python3
"""Find unanswered GitHub Discussions worth answering, for the Galaxy Brain badge.

Usage:
    python3 galaxy_radar.py [--top 12] [--days 45] [--json]

Galaxy Brain only counts an answer when the discussion author marks it as THE
answer, which is only possible in Q&A-style (answerable) categories. This
script scans the repos you actually build on, keeps the recent unanswered
questions in answerable categories, scores them against what you've shipped,
and prints a shortlist.

It finds questions. You write the answers — never auto-post, never paste
generated text you can't defend. A wrong answer that gets marked correct
helps nobody, and answer-spam is exactly what gets accounts flagged.

Needs the `gh` CLI authenticated, or GITHUB_TOKEN set (as in CI).
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone

# repos whose discussions are in range — all verified to have answerable
# categories and a real backlog. Trim this to what you genuinely know.
REPOS = [
    "vercel/next.js",
    "supabase/supabase",
    "prisma/prisma",
    "shadcn-ui/ui",
    "tailwindlabs/tailwindcss",
    "vitejs/vite",
    "recharts/recharts",
    "motiondivision/motion",
    "vercel/vercel",
]

# what you've actually shipped and can defend in a review — keyword: weight.
# Edit freely; anything not in here scores 0 and drops off the list.
EXPERTISE = {
    "prisma": 3, "supabase": 3, "sqlite": 3, "postgres": 2, "migration": 2,
    "pooler": 3, "supavisor": 3, "pgbouncer": 3, "connection limit": 3,
    "app router": 3, "server action": 3, "route handler": 2, "middleware": 2,
    "server component": 2, "use client": 2, "hydration": 2, "revalidate": 2,
    "playwright": 3, "scrape": 3, "scraping": 3, "headless": 2, "cheerio": 2,
    "recharts": 3, "chart": 2, "responsivecontainer": 3, "tooltip": 1,
    "framer": 2, "motion": 1, "animation": 1,
    "tailwind": 2, "shadcn": 2, "radix": 1,
    "vercel": 2, "deploy": 2, "build error": 2, "env var": 2, "cron": 2,
    "github action": 2, "localstorage": 2, "float": 1, "overflow": 2,
    "typescript": 1, "seed": 1, "schema": 1,
}

# one repo per request: batching them all blows GitHub's GraphQL complexity limit
QUESTION_WORDS = {
    "how", "why", "what", "when", "where", "which", "who", "can", "cant",
    "does", "do", "is", "are", "should", "would", "could", "any", "help",
}

QUERY = """{
  repository(owner: "%s", name: "%s") {
    nameWithOwner
    discussions(first: 30, answered: false, orderBy: {field: CREATED_AT, direction: DESC}) {
      nodes {
        title url createdAt upvoteCount bodyText
        comments { totalCount }
        category { name isAnswerable }
      }
    }
  }
}"""


def graphql(query: str) -> dict:
    """Run a GraphQL query via gh CLI, falling back to GITHUB_TOKEN + urllib."""
    try:
        out = subprocess.run(
            ["gh", "api", "graphql", "-f", f"query={query}"],
            capture_output=True, text=True, timeout=90,
        )
        if out.returncode == 0:
            return json.loads(out.stdout)
        err = out.stderr.strip()
    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        err = str(exc)

    token = os.environ.get("GITHUB_TOKEN")
    if not token:
        sys.exit(f"gh CLI failed and GITHUB_TOKEN is unset: {err}")

    req = urllib.request.Request(
        "https://api.github.com/graphql",
        data=json.dumps({"query": query}).encode(),
        headers={"Authorization": f"bearer {token}",
                 "Content-Type": "application/json",
                 "User-Agent": "badge-quest"},
    )
    try:
        with urllib.request.urlopen(req, timeout=90) as resp:
            return json.load(resp)
    except urllib.error.HTTPError as exc:
        sys.exit(f"GraphQL request failed: {exc.code} {exc.read()[:200]!r}")


def fetch(repos: list[str]) -> list[dict]:
    """Recent unanswered discussions across every configured repo."""
    found = []
    for repo in repos:
        owner, name = repo.split("/", 1)
        payload = graphql(QUERY % (owner, name))

        for error in payload.get("errors", [])[:2]:
            print(f"  warning: {repo}: {error.get('message', '')[:90]}", file=sys.stderr)

        node = (payload.get("data") or {}).get("repository")
        if not node:
            continue
        for d in node["discussions"]["nodes"]:
            d["repo"] = node["nameWithOwner"]
            found.append(d)
    return found


def clip(text: str, width: int) -> str:
    """Trim to width on a word boundary, with an ellipsis if anything was cut."""
    if len(text) <= width:
        return text
    return text[:width].rsplit(" ", 1)[0] + "…"


def score(d: dict, max_age_days: int) -> tuple[int, list[str], int]:
    """Return (score, matched keywords, age in days). Score 0 means skip."""
    created = datetime.fromisoformat(d["createdAt"].replace("Z", "+00:00"))
    age = (datetime.now(timezone.utc) - created).days

    # only answerable categories can ever be marked as answered
    if not d["category"]["isAnswerable"] or age > max_age_days:
        return 0, [], age

    title = d["title"].lower()
    body = d["bodyText"][:2000].lower()

    points, matched = 0, []
    for keyword, weight in EXPERTISE.items():
        if keyword in title:
            points += weight * 2
            matched.append(keyword)
        elif keyword in body:
            points += weight
            matched.append(keyword)
    if not matched:
        return 0, [], age

    # showcase and RFC posts match keywords heavily but nobody marks them
    # answered — reward things actually shaped like a question
    asks = title.rstrip().endswith("?") or title.split(" ")[0] in QUESTION_WORDS
    points += 3 if asks else -3

    # fresher questions are likelier to get an answer marked — the asker is
    # still around and still stuck
    points += 4 if age <= 3 else 3 if age <= 7 else 2 if age <= 14 else 1 if age <= 30 else 0
    # nobody has taken a swing at it yet
    comments = d["comments"]["totalCount"]
    points += 2 if comments == 0 else -2 if comments > 5 else 0

    return points, matched, age


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--top", type=int, default=12, help="how many to show")
    ap.add_argument("--days", type=int, default=45, help="ignore questions older than this")
    ap.add_argument("--repos", nargs="*", default=REPOS, help="owner/name repos to scan")
    ap.add_argument("--json", action="store_true", help="emit JSON instead of a table")
    ap.add_argument("--markdown", action="store_true", help="emit a markdown checklist")
    args = ap.parse_args()

    ranked = []
    for d in fetch(args.repos):
        points, matched, age = score(d, args.days)
        if points > 0:
            ranked.append({
                "score": points, "age_days": age, "repo": d["repo"],
                "title": d["title"], "url": d["url"],
                "comments": d["comments"]["totalCount"],
                "matched": sorted(set(matched))[:5],
            })
    ranked.sort(key=lambda r: (-r["score"], r["age_days"]))
    ranked = ranked[: args.top]

    if args.json:
        print(json.dumps(ranked, indent=2))
        return

    if args.markdown:
        print("Unanswered questions in your lane this week. Answer the ones you've")
        print("actually hit in your own projects — an accepted answer counts toward")
        print("Galaxy Brain, a guessed one costs credibility.\n")
        for r in ranked:
            n = r["comments"]
            replies = "no replies yet" if n == 0 else f"{n} reply" if n == 1 else f"{n} replies"
            print(f"- [ ] [{clip(r['title'], 95)}]({r['url']})  \n"
                  f"      `{r['repo']}` · {r['age_days']}d old · {replies} · "
                  f"matched: {', '.join(r['matched'])}")
        return

    print(f"\nGalaxy Brain radar — {len(ranked)} unanswered questions in your lane\n" + "=" * 70)
    for r in ranked:
        n = r["comments"]
        comments = "no replies yet" if n == 0 else f"{n} reply" if n == 1 else f"{n} replies"
        print(f"\n  [{r['score']:>2}] {r['repo']} · {r['age_days']}d old · {comments}")
        print(f"       {clip(r['title'], 90)}")
        print(f"       {r['url']}")
        print(f"       matched: {', '.join(r['matched'])}")
    print("\n  Answer only what you've actually hit. Accepted answers count;"
          "\n  wrong ones cost you credibility you can't buy back.\n")


if __name__ == "__main__":
    main()
