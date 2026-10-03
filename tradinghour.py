#!/usr/bin/env python3

import json
import sys
from datetime import datetime, timezone

import requests


# ============================================================
# FILE CONFIG
# ============================================================

API_FILE = "api.txt"
CONFIG_FILE = "config.json"
MESSAGES_FILE = "messageshour.json"

BASE_URL = "https://api.bitget.com"


# ============================================================
# LOAD API.TXT
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
        print()
        print("Format:")
        print("API_KEY")
        print("SECRET_KEY")
        print("PASSPHRASE")
        sys.exit(1)

    return {
        "api_key": lines[0],
        "secret_key": lines[1],
        "passphrase": lines[2]
    }


# ============================================================
# LOAD JSON
# ============================================================

def load_json(filename):
    try:
        with open(filename, "r", encoding="utf-8") as f:
            return json.load(f)

    except FileNotFoundError:
        print(f"❌ File {filename} tidak ditemukan")
        sys.exit(1)

    except json.JSONDecodeError as e:
        print(f"❌ JSON {filename} rusak:")
        print(e)
        sys.exit(1)


# ============================================================
# BITGET CANDLE
# ============================================================

def get_candles(symbol, limit=100):
    """
    Mengambil candle Spot Bitget.

    Daily:
        1day

    Response:
        [
            timestamp,
            open,
            high,
            low,
            close,
            base_volume,
            quote_volume
        ]
    """

    url = f"{BASE_URL}/api/v2/spot/market/candles"

    params = {
        "symbol": symbol,
        "granularity": "1h",
        "limit": str(limit)
    }

    try:
        response = requests.get(
            url,
            params=params,
            timeout=15
        )

    except requests.RequestException as e:
        print(f"❌ Gagal koneksi Bitget: {e}")
        sys.exit(1)

    if response.status_code != 200:
        print(f"❌ HTTP Error: {response.status_code}")
        print(response.text)
        sys.exit(1)

    try:
        result = response.json()
    except ValueError:
        print("❌ Response Bitget bukan JSON")
        print(response.text)
        sys.exit(1)

    if result.get("code") != "00000":
        print("❌ Bitget API error")
        print(result)
        sys.exit(1)

    data = result.get("data", [])

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
            "quote_volume": float(row[6])
        })

    # Bitget biasanya memberikan data terbaru lebih dulu.
    # Kita ubah menjadi oldest -> newest.
    candles.sort(key=lambda x: x["timestamp"])

    return candles


# ============================================================
# FILTER CANDLE DAILY YANG SUDAH CLOSE
# ============================================================

def remove_open_candle(candles):
    """
    Candle daily terakhir bisa masih berjalan.
    Candle daily = 1 hari.

    Jika candle terakhir belum selesai, buang.
    """

    if not candles:
        return candles

    now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)

    last = candles[-1]

    hour_ms = 60 * 60 * 1000

    candle_end = last["timestamp"] + hour_ms

    if candle_end > now_ms:
        return candles[:-1]

    return candles


# ============================================================
# EMA
# ============================================================

def calculate_ema(values, period):
    if len(values) < period:
        return None

    multiplier = 2 / (period + 1)

    # SMA awal
    ema = sum(values[:period]) / period

    for price in values[period:]:
        ema = ((price - ema) * multiplier) + ema

    return ema


# ============================================================
# RSI
# ============================================================

def calculate_rsi(values, period=14):
    if len(values) < period + 1:
        return None

    gains = []
    losses = []

    for i in range(1, len(values)):
        change = values[i] - values[i - 1]

        if change > 0:
            gains.append(change)
            losses.append(0)
        else:
            gains.append(0)
            losses.append(abs(change))

    # Initial average
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period

    for i in range(period, len(gains)):
        avg_gain = (
            (avg_gain * (period - 1)) + gains[i]
        ) / period

        avg_loss = (
            (avg_loss * (period - 1)) + losses[i]
        ) / period

    if avg_loss == 0:
        return 100.0

    rs = avg_gain / avg_loss

    return 100 - (100 / (1 + rs))


# ============================================================
# FORMAT PRICE
# ============================================================

