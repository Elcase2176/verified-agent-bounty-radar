#!/usr/bin/env python3
"""Read-only monitor for bounty sources with verifiable payment rails."""

from __future__ import annotations

import argparse
import html
import json
import os
import re
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any


USER_AGENT = "Codex-income-monitor/1.0"
MIN_USD = Decimal("1")
TARGET_TOTAL_USD = Decimal("5")
MAX_COMPETITORS = 2
EXCLUDED_TASKMARKET_IDS = {
    "0xf41d2979b5765bda2feedd0fc6ddd8d736bc74a11f549fd31c2e0e2aecb858a6",
}
EXCLUDED_BOUNTYHUB_IDS = {
    "5bd7b660-5c46-4686-bead-39a53699e98d",
    "27a47575-ef9f-49d3-9685-c056d6825f9d",
    "521afa31-6c6f-4d2c-becc-c6b14318d2b4",
}
EXCLUDED_TARI_IDS = {
    # Requires proof from physical Windows hardware with more than 64 logical cores.
    "tari-project/universe#3299",
}
EXCLUDED_ISSUEHUNT_IDS = {
    # Manually audited: closed/resolved, archived, crowded, unbounded, or hardware-bound.
    "kazup01/lowverflow#2",
    "Kreyren/git-workspace#1",
    "dnbradio/thelounge#1",
    "ffMathy/awesome-docker#1",
    "SelfhostedPro/selfhosted_templates#122",
    "droundy/bigbro#2",
    "FAForever/downlords-faf-client#3133",
    "tuzig/capacitor-ssh-plugin#3",
    "BoostIO/BoostNote-App#244",
    "BoostIO/BoostNote-App#726",
    "I-am-Erk/CDDA-Tilesets#148",
    "taskforcesh/bullmq#126",
    "ElemeFE/element#16703",
    "rvm/rvm#4694",
    "BoostIo/Boostnote#2984",
    "avajs/ava#595",
    "avajs/ava#1986",
    "egoist/saber#136",
    "piotrwitek/utility-types#30",
    "ElemeFE/element#8548",
    "pedronauck/docz#418",
    "avajs/ava#928",
    "cyclejs/cyclejs#618",
    "cyclejs/cyclejs#765",
    "BoostIo/Boostnote#2667",
    "swapagarwal/shoutlink#1",
    "ant-design/ant-design#11902",
    "ant-design/ant-design#12878",
    "ant-design/ant-design#13202",
    "cyclejs/cyclejs#233",
    "cyclejs/cyclejs#480",
    "cyclejs/cyclejs#583",
    "jfairbank/redux-saga-test-plan#93",
    "jfairbank/redux-saga-test-plan#109",
    "drcmda/react-spring#102",
    "cyclejs/cyclejs#802",
    "cyclejs/cyclejs#851",
    "cyclejs/cyclejs#857",
    "react-native-community/react-native-camera#1926",
    "gogs/gogs#1932",
    "PanJiaChen/vue-element-admin#439",
    "x64dbg/x64dbg#2065",
    "linkerd/linkerd#640",
    "NG-ZORRO/ng-zorro-antd#2027",
    "iview/iview#2273",
    "iview/iview#3472",
    "linkerd/linkerd#639",
    "sqlkata/querybuilder#35",
    "BoostIo/Boostnote#2248",
    "BoostIo/Boostnote#2252",
    "InvoicePlane/InvoicePlane#625",
    "BoostIo/Boostnote#1986",
}
ALGORA_ORGS = (
    "activepieces",
    "aqualinkorg",
    "arakoodev",
    "archestra-ai",
    "BasedHardware",
    "cal",
    "cloudgakkai",
    "daytonaio",
    "getkyo",
    "gyroflow",
    "highlight",
    "projectdiscovery",
    "SCIBASE.AI",
    "spaceandtimelabs",
    "triggerdotdev",
    "tscircuit",
)
ISSUEHUNT_MAX_PAGES = 42
OPIRE_UNCLAIMED_BANDS = ((5, 50), (50, 100), (100, 500), (500, 5000))
ISSUEHUNT_SMALL_TASK = re.compile(
    r"\b(fix|bug|error|test|tests|testing|docs|documentation|typo|race|crash|broken|"
    r"incorrect|fail|failure|cleanup|warning|lint|refactor)\b",
    flags=re.IGNORECASE,
)


