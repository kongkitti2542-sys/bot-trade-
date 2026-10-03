from collections import defaultdict
from datetime import datetime

from backtest_data_100k import (
    get_historical_candles_100k,
    validate_candles,
)
from incremental_features import IncrementalFeatures
from regime import detect_regime
from strategy import analyze_market
from risk import evaluate_risk


SYMBOL = "BTCUSDT"
INTERVAL = "5m"
CANDLES_NEEDED = 100_000
STARTING_CAPITAL = 1000.0

OOS_BOUNDARY = "2026-07-21T10:05:00+00:00"

TEST_HOLDS = {
    "18h": 216,
    "20h": 240,
    "22h": 264,
}


def close_position(position, exit_price, exit_time, exit_reason):
    if position["side"] == "BUY":
        pnl = (
            exit_price - position["entry_price"]
        ) * position["position_size"]
    else:
        pnl = (
            position["entry_price"] - exit_price
        ) * position["position_size"]

    return {
        "entry_time": position["entry_time"],
        "exit_time": exit_time,
        "side": position["side"],
        "entry_price": position["entry_price"],
        "exit_price": exit_price,
        "position_size": position["position_size"],
        "regime": position["regime"],
        "score": position["score"],
        "confidence": position["confidence"],
        "bars_held": position["bars_held"],
        "pnl": pnl,
        "exit_reason": exit_reason,
    }


def run_oos_backtest(candles, max_hold_bars, boundary):
    capital = STARTING_CAPITAL
    position = None
    trades = []
    risk_rejections = 0

    feature_engine = IncrementalFeatures()

    for index, candle in enumerate(candles):
        features = feature_engine.update(candle)

        if index < 200:
            continue

        candle_time = candle["time"]

        if position is not None:
            position["bars_held"] += 1

            if position["side"] == "BUY":
                if candle["low"] <= position["stop_loss"]:
                    trade = close_position(
                        position,
                        position["stop_loss"],
                        candle_time,
                        "STOP_LOSS",
                    )
                    capital += trade["pnl"]
                    trades.append(trade)
                    position = None
                    continue

            elif position["side"] == "SELL":
                if candle["high"] >= position["stop_loss"]:
                    trade = close_position(
                        position,
                        position["stop_loss"],
                        candle_time,
                        "STOP_LOSS",
                    )
                    capital += trade["pnl"]
                    trades.append(trade)
                    position = None
                    continue

            if position["bars_held"] >= max_hold_bars:
                trade = close_position(
                    position,
                    candle["close"],
                    candle_time,
                    "TIME_EXIT",
                )
                capital += trade["pnl"]
                trades.append(trade)
                position = None
                continue

            continue

        if candle_time < boundary:
            continue

        regime = detect_regime(features)
        decision = analyze_market(features, regime)

        if decision["signal"] == "WAIT":
            continue

        risk = evaluate_risk(
            decision,
            features,
            capital=capital,
            daily_pnl=0.0,
            open_positions=0,
        )

        if not risk["allowed"]:
            risk_rejections += 1
            continue

        position = {
            "side": decision["signal"],
            "entry_time": candle_time,
            "entry_price": features["close"],
            "position_size": risk["position_size"],
            "stop_loss": risk["stop_loss"],
            "regime": regime,
            "score": decision["score"],
            "confidence": decision["confidence"],
            "bars_held": 0,
        }

    if position is not None:
        last_candle = candles[-1]

        trade = close_position(
            position,
            last_candle["close"],
            last_candle["time"],
            "BACKTEST_END",
        )

        capital += trade["pnl"]
        trades.append(trade)

    return capital, trades, risk_rejections


def bucket(hours):
    if hours < 2:
        return "<2h"
    if hours < 4:
        return "2-4h"
    if hours < 8:
        return "4-8h"
    if hours < 12:
        return "8-12h"
    if hours < 16:
        return "12-16h"
    if hours < 20:
        return "16-20h"
    if hours <= 24:
        return "20-24h"
    return ">24h"


