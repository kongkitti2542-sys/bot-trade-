"""
RESEARCH ONLY
Arena Discovery for Personal Trading Bot

Purpose:
    Compare liquid USDT-margined futures markets and timeframes
    using the bot's existing research philosophy.

IMPORTANT:
    - Does NOT modify Core strategy/risk/engine.
    - Does NOT place orders.
    - Does NOT select parameters automatically.
    - Results are evidence for further research only.
"""

from __future__ import annotations

import json
import math
import statistics
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SYMBOLS = [
    "BTCUSDT",
    "ETHUSDT",
    "SOLUSDT",
    "BNBUSDT",
    "XRPUSDT",
    "DOGEUSDT",
]

INTERVALS = [
    "5m",
    "15m",
    "30m",
    "1h",
]

LIMIT = 1000

# Research assumption only.
# Same round-trip cost used in the recent research layer.
ROUND_TRIP_COST = 0.0014

# Forward horizon in candles.
HORIZON = 20


@dataclass
class Candle:
    time: int
    open: float
    high: float
    low: float
    close: float
    volume: float


def fetch_klines(symbol: str, interval: str, limit: int = LIMIT) -> list[Candle]:
    params = urllib.parse.urlencode(
        {
            "symbol": symbol,
            "interval": interval,
            "limit": limit,
        }
    )

    url = f"https://fapi.binance.com/fapi/v1/klines?{params}"

    request = urllib.request.Request(
        url,
        headers={"User-Agent": "personal-trading-bot-research"},
    )

    with urllib.request.urlopen(request, timeout=20) as response:
        raw = json.loads(response.read().decode("utf-8"))

    candles: list[Candle] = []

    for row in raw:
        candles.append(
            Candle(
                time=int(row[0]),
                open=float(row[1]),
                high=float(row[2]),
                low=float(row[3]),
                close=float(row[4]),
                volume=float(row[5]),
            )
        )

    # Exclude the newest candle because it may still be forming.
    if candles:
        candles = candles[:-1]

    return candles


def ema(values: list[float], period: int) -> list[float | None]:
    result: list[float | None] = [None] * len(values)

    if len(values) < period:
        return result

    seed = sum(values[:period]) / period
    result[period - 1] = seed

    multiplier = 2.0 / (period + 1)

    previous = seed

    for i in range(period, len(values)):
        previous = (values[i] - previous) * multiplier + previous
        result[i] = previous

    return result


def atr(candles: list[Candle], period: int = 14) -> list[float | None]:
    result: list[float | None] = [None] * len(candles)

    if len(candles) < period + 1:
        return result

    trs: list[float] = []

    for i, candle in enumerate(candles):
        if i == 0:
            tr = candle.high - candle.low
        else:
            previous_close = candles[i - 1].close
            tr = max(
                candle.high - candle.low,
                abs(candle.high - previous_close),
                abs(candle.low - previous_close),
            )

        trs.append(tr)

    value = sum(trs[:period]) / period
    result[period - 1] = value

    for i in range(period, len(candles)):
        value = ((value * (period - 1)) + trs[i]) / period
        result[i] = value

    return result


def relative_volume(
    candles: list[Candle],
    period: int = 20,
) -> list[float | None]:
    result: list[float | None] = [None] * len(candles)

    if len(candles) <= period:
        return result

    for i in range(period, len(candles)):
        previous = [c.volume for c in candles[i - period:i]]

        average = sum(previous) / len(previous)

        if average > 0:
            result[i] = candles[i].volume / average

    return result


def structure(candles: list[Candle], lookback: int = 5) -> list[str | None]:
    result: list[str | None] = [None] * len(candles)

    for i in range(lookback, len(candles)):
        current = candles[i]
        previous = candles[i - lookback:i]

        previous_high = max(c.high for c in previous)
        previous_low = min(c.low for c in previous)

        if current.high > previous_high and current.low > previous_low:
            result[i] = "BULLISH"
        elif current.high < previous_high and current.low < previous_low:
            result[i] = "BEARISH"
        else:
            result[i] = "NEUTRAL"

    return result


def build_features(candles: list[Candle]) -> dict[str, list[Any]]:
    closes = [c.close for c in candles]

    return {
        "ema20": ema(closes, 20),
        "ema50": ema(closes, 50),
        "ema200": ema(closes, 200),
        "atr": atr(candles, 14),
        "rv": relative_volume(candles, 20),
        "structure": structure(candles, 5),
    }


def directional_alignment(
    candle: Candle,
    ema20_value: float,
    ema50_value: float,
    ema200_value: float,
    structure_value: str,
) -> str | None:
    if (
        candle.close > ema200_value
        and ema20_value > ema50_value
        and structure_value == "BULLISH"
    ):
        return "LONG"

    if (
        candle.close < ema200_value
        and ema20_value < ema50_value
        and structure_value == "BEARISH"
    ):
        return "SHORT"

    return None


def evaluate_trade(
    candles: list[Candle],
    index: int,
    side: str,
) -> float:
    entry = candles[index].close
    exit_price = candles[index + HORIZON].close

    if entry <= 0:
        return 0.0

    if side == "LONG":
        gross = (exit_price / entry) - 1.0
    else:
        gross = (entry / exit_price) - 1.0

    return gross - ROUND_TRIP_COST


