from datetime import datetime

from backtest_data_100k import (
    get_historical_candles_100k,
    validate_candles,
)
from edge_fingerprint_trend_buy import run

OOS_BOUNDARY = datetime.fromisoformat(
    "2026-07-21T10:05:00+00:00"
)

FEE_PER_SIDE = 0.0005
SLIPPAGE_PER_SIDE = 0.0002

HORIZON = 240


def cost(entry_price, exit_price, size):
    entry_value = entry_price * size
    exit_value = exit_price * size

    fees = (
        entry_value * FEE_PER_SIDE
        + exit_value * FEE_PER_SIDE
    )

    slip = (
        entry_value * SLIPPAGE_PER_SIDE
        + exit_value * SLIPPAGE_PER_SIDE
    )

    return fees, slip


def structural_snapshot(candles, entry_index, entry_price):
    recent = candles[entry_index - 5:entry_index]

    if len(recent) != 5:
        return None

    # Reconstruct the EMA20/EMA50 values stored at entry
    # from the trade fingerprint.
    # The strategy itself has already generated this trade.
    # These values are descriptive only.
    #
    # We use the stored entry fingerprint values to derive
    # structural relationships, while the candle sequence
    # supplies event timing.

    entry_time = candles[entry_index]["time"]

    # The fingerprint contains the exact entry-time pullback
    # measurements through the trade object.
    return {
        "entry_time": entry_time,
        "recent": recent,
    }


def classify_event(trade, candles, time_to_index):
    entry_time = trade["entry_time"]
    entry_index = time_to_index.get(entry_time)

    if entry_index is None or entry_index < 5:
        return None

    recent = candles[entry_index - 5:entry_index]

    # We need the actual EMA20/EMA50 values represented by
    # the entry fingerprint.
    features = trade["features"]

    price_vs_ema20 = features.get("price_vs_ema20_pct")
    price_vs_ema50 = features.get("price_vs_ema50_pct")
    ema50_buffer = features.get("ema50_buffer_pct")
    pullback_depth = features.get("pullback_depth_pct")
    recovery_strength = features.get("recovery_strength_pct")

    if price_vs_ema20 is None:
        return None

    # Reconstruct the EMA20 value from price-vs-EMA20.
    # price_vs_ema20 = (close - ema20) / ema20 * 100
    close = trade["entry_price"]
    ema20 = close / (1.0 + price_vs_ema20 / 100.0)

    touch_positions = [
        i + 1
        for i, candle in enumerate(recent)
        if candle["low"] <= ema20
    ]

    if not touch_positions:
        return None

    last_touch = touch_positions[-1]

    return {
        "touch_count": len(touch_positions),
        "first_touch_position": touch_positions[0],
        "last_touch_position": last_touch,
        "last_touch_age": 5 - last_touch,
        "pullback_depth": pullback_depth,
        "ema50_buffer": ema50_buffer,
        "recovery_strength": recovery_strength,
        "price_vs_ema50": price_vs_ema50,
    }


def evaluate_trade(trade, candles, time_to_index):
    event = classify_event(
        trade,
        candles,
        time_to_index,
    )

    if event is None:
        return None

    # Revalue every trade at its actual existing 240-bar
    # endpoint unless it already hit the existing stop.
    entry_time = trade["entry_time"]
    entry_index = time_to_index[entry_time]

    if trade["exit_reason"] == "STOP_LOSS":
        exit_price = trade["exit_price"]
    else:
        target = entry_index + HORIZON

        if target >= len(candles):
            return None

        exit_price = candles[target]["close"]

    gross = (
        exit_price - trade["entry_price"]
    ) * trade["position_size"]

    fees, slip = cost(
        trade["entry_price"],
        exit_price,
        trade["position_size"],
    )

    net = gross - fees - slip

    return {
        **event,
        "entry_time": entry_time,
        "gross": gross,
        "fees": fees,
        "slip": slip,
        "net": net,
    }


