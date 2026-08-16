#!/usr/bin/env python3
"""
Portable Air Conditioner stock watcher  --  Bromley BR1 3RU
============================================================

Checks UK retailers for portable air conditioning units that are available
for click & collect, and pushes a notification to your iPhone and laptop
via ntfy.sh when something new comes into stock.

Standard library only -- no pip install required.

Usage
-----
    python3 check_stock.py                 # normal run
    python3 check_stock.py --dry-run       # check stock, print, send nothing
    python3 check_stock.py --test-notify   # send one test push and exit
    python3 check_stock.py --verbose       # show every product considered
    python3 check_stock.py --reset         # clear saved state (re-baseline)

Configuration lives in config.json next to this file.
The ntfy topic comes from the NTFY_TOPIC environment variable
(falling back to config.json -> ntfy.topic).
"""

from __future__ import annotations

import argparse
import gzip
import json
import os
import random
import re
import ssl
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Iterable

HERE = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(HERE, "config.json")
STATE_PATH = os.environ.get("AC_STATE_FILE") or os.path.join(HERE, "state.json")

BROWSER_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)

BASE_HEADERS = {
    "User-Agent": BROWSER_UA,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-GB,en;q=0.9",
    "Accept-Encoding": "gzip",
    "Upgrade-Insecure-Requests": "1",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
    "Connection": "close",
}


# --------------------------------------------------------------------------
# Small helpers
# --------------------------------------------------------------------------

def log(msg: str) -> None:
    stamp = datetime.now(timezone.utc).strftime("%H:%M:%S")
    print(f"[{stamp}] {msg}", flush=True)


class Blocked(Exception):
    """Retailer refused the request (bot protection / datacentre IP block)."""


class FetchFailed(Exception):
    """Network or server error we could not recover from."""


def fetch(url: str, timeout: int = 25, retries: int = 2) -> str:
    """GET a URL and return decoded text. Raises Blocked / FetchFailed."""
    ctx = ssl.create_default_context()
    last_err: Exception | None = None

    for attempt in range(retries + 1):
        req = urllib.request.Request(url, headers=BASE_HEADERS)
        try:
            with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
                raw = resp.read()
                if resp.headers.get("Content-Encoding") == "gzip":
                    raw = gzip.decompress(raw)
                return raw.decode("utf-8", errors="ignore")
        except urllib.error.HTTPError as e:
            if e.code in (401, 403, 405, 406, 429):
                raise Blocked(f"HTTP {e.code}") from e
            last_err = e
        except Exception as e:  # noqa: BLE001 - network layer is genuinely varied
            last_err = e

        if attempt < retries:
            time.sleep(1.5 * (attempt + 1) + random.random())

    raise FetchFailed(str(last_err))


def json_ld_blocks(html: str) -> Iterable[dict]:
    """Yield every parsed application/ld+json object found in the page."""
    pattern = re.compile(
        r'<script[^>]*type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
        re.S | re.I,
    )
    for m in pattern.finditer(html):
        text = m.group(1).strip()
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            continue
        if isinstance(data, list):
            for d in data:
                if isinstance(d, dict):
                    yield d
        elif isinstance(data, dict):
            yield data


def unescape(text: str) -> str:
    return (
        text.replace("&amp;", "&")
        .replace("&quot;", '"')
        .replace("&#39;", "'")
        .replace("&lt;", "<")
        .replace("&gt;", ">")
        .replace("&nbsp;", " ")
    ).strip()


# --------------------------------------------------------------------------
# Data shapes
# --------------------------------------------------------------------------

@dataclass
class Candidate:
    retailer: str
    name: str
    url: str
    sku: str = ""
    price: float | None = None

    @property
    def key(self) -> str:
        return f"{self.retailer}:{self.sku or self.url}"


@dataclass
class StockResult:
    collect: bool | None = None   # available for click & collect / in store
    delivery: bool | None = None  # available for home delivery
    note: str = ""


@dataclass
class Finding:
    candidate: Candidate
    stock: StockResult


@dataclass
class RetailerReport:
    name: str
    ok: bool = True
    reason: str = ""
    findings: list[Finding] = field(default_factory=list)


# --------------------------------------------------------------------------
# Product filtering  --  keeps real AC units, drops fans / covers / hoses
# --------------------------------------------------------------------------

# Matches "9000BTU", "12,000 BTU" and the shorthand "12KBTU".
BTU_RE = re.compile(r"\b(?:\d{1,2}[,.]?\d{3}|\d{1,2}\s*k)\s*btu\b", re.I)


