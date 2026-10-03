from __future__ import annotations

import json
import math
from bisect import bisect_right, insort
from collections import deque
from pathlib import Path

from market_intelligence_formula_v1 import (
    WINDOW,
    build_feature_rows,
    direction_alignment,
    percentile_rank,
)

CACHE = Path("research_cache/btc_usdt_5m_100k.json")

HORIZON = 20
ROUND_TRIP_COST = 0.0014
STARTING_POT = 1500.0


def load_candles():
    with CACHE.open("r", encoding="utf-8") as f:
        payload = json.load(f)

    if isinstance(payload, dict):
        candles = payload.get("candles", payload.get("data"))
    else:
        candles = payload

    if not isinstance(candles, list):
        raise ValueError("Cache does not contain a candle list")

    return candles


def rolling_insert(values, value):
    insort(values, value)


def rolling_remove(values, value):
    index = bisect_right(values, value) - 1
    if index < 0 or values[index] != value:
        raise ValueError("Rolling value removal failed")
    values.pop(index)


def median_sorted(values):
    n = len(values)
    if n == 0:
        return None
    mid = n // 2
    if n % 2:
        return values[mid]
    return (values[mid - 1] + values[mid]) / 2.0


def calculate_metrics_fast(rows):
    """
    Reproduces the ranking logic used by market_intelligence_formula_v1.py.

    The original structure rank is percentile_rank(
        bb_width / rolling_median(bb_width),
        current_bb_width / rolling_median(bb_width)
    ).

    Because the same positive median divides every value in that window,
    the ordering is identical to bb_width itself. Therefore the percentile
    rank is mathematically equivalent to percentile_rank(bb_values,
    current_bb_width).
    """
    trend_values = []
    momentum_values = []
    atr_values = []
    rv_values = []
    bb_values = []

    trend_q = deque()
    momentum_q = deque()
    atr_q = deque()
    rv_q = deque()
    bb_q = deque()

    metrics = [None] * len(rows)

    for i, row in enumerate(rows):
        trend_raw = (
            abs(row["price"] - row["ema200"]) / row["atr"]
        )
        momentum_raw = (
            abs(row["ema20"] - row["ema50"]) / row["atr"]
        )

        trend_value = trend_raw
        momentum_value = momentum_raw
        atr_value = row["atr_pct"]
        rv_value = row["rv"]
        bb_value = row["bb_width"]

        trend_q.append(trend_value)
        momentum_q.append(momentum_value)
        atr_q.append(atr_value)
        rv_q.append(rv_value)
        bb_q.append(bb_value)

        rolling_insert(trend_values, trend_value)
        rolling_insert(momentum_values, momentum_value)
        rolling_insert(atr_values, atr_value)
        rolling_insert(rv_values, rv_value)
        rolling_insert(bb_values, bb_value)

        if len(trend_q) > WINDOW:
            old = trend_q.popleft()
            rolling_remove(trend_values, old)

            old = momentum_q.popleft()
            rolling_remove(momentum_values, old)

            old = atr_q.popleft()
            rolling_remove(atr_values, old)

            old = rv_q.popleft()
            rolling_remove(rv_values, old)

            old = bb_q.popleft()
            rolling_remove(bb_values, old)

        if len(trend_values) < WINDOW:
            continue

        trend_rank = percentile_rank(trend_values, trend_raw)
        momentum_rank = percentile_rank(momentum_values, momentum_raw)
        volatility_rank = percentile_rank(atr_values, atr_value)
        volume_rank = percentile_rank(rv_values, rv_value)
        structure_rank = percentile_rank(bb_values, bb_value)

        market_quality = (
            trend_rank * 0.30
            + momentum_rank * 0.20
            + volatility_rank * 0.25
            + volume_rank * 0.15
            + structure_rank * 0.10
        )

        metrics[i] = {
            "trend_rank": trend_rank,
            "momentum_rank": momentum_rank,
            "volatility_rank": volatility_rank,
            "volume_rank": volume_rank,
            "structure_rank": structure_rank,
            "market_quality": market_quality,
        }

    return metrics


def forward_return(rows, index, side):
    exit_index = index + HORIZON

    if exit_index >= len(rows):
        return None

    entry = rows[index]["price"]
    exit_price = rows[exit_index]["price"]

    if entry <= 0:
        return None

    gross = (
        (exit_price - entry) / entry
        if side == "BUY"
        else (entry - exit_price) / entry
    )

    net = gross - ROUND_TRIP_COST
    return gross, net, exit_index


def quantile_bucket(value, values):
    if not values:
        return None

    rank = percentile_rank(sorted(values), value)

    if rank <= 20:
        return "Q1"
    if rank <= 40:
        return "Q2"
    if rank <= 60:
        return "Q3"
    if rank <= 80:
        return "Q4"
    return "Q5"


def summarize(trades):
    if not trades:
        return {
            "N": 0,
            "win_rate": 0.0,
            "avg_net_pct": 0.0,
            "gross_pct": 0.0,
            "net_pct": 0.0,
            "profit_factor": 0.0,
        }

    gross_values = [t["gross"] for t in trades]
    net_values = [t["net"] for t in trades]

    wins = [x for x in net_values if x > 0]
    losses = [x for x in net_values if x < 0]

    gross_positive = sum(x for x in gross_values if x > 0)
    gross_negative = -sum(x for x in gross_values if x < 0)

    pf = (
        gross_positive / gross_negative
        if gross_negative > 0
        else math.inf
    )

    return {
        "N": len(trades),
        "win_rate": sum(x > 0 for x in net_values) / len(net_values) * 100.0,
        "avg_net_pct": sum(net_values) / len(net_values) * 100.0,
        "gross_pct": sum(gross_values) * 100.0,
        "net_pct": sum(net_values) * 100.0,
        "profit_factor": pf,
    }


