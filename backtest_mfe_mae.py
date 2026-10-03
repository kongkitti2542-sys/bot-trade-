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
MAX_HOLD_BARS = 288


def close_position(
    position,
    exit_price,
    exit_time,
    exit_reason,
):
    if position["side"] == "BUY":
        pnl = (
            exit_price - position["entry_price"]
        ) * position["position_size"]
    else:
        pnl = (
            position["entry_price"] - exit_price
        ) * position["position_size"]

    return {
        **position,
        "exit_time": exit_time,
        "exit_price": exit_price,
        "pnl": pnl,
        "exit_reason": exit_reason,
    }


def run_backtest(candles):
    capital = STARTING_CAPITAL
    position = None
    trades = []

    decisions = {
        "BUY": 0,
        "SELL": 0,
        "WAIT": 0,
    }

    risk_rejections = 0
    feature_engine = IncrementalFeatures()

    for index, candle in enumerate(candles):
        features = feature_engine.update(candle)

        if index < 200:
            continue

        # ---------------------------------------------------------
        # POSITION MANAGEMENT
        # ---------------------------------------------------------
        if position is not None:
            position["bars_held"] += 1

            entry = position["entry_price"]

            # Track Maximum Favorable Excursion
            if position["side"] == "BUY":
                favorable = (
                    candle["high"] - entry
                ) / entry

                adverse = (
                    candle["low"] - entry
                ) / entry

            else:
                favorable = (
                    entry - candle["low"]
                ) / entry

                adverse = (
                    entry - candle["high"]
                ) / entry

            position["mfe"] = max(
                position["mfe"],
                favorable,
            )

            position["mae"] = min(
                position["mae"],
                adverse,
            )

            # -----------------------------------------------------
            # STOP LOSS
            # -----------------------------------------------------
            if position["side"] == "BUY":
                if candle["low"] <= position["stop_loss"]:
                    trade = close_position(
                        position,
                        position["stop_loss"],
                        candle["time"],
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
                        candle["time"],
                        "STOP_LOSS",
                    )

                    capital += trade["pnl"]
                    trades.append(trade)
                    position = None
                    continue

            # -----------------------------------------------------
            # TIME EXIT
            # -----------------------------------------------------
            if position["bars_held"] >= MAX_HOLD_BARS:
                trade = close_position(
                    position,
                    candle["close"],
                    candle["time"],
                    "TIME_EXIT",
                )

                capital += trade["pnl"]
                trades.append(trade)
                position = None
                continue

            continue

        # ---------------------------------------------------------
        # ENTRY
        # ---------------------------------------------------------
        regime = detect_regime(features)
        decision = analyze_market(
            features,
            regime,
        )

        signal = decision["signal"]
        decisions[signal] += 1

        if signal == "WAIT":
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
            "side": signal,
            "entry_time": candle["time"],
            "entry_price": features["close"],
            "position_size": risk["position_size"],
            "stop_loss": risk["stop_loss"],
            "regime": regime,
            "score": decision["score"],
            "bars_held": 0,
            "mfe": 0.0,
            "mae": 0.0,
        }

    # -------------------------------------------------------------
    # DATASET END
    # -------------------------------------------------------------
    if position is not None:
        last = candles[-1]

        trade = close_position(
            position,
            last["close"],
            last["time"],
            "BACKTEST_END",
        )

        capital += trade["pnl"]
        trades.append(trade)

    return (
        capital,
        trades,
        decisions,
        risk_rejections,
    )


def summarize(trades):
    if not trades:
        return None

    wins = [
        t for t in trades
        if t["pnl"] > 0
    ]

    losses = [
        t for t in trades
        if t["pnl"] < 0
    ]

    return {
        "count": len(trades),
        "wins": len(wins),
        "losses": len(losses),
        "pnl": sum(t["pnl"] for t in trades),
        "avg_pnl": (
            sum(t["pnl"] for t in trades)
            / len(trades)
        ),
        "avg_mfe": (
            sum(t["mfe"] for t in trades)
            / len(trades)
        ),
        "avg_mae": (
            sum(t["mae"] for t in trades)
            / len(trades)
        ),
        "max_mfe": max(t["mfe"] for t in trades),
        "worst_mae": min(t["mae"] for t in trades),
    }


