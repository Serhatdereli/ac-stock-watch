# Portable AC stock watcher — Bromley BR1 3RU

Watches UK retailers for portable air conditioning units available for **click & collect**, and pushes an alert to your iPhone and laptop the moment something new comes into stock.

Costs nothing to run. Uses no Claude usage at all once it's set up.

---

## What it actually does

Every 30 minutes it searches each retailer, throws away the fans, air coolers, hoses and covers that clutter the results, and checks the genuine AC units for collection availability. If a unit that was out of stock is now collectable, you get a push notification with the price and a link straight to the branch stock checker.

You are **not** notified again for the same unit until it goes out of stock and comes back.

### Retailer coverage — read this bit

| Retailer | Status |
|---|---|
| **B&Q** | ✅ Working — publishes collect and delivery availability separately |
| **Screwfix** | ✅ Working — publishes collect and delivery availability separately |
| Toolstation | ⚠️ Best effort — builds its results in the browser, so usually returns nothing |
| Argos | ❌ Needs the browser add-on |
| Currys | ❌ Needs the browser add-on |
| John Lewis | ❌ Needs the browser add-on |

**Why three retailers are missing.** B&Q and Screwfix publish their stock as structured data inside the page, which anything can read. Argos, Currys and John Lewis build their search results in the browser using JavaScript, so a plain fetch receives an empty shell with no products in it. Argos goes further and refuses non-browser requests outright — this was tested from a home broadband connection as well as from the cloud, and it blocks both.

Covering them properly means driving a real Chrome in the background, which is a separate opt-in add-on rather than something worth forcing on every install.

**Worth knowing:** Argos is the only one of the six that filters its results to *BR1 3RU within 25 miles*, so if you do add the browser add-on later, Argos gives genuinely local stock rather than national availability. At the time of setup it listed three portable units — MeacoCool 9000BTU at £400, Pro Breeze 5000BTU at £399.99 and Pro Breeze 12,000BTU at £669.99 — all out of stock.

---

## Part 1 — Phone alerts (5 minutes)

A private topic has already been generated and saved on your Mac at `~/ac-stock-watch/.ntfy-topic`. It is stored as a GitHub Actions secret and is deliberately excluded from this repository — treat it like a password, since anyone who knows it can read your alerts.

To see it:

```bash
cat ~/ac-stock-watch/.ntfy-topic
```

1. Install **ntfy** on your iPhone — free, App Store, by Philipp Heckel.
2. In the app: **+** → paste that topic → **Subscribe**.
3. On your laptop, open <https://ntfy.sh/> and subscribe to the same topic (or install the Mac app). Allow notifications when the browser asks.

That's both devices covered by one topic. Any alert already sent will appear as soon as you subscribe — ntfy holds recent messages for you.

---

## Part 2 — The always-on cloud checker

> **✅ Already done.** The repo is live at <https://github.com/Serhatdereli/ac-stock-watch>, the `NTFY_TOPIC` secret is set, workflow write permission is granted, and the first run completed successfully. It now runs itself every 30 minutes. The steps below are kept only as a record of how it was set up, or in case you ever need to rebuild it.

1. **Create a free GitHub account** at <https://github.com/signup> if you don't have one.

2. **Create a repository**
   - <https://github.com/new>
   - Name: `ac-stock-watch`
   - Set it to **Public** — public repos get unlimited free Actions minutes; private ones are capped at 2,000 a month, which this would eat most of.
   - Click **Create repository**.

   Your ntfy topic is stored separately as a secret, so nothing private goes into the public repo.

3. **Upload the files**
   - On the new repo page, click **uploading an existing file**.
   - Drag in everything from this folder **including the hidden `.github` folder**.
   - If macOS won't let you see `.github`, press `Cmd + Shift + .` in Finder to show hidden files.
   - Click **Commit changes**.

4. **Add your topic as a secret**
   - Repo → **Settings** → **Secrets and variables** → **Actions**
   - **New repository secret**
   - Name: `NTFY_TOPIC`
   - Secret: your topic from Part 1
   - **Add secret**

5. **Let it write its own memory**
   - Repo → **Settings** → **Actions** → **General**
   - Scroll to **Workflow permissions** → select **Read and write permissions** → **Save**
   - Without this the checker works but forgets what it already told you about.

