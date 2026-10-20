#!/usr/bin/env python3

import json
import time
import hmac
import base64
import hashlib
import uuid
import requests
from decimal import Decimal, ROUND_DOWN
from urllib.parse import urlencode

API_FILE = "api.txt"
CONFIG_FILE = "config.json"

BASE_URL = "https://api.bitget.com"

DEFAULT_TAKER_FEE = 0.001
TP_PERCENT = 0.01

POLL_INTERVAL = 2
MAX_POLL = 300


# ============================================================
# LOAD
# ============================================================

def load_api():
    with open(API_FILE, "r") as f:
        lines = [x.strip() for x in f.readlines() if x.strip()]

    if len(lines) < 3:
        raise ValueError(
            "api.txt harus berisi API KEY, SECRET KEY, PASSPHRASE"
        )

    return {
        "api_key": lines[0],
        "secret_key": lines[1],
        "passphrase": lines[2],
    }


def load_config():
    try:
        with open(CONFIG_FILE, "r") as f:
            return json.load(f)
    except FileNotFoundError:
        return {
            "symbol": "SOLUSDT"
        }


# ============================================================
# SIGNATURE
# ============================================================

def make_signature(
    secret_key,
    timestamp,
    method,
    request_path,
    body=""
):
    message = (
        f"{timestamp}"
        f"{method.upper()}"
        f"{request_path}"
        f"{body}"
    )

    digest = hmac.new(
        secret_key.encode(),
        message.encode(),
        hashlib.sha256
    ).digest()

    return base64.b64encode(digest).decode()


# ============================================================
# PRIVATE REQUEST
# ============================================================

def private_request(
    api,
    method,
    path,
    params=None,
    body=None
):

    timestamp = str(int(time.time() * 1000))
    method = method.upper()

    if method == "GET":

        query = urlencode(params or {})
        request_path = path

        if query:
            request_path += "?" + query

        body_text = ""

    else:

        request_path = path

        body_text = json.dumps(
            body or {},
            separators=(",", ":")
        )

    sign = make_signature(
        api["secret_key"],
        timestamp,
        method,
        request_path,
        body_text
    )

    headers = {
        "ACCESS-KEY": api["api_key"],
        "ACCESS-SIGN": sign,
        "ACCESS-PASSPHRASE": api["passphrase"],
        "ACCESS-TIMESTAMP": timestamp,
        "Content-Type": "application/json",
        "locale": "en-US",
    }

    try:

        if method == "GET":

            response = requests.get(
                BASE_URL + path,
                headers=headers,
                params=params,
                timeout=15
            )

        else:

            response = requests.post(
                BASE_URL + path,
                headers=headers,
                data=body_text,
                timeout=15
            )

        response.raise_for_status()

        result = response.json()

        if result.get("code") != "00000":

            print(f"❌ API error: {result}")

            return None

        return result.get("data")

    except Exception as e:

        print(f"❌ Request error: {e}")

        return None


# ============================================================
# PUBLIC REQUEST
# ============================================================

def public_get(path, params=None):

    try:

        response = requests.get(
            BASE_URL + path,
            params=params,
            timeout=15
        )

        response.raise_for_status()

        result = response.json()

        if result.get("code") != "00000":

            print(f"❌ API error: {result}")

            return None

        return result.get("data")

    except Exception as e:

        print(f"❌ Request error: {e}")

        return None


# ============================================================
# GET BALANCE
# ============================================================

def get_available_balance(api, coin):

    data = private_request(
        api,
        "GET",
        "/api/v2/spot/account/assets",
        params={
            "coin": coin
        }
    )

    if data is None:
        return None

    if isinstance(data, list):

        for asset in data:

            if asset.get("coin", "").upper() == coin.upper():

                return float(
                    asset.get("available", "0")
                )

        return 0.0

    if isinstance(data, dict):

        if data.get("coin", "").upper() == coin.upper():

            return float(
                data.get("available", "0")
            )

    return 0.0


# ============================================================
# SYMBOL INFO
# ============================================================

def get_symbol_info(symbol):

    data = public_get(
        "/api/v2/spot/public/symbols",
        {
            "symbol": symbol
        }
    )

    if not data:
        return None

    if isinstance(data, list):

        info = data[0] if data else None

    else:

        info = data

    if not info:
        return None

    return {
        "price_precision": int(
            info.get("pricePrecision", 4)
        ),

        "qty_precision": int(
            info.get("quantityPrecision", 4)
        ),

        "min_trade_usdt": float(
            info.get("minTradeUSDT", 1)
        ),

        "taker_fee": float(
            info.get(
                "takerFeeRate",
                DEFAULT_TAKER_FEE
            )
        ),

        "maker_fee": float(
            info.get(
                "makerFeeRate",
                DEFAULT_TAKER_FEE
            )
        ),
    }


# ============================================================
# PLACE ORDER
# ============================================================

