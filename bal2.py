#!/usr/bin/env python3

import time
import hmac
import hashlib
import base64
import requests
from decimal import Decimal, InvalidOperation


BASE_URL = "https://api.bitget.com"

API_FILE = "api.txt"

# Classic Account
ASSET_PATH = "/api/v2/spot/account/assets"
TICKER_PATH = "/api/v2/spot/market/tickers"


# ============================================================
# LOAD API
# ============================================================

def load_api():

    try:
        with open(API_FILE, "r", encoding="utf-8") as f:
            lines = [
                line.strip()
                for line in f
                if line.strip()
            ]

    except FileNotFoundError:
        print(f"❌ {API_FILE} tidak ditemukan")
        raise SystemExit(1)

    if len(lines) < 3:
        print("❌ Format api.txt salah")
        print()
        print("Format:")
        print("API_KEY")
        print("SECRET_KEY")
        print("PASSPHRASE")
        raise SystemExit(1)

    return lines[0], lines[1], lines[2]


# ============================================================
# HMAC SIGNATURE
# ============================================================

def make_signature(
    timestamp,
    method,
    path,
    query="",
    body=""
):

    message = (
        timestamp
        + method.upper()
        + path
        + query
        + body
    )

    digest = hmac.new(
        SECRET_KEY.encode("utf-8"),
        message.encode("utf-8"),
        hashlib.sha256
    ).digest()

    return base64.b64encode(digest).decode("utf-8")


# ============================================================
# GET SPOT ASSETS
# ============================================================

def get_assets():

    timestamp = str(
        int(time.time() * 1000)
    )

    method = "GET"
    path = ASSET_PATH

    signature = make_signature(
        timestamp,
        method,
        path
    )

    headers = {
        "ACCESS-KEY": API_KEY,
        "ACCESS-SIGN": signature,
        "ACCESS-TIMESTAMP": timestamp,
        "ACCESS-PASSPHRASE": PASSPHRASE,
        "Content-Type": "application/json",
        "locale": "en-US",
    }

    try:

        response = requests.get(
            BASE_URL + path,
            headers=headers,
            timeout=15
        )

        return response

    except requests.exceptions.RequestException as e:

        print("❌ Koneksi Bitget gagal:")
        print(e)

        raise SystemExit(1)


# ============================================================
# GET MARKET TICKERS
# ============================================================

def get_tickers():

    try:

        response = requests.get(
            BASE_URL + TICKER_PATH,
            timeout=15
        )

        if response.status_code != 200:

            print(
                "❌ Market API HTTP:",
                response.status_code
            )

            return {}

        data = response.json()

    except Exception as e:

        print("❌ Gagal mengambil harga:")
        print(e)

        return {}

    if data.get("code") != "00000":

        print("❌ Market API Error:")
        print(data)

        return {}

    tickers = {}

    for item in data.get("data", []):

        symbol = item.get("symbol")

        last_price = item.get("lastPr", "0")

        if symbol:

            tickers[symbol] = last_price

    return tickers


# ============================================================
# DECIMAL
# ============================================================

def decimal(value):

    try:

        return Decimal(
            str(value or "0")
        )

    except (
        InvalidOperation,
        ValueError
    ):

        return Decimal("0")


# ============================================================
# FORMAT
# ============================================================

def fmt(value, digits=8):

    value = decimal(value)

    if value == 0:

        return "0"

    text = f"{value:.{digits}f}"

    text = text.rstrip("0").rstrip(".")

    return text


def money(value):

    value = decimal(value)

    return f"{value:,.2f}"


# ============================================================
# FIND USDT PRICE
# ============================================================

def get_usdt_price(coin, tickers):

    coin = coin.upper()

    # USDT selalu 1 USDT
    if coin == "USDT":

        return Decimal("1")

    symbol = coin + "USDT"

    price = tickers.get(symbol)

    if price is not None:

        price = decimal(price)

        if price > 0:

            return price

    return None


# ============================================================
# MAIN
# ============================================================

def main():

    global API_KEY
    global SECRET_KEY
    global PASSPHRASE

    API_KEY, SECRET_KEY, PASSPHRASE = load_api()

    print("🔐 Bitget HMAC")
    print("📡 Checking Classic Spot Account...")

    # --------------------------------------------------------
    # SALDO
    # --------------------------------------------------------

    response = get_assets()

    print()
    print("HTTP:", response.status_code)

    try:

        data = response.json()

    except ValueError:

        print("❌ Response bukan JSON")
        print(response.text)

        return

    if data.get("code") != "00000":

        print("❌ Bitget Error")
        print("Code :", data.get("code"))
        print("Msg  :", data.get("msg"))

        return

    print("✅ API berhasil diautentikasi")

    assets = data.get("data", [])

    # --------------------------------------------------------
    # HARGA
    # --------------------------------------------------------

    print("📊 Mengambil harga market...")

    tickers = get_tickers()

    if not tickers:

        print("❌ Harga market tidak tersedia")
        return

    # --------------------------------------------------------
    # PORTFOLIO
    # --------------------------------------------------------

    print()
    print("=" * 78)
    print("💰 BITGET SPOT PORTFOLIO")
    print("=" * 78)

    print(
        f"{'COIN':<8}"
        f"{'QTY':>20}"
        f"{'PRICE USDT':>20}"
        f"{'VALUE USDT':>20}"
    )

    print("-" * 78)

    total_usdt = Decimal("0")

    count = 0

    for asset in assets:

        if not isinstance(asset, dict):
            continue

        coin = asset.get(
            "coin",
            "?"
        )

        available = decimal(
            asset.get(
                "available",
                "0"
            )
        )

        frozen = decimal(
            asset.get(
                "frozen",
                "0"
            )
        )

        locked = decimal(
            asset.get(
                "locked",
                "0"
            )
        )

        quantity = (
            available
            + frozen
            + locked
        )

        # Tidak tampilkan coin kosong
        if quantity <= 0:
            continue

        count += 1

        price = get_usdt_price(
            coin,
            tickers
        )

        # Coin tidak punya pair USDT
        if price is None:

            print(
                f"{coin:<8}"
                f"{fmt(quantity):>20}"
                f"{'N/A':>20}"
                f"{'N/A':>20}"
            )

            continue

        value = quantity * price

        total_usdt += value

        print(
            f"{coin:<8}"
            f"{fmt(quantity):>20}"
            f"{fmt(price, 8):>20}"
            f"{money(value):>20}"
        )

    # --------------------------------------------------------
    # TOTAL
    # --------------------------------------------------------

    print("-" * 78)

    print(
        f"{'TOTAL':<8}"
        f"{'':>20}"
        f"{'':>20}"
        f"{money(total_usdt):>20}"
    )

    print("=" * 78)

    print(
        f"🪙 Total coin : {count}"
    )

    print(
        f"💵 Total USDT : {money(total_usdt)}"
    )

    print("=" * 78)


# ============================================================
# RUN
# ============================================================

if __name__ == "__main__":

    main()
