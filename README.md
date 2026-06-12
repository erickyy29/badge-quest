# badge-quest 🏆

Track your GitHub Achievements progress from the terminal.

```bash
python3 check_badges.py            # defaults to erickyy29
python3 check_badges.py <username> # any public profile
```

Example output:

```
GitHub Achievements — erickyy29
========================================
  Pull Shark             ✓ x2  (82 merged PRs, next tier at 128)
  Pair Extraordinaire    ✓ x1  (next tier at 10)
  Galaxy Brain           ✓ x1  (next tier at 8)
  Starstruck             ✗ not earned  (first tier at 16)
  Quickdraw              ✓ x1 (MAXED)
  YOLO                   ✓ x1 (MAXED)
  Public Sponsor         ✗ not earned  (first tier at 1)
```

No dependencies, no tokens — it reads the public achievements tab. If the
[`gh` CLI](https://cli.github.com/) is installed and logged in, Pull Shark
also shows your exact merged-PR count.

## Tier thresholds

| Badge | How you earn it | Base | x2 | x3 | x4 |
|---|---|---|---|---|---|
| Pull Shark | merged pull requests | 2 | 16 | 128 | 1024 |
| Pair Extraordinaire | merged PRs with a co-authored commit | 1 | 10 | 24 | 48 |
| Galaxy Brain | accepted answers in Discussions | 2 | 8 | 16 | 32 |
| Starstruck | stars on one repository | 16 | 128 | 512 | 4096 |
| Quickdraw | close an issue/PR within 5 min of opening | 1 | — | — | — |
| YOLO | merge a PR with no review | 1 | — | — | — |
| Public Sponsor | sponsor a developer via GitHub Sponsors | 1 | — | — | — |

Retired and unobtainable: Arctic Code Vault Contributor, Mars 2020 Helicopter
Contributor. Beta-only (never generally released): Heart On Your Sleeve,
Open Sourcerer.

## Ground rules

Earn badges through real activity on your own repos. Star rings, bought
stars, sockpuppet accounts, and junk PRs to other people's projects violate
GitHub's [spam policy](https://docs.github.com/en/site-policy/acceptable-use-policies/github-acceptable-use-policies)
and are the fastest way to lose the account the badges live on.