def looks_like_ac_unit(name: str, price: float | None, rules: dict) -> tuple[bool, str]:
    """Return (keep?, reason). Search pages are full of fans and accessories."""
    n = unescape(name).lower()

    for bad in rules.get("exclude_keywords", []):
        if bad.lower() in n:
            return False, f"excluded on '{bad}'"

    if not any(k.lower() in n for k in rules.get("require_any_keyword", [])):
        return False, "no air-conditioning keyword"

    has_btu = bool(BTU_RE.search(n))
    if rules.get("require_btu_rating", True) and not has_btu:
        return False, "no BTU rating in title"

    floor = rules.get("min_price")
    if floor is not None and price is not None and price < floor:
        return False, f"price £{price:.2f} below £{floor:.2f} floor"

    ceiling = rules.get("max_price")
    if ceiling is not None and price is not None and price > ceiling:
        return False, f"price £{price:.2f} above £{ceiling:.2f} cap"

    return True, "match"


# --------------------------------------------------------------------------
# Generic schema.org offer reader  --  works for B&Q, Screwfix and others
# --------------------------------------------------------------------------

def read_offers(html: str) -> StockResult:
    """
    Read schema.org Product offers and work out whether the item can be
    collected in store and/or delivered.

    Retailers publish one Offer per fulfilment route, e.g.
        OnSitePickup  + InStock     -> collect available
        ParcelService + OutOfStock  -> delivery unavailable
    """
    collect: bool | None = None
    delivery: bool | None = None
    seen_any = False

    for block in json_ld_blocks(html):
        if block.get("@type") not in ("Product", "IndividualProduct"):
            continue
        offers = block.get("offers")
        if not offers:
            continue
        if isinstance(offers, dict):
            offers = [offers]

        for offer in offers:
            if not isinstance(offer, dict):
                continue
            availability = str(offer.get("availability", "")).lower()
            if not availability:
                continue
            seen_any = True

            in_stock = "instock" in availability or "limitedavailability" in availability
            method = str(offer.get("availableDeliveryMethod", "")).lower()
            desc = str(offer.get("description", "")).lower()

            is_pickup = "onsitepickup" in method or "collect" in desc or "in-store" in desc
            is_delivery = "parcelservice" in method or "delivery" in desc or "mail" in method

            if is_pickup:
                collect = True if in_stock else (collect or False)
            elif is_delivery:
                delivery = True if in_stock else (delivery or False)
            else:
                # No fulfilment hint at all -- treat as general availability.
                if delivery is None or in_stock:
                    delivery = in_stock

    if not seen_any:
        return StockResult(note="no availability data published")
    return StockResult(collect=collect, delivery=delivery)


def read_item_list(html: str, base: str = "") -> list[tuple[str, str, str, float | None]]:
    """Read a schema.org ItemList of products from a search results page."""
    out: list[tuple[str, str, str, float | None]] = []
    for block in json_ld_blocks(html):
        if block.get("@type") != "ItemList":
            continue
        for item in block.get("itemListElement", []):
            if not isinstance(item, dict) or item.get("@type") != "Product":
                continue
            url = item.get("url") or ""
            if url.startswith("/"):
                url = base.rstrip("/") + url
            price = None
            offers = item.get("offers")
            if isinstance(offers, dict):
                try:
                    price = float(offers.get("price"))
                except (TypeError, ValueError):
                    price = None
            out.append((unescape(item.get("name", "")), url, str(item.get("sku", "")), price))
    return out


# --------------------------------------------------------------------------
# Retailer adapters
# --------------------------------------------------------------------------

class Retailer:
    key = ""
    label = ""
    base = ""
    # Retailers behind aggressive bot protection only work from a home
    # broadband connection, not from a datacentre such as GitHub Actions.
    home_ip_only = False

    def search(self, term: str) -> list[Candidate]:
        raise NotImplementedError

    def stock(self, cand: Candidate) -> StockResult:
        return read_offers(fetch(cand.url))

    def collect_link(self, cand: Candidate) -> str:
        return cand.url


class BQ(Retailer):
    key, label, base = "bq", "B&Q", "https://www.diy.com"

    def search(self, term: str) -> list[Candidate]:
        url = f"{self.base}/search?term={urllib.parse.quote_plus(term)}"
        html = fetch(url)
        return [
            Candidate(self.key, n, u, s, p)
            for (n, u, s, p) in read_item_list(html, self.base)
        ]


