import os
import json
import sys
from typing import Optional, List

import ccxt
import gspread
from google.oauth2.service_account import Credentials


# ------------ Config via ENV ------------ #

GOOGLE_CREDS_JSON = os.environ.get("GOOGLE_CREDS_JSON")
KRAKEN_API_KEY = os.environ.get("KRAKEN_API_KEY")
KRAKEN_API_SECRET = os.environ.get("KRAKEN_API_SECRET")

# Quote currency you’re spending on Kraken (e.g. USD, USDT, EUR)
BASE_CURRENCY = os.environ.get("KRAKEN_BASE_CURRENCY", "USD")

# Optional: minimum order notional in quote currency (to avoid microscopic orders)
MIN_ORDER_NOTIONAL = float(os.environ.get("MIN_ORDER_NOTIONAL", "5.0"))

# Sheet / worksheet names
SHEET_NAME = os.environ.get("SHEET_NAME", "Active-Investing")
WORKSHEET_NAME = os.environ.get("WORKSHEET_NAME", "Kraken-Screener")


# ------------ Helpers ------------ #

def fatal(msg: str):
    print(f"[FATAL] {msg}", file=sys.stderr)
    sys.exit(1)


def get_gspread_client():
    if not GOOGLE_CREDS_JSON:
        fatal("GOOGLE_CREDS_JSON env var is not set.")

    try:
        info = json.loads(GOOGLE_CREDS_JSON)
    except json.JSONDecodeError as e:
        fatal(f"GOOGLE_CREDS_JSON is not valid JSON: {e}")

    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive",
    ]
    creds = Credentials.from_service_account_info(info, scopes=scopes)
    return gspread.authorize(creds)


def get_kraken_exchange():
    if not KRAKEN_API_KEY or not KRAKEN_API_SECRET:
        fatal("KRAKEN_API_KEY and/or KRAKEN_API_SECRET env vars are not set.")

    exchange = ccxt.kraken({
        "apiKey": KRAKEN_API_KEY,
        "secret": KRAKEN_API_SECRET,
        "enableRateLimit": True,
    })
    return exchange


def parse_float(value: str) -> Optional[float]:
    if value is None:
        return None
    value = str(value).strip()
    if value == "":
        return None
    try:
        return float(value)
    except ValueError:
        return None


def determine_tier_fraction(pct_down: float) -> Optional[float]:
    """
    pct_down is expected to be negative (e.g., -37.5 for 37.5% down).
    We use its absolute value to map tiers:
        0%–25% down: 5% of funds
        26%–50% down: 10% of funds
        51%–75% down: 15% of funds
        76%–99.9% down: 20% of funds
    """
    d = abs(pct_down)

    if 0 <= d <= 25:
        return 0.05
    elif 26 <= d <= 50:
        return 0.10
    elif 51 <= d <= 75:
        return 0.15
    elif 76 <= d <= 99.9:
        return 0.20
    else:
        # Outside your specified brackets
        return None


ICON_MULTIPLIERS = {
    "💎": 1.0,
    "💥": 0.9,
    "🚀": 0.8,
    "✨": 0.7,
    "📊": 0.6,
}


def sentiment_multiplier(sent_str: Optional[str]) -> Optional[float]:
    """
    Column P: if a positive numeric value exists, use that as the multiplier.
    If no entry, invalid, or non-positive, return None (meaning: do not buy).
    """
    if sent_str is None:
        return None

    sent_str = str(sent_str).strip()
    if sent_str == "":
        return None

    val = parse_float(sent_str)
    if val is not None and val > 0:
        return val

    return None


# ------------ Core Logic ------------ #

