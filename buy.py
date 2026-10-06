#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import base64
import hashlib
import hmac
import json
import os
import sys
import time
from decimal import Decimal, InvalidOperation, ROUND_DOWN
from urllib.parse import urlencode

import requests
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.prompt import Prompt, IntPrompt
from rich import box


BASE_URL = "https://api.bitget.com"
API_FILE = "api.txt"
COIN_FILE = "coin.txt"

console = Console()


# ============================================================
# BASIC HELPERS
# ============================================================

def fmt_num(value):
    """Format Decimal/number without unnecessary trailing zeros."""
    d = Decimal(str(value))
    s = format(d, "f")
    if "." in s:
        s = s.rstrip("0").rstrip(".")
    return s or "0"


def dec(value, default=None):
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return default


def load_api():
    if not os.path.exists(API_FILE):
        console.print(f"[red]❌ File {API_FILE} tidak ditemukan.[/red]")
        sys.exit(1)

    lines = [
        x.strip()
        for x in open(API_FILE, "r", encoding="utf-8").read().splitlines()
        if x.strip()
    ]

    if len(lines) < 3:
        console.print(
            f"[red]❌ {API_FILE} harus berisi:[/red]\n"
            "[yellow]API_KEY\nSECRET_KEY\nPASSPHRASE[/yellow]"
        )
        sys.exit(1)

    return lines[0], lines[1], lines[2]


def load_coins():
    if not os.path.exists(COIN_FILE):
        console.print(f"[red]❌ File {COIN_FILE} tidak ditemukan.[/red]")
        console.print("[yellow]Contoh isi coin.txt:[/yellow]")
        console.print("SOLUSDT")
        console.print("XAUTUSDT")
        sys.exit(1)

    coins = []
    for line in open(COIN_FILE, "r", encoding="utf-8").read().splitlines():
        coin = line.strip().upper()
        if coin and not coin.startswith("#"):
            coins.append(coin)

    if not coins:
        console.print(f"[red]❌ {COIN_FILE} kosong.[/red]")
        sys.exit(1)

    # Hilangkan duplikat, tetap mempertahankan urutan
    return list(dict.fromkeys(coins))


# ============================================================
# BITGET SIGNED REQUEST
# ============================================================

def sign_request(secret_key, timestamp, method, request_path, query_string="", body=""):
    message = f"{timestamp}{method.upper()}{request_path}"
    if query_string:
        message += f"?{query_string}"
    message += body

    digest = hmac.new(
        secret_key.encode("utf-8"),
        message.encode("utf-8"),
        hashlib.sha256,
    ).digest()

    return base64.b64encode(digest).decode()


def private_request(api, method, path, params=None, body=None, timeout=15):
    api_key, secret_key, passphrase = api

    method = method.upper()
    params = params or {}

    query_string = urlencode(params, doseq=True) if params else ""

    if body is None:
        body_text = ""
    else:
        body_text = json.dumps(
            body,
            separators=(",", ":"),
            ensure_ascii=False,
        )

    timestamp = str(int(time.time() * 1000))

    signature = sign_request(
        secret_key,
        timestamp,
        method,
        path,
        query_string,
        body_text,
    )

    headers = {
        "ACCESS-KEY": api_key,
        "ACCESS-SIGN": signature,
        "ACCESS-TIMESTAMP": timestamp,
        "ACCESS-PASSPHRASE": passphrase,
        "Content-Type": "application/json",
        "locale": "en-US",
    }

    url = BASE_URL + path

    try:
        if method == "GET":
            r = requests.get(
                url,
                headers=headers,
                params=params or None,
                timeout=timeout,
            )
        else:
            r = requests.request(
                method,
                url,
                headers=headers,
                params=params or None,
                data=body_text,
                timeout=timeout,
            )
    except requests.RequestException as e:
        return None, f"Koneksi gagal: {e}"

    try:
        data = r.json()
    except ValueError:
        return None, f"HTTP {r.status_code}: {r.text[:500]}"

    if r.status_code != 200:
        return None, f"HTTP {r.status_code}: {data}"

    if isinstance(data, dict) and data.get("code") not in (None, "00000", 0):
        return None, str(data)

    return data, None


