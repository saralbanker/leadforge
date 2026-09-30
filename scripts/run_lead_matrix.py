"""Lead-supply runner: drives the existing discovery pipeline across a target matrix.

This adds no scraping capability. It is a scheduler-friendly loop around
`python main.py <city> <category> --limit N`, which already works worldwide,
plus the existing WebsiteProvider email enrichment for whatever it finds.

Resumability comes from the `search_history` table the pipeline already writes:
a (city, category) pair completed within `recrawl_after_days` is skipped, so the
job can be killed and restarted, or run daily from cron, without redoing work.

Usage:
    python scripts/run_lead_matrix.py --pairs 4
    python scripts/run_lead_matrix.py --pairs 4 --dry-run
"""

import argparse
import asyncio
import random
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

import yaml

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))

DB = BASE / "leadforge.db"
TARGETS = BASE / "campaign_targets.yaml"


def load_targets() -> tuple[list[tuple[str, str]], dict]:
    """Expands the matrix into (city, category) pairs.

    Supports the current campaign_targets.yaml shape (priority_clusters /
    secondary_clusters, each a list of {area, city, categories: [{name, ...}]}),
    with fallback to the older markets/categories shape for backward compat.
    """
    cfg = yaml.safe_load(TARGETS.read_text())
    pairs: list[tuple[str, str]] = []

    if "priority_clusters" in cfg or "secondary_clusters" in cfg:
        clusters = list(cfg.get("priority_clusters", [])) + list(cfg.get("secondary_clusters", []))
        for cluster in clusters:
            city = cluster.get("city", cfg.get("defaults", {}).get("city", ""))
            for cat in cluster.get("categories", []):
                pairs.append((city, cat["name"]))
        return pairs, cfg.get("defaults", {})

    # Legacy shape: top-level markets[].cities[] x categories[].name
    cats = [c["name"] for c in cfg["categories"]]
    for market in sorted(cfg["markets"], key=lambda m: m.get("tier", 9)):
        for city in market["cities"]:
            for cat in cats:
                pairs.append((city, cat))
    return pairs, cfg["defaults"]


def completed_recently(con: sqlite3.Connection, days: int) -> set[tuple[str, str]]:
    rows = con.execute(
        """
        SELECT DISTINCT city, category FROM search_history
        WHERE status = 'COMPLETED'
          AND created_at >= datetime('now', ?)
        """,
        (f"-{days} days",),
    ).fetchall()
    return {(r[0].strip().lower(), r[1].strip().lower()) for r in rows}


def run_pair(city: str, category: str, limit: int) -> bool:
    """Runs the existing pipeline in a subprocess so a Playwright crash can't kill the loop."""
    print(f"  [discover] {city} / {category} (limit {limit}) ...", flush=True)
    try:
        proc = subprocess.run(
            [sys.executable, "main.py", city, category, "--limit", str(limit)],
            cwd=str(BASE), capture_output=True, text=True, timeout=1800,
        )
    except subprocess.TimeoutExpired:
        print("    TIMEOUT after 1800s", flush=True)
        return False
    if proc.returncode != 0:
        tail = (proc.stderr or proc.stdout or "").strip().splitlines()[-3:]
        print(f"    FAILED rc={proc.returncode}: {' | '.join(tail)}", flush=True)
        return False
    for line in (proc.stdout or "").splitlines():
        if "Qualified Count:" in line or "New Leads:" in line:
            print(f"    {line.strip()}", flush=True)
    return True


async def enrich_new_leads(limit: int = 60) -> tuple[int, int]:
    """Runs email discovery over website-having businesses that still lack an address.

    Only WebsiteProvider is used. IndiaMart/Justdial/TradeIndia are proven dead
    (HTTP 200, client-rendered shells, zero results) and cost ~8s of timeout each.
    """
    from leadforge.enrichment.orchestrator import EmailEnrichmentOrchestrator
    from leadforge.enrichment.website import WebsiteProvider

    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    rows = con.execute(
        """
        SELECT id, name, website_domain, display_phone FROM businesses
        WHERE website_domain IS NOT NULL AND website_domain != ''
          AND (contact_email IS NULL OR contact_email = '')
          AND is_suppressed = 0 AND deleted_at IS NULL
        ORDER BY first_discovered_at DESC LIMIT ?
        """,
        (limit,),
    ).fetchall()
    con.close()
    if not rows:
        return 0, 0

    orch = EmailEnrichmentOrchestrator(providers=[WebsiteProvider()])
    found = 0
    for r in rows:
        prof = {
            "business_id": r["id"], "name": r["name"],
            "website_domain": r["website_domain"], "phone": r["display_phone"],
        }
        try:
            top, _ = await orch.enrich_business(prof, global_timeout=20.0)
            if top and getattr(top, "email", None):
                found += 1
        except Exception as exc:  # one bad site must not end the batch
            print(f"    enrich error {r['name'][:30]}: {type(exc).__name__}", flush=True)
    return found, len(rows)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--pairs", type=int, default=4, help="city/category pairs this run")
    ap.add_argument("--limit", type=int, default=None, help="override businesses per pair")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    pairs, defaults = load_targets()
    limit = args.limit or defaults.get("limit_per_pair") or defaults.get("limit_per_run", 30)

    con = sqlite3.connect(DB)
    done = completed_recently(con, defaults["recrawl_after_days"])
    con.close()

    todo = [p for p in pairs if (p[0].lower(), p[1].lower()) not in done]
    print(f"Matrix: {len(pairs)} pairs | {len(done)} done recently | {len(todo)} remaining")
    if not todo:
        print("Nothing to do - whole matrix crawled within the recrawl window.")
        return

    # Spread across cities rather than exhausting one market first: a single
    # city's businesses share too much context for varied copy, and Maps
    # rate-limits a hammered geography faster than a scattered one.
    random.shuffle(todo)
    batch = todo[: args.pairs]

    if args.dry_run:
        for c, k in batch:
            print(f"  would run: {c} / {k} (limit {limit})")
        return

    t0 = time.time()
    ok = 0
    for city, category in batch:
        if run_pair(city, category, limit):
            ok += 1

    print("\n[enrich] discovering emails for newly found websites ...", flush=True)
    found, checked = asyncio.run(enrich_new_leads())
    pct = (found / checked * 100) if checked else 0.0
    print(f"\nDone in {time.time()-t0:.0f}s | pairs ok {ok}/{len(batch)} "
          f"| emails {found}/{checked} ({pct:.0f}%)")


if __name__ == "__main__":
    main()