def print_group(title, trades):
    result = summarize(trades)

    print()
    print("-" * 78)
    print(title)
    print("-" * 78)

    if result is None:
        print("No trades.")
        return

    print(f"Trades           : {result['count']}")
    print(f"Wins             : {result['wins']}")
    print(f"Losses           : {result['losses']}")
    print(f"Total P/L        : ${result['pnl']:+.4f}")
    print(f"Average P/L      : ${result['avg_pnl']:+.4f}")
    print(
        f"Average MFE      : "
        f"{result['avg_mfe'] * 100:+.3f}%"
    )
    print(
        f"Average MAE      : "
        f"{result['avg_mae'] * 100:+.3f}%"
    )
    print(
        f"Maximum MFE      : "
        f"{result['max_mfe'] * 100:+.3f}%"
    )
    print(
        f"Worst MAE        : "
        f"{result['worst_mae'] * 100:+.3f}%"
    )


def main():
    print("=" * 78)
    print("MFE / MAE EXIT ANALYSIS")
    print("=" * 78)

    candles = get_historical_candles_100k(
        symbol=SYMBOL,
        interval=INTERVAL,
        candles_needed=CANDLES_NEEDED,
    )

    valid, reason = validate_candles(candles)

    print(f"Candles:     {len(candles)}")
    print(f"Validation:  {valid}")
    print(f"Reason:      {reason}")

    if not valid:
        raise RuntimeError(reason)

    (
        capital,
        trades,
        decisions,
        risk_rejections,
    ) = run_backtest(candles)

    realized = [
        t for t in trades
        if t["exit_reason"] != "BACKTEST_END"
    ]

    stop_losses = [
        t for t in realized
        if t["exit_reason"] == "STOP_LOSS"
    ]

    time_exits = [
        t for t in realized
        if t["exit_reason"] == "TIME_EXIT"
    ]

    forced = [
        t for t in trades
        if t["exit_reason"] == "BACKTEST_END"
    ]

    print()
    print("-" * 78)
    print("OVERALL")
    print("-" * 78)

    print(f"Starting Capital : ${STARTING_CAPITAL:.2f}")
    print(f"Final Capital    : ${capital:.2f}")
    print(
        f"Realized P/L     : "
        f"${sum(t['pnl'] for t in realized):+.4f}"
    )
    print(
        f"Dataset-End P/L  : "
        f"${sum(t['pnl'] for t in forced):+.4f}"
    )
    print(f"Realized Trades  : {len(realized)}")
    print(f"Risk Rejections  : {risk_rejections}")

    print_group(
        "STOP LOSS",
        stop_losses,
    )

    print_group(
        "TIME EXIT",
        time_exits,
    )

    # -------------------------------------------------------------
    # TIME EXIT BY SIDE
    # -------------------------------------------------------------
    buy_time = [
        t for t in time_exits
        if t["side"] == "BUY"
    ]

    sell_time = [
        t for t in time_exits
        if t["side"] == "SELL"
    ]

    print_group(
        "TIME EXIT — BUY",
        buy_time,
    )

    print_group(
        "TIME EXIT — SELL",
        sell_time,
    )

    # -------------------------------------------------------------
    # STOP LOSS BY REGIME
    # -------------------------------------------------------------
    regime_groups = {}

    for trade in stop_losses:
        regime_groups.setdefault(
            trade["regime"],
            [],
        ).append(trade)

    print()
    print("-" * 78)
    print("STOP LOSS — MFE / MAE BY REGIME")
    print("-" * 78)

    for regime, group in sorted(
        regime_groups.items()
    ):
        result = summarize(group)

        print(
            f"{regime:<20} "
            f"N {result['count']:>4} "
            f"Avg MFE "
            f"{result['avg_mfe'] * 100:+7.3f}% "
            f"Avg MAE "
            f"{result['avg_mae'] * 100:+7.3f}% "
            f"P/L "
            f"${result['pnl']:+9.3f}"
        )

    # -------------------------------------------------------------
    # TIME EXIT BY REGIME
    # -------------------------------------------------------------
    regime_groups = {}

    for trade in time_exits:
        regime_groups.setdefault(
            trade["regime"],
            [],
        ).append(trade)

    print()
    print("-" * 78)
    print("TIME EXIT — MFE / MAE BY REGIME")
    print("-" * 78)

    for regime, group in sorted(
        regime_groups.items()
    ):
        result = summarize(group)

        print(
            f"{regime:<20} "
            f"N {result['count']:>4} "
            f"Avg MFE "
            f"{result['avg_mfe'] * 100:+7.3f}% "
            f"Avg MAE "
            f"{result['avg_mae'] * 100:+7.3f}% "
            f"P/L "
            f"${result['pnl']:+9.3f}"
        )

    print()
    print("=" * 78)
    print("MFE / MAE ANALYSIS COMPLETE")
    print("=" * 78)


if __name__ == "__main__":
    main()