class Screwfix(Retailer):
    key, label, base = "screwfix", "Screwfix", "https://www.screwfix.com"

    def search(self, term: str) -> list[Candidate]:
        url = f"{self.base}/search?search={urllib.parse.quote_plus(term)}"
        html = fetch(url)
        return [
            Candidate(self.key, n, u, s, p)
            for (n, u, s, p) in read_item_list(html, self.base)
        ]

    def collect_link(self, cand: Candidate) -> str:
        # Screwfix has a dedicated branch stock finder keyed on the SKU.
        if cand.sku:
            return f"{self.base}/checkstock?product_id={urllib.parse.quote(cand.sku)}"
        return cand.url


class Toolstation(Retailer):
    key, label, base = "toolstation", "Toolstation", "https://www.toolstation.com"

    def search(self, term: str) -> list[Candidate]:
        url = f"{self.base}/search?q={urllib.parse.quote_plus(term)}"
        html = fetch(url)
        found = read_item_list(html, self.base)
        if found:
            return [Candidate(self.key, n, u, s, p) for (n, u, s, p) in found]
        # Toolstation renders client-side; fall back to product links in markup.
        cands: dict[str, Candidate] = {}
        for m in re.finditer(r'href="(/p/[a-z0-9\-]+/[a-z0-9]+)"[^>]*>([^<]{6,120})<', html, re.I):
            path, name = m.group(1), unescape(m.group(2))
            cands[path] = Candidate(self.key, name, self.base + path, path.rsplit("/", 1)[-1])
        return list(cands.values())


class Argos(Retailer):
    key, label, base = "argos", "Argos", "https://www.argos.co.uk"
    home_ip_only = True

    def search(self, term: str) -> list[Candidate]:
        url = f"{self.base}/search/{urllib.parse.quote(term.replace(' ', '-'))}/"
        html = fetch(url)
        found = read_item_list(html, self.base)
        return [Candidate(self.key, n, u, s, p) for (n, u, s, p) in found]


class Currys(Retailer):
    key, label, base = "currys", "Currys", "https://www.currys.co.uk"
    home_ip_only = True

    def search(self, term: str) -> list[Candidate]:
        url = f"{self.base}/search?q={urllib.parse.quote_plus(term)}"
        html = fetch(url)
        found = read_item_list(html, self.base)
        return [Candidate(self.key, n, u, s, p) for (n, u, s, p) in found]


class JohnLewis(Retailer):
    key, label, base = "johnlewis", "John Lewis", "https://www.johnlewis.com"
    home_ip_only = True

    def search(self, term: str) -> list[Candidate]:
        url = f"{self.base}/search?search-term={urllib.parse.quote_plus(term)}"
        html = fetch(url)
        found = read_item_list(html, self.base)
        return [Candidate(self.key, n, u, s, p) for (n, u, s, p) in found]


ALL_RETAILERS: dict[str, Retailer] = {
    r.key: r for r in (BQ(), Screwfix(), Toolstation(), Argos(), Currys(), JohnLewis())
}


# --------------------------------------------------------------------------
# Notifications (ntfy.sh)
# --------------------------------------------------------------------------

