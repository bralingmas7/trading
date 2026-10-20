
#!/usr/bin/env python3

import requests

from rich.console import Console
from rich.table import Table
from rich.prompt import Prompt
from rich import box

BASE_URL = "https://api.bitget.com"
console = Console()
def get_day_stats(symbol):
    url = f"{BASE_URL}/api/v2/spot/market/tickers"

    response = requests.get(
        url,
        params={"symbol": symbol},
        timeout=15
    )
    response.raise_for_status()
    result = response.json()

    if result.get("code") != "00000":
        raise RuntimeError(result.get("msg", "Ticker API error"))

    data = result.get("data", [])
    if not data:
        raise RuntimeError(f"Ticker {symbol} tidak ditemukan")

    ticker = data[0]

    utc_now = datetime.now(timezone.utc)
    utc_midnight = utc_now.replace(
        hour=0, minute=0, second=0, microsecond=0
    )

    candle_url = f"{BASE_URL}/api/v2/spot/market/candles"
    candle_response = requests.get(
        candle_url,
        params={
            "symbol": symbol,
            "granularity": "1h",
            "startTime": str(int(utc_midnight.timestamp() * 1000)),
            "endTime": str(int(utc_now.timestamp() * 1000)),
            "limit": "24",
        },
        timeout=15
    )
    candle_response.raise_for_status()
    candle_result = candle_response.json()

    if candle_result.get("code") != "00000":
        raise RuntimeError(
            candle_result.get("msg", "Candle API error")
        )

    candles = candle_result.get("data", [])
    if not candles:
        raise RuntimeError("Data candle UTC hari ini kosong")

    return {
        "low": min(float(candle[3]) for candle in candles),
        "high": max(float(candle[2]) for candle in candles),
        "change": float(ticker["changeUtc24h"]) * 100,
    }


def get_candles(symbol, limit=24):
    url = f"{BASE_URL}/api/v2/spot/market/candles"

    params = {
        "symbol": symbol,
        "granularity": "1h",
        "limit": str(limit),
    }

    response = requests.get(url, params=params, timeout=15)
    response.raise_for_status()

    result = response.json()

    if result.get("code") != "00000":
        raise RuntimeError(result.get("msg", "API error"))

    return result.get("data", [])





def main():
    coin = Prompt.ask(
        "Masukkan ticker coin",
        default="BTC"
    ).strip().upper()

    symbol = coin if coin.endswith("USDT") else coin + "USDT"

    try:
        candles = get_candles(symbol)

        if not candles:
            console.print("[red]Data candle kosong.[/red]")
            return
        day = get_day_stats(symbol)

        # Urutkan dari waktu paling lama ke paling baru
        candles.sort(key=lambda row: int(row[0]))



        day_color = "green" if day["change"] >= 0 else "red"

        table = Table(
            title=(
                f"{symbol} | Candle 1 Jam\n"
                f"Low 24h: {day['low']:.8f} | "
                f"High 24h: {day['high']:.8f} | "
                f"[{day_color}]Perubahan 24h: "
                f"{day['change']:+.2f}%[/{day_color}]"
            ),
            box=box.SIMPLE_HEAVY,
            header_style="bold cyan"
        )
        table.add_column("Waktu", style="white")
        table.add_column("Open", justify="right")
        table.add_column("Close", justify="right")
        table.add_column("Perubahan %", justify="right")

        for candle in candles:
            timestamp = int(candle[0]) / 1000
            open_price = float(candle[1])
            close_price = float(candle[4])

            if open_price <= 0:
                continue

            change = (
                (close_price - open_price)
                / open_price
            ) * 100

            color = "green" if close_price >= open_price else "red"

            waktu = datetime.fromtimestamp(timestamp).strftime(
                "%d-%m %H:%M"
            )

            table.add_row(
                waktu,
                f"{open_price:.8f}".rstrip("0").rstrip("."),
                f"{close_price:.8f}".rstrip("0").rstrip("."),
                f"{change:+.2f}%",
                style=color
            )

        console.print()
        console.print(table)
        console.print(
            "[dim]Waktu mengikuti zona waktu perangkat.[/dim]"
        )

    except requests.RequestException as exc:
        console.print(f"[red]Koneksi API gagal: {exc}[/red]")
    except (ValueError, IndexError, TypeError) as exc:
        console.print(f"[red]Format data tidak valid: {exc}[/red]")
    except RuntimeError as exc:
        console.print(f"[red]Bitget API: {exc}[/red]")


if __name__ == "__main__":
    main()

