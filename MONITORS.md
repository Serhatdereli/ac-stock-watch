# Page monitors — covering the retailers the watcher can't reach

The automated watcher covers B&Q, Screwfix and John Lewis. Argos, Currys and AO
block it outright. This file covers those with a free page-monitoring service
instead, which works because those services render pages in a real browser.

**Set-up time: about 10 minutes. Cost: £0.**

---

## Which service

**Use [Visualping](https://visualping.io) for these three.** Argos sits behind Akamai,
Currys behind Cloudflare, and AO blocked us as well — Visualping renders pages in a
real browser, so it gets through where a plain fetcher won't. Free tier is 5 pages
checked daily.

[UptimeRobot](https://uptimerobot.com/free-tools/back-in-stock-alert/) is the
alternative: 50 monitors and 5-minute checks on the free tier (personal use only),
which is six times faster than our own job. But it fetches raw HTML rather than
rendering, so **it may be refused by Cloudflare on Currys**. Worth trying, since the
allowance is so much bigger — just set up **one** monitor first and confirm it reports
the page correctly before building the rest.

Honest expectation: the same bot protection that blocked us may block them. Test one,
then scale.

---

## Send the alerts to your phone, not your inbox

Both services can POST to a webhook. Point it at your existing ntfy topic and these
alerts land in the same place as everything else, rather than in email.

Get your webhook URL by running this in Terminal, then paste the result into the
service:

```bash
echo "https://ntfy.sh/$(cat ~/ac-stock-watch/.ntfy-topic)"
```

Set the webhook method to **POST** and leave the body as the default text. If your
plan doesn't include webhooks, use email — it still reaches both devices.

*(The topic itself is deliberately not written into this file, because this file
lives in a public repository. Treat it like a password.)*

---

## What to monitor — in priority order

### 1-3. Argos (highest value — the only genuinely local stock data)

Argos is the only retailer of the nine that filters availability to **BR1 3RU within
25 miles**. Everything else reports national stock. These three were all out of stock
at setup.

| Unit | Price | URL |
|---|---|---|
| MeacoCool MC Series Pro 9000BTU | £400.00 | https://www.argos.co.uk/product/7623899 |
| Pro Breeze 5000 BTU 3-in-1 | £399.99 | https://www.argos.co.uk/product/yzd6dz6x |
| Pro Breeze 12,000 BTU | £669.99 | https://www.argos.co.uk/product/3ev7rdph |

**Keyword to watch:** `Out of stock`
**Alert when:** the keyword **disappears** (that's the restock)

### 4-5. Currys — pick two

Currys carries the widest portable range of any retailer checked. Two suggestions
below; the full list follows if you'd rather choose your own.

| Unit | URL |
|---|---|
| LOGIK LAC07C25 Portable AC & Dehumidifier | https://www.currys.co.uk/products/logik-lac07c25-portable-air-conditioner-and-dehumidifier-white-10270705.html |
| DELONGHI Pinguino ES72 8300 BTU | https://www.currys.co.uk/products/delonghi-pinguino-es72-8300-btu-air-conditioner-and-dehumidifier-white-10259980.html |

**Keyword to watch:** `Out of stock`
**Alert when:** the keyword **disappears**

<details>
<summary>Full Currys portable range (13 units) — click to expand</summary>

All verified present on 16 Aug 2026. Split-system and installation packages excluded.

- MEACO MeacoCool MC12000CHR PRO — `/products/meaco-meacocool-mc12000chr-pro-smart-air-conditioner-heater-and-dehumidifier-white-10260647.html`
- MEACO MeacoCool 8000CHR PRO — `/products/meaco-meacocool-8000chr-pro-smart-air-conditioner-and-dehumidifier-white-10260645.html`
- LOGIK LAC07C25 — `/products/logik-lac07c25-portable-air-conditioner-and-dehumidifier-white-10270705.html`
- LOGIK LAC09C26 — `/products/logik-lac09c26-portable-air-conditioner-and-dehumidifier-white-10294164.html`
- LOGIK LAC12C24 — `/products/logik-lac12c24-portable-air-conditioner-and-dehumidifier-white-10257344.html`
- LOGIK LAC12CH26 — `/products/logik-lac12ch26-portable-air-conditioner-heater-and-dehumidifier-white-10294167.html`
- DELONGHI Pinguino ES72 8300 BTU — `/products/delonghi-pinguino-es72-8300-btu-air-conditioner-and-dehumidifier-white-10259980.html`
- DELONGHI Pinguino EM90 ECO 9800 BTU — `/products/delonghi-pinguino-em90-eco-9800-btu-air-conditioner-and-dehumidifier-white-10226847.html`
- DELONGHI Pinguino EX100 10000 BTU — `/products/delonghi-pinguino-ex100-10000-btu-portable-air-conditioner-and-dehumidifier-white-10300973.html`
- DELONGHI Pinguino EX93 Extreme 9400 BTU — `/products/delonghi-pinguino-ex93-extreme-9400-btu-portable-air-conditioner-fan-and-dehumidifier-white-10300951.html`
- DELONGHI Pinguino AP98 GentleJet 11500 BTU — `/products/delonghi-pinguino-ap98-gentlejet-11500-btu-portable-air-conditioner-fan-and-dehumidifier-white-10300393.html`
- DELONGHI Pinguino AP130i GentleJet 13000 BTU — `/products/delonghi-pinguino-ap130i-gentlejet-13000-btu-portable-air-conditioner-fan-and-dehumidifier-white-10300416.html`
- DIMPLEX Eco Air — `/products/dimplex-eco-air-portable-air-conditioner-and-dehumidifier-10301228.html`

Prefix each with `https://www.currys.co.uk`.

</details>

---

## Steps

1. Go to [visualping.io](https://visualping.io) and create a free account.
2. Paste the first Argos URL. Choose **text change** monitoring.
3. Select the area of the page showing stock status, or set the keyword to
   `Out of stock` and alert when it disappears.
4. Set the check frequency to daily (the free tier's limit).
5. Add the webhook URL from the section above, or use email.
6. **Confirm this one works before adding the rest** — if Argos blocks Visualping too,
   there's no point building four more.
7. Repeat for the remaining four.

---

## What this does and doesn't give you

**Does:** covers the three retailers the watcher can't reach, including the only
BR1-local stock data available anywhere.

**Doesn't:** discover new products. A page monitor only ever watches the exact URLs
you give it. If Argos stocks a new model next week, you won't hear about it — the
watcher would have caught that on B&Q or Screwfix, but nobody will catch it on Argos.

That's the honest trade. Between the two approaches you get broad discovery on three
retailers and pinpoint coverage on five specific units elsewhere.
