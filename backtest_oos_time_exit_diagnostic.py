from backtest_data_100k import get_historical_candles_100k, validate_candles
from incremental_features import IncrementalFeatures
from regime import detect_regime
from strategy import analyze_market
from risk import evaluate_risk


SYMBOL = "BTCUSDT"
INTERVAL = "5m"
CANDLES_NEEDED = 100_000
STARTING_CAPITAL = 1000.0

OOS_BOUNDARY = "2026-07-21T10:05:00+00:00"

MAX_HOLD_BARS = 240

CHECKPOINTS = {
    "12h": 144,
    "16h": 192,
    "18h": 216,
    "20h": 240,
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
        "bars_held": position["bars_held"],
        "pnl": pnl,
        "exit_reason": exit_reason,
    }


def unrealized_pnl_percent(position, price):
    entry = position["entry_price"]

    if entry <= 0:
        return 0.0

    if position["side"] == "BUY":
        return (price - entry) / entry * 100.0

    return (entry - price) / entry * 100.0


def pnl_bucket(value):
    if value < -1.0:
        return "< -1%"
    if value < -0.5:
        return "-1% to -0.5%"
    if value < -0.25:
        return "-0.5% to -0.25%"
    if value < 0:
        return "-0.25% to 0%"
    if value < 0.25:
        return "0% to +0.25%"
    if value < 0.5:
        return "+0.25% to +0.5%"
    if value < 1.0:
        return "+0.5% to +1%"
    if value < 2.0:
        return "+1% to +2%"
    return ">= +2%"


def score_bucket(score):
    absolute = abs(score)

    if absolute < 70:
        return "<70"

    if absolute < 85:
        return "70-84"

    return "85+"


def run_diagnostic(candles, boundary):
    capital = STARTING_CAPITAL
    position = None
    trades = []
    checkpoints = []

    feature_engine = IncrementalFeatures()

    for index, candle in enumerate(candles):
        features = feature_engine.update(candle)

        if index < 200:
            continue

        candle_time = candle["time"]

        if position is not None:
            position["bars_held"] += 1

            current_regime = detect_regime(features)
            current_decision = analyze_market(
                features,
                current_regime,
            )

            current_price = candle["close"]

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

            else:
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

            if position["bars_held"] in CHECKPOINTS.values():
                checkpoint_label = next(
                    label
                    for label, bars in CHECKPOINTS.items()
                    if bars == position["bars_held"]
                )

                checkpoints.append({
                    "checkpoint": checkpoint_label,
                    "bars_held": position["bars_held"],
                    "entry_time": position["entry_time"],
                    "side": position["side"],
                    "entry_price": position["entry_price"],
                    "current_price": current_price,
                    "unrealized_pnl_pct": unrealized_pnl_percent(
                        position,
                        current_price,
                    ),
                    "pnl_bucket": pnl_bucket(
                        unrealized_pnl_percent(
                            position,
                            current_price,
                        )
                    ),
                    "entry_regime": position["regime"],
                    "entry_score": position["score"],
                    "current_regime": current_regime,
                    "current_score": current_decision["score"],
                    "current_signal": current_decision["signal"],
                    "final_trade": None,
                })

            if position["bars_held"] >= MAX_HOLD_BARS:
                trade = close_position(
                    position,
                    candle["close"],
                    candle_time,
                    "TIME_EXIT",
                )

                capital += trade["pnl"]
                trades.append(trade)

                for item in reversed(checkpoints):
                    if (
                        item["entry_time"] == trade["entry_time"]
                        and item["final_trade"] is None
                    ):
                        item["final_trade"] = trade
                    else:
                        break

                position = None
                continue

            continue

        if candle_time < boundary:
            continue

        regime = detect_regime(features)
        decision = analyze_market(
            features,
            regime,
        )

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
            continue

        position = {
            "side": decision["signal"],
            "entry_time": candle_time,
            "entry_price": features["close"],
            "position_size": risk["position_size"],
            "stop_loss": risk["stop_loss"],
            "regime": regime,
            "score": decision["score"],
            "bars_held": 0,
        }

    return checkpoints, trades


