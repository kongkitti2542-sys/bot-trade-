from bisect import bisect_right
from statistics import median
from datetime import datetime

from incremental_features import IncrementalFeatures
from regime import detect_regime
from strategy import analyze_market
from backtest_oos_time_exit import (
    run_oos_backtest,
    OOS_BOUNDARY,
)
from research_data_cache import load_candles


WINDOW = 2016
START_TIME = datetime.fromisoformat("2026-07-21T10:05:00+00:00")


def percentile_rank(values, current):
    if not values:
        return 50.0

    ordered = sorted(values)
    rank = bisect_right(ordered, current)
    return (rank / len(ordered)) * 100.0


def centered_quality(percentile):
    """
    100 = near middle of historical distribution
    0   = near extreme
    """
    return max(0.0, 100.0 - abs(percentile - 50.0) * 2.0)


def build_feature_rows(candles):
    engine = IncrementalFeatures()
    rows = []

    for index, candle in enumerate(candles):
        features = engine.update(candle)

        if index < 200:
            continue

        if not features:
            continue

        atr = features.get("atr14")
        ema200 = features.get("ema200")
        ema20 = features.get("ema20")
        ema50 = features.get("ema50")
        price = features.get("close")
        rsi = features.get("rsi14")
        rv = features.get("relative_volume")
        bollinger = features.get("bollinger")

        if not all(
            value is not None
            for value in (
                atr,
                ema200,
                ema20,
                ema50,
                price,
                rsi,
                rv,
                bollinger,
            )
        ):
            continue

        if atr <= 0 or price <= 0:
            continue

        bb_upper = bollinger.get("upper")
        bb_lower = bollinger.get("lower")

        if bb_upper is None or bb_lower is None:
            continue

        bb_width = (bb_upper - bb_lower) / price
        atr_pct = atr / price

        rows.append(
            {
                "time": candle["time"],
                "price": price,
                "ema20": ema20,
                "ema50": ema50,
                "ema200": ema200,
                "atr": atr,
                "atr_pct": atr_pct,
                "rsi": rsi,
                "rv": rv,
                "bb_width": bb_width,
                "structure": features.get("structure", {}).get(
                    "structure", "MIXED"
                ),
            }
        )

    return rows


def calculate_metrics(rows, index):
    start = max(0, index - WINDOW + 1)
    window = rows[start:index + 1]

    current = rows[index]

    trend_raw = abs(
        current["price"] - current["ema200"]
    ) / current["atr"]

    momentum_raw = abs(
        current["ema20"] - current["ema50"]
    ) / current["atr"]

    atr_values = [row["atr_pct"] for row in window]
    rv_values = [row["rv"] for row in window]
    bb_values = [row["bb_width"] for row in window]
    trend_values = [
        abs(row["price"] - row["ema200"]) / row["atr"]
        for row in window
        if row["atr"] > 0
    ]
    momentum_values = [
        abs(row["ema20"] - row["ema50"]) / row["atr"]
        for row in window
        if row["atr"] > 0
    ]

    trend_rank = percentile_rank(trend_values, trend_raw)
    momentum_rank = percentile_rank(momentum_values, momentum_raw)
    volatility_rank = percentile_rank(
        atr_values,
        current["atr_pct"],
    )
    volume_rank = percentile_rank(
        rv_values,
        current["rv"],
    )

    bb_median = median(bb_values)

    if bb_median > 0:
        bb_ratio = current["bb_width"] / bb_median
        bb_ratio_values = [
            row["bb_width"] / bb_median
            for row in window
        ]
    else:
        bb_ratio = 1.0
        bb_ratio_values = [1.0 for _ in window]

    structure_rank = percentile_rank(
        bb_ratio_values,
        bb_ratio,
    )

    market_quality = (
        trend_rank * 0.30
        + momentum_rank * 0.20
        + volatility_rank * 0.25
        + volume_rank * 0.15
        + structure_rank * 0.10
    )

    return {
        "trend_rank": trend_rank,
        "momentum_rank": momentum_rank,
        "volatility_rank": volatility_rank,
        "volume_rank": volume_rank,
        "structure_rank": structure_rank,
        "market_quality": market_quality,
        "trend_raw": trend_raw,
        "momentum_raw": momentum_raw,
        "atr_pct": current["atr_pct"],
        "rv": current["rv"],
        "bb_ratio": bb_ratio,
    }


def direction_alignment(row, side):
    checks = []

    if side == "BUY":
        checks.append(row["price"] > row["ema200"])
        checks.append(row["ema20"] > row["ema50"])
        checks.append(row["structure"] == "BULLISH")

    elif side == "SELL":
        checks.append(row["price"] < row["ema200"])
        checks.append(row["ema20"] < row["ema50"])
        checks.append(row["structure"] == "BEARISH")

    else:
        return 0.0

    return sum(checks) / len(checks) * 100.0


def main():
    candles = load_candles()

    print("=" * 70)
    print("MARKET INTELLIGENCE FORMULA V1")
    print("=" * 70)
    print(f"Candles: {len(candles)}")
    print(f"Window:  {WINDOW}")
    print(f"Start:   {START_TIME.isoformat()}")
    print()

    rows = build_feature_rows(candles)

    row_by_time = {
        row["time"]: (index, row)
        for index, row in enumerate(rows)
    }

    print(f"Feature rows: {len(rows)}")

    boundary = datetime.fromisoformat(OOS_BOUNDARY)

    _, trades, risk_rejections = run_oos_backtest(
        candles,
        max_hold_bars=240,
        boundary=boundary,
    )

    print(f"Reference trades: {len(trades)}")
    print(f"Risk rejections:  {risk_rejections}")
    print()

    results = []

    for trade in trades:
        entry_time = trade["entry_time"]

        if entry_time not in row_by_time:
            continue

        index, row = row_by_time[entry_time]

        metrics = calculate_metrics(rows, index)
        alignment = direction_alignment(row, trade["side"])

        results.append(
            {
                "side": trade["side"],
                "entry_time": entry_time,
                "score": trade["score"],
                "gross_pnl": trade["pnl"],
                "market_quality": metrics["market_quality"],
                "direction_alignment": alignment,
                **metrics,
            }
        )

    print(f"Analyzed entries: {len(results)}")
    print()

    if not results:
        print("No results.")
        return

    print("MARKET QUALITY DISTRIBUTION")
    print("-" * 70)

    mq_values = sorted(
        result["market_quality"]
        for result in results
    )

    da_values = sorted(
        result["direction_alignment"]
        for result in results
    )

    print(
        f"MQ  min={mq_values[0]:.2f} "
        f"median={median(mq_values):.2f} "
        f"max={mq_values[-1]:.2f}"
    )

    print(
        f"DA  min={da_values[0]:.2f} "
        f"median={median(da_values):.2f} "
        f"max={da_values[-1]:.2f}"
    )

    print()
    print("SAMPLE ENTRIES")
    print("-" * 70)

    for result in results[:10]:
        print(
            result["entry_time"].isoformat(),
            result["side"],
            f"score={result['score']}",
            f"MQ={result['market_quality']:.2f}",
            f"DA={result['direction_alignment']:.2f}",
            f"T={result['trend_rank']:.1f}",
            f"M={result['momentum_rank']:.1f}",
            f"V={result['volatility_rank']:.1f}",
            f"RV={result['volume_rank']:.1f}",
            f"S={result['structure_rank']:.1f}",
        )

    print()
    print("=" * 70)
    print("RESEARCH ONLY")
    print("No Core files modified.")
    print("=" * 70)


if __name__ == "__main__":
    main()
