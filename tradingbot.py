#!/usr/bin/env python3
"""
Bitget 1H Trading Bot
Signal → Confirm Buy → Monitor Fill → Sell +1% → Monitor Sell
"""

import json
import sys
import time
import hmac
import base64
import hashlib
import uuid
from datetime import datetime, timezone
from urllib.parse import urlencode

import requests

# ============================================================
# FILE CONFIG
# ============================================================

API_FILE = "api.txt"
CONFIG_FILE = "config.json"
MESSAGES_FILE = "messageshour.json"

BASE_URL = "https://api.bitget.com"

# Fee default (bisa override di config)
DEFAULT_TAKER_FEE = 0.001   # 0.1%
DEFAULT_MAKER_FEE = 0.001

TP_PERCENT = 0.01           # +1%
POLL_INTERVAL = 2           # detik
MAX_POLL = 300              # max \~10 menit

# ============================================================
# LOAD FILES
# ============================================================

def load_api():
    try:
        with open(API_FILE, "r", encoding="utf-8") as f:
            lines = [x.strip() for x in f if x.strip()]
    except FileNotFoundError:
        print(f"❌ File {API_FILE} tidak ditemukan")
        sys.exit(1)

    if len(lines) < 3:
        print("❌ Format api.txt salah")
        print("Format:\nAPI_KEY\nSECRET_KEY\nPASSPHRASE")
        sys.exit(1)

    return {
        "api_key": lines[0],
        "secret_key": lines[1],
        "passphrase": lines[2],
    }