def ntfy_push(cfg: dict, title: str, message: str, *, click: str = "",
              tags: str = "snowflake", priority: str = "default") -> bool:
    topic = os.environ.get("NTFY_TOPIC") or cfg.get("ntfy", {}).get("topic", "")
    if not topic:
        log("!! No ntfy topic configured -- set the NTFY_TOPIC environment variable.")
        return False

    server = (os.environ.get("NTFY_SERVER")
              or cfg.get("ntfy", {}).get("server", "https://ntfy.sh")).rstrip("/")
    url = f"{server}/{urllib.parse.quote(topic)}"

    headers = {
        "User-Agent": "ac-stock-watch/1.0",
        "Content-Type": "text/plain; charset=utf-8",
        "Title": title.encode("ascii", "ignore").decode() or "Stock alert",
        "Tags": tags,
        "Priority": priority,
    }
    if click:
        headers["Click"] = click
    token = os.environ.get("NTFY_TOKEN") or cfg.get("ntfy", {}).get("token", "")
    if token:
        headers["Authorization"] = f"Bearer {token}"

    req = urllib.request.Request(url, data=message.encode("utf-8"),
                                 headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            return 200 <= resp.status < 300
    except Exception as e:  # noqa: BLE001
        log(f"!! ntfy push failed: {e}")
        return False


# --------------------------------------------------------------------------
# State
# --------------------------------------------------------------------------

def load_state() -> dict:
    if not os.path.exists(STATE_PATH):
        return {"initialised": False, "items": {}, "last_run": "", "last_commit_day": ""}
    try:
        with open(STATE_PATH, encoding="utf-8") as f:
            return json.load(f)
    except Exception:  # noqa: BLE001
        return {"initialised": False, "items": {}, "last_run": "", "last_commit_day": ""}


def save_state(state: dict) -> None:
    with open(STATE_PATH, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2, sort_keys=True)
        f.write("\n")


# --------------------------------------------------------------------------
# Main run
# --------------------------------------------------------------------------

def money(p: float | None) -> str:
    return f"£{p:,.2f}" if isinstance(p, (int, float)) else "price n/a"


def run(cfg: dict, args: argparse.Namespace) -> int:
    rules = cfg.get("matching", {})
    settings = cfg.get("settings", {})
    delay = float(settings.get("polite_delay_seconds", 1.5))
    max_products = int(settings.get("max_products_per_retailer", 12))
    alert_on = settings.get("alert_on", "collect")  # collect | delivery | any

    enabled = [k for k in cfg.get("retailers", []) if k in ALL_RETAILERS]
    if args.only:
        enabled = [k for k in enabled if k in args.only.split(",")]

    running_locally = os.environ.get("GITHUB_ACTIONS") != "true"
    reports: list[RetailerReport] = []

    for key in enabled:
        r = ALL_RETAILERS[key]
        rep = RetailerReport(name=r.label)

        if r.home_ip_only and not running_locally and not settings.get("try_blocked_retailers_in_cloud", False):
            rep.ok = False
            rep.reason = "skipped in cloud (needs a home broadband connection)"
            reports.append(rep)
            log(f"-- {r.label}: {rep.reason}")
            continue

        seen: dict[str, Candidate] = {}
        try:
            for term in cfg.get("search_terms", ["portable air conditioner"]):
                for c in r.search(term):
                    if c.url and c.key not in seen:
                        seen[c.key] = c
                time.sleep(delay)
        except Blocked as e:
            rep.ok, rep.reason = False, f"blocked by bot protection ({e})"
            reports.append(rep)
            log(f"!! {r.label}: {rep.reason}")
            continue
        except FetchFailed as e:
            rep.ok, rep.reason = False, f"unreachable ({e})"
            reports.append(rep)
            log(f"!! {r.label}: {rep.reason}")
            continue

        kept: list[Candidate] = []
        for c in seen.values():
            ok, why = looks_like_ac_unit(c.name, c.price, rules)
            if args.verbose:
                mark = "KEEP" if ok else "drop"
                log(f"   [{mark}] {r.label}: {c.name[:64]} -- {why}")
            if ok:
                kept.append(c)

        kept.sort(key=lambda c: (c.price is None, c.price or 0))
        kept = kept[:max_products]
        log(f"-- {r.label}: {len(seen)} results, {len(kept)} genuine AC units to check")

        for c in kept:
            try:
                st = r.stock(c)
            except Blocked as e:
                st = StockResult(note=f"blocked ({e})")
            except FetchFailed as e:
                st = StockResult(note=f"unreachable ({e})")
            rep.findings.append(Finding(c, st))
            if args.verbose:
                log(f"     {c.name[:50]:52} collect={st.collect} delivery={st.delivery} {st.note}")
            time.sleep(delay)

        reports.append(rep)

    # ---- decide what counts as "in stock" -------------------------------
    def is_hit(st: StockResult) -> bool:
        if alert_on == "collect":
            return st.collect is True
        if alert_on == "delivery":
            return st.delivery is True
        return st.collect is True or st.delivery is True

    state = load_state()
    prev: dict = state.get("items", {})
    now_items: dict = {}
    newly_in_stock: list[Finding] = []

    for rep in reports:
        for f in rep.findings:
            hit = is_hit(f.stock)
            now_items[f.candidate.key] = {
                "name": f.candidate.name,
                "price": f.candidate.price,
                "url": f.candidate.url,
                "retailer": rep.name,
                "in_stock": hit,
            }
            was = prev.get(f.candidate.key, {}).get("in_stock", False)
            if hit and not was:
                newly_in_stock.append(f)

    # Retailers that failed keep their previous state rather than being
    # forgotten -- otherwise a temporary outage would re-alert everything.
    for rep in reports:
        if not rep.ok:
            for k, v in prev.items():
                if v.get("retailer") == rep.name:
                    now_items.setdefault(k, v)

    in_stock_now = [(k, v) for k, v in now_items.items() if v["in_stock"]]
    log(f"== {len(now_items)} units tracked, {len(in_stock_now)} currently available, "
        f"{len(newly_in_stock)} newly available")

    # ---- notify ---------------------------------------------------------
    label = {"collect": "click & collect", "delivery": "delivery",
             "any": "collect or delivery"}.get(alert_on, alert_on)

    if args.dry_run:
        log("(dry run -- no notifications sent)")
        for k, v in in_stock_now:
            log(f"   IN STOCK: {v['retailer']} -- {v['name']} {money(v['price'])}")
    elif not state.get("initialised"):
        # First ever run: send one baseline message, then stay quiet.
        if in_stock_now:
            body = "\n".join(
                f"- {v['retailer']}: {v['name']} ({money(v['price'])})"
                for _, v in in_stock_now[:10]
            )
            ntfy_push(cfg, "AC watch is live - some units already in stock",
                      f"Watching {len(now_items)} portable AC units near BR1 3RU.\n"
                      f"Available for {label} right now:\n\n{body}\n\n"
                      "You'll only be alerted from now on when something NEW comes in.",
                      tags="white_check_mark,snowflake",
                      click=in_stock_now[0][1]["url"])
        else:
            ntfy_push(cfg, "AC watch is live",
                      f"Watching {len(now_items)} portable AC units near BR1 3RU. "
                      f"Nothing available for {label} right now - "
                      "I'll ping you the moment that changes.",
                      tags="eyes")
        log("Baseline notification sent; future runs alert on changes only.")
    else:
        cap = int(settings.get("max_alerts_per_run", 5))
        for f in newly_in_stock[:cap]:
            r = ALL_RETAILERS[f.candidate.retailer]
            extra = "" if f.stock.delivery is not True else "  (delivery also available)"
            ntfy_push(
                cfg,
                f"In stock: {f.candidate.name[:60]}",
                f"{r.label} - {money(f.candidate.price)}\n"
                f"Available for {label}.{extra}\n\n"
                f"Tap to open and check your nearest branch to BR1 3RU.",
                click=r.collect_link(f.candidate),
                tags="snowflake,shopping_cart",
                priority="high",
            )
            log(f">> ALERTED: {r.label} -- {f.candidate.name}")
            time.sleep(1)
        if len(newly_in_stock) > cap:
            ntfy_push(cfg, f"+{len(newly_in_stock) - cap} more units came into stock",
                      "Several units restocked at once - open the retailer sites to see them all.",
                      tags="package")

    # ---- persist --------------------------------------------------------
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    changed = now_items != prev
    if changed or state.get("last_commit_day") != today:
        state["items"] = now_items
        state["last_run"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
        state["last_commit_day"] = today
        state["initialised"] = True
        if not args.dry_run:
            save_state(state)
            log("State saved.")
    else:
        log("No change since last run; state left untouched.")

    broken = [r for r in reports if not r.ok]
    if broken:
        log("Retailers unavailable this run: "
            + "; ".join(f"{r.name} ({r.reason})" for r in broken))
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description="Portable AC stock watcher for BR1 3RU")
    p.add_argument("--dry-run", action="store_true", help="check stock but send nothing")
    p.add_argument("--test-notify", action="store_true", help="send a test push and exit")
    p.add_argument("--verbose", action="store_true", help="show every product considered")
    p.add_argument("--reset", action="store_true", help="clear saved state and re-baseline")
    p.add_argument("--only", default="", help="comma separated retailer keys, e.g. bq,screwfix")
    args = p.parse_args()

    with open(CONFIG_PATH, encoding="utf-8") as f:
        cfg = json.load(f)

    if args.test_notify:
        ok = ntfy_push(cfg, "AC stock watch - test",
                       "If you can read this on your iPhone and your laptop, "
                       "notifications are working correctly.",
                       tags="white_check_mark")
        log("Test notification sent." if ok else "Test notification FAILED.")
        return 0 if ok else 1

    if args.reset and os.path.exists(STATE_PATH):
        os.remove(STATE_PATH)
        log("State cleared.")

    return run(cfg, args)


if __name__ == "__main__":
    sys.exit(main())