def analyze(label, capital, trades, risk_rejections):
    realized = [
        t for t in trades
        if t["exit_reason"] != "BACKTEST_END"
    ]

    winners = [
        t for t in realized
        if t["pnl"] > 0
    ]

    print("=" * 100)
    print(f"TIME EXIT {label}")
    print("=" * 100)
    print(f"Ending capital:  ${capital:.2f}")
    print(f"Risk rejections: {risk_rejections}")
    print(f"Realized trades: {len(realized)}")
    print(f"Winners:         {len(winners)}")
    print()

    groups = defaultdict(list)

    for trade in winners:
        hours = trade["bars_held"] * 5 / 60
        groups[bucket(hours)].append(trade)

    order = [
        "<2h",
        "2-4h",
        "4-8h",
        "8-12h",
        "12-16h",
        "16-20h",
        "20-24h",
        ">24h",
    ]

    print("WINNERS BY HOLDING TIME")
    print("-" * 100)
    print(
        f"{'Bucket':<10}"
        f"{'Count':>8}"
        f"{'P/L':>14}"
        f"{'Avg':>12}"
        f"{'Share':>10}"
        f"{'Avg Mins':>12}"
    )

    total_winner_pnl = sum(t["pnl"] for t in winners)

    for name in order:
        values = groups.get(name, [])

        if not values:
            continue

        pnl = sum(t["pnl"] for t in values)
        avg = pnl / len(values)
        share = (
            pnl / total_winner_pnl * 100
            if total_winner_pnl != 0
            else 0.0
        )
        avg_hours = (
            sum(t["bars_held"] * 5 / 60 for t in values)
            / len(values)
        )

        print(
            f"{name:<10}"
            f"{len(values):>8}"
            f"${pnl:>13.4f}"
            f"${avg:>11.4f}"
            f"{share:>9.2f}%"
            f"{avg_hours:>11.2f}h"
        )

    print()
    print("WINNERS BY EXIT REASON")
    print("-" * 80)

    for reason in ("STOP_LOSS", "TIME_EXIT"):
        values = [
            t for t in winners
            if t["exit_reason"] == reason
        ]

        if values:
            pnl = sum(t["pnl"] for t in values)

            print(
                f"{reason:<12}"
                f"count={len(values):4d} "
                f"P/L=${pnl:10.4f} "
                f"avg=${pnl / len(values):8.4f}"
            )

    print()
    print("WINNERS BY REGIME")
    print("-" * 80)

    regime_values = defaultdict(list)

    for trade in winners:
        regime_values[trade["regime"]].append(trade)

    for regime in sorted(regime_values):
        values = regime_values[regime]
        pnl = sum(t["pnl"] for t in values)

        print(
            f"{regime:<16}"
            f"count={len(values):4d} "
            f"P/L=${pnl:10.4f} "
            f"avg=${pnl / len(values):8.4f}"
        )

    print()


def main():
    print("=" * 100)
    print("OOS WINNER HOLDING-TIME ANALYSIS")
    print("=" * 100)

    candles = get_historical_candles_100k(
        symbol=SYMBOL,
        interval=INTERVAL,
        candles_needed=CANDLES_NEEDED,
    )

    valid, reason = validate_candles(candles)

    print(f"Candles:       {len(candles)}")
    print(f"Validation:    {valid}")
    print(f"Reason:        {reason}")

    if not valid:
        raise RuntimeError(
            f"Dataset validation failed: {reason}"
        )

    if not candles:
        raise RuntimeError("No candles returned.")

    print(f"First:         {candles[0]['time']}")
    print(f"Last:          {candles[-1]['time']}")
    print(f"OOS Boundary:  {OOS_BOUNDARY}")
    print()

    boundary = datetime.fromisoformat(OOS_BOUNDARY)

    for label, bars in TEST_HOLDS.items():
        capital, trades, risk_rejections = run_oos_backtest(
            candles,
            max_hold_bars=bars,
            boundary=boundary,
        )

        analyze(
            label,
            capital,
            trades,
            risk_rejections,
        )

    print("=" * 100)
    print("Research only. No Core files were modified.")
    print("=" * 100)


if __name__ == "__main__":
    main()