def load_json(filename):
    try:
        with open(filename, "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        print(f"❌ File {filename} tidak ditemukan")
        sys.exit(1)
    except json.JSONDecodeError as e:
        print(f"❌ JSON {filename} rusak: {e}")
        sys.exit(1)

# ============================================================
# BITGET SIGNED REQUEST
# ============================================================

def _sign(secret_key, timestamp, method, request_path, query_string="", body=""):
    if query_string:
        message = f"{timestamp}{method}{request_path}?{query_string}{body}"
    else:
        message = f"{timestamp}{method}{request_path}{body}"

    mac = hmac.new(
        secret_key.encode("utf-8"),
        message.encode("utf-8"),
        hashlib.sha256,
    )
    return base64.b64encode(mac.digest()).decode("utf-8")

def private_request(api, method, path, params=None, body=None):
    timestamp = str(int(time.time() * 1000))
    method = method.upper()

    query_string = ""
    if params:
        query_string = urlencode(params)

    body_str = ""
    if body is not None:
        body_str = json.dumps(body)

    sign = _sign(
        api["secret_key"],
        timestamp,
        method,
        path,
        query_string,
        body_str,
    )

    headers = {
        "ACCESS-KEY": api["api_key"],
        "ACCESS-SIGN": sign,
        "ACCESS-PASSPHRASE": api["passphrase"],
        "ACCESS-TIMESTAMP": timestamp,
        "Content-Type": "application/json",
        "locale": "en-US",
    }

    url = BASE_URL + path
    if query_string:
        url += "?" + query_string

    try:
        if method == "GET":
            resp = requests.get(url, headers=headers, timeout=15)
        elif method == "POST":
            resp = requests.post(url, headers=headers, data=body_str, timeout=15)
        else:
            raise ValueError(f"Method tidak didukung: {method}")
    except requests.RequestException as e:
        print(f"❌ Request error: {e}")
        return None

    try:
        result = resp.json()
    except ValueError:
        print(f"❌ Response bukan JSON: {resp.text}")
        return None

    if result.get("code") != "00000":
        print(f"❌ API error: {result}")
        return None

    return result.get("data")

def public_get(path, params=None):
    url = BASE_URL + path
    try:
        resp = requests.get(url, params=params, timeout=15)
    except requests.RequestException as e:
        print(f"❌ Koneksi gagal: {e}")
        sys.exit(1)

    if resp.status_code != 200:
        print(f"❌ HTTP {resp.status_code}: {resp.text}")
        sys.exit(1)

    try:
        result = resp.json()
    except ValueError:
        print("❌ Response bukan JSON")
        sys.exit(1)

    if result.get("code") != "00000":
        print(f"❌ API error: {result}")
        sys.exit(1)

    return result.get("data")

# ============================================================
# MARKET DATA
# ============================================================

def get_candles(symbol, limit=100):
    data = public_get(
        "/api/v2/spot/market/candles",
        {
            "symbol": symbol,
            "granularity": "1h",
            "limit": str(limit),
        },
    )

    if not data:
        print("❌ Tidak ada data candle")
        sys.exit(1)

    candles = []
    for row in data:
        if len(row) < 7:
            continue
        candles.append({
            "timestamp": int(row[0]),
            "open": float(row[1]),
            "high": float(row[2]),
            "low": float(row[3]),
            "close": float(row[4]),
            "volume": float(row[5]),
            "quote_volume": float(row[6]),
        })

    candles.sort(key=lambda x: x["timestamp"])
    return candles

def remove_open_candle(candles):
    if not candles:
        return candles

    now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    last = candles[-1]
    hour_ms = 60 * 60 * 1000
    candle_end = last["timestamp"] + hour_ms

    if candle_end > now_ms:
        return candles[:-1]
    return candles

def get_best_ask(symbol):
    data = public_get(
        "/api/v2/spot/market/orderbook",
        {"symbol": symbol, "type": "step0", "limit": "5"},
    )
    asks = data.get("asks") or []
    if not asks:
        print("❌ Orderbook kosong")
        sys.exit(1)
    return float(asks[0][0]), float(asks[0][1])

def get_symbol_info(symbol):
    data = public_get(
        "/api/v2/spot/public/symbols",
        {"symbol": symbol},
    )
    if not data:
        print(f"❌ Symbol {symbol} tidak ditemukan")
        sys.exit(1)
    info = data[0]
    return {
        "price_precision": int(info.get("pricePrecision", 4)),
        "qty_precision": int(info.get("quantityPrecision", 4)),
        "min_trade_usdt": float(info.get("minTradeUSDT", 1)),
        "taker_fee": float(info.get("takerFeeRate", DEFAULT_TAKER_FEE)),
        "maker_fee": float(info.get("makerFeeRate", DEFAULT_MAKER_FEE)),
    }

# ============================================================
# ORDER
# ============================================================

def place_order(api, symbol, side, order_type, size, price=None, force="gtc"):
    body = {
        "symbol": symbol,
        "side": side,
        "orderType": order_type,
        "size": str(size),
        "clientOid": str(uuid.uuid4()).replace("-", "")[:32],
    }

    if order_type == "limit":
        body["price"] = str(price)
        body["force"] = force

    data = private_request(
        api,
        "POST",
        "/api/v2/spot/trade/place-order",
        body=body,
    )
    return data

def get_order_info(api, symbol, order_id):
    data = private_request(
        api,
        "GET",
        "/api/v2/spot/trade/orderInfo",
        params={"symbol": symbol, "orderId": order_id},
    )
    # API kadang return list / dict
    if isinstance(data, list):
        return data[0] if data else None
    return data

def wait_until_filled(api, symbol, order_id, label="Order"):
    print(f"\n⏳ Monitor {label} ...")
    print(f"   Order ID: {order_id}")

    for i in range(MAX_POLL):
        info = get_order_info(api, symbol, order_id)
        if not info:
            time.sleep(POLL_INTERVAL)
            continue

        status = (info.get("status") or "").lower()
        base_vol = float(info.get("baseVolume") or 0)
        quote_vol = float(info.get("quoteVolume") or 0)
        price_avg = float(info.get("priceAvg") or 0)
        size = float(info.get("size") or 0)

        filled_pct = 0.0
        if size > 0 and base_vol > 0:
            # limit: size = base qty
            filled_pct = min(100.0, (base_vol / size) * 100)
        elif quote_vol > 0 and size > 0 and status == "filled":
            filled_pct = 100.0

        print(
            f"\r   [{i+1}] status={status}  "
            f"filled≈{filled_pct:.1f}%  "
            f"avg={price_avg}  base={base_vol}",
            end="",
            flush=True,
        )

        if status in ("filled", "full_fill"):
            print()
            print(f"✅ {label} 100% filled")
            return {
                "status": status,
                "price_avg": price_avg,
                "base_volume": base_vol,
                "quote_volume": quote_vol,
                "raw": info,
            }

        if status in ("cancelled", "canceled"):
            print()
            print(f"❌ {label} dibatalkan")
            return None

        time.sleep(POLL_INTERVAL)

    print()
    print(f"⚠️ Timeout monitor {label}")
    return None

# ============================================================
# INDICATORS
# ============================================================

def calculate_ema(values, period):
    if len(values) < period:
        return None
    multiplier = 2 / (period + 1)
    ema = sum(values[:period]) / period
    for price in values[period:]:
        ema = ((price - ema) * multiplier) + ema
    return ema

def calculate_rsi(values, period=14):
    if len(values) < period + 1:
        return None

    gains, losses = [], []
    for i in range(1, len(values)):
        change = values[i] - values[i - 1]
        if change > 0:
            gains.append(change)
            losses.append(0)
        else:
            gains.append(0)
            losses.append(abs(change))

    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period

    for i in range(period, len(gains)):
        avg_gain = ((avg_gain * (period - 1)) + gains[i]) / period
        avg_loss = ((avg_loss * (period - 1)) + losses[i]) / period

    if avg_loss == 0:
        return 100.0

    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))