def public_get(path, params=None, timeout=15):
    try:
        r = requests.get(
            BASE_URL + path,
            params=params or None,
            timeout=timeout,
        )
    except requests.RequestException as e:
        return None, f"Koneksi gagal: {e}"

    try:
        data = r.json()
    except ValueError:
        return None, f"HTTP {r.status_code}: {r.text[:500]}"

    if r.status_code != 200:
        return None, f"HTTP {r.status_code}: {data}"

    if isinstance(data, dict) and data.get("code") not in (None, "00000", 0):
        return None, str(data)

    return data, None


# ============================================================
# MARKET DATA / ACCOUNT
# ============================================================

def get_usdt_balance(api):
    data, err = private_request(
        api,
        "GET",
        "/api/v2/spot/account/assets",
        params={"coin": "USDT"},
    )

    if err:
        return None, err

    rows = data.get("data", []) if isinstance(data, dict) else []

    if isinstance(rows, dict):
        rows = [rows]

    if not rows:
        return Decimal("0"), None

    row = rows[0]

    # Bitget responses can expose available balance under different names.
    for key in ("available", "availableBalance", "availBal", "balance"):
        value = dec(row.get(key))
        if value is not None:
            return value, None

    return Decimal("0"), None


def get_ticker(symbol):
    data, err = public_get(
        "/api/v2/spot/market/tickers",
        params={"symbol": symbol},
    )

    if err:
        return None, err

    rows = data.get("data", []) if isinstance(data, dict) else []

    if isinstance(rows, dict):
        rows = [rows]

    if not rows:
        return None, "Ticker tidak ditemukan."

    row = rows[0]

    bid = dec(row.get("bidPr") or row.get("bid"))
    ask = dec(row.get("askPr") or row.get("ask"))
    last = dec(row.get("lastPr") or row.get("last"))

    return {
        "bid": bid,
        "ask": ask,
        "last": last,
    }, None


def get_symbol_info(symbol):
    data, err = public_get(
        "/api/v2/spot/public/symbols",
        params={"symbol": symbol},
    )

    if err:
        return None, err

    rows = data.get("data", []) if isinstance(data, dict) else []

    if isinstance(rows, dict):
        rows = [rows]

    if not rows:
        return None, f"Symbol {symbol} tidak ditemukan."

    row = rows[0]

    return row, None


# ============================================================
# SYMBOL RULES
# ============================================================

def get_min_usdt(info):
    """
    Ambil minimum quote/USDT order dari response Bitget.
    Fallback 1 USDT untuk menghindari order di bawah minimum
    yang sebelumnya menghasilkan error 45110.
    """
    candidates = (
        "minTradeUSDT",
        "minTradeAmount",
        "minTradeQuote",
        "minOrderAmount",
    )

    for key in candidates:
        value = dec(info.get(key))
        if value is not None and value > 0:
            return value

    return Decimal("1")


def get_price_precision(info):
    for key in ("pricePlace", "pricePrecision"):
        try:
            value = int(info.get(key))
            if value >= 0:
                return value
        except (TypeError, ValueError):
            pass

    return 8


def get_qty_precision(info):
    for key in ("quantityPlace", "quantityPrecision"):
        try:
            value = int(info.get(key))
            if value >= 0:
                return value
        except (TypeError, ValueError):
            pass

    return 8


def round_down(value, places):
    q = Decimal("1").scaleb(-places)
    return Decimal(str(value)).quantize(q, rounding=ROUND_DOWN)


def get_quote_precision(info):
    for key in ("quotePrecision", "quotePlace"):
        try:
            value = int(info.get(key))
            if value >= 0:
                return value
        except (TypeError, ValueError):
            pass
    return 6