def compound(trades):
    pot = STARTING_POT
    peak = pot
    max_dd = 0.0

    for trade in trades:
        pot *= 1.0 + trade["net"]

        if pot > peak:
            peak = pot

        drawdown = (pot / peak - 1.0) * 100.0
        max_dd = min(max_dd, drawdown)

    return pot, max_dd


def max_loss_streak(trades):
    streak = 0
    maximum = 0

    for trade in trades:
        if trade["net"] < 0:
            streak += 1
            maximum = max(maximum, streak)
        else:
            streak = 0

    return maximum


def main():
    print("=" * 78)
    print("MI DIRECTIONAL EDGE RESEARCH")
    print("=" * 78)
    print(f"Cache       : {CACHE}")
    print(f"Horizon     : {HORIZON} bars")
    print(f"Round cost  : {ROUND_TRIP_COST * 100:.3f}%")
    print(f"Starting pot: THB {STARTING_POT:,.2f}")
    print()

    candles = load_candles()
    print(f"Candles     : {len(candles):,}")

    rows = build_feature_rows(candles)
    print(f"Feature rows: {len(rows):,}")

    metrics = calculate_metrics_fast(rows)
    print("MI metrics  : ready")

    candidates = []

    for i, row in enumerate(rows):
        if metrics[i] is None:
            continue

        buy_alignment = direction_alignment(row, "BUY")
        sell_alignment = direction_alignment(row, "SELL")

        if buy_alignment == 100.0:
            side = "BUY"
        elif sell_alignment == 100.0:
            side = "SELL"
        else:
            continue

        result = forward_return(rows, i, side)
        if result is None:
            continue

        gross, net, exit_index = result

        candidates.append({
            "index": i,
            "exit_index": exit_index,
            "side": side,
            "time": row["time"],
            "gross": gross,
            "net": net,
            "trend_rank": metrics[i]["trend_rank"],
            "momentum_rank": metrics[i]["momentum_rank"],
            "volatility_rank": metrics[i]["volatility_rank"],
            "volume_rank": metrics[i]["volume_rank"],
            "structure_rank": metrics[i]["structure_rank"],
            "market_quality": metrics[i]["market_quality"],
        })

    print(f"Aligned candidates: {len(candidates):,}")

    # Event-based execution:
    # only one active trade at a time.
    # Once a trade opens, no new trade can overlap its 20-bar horizon.
    trades = []
    next_available_index = -1

    for candidate in candidates:
        if candidate["index"] < next_available_index:
            continue

        trades.append(candidate)
        next_available_index = candidate["exit_index"] + 1

    print(f"Non-overlapping trades: {len(trades):,}")
    print()

    summary = summarize(trades)
    pot, max_dd = compound(trades)

    print("-" * 78)
    print("ALL DIRECTIONALLY ALIGNED TRADES")
    print("-" * 78)
    print(f"N              : {summary['N']:,}")
    print(f"Win rate       : {summary['win_rate']:.2f}%")
    print(f"Avg Net        : {summary['avg_net_pct']:.4f}%")
    print(f"Gross          : {summary['gross_pct']:.4f}%")
    print(f"Net            : {summary['net_pct']:.4f}%")
    print(f"Profit Factor  : {summary['profit_factor']:.3f}")
    print(f"Loss streak    : {max_loss_streak(trades)}")
    print(f"Final Pot      : THB {pot:,.2f}")
    print(f"Max Drawdown   : {max_dd:.2f}%")
    print()

    if trades:
        split = len(trades) // 2
        first = trades[:split]
        second = trades[split:]

        print("-" * 78)
        print("CHRONOLOGICAL SPLIT")
        print("-" * 78)

        for name, subset in (
            ("FIRST HALF", first),
            ("SECOND HALF", second),
        ):
            s = summarize(subset)
            p, dd = compound(subset)
            print(
                f"{name:12s} "
                f"N={s['N']:4d} "
                f"Net={s['net_pct']:9.4f}% "
                f"PF={s['profit_factor']:6.3f} "
                f"Pot={p:10.2f} "
                f"DD={dd:7.2f}%"
            )

    component_names = [
        "trend_rank",
        "momentum_rank",
        "volatility_rank",
        "volume_rank",
        "structure_rank",
        "market_quality",
    ]

    print()
    print("-" * 78)
    print("MI COMPONENTS — ONLY DIRECTIONALLY ALIGNED TRADES")
    print("-" * 78)

    for component in component_names:
        component_values = [t[component] for t in trades]

        print()
        print(component.upper())

        for bucket in ("Q1", "Q2", "Q3", "Q4", "Q5"):
            bucket_trades = [
                t for t in trades
                if quantile_bucket(t[component], component_values) == bucket
            ]

            s = summarize(bucket_trades)

            print(
                f"  {bucket}: "
                f"N={s['N']:4d} "
                f"Net={s['net_pct']:9.4f}% "
                f"PF={s['profit_factor']:6.3f}"
            )

    print()
    print("=" * 78)
    print("RESEARCH ONLY — NO LIVE ORDERS")
    print("=" * 78)


if __name__ == "__main__":
    main()