def price_format(value):
    if value >= 1000:
        return f"{value:,.2f}"
    if value >= 1:
        return f"{value:,.4f}"
    return f"{value:.6f}"

# ============================================================
# ANALYSIS
# ============================================================

def analyze(candles, config):
    indicators = config["indicators"]
    entry_config = config["entry"]

    rsi_period = int(indicators["rsi_period"])
    ema_fast_period = int(indicators["ema_fast"])
    ema_slow_period = int(indicators["ema_slow"])

    closes = [x["close"] for x in candles]
    volumes = [x["volume"] for x in candles]
    current = candles[-1]
    price = current["close"]

    rsi = calculate_rsi(closes, rsi_period)
    ema_fast = calculate_ema(closes, ema_fast_period)
    ema_slow = calculate_ema(closes, ema_slow_period)

    volume_period = int(entry_config.get("volume_period", 20))
    volume_multiplier = float(entry_config.get("volume_multiplier", 1.0))

    if len(volumes) > volume_period:
        previous_volumes = volumes[-volume_period - 1:-1]
        avg_volume = sum(previous_volumes) / len(previous_volumes)
    else:
        avg_volume = sum(volumes[:-1]) / max(len(volumes[:-1]), 1)

    volume_ratio = current["volume"] / avg_volume if avg_volume > 0 else 0

    score = 0
    conditions = []

    # 1 EMA trend
    if ema_fast is not None and ema_slow is not None:
        if ema_fast > ema_slow:
            score += 1
            conditions.append(("EMA trend", True, "Bullish"))
        else:
            conditions.append(("EMA trend", False, "Bearish"))

    # 2 RSI
    rsi_min = float(entry_config["rsi_min"])
    rsi_max = float(entry_config["rsi_max"])
    if rsi is not None:
        if rsi_min <= rsi <= rsi_max:
            score += 1
            conditions.append(("RSI", True, "Area entry"))
        else:
            conditions.append(("RSI", False, "Di luar area entry"))

    # 3 Price vs EMA
    price_above_ema = bool(entry_config.get("price_above_ema", True))
    if ema_fast is not None:
        price_condition = price > ema_fast if price_above_ema else price < ema_fast
        if price_condition:
            score += 1
        conditions.append((
            "Price / EMA",
            price_condition,
            "Sesuai" if price_condition else "Tidak sesuai",
        ))

    # 4 Candle
    candle_bullish = current["close"] > current["open"]
    if candle_bullish:
        score += 1
    conditions.append((
        "1H candle",
        candle_bullish,
        "Bullish" if candle_bullish else "Bearish",
    ))

    # 5 Volume
    volume_good = current["volume"] >= avg_volume * volume_multiplier
    if volume_good:
        score += 1
    conditions.append((
        "Volume",
        volume_good,
        "Mendukung" if volume_good else "Rendah",
    ))

    strong_score = int(entry_config.get("strong_score", 5))
    normal_score = int(entry_config.get("normal_score", 4))
    wait_score = int(entry_config.get("wait_score", 3))

    if score >= strong_score:
        signal = "strong"
    elif score >= normal_score:
        signal = "normal"
    elif score >= wait_score:
        signal = "wait"
    else:
        signal = "avoid"

    return {
        "price": price,
        "rsi": rsi,
        "ema_fast": ema_fast,
        "ema_slow": ema_slow,
        "volume": current["volume"],
        "avg_volume": avg_volume,
        "volume_ratio": volume_ratio,
        "score": score,
        "max_score": 5,
        "signal": signal,
        "conditions": conditions,
        "candle": current,
    }