def main():
    print("Starting Kraken crypto buying bot (one-shot run).")

    # 1. Connect to Google Sheets
    gc = get_gspread_client()
    try:
        sh = gc.open(SHEET_NAME)
    except Exception as e:
        fatal(f"Unable to open Google Sheet '{SHEET_NAME}': {e}")

    try:
        ws = sh.worksheet(WORKSHEET_NAME)
    except Exception as e:
        fatal(f"Unable to open worksheet '{WORKSHEET_NAME}': {e}")

    # Get all values. First row is header, data starts at second row.
    all_values: List[List[str]] = ws.get_all_values()
    if len(all_values) < 2:
        print("No data rows in sheet; exiting.")
        return

    header = all_values[0]
    data_rows = all_values[1:]

    print(f"Header row: {header}")
    print(f"Loaded {len(data_rows)} data rows from worksheet '{WORKSHEET_NAME}'.")

    # 2. Connect to Kraken & get available funds
    exchange = get_kraken_exchange()
    balance = exchange.fetch_balance()
    free_funds = balance.get(BASE_CURRENCY, {}).get("free")

    if free_funds is None:
        # ccxt's generic structure: balance['free'][BASE_CURRENCY]
        free_dict = balance.get("free", {})
        free_funds = free_dict.get(BASE_CURRENCY)

    if free_funds is None:
        fatal(f"Could not determine free balance for base currency '{BASE_CURRENCY}'.")

    remaining_funds = float(free_funds)
    print(f"Available funds in Kraken ({BASE_CURRENCY}): {remaining_funds}")

    if remaining_funds <= 0:
        print("No available funds. Exiting without placing any orders.")
        return

    # Column indexes (0-based)
    COL_SYMBOL = 0  # A: crypto symbol (e.g. 'ETH')
    COL_PRICE = 1   # B: current price
    COL_PCT_DOWN = 2  # C: % down from ATH
    COL_LONG_MA = 8   # I: long MA
    COL_ICON = 14     # O: icon
    COL_SENTIMENT = 15  # P: sentiment (optional)

    orders_placed = []

    # 3. Iterate over sheet rows
    for idx, row in enumerate(data_rows, start=2):  # start=2 for real sheet row number
        # Ensure row has enough columns
        if len(row) <= max(COL_SENTIMENT, COL_ICON, COL_LONG_MA, COL_PCT_DOWN, COL_PRICE, COL_SYMBOL):
            print(f"Row {idx}: not enough columns, skipping.")
            continue

        symbol = row[COL_SYMBOL].strip().upper()
        price_str = row[COL_PRICE]
        pct_down_str = row[COL_PCT_DOWN]
        long_ma_str = row[COL_LONG_MA]
        icon = row[COL_ICON].strip()
        sentiment_str = row[COL_SENTIMENT] if len(row) > COL_SENTIMENT else ""

        # Required fields (except P): if missing, skip asset
        if not symbol or not price_str or not pct_down_str or not long_ma_str or not icon:
            print(f"Row {idx} ({symbol}): missing required data, skipping.")
            continue

        if icon not in ICON_MULTIPLIERS:
            print(f"Row {idx} ({symbol}): icon '{icon}' not in allowed set, skipping.")
            continue

        price = parse_float(price_str)
        pct_down = parse_float(pct_down_str)
        long_ma = parse_float(long_ma_str)

        if price is None or pct_down is None or long_ma is None:
            print(f"Row {idx} ({symbol}): invalid numeric data, skipping.")
            continue

        if price <= 0:
            print(f"Row {idx} ({symbol}): non-positive price, skipping.")
            continue

        # Tier fraction from % down from ATH
        tier_fraction = determine_tier_fraction(pct_down)
        if tier_fraction is None:
            print(f"Row {idx} ({symbol}): % down {pct_down} not in any bracket, skipping.")
            continue

        # Icon multiplier
        icon_mult = ICON_MULTIPLIERS[icon]

        # MA multiplier: I / B
        ma_ratio = long_ma / price

        # Sentiment multiplier: if missing/invalid/non-positive -> skip buying
        sent_mult = sentiment_multiplier(sentiment_str)
        if sent_mult is None:
            print(f"Row {idx} ({symbol}): sentiment missing or non-positive, skipping buy.")
            continue

        # If no funds left, stop processing
        if remaining_funds <= 0:
            print("No remaining funds; stopping further processing.")
            break

        # Base notional from tier
        base_notional = remaining_funds * tier_fraction

        # Apply multipliers (icon, MA, sentiment)
        order_notional = base_notional * icon_mult * ma_ratio * sent_mult

        # Cap to remaining funds
        order_notional = min(order_notional, remaining_funds)

        if order_notional < MIN_ORDER_NOTIONAL:
            print(
                f"Row {idx} ({symbol}): calculated order notional {order_notional:.4f} "
                f"< MIN_ORDER_NOTIONAL ({MIN_ORDER_NOTIONAL}), skipping."
            )
            continue

        # Compute amount in base asset to buy
        amount_base = order_notional / price

        # Kraken symbol format: e.g. "ETH/USD"
        market_symbol = f"{symbol}/{BASE_CURRENCY}"

        print(
            f"Row {idx} ({symbol}): price={price}, pct_down={pct_down}, "
            f"tier_fraction={tier_fraction}, icon={icon}, icon_mult={icon_mult}, "
            f"ma_ratio={ma_ratio:.4f}, sent_mult={sent_mult}, "
            f"order_notional={order_notional:.4f} {BASE_CURRENCY}, "
            f"amount={amount_base:.8f} {symbol}, "
            f"market_symbol={market_symbol}"
        )

        # Place live market buy order
        try:
            order = exchange.create_market_buy_order(market_symbol, amount_base)
            remaining_funds -= order_notional
            orders_placed.append({
                "row": idx,
                "symbol": symbol,
                "market_symbol": market_symbol,
                "notional": order_notional,
                "amount": amount_base,
                "order_id": order.get("id"),
            })
            print(
                f"Row {idx} ({symbol}): order placed, id={order.get('id')}, "
                f"spent={order_notional:.4f} {BASE_CURRENCY}, "
                f"remaining_funds={remaining_funds:.4f} {BASE_CURRENCY}"
            )
        except ccxt.BaseError as e:
            print(f"Row {idx} ({symbol}): failed to place order: {e}")
            # On failure, do NOT reduce remaining_funds (since no funds were spent)
            continue

    print("\nRun complete.")
    print(f"Total orders placed: {len(orders_placed)}")
    for o in orders_placed:
        print(
            f"  Row {o['row']} {o['market_symbol']}: "
            f"amount={o['amount']:.8f}, notional={o['notional']:.4f} {BASE_CURRENCY}, "
            f"id={o['order_id']}"
        )


if __name__ == "__main__":
    main()
