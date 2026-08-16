# Hand-off — Portable AC stock watcher (Bromley BR1 3RU)

Written 16 August 2026. Everything below is **verified working**, not planned.
Read this top to bottom before changing anything.

---

## 1. What this is

Watches UK retailers for portable air conditioning units available for click & collect
near BR1 3RU, and pushes a notification to Serhat's iPhone and laptop via ntfy.sh when
something that was out of stock becomes available.

Two independent halves:

| Half | Runs on | Covers | Schedule |
|---|---|---|---|
| **Cloud** | GitHub Actions | B&Q, Screwfix, Toolstation | Every 30 min, 24/7 |
| **Browser add-on** | Serhat's Mac, launchd | John Lewis | Every 30 min while awake |

They share nothing at runtime and keep **separate state files**, so one cannot corrupt
the other.

---

## 2. Where everything lives

| Thing | Location |
|---|---|
| GitHub repo (public) | https://github.com/Serhatdereli/ac-stock-watch |
| Local working copy | `~/ac-stock-watch` (this folder, is the git clone) |
| ntfy topic | `~/ac-stock-watch/.ntfy-topic` — **gitignored, treat as a password** |
| Same topic in CI | GitHub Actions secret `NTFY_TOPIC` |
| Cloud workflow | `.github/workflows/check-stock.yml` |
| Python venv | `~/ac-stock-watch/.venv` (gitignored) — has `playwright`, `curl_cffi` |
| Chrome profile for automation | `~/ac-stock-watch/.browser-profile` (gitignored) |
| launchd job | `~/Library/LaunchAgents/com.serhat.acstockwatch.plist` |
| Cloud state | `state.json` (committed by the workflow each run) |
| Mac state | `state-browser.json` (local only, gitignored) |
| Mac log | `ac-stock-watch.log` (gitignored, auto-trimmed to 2000 lines) |

`gh` CLI is installed and authenticated as **Serhatdereli** with `repo` + `workflow`
scopes, so no browser login is needed for any GitHub operation.

---

## 3. Files and what each does

| File | Purpose |
|---|---|
| `check_stock.py` | The main checker. **Standard library only** — no pip installs. Used by the cloud job. Keep it dependency-free. |
| `browser_check.py` | The browser add-on. Needs Playwright. Drives real Chrome off-screen for retailers that refuse plain HTTP. Imports helpers from `check_stock.py`. |
| `config.json` | All tuning: retailers, search terms, product filters, price floor/cap, alert mode. |
| `run-on-mac.sh` | What launchd calls. Loads the topic, runs `browser_check.py`, trims the log. |
| `com.serhat.acstockwatch.plist` | launchd definition, `StartInterval` 1800s. |
| `SETUP.md` | End-user instructions written for a non-developer. |
| `probe_browser.py` | Throwaway diagnostic (gitignored). Run it to re-test whether a retailer's bot protection has changed. |

---

## 4. Verified retailer findings — read before "fixing" anything

This was tested exhaustively. **Do not assume a retailer is broken code.**

| Retailer | Plain HTTP | curl_cffi (TLS spoof) | Headless Chrome | Automated visible Chrome | Verdict |
|---|---|---|---|---|---|
| **B&Q** (diy.com) | ✅ works | — | — | — | **Live in cloud.** schema.org offers split Click&Collect / In-Store / Home Delivery |
| **Screwfix** | ✅ works | — | — | — | **Live in cloud.** Same split. `/checkstock?product_id=SKU` deep-links to branch stock |
| **Toolstation** | ⚠️ 200 but empty | — | not tried | not tried | Enabled, returns 0. Nuxt-rendered. Move to `browser_check.py` if wanted |
| **John Lewis** | ❌ empty shell | ⚠️ ItemList without offers | ❌ `ERR_HTTP2_PROTOCOL_ERROR` | ✅ works | **Live on Mac.** Product pages carry proper schema.org availability |
| **Argos** | ❌ 403 Akamai | ❌ 403 (one fluke 200 with `safari`, never repeated) | ❌ Access Denied | ❌ Access Denied | **Blocked.** Product pages blocked too, not just search |
| **Currys** | ❌ 403 | ✅ 200 but no structured data, client-rendered | ❌ Cloudflare | ❌ Cloudflare | **Blocked** |