def print_analysis(symbol, analysis, messages):
    print()
    print("═" * 50)
    print(f"        {symbol} 1H ANALYSIS")
    print("═" * 50)

    candle = analysis["candle"]
    dt = datetime.fromtimestamp(candle["timestamp"] / 1000, tz=timezone.utc)
    print(f"1H candle     : {dt.strftime('%Y-%m-%d %H:%M')} UTC")
    print()
    print(f"Harga         : ${price_format(analysis['price'])}")
    print(f"RSI 14        : {analysis['rsi']:.2f}" if analysis["rsi"] else "RSI 14        : -")
    print(f"EMA Fast      : ${price_format(analysis['ema_fast'])}" if analysis["ema_fast"] else "EMA Fast      : -")
    print(f"EMA Slow      : ${price_format(analysis['ema_slow'])}" if analysis["ema_slow"] else "EMA Slow      : -")
    print()
    print(f"Volume        : {analysis['volume']:,.2f}")
    print(f"Avg Volume    : {analysis['avg_volume']:,.2f}")
    print(f"Volume Ratio  : {analysis['volume_ratio']:.2f}x")
    print()
    print("INDICATORS")
    print("-" * 50)
    for name, good, status in analysis["conditions"]:
        icon = "✅" if good else "❌"
        print(f"{icon} {name:<15} : {status}")
    print()
    print(f"SCORE         : {analysis['score']}/{analysis['max_score']}")

    signal = analysis["signal"]
    try:
        message = messages["entry"][signal]
    except KeyError:
        message = signal
    print(f"SIGNAL        : {message}")
    print("═" * 50)
    print()

# ============================================================
# PREVIEW & TRADE FLOW
# ============================================================

def round_qty(qty, precision):
    factor = 10 ** precision
    return int(qty * factor) / factor

def round_price(price, precision):
    factor = 10 ** precision
    return int(price * factor) / factor

def ask_yes_no(prompt):
    while True:
        ans = input(f"{prompt} (y/n): ").strip().lower()
        if ans in ("y", "yes"):
            return True
        if ans in ("n", "no"):
            return False
        print("  Ketik y atau n")

def ask_usdt_amount(min_usdt):
    while True:
        raw = input(f"Nominal USDT (min {min_usdt}): ").strip()
        try:
            amount = float(raw)
            if amount < min_usdt:
                print(f"  Minimal {min_usdt} USDT")
                continue
            return amount
        except ValueError:
            print("  Masukkan angka valid")

