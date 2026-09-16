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
import re
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
    # data layer — as used from an app, not as a DBA
    "prisma": 3, "supabase": 2, "sqlite": 3, "migration": 2, "prisma client": 3,
    "pooler": 3, "supavisor": 3, "pgbouncer": 3, "connection limit": 3,
    "too many connections": 3, "rls": 2, "row level security": 2,
    # next.js app router, the thing every project here is built on
    "app router": 3, "server action": 3, "route handler": 3, "middleware": 2,
    "server component": 3, "use client": 3, "hydration": 3, "revalidate": 3,
    "next 16": 3, "next.js 16": 3, "turbopack": 2, "edge runtime": 2,
    # scraping — the undici/WAF territory from binky-ugc-dashboard and orbit
    "playwright": 3, "scrape": 3, "scraping": 3, "headless": 2, "cheerio": 2,
    "undici": 3, "user-agent": 2, "sec-fetch": 3, "403": 2, "rate limit": 2,
    # charts and UI
    "recharts": 3, "responsivecontainer": 3, "framer-motion": 3,
    "tailwind": 2, "shadcn": 2, "radix": 2, "class-variance-authority": 2,
    # ship-it problems
    "vercel": 2, "build error": 3, "env var": 2, "cron": 2, "github action": 2,
    "localstorage": 2, "overflow": 2, "i32": 3, "float": 2,
}

# deep-DBA territory: heavy Postgres-internals questions score high on raw
# keyword overlap but you'd be researching an answer, not recalling one
NOISE = {
    "supabase_admin": 6, "pg_catalog": 6, "postgis": 6, "pg_net": 6,
    "pgsodium": 6, "security definer": 5, "logical decoding": 5,
    "tablespace": 5, "replication slot": 5, "wal": 4, "revoke": 4,
    "privilege": 4, "role ownership": 4, "partition": 3, "grant": 3,
    "vacuum": 4, "pg_dump": 3,
}

# project announcements dressed up as discussions — they match keywords
# heavily, sit in answerable categories, and are never marked answered
# Categories that can't produce a Galaxy Brain answer no matter what the API
# says. vercel/next.js marks "Show and tell" answerable, which let every
# project announcement in the repo through the isAnswerable check.
BLOCKED_CATEGORIES = {
    "show and tell", "feature requests", "ideas", "rfc", "polls", "feedback",
    "announcements", "jobs board", "changelog", "general",
}

# "ProductName: what it does" — the standard shape of a project pitch,
# with an em dash or a colon, optionally wrapped in backticks
PITCH_TITLE = re.compile(r"^[`\w.\-+ ]{2,24}\s*[:—–]\s*[A-Za-z]")

SHOWCASE = (
    "i built", "i've built", "ive built", "i made", "i have built",
    "introducing", "excited to share", "happy to share", "check out my",
    "production-ready", "feedback welcome", "would love feedback",
    "sharing my", "just shipped", "just launched", "show and tell",
    "here's a", "i created", "open-sourced",
    # recruitment for someone else's product — "help testing" slips past the
    # question-word exemption below, so match it outright
    "beta key", "beta test", "help testing", "looking for testers",
    "ui kit", "early access", "waitlist", "free beta", "try my",
)

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

    # only answerable categories can ever be marked as answered — and not
    # every category the API calls answerable actually produces answers
    if not d["category"]["isAnswerable"] or age > max_age_days:
        return 0, [], age
    if d["category"]["name"].strip().lower() in BLOCKED_CATEGORIES:
        return 0, [], age

    title = d["title"].lower()
    body = d["bodyText"][:2000].lower()

    points, matched = 0, []
    for keyword, weight in NOISE.items():
        if keyword in title or keyword in body:
            points -= weight
    for keyword, weight in EXPERTISE.items():
        if keyword in title:
            points += weight * 2
            matched.append(keyword)
        elif keyword in body:
            points += weight
            matched.append(keyword)
    if not matched:
        return 0, [], age

    # a showcase post can't be answered, so it can never count — drop it
    if any(marker in title or marker in body[:800] for marker in SHOWCASE):
        return 0, [], age
    # ...as can a project pitch, unless it's actually asking something
    if (PITCH_TITLE.match(d["title"])
            and "?" not in title
            and not set(title.split()) & QUESTION_WORDS):
        return 0, [], age

    # reward things actually shaped like a question
    asks = title.rstrip().endswith("?") or title.split(" ")[0] in QUESTION_WORDS
    points += 3 if asks else -1

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
