from collections import Counter, defaultdict
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


def analyze(label, capital, trades, risk_rejections):
    realized = [
        t for t in trades
        if t["exit_reason"] != "BACKTEST_END"
    ]

    print("=" * 100)
    print(f"TIME EXIT {label}")
    print("=" * 100)
    print(f"Ending capital:  ${capital:.2f}")
    print(f"Risk rejections: {risk_rejections}")
    print(f"Realized trades: {len(realized)}")

    loss_chain = [
        (prev, curr)
        for prev, curr in zip(realized, realized[1:])
        if prev["pnl"] < 0 and curr["pnl"] < 0
    ]

    print()
    print("LOSS -> LOSS BY NEXT TRADE REGIME")
    print("-" * 80)

    regime_values = defaultdict(list)

    for _, curr in loss_chain:
        regime_values[curr["regime"]].append(curr["pnl"])

    for regime in sorted(regime_values):
        values = regime_values[regime]
        print(
            f"{regime:<16}"
            f"count={len(values):4d} "
            f"avg_next_pnl=${sum(values) / len(values):8.4f}"
        )

    print()
    print("LOSS -> LOSS BY NEXT TRADE SCORE")
    print("-" * 80)

    score_values = defaultdict(list)

    for _, curr in loss_chain:
        score = abs(curr["score"])

        if 60 <= score < 70:
            bucket = "60-69"
        elif 70 <= score < 85:
            bucket = "70-84"
        elif score >= 85:
            bucket = "85+"
        else:
            bucket = "<60"

        score_values[bucket].append(curr["pnl"])

    for bucket in ("<60", "60-69", "70-84", "85+"):
        values = score_values.get(bucket, [])

        if values:
            print(
                f"{bucket:<8}"
                f"count={len(values):4d} "
                f"avg_next_pnl=${sum(values) / len(values):8.4f}"
            )

    print()
    print("LOSS -> LOSS BY PREVIOUS EXIT")
    print("-" * 80)

    exit_values = defaultdict(list)

    for prev, curr in loss_chain:
        exit_values[prev["exit_reason"]].append(curr["pnl"])

    for reason in ("STOP_LOSS", "TIME_EXIT"):
        values = exit_values.get(reason, [])

        if values:
            print(
                f"{reason:<12}"
                f"count={len(values):4d} "
                f"avg_next_pnl=${sum(values) / len(values):8.4f}"
            )

    print()
    print("LOSS -> LOSS BY SIDE TRANSITION")
    print("-" * 80)

    transitions = defaultdict(list)

    for prev, curr in loss_chain:
        transitions[
            f"{prev['side']}->{curr['side']}"
        ].append(curr["pnl"])

    for transition in (
        "BUY->BUY",
        "BUY->SELL",
        "SELL->BUY",
        "SELL->SELL",
    ):
        values = transitions.get(transition, [])

        if values:
            print(
                f"{transition:<8}"
                f"count={len(values):4d} "
                f"avg_next_pnl=${sum(values) / len(values):8.4f}"
            )

    print()
    print("CONSECUTIVE LOSS STREAKS")
    print("-" * 80)

    streaks = []
    current_streak = 0

    for trade in realized:
        if trade["pnl"] < 0:
            current_streak += 1
        else:
            if current_streak > 0:
                streaks.append(current_streak)
            current_streak = 0

    if current_streak > 0:
        streaks.append(current_streak)

    if streaks:
        print(f"Number of loss streaks: {len(streaks)}")
        print(f"Max loss streak:       {max(streaks)}")

        distribution = Counter(streaks)

        for length in sorted(distribution):
            if length >= 2:
                print(
                    f"streak {length:2d}: "
                    f"{distribution[length]:3d} occurrence(s)"
                )

    print()


def main():
    print("=" * 100)
    print("OOS LOSS CHAIN ANALYSIS")
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

    first_time = candles[0]["time"]
    last_time = candles[-1]["time"]

    print(f"First:         {first_time}")
    print(f"Last:          {last_time}")
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