def preview_buy(symbol, usdt_amount, best_ask, sym_info, fee_rate):
    qty = round_qty(usdt_amount / best_ask, sym_info["qty_precision"])
    cost = qty * best_ask
    fee_buy = cost * fee_rate
    total_cost = cost + fee_buy

    sell_price = round_price(best_ask * (1 + TP_PERCENT), sym_info["price_precision"])
    sell_gross = qty * sell_price
    fee_sell = sell_gross * fee_rate
    net_receive = sell_gross - fee_sell
    net_profit = net_receive - total_cost
    net_pct = (net_profit / total_cost) * 100 if total_cost > 0 else 0

    print()
    print("═" * 50)
    print("        BUY PREVIEW")
    print("═" * 50)
    print(f"Symbol        : {symbol}")
    print(f"Best Ask      : ${price_format(best_ask)}")
    print(f"Qty           : {qty}")
    print(f"Est. Cost     : ${price_format(cost)}")
    print(f"Fee Buy (\~{fee_rate*100:.2f}%) : ${price_format(fee_buy)}")
    print(f"Total Cost    : ${price_format(total_cost)}")
    print()
    print(f"TP Price (+1%): ${price_format(sell_price)}")
    print(f"Est. Sell     : ${price_format(sell_gross)}")
    print(f"Fee Sell      : ${price_format(fee_sell)}")
    print(f"Net Receive   : ${price_format(net_receive)}")
    print()
    print(f"Net Profit    : ${price_format(net_profit)}  ({net_pct:.3f}%)")
    print("═" * 50)
    print()

    return {
        "qty": qty,
        "best_ask": best_ask,
        "cost": cost,
        "fee_buy": fee_buy,
        "total_cost": total_cost,
        "sell_price": sell_price,
        "fee_rate": fee_rate,
    }

def preview_sell(qty, entry_price, sell_price, fee_rate, total_cost_buy):
    sell_gross = qty * sell_price
    fee_sell = sell_gross * fee_rate
    net_receive = sell_gross - fee_sell
    net_profit = net_receive - total_cost_buy
    net_pct = (net_profit / total_cost_buy) * 100 if total_cost_buy > 0 else 0

    print()
    print("═" * 50)
    print("        SELL PREVIEW (+1%)")
    print("═" * 50)
    print(f"Entry Avg     : ${price_format(entry_price)}")
    print(f"Sell Price    : ${price_format(sell_price)}")
    print(f"Qty           : {qty}")
    print(f"Gross Sell    : ${price_format(sell_gross)}")
    print(f"Fee Sell      : ${price_format(fee_sell)}")
    print(f"Net Receive   : ${price_format(net_receive)}")
    print(f"Total Cost Buy: ${price_format(total_cost_buy)}")
    print()
    print(f"Net Profit    : ${price_format(net_profit)}  ({net_pct:.3f}%)")
    print("═" * 50)
    print()

    return net_profit

