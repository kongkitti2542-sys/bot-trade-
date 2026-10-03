from statistics import mean, median
from datetime import datetime

from backtest_data_100k import (
    get_historical_candles_100k,
    validate_candles,
)
from edge_fingerprint_trend_buy import run

OOS_BOUNDARY = datetime.fromisoformat("2026-07-21T10:05:00+00:00")


FEATURES = [
    "price_vs_ema200_pct",
    "ema50_vs_ema200_pct",
    "ema20_vs_ema50_pct",
    "price_vs_ema50_pct",
    "ema50_buffer_pct",
    "pullback_depth_pct",
    "atr_pct",
]


def fmt(v):
    if v is None:
        return "None"
    return f"{v:.6f}"


def analyze_numeric(winners, name):
    values = [
        t["features"].get(name)
        for t in winners
        if t["features"].get(name) is not None
    ]

    if not values:
        return

    print(
        f"{name:28s} | "
        f"MIN {min(values):>10.6f} | "
        f"MED {median(values):>10.6f} | "
        f"AVG {mean(values):>10.6f} | "
        f"MAX {max(values):>10.6f}"
    )


def analyze_categorical(winners, name):
    values = [t["features"].get(name) for t in winners]

    counts = {}
    for value in values:
        counts[value] = counts.get(value, 0) + 1

    print(f"{name:28s} | {counts}")


def main():
    candles = get_historical_candles_100k(
        symbol="BTCUSDT",
        interval="5m",
        candles_needed=100_000,
    )

    valid, reason = validate_candles(candles)

    if not valid:
        raise RuntimeError(
            f"Dataset validation failed: {reason}"
        )

    final_capital, trades = run(candles, OOS_BOUNDARY)

    winners = [
        t for t in trades
        if t.get("gross_pnl", 0) > 0
    ]

    print()
    print("=" * 100)
    print("WINNER-ONLY EDGE MINER")
    print("RESEARCH ONLY — DESCRIPTIVE — NO CORE FILES MODIFIED")
    print("=" * 100)

    print(f"Candidate trades: {len(trades)}")
    print(f"Winning trades:   {len(winners)}")

    if not winners:
        print("NO WINNERS FOUND")
        return

    print()
    print("=" * 100)
    print("WINNER P/L")
    print("=" * 100)

    gross = sum(t["gross_pnl"] for t in winners)

    print(f"Gross winner P/L: ${gross:+.6f}")
    print(f"Average winner:   ${mean(t['gross_pnl'] for t in winners):+.6f}")
    print(f"Median winner:    ${median(t['gross_pnl'] for t in winners):+.6f}")

    print()
    print("=" * 100)
    print("WINNER ENTRY FINGERPRINT")
    print("=" * 100)

    for name in FEATURES:
        analyze_numeric(winners, name)

    print()
    print("=" * 100)
    print("WINNER STRUCTURE")
    print("=" * 100)

    for name in [
        "structure",
        "touched_ema20",
        "held_ema50",
        "recovery_confirmed",
    ]:
        analyze_categorical(winners, name)

    print()
    print("=" * 100)
    print("WINNER EXIT BEHAVIOR")
    print("=" * 100)

    exits = {}
    for trade in winners:
        reason = trade.get("exit_reason")
        exits[reason] = exits.get(reason, 0) + 1

    print(f"Exit types: {exits}")

    held = [t["bars_held"] for t in winners]

    print(f"Bars held MIN:    {min(held)}")
    print(f"Bars held MEDIAN: {median(held)}")
    print(f"Bars held AVG:    {mean(held):.2f}")
    print(f"Bars held MAX:    {max(held)}")

    print()
    print("=" * 100)
    print("INDIVIDUAL WINNERS")
    print("=" * 100)

    for i, trade in enumerate(winners, 1):
        f = trade["features"]

        print(
            f"{i:02d} | "
            f"Entry {trade['entry_time']} | "
            f"Gross ${trade['gross_pnl']:+.6f} | "
            f"Bars {trade['bars_held']:3d} | "
            f"EMA200 {fmt(f.get('price_vs_ema200_pct'))}% | "
            f"EMA50/200 {fmt(f.get('ema50_vs_ema200_pct'))}% | "
            f"EMA20/50 {fmt(f.get('ema20_vs_ema50_pct'))}% | "
            f"Pullback {fmt(f.get('pullback_depth_pct'))}% | "
            f"ATR {fmt(f.get('atr_pct'))}%"
        )

    print()
    print("=" * 100)
    print("IMPORTANT")
    print("=" * 100)
    print("This output describes winners only.")
    print("It does NOT prove causation or a tradable threshold.")
    print("No threshold optimization was performed.")
    print("No future information was used to define entry features.")
    print("No Core strategy/risk/execution file was modified.")
    print("=" * 100)


if __name__ == "__main__":
    main()