Argos and Currys were tested from Serhat's **home broadband** as well as from GitHub's
data centre. Both refuse either way. The only thing that ever loaded Argos was his
ordinary, hand-driven Chrome with his real profile.

**Notable:** Argos is the only retailer of the six that filters results to
*BR1 3RU within 25 miles* — genuinely local stock rather than national. That makes it
the highest-value target if anyone finds a durable way in. At time of writing it listed
MeacoCool 9000BTU £400, Pro Breeze 5000BTU £399.99, Pro Breeze 12,000BTU £669.99 —
all out of stock.

---

## 5. How the logic works

**Product filtering is the hard part, not fetching.** A B&Q search for "portable air
conditioner" returns 51 results: desk fans, car vent clips, hose covers, an inflatable
mattress, a card reader. Two are actual AC units.

`looks_like_ac_unit()` in `check_stock.py` filters on, in order:

1. `exclude_keywords` — kills "air cooler", "car clip", "cover", "hose", "bracket" etc.
2. `require_any_keyword` — must mention air conditioning
3. `require_btu_rating` — must advertise a BTU figure. **Single most effective rule.**
   Genuine units advertise BTU; fans don't.
4. `min_price` (£100) / `max_price` (unset)

Measured effect: B&Q 51 → 2, Screwfix 9 → 3.