def run_trade_flow(api, symbol, config, messages):
    sym_info = get_symbol_info(symbol)
    fee_rate = float(config.get("fee_rate", sym_info["taker_fee"]))

    print(f"📐 Precision  price={sym_info['price_precision']}  qty={sym_info['qty_precision']}")
    print(f"💰 Fee rate   {fee_rate*100:.3f}%")
    print(f"📉 Min USDT   {sym_info['min_trade_usdt']}")

    if not ask_yes_no("\nLanjut ke Confirm Buy?"):
        print("Dibatalkan.")
        return

    usdt_amount = ask_usdt_amount(sym_info["min_trade_usdt"])

    best_ask, ask_size = get_best_ask(symbol)
    print(f"\n📊 Best Ask: ${price_format(best_ask)}  (size {ask_size})")

    preview = preview_buy(symbol, usdt_amount, best_ask, sym_info, fee_rate)

    if preview["qty"] <= 0:
        print("❌ Qty terlalu kecil setelah rounding")
        return

    if not ask_yes_no("Confirm BUY sekarang?"):
        print("Buy dibatalkan.")
        return

    # Place limit buy @ best ask
    print("\n🚀 Place BUY limit @ best ask ...")
    result = place_order(
        api,
        symbol=symbol,
        side="buy",
        order_type="limit",
        size=preview["qty"],
        price=preview["best_ask"],
        force="gtc",
    )

    if not result:
        print("❌ Gagal place buy")
        return

    order_id = result.get("orderId")
    print(f"✅ Buy order placed: {order_id}")

    fill = wait_until_filled(api, symbol, order_id, label="BUY")
    if not fill:
        print("❌ Buy tidak ter-fill / dibatalkan")
        return

    entry_price = fill["price_avg"] or preview["best_ask"]
    filled_qty = fill["base_volume"] or preview["qty"]
    quote_spent = fill["quote_volume"] or (filled_qty * entry_price)

    # Actual cost + fee estimate
    fee_buy_est = quote_spent * fee_rate
    total_cost = quote_spent + fee_buy_est

    print(f"\n📦 Filled qty  : {filled_qty}")
    print(f"   Avg price   : ${price_format(entry_price)}")
    print(f"   Quote spent : ${price_format(quote_spent)}")

    # Sell price +1% dari avg fill
    sell_price = round_price(entry_price * (1 + TP_PERCENT), sym_info["price_precision"])
    preview_sell(filled_qty, entry_price, sell_price, fee_rate, total_cost)

    if not ask_yes_no("Confirm SELL +1% sekarang?"):
        print("Sell dibatalkan. Posisi tetap dipegang.")
        return

    print("\n🚀 Place SELL limit @ +1% ...")
    result = place_order(
        api,
        symbol=symbol,
        side="sell",
        order_type="limit",
        size=filled_qty,
        price=sell_price,
        force="gtc",
    )

    if not result:
        print("❌ Gagal place sell")
        return

    sell_order_id = result.get("orderId")
    print(f"✅ Sell order placed: {sell_order_id}")

    sell_fill = wait_until_filled(api, symbol, sell_order_id, label="SELL")
    if not sell_fill:
        print("⚠️ Sell belum filled / timeout. Cek manual di Bitget.")
        return

    sell_avg = sell_fill["price_avg"] or sell_price
    sell_quote = sell_fill["quote_volume"] or (filled_qty * sell_avg)
    fee_sell_est = sell_quote * fee_rate
    net_receive = sell_quote - fee_sell_est
    net_profit = net_receive - total_cost

    print()
    print("═" * 50)
    print("        TRADE SELESAI")
    print("═" * 50)
    print(f"Entry         : ${price_format(entry_price)}")
    print(f"Exit          : ${price_format(sell_avg)}")
    print(f"Qty           : {filled_qty}")
    print(f"Cost (est)    : ${price_format(total_cost)}")
    print(f"Receive (est) : ${price_format(net_receive)}")
    print(f"Net Profit    : ${price_format(net_profit)}")
    print("═" * 50)
    print()

# ============================================================
# MAIN
# ============================================================

def main():
    print()
    print("📊 Bitget 1H Trading Bot")
    print("   Signal → Buy → Sell +1%")
    print()

    api = load_api()
    config = load_json(CONFIG_FILE)
    messages = load_json(MESSAGES_FILE)

    symbol = config.get("symbol", "SOLUSDT")
    limit = int(config.get("candle_limit", 100))

    print(f"🌐 Mengambil data {symbol} dari Bitget...")

    candles = get_candles(symbol, limit)

    if config.get("use_closed_candle", True):
        candles = remove_open_candle(candles)

    required = max(
        int(config["indicators"]["ema_slow"]),
        int(config["indicators"]["rsi_period"]) + 1,
        20,
    )

    if len(candles) < required:
        print(f"❌ Data candle tidak cukup. Butuh {required}, ada {len(candles)}")
        sys.exit(1)

    analysis = analyze(candles, config)
    print_analysis(symbol, analysis, messages)

    signal = analysis["signal"]

    if signal in ("strong", "normal"):
        print(f"🎯 Signal {signal.upper()} — siap entry")
        run_trade_flow(api, symbol, config, messages)
    else:
        print(f"⏸ Signal = {signal} — tidak ada entry")
        print("   Jalankan lagi nanti setelah candle baru close.")

if __name__ == "__main__":
    main()
