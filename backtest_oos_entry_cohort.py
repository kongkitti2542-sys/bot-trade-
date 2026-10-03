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


def run_analysis(candles, boundary):
    capital = STARTING_CAPITAL
    position = None

    feature_engine = IncrementalFeatures()

    all_entries = []
    checkpoints = []

    for index, candle in enumerate(candles):
        features = feature_engine.update(candle)

        if index < 200:
            continue

        candle_time = candle["time"]

        # ---------------------------------------------------------
        # Existing position
        # ---------------------------------------------------------
        if position is not None:
            position["bars_held"] += 1

            current_price = candle["close"]

            # Record checkpoint BEFORE exit evaluation.
            # This represents information available at this candle.
            if position["bars_held"] in CHECKPOINTS.values():
                label = next(
                    k for k, v in CHECKPOINTS.items()
                    if v == position["bars_held"]
                )

                checkpoints.append({
                    "entry_id": position["entry_id"],
                    "checkpoint": label,
                    "bars_held": position["bars_held"],
                    "entry_time": position["entry_time"],
                    "side": position["side"],
                    "entry_price": position["entry_price"],
                    "current_price": current_price,
                    "unrealized_pnl_pct":
                        unrealized_pnl_percent(
                            position,
                            current_price,
                        ),
                    "pnl_bucket":
                        pnl_bucket(
                            unrealized_pnl_percent(
                                position,
                                current_price,
                            )
                        ),
                    "entry_regime": position["regime"],
                    "entry_score": position["score"],
                    "final_exit_reason": None,
                    "final_pnl": None,
                })

            # Stop loss
            if position["side"] == "BUY":
                if candle["low"] <= position["stop_loss"]:
                    trade = close_position(
                        position,
                        position["stop_loss"],
                        candle_time,
                        "STOP_LOSS",
                    )

                    capital += trade["pnl"]

                    for item in checkpoints:
                        if (
                            item["entry_id"]
                            == position["entry_id"]
                            and item["final_pnl"] is None
                        ):
                            item["final_exit_reason"] = (
                                trade["exit_reason"]
                            )
                            item["final_pnl"] = trade["pnl"]

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

                    for item in checkpoints:
                        if (
                            item["entry_id"]
                            == position["entry_id"]
                            and item["final_pnl"] is None
                        ):
                            item["final_exit_reason"] = (
                                trade["exit_reason"]
                            )
                            item["final_pnl"] = trade["pnl"]

                    position = None
                    continue

            # 20h Time Exit
            if position["bars_held"] >= max(
                CHECKPOINTS.values()
            ):
                trade = close_position(
                    position,
                    candle["close"],
                    candle_time,
                    "TIME_EXIT",
                )

                capital += trade["pnl"]

                for item in checkpoints:
                    if (
                        item["entry_id"]
                        == position["entry_id"]
                        and item["final_pnl"] is None
                    ):
                        item["final_exit_reason"] = (
                            trade["exit_reason"]
                        )
                        item["final_pnl"] = trade["pnl"]

                position = None
                continue

            continue

        # ---------------------------------------------------------
        # New entry
        # ---------------------------------------------------------
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

        entry_id = len(all_entries) + 1

        position = {
            "entry_id": entry_id,
            "side": decision["signal"],
            "entry_time": candle_time,
            "entry_price": features["close"],
            "position_size": risk["position_size"],
            "stop_loss": risk["stop_loss"],
            "regime": regime,
            "score": decision["score"],
            "bars_held": 0,
        }

        all_entries.append(entry_id)

    return all_entries, checkpoints


def summarize_checkpoint(checkpoints, label):
    rows = [
        x for x in checkpoints
        if x["checkpoint"] == label
        and x["final_pnl"] is not None
    ]

    print()
    print("=" * 110)
    print(f"CHECKPOINT {label}")
    print("=" * 110)

    print(f"Entries reaching checkpoint: {len(rows)}")

    if not rows:
        return

    winners = [
        x for x in rows
        if x["final_pnl"] > 0
    ]

    losers = [
        x for x in rows
        if x["final_pnl"] < 0
    ]

    print(f"Final winners:               {len(winners)}")
    print(f"Final losers:                {len(losers)}")

    print()
    print("P/L AT CHECKPOINT → FINAL OUTCOME")
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
        f"{'Checkpoint P/L':<20}"
        f"{'N':>8}"
        f"{'WIN':>8}"
        f"{'LOSS':>8}"
        f"{'Win%':>10}"
        f"{'Final P/L':>16}"
    )

    for bucket in buckets:
        subset = [
            x for x in rows
            if x["pnl_bucket"] == bucket
        ]

        win_count = sum(
            1 for x in subset
            if x["final_pnl"] > 0
        )

        loss_count = sum(
            1 for x in subset
            if x["final_pnl"] < 0
        )

        total_pnl = sum(
            x["final_pnl"]
            for x in subset
        )

        win_rate = (
            win_count / len(subset) * 100
            if subset
            else 0.0
        )

        print(
            f"{bucket:<20}"
            f"{len(subset):>8}"
            f"{win_count:>8}"
            f"{loss_count:>8}"
            f"{win_rate:>10.2f}"
            f"{total_pnl:>16.4f}"
        )

    print()
    print("FINAL EXIT REASON")
    print("-" * 110)

    reasons = [
        "STOP_LOSS",
        "TIME_EXIT",
    ]

    print(
        f"{'Exit':<20}"
        f"{'N':>8}"
        f"{'WIN':>8}"
        f"{'LOSS':>8}"
        f"{'Win%':>10}"
        f"{'P/L':>16}"
    )

    for reason in reasons:
        subset = [
            x for x in rows
            if x["final_exit_reason"] == reason
        ]

        win_count = sum(
            1 for x in subset
            if x["final_pnl"] > 0
        )

        loss_count = sum(
            1 for x in subset
            if x["final_pnl"] < 0
        )

        total_pnl = sum(
            x["final_pnl"]
            for x in subset
        )

        win_rate = (
            win_count / len(subset) * 100
            if subset
            else 0.0
        )

        print(
            f"{reason:<20}"
            f"{len(subset):>8}"
            f"{win_count:>8}"
            f"{loss_count:>8}"
            f"{win_rate:>10.2f}"
            f"{total_pnl:>16.4f}"
        )


def main():
    print("=" * 110)
    print("OOS ENTRY COHORT / TIME EXIT DIAGNOSTIC")
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
    print()

    all_entries, checkpoints = run_analysis(
        candles,
        boundary,
    )

    print(f"Total OOS entries: {len(all_entries)}")

    for label in CHECKPOINTS:
        summarize_checkpoint(
            checkpoints,
            label,
        )

    print()
    print("=" * 110)
    print("RESEARCH ONLY — NO CORE FILES MODIFIED")
    print("=" * 110)


if __name__ == "__main__":
    main()
