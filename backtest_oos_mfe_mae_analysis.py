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
        "mfe_pct": position["mfe_pct"],
        "mae_pct": position["mae_pct"],
    }


def update_excursion(position, candle):
    entry = position["entry_price"]

    if entry <= 0:
        return

    if position["side"] == "BUY":
        favorable = (
            float(candle["high"]) - entry
        ) / entry * 100

        adverse = (
            float(candle["low"]) - entry
        ) / entry * 100

    else:
        favorable = (
            entry - float(candle["low"])
        ) / entry * 100

        adverse = (
            entry - float(candle["high"])
        ) / entry * 100

    position["mfe_pct"] = max(
        position["mfe_pct"],
        favorable,
    )

    position["mae_pct"] = min(
        position["mae_pct"],
        adverse,
    )


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

            update_excursion(position, candle)

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
            "mfe_pct": 0.0,
            "mae_pct": 0.0,
        }

    if position is not None:
        last_candle = candles[-1]

        update_excursion(position, last_candle)

        trade = close_position(
            position,
            last_candle["close"],
            last_candle["time"],
            "BACKTEST_END",
        )

        capital += trade["pnl"]
        trades.append(trade)

    return capital, trades, risk_rejections


def print_stats(title, trades):
    print()
    print(title)
    print("-" * 100)

    if not trades:
        print("No trades.")
        return

    mfe = [t["mfe_pct"] for t in trades]
    mae = [t["mae_pct"] for t in trades]

    print(f"Count:          {len(trades)}")
    print(f"Avg MFE:        {sum(mfe) / len(mfe):.4f}%")
    print(f"Max MFE:        {max(mfe):.4f}%")
    print(f"Avg MAE:        {sum(mae) / len(mae):.4f}%")
    print(f"Worst MAE:      {min(mae):.4f}%")

    winners = [t for t in trades if t["pnl"] > 0]
    losers = [t for t in trades if t["pnl"] < 0]

    if winners:
        print()
        print(
            f"WINNERS: count={len(winners):4d} "
            f"avg_mfe={sum(t['mfe_pct'] for t in winners) / len(winners):.4f}% "
            f"avg_mae={sum(t['mae_pct'] for t in winners) / len(winners):.4f}% "
            f"avg_pnl=${sum(t['pnl'] for t in winners) / len(winners):.4f}"
        )

    if losers:
        print(
            f"LOSERS:  count={len(losers):4d} "
            f"avg_mfe={sum(t['mfe_pct'] for t in losers) / len(losers):.4f}% "
            f"avg_mae={sum(t['mae_pct'] for t in losers) / len(losers):.4f}% "
            f"avg_pnl=${sum(t['pnl'] for t in losers) / len(losers):.4f}"
        )


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

    print_stats(
        "ALL REALIZED TRADES",
        realized,
    )

    print_stats(
        "TIME EXIT WINNERS",
        [
            t for t in realized
            if t["exit_reason"] == "TIME_EXIT"
            and t["pnl"] > 0
        ],
    )

    print_stats(
        "TIME EXIT LOSERS",
        [
            t for t in realized
            if t["exit_reason"] == "TIME_EXIT"
            and t["pnl"] < 0
        ],
    )

    print_stats(
        "STOP LOSS TRADES",
        [
            t for t in realized
            if t["exit_reason"] == "STOP_LOSS"
        ],
    )

    print()
    print("TIME EXIT WINNERS — MFE BUCKETS")
    print("-" * 100)

    winners = [
        t for t in realized
        if t["exit_reason"] == "TIME_EXIT"
        and t["pnl"] > 0
    ]

    buckets = [
        ("<0.5%", 0, 0.5),
        ("0.5-1%", 0.5, 1),
        ("1-2%", 1, 2),
        ("2-3%", 2, 3),
        ("3-5%", 3, 5),
        (">5%", 5, float("inf")),
    ]

    for name, low, high in buckets:
        values = [
            t for t in winners
            if low <= t["mfe_pct"] < high
        ]

        if values:
            pnl = sum(t["pnl"] for t in values)

            print(
                f"{name:<10}"
                f"count={len(values):4d} "
                f"P/L=${pnl:10.4f} "
                f"avg=${pnl / len(values):8.4f}"
            )

    print()
    print("TIME EXIT WINNERS — MAE BUCKETS")
    print("-" * 100)

    mae_buckets = [
        (">-0.1%", -0.1, float("inf")),
        ("-0.1--0.25%", -0.25, -0.1),
        ("-0.25--0.5%", -0.5, -0.25),
        ("-0.5--1%", -1, -0.5),
        ("<-1%", -float("inf"), -1),
    ]

    for name, low, high in mae_buckets:
        values = [
            t for t in winners
            if low <= t["mae_pct"] < high
        ]

        if values:
            pnl = sum(t["pnl"] for t in values)

            print(
                f"{name:<16}"
                f"count={len(values):4d} "
                f"avg_mae={sum(t['mae_pct'] for t in values) / len(values):8.4f}% "
                f"avg_pnl=${pnl / len(values):8.4f}"
            )

    print()


def main():
    print("=" * 100)
    print("OOS MFE / MAE ANALYSIS")
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