def request_json(url: str, payload: dict[str, Any] | None = None) -> Any:
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=data,
        headers={"Accept": "application/json", "Content-Type": "application/json", "User-Agent": USER_AGENT},
        method="POST" if data is not None else "GET",
    )
    with urllib.request.urlopen(request, timeout=25) as response:
        return json.load(response)


def request_text(url: str) -> str:
    request = urllib.request.Request(
        url,
        headers={"Accept": "text/html", "User-Agent": USER_AGENT},
    )
    with urllib.request.urlopen(request, timeout=25) as response:
        return response.read().decode("utf-8", errors="strict")


def decimal(value: Any) -> Decimal:
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return Decimal("0")


def future_deadline(value: Any, now: datetime | None = None) -> bool:
    if not value:
        return False
    now = now or datetime.now(timezone.utc)
    try:
        deadline = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return False
    if deadline.tzinfo is None:
        deadline = deadline.replace(tzinfo=timezone.utc)
    return deadline > now


def moltjobs_candidates(jobs: list[dict[str, Any]], now: datetime | None = None) -> list[dict[str, Any]]:
    candidates = []
    for job in jobs:
        reward = decimal(job.get("budgetUsdc"))
        if (
            job.get("status") != "OPEN"
            or reward < MIN_USD
            or not future_deadline(job.get("deadlineAt"), now)
            or not job.get("escrowTxHash")
            or job.get("agentId")
        ):
            continue
        candidates.append(
            {
                "source": "MoltJobs",
                "id": job.get("id"),
                "title": job.get("title"),
                "gross_usd": float(reward),
                "escrow_tx": job.get("escrowTxHash"),
                "deadline": job.get("deadlineAt"),
                "url": f"https://moltjobs.io/open-jobs/{job.get('id')}",
                "needs_manual_scope_review": True,
            }
        )
    return candidates


EXECUTION_MARKET_REMOTE_CATEGORIES = {
    "data_collection",
    "knowledge_access",
    "research",
    "verification",
}


def execution_market_candidates(
    tasks: list[dict[str, Any]], now: datetime | None = None
) -> list[dict[str, Any]]:
    candidates = []
    for task in tasks:
        gross = decimal(task.get("bounty_usd"))
        net = gross * Decimal("0.87")
        if (
            task.get("status") != "published"
            or net < MIN_USD
            or task.get("category") not in EXECUTION_MARKET_REMOTE_CATEGORIES
            or not future_deadline(task.get("deadline"), now)
            or int(task.get("max_executors") or 0) < 1
        ):
            continue
        candidates.append(
            {
                "source": "Execution Market",
                "id": task.get("id"),
                "title": task.get("title"),
                "gross_usd": float(gross),
                "net_usd": float(net),
                "payment_network": task.get("payment_network"),
                "funding_status": "escrow locks only after publisher assigns worker",
                "deadline": task.get("deadline"),
                "needs_manual_scope_review": True,
            }
        )
    return candidates


