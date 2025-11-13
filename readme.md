# Kraken Automated Buying Bot (Google Sheets + CCXT)

This script performs **automated crypto purchasing on Kraken**, using signals and multipliers defined inside a Google Sheet. It reads data row‑by‑row, calculates an order size using tier, MA, icon, and sentiment multipliers, then places **live market buy orders** through Kraken’s API using **CCXT**.

This is designed for **one‑shot runs** (cron, GitHub Actions, scheduled job, etc.).

---

## 🚀 What the Bot Does

For each asset row in your Google Sheet, the bot:

1. Reads:

   * Symbol (A)
   * Price (B)
   * % Down from ATH (C)
   * Long MA (I)
   * Icon (O)
   * Sentiment (P)
2. Determines a **tier fraction** based on % down from ATH.
3. Applies:

   * **Icon multiplier**
   * **Moving average multiplier** (I ÷ B)
   * **Sentiment multiplier** (using column P)
4. Computes order notional subject to:

   * Remaining available funds on Kraken
   * `MIN_ORDER_NOTIONAL`
5. Places a **live market buy order** on Kraken using CCXT.
6. Logs all actions to console.

---

## 📄 Google Sheet Layout

The script expects a worksheet like:

| Col | Purpose                                          |
| --- | ------------------------------------------------ |
| A   | Symbol (e.g., `ETH`)                             |
| B   | Current Price                                    |
| C   | % Down From ATH (negative)                       |
| I   | Long Moving Average                              |
| O   | Icon flag (💎, 💥, 🚀, ✨, 📊)                    |
| P   | Optional sentiment multiplier (positive numeric) |

You may have additional columns — the bot ignores all except the above.

Worksheet name defaults to **`Kraken-Screener`**, but can be changed via env vars.

---

## 🔧 Environment Variables

| Variable               | Required | Description                                                   |
| ---------------------- | -------- | ------------------------------------------------------------- |
| `GOOGLE_CREDS_JSON`    | Yes      | Full Google service account JSON as a **single-line string**. |
| `KRAKEN_API_KEY`       | Yes      | Kraken API key.                                               |
| `KRAKEN_API_SECRET`    | Yes      | Kraken API secret.                                            |
| `KRAKEN_BASE_CURRENCY` | No       | Default: `USD`. Quote currency for buying.                    |
| `MIN_ORDER_NOTIONAL`   | No       | Default: `5.0`. Smallest allowed order in quote currency.     |
| `SHEET_NAME`           | No       | Default: `Active-Investing`.                                  |
| `WORKSHEET_NAME`       | No       | Default: `Kraken-Screener`.                                   |

---

## 🧮 Order Sizing Logic

### 1. **Tier Fraction (based on % down from ATH)**

| % Down Range | Tier Fraction |
| ------------ | ------------- |
| 0–25%        | 0.05          |
| 26–50%       | 0.10          |
| 51–75%       | 0.15          |
| 76–99.9%     | 0.20          |

### 2. **Icon Multipliers**

```
💎 → 1.0
💥 → 0.9
🚀 → 0.8
✨ → 0.7
📊 → 0.6
```

### 3. **Sentiment Multiplier** (Column P)

* If positive numeric → use the number.
* Missing/invalid/non-positive → **0.1**.

### 4. **MA Multiplier**

```
MA Ratio = (Long MA) / (Price)
```

### 5. **Order Notional**

```
base_notional = remaining_funds × tier_fraction
order_notional = base_notional × icon_mult × ma_ratio × sentiment_mult
```

Capped by:

* Remaining funds
* `MIN_ORDER_NOTIONAL`

Then converted to:

```
amount_base = order_notional / price
```

Final market symbol example:

```
ETH/USD
```

---

## 🏦 Kraken API (CCXT)

* Uses `ccxt.kraken()`
* Handles rate limiting via CCXT built‑ins
* Places **market buy** orders:

```python
exchange.create_market_buy_order(market_symbol, amount_base)
```

The response `order['id']` is displayed in logs.

---

## 📚 Installation

```bash
pip install ccxt gspread google-auth requests
```

Ensure your Google service account:

* Has Drive + Sheets API enabled
* Is shared as **Editor** on your target Google Sheet

---

## ▶️ Running

```bash
python kraken_buy_bot.py
```

Output example:

```
Row 5 (ETH): price=2345.12, pct_down=-42.3, tier_fraction=0.10,
icon=💎, ma_ratio=1.0543, sent_mult=0.23,
order_notional=18.22 USD, amount=0.00777 ETH
Row 5 (ETH): order placed, id=XYZ123, spent=18.22 USD
```

---

## 💡 Notes & Safety

* Script performs **live** trades — use responsibly.
* Always test using **Kraken sandbox** or minimal funds.
* Ensure your sheet data is accurate before running.

---

## 🛠 Future Enhancements (Ideas)

* Auto‑logging trades to a Google Sheet
* Adding stop‑loss or sell logic
* Exchange abstraction layer (Binance, Coinbase, etc.)
* Probability‑weighted sentiment integration
* Telegram or Discord alerts

---

## 📄 License

Add your preferred license here.