def place_order(
    api,
    symbol,
    side,
    order_type,
    size,
    price=None,
    force="gtc"
):

    body = {
        "symbol": symbol,
        "side": side,
        "orderType": order_type,
        "size": str(size),
        "clientOid": str(uuid.uuid4()),
    }

    if order_type == "limit":

        body["price"] = str(price)
        body["force"] = force

    print("\n📤 Sending order...")

    print(
        json.dumps(
            body,
            indent=2
        )
    )

    return private_request(
        api,
        "POST",
        "/api/v2/spot/trade/place-order",
        body=body
    )


# ============================================================
# ORDER INFO
# ============================================================

def get_order_info(
    api,
    symbol,
    order_id
):

    return private_request(
        api,
        "GET",
        "/api/v2/spot/trade/orderInfo",
        params={
            "symbol": symbol,
            "orderId": order_id,
        }
    )


# ============================================================
# ROUNDING
# ============================================================

def floor_qty(qty, precision):

    value = Decimal(str(qty))

    step = Decimal("1") / (
        Decimal("10") ** precision
    )

    return float(
        value.quantize(
            step,
            rounding=ROUND_DOWN
        )
    )


def round_price(price, precision):

    value = Decimal(str(price))

    step = Decimal("1") / (
        Decimal("10") ** precision
    )

    return float(
        value.quantize(
            step,
            rounding=ROUND_DOWN
        )
    )


# ============================================================
# MONITOR SELL
# ============================================================

def monitor_order(
    api,
    symbol,
    order_id
):

    print("\n⏳ Monitoring SELL order...")

    start = time.time()

    while time.time() - start < MAX_POLL:

        data = get_order_info(
            api,
            symbol,
            order_id
        )

        if not data:

            time.sleep(POLL_INTERVAL)

            continue

        if isinstance(data, list):

            data = data[0] if data else {}

        status = data.get(
            "status",
            ""
        ).lower()

        filled = data.get(
            "baseVolume",
            "0"
        )

        print(
            f"\rStatus: {status} | "
            f"Filled: {filled}",
            end="",
            flush=True
        )

        if status in (
            "filled",
            "full_fill",
            "filled_all"
        ):

            print("\n\n✅ SELL FILLED")

            return True

        if status in (
            "cancelled",
            "canceled",
            "rejected",
            "expired"
        ):

            print(
                f"\n\n❌ SELL {status}"
            )

            return False

        time.sleep(POLL_INTERVAL)

    print("\n\n⚠️ Monitoring timeout")

    return False


# ============================================================
# MAIN
# ============================================================

