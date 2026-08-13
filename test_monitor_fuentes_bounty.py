import json
import unittest
from datetime import datetime, timezone
from decimal import Decimal

from monitor_fuentes_bounty import (
    MIN_USD,
    TARGET_TOTAL_USD,
    aggregate_algora_bounties,
    algora_candidates,
    bountyhub_candidates,
    execution_market_candidates,
    gitwork_candidates,
    issuehunt_candidates,
    moltjobs_candidates,
    parse_algora_bounties,
    parse_issuehunt_issues,
    parse_opire_bounties,
    parse_tari_bounties,
    payanagent_candidates,
    superteam_current_listings,
    taskmarket_candidates,
    tari_candidates,
)


class CandidateFiltersTest(unittest.TestCase):
    def test_small_task_threshold_is_separate_from_total_goal(self):
        self.assertEqual(MIN_USD, Decimal("1"))
        self.assertEqual(TARGET_TOTAL_USD, Decimal("5"))

    def test_moltjobs_requires_live_deadline_and_funded_unassigned_job(self):
        now = datetime(2026, 8, 13, tzinfo=timezone.utc)
        base = {
            "id": "funded",
            "title": "Implement parser",
            "status": "OPEN",
            "budgetUsdc": "2",
            "deadlineAt": "2026-08-14T00:00:00Z",
            "escrowTxHash": "0xabc",
            "agentId": None,
        }
        self.assertEqual([item["id"] for item in moltjobs_candidates([base], now)], ["funded"])
        self.assertEqual(moltjobs_candidates([{**base, "escrowTxHash": None}], now), [])
        self.assertEqual(
            moltjobs_candidates([{**base, "deadlineAt": "2026-08-12T00:00:00Z"}], now), []
        )

    def test_execution_market_uses_net_reward_and_remote_categories(self):
        now = datetime(2026, 8, 13, tzinfo=timezone.utc)
        tasks = [
            {
                "id": "remote",
                "title": "Research API",
                "status": "published",
                "bounty_usd": 2,
                "category": "research",
                "deadline": "2026-08-14T00:00:00Z",
                "max_executors": 1,
                "payment_network": "base",
            },
            {
                "id": "physical",
                "status": "published",
                "bounty_usd": 20,
                "category": "physical_presence",
                "deadline": "2026-08-14T00:00:00Z",
                "max_executors": 1,
            },
            {
                "id": "tiny",
                "status": "published",
                "bounty_usd": 1,
                "category": "research",
                "deadline": "2026-08-14T00:00:00Z",
                "max_executors": 1,
            },
        ]
        found = execution_market_candidates(tasks, now)
        self.assertEqual([item["id"] for item in found], ["remote"])
        self.assertEqual(found[0]["net_usd"], 1.74)

    def test_opire_parser_extracts_next_flight_bounty_and_unique_competitors(self):
        bounty = {
            "id": "reward-1",
            "title": "Fix parser bug",
            "url": "https://github.com/acme/tool/issues/7",
            "pendingPrice": {"value": 4200, "unit": "USD_CENT"},
            "tryingUsers": [{"id": "user-1", "username": "one"}],
            "claimerUsers": [{"id": "user-1", "username": "one"}],
            "project": {"isBotInstalled": True},
        }
        flight = json.dumps({"children": [bounty]}, separators=(",", ":"))
        page = "<script>self.__next_f.push(" + json.dumps([1, flight]) + ")</script>"
        parsed = parse_opire_bounties(page)
        self.assertEqual(len(parsed), 1)
        self.assertEqual(parsed[0]["gross_usd"], 42.0)
        self.assertEqual(parsed[0]["competitors_shown"], 1)
        self.assertTrue(parsed[0]["bot_installed"])

    def test_issuehunt_parser_preserves_state_funding_and_pr_count(self):
        page = '''
        <div class="list-group-item"><a class="text-body" href="/r/acme/tool/issues/7"><svg class="issueStateIcon open"></svg>Fix parser bug</a>
        <strong>2<!-- --> <!-- -->pull requests</strong><strong><span><span>$</span>25.00</span></strong></div>
        <div class="list-group-item"><a class="text-body" href="/r/acme/tool/issues/8"><svg class="issueStateIcon closed"></svg>Closed docs bug</a>
        <strong><span><span>$</span>50.00</span></strong></div>
        '''
        parsed = parse_issuehunt_issues(page)
        self.assertEqual(parsed[0]["state"], "open")
        self.assertEqual(parsed[0]["gross_usd"], 25.0)
        self.assertEqual(parsed[0]["competitors"], 2)
        self.assertEqual([item["id"] for item in issuehunt_candidates(parsed)], ["acme/tool#7"])

    def test_issuehunt_rejects_non_bounded_or_crowded_work(self):
        entries = [
            {"repository": "a/r", "issue_number": 1, "state": "open", "gross_usd": 20, "competitors": 0, "title": "Build entire platform"},
            {"repository": "a/r", "issue_number": 2, "state": "open", "gross_usd": 20, "competitors": 3, "title": "Fix parser bug"},
            {"repository": "a/r", "issue_number": 3, "state": "closed", "gross_usd": 20, "competitors": 0, "title": "Fix parser bug"},
        ]
        self.assertEqual(issuehunt_candidates(entries), [])

    def test_issuehunt_rejects_previously_audited_false_positive(self):
        entries = [{
            "repository": "cyclejs/cyclejs",
            "issue_number": 857,
            "title": "Basic mouseenter event broken",
            "state": "open",
            "gross_usd": 60,
            "competitors": 0,
            "url": "https://github.com/cyclejs/cyclejs/issues/857",
        }]
        self.assertEqual(issuehunt_candidates(entries), [])

    def test_algora_parser_aggregates_funding_and_claims(self):
        page = """
        <table><tr><td><div>$25</div><a href="https://github.com/acme/tool/issues/7">tool#7</a></td><td>2 claims</td></tr>
        <tr><td><div>$10</div><a href="https://github.com/acme/tool/issues/7">tool#7</a></td><td>1 claim</td></tr></table>
        """
        parsed = parse_algora_bounties(page)
        self.assertEqual(len(parsed), 2)
        aggregate = aggregate_algora_bounties(parsed)
        self.assertEqual(aggregate[0]["gross_usd"], 35.0)
        self.assertEqual(aggregate[0]["competitors"], 2)

    def test_algora_requires_live_issue_and_unarchived_repository(self):
        entries = [
            {"url": "https://github.com/acme/live/issues/1", "repository": "acme/live", "issue_number": 1, "gross_usd": 20, "competitors": 1},
            {"url": "https://github.com/acme/closed/issues/2", "repository": "acme/closed", "issue_number": 2, "gross_usd": 20, "competitors": 0},
            {"url": "https://github.com/acme/archive/issues/3", "repository": "acme/archive", "issue_number": 3, "gross_usd": 20, "competitors": 0},
            {"url": "https://github.com/acme/crowded/issues/4", "repository": "acme/crowded", "issue_number": 4, "gross_usd": 20, "competitors": 3},
        ]

        def issue_lookup(repository, issue_number):
            return {"state": "closed" if repository == "acme/closed" else "open", "title": f"Issue {issue_number}"}

        def repo_lookup(repository):
            return {"archived": repository == "acme/archive", "disabled": False}

        def pulls_lookup(repository):
            if repository == "acme/live":
                return [{"title": "Unrelated", "body": "Fixes #99"}]
            return []

        candidates, stats = algora_candidates(entries, issue_lookup, repo_lookup, pulls_lookup)
        self.assertEqual([item["id"] for item in candidates], ["acme/live#1"])
        self.assertEqual(stats["closed"], 1)
        self.assertEqual(stats["archived"], 1)
        self.assertEqual(stats["crowded"], 1)

    def test_algora_counts_open_prs_linked_to_issue(self):
        entries = [{
            "url": "https://github.com/acme/tool/issues/7",
            "repository": "acme/tool",
            "issue_number": 7,
            "gross_usd": 30,
            "competitors": 0,
        }]
        pulls = [
            {"title": "Fix generator", "body": "Fixes #7"},
            {"title": "Alternative", "body": "/claim #7"},
            {"title": "Third", "body": "Closes #7"},
            {"title": "Unrelated", "body": "Fixes #70"},
        ]
        candidates, stats = algora_candidates(
            entries,
            lambda repository, issue_number: {"state": "open", "title": "Issue"},
            lambda repository: {"archived": False, "disabled": False},
            lambda repository: pulls,
        )
        self.assertEqual(candidates, [])
        self.assertEqual(stats["crowded"], 1)

    def test_taskmarket_applies_fee_scaled_reward_and_competition(self):
        tasks = [
            {"id": "good", "netReward": "5000000", "submissionCount": 2, "description": "# Good"},
            {"id": "small", "netReward": "999999", "submissionCount": 0, "description": "Small"},
            {"id": "crowded", "netReward": "9000000", "submissionCount": 3, "description": "Crowded"},
        ]
        self.assertEqual([item["id"] for item in taskmarket_candidates(tasks)], ["good"])

    def test_known_rejected_taskmarket_candidate_stays_suppressed(self):
        tasks = [{
            "id": "0xf41d2979b5765bda2feedd0fc6ddd8d736bc74a11f549fd31c2e0e2aecb858a6",
            "netReward": "92500000",
            "submissionCount": 1,
            "description": "Paintbot",
        }]
        self.assertEqual(taskmarket_candidates(tasks), [])

    def test_bountyhub_requires_paid_open_unassigned_bounty(self):
        base = {
            "id": "good",
            "totalAmount": "20",
            "paymentStatus": "PAID",
            "solved": False,
            "retracted": False,
            "assignee": None,
            "assignmentType": "open",
        }
        self.assertEqual(len(bountyhub_candidates([base])), 1)
        self.assertEqual(len(bountyhub_candidates([{**base, "paymentStatus": "PROMISED"}])), 0)
        self.assertEqual(len(bountyhub_candidates([{**base, "assignee": {"id": "taken"}}])), 0)

    def test_gitwork_uses_current_usd_value(self):
        bounties = [
            {"id": 1, "valueUsd": 5, "claimedBy": None},
            {"id": 2, "valueUsd": 0.99, "claimedBy": None},
            {"id": 3, "valueUsd": 50, "claimedBy": "someone"},
        ]
        self.assertEqual([item["id"] for item in gitwork_candidates(bounties)], [1])

    def test_payanagent_requires_open_escrow_and_minimum_reward(self):
        requests = [
            {"id": "good", "status": "open", "escrow": True, "budgetMaxCents": 500},
            {"id": "tiny", "status": "open", "escrow": True, "budgetMaxCents": 5},
            {"id": "promise", "status": "open", "escrow": False, "budgetMaxCents": 1000},
            {"id": "closed", "status": "closed", "escrow": True, "budgetMaxCents": 1000},
        ]
        self.assertEqual([item["id"] for item in payanagent_candidates(requests)], ["good"])

    def test_superteam_excludes_announced_and_expired_listings(self):
        now = datetime(2026, 8, 12, tzinfo=timezone.utc)
        listings = [
            {"id": "future", "deadline": "2026-08-13T00:00:00Z", "isWinnersAnnounced": False},
            {"id": "expired", "deadline": "2026-08-11T00:00:00Z", "isWinnersAnnounced": False},
            {"id": "announced", "deadline": "2026-08-13T00:00:00Z", "isWinnersAnnounced": True},
        ]
        self.assertEqual([item["id"] for item in superteam_current_listings(listings, now)], ["future"])

    def test_tari_parser_values_open_board_rows_and_filters_competition(self):
        board = """
| [#7 â€” Fix bounded parser](https://github.com/tari-project/tool/issues/7) | tool | S | 15,000 | @maintainer | ðŸŸ¢ Open | â€” | ðŸ’¬ 0 |
| [#8 â€” Existing attempt](https://github.com/tari-project/tool/issues/8) | tool | S | 15,000 | @maintainer | ðŸŸ¡ PR Open | [1 PR](https://github.com/tari-project/tool/pulls) | ðŸ’¬ 1 |
| [#9 â€” Crowded task](https://github.com/tari-project/tool/issues/9) | tool | M | 60,000 | @maintainer | ðŸŸ¢ Open | [3 PRs](https://github.com/tari-project/tool/pulls) | ðŸ’¬ 3 |
"""
        parsed = parse_tari_bounties(board, Decimal("0.0005"))
        self.assertEqual(parsed[0]["gross_usd"], 7.5)
        self.assertEqual(parsed[1]["status"], "pr open")
        self.assertEqual([item["id"] for item in tari_candidates(parsed)], ["tari-project/tool#7"])


if __name__ == "__main__":
    unittest.main()
