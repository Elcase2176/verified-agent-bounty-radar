# Verified agent bounty radar

Read-only monitor for coding bounties and agent work with observable payment rails. It checks public inventories, validates GitHub state where possible, and rejects stale, unfunded, overcrowded, expired, or economically unsuitable tasks.

## Sources

The current monitor covers Algora, IssueHunt, Taskmarket, TaskBounty, BountyHub, GitWork, Code Bounty, MoltJobs, Execution Market, PayanAgent, Opire, Superteam, and Tari.

## Run

```bash
python -m unittest -v
python monitor_fuentes_bounty.py --output bounty-radar.json
```

`bounty-radar.json` contains the generation time, filter thresholds, source diagnostics, and preliminary candidates. A candidate is not a payment guarantee; every candidate still requires manual scope and eligibility review before work begins.

GitHub Actions runs the test suite and refreshes the feed every six hours.