def summarize(rows, label):
    if not rows:
        print(
            f"{label:<28} N=0"
        )
        return

    gross = sum(x["gross"] for x in rows)
    fees = sum(x["fees"] for x in rows)
    slip = sum(x["slip"] for x in rows)
    net = sum(x["net"] for x in rows)

    wins = sum(
        1 for x in rows
        if x["net"] > 0
    )

    losses = sum(
        1 for x in rows
        if x["net"] < 0
    )

    gross_wins = sum(
        x["gross"]
        for x in rows
        if x["gross"] > 0
    )

    gross_losses = abs(sum(
        x["gross"]
        for x in rows
        if x["gross"] < 0
    ))

    pf = (
        gross_wins / gross_losses
        if gross_losses
        else float("inf")
    )

    print(
        f"{label:<28} "
        f"N={len(rows):3d} "
        f"W={wins:3d} "
        f"L={losses:3d} "
        f"Gross=${gross:+.6f} "
        f"Net=${net:+.6f} "
        f"PF={pf:.4f}"
    )


def main():
    print("=" * 100)
    print("TREND_PULLBACK + BUY — STRUCTURAL PULLBACK FINAL TEST")
    print("RESEARCH ONLY — NO CORE FILES MODIFIED")
    print("=" * 100)

    candles = get_historical_candles_100k(
        symbol="BTCUSDT",
        interval="5m",
        candles_needed=100_000,
    )

    valid, reason = validate_candles(candles)

    print(f"Candles:        {len(candles)}")
    print(f"Validation:     {valid}")
    print(f"Reason:         {reason}")
    print(f"OOS Boundary:   {OOS_BOUNDARY}")

    if not valid:
        raise RuntimeError(
            f"Dataset validation failed: {reason}"
        )

    boundary = OOS_BOUNDARY

    final_capital, trades = run(
        candles,
        boundary,
    )

    time_to_index = {
        candle["time"]: index
        for index, candle in enumerate(candles)
    }

    rows = []

    for trade in trades:
        row = evaluate_trade(
            trade,
            candles,
            time_to_index,
        )

        if row is not None:
            rows.append(row)

    discovery = [
        row for row in rows
        if row["entry_time"] < boundary
    ]

    # The original run already applies OOS boundary,
    # so use chronological half split inside the candidate set.
    midpoint = len(rows) // 2

    first_half = rows[:midpoint]
    second_half = rows[midpoint:]

    print()
    print("=" * 100)
    print("BASELINE")
    print("=" * 100)

    summarize(rows, "ALL CANDIDATES")

    print()
    print("=" * 100)
    print("EVENT: TOUCH COUNT")
    print("=" * 100)

    for count in sorted(
        set(row["touch_count"] for row in rows)
    ):
        subset = [
            row for row in rows
            if row["touch_count"] == count
        ]

        summarize(
            subset,
            f"Touch count = {count}",
        )

    print()
    print("=" * 100)
    print("EVENT: LAST TOUCH POSITION")
    print("=" * 100)

    for position in sorted(
        set(row["last_touch_position"] for row in rows)
    ):
        subset = [
            row for row in rows
            if row["last_touch_position"] == position
        ]

        summarize(
            subset,
            f"Last touch bar = {position}",
        )

    print()
    print("=" * 100)
    print("EVENT: LAST TOUCH AGE")
    print("=" * 100)

    for age in sorted(
        set(row["last_touch_age"] for row in rows)
    ):
        subset = [
            row for row in rows
            if row["last_touch_age"] == age
        ]

        summarize(
            subset,
            f"Last touch age = {age}",
        )

    print()
    print("=" * 100)
    print("TIME SPLIT")
    print("=" * 100)

    summarize(first_half, "FIRST HALF")
    summarize(second_half, "SECOND HALF")

    print()
    print("=" * 100)
    print("WINNER STRUCTURAL CONSISTENCY")
    print("=" * 100)

    winners = [
        row for row in rows
        if row["net"] > 0
    ]

    print(f"Net-positive trades: {len(winners)}")

    if winners:
        for name in [
            "touch_count",
            "first_touch_position",
            "last_touch_position",
            "last_touch_age",
        ]:
            values = [
                row[name]
                for row in winners
            ]

            print(
                f"{name:<28} "
                f"MIN={min(values)} "
                f"MAX={max(values)} "
                f"VALUES={sorted(set(values))}"
            )

    print()
    print("=" * 100)
    print("FINAL DECISION RULE")
    print("=" * 100)
    print(
        "This test does NOT create a new strategy threshold."
    )
    print(
        "A structural pattern is useful only if it remains"
    )
    print(
        "profitable on unseen chronological data after costs."
    )
    print(
        "If no structural event survives that test,"
    )
    print(
        "TREND_PULLBACK + BUY is closed as an edge candidate."
    )
    print(
        "No Core strategy/risk/execution file was modified."
    )
    print("=" * 100)


if __name__ == "__main__":
    main()