`browser_check.py` deliberately sets `require_btu_rating = False`, because John Lewis
already narrows to its Air Conditioners category and some genuine units (e.g. "Meaco
7000R PRO") have no BTU in the title.

**Stock reading** — `read_offers()` parses schema.org `Offer` blocks. Retailers publish
one Offer per fulfilment route:

```
OnSitePickup  + InStock     -> collect available
ParcelService + OutOfStock  -> delivery unavailable
```

`alert_on` in config decides which counts: `collect` (default), `delivery`, or `any`.

**De-duplication** — state maps `retailer:sku` → `{in_stock: bool}`. An alert fires only
on a `False → True` transition. First ever run sends one baseline summary then goes
quiet, so there's no flood on install. A retailer that errors keeps its previous entries,
so an outage doesn't cause a re-alert storm on recovery.

---

## 6. Verified test results

- Cloud workflow: two manual runs, both green (51s, 36s). Second run correctly silent.
- State commits back to the repo successfully (`contents: write` is granted).
- Simulated a unit going out of stock then returning → alerted **exactly once**.
- Three ntfy pushes confirmed delivered end-to-end via the ntfy poll API.
- Browser add-on: found all 4 John Lewis units, read availability correctly, baseline sent.
- launchd job loaded and running (`launchctl list | grep acstockwatch` → exit code 0).

**Live stock at handover:** Screwfix had 3 units available for click & collect —
Air Conditioning Unit 5000BTU £174.99, Blyss 9000BTU £269.99, Blyss 12,000BTU £299.99.
B&Q's 2 units were delivery-only. All 4 John Lewis units out of stock.

---

## 7. Open items, roughly by value

**1. Serhat must subscribe on his iPhone.** Nothing else is blocking, but he won't see
alerts until he installs the ntfy app and subscribes to the topic in `.ntfy-topic`.
Alerts already sent are held by ntfy and will appear on subscribe.

**2. Per-branch stock rather than national.** B&Q, Screwfix and John Lewis publish
national availability. An item can be collectable somewhere in the UK but not in
Bromley. Alerts currently deep-link into each retailer's own branch checker
(Screwfix `/checkstock?product_id=SKU`) so it's one tap to confirm. Genuine per-branch
numbers sit behind undocumented client-side calls — investigate only if it matters.

**3. Toolstation returns 0 results.** It's Nuxt-rendered. Either move it into
`browser_check.py` (it isn't bot-protected, so headless Chrome should be enough) or
drop it from `config.json` to stop the pointless request.

**4. Argos and Currys.** The only untried approach is attaching to Serhat's *everyday*
Chrome over CDP (`--remote-debugging-port`) so the request carries his real profile and
history. Considered and not done: it conflicts with normal browsing (profile lock),
breaks whenever he restarts Chrome, and is an arms race. Recommend leaving these alone
unless he specifically asks again. If attempted, `probe_browser.py` is the quickest way
to re-test.

**5. Mac half only runs while the Mac is awake.** By design. The cloud half is
unaffected. If John Lewis coverage needs to be 24/7 it would have to move to a machine
that stays on.

**6. GitHub disables scheduled workflows after 60 days of repo inactivity.** The job
commits `state.json` roughly daily, which should keep it alive. If alerts stop for
months, check the Actions tab for a "workflow disabled" banner.

---

## 8. Gotchas that cost time — don't rediscover these

- **`state.json` conflicts.** The cloud job commits `state.json` back to `main`, so a
  local `git push` will be rejected as non-fast-forward. Always
  `git checkout -- state.json && git pull --rebase origin main` before pushing.

- **Never let the ntfy topic reach the repo.** The repo is public. `run-on-mac.sh` reads
  it from the gitignored `.ntfy-topic`. Before any push, run:
  ```bash
  git grep -q "$(cat .ntfy-topic)" --cached && echo "LEAK" || echo "clean"
  ```

- **`check_stock.py` must stay dependency-free.** The cloud job runs it with bare
  Python 3.12 and no `pip install` step. Anything needing a package belongs in
  `browser_check.py`.

- **The two halves must not share a state file.** `check_stock.py` honours the
  `AC_STATE_FILE` env var for exactly this reason; `browser_check.py` hard-codes
  `state-browser.json`. Sharing one file would make each half wipe the other's entries,
  because each writes the full dict from its own run.

- **Product names from search cards are unreliable.** John Lewis cards expose finance
  small print ("Pay no interest from £74.83 a month") rather than the product title.
  `slug_name()` derives the name from the URL slug instead. Applies to most modern
  retail front-ends — check before trusting `innerText`.

- **Repo must stay public** for unlimited Actions minutes. Private is capped at 2,000
  min/month; at 48 runs/day this would consume most of it.

- **Be polite.** 30-minute interval, 1.5s between requests, ~12 product pages per
  retailer per run. Don't tighten it — the blocks in section 4 are what happens when
  sites decide they don't like you.

---

## 9. Commands

```bash
cd ~/ac-stock-watch

# --- cloud half (no dependencies) ---
python3 check_stock.py --dry-run --verbose     # see every product and why kept/dropped
python3 check_stock.py --test-notify           # confirm push reaches both devices
python3 check_stock.py --only bq,screwfix      # limit to specific retailers
python3 check_stock.py --reset                 # forget history, re-baseline

# --- browser half ---
./.venv/bin/python browser_check.py --dry-run --verbose
./.venv/bin/python probe_browser.py            # re-test bot protection (HEADLESS=0 for visible)
./run-on-mac.sh                                # exactly what launchd runs

# --- launchd ---
launchctl list | grep acstockwatch             # 2nd column is last exit code, want 0
launchctl unload ~/Library/LaunchAgents/com.serhat.acstockwatch.plist
launchctl load   ~/Library/LaunchAgents/com.serhat.acstockwatch.plist

# --- GitHub ---
gh run list --workflow="Check AC stock" --limit 5
gh run view <run-id> --log
gh workflow run "Check AC stock"
gh secret list

# --- what's being tracked right now ---
python3 -c "import json;d=json.load(open('state.json'));[print(('IN STOCK ' if v['in_stock'] else 'out      '),v['retailer'],v['name'][:55]) for v in d['items'].values()]"
```

---

## 10. If asked to extend this

Most likely requests, and where they land:

| Request | Where |
|---|---|
| "Stop alerting about X" | add a word to `matching.exclude_keywords` in `config.json` |
| "Only under £400" | set `matching.max_price` |
| "Tell me about delivery too" | set `settings.alert_on` to `"any"` |
| "Check more often" | edit the `cron` in `.github/workflows/check-stock.yml` — but read section 8 first |
| "Add retailer Y" | new adapter class in `check_stock.py` if it serves static HTML with schema.org data; otherwise an entry in `RETAILERS` in `browser_check.py` |
| "Watch something other than AC units" | `search_terms` + `matching` rules in `config.json`. The whole thing is generic; nothing is AC-specific outside config |

The architecture is deliberately boring: adapters return `Candidate`s, `read_offers()`
turns a page into a `StockResult`, and the state/notify layer is shared. Add retailers
by writing a `search()` method; everything downstream is free.