def price_format(value):
    if value >= 1000:
        return f"{value:,.2f}"

    if value >= 1:
        return f"{value:,.3f}"

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

    rsi = calculate_rsi(
        closes,
        rsi_period
    )

    ema_fast = calculate_ema(
        closes,
        ema_fast_period
    )

    ema_slow = calculate_ema(
        closes,
        ema_slow_period
    )

    # --------------------------------------------------------
    # Average volume
    # --------------------------------------------------------

    volume_period = int(
        entry_config.get("volume_period", 20)
    )

    volume_multiplier = float(
        entry_config.get("volume_multiplier", 1.0)
    )

    if len(volumes) > volume_period:
        previous_volumes = volumes[-volume_period-1:-1]

        avg_volume = (
            sum(previous_volumes) /
            len(previous_volumes)
        )

    else:
        avg_volume = sum(volumes[:-1]) / max(
            len(volumes[:-1]), 1
        )

    # Volume ratio terhadap rata-rata volume sebelumnya
    volume_ratio = (
        current["volume"] / avg_volume
        if avg_volume > 0
        else 0
    )

    # --------------------------------------------------------
    # SCORE
    # --------------------------------------------------------

    score = 0
    conditions = []

    # ========================================================
    # CONDITION 1
    # EMA TREND
    # ========================================================

    ema_bullish = False

    if ema_fast is not None and ema_slow is not None:

        if ema_fast > ema_slow:
            ema_bullish = True
            score += 1
            conditions.append(
                ("EMA trend", True, "Bullish")
            )
        else:
            conditions.append(
                ("EMA trend", False, "Bearish")
            )

    # ========================================================
    # CONDITION 2
    # RSI
    # ========================================================

    rsi_min = float(
        entry_config["rsi_min"]
    )

    rsi_max = float(
        entry_config["rsi_max"]
    )

    rsi_good = False

    if rsi is not None:

        if rsi_min <= rsi <= rsi_max:
            rsi_good = True
            score += 1

            conditions.append(
                ("RSI", True, "Area entry")
            )

        else:
            conditions.append(
                ("RSI", False, "Di luar area entry")
            )

    # ========================================================
    # CONDITION 3
    # PRICE VS EMA FAST
    # ========================================================

    price_above_ema = bool(
        entry_config.get(
            "price_above_ema",
            True
        )
    )

    price_condition = False

    if ema_fast is not None:

        if price_above_ema:
            price_condition = price > ema_fast
        else:
            price_condition = price < ema_fast

        if price_condition:
            score += 1

        conditions.append(
            (
                "Price / EMA",
                price_condition,
                "Sesuai"
                if price_condition
                else "Tidak sesuai"
            )
        )

    # ========================================================
    # CONDITION 4
    # DAILY CANDLE
    # ========================================================

    candle_bullish = (
        current["close"] > current["open"]
    )

    if candle_bullish:
        score += 1

    conditions.append(
        (
            "1H candle",
            candle_bullish,
            "Bullish"
            if candle_bullish
            else "Bearish"
        )
    )

    # ========================================================
    # CONDITION 5
    # VOLUME
    # ========================================================

    volume_good = (
        current["volume"]
        >= avg_volume * volume_multiplier
    )

    if volume_good:
        score += 1

    conditions.append(
        (
            "Volume",
            volume_good,
            "Mendukung"
            if volume_good
            else "Rendah"
        )
    )

    # ========================================================
    # ENTRY LEVEL
    # ========================================================

    strong_score = int(
        entry_config.get(
            "strong_score",
            5
        )
    )

    normal_score = int(
        entry_config.get(
            "normal_score",
            4
        )
    )

    wait_score = int(
        entry_config.get(
            "wait_score",
            3
        )
    )

    if score >= strong_score:
        signal = "strong"

    elif score >= normal_score:
        signal = "normal"

    elif score >= wait_score:
        signal = "wait"

    else:
        signal = "avoid"

    # ========================================================
    # MARKET STATUS
    # ========================================================

    market_status = []

    # RSI status
    if rsi is not None:
        if rsi >= 70:
            market_status.append(("rsi_overbought", "explanation", "overbought"))
        elif rsi >= 55:
            market_status.append(("rsi_momentum", "market", ""))
            market_status.append(("high_rsi", "explanation", ""))
        elif rsi >= rsi_min:
            market_status.append(("rsi_entry", "market", ""))
            market_status.append(("entry_zone", "explanation", ""))
        else:
            market_status.append(("rsi_entry", "market", ""))

    # EMA status
    if ema_fast is not None and ema_slow is not None:
        if ema_fast > ema_slow:
            market_status.append(("ema_bullish", "market", ""))
            market_status.append(("bullish_trend", "explanation", ""))
        else:
            market_status.append(("ema_bearish", "market", ""))
            market_status.append(("bearish_trend", "explanation", ""))

    # Price vs EMA
    if ema_fast is not None:
        distance_pct = (
            (price - ema_fast) / ema_fast
        ) * 100

        if price > ema_fast:
            if distance_pct >= 15:
                market_status.append(
                    ("price_far_above_ema", "market", "")
                )
                market_status.append(
                    ("price_far_above_ema", "explanation", "")
                )
            else:
                market_status.append(
                    ("price_above_ema", "market", "")
                )
        else:
            market_status.append(
                ("price_below_ema", "market", "")
            )

    # Candle
    if candle_bullish:
        market_status.append(
            ("bullish_candle", "market", "")
        )
    else:
        market_status.append(
            ("bearish_candle", "market", "")
        )

    # Volume
    if volume_ratio >= 1.2:
        market_status.append(
            ("volume_strong", "market", "")
        )
        market_status.append(
            ("strong_volume", "explanation", "")
        )
    elif volume_ratio >= 0.8:
        market_status.append(
            ("volume_normal", "market", "")
        )
    else:
        market_status.append(
            ("volume_weak", "market", "")
        )
        market_status.append(
            ("weak_volume", "explanation", "")
        )

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
        "market_status": market_status,
        "candle": current
    }