def print_checkpoint_summary(checkpoints, label):
    rows = [
        x for x in checkpoints
        if x["checkpoint"] == label
        and x["final_trade"] is not None
    ]

    winners = [
        x for x in rows
        if x["final_trade"]["pnl"] > 0
    ]

    losers = [
        x for x in rows
        if x["final_trade"]["pnl"] < 0
    ]

    print()
    print("=" * 110)
    print(f"CHECKPOINT {label}")
    print("=" * 110)

    print(f"Samples:           {len(rows)}")
    print(f"Final Winners:     {len(winners)}")
    print(f"Final Losers:      {len(losers)}")

    if rows:
        print(
            f"Final Win Rate:    "
            f"{len(winners) / len(rows) * 100:.2f}%"
        )

    print()
    print("UNREALIZED P/L AT CHECKPOINT")
    print("-" * 110)

    buckets = [
        "< -1%",
        "-1% to -0.5%",
        "-0.5% to -0.25%",
        "-0.25% to 0%",
        "0% to +0.25%",
        "+0.25% to +0.5%",
        "+0.5% to +1%",
        "+1% to +2%",
        ">= +2%",
    ]

    print(
        f"{'Bucket':<18}"
        f"{'N':>8}"
        f"{'W':>8}"
        f"{'L':>8}"
        f"{'Win%':>10}"
        f"{'Final P/L':>16}"
    )

    for bucket in buckets:
        subset = [
            x for x in rows
            if x["pnl_bucket"] == bucket
        ]

        wins = [
            x for x in subset
            if x["final_trade"]["pnl"] > 0
        ]

        losses = [
            x for x in subset
            if x["final_trade"]["pnl"] < 0
        ]

        pnl = sum(
            x["final_trade"]["pnl"]
            for x in subset
        )

        win_rate = (
            len(wins) / len(subset) * 100
            if subset
            else 0.0
        )

        print(
            f"{bucket:<18}"
            f"{len(subset):>8}"
            f"{len(wins):>8}"
            f"{len(losses):>8}"
            f"{win_rate:>10.2f}"
            f"{pnl:>16.4f}"
        )

    print()
    print("CURRENT REGIME AT CHECKPOINT")
    print("-" * 110)

    regimes = sorted(
        set(x["current_regime"] for x in rows)
    )

    print(
        f"{'Regime':<20}"
        f"{'N':>8}"
        f"{'W':>8}"
        f"{'L':>8}"
        f"{'Win%':>10}"
        f"{'Final P/L':>16}"
    )

    for regime in regimes:
        subset = [
            x for x in rows
            if x["current_regime"] == regime
        ]

        wins = [
            x for x in subset
            if x["final_trade"]["pnl"] > 0
        ]

        losses = [
            x for x in subset
            if x["final_trade"]["pnl"] < 0
        ]

        pnl = sum(
            x["final_trade"]["pnl"]
            for x in subset
        )

        win_rate = (
            len(wins) / len(subset) * 100
            if subset
            else 0.0
        )

        print(
            f"{regime:<20}"
            f"{len(subset):>8}"
            f"{len(wins):>8}"
            f"{len(losses):>8}"
            f"{win_rate:>10.2f}"
            f"{pnl:>16.4f}"
        )

    print()
    print("CURRENT SCORE AT CHECKPOINT")
    print("-" * 110)

    score_groups = ["<70", "70-84", "85+"]

    print(
        f"{'Score':<20}"
        f"{'N':>8}"
        f"{'W':>8}"
        f"{'L':>8}"
        f"{'Win%':>10}"
        f"{'Final P/L':>16}"
    )

    for group in score_groups:
        subset = [
            x for x in rows
            if score_bucket(x["current_score"]) == group
        ]

        wins = [
            x for x in subset
            if x["final_trade"]["pnl"] > 0
        ]

        losses = [
            x for x in subset
            if x["final_trade"]["pnl"] < 0
        ]

        pnl = sum(
            x["final_trade"]["pnl"]
            for x in subset
        )

        win_rate = (
            len(wins) / len(subset) * 100
            if subset
            else 0.0
        )

        print(
            f"{group:<20}"
            f"{len(subset):>8}"
            f"{len(wins):>8}"
            f"{len(losses):>8}"
            f"{win_rate:>10.2f}"
            f"{pnl:>16.4f}"
        )

    print()
    print("CURRENT SIGNAL AT CHECKPOINT")
    print("-" * 110)

    signals = ["BUY", "SELL", "WAIT"]

    print(
        f"{'Signal':<20}"
        f"{'N':>8}"
        f"{'W':>8}"
        f"{'L':>8}"
        f"{'Win%':>10}"
        f"{'Final P/L':>16}"
    )

    for signal in signals:
        subset = [
            x for x in rows
            if x["current_signal"] == signal
        ]

        wins = [
            x for x in subset
            if x["final_trade"]["pnl"] > 0
        ]

        losses = [
            x for x in subset
            if x["final_trade"]["pnl"] < 0
        ]

        pnl = sum(
            x["final_trade"]["pnl"]
            for x in subset
        )

        win_rate = (
            len(wins) / len(subset) * 100
            if subset
            else 0.0
        )

        print(
            f"{signal:<20}"
            f"{len(subset):>8}"
            f"{len(wins):>8}"
            f"{len(losses):>8}"
            f"{win_rate:>10.2f}"
            f"{pnl:>16.4f}"
        )


def main():
    print("=" * 110)
    print("OOS TIME EXIT DIAGNOSTIC")
    print("=" * 110)

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

    import datetime

    boundary = datetime.datetime.fromisoformat(
        OOS_BOUNDARY
    )

    print(f"First:         {candles[0]['time']}")
    print(f"Last:          {candles[-1]['time']}")
    print(f"OOS Boundary:  {OOS_BOUNDARY}")
    print(f"Max Hold:      {MAX_HOLD_BARS} bars / 20h")
    print()

    checkpoints, trades = run_diagnostic(
        candles,
        boundary,
    )

    for label in CHECKPOINTS:
        print_checkpoint_summary(
            checkpoints,
            label,
        )

    print()
    print("=" * 110)
    print("RESEARCH ONLY — NO CORE FILES MODIFIED")
    print("=" * 110)


if __name__ == "__main__":
    main()