def summarize(returns: list[float]) -> dict[str, float]:
    if not returns:
        return {
            "n": 0,
            "win_rate": 0.0,
            "gross": 0.0,
            "net": 0.0,
            "pf": 0.0,
            "avg": 0.0,
            "max_dd": 0.0,
            "max_loss_streak": 0.0,
        }

    wins = [x for x in returns if x > 0]
    losses = [x for x in returns if x < 0]

    gross = sum(returns)
    win_rate = len(wins) / len(returns)

    gross_profit = sum(wins)
    gross_loss = abs(sum(losses))

    if gross_loss > 0:
        pf = gross_profit / gross_loss
    else:
        pf = math.inf if gross_profit > 0 else 0.0

    equity = 1.0
    peak = 1.0
    max_dd = 0.0

    loss_streak = 0
    max_loss_streak = 0

    for r in returns:
        equity *= 1.0 + r

        if equity > peak:
            peak = equity

        dd = (equity / peak) - 1.0

        if dd < max_dd:
            max_dd = dd

        if r < 0:
            loss_streak += 1
            max_loss_streak = max(max_loss_streak, loss_streak)
        else:
            loss_streak = 0

    return {
        "n": len(returns),
        "win_rate": win_rate,
        "gross": gross,
        "net": gross,
        "pf": pf,
        "avg": statistics.mean(returns),
        "max_dd": max_dd,
        "max_loss_streak": max_loss_streak,
    }


def analyze_market(
    symbol: str,
    interval: str,
    candles: list[Candle],
) -> dict[str, Any]:
    features = build_features(candles)

    trades: list[dict[str, Any]] = []

    start = 200
    end = len(candles) - HORIZON

    for i in range(start, end):
        ema20_value = features["ema20"][i]
        ema50_value = features["ema50"][i]
        ema200_value = features["ema200"][i]
        atr_value = features["atr"][i]
        rv_value = features["rv"][i]
        structure_value = features["structure"][i]

        if (
            ema20_value is None
            or ema50_value is None
            or ema200_value is None
            or atr_value is None
            or rv_value is None
            or structure_value is None
        ):
            continue

        # Basic data-quality gate.
        if candles[i].close <= 0 or atr_value <= 0:
            continue

        side = directional_alignment(
            candles[i],
            ema20_value,
            ema50_value,
            ema200_value,
            structure_value,
        )

        if side is None:
            continue

        net_return = evaluate_trade(candles, i, side)

        trades.append(
            {
                "index": i,
                "time": candles[i].time,
                "side": side,
                "return": net_return,
                "rv": rv_value,
                "atr_pct": atr_value / candles[i].close,
            }
        )

    returns = [t["return"] for t in trades]

    overall = summarize(returns)

    midpoint = len(trades) // 2

    first = summarize(
        [t["return"] for t in trades[:midpoint]]
    )

    second = summarize(
        [t["return"] for t in trades[midpoint:]]
    )

    long_returns = [
        t["return"]
        for t in trades
        if t["side"] == "LONG"
    ]

    short_returns = [
        t["return"]
        for t in trades
        if t["side"] == "SHORT"
    ]

    return {
        "symbol": symbol,
        "interval": interval,
        "candles": len(candles),
        "overall": overall,
        "first_half": first,
        "second_half": second,
        "long": summarize(long_returns),
        "short": summarize(short_returns),
    }


def print_result(result: dict[str, Any]) -> None:
    o = result["overall"]
    f = result["first_half"]
    s = result["second_half"]

    print(
        f"{result['symbol']:8} "
        f"{result['interval']:>3} "
        f"N={o['n']:5d} "
        f"WR={o['win_rate']*100:6.2f}% "
        f"Net={o['net']*100:8.3f}% "
        f"PF={o['pf']:6.3f} "
        f"1H={f['net']*100:8.3f}% "
        f"2H={s['net']*100:8.3f}% "
        f"DD={o['max_dd']*100:7.2f}% "
        f"LS={int(o['max_loss_streak']):3d}"
    )


def main() -> None:
    print("=" * 120)
    print("TRADING BOT — ARENA DISCOVERY")
    print("RESEARCH ONLY — NO ORDERS — CORE UNTOUCHED")
    print("=" * 120)
    print(
        f"Symbols   : {', '.join(SYMBOLS)}"
    )
    print(
        f"Intervals : {', '.join(INTERVALS)}"
    )
    print(
        f"Horizon   : {HORIZON} candles"
    )
    print(
        f"Cost      : {ROUND_TRIP_COST * 100:.3f}% round trip"
    )
    print()

    results: list[dict[str, Any]] = []

    for symbol in SYMBOLS:
        for interval in INTERVALS:
            print(
                f"Loading {symbol} {interval}...",
                flush=True,
            )

            try:
                candles = fetch_klines(
                    symbol,
                    interval,
                    LIMIT,
                )

                if len(candles) < 250:
                    print(
                        f"  SKIP: only {len(candles)} closed candles"
                    )
                    continue

                result = analyze_market(
                    symbol,
                    interval,
                    candles,
                )

                results.append(result)

                print_result(result)

            except Exception as exc:
                print(
                    f"  ERROR: {type(exc).__name__}: {exc}"
                )

    print()
    print("=" * 120)
    print("RESULTS")
    print("=" * 120)

    print(
        "Market    TF   N       WR       Net       PF      "
        "1H Net     2H Net      DD      LS"
    )
    print("-" * 120)

    for result in sorted(
        results,
        key=lambda r: r["overall"]["net"],
        reverse=True,
    ):
        print_result(result)

    output = {
        "research_only": True,
        "cost_round_trip": ROUND_TRIP_COST,
        "horizon": HORIZON,
        "results": results,
    }

    output_path = Path("research_arena_discovery_results.json")

    output_path.write_text(
        json.dumps(output, indent=2),
        encoding="utf-8",
    )

    print()
    print(f"Saved: {output_path}")
    print()
    print("IMPORTANT:")
    print("- This is arena discovery, not a strategy approval.")
    print("- No Core files were modified.")
    print("- No automatic parameter selection was performed.")


if __name__ == "__main__":
    main()