6. **Run it once by hand**
   - Repo → **Actions** tab → if prompted, click **I understand my workflows, go ahead and enable them**
   - Click **Check AC stock** → **Run workflow** → **Run workflow**
   - After a minute or two you should get a "AC watch is live" notification on your phone.

Done. It now runs itself every 30 minutes, forever, free.

---

## Part 3 — The browser add-on for Argos, Currys and John Lewis (optional)

Not installed by default. Skip it unless you specifically want those three covered.

These retailers only reveal their stock to a real browser. The add-on drives your existing Chrome in the background — headless, so no windows appear — reads the same pages you'd see by hand, and feeds the results into the same alerting.

**Trade-offs, honestly:**

- It only runs while the Mac is awake, so overnight restocks are missed. The cloud job is unaffected.
- It's more fragile than the cloud job. Retailers change their pages, and bot protection is an arms race — expect to need the occasional fix.
- Upside: Argos is the only retailer of the six that filters stock to *BR1 3RU within 25 miles*, so it gives real local availability rather than national.

The Mac-side pieces (`run-on-mac.sh`, `com.serhat.acstockwatch.plist`) are already in this folder, ready to be pointed at the add-on once it exists. `run-on-mac.sh` reads your ntfy topic from a `.ntfy-topic` file kept out of the repo, so nothing private is ever published.

To schedule it once the add-on is in place:

```bash
cp ~/ac-stock-watch/com.serhat.acstockwatch.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.serhat.acstockwatch.plist
```

To stop it later:

```bash
launchctl unload ~/Library/LaunchAgents/com.serhat.acstockwatch.plist
```

---

## Tuning it

Everything lives in `config.json`.

| Setting | What it does |
|---|---|
| `settings.alert_on` | `"collect"` (default) alerts only on click & collect. Change to `"any"` to include home delivery, or `"delivery"` for delivery only. |
| `matching.min_price` | Currently £100. Real portable AC units start around £150; the junk is £10–£40. Raising this cuts noise further. |
| `matching.max_price` | `null` = no cap. Set to e.g. `400` to only hear about units under £400. |
| `matching.require_btu_rating` | `true` is the single most effective filter — genuine AC units advertise their BTU, desk fans don't. Turning it off will let some rubbish through. |
| `matching.exclude_keywords` | Add any word to permanently silence a category of junk. |
| `search_terms` | Add more phrases if you want wider coverage. |
| `retailers` | Remove any you don't care about. |

To change how often the cloud job runs, edit the `cron` line in `.github/workflows/check-stock.yml`. `"0 * * * *"` = hourly, `"*/15 * * * *"` = every 15 minutes.

---

## Useful commands

Run these from inside the folder in Terminal.

```bash
python3 check_stock.py --test-notify     # send a test push, confirm both devices
python3 check_stock.py --dry-run         # check stock, print results, send nothing
python3 check_stock.py --dry-run --verbose   # show every product and why it was kept or dropped
python3 check_stock.py --reset           # forget history and re-baseline
python3 check_stock.py --only bq,screwfix    # check specific retailers
```

---

## If something goes wrong

**No notifications at all**
Run `python3 check_stock.py --test-notify`. If that works, the problem is the GitHub secret — check `NTFY_TOPIC` is spelled exactly right in repo Settings. If the test fails, check the topic name matches what you subscribed to in the app.

**Alerts stopped after a couple of months**
GitHub switches off scheduled workflows in repos with no activity for 60 days. This one commits its state roughly daily so it should stay awake, but if it does sleep, just open the Actions tab and click **Enable workflow**.

**"Blocked by bot protection" in the logs**
Expected for Argos and Currys in the cloud. If you see it for B&Q or Screwfix, they've tightened things up — lengthen the interval in the cron line and it usually settles.

**Getting alerts about things that aren't air conditioners**
Add a word from the product name to `matching.exclude_keywords`, or raise `matching.min_price`.

**Alerted about something that's actually sold out**
Retailers publish availability at national level, so an item can be collectable somewhere in the country but not at Bromley. The alert links straight into the retailer's own branch checker so you can confirm before setting off. Per-branch numbers aren't published in any form that can be read reliably from outside — that's a genuine limitation, not something worth engineering around.

---

## A note on being a good citizen

This reads the same public product pages your browser does, at a deliberately slow pace, twice an hour, with a pause between every request. That's polite and proportionate. Don't drop the interval to every minute — you'd get blocked, and fairly.