def taskmarket_candidates(tasks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    candidates = []
    for task in tasks:
        if task.get("id") in EXCLUDED_TASKMARKET_IDS:
            continue
        net_usdc = decimal(task.get("netReward")) / Decimal("1000000")
        competitors = int(task.get("submissionCount") or 0)
        if net_usdc < MIN_USD or competitors > MAX_COMPETITORS:
            continue
        candidates.append(
            {
                "source": "Taskmarket",
                "id": task.get("id"),
                "title": (task.get("description") or "").splitlines()[0].lstrip("# "),
                "net_usd": float(net_usdc),
                "competitors": competitors,
                "escrow_tx": task.get("escrowTxHash"),
                "expires_at": task.get("expiryTime"),
                "needs_manual_scope_review": True,
            }
        )
    return candidates


def bountyhub_candidates(bounties: list[dict[str, Any]]) -> list[dict[str, Any]]:
    candidates = []
    for bounty in bounties:
        if bounty.get("id") in EXCLUDED_BOUNTYHUB_IDS:
            continue
        reward = decimal(bounty.get("totalAmount") or bounty.get("amount"))
        if (
            reward < MIN_USD
            or bounty.get("paymentStatus") != "PAID"
            or bounty.get("solved")
            or bounty.get("retracted")
            or bounty.get("assignee")
            or bounty.get("assignmentType") not in (None, "open")
        ):
            continue
        candidates.append(
            {
                "source": "BountyHub",
                "id": bounty.get("id"),
                "title": bounty.get("title"),
                "gross_usd": float(reward),
                "url": bounty.get("htmlURL"),
                "repository": bounty.get("repositoryFullName"),
                "needs_manual_scope_review": True,
            }
        )
    return candidates


def gitwork_candidates(bounties: list[dict[str, Any]]) -> list[dict[str, Any]]:
    candidates = []
    for bounty in bounties:
        value_usd = decimal(bounty.get("valueUsd"))
        if value_usd < MIN_USD or bounty.get("claimedBy"):
            continue
        candidates.append(
            {
                "source": "GitWork",
                "id": bounty.get("id"),
                "title": bounty.get("name"),
                "gross_usd": float(value_usd),
                "url": bounty.get("githubUrl"),
                "needs_manual_scope_review": True,
            }
        )
    return candidates


def payanagent_candidates(requests: list[dict[str, Any]]) -> list[dict[str, Any]]:
    candidates = []
    for item in requests:
        budget_cents = decimal(item.get("budgetMaxCents"))
        if item.get("status") != "open" or item.get("escrow") is not True or budget_cents < MIN_USD * 100:
            continue
        candidates.append(
            {
                "source": "PayanAgent",
                "id": item.get("id"),
                "title": item.get("title"),
                "gross_usd": float(budget_cents / 100),
                "escrowed": True,
                "needs_manual_scope_review": True,
            }
        )
    return candidates


def superteam_current_listings(listings: list[dict[str, Any]], now: datetime | None = None) -> list[dict[str, Any]]:
    now = now or datetime.now(timezone.utc)
    current = []
    for listing in listings:
        deadline = listing.get("deadline")
        if not deadline or listing.get("isWinnersAnnounced"):
            continue
        try:
            parsed = datetime.fromisoformat(str(deadline).replace("Z", "+00:00"))
        except ValueError:
            continue
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        if parsed > now:
            current.append(listing)
    return current


def parse_algora_bounties(page: str) -> list[dict[str, Any]]:
    """Extract open Algora rows without trusting Algora's GitHub state cache."""
    entries: list[dict[str, Any]] = []
    for row in re.findall(r"<tr\b[^>]*>(.*?)</tr>", page, flags=re.IGNORECASE | re.DOTALL):
        issue_match = re.search(
            r'href="(https://github\.com/([^/]+)/([^/]+)/issues/(\d+))"',
            row,
            flags=re.IGNORECASE,
        )
        amount_match = re.search(r">\s*\$([\d,]+(?:\.\d+)?)\s*<", row)
        if not issue_match or not amount_match:
            continue
        claims_match = re.search(r"\b(\d+)\s+claims?\b", html.unescape(re.sub(r"<[^>]+>", " ", row)))
        entries.append(
            {
                "url": issue_match.group(1),
                "repository": f"{issue_match.group(2)}/{issue_match.group(3)}",
                "issue_number": int(issue_match.group(4)),
                "gross_usd": float(decimal(amount_match.group(1).replace(",", ""))),
                "competitors": int(claims_match.group(1)) if claims_match else 0,
            }
        )
    return entries


def aggregate_algora_bounties(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, dict[str, Any]] = {}
    for entry in entries:
        key = entry["url"]
        if key not in grouped:
            grouped[key] = dict(entry)
        else:
            grouped[key]["gross_usd"] += entry["gross_usd"]
            grouped[key]["competitors"] = max(grouped[key]["competitors"], entry["competitors"])
    return list(grouped.values())


def parse_issuehunt_issues(page: str) -> list[dict[str, Any]]:
    """Parse IssueHunt cards, including the live open/closed icon state."""
    entries: list[dict[str, Any]] = []
    for card in page.split('<div class="list-group-item">')[1:]:
        issue_match = re.search(r'href="/r/([^/]+/[^/]+)/issues/(\d+)"', card)
        amount_match = re.search(r'<span>\$</span>([\d,.]+)', card)
        if not issue_match or not amount_match:
            continue
        title_match = re.search(r'class="text-body"[^>]*>.*?</svg>(.*?)</a>', card, flags=re.DOTALL)
        icon = card[:2500]
        state_match = re.search(r'issueStateIcon[^\"]*\b(open|closed)\b', icon)
        pull_match = re.search(r'(\d+)<!-- --> <!-- -->pull requests?', card)
        title = ""
        if title_match:
            title = html.unescape(re.sub(r"<[^>]+>", "", title_match.group(1))).strip()
        repository = issue_match.group(1)
        issue_number = int(issue_match.group(2))
        entries.append(
            {
                "url": f"https://github.com/{repository}/issues/{issue_number}",
                "issuehunt_url": f"https://oss.issuehunt.io/r/{repository}/issues/{issue_number}",
                "repository": repository,
                "issue_number": issue_number,
                "title": title,
                "state": state_match.group(1) if state_match else "unknown",
                "gross_usd": float(decimal(amount_match.group(1).replace(",", ""))),
                "competitors": int(pull_match.group(1)) if pull_match else 0,
            }
        )
    return entries


def parse_opire_bounties(page: str) -> list[dict[str, Any]]:
    """Extract Opire's server-rendered bounty objects from Next.js flight data."""
    chunks: list[str] = []
    for match in re.finditer(
        r"self\.__next_f\.push\((\[.*?\])\)</script>",
        page,
        flags=re.DOTALL,
    ):
        try:
            payload = json.loads(match.group(1))
        except json.JSONDecodeError:
            continue
        if len(payload) > 1 and isinstance(payload[1], str):
            chunks.append(payload[1])

    flight_data = "".join(chunks)
    decoder = json.JSONDecoder()
    entries: list[dict[str, Any]] = []
    position = 0
    while True:
        position = flight_data.find('{"id":"', position)
        if position < 0:
            break
        try:
            item, consumed = decoder.raw_decode(flight_data[position:])
        except json.JSONDecodeError:
            position += 1
            continue
        position += max(consumed, 1)
        if not isinstance(item, dict) or not {"title", "url", "pendingPrice"} <= item.keys():
            continue
        issue_match = re.fullmatch(
            r"https://github\.com/([^/]+/[^/]+)/issues/(\d+)",
            str(item.get("url") or ""),
        )
        if not issue_match:
            continue
        participants = {
            str(user.get("id") or user.get("username"))
            for field in ("tryingUsers", "claimerUsers")
            for user in (item.get(field) or [])
            if user.get("id") or user.get("username")
        }
        price = item.get("pendingPrice") or {}
        entries.append(
            {
                "id": item.get("id"),
                "title": item.get("title"),
                "url": item.get("url"),
                "repository": issue_match.group(1),
                "issue_number": int(issue_match.group(2)),
                "gross_usd": float(decimal(price.get("value")) / 100),
                "competitors_shown": len(participants),
                "bot_installed": bool((item.get("project") or {}).get("isBotInstalled")),
            }
        )
    return entries


def parse_tari_bounties(markdown: str, xtm_usd: Decimal) -> list[dict[str, Any]]:
    """Parse Tari's official markdown board and value rewards at a live XTM price."""
    entries: list[dict[str, Any]] = []
    row_pattern = re.compile(
        r"^\| \[#(?P<number>-?\d+) â€” (?P<title>.+?)\]"
        r"\(https://github\.com/(?P<repository>[^/]+/[^/]+)/(?:issues|pull)/\d+\)"
        r" \| [^|]+ \| (?P<tier>[SML]) \| (?P<xtm>[\d,]+) \| [^|]+"
        r" \| (?P<status>[^|]+) \| (?P<pulls>[^|]+) \|",
        flags=re.MULTILINE,
    )
    for match in row_pattern.finditer(markdown):
        number = abs(int(match.group("number")))
        repository = match.group("repository")
        pull_match = re.search(r"(\d+) PRs?", match.group("pulls"))
        xtm = decimal(match.group("xtm").replace(",", ""))
        status = re.sub(r"[^A-Za-z ]", "", match.group("status")).strip().lower()
        entries.append(
            {
                "id": f"{repository}#{number}",
                "repository": repository,
                "issue_number": number,
                "title": match.group("title"),
                "tier": match.group("tier"),
                "xtm": int(xtm),
                "gross_usd": float(xtm * xtm_usd),
                "status": status,
                "competitors": int(pull_match.group(1)) if pull_match else 0,
                "url": f"https://github.com/{repository}/issues/{number}",
            }
        )
    return entries


def tari_candidates(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Keep newly open Tari work; AI use and payment-on-merge are program rules."""
    candidates: list[dict[str, Any]] = []
    for entry in entries:
        if (
            entry.get("id") in EXCLUDED_TARI_IDS
            or entry.get("status") != "open"
            or decimal(entry.get("gross_usd")) < MIN_USD
            or int(entry.get("competitors") or 0) > MAX_COMPETITORS
        ):
            continue
        candidates.append(
            {
                "source": "Tari official bounty program",
                **entry,
                "funding_status": "official program; paid in XTM after merge",
                "ai_allowed": True,
                "needs_manual_scope_review": True,
            }
        )
    return candidates


def issuehunt_candidates(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Keep deposited, open, low-competition entries that resemble bounded work."""
    candidates = []
    seen: set[tuple[str, int]] = set()
    for entry in entries:
        key = (entry["repository"], entry["issue_number"])
        if key in seen:
            continue
        seen.add(key)
        issue_id = f"{entry['repository']}#{entry['issue_number']}"
        if (
            issue_id in EXCLUDED_ISSUEHUNT_IDS
            or entry.get("state") != "open"
            or decimal(entry.get("gross_usd")) < MIN_USD
            or int(entry.get("competitors") or 0) > MAX_COMPETITORS
            or not ISSUEHUNT_SMALL_TASK.search(entry.get("title") or "")
        ):
            continue
        candidates.append(
            {
                "source": "IssueHunt",
                "id": issue_id,
                "title": entry.get("title"),
                "gross_usd": float(decimal(entry.get("gross_usd"))),
                "competitors": int(entry.get("competitors") or 0),
                "url": entry.get("url"),
                "funding_url": entry.get("issuehunt_url"),
                "repository": entry.get("repository"),
                "funding_status": "Funded",
                "needs_manual_scope_review": True,
            }
        )
    return candidates


def algora_candidates(
    entries: list[dict[str, Any]],
    issue_lookup: Any,
    repo_lookup: Any,
    pulls_lookup: Any | None = None,
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    candidates: list[dict[str, Any]] = []
    stats = {
        "closed": 0,
        "archived": 0,
        "crowded": 0,
        "under_minimum": 0,
        "lookup_errors": 0,
        "live_open": 0,
    }
    for entry in aggregate_algora_bounties(entries):
        if decimal(entry.get("gross_usd")) < MIN_USD:
            stats["under_minimum"] += 1
            continue
        if int(entry.get("competitors") or 0) > MAX_COMPETITORS:
            stats["crowded"] += 1
            continue
        try:
            issue = issue_lookup(entry["repository"], entry["issue_number"])
        except (OSError, urllib.error.URLError, ValueError, json.JSONDecodeError):
            stats["lookup_errors"] += 1
            continue
        if issue.get("state") != "open" or issue.get("pull_request"):
            stats["closed"] += 1
            continue
        try:
            repository = repo_lookup(entry["repository"])
        except (OSError, urllib.error.URLError, ValueError, json.JSONDecodeError):
            stats["lookup_errors"] += 1
            continue
        if repository.get("archived") or repository.get("disabled"):
            stats["archived"] += 1
            continue
        competitors = int(entry.get("competitors") or 0)
        if pulls_lookup is not None:
            try:
                issue_ref = re.compile(rf"(?<!\d)#{entry['issue_number']}(?!\d)")
                linked_pulls = [
                    pull
                    for pull in pulls_lookup(entry["repository"])
                    if issue_ref.search(f"{pull.get('title') or ''}\n{pull.get('body') or ''}")
                ]
                competitors = max(competitors, len(linked_pulls))
            except (OSError, urllib.error.URLError, ValueError, json.JSONDecodeError):
                stats["lookup_errors"] += 1
                continue
        if competitors > MAX_COMPETITORS:
            stats["crowded"] += 1
            continue
        stats["live_open"] += 1
        candidates.append(
            {
                "source": "Algora",
                "id": f"{entry['repository']}#{entry['issue_number']}",
                "title": issue.get("title"),
                "gross_usd": float(decimal(entry.get("gross_usd"))),
                "competitors": competitors,
                "url": entry["url"],
                "repository": entry["repository"],
                "payment_window": "2-5 days after reward",
                "needs_manual_scope_review": True,
            }
        )
    return candidates, stats


CODEBOUNTY_QUERY = """
query {
  bounties(first: 100, orderBy: createdAt, orderDirection: desc) {
    id bountyId token amount owner repo issueId claimed contributor deadline
    createdAt createTransactionHash claimTransactionHash
  }
}
"""


def inspect_sources() -> dict[str, Any]:
    report: dict[str, Any] = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "minimum_usd": float(MIN_USD),
        "target_total_usd": float(TARGET_TOTAL_USD),
        "maximum_competitors": MAX_COMPETITORS,
        "sources": {},
        "preliminary_candidates": [],
    }

    def capture(name: str, operation: Any) -> Any:
        try:
            value = operation()
            report["sources"][name] = {"ok": True}
            return value
        except (OSError, urllib.error.URLError, ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
            report["sources"][name] = {"ok": False, "error": str(exc)}
            return None

    taskmarket = capture(
        "taskmarket",
        lambda: request_json("https://api.taskmarket.dev/api/tasks?status=open&phase=active"),
    )
    if taskmarket is not None:
        tasks = taskmarket.get("tasks", [])
        found = taskmarket_candidates(tasks)
        report["sources"]["taskmarket"].update({"active": len(tasks), "preliminary": len(found)})
        report["preliminary_candidates"].extend(found)

    moltjobs = capture("moltjobs", lambda: request_json("https://api.moltjobs.io/v1/jobs?status=OPEN"))
    if moltjobs is not None:
        jobs = moltjobs.get("data", [])
        found = moltjobs_candidates(jobs)
        report["sources"]["moltjobs"].update(
            {
                "open_status": len(jobs),
                "future_deadline": sum(1 for job in jobs if future_deadline(job.get("deadlineAt"))),
                "escrow_tx_present": sum(1 for job in jobs if job.get("escrowTxHash")),
                "preliminary": len(found),
            }
        )
        report["preliminary_candidates"].extend(found)

    moltjobs_stats = capture("moltjobs_stats", lambda: request_json("https://api.moltjobs.io/v1/stats"))
    if moltjobs_stats is not None:
        report["sources"]["moltjobs_stats"].update(moltjobs_stats.get("data", {}))

    execution_market = capture(
        "execution_market",
        lambda: request_json("https://api.execution.market/api/v1/tasks/available"),
    )
    if execution_market is not None:
        tasks = execution_market.get("tasks", [])
        found = execution_market_candidates(tasks)
        rewards = [decimal(task.get("bounty_usd")) for task in tasks]
        report["sources"]["execution_market"].update(
            {
                "available": len(tasks),
                "max_gross_usd": float(max(rewards, default=0)),
                "fee_percent": 13,
                "preliminary": len(found),
            }
        )
        report["preliminary_candidates"].extend(found)

    bountyhub = capture("bountyhub", lambda: request_json("https://api.bountyhub.dev/api/bounties"))
    if bountyhub is not None:
        bounties = bountyhub.get("data", [])
        found = bountyhub_candidates(bounties)
        report["sources"]["bountyhub"].update({"listed": len(bounties), "preliminary": len(found)})
        report["preliminary_candidates"].extend(found)

    taskbounty = capture("taskbounty", lambda: request_json("https://www.task-bounty.com/api/v1/tasks"))
    if taskbounty is not None:
        report["sources"]["taskbounty"].update({"active": len(taskbounty.get("data", []))})

    gitwork = capture("gitwork", lambda: request_json("https://gitwork.io/api/bounties/search"))
    if gitwork is not None:
        bounties = gitwork.get("bounties", [])
        found = gitwork_candidates(bounties)
        report["sources"]["gitwork"].update({"active": len(bounties), "preliminary": len(found)})
        report["preliminary_candidates"].extend(found)

    gitwork_stats = capture("gitwork_stats", lambda: request_json("https://gitwork.io/api/bounties/stats"))
    if gitwork_stats is not None:
        report["sources"]["gitwork_stats"].update(gitwork_stats.get("stats", {}))

    payanagent = capture("payanagent", lambda: request_json("https://payanagent.com/api/v1/requests"))
    if payanagent is not None:
        requests = payanagent.get("requests", payanagent) if isinstance(payanagent, dict) else payanagent
        open_requests = [item for item in requests if item.get("status") == "open"]
        escrowed = [item for item in open_requests if item.get("escrow") is True]
        found = payanagent_candidates(requests)
        report["sources"]["payanagent"].update(
            {
                "open": len(open_requests),
                "escrowed": len(escrowed),
                "max_escrowed_usd": float(max((decimal(item.get("budgetMaxCents")) for item in escrowed), default=0) / 100),
                "preliminary": len(found),
            }
        )
        report["preliminary_candidates"].extend(found)

    superteam_secret = os.path.join(
        os.environ.get("LOCALAPPDATA", ""), "Codex", "secrets", "superteam_earn_agent.json"
    )
    if os.path.isfile(superteam_secret):
        def fetch_superteam() -> Any:
            with open(superteam_secret, encoding="utf-8-sig") as handle:
                secret = json.load(handle)
            request = urllib.request.Request(
                "https://superteam.fun/api/agents/listings/live?take=100",
                headers={"Accept": "application/json", "Authorization": f"Bearer {secret['apiKey']}", "User-Agent": USER_AGENT},
            )
            with urllib.request.urlopen(request, timeout=25) as response:
                return json.load(response)

        superteam = capture("superteam", fetch_superteam)
        if superteam is not None:
            listings = superteam.get("listings", superteam.get("data", superteam)) if isinstance(superteam, dict) else superteam
            current = superteam_current_listings(listings)
            report["sources"]["superteam"].update({"listed": len(listings), "current": len(current)})
    else:
        report["sources"]["superteam"] = {"ok": False, "error": "local credential not configured"}

    def fetch_algora() -> dict[str, Any]:
        entries: list[dict[str, Any]] = []
        errors: dict[str, str] = {}
        for org in ALGORA_ORGS:
            try:
                entries.extend(parse_algora_bounties(request_text(f"https://algora.io/{org}/bounties?status=open")))
            except (OSError, urllib.error.URLError, ValueError, UnicodeDecodeError) as exc:
                errors[org] = str(exc)
        return {"entries": entries, "page_errors": errors}

    algora = capture("algora", fetch_algora)
    if algora is not None:
        entries = algora["entries"]
        found, stats = algora_candidates(
            entries,
            lambda repository, issue_number: request_json(
                f"https://api.github.com/repos/{repository}/issues/{issue_number}"
            ),
            lambda repository: request_json(f"https://api.github.com/repos/{repository}"),
            lambda repository: request_json(
                f"https://api.github.com/repos/{repository}/pulls?state=open&per_page=100"
            ),
        )
        report["sources"]["algora"].update(
            {
                "organizations": len(ALGORA_ORGS),
                "rows": len(entries),
                "unique_issues": len(aggregate_algora_bounties(entries)),
                "page_errors": algora["page_errors"],
                "preliminary": len(found),
                **stats,
            }
        )
        report["preliminary_candidates"].extend(found)

    def fetch_issuehunt() -> list[dict[str, Any]]:
        entries: list[dict[str, Any]] = []
        for page_number in range(1, ISSUEHUNT_MAX_PAGES + 1):
            entries.extend(parse_issuehunt_issues(request_text(f"https://oss.issuehunt.io/issues?page={page_number}")))
        return entries

    issuehunt = capture("issuehunt", fetch_issuehunt)
    if issuehunt is not None:
        found = issuehunt_candidates(issuehunt)
        report["sources"]["issuehunt"].update(
            {
                "pages": ISSUEHUNT_MAX_PAGES,
                "listed": len(issuehunt),
                "open": sum(1 for item in issuehunt if item.get("state") == "open"),
                "funded_open_low_competition": sum(
                    1
                    for item in issuehunt
                    if item.get("state") == "open"
                    and decimal(item.get("gross_usd")) >= MIN_USD
                    and int(item.get("competitors") or 0) <= MAX_COMPETITORS
                ),
                "small_task_preliminary": len(found),
            }
        )
        report["preliminary_candidates"].extend(found)

    def fetch_opire() -> list[dict[str, Any]]:
        entries: list[dict[str, Any]] = []
        for minimum, maximum in OPIRE_UNCLAIMED_BANDS:
            entries.extend(
                parse_opire_bounties(
                    request_text(
                        "https://app.opire.dev/home"
                        f"?usersTrying=NOBODY&minPrice={minimum}&maxPrice={maximum}"
                    )
                )
            )
        unique = {str(item["id"]): item for item in entries}
        return list(unique.values())

    opire = capture("opire", fetch_opire)
    if opire is not None:
        report["sources"]["opire"].update(
            {
                "listed_unclaimed_in_bands": len(opire),
                "amount_bands_usd": [list(band) for band in OPIRE_UNCLAIMED_BANDS],
                "preliminary": 0,
                "funding_status": "not_prefunded_or_escrowed",
                "reason_excluded": (
                    "Reward creators add payment details only after choosing a claim; "
                    "payment is discretionary and therefore not verified funding."
                ),
            }
        )

    def fetch_tari() -> dict[str, Any]:
        price = request_json("https://api.mexc.com/api/v3/ticker/price?symbol=XTMUSDT")
        xtm_usd = decimal(price["price"])
        board = request_text(
            "https://raw.githubusercontent.com/tari-project/bounties/main/README.md"
        )
        return {"xtm_usd": xtm_usd, "entries": parse_tari_bounties(board, xtm_usd)}

    tari = capture("tari", fetch_tari)
    if tari is not None:
        found = tari_candidates(tari["entries"])
        report["sources"]["tari"].update(
            {
                "xtm_usd": float(tari["xtm_usd"]),
                "listed": len(tari["entries"]),
                "open": sum(1 for item in tari["entries"] if item.get("status") == "open"),
                "pr_open": sum(1 for item in tari["entries"] if item.get("status") == "pr open"),
                "preliminary": len(found),
            }
        )
        report["preliminary_candidates"].extend(found)

    for network, url in {
        "codebounty_base": "https://api.studio.thegraph.com/query/31275/code-bounty-base/version/latest",
        "codebounty_mainnet": "https://api.studio.thegraph.com/query/31275/code-bounty-mainnet/version/latest",
    }.items():
        result = capture(network, lambda url=url: request_json(url, {"query": CODEBOUNTY_QUERY}))
        if result is not None:
            bounties = result.get("data", {}).get("bounties", [])
            open_count = sum(1 for bounty in bounties if not bounty.get("claimed"))
            report["sources"][network].update({"listed": len(bounties), "unclaimed": open_count})

    return report


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--compact", action="store_true", help="Emit compact JSON")
    parser.add_argument("--output", type=Path, help="Also save the UTF-8 JSON report to this path")
    args = parser.parse_args()
    report = inspect_sources()
    rendered = json.dumps(report, ensure_ascii=False, indent=None if args.compact else 2, sort_keys=True)
    if args.output:
        args.output.write_text(f"{rendered}\n", encoding="utf-8")
    print(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