# ============================================================
# PRINT RESULT
# ============================================================

def print_result(symbol, analysis, messages):

    print()
    print("═" * 50)
    print(f"        {symbol} 1H ANALYSIS")
    print("═" * 50)

    candle = analysis["candle"]

    dt = datetime.fromtimestamp(
        candle["timestamp"] / 1000,
        tz=timezone.utc
    )

    print(
        f"1H candle     : "
        f"{dt.strftime('%Y-%m-%d')} UTC"
    )

    print()

    print(
        f"Harga         : "
        f"${price_format(analysis['price'])}"
    )

    print(
        f"RSI 14        : "
        f"{analysis['rsi']:.2f}"
    )

    print(
        f"EMA Fast      : "
        f"${price_format(analysis['ema_fast'])}"
    )

    print(
        f"EMA Slow      : "
        f"${price_format(analysis['ema_slow'])}"
    )

    print()

    print(
        f"Volume        : "
        f"{analysis['volume']:,.2f}"
    )

    print(
        f"Avg Volume    : "
        f"{analysis['avg_volume']:,.2f}"
    )

    volume_ratio = (
        analysis["volume"] /
        analysis["avg_volume"]
        if analysis["avg_volume"] > 0
        else 0
    )

    print(
        f"Volume Ratio  : "
        f"{volume_ratio:.2f}x"
    )

    print()
    print("INDICATORS")
    print("-" * 50)

    for name, good, status in analysis["conditions"]:

        icon = "✅" if good else "❌"

        print(
            f"{icon} {name:<15} : {status}"
        )

    print()

    print(
        f"SCORE         : "
        f"{analysis['score']}/{analysis['max_score']}"
    )

    print()

    signal = analysis["signal"]

    try:
        message = messages["entry"][signal]
    except KeyError:
        message = signal

    print(
        f"SIGNAL        : {message}"
    )

    # ========================================================
    # MARKET STATUS
    # ========================================================

    print()
    print("MARKET STATUS")
    print("-" * 50)

    for key, category, _ in analysis["market_status"]:

        if category != "market":
            continue

        try:
            text = messages["market"][key]
        except KeyError:
            continue

        print(text)

    # ========================================================
    # EXPLANATION
    # ========================================================

    print()
    print("EXPLANATION")
    print("-" * 50)

    explanations = []

    for key, category, _ in analysis["market_status"]:

        if category != "explanation":
            continue

        try:
            text = messages["explanation"][key]
        except KeyError:
            continue

        if text not in explanations:
            explanations.append(text)

    for text in explanations:
        print(f"• {text}")

    print("═" * 50)
    print()


# ============================================================
# MAIN
# ============================================================

def main():

    print()
    print("📊 Bitget 1H Trading Analyzer")
    print("   SOLUSDT")
    print()

    # Load API
    # Credential hanya divalidasi.
    # Endpoint market candle adalah public API.
    load_api()

    config = load_json(CONFIG_FILE)
    messages = load_json(MESSAGES_FILE)

    symbol = config.get(
        "symbol",
        "SOLUSDT"
    )

    limit = int(
        config.get(
            "candle_limit",
            100
        )
    )

    print(
        f"🌐 Mengambil data {symbol} dari Bitget..."
    )

    candles = get_candles(
        symbol,
        limit
    )

    if config.get(
        "use_closed_candle",
        True
    ):
        candles = remove_open_candle(
            candles
        )

    # Minimum data
    required = max(
        int(config["indicators"]["ema_slow"]),
        int(config["indicators"]["rsi_period"]) + 1,
        20
    )

    if len(candles) < required:
        print(
            f"❌ Data candle tidak cukup."
        )
        print(
            f"   Diperlukan minimal {required}"
        )
        print(
            f"   Tersedia {len(candles)}"
        )
        sys.exit(1)

    analysis = analyze(
        candles,
        config
    )

    print_result(
        symbol,
        analysis,
        messages
    )


if __name__ == "__main__":
    main()