def prepare_limit_order(symbol, usdt_amount, price, info):
    """
    Hitung size limit buy dari nominal USDT.
    Pastikan setelah round-down, notional (qty * price)
    masih >= minTradeUSDT (mirip tradingbot.py).
    """
    qty_precision = get_qty_precision(info)
    price_precision = get_price_precision(info)
    minimum = get_min_usdt(info)

    price = round_down(price, price_precision)

    if price <= 0:
        raise ValueError("Harga bid tidak valid.")

    quantity = Decimal(str(usdt_amount)) / price
    quantity = round_down(quantity, qty_precision)

    if quantity <= 0:
        raise ValueError("Quantity setelah pembulatan menjadi 0.")

    notional = quantity * price

    if notional < minimum:
        # Hitung minimum qty yang aman setelah precision
        min_qty = (minimum / price).quantize(
            Decimal("1").scaleb(-qty_precision),
            rounding=ROUND_DOWN,
        )
        # Naikkan 1 tick qty supaya pasti lolos
        step = Decimal("1").scaleb(-qty_precision)
        min_qty = min_qty + step
        min_safe_usdt = (min_qty * price).quantize(
            Decimal("0.000001"),
            rounding=ROUND_DOWN,
        )
        raise ValueError(
            f"Notional setelah round {fmt_num(notional)} USDT "
            f"< minimum {fmt_num(minimum)} USDT. "
            f"Pakai nominal minimal aman ≈ {fmt_num(min_safe_usdt)} USDT"
        )

    return {
        "symbol": symbol,
        "usdt": Decimal(str(usdt_amount)),
        "price": price,
        "size": quantity,
        "notional": notional,
        "price_precision": price_precision,
        "qty_precision": qty_precision,
    }


# ============================================================
# INPUT PARSING
# ============================================================

def parse_coin_selection(text, max_index):
    """
    Mendukung:
      1
      1,2,3
      1-3
      1,3-5
    """
    selected = []

    for part in text.replace(" ", "").split(","):
        if not part:
            continue

        if "-" in part:
            pieces = part.split("-")
            if len(pieces) != 2:
                raise ValueError(f"Format pilihan tidak valid: {part}")

            start = int(pieces[0])
            end = int(pieces[1])

            if start > end:
                start, end = end, start

            selected.extend(range(start, end + 1))
        else:
            selected.append(int(part))

    if not selected:
        raise ValueError("Belum memilih coin.")

    result = []
    for index in selected:
        if index < 1 or index > max_index:
            raise ValueError(f"Nomor coin {index} tidak tersedia.")
        if index not in result:
            result.append(index)

    return result


def parse_amounts(text, expected_count):
    """
    Contoh:
      Pilih coin : 1,2
      Nominal USDT : 2,1

    Mapping:
      coin pilihan pertama  -> 2 USDT
      coin pilihan kedua    -> 1 USDT
    """
    parts = [x.strip() for x in text.replace(" ", "").split(",") if x.strip()]

    if len(parts) != expected_count:
        raise ValueError(
            f"Jumlah nominal harus {expected_count}, "
            f"sesuai jumlah coin yang dipilih."
        )

    amounts = []

    for part in parts:
        value = dec(part)

        if value is None or value <= 0:
            raise ValueError(f"Nominal tidak valid: {part}")

        amounts.append(value)

    return amounts


# ============================================================
# ORDER FUNCTIONS
# ============================================================

def place_market_buy(api, symbol, usdt_amount):
    """
    Market BUY berdasarkan nominal USDT.

    sizeMode=quote berarti size adalah nominal quote/USDT,
    bukan jumlah coin.
    """
    body = {
        "symbol": symbol,
        "side": "buy",
        "orderType": "market",
        "size": fmt_num(usdt_amount),
    }

    return private_request(
        api,
        "POST",
        "/api/v2/spot/trade/place-order",
        body=body,
    )


