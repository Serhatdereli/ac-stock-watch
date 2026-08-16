#!/usr/bin/env python3
"""
Browser add-on for the portable AC stock watcher.
==================================================

Some retailers build their search results in the browser and refuse plain
HTTP requests, so they need a real Chrome to read. This script drives your
installed Chrome through Playwright, with the window parked off-screen so
it never interrupts you.

WHAT WORKS, AND WHAT DOESN'T -- tested 16 Aug 2026
--------------------------------------------------
  John Lewis  WORKS. Needs a visible (non-headless) Chrome; headless is
              refused at the HTTP/2 layer. Publishes proper schema.org
              availability on product pages.

  Argos       BLOCKED. Akamai returns "Access Denied" to plain requests,
              to TLS-impersonated requests, to headless Chrome and to
              automated visible Chrome -- from a home broadband line as
              well as from the cloud. Product pages are blocked too, not
              just search. Only an ordinary hand-driven Chrome gets in.

  Currys      BLOCKED. Cloudflare returns "Attention Required" to
              automated Chrome, headless or not.

Argos and Currys are left in as disabled entries rather than deleted, so
the reasoning survives. If their protection ever loosens, flip them on.

Usage
-----
    python3 browser_check.py                # check and notify
    python3 browser_check.py --dry-run      # check and print, notify nothing
    python3 browser_check.py --verbose      # show every product considered
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

# Reuse the filtering, offer parsing and notification code from the main script.
from check_stock import (  # noqa: E402
    Candidate, StockResult, Finding, RetailerReport,
    looks_like_ac_unit, read_offers, ntfy_push, money, log,
)

STATE_PATH = os.path.join(HERE, "state-browser.json")
PROFILE_DIR = os.path.join(HERE, ".browser-profile")

# Parked far off-screen so the window never appears over your work.
CHROME_ARGS = [
    "--window-position=-3000,-3000",
    "--disable-blink-features=AutomationControlled",
]

RETAILERS = {
    "johnlewis": {
        "label": "John Lewis",
        "enabled": True,
        "search": "https://www.johnlewis.com/search?search-term={term}",
    },
    "argos": {
        "label": "Argos",
        "enabled": False,
        "reason": "Akamai blocks automated Chrome, headless or otherwise",
        "search": "https://www.argos.co.uk/search/{slug}/",
    },
    "currys": {
        "label": "Currys",
        "enabled": False,
        "reason": "Cloudflare blocks automated Chrome, headless or otherwise",
        "search": "https://www.currys.co.uk/search?q={term}",
    },
}

# Pulls product links, names and prices out of a rendered search page.
EXTRACT_JS = r"""() => {
  const ld = [...document.querySelectorAll('script[type="application/ld+json"]')]
      .map(s => { try { return JSON.parse(s.textContent); } catch (e) { return null; } })
      .filter(Boolean);
  const list = ld.find(d => d['@type'] === 'ItemList');
  const urls = list ? list.itemListElement.map(i => i.url).filter(Boolean) : [];

  const byUrl = {};
  for (const card of document.querySelectorAll('a[href]')) {
    const href = card.getAttribute('href') || '';
    const abs = href.startsWith('http') ? href : location.origin + href;
    const box = card.closest('article, li, div');
    const text = ((box && box.innerText) || card.innerText || '').replace(/\s+/g, ' ').trim();
    if (!text || text.length > 400) continue;
    const price = (text.match(/£\s?([\d,]+\.\d{2})/) || [])[1];
    if (!byUrl[abs] || (price && !byUrl[abs].price)) {
      byUrl[abs] = {
        url: abs,
        name: (card.getAttribute('aria-label') || card.innerText || '').replace(/\s+/g, ' ').trim().slice(0, 140),
        price: price ? parseFloat(price.replace(/,/g, '')) : null,
        text: text.slice(0, 200)
      };
    }
  }
  return urls.map(u => byUrl[u] || { url: u, name: '', price: null, text: '' });
}"""

# Reads schema.org offers from a rendered product page.
OFFERS_JS = r"""() => {
  const out = [];
  for (const s of document.querySelectorAll('script[type="application/ld+json"]')) {
    out.push(s.textContent);
  }
  return { blocks: out, name: document.title };
}"""


def load_state() -> dict:
    try:
        with open(STATE_PATH, encoding="utf-8") as f:
            return json.load(f)
    except Exception:  # noqa: BLE001
        return {"initialised": False, "items": {}, "last_run": ""}


def save_state(state: dict) -> None:
    with open(STATE_PATH, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2, sort_keys=True)
        f.write("\n")


def slug_name(url: str) -> str:
    """Turn a product URL into a readable name.

    Search cards often expose finance blurb ("Pay no interest from...") rather
    than the product title, so the URL slug is the more reliable source.
    """
    parts = [p for p in url.split("?")[0].rstrip("/").split("/") if p]
    for part in reversed(parts):
        # Skip trailing id segments like "p115439147" or bare numbers.
        if re.fullmatch(r"p?\d{5,}", part):
            continue
        if "-" in part:
            return part.replace("-", " ").strip().title()
    return parts[-1] if parts else url


def collect_candidates(page, key: str, spec: dict, terms: list[str],
                       rules: dict, verbose: bool) -> list[Candidate]:
    """Run each search term through the rendered page and keep real AC units."""
    seen: dict[str, Candidate] = {}
    for term in terms:
        url = spec["search"].format(
            term=term.replace(" ", "+"),
            slug=term.replace(" ", "-"),
        )
        page.goto(url, wait_until="domcontentloaded", timeout=45000)
        page.wait_for_timeout(6000)
        for row in page.evaluate(EXTRACT_JS):
            if not row.get("url"):
                continue
            # The URL slug is a far more reliable source of the product name
            # than the card text, which is usually finance small print.
            name = slug_name(row["url"])
            c = Candidate(key, name, row["url"], row["url"].rsplit("/", 1)[-1], row.get("price"))
            seen.setdefault(c.key, c)

    kept = []
    for c in seen.values():
        ok, why = looks_like_ac_unit(c.name, c.price, rules)
        if verbose:
            log(f"   [{'KEEP' if ok else 'drop'}] {spec['label']}: {c.name[:60]} -- {why}")
        if ok:
            kept.append(c)
    return kept


def read_stock(page, cand: Candidate) -> StockResult:
    """Open the product page and read its published availability."""
    page.goto(cand.url, wait_until="domcontentloaded", timeout=45000)
    page.wait_for_timeout(4000)
    data = page.evaluate(OFFERS_JS)
    html = "".join(
        f'<script type="application/ld+json">{b}</script>' for b in data["blocks"]
    )
    st = read_offers(html)
    # John Lewis publishes a single availability figure covering both routes;
    # it offers Click & Collect on anything it can sell.
    if st.collect is None and st.delivery is not None:
        st.collect = st.delivery
        st.note = "single national availability figure; collect assumed to follow"
    return st


def main() -> int:
    ap = argparse.ArgumentParser(description="Browser add-on for the AC stock watcher")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--verbose", action="store_true")
    ap.add_argument("--reset", action="store_true")
    args = ap.parse_args()

    if args.reset and os.path.exists(STATE_PATH):
        os.remove(STATE_PATH)
        log("Browser state cleared.")

    with open(os.path.join(HERE, "config.json"), encoding="utf-8") as f:
        cfg = json.load(f)
    rules = dict(cfg.get("matching", {}))
    terms = cfg.get("search_terms", ["portable air conditioner"])

    # John Lewis already narrows the results to its Air Conditioners category,
    # so the BTU-in-the-title rule is unnecessary here and would wrongly drop
    # genuine units named without one (e.g. "Meaco 7000R PRO").
    rules["require_btu_rating"] = False

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        log("!! Playwright is not installed. Run: ./.venv/bin/pip install playwright")
        return 1

    reports: list[RetailerReport] = []

    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(
            PROFILE_DIR, channel="chrome", headless=False,
            viewport={"width": 1440, "height": 1000},
            locale="en-GB", timezone_id="Europe/London",
            args=CHROME_ARGS,
        )
        page = ctx.pages[0] if ctx.pages else ctx.new_page()

        for key, spec in RETAILERS.items():
            rep = RetailerReport(name=spec["label"])
            if not spec.get("enabled"):
                rep.ok, rep.reason = False, spec.get("reason", "disabled")
                reports.append(rep)
                log(f"-- {spec['label']}: skipped ({rep.reason})")
                continue
            try:
                kept = collect_candidates(page, key, spec, terms, rules, args.verbose)
                log(f"-- {spec['label']}: {len(kept)} genuine AC units to check")
                for c in kept[: int(cfg.get("settings", {}).get("max_products_per_retailer", 12))]:
                    try:
                        st = read_stock(page, c)
                    except Exception as e:  # noqa: BLE001
                        st = StockResult(note=f"could not read ({type(e).__name__})")
                    rep.findings.append(Finding(c, st))
                    if args.verbose:
                        log(f"     {c.name[:46]:48} collect={st.collect} delivery={st.delivery}")
            except Exception as e:  # noqa: BLE001
                rep.ok, rep.reason = False, f"{type(e).__name__}: {str(e)[:70]}"
                log(f"!! {spec['label']}: {rep.reason}")
            reports.append(rep)

        ctx.close()

    return finalise(cfg, reports, args)


def finalise(cfg: dict, reports: list[RetailerReport], args) -> int:
    """Compare against last run, alert on anything newly available, save state."""
    settings = cfg.get("settings", {})
    alert_on = settings.get("alert_on", "collect")
    label = {"collect": "click & collect", "delivery": "delivery",
             "any": "collect or delivery"}.get(alert_on, alert_on)

    def is_hit(st: StockResult) -> bool:
        if alert_on == "collect":
            return st.collect is True
        if alert_on == "delivery":
            return st.delivery is True
        return st.collect is True or st.delivery is True

    state = load_state()
    prev = state.get("items", {})
    now_items, newly = {}, []

    for rep in reports:
        for f in rep.findings:
            hit = is_hit(f.stock)
            now_items[f.candidate.key] = {
                "name": f.candidate.name, "price": f.candidate.price,
                "url": f.candidate.url, "retailer": rep.name, "in_stock": hit,
            }
            if hit and not prev.get(f.candidate.key, {}).get("in_stock", False):
                newly.append(f)

    # A retailer that failed this run keeps its old entries, so a temporary
    # outage never causes a re-alert storm when it recovers.
    for rep in reports:
        if not rep.ok:
            for k, v in prev.items():
                if v.get("retailer") == rep.name:
                    now_items.setdefault(k, v)

    live = [(k, v) for k, v in now_items.items() if v["in_stock"]]
    log(f"== {len(now_items)} units tracked, {len(live)} available, {len(newly)} newly available")

    if args.dry_run:
        log("(dry run -- nothing sent)")
        for _, v in live:
            log(f"   IN STOCK: {v['retailer']} -- {v['name'][:60]} {money(v['price'])}")
    elif not state.get("initialised"):
        if live:
            body = "\n".join(f"- {v['retailer']}: {v['name'][:60]} ({money(v['price'])})"
                             for _, v in live[:10])
            ntfy_push(cfg, "Browser watch is live - units already available",
                      f"Also watching {len(now_items)} units at John Lewis.\n"
                      f"Available for {label} now:\n\n{body}",
                      tags="white_check_mark,snowflake", click=live[0][1]["url"])
        else:
            ntfy_push(cfg, "Browser watch is live",
                      f"Also watching {len(now_items)} units at John Lewis. "
                      f"None available for {label} right now.", tags="eyes")
        log("Baseline sent; future runs alert on changes only.")
    else:
        for f in newly[: int(settings.get("max_alerts_per_run", 5))]:
            ntfy_push(cfg, f"In stock: {f.candidate.name[:60]}",
                      f"John Lewis - {money(f.candidate.price)}\n"
                      f"Available for {label}.\n\n"
                      "Note: John Lewis publishes national availability, so check "
                      "your nearest branch before travelling.",
                      click=f.candidate.url, tags="snowflake,shopping_cart", priority="high")
            log(f">> ALERTED: John Lewis -- {f.candidate.name[:60]}")
            time.sleep(1)

    if not args.dry_run:
        state.update({"items": now_items, "initialised": True,
                      "last_run": datetime.now(timezone.utc).isoformat(timespec="seconds")})
        save_state(state)
        log("Browser state saved.")

    for rep in reports:
        if not rep.ok:
            log(f"   unavailable: {rep.name} ({rep.reason})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