def main():

    print("=" * 55)
    print("💰 BITGET STANDALONE SELL")
    print("=" * 55)

    api = load_api()
    config = load_config()

    default_symbol = config.get(
        "symbol",
        "SOLUSDT"
    )

    symbol_input = input(
        f"\nSymbol [{default_symbol}]: "
    ).strip().upper()

    symbol = (
        symbol_input
        or default_symbol
    )

    # --------------------------------------------------------
    # GET BASE COIN
    # --------------------------------------------------------

    if symbol.endswith("USDT"):

        coin = symbol[:-4]

    else:

        coin = input(
            "\nBase coin untuk SELL "
            f"[contoh: SOL]: "
        ).strip().upper()

    if not coin:

        print("❌ Base coin tidak valid")

        return

    # --------------------------------------------------------
    # SYMBOL INFO
    # --------------------------------------------------------

    print(
        f"\n🔎 Getting symbol info: {symbol}"
    )

    sym_info = get_symbol_info(symbol)

    if not sym_info:

        print(
            "❌ Gagal mendapatkan "
            "symbol info"
        )

        return

    print(
        f"Price precision : "
        f"{sym_info['price_precision']}"
    )

    print(
        f"Qty precision   : "
        f"{sym_info['qty_precision']}"
    )

    print(
        f"Taker fee       : "
        f"{sym_info['taker_fee']}"
    )

    # --------------------------------------------------------
    # GET MAX AVAILABLE BALANCE
    # --------------------------------------------------------

    print(
        f"\n💰 Checking available "
        f"{coin} balance..."
    )

    available_qty = get_available_balance(
        api,
        coin
    )

    if available_qty is None:

        print(
            "❌ Gagal mendapatkan "
            "saldo"
        )

        return

    print(
        f"💰 Available {coin}: "
        f"{available_qty}"
    )

    if available_qty <= 0:

        print(
            f"❌ Tidak ada saldo "
            f"{coin} yang tersedia"
        )

        return

    # --------------------------------------------------------
    # MAX SELL QTY
    # --------------------------------------------------------

    fee_rate = sym_info["taker_fee"]

    if fee_rate <= 0:

        fee_rate = DEFAULT_TAKER_FEE

    max_sell_qty = floor_qty(
        available_qty * (1 - fee_rate),
        sym_info["qty_precision"]
    )

    print(
        f"📦 MAX SELL QTY : "
        f"{max_sell_qty}"
    )

    if max_sell_qty <= 0:

        print(
            "❌ MAX SELL QTY terlalu kecil"
        )

        return

    # --------------------------------------------------------
    # MARKET PRICE / BEST BID
    # --------------------------------------------------------

    best_bid = get_best_bid(symbol)

    if best_bid is None:
        print("❌ Gagal mendapatkan harga best bid")
        return

    print(f"\n📈 Best bid {symbol}: {best_bid}")

    # --------------------------------------------------------
    # SELL MODE
    # --------------------------------------------------------

    print("\nPilih metode jumlah SELL:")
    print("[1] Persentase saldo")
    print("[2] Nilai USDT")
    print("[3] Jumlah coin")

    qty_mode = input("Pilihan [1-3]: ").strip()

    try:
        if qty_mode == "1":
            percent = float(input("Persentase saldo (%): ").strip())

            if not 0 < percent <= 100:
                print("❌ Persentase harus > 0 dan maksimal 100")
                return

            requested_qty = available_qty * percent / 100

        elif qty_mode == "2":
            usdt_amount = float(input("Nilai jual USDT: ").strip())

            if usdt_amount <= 0:
                print("❌ Nilai USDT harus > 0")
                return

            requested_qty = usdt_amount / best_bid

        elif qty_mode == "3":
            requested_qty = float(input(f"Jumlah {coin} yang dijual: ").strip())

            if requested_qty <= 0:
                print("❌ Qty harus > 0")
                return

        else:
            print("❌ Pilihan tidak valid")
            return

    except ValueError:
        print("❌ Input harus berupa angka")
        return

    sell_qty = floor_qty(
        requested_qty,
        sym_info["qty_precision"]
    )

    if sell_qty <= 0:
        print("❌ Qty terlalu kecil untuk precision simbol")
        return

    if sell_qty > available_qty:
        print(f"❌ Qty melebihi saldo tersedia: {available_qty} {coin}")
        return

    # --------------------------------------------------------
    # ORDER TYPE
    # --------------------------------------------------------

    print("\nPilih jenis order:")
    print("[1] Market SELL")
    print("[2] Limit SELL pada best bid")

    order_choice = input("Pilihan [1-2]: ").strip()

    if order_choice == "1":
        order_type = "market"
        order_price = None
        estimated_price = best_bid

    elif order_choice == "2":
        order_type = "limit"
        order_price = round_price(
            best_bid,
            sym_info["price_precision"]
        )
        estimated_price = order_price

    else:
        print("❌ Pilihan order tidak valid")
        return

    sell_value = sell_qty * estimated_price

    # --------------------------------------------------------
    # PREVIEW
    # --------------------------------------------------------

    print("\n" + "=" * 55)
    print("📊 SELL PREVIEW")
    print("=" * 55)
    print(f"Symbol          : {symbol}")
    print(f"Available       : {available_qty} {coin}")
    print(f"Qty SELL        : {sell_qty} {coin}")
    print(f"Order type      : {order_type.upper()}")
    print(f"Best bid        : {best_bid}")
    if order_type == "limit":
        print(f"Limit price     : {order_price}")
    print(f"Estimated value : {sell_value:.6f} USDT")
    print(f"Minimum order   : {sym_info['min_trade_usdt']} USDT")
    print("=" * 55)

    if sell_value < sym_info["min_trade_usdt"]:
        print(
            f"❌ Nilai order {sell_value:.6f} USDT "
            f"di bawah minimum {sym_info['min_trade_usdt']} USDT"
        )
        return

    # --------------------------------------------------------
    # MINIMUM ORDER
    # --------------------------------------------------------

    if sell_value < sym_info["min_trade_usdt"]:

        print(
            f"\n❌ SELL value "
            f"{sell_value:.4f} USDT "
            f"< minimum "
            f"{sym_info['min_trade_usdt']} USDT"
        )

        return

    # --------------------------------------------------------
    # CONFIRM
    # --------------------------------------------------------

    confirm = input(
        f"\n🚨 Konfirmasi SELL {sell_qty} {coin} "
        f"({order_type.upper()})? (y/n): "
    ).strip().lower()

    if confirm != "y":

        print(
            "❌ SELL dibatalkan"
        )

        return

    # --------------------------------------------------------
    # PLACE SELL
    # --------------------------------------------------------

    print(f"\n🚀 Place SELL {order_type.upper()} ...")

    result = place_order(
        api,
        symbol=symbol,
        side="sell",
        order_type=order_type,
        size=sell_qty,
        price=order_price,
        force="gtc",
    )

    if not result:

        print(
            "❌ Gagal place SELL"
        )

        return

    order_id = result.get(
        "orderId"
    )

    print(
        f"\n✅ SELL order placed: "
        f"{order_id}"
    )

    # --------------------------------------------------------
    # MONITOR
    # --------------------------------------------------------

    if order_id:

        monitor_order(
            api,
            symbol,
            order_id
        )


if __name__ == "__main__":
    main()