def place_limit_buy(api, symbol, quantity, price):
    body = {
        "symbol": symbol,
        "side": "buy",
        "orderType": "limit",
        "force": "gtc",
        "size": fmt_num(quantity),
        "price": fmt_num(price),
    }

    return private_request(
        api,
        "POST",
        "/api/v2/spot/trade/place-order",
        body=body,
    )


# ============================================================
# DISPLAY
# ============================================================

def show_coins(coins):
    table = Table(
        title="COIN LIST",
        box=box.ROUNDED,
        show_lines=False,
    )
    table.add_column("#", justify="right", style="cyan", width=4)
    table.add_column("Symbol", style="bold white")

    for i, coin in enumerate(coins, 1):
        table.add_row(str(i), coin)

    console.print(table)


def show_selected(coins, indices, amounts):
    table = Table(
        title="ORDER YANG DIPILIH",
        box=box.ROUNDED,
    )
    table.add_column("#", justify="right")
    table.add_column("Coin")
    table.add_column("Nominal / Grid", justify="right")
    table.add_column("USDT", justify="right")

    for n, (index, amount) in enumerate(zip(indices, amounts), 1):
        table.add_row(
            str(n),
            coins[index - 1],
            fmt_num(amount),
            "USDT",
        )

    console.print(table)


# ============================================================
# MAIN
# ============================================================

