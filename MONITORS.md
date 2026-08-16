# Page monitors — Currys coverage via Visualping

**Status: set up and running.** Five monitors are live on the free plan, checking
daily, alerting to the same ntfy topic as everything else.

The automated watcher covers B&Q, Screwfix and John Lewis. This covers Currys.
Argos could not be covered — see below.

---

## Argos: definitively unreachable

Argos has now defeated **five** separate approaches:

| Approach | Result |
|---|---|
| Plain HTTP request | 403 Access Denied |
| TLS-fingerprint impersonation (curl_cffi, Chrome + Safari profiles) | 403 — one fluke success, never reproduced |
| Headless Chrome via Playwright | Access Denied |
| Automated visible Chrome via Playwright | Access Denied |
| **Visualping** (third-party, real browser, their infrastructure) | **Access Denied** |

Tested from a home broadband line and from a data centre. Product pages are blocked
as well as search pages. Only an ordinary Chrome that a human is driving gets in.

This matters more than it sounds: Argos is the **only** retailer of the ten checked
that filters availability to *BR1 3RU within 25 miles*. Everything else reports
national stock. So the one source of genuinely local data is the one source that
can't be automated.

**Practical answer:** check Argos by hand occasionally. The three units, all out of
stock at the time of writing:

- MeacoCool MC Series Pro 9000BTU — £400.00 — https://www.argos.co.uk/product/7623899
- Pro Breeze 5000 BTU 3-in-1 — £399.99 — https://www.argos.co.uk/product/yzd6dz6x
- Pro Breeze 12,000 BTU — £669.99 — https://www.argos.co.uk/product/3ev7rdph

---

## Currys: five monitors live

Visualping loads Currys without trouble and its AI correctly identifies the pages as
products, offering stock-status conditions directly.

| # | Unit | Job |
|---|---|---|
| 1 | LOGIK LAC07C25 Portable AC & Dehumidifier | 9087533 |
| 2 | MEACO MeacoCool 8000CHR PRO | 9087536 |
| 3 | DELONGHI Pinguino ES72 8300 BTU | 9087537 |
| 4 | DELONGHI Pinguino EX100 10000 BTU | 9087540 |
| 5 | LOGIK LAC12C24 12000 BTU | 9087543 |

Chosen to span 7,000–12,000 BTU and budget through premium, so a restock anywhere in
the range gets caught.

**Condition:** stock status change / product back in stock — Visualping words this
differently per page; each monitor uses whichever variant it offered.
**Frequency:** daily (the free plan's limit).
**Alerts:** webhook to the ntfy topic, so they arrive as phone notifications.

Dashboard: <https://visualping.io/jobs>

---

## The one thing to watch for

Visualping doesn't send a confirmation when a webhook is saved, so the webhook was
entered and accepted on all five but has not been proven end-to-end.

**The first real alert proves it.** If it arrives as a phone notification, everything
is wired correctly. If it arrives as an email instead, the webhook didn't save — open
the monitor, click **Notifications → Webhook**, and paste this in:

```bash
echo "https://ntfy.sh/$(cat ~/ac-stock-watch/.ntfy-topic)"
```

*(The topic isn't written into this file because the repository is public.)*

---

## Free plan limits

150 checks a month, refilling 16 September 2026. Five monitors checked daily uses
almost exactly that — so the allowance is fully committed. Adding a sixth monitor
means removing one, or the checks will run out before month end.

To swap a unit: open the monitor from the dashboard, delete it, then **New monitor**
and follow the same steps — paste URL, **Go**, pick the stock-status condition,
**Notifications → Webhook**, **Start monitoring**.

The full Currys range, if you want to swap in a different size:

<details>
<summary>All 13 Currys portable units — click to expand</summary>

Verified present 16 Aug 2026. Prefix each with `https://www.currys.co.uk/products/`.

- `meaco-meacocool-mc12000chr-pro-smart-air-conditioner-heater-and-dehumidifier-white-10260647.html`
- `meaco-meacocool-8000chr-pro-smart-air-conditioner-and-dehumidifier-white-10260645.html` ⭐ monitored
- `logik-lac07c25-portable-air-conditioner-and-dehumidifier-white-10270705.html` ⭐ monitored
- `logik-lac09c26-portable-air-conditioner-and-dehumidifier-white-10294164.html`
- `logik-lac12c24-portable-air-conditioner-and-dehumidifier-white-10257344.html` ⭐ monitored
- `logik-lac12ch26-portable-air-conditioner-heater-and-dehumidifier-white-10294167.html`
- `delonghi-pinguino-es72-8300-btu-air-conditioner-and-dehumidifier-white-10259980.html` ⭐ monitored
- `delonghi-pinguino-em90-eco-9800-btu-air-conditioner-and-dehumidifier-white-10226847.html`
- `delonghi-pinguino-ex100-10000-btu-portable-air-conditioner-and-dehumidifier-white-10300973.html` ⭐ monitored
- `delonghi-pinguino-ex93-extreme-9400-btu-portable-air-conditioner-fan-and-dehumidifier-white-10300951.html`
- `delonghi-pinguino-ap98-gentlejet-11500-btu-portable-air-conditioner-fan-and-dehumidifier-white-10300393.html`
- `delonghi-pinguino-ap130i-gentlejet-13000-btu-portable-air-conditioner-fan-and-dehumidifier-white-10300416.html`
- `dimplex-eco-air-portable-air-conditioner-and-dehumidifier-10301228.html`

</details>

---

## Where everything now stands

| Retailer | Covered by | Runs |
|---|---|---|
| B&Q | `check_stock.py` | GitHub Actions, every 30 min, 24/7 |
| Screwfix | `check_stock.py` | GitHub Actions, every 30 min, 24/7 |
| Toolstation | `check_stock.py` | GitHub Actions — best effort, usually returns nothing |
| John Lewis | `browser_check.py` | Mac launchd, every 30 min while awake |
| **Currys** | **Visualping** | **Daily, 5 units** |
| Argos | nothing — blocks everything | check by hand |
| AO.com | nothing — blocked | — |

All four channels alert to the same ntfy topic, so everything arrives in one place on
your phone and laptop.