def main():
    console.clear()

    console.print(
        Panel.fit(
            "[bold cyan]BITGET SPOT BUY[/bold cyan]\n"
            "[dim]Market Buy / Limit Bid[/dim]",
            border_style="cyan",
        )
    )

    api = load_api()
    coins = load_coins()

    # Saldo USDT di bagian atas
    balance, balance_err = get_usdt_balance(api)

    if balance_err:
        balance_text = "[red]Gagal membaca saldo[/red]"
    else:
        balance_text = f"[bold green]{fmt_num(balance)} USDT[/bold green]"

    console.print(
        Panel.fit(
            f"[bold cyan]Saldo USDT[/bold cyan]\n"
            f"{balance_text}",
            border_style="green",
        )
    )

    show_coins(coins)

    # --------------------------------------------------------
    # 1. PILIH COIN DULU
    # --------------------------------------------------------
    while True:
        raw = Prompt.ask(
            "\n[bold yellow]Pilih coin[/bold yellow]",
            default="1",
        )

        try:
            indices = parse_coin_selection(raw, len(coins))
            break
        except (ValueError, TypeError) as e:
            console.print(f"[red]❌ {e}[/red]")

    selected_symbols = [coins[i - 1] for i in indices]

    console.print(
        "\n[green]Coin terpilih:[/green] "
        + ", ".join(selected_symbols)
    )

    # --------------------------------------------------------
    # 2. NOMINAL SETELAH COIN DIPILIH
    # --------------------------------------------------------
    console.print(
        "\n[bold cyan]Masukkan nominal sesuai urutan coin.[/bold cyan]"
    )
    console.print(
        "[dim]Contoh: coin 1,2 lalu nominal 2,1 "
        "→ coin pertama $2, coin kedua $1[/dim]"
    )

    while True:
        raw_amounts = Prompt.ask(
            "[bold yellow]Nominal USDT[/bold yellow]"
        )

        try:
            amounts = parse_amounts(
                raw_amounts,
                len(selected_symbols),
            )
            break
        except ValueError as e:
            console.print(f"[red]❌ {e}[/red]")

    show_selected(coins, indices, amounts)

    # --------------------------------------------------------
    # 3. MODE ORDER
    # --------------------------------------------------------
    console.print("\n[bold cyan]Pilih mode order:[/bold cyan]")
    console.print("[1] Market Buy")
    console.print("[2] Pasang Bid (Limit)")

    while True:
        mode = Prompt.ask(
            "[bold yellow]Mode[/bold yellow]",
            choices=["1", "2"],
            default="1",
        )
        break

    # --------------------------------------------------------
    # MARKET BUY
    # --------------------------------------------------------
    if mode == "1":
        console.print(
            "\n[bold green]MODE: MARKET BUY[/bold green]"
        )

        balance, err = get_usdt_balance(api)

        if err:
            console.print(f"[red]❌ Gagal cek saldo: {err}[/red]")
            return

        total = sum(amounts, Decimal("0"))

        console.print(
            f"[cyan]Saldo USDT:[/cyan] {fmt_num(balance)}"
        )
        console.print(
            f"[cyan]Total pembelian:[/cyan] {fmt_num(total)} USDT"
        )

        if total > balance:
            console.print(
                "[red]❌ Saldo USDT tidak cukup untuk seluruh pembelian.[/red]"
            )
            return

        console.print()

        for symbol, amount in zip(selected_symbols, amounts):
            info, err = get_symbol_info(symbol)

            if err:
                console.print(
                    f"[red]❌ {symbol}: gagal membaca aturan symbol: {err}[/red]"
                )
                continue

            minimum = get_min_usdt(info)
            quote_prec = get_quote_precision(info)
            qty_prec = get_qty_precision(info)

            ticker, err = get_ticker(symbol)

            if err:
                console.print(
                    f"[red]❌ {symbol}: gagal mengambil ticker: {err}[/red]"
                )
                continue

            ask = ticker.get("ask")
            last = ticker.get("last")
            ref_price = ask or last

            if ref_price is None or ref_price <= 0:
                console.print(
                    f"[red]❌ {symbol}: harga tidak valid.[/red]"
                )
                continue

            # Fee Bitget 0.1%
            fee_rate = Decimal("0.001")
            order_amount = amount / (Decimal("1") - fee_rate)
            order_amount = round_down(order_amount, quote_prec)

            # Min aman: setelah exchange convert quote→base + round qty,
            # notional harus tetap >= minTradeUSDT
            qty_step = Decimal("1").scaleb(-qty_prec)
            min_qty = (minimum / ref_price).quantize(
                qty_step, rounding=ROUND_DOWN
            ) + qty_step
            min_safe = (min_qty * ref_price).quantize(
                Decimal("1").scaleb(-quote_prec),
                rounding=ROUND_DOWN,
            )
            # +1 tick quote biar pasti lolos
            quote_step = Decimal("1").scaleb(-quote_prec)
            min_safe = min_safe + quote_step

            if order_amount < min_safe:
                console.print(
                    f"[yellow]⚠️ {symbol}: nominal dinaikkan "
                    f"{fmt_num(order_amount)} → {fmt_num(min_safe)} USDT "
                    f"(min aman @ {fmt_num(ref_price)})[/yellow]"
                )
                order_amount = min_safe

            console.print(
                Panel(
                    f"[bold]{symbol}[/bold]\n"
                    f"Nominal : [yellow]{fmt_num(amount)} USDT[/yellow]\n"
                    f"Order   : [yellow]{fmt_num(order_amount)} USDT[/yellow]\n"
                    f"Fee     : [dim]0.1%[/dim]\n"
                    f"Ask     : {fmt_num(ask) if ask else '-'}\n"
                    f"Last    : {fmt_num(last) if last else '-'}",
                    border_style="green",
                )
            )

            data, err = place_market_buy(
                api,
                symbol,
                order_amount,
            )

            if err:
                console.print(
                    f"[red]❌ {symbol}: {err}[/red]"
                )
            else:
                console.print(
                    f"[bold green]✅ {symbol}: MARKET BUY berhasil[/bold green]"
                )
                console.print(f"[dim]{data}[/dim]")

        return

    # --------------------------------------------------------
    # LIMIT BID / GRID
    # --------------------------------------------------------
    console.print(
        "\n[bold magenta]MODE: PASANG BID (LIMIT)[/bold magenta]"
    )

    while True:
        try:
            grid_count = IntPrompt.ask(
                "[bold yellow]Jumlah grid[/bold yellow]",
                default=1,
            )
            if grid_count < 1:
                raise ValueError
            break
        except (ValueError, TypeError):
            console.print("[red]❌ Jumlah grid harus >= 1.[/red]")

    while True:
        try:
            grid_spacing = dec(
                Prompt.ask(
                    "[bold yellow]Jarak grid (%)"
                )
            )
            if grid_spacing is None or grid_spacing <= 0:
                raise ValueError
            break
        except ValueError:
            console.print("[red]❌ Jarak grid harus > 0.[/red]")

    console.print(
        f"\n[cyan]Grid:[/cyan] {grid_count}"
        f"  [cyan]Spacing:[/cyan] {fmt_num(grid_spacing)}%"
    )
    console.print(
        "[dim]Nominal yang dimasukkan adalah nominal PER GRID.[/dim]"
    )

    balance, err = get_usdt_balance(api)

    if err:
        console.print(f"[red]❌ Gagal cek saldo: {err}[/red]")
        return

    total_required = sum(amounts, Decimal("0")) * Decimal(grid_count)

    console.print(
        f"[cyan]Saldo USDT:[/cyan] {fmt_num(balance)}"
    )
    console.print(
        f"[cyan]Maksimal kebutuhan:[/cyan] "
        f"{fmt_num(total_required)} USDT"
    )

    if total_required > balance:
        console.print(
            "[red]❌ Saldo tidak cukup untuk seluruh grid.[/red]"
        )
        return

    console.print()

    for symbol, amount in zip(selected_symbols, amounts):
        info, err = get_symbol_info(symbol)

        if err:
            console.print(
                f"[red]❌ {symbol}: gagal membaca aturan symbol: {err}[/red]"
            )
            continue

        minimum = get_min_usdt(info)

        if amount < minimum:
            console.print(
                f"[red]❌ {symbol}: nominal per grid "
                f"{fmt_num(amount)} USDT < minimum "
                f"{fmt_num(minimum)} USDT[/red]"
            )
            continue

        ticker, err = get_ticker(symbol)

        if err:
            console.print(
                f"[red]❌ {symbol}: gagal mengambil ticker: {err}[/red]"
            )
            continue

        bid = ticker.get("bid")
        if bid is None or bid <= 0:
            console.print(
                f"[red]❌ {symbol}: bid tidak valid.[/red]"
            )
            continue

        console.print(
            Panel.fit(
                f"[bold]{symbol}[/bold]\n"
                f"Nominal / grid : [yellow]{fmt_num(amount)} USDT[/yellow]\n"
                f"Bid awal       : [cyan]{fmt_num(bid)}[/cyan]\n"
                f"Grid           : {grid_count}\n"
                f"Jarak          : {fmt_num(grid_spacing)}%",
                border_style="magenta",
            )
        )

        for grid in range(grid_count):
            # Grid 1 = bid sekarang.
            # Grid berikutnya turun sesuai persentase spacing.
            multiplier = (
                Decimal("1")
                - (Decimal(str(grid_spacing)) / Decimal("100"))
            ) ** grid

            price = bid * multiplier

            try:
                prepared = prepare_limit_order(
                    symbol,
                    amount,
                    price,
                    info,
                )
            except ValueError as e:
                console.print(
                    f"[red]❌ {symbol} Grid {grid + 1}: {e}[/red]"
                )
                continue

            console.print(
                f"  [cyan]Grid {grid + 1}[/cyan] "
                f"@ [yellow]{fmt_num(prepared['price'])}[/yellow] "
                f"size [white]{fmt_num(prepared['size'])}[/white] "
                f"≈ [yellow]{fmt_num(amount)} USDT[/yellow]"
            )

            data, err = place_limit_buy(
                api,
                symbol,
                prepared["size"],
                prepared["price"],
            )

            if err:
                console.print(
                    f"  [red]❌ Order gagal: {err}[/red]"
                )
            else:
                console.print(
                    f"  [bold green]✅ Grid {grid + 1} terpasang[/bold green]"
                )
                console.print(f"  [dim]{data}[/dim]")

    console.print(
        "\n[bold green]Selesai.[/bold green]"
    )


if __name__ == "__main__":
    main()
