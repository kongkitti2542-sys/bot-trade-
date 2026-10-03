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

# Trail starts only after price has moved this far
TRAIL_STARTS = [0.005, 0.010, 0.015]

# Conservative ATR-based trailing distance.
TRAIL_ATR_MULTIPLIER = 2.0


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


def run_backtest(candles, trail_start):
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

            if position["side"] == "BUY":
                favorable = (
                    candle["high"] - entry
                ) / entry
            else:
                favorable = (
                    entry - candle["low"]
                ) / entry

            position["mfe"] = max(
                position["mfe"],
                favorable,
            )

            # -----------------------------------------------------
            # ACTIVATE TRAILING STOP
            # -----------------------------------------------------
            if (
                not position["trailing_active"]
                and position["mfe"] >= trail_start
            ):
                position["trailing_active"] = True

            # -----------------------------------------------------
            # UPDATE TRAILING STOP
            # -----------------------------------------------------
            if (
                position["trailing_active"]
                and features["atr14"] is not None
            ):
                trail_distance = (
                    features["atr14"]
                    * TRAIL_ATR_MULTIPLIER
                )

                if position["side"] == "BUY":
                    candidate = (
                        candle["high"]
                        - trail_distance
                    )

                    if position["trailing_stop"] is None:
                        position["trailing_stop"] = candidate
                    else:
                        position["trailing_stop"] = max(
                            position["trailing_stop"],
                            candidate,
                        )

                else:
                    candidate = (
                        candle["low"]
                        + trail_distance
                    )

                    if position["trailing_stop"] is None:
                        position["trailing_stop"] = candidate
                    else:
                        position["trailing_stop"] = min(
                            position["trailing_stop"],
                            candidate,
                        )

            # -----------------------------------------------------
            # STOP CHECK
            # -----------------------------------------------------
            if position["side"] == "BUY":

                if (
                    position["trailing_active"]
                    and position["trailing_stop"] is not None
                    and candle["low"]
                    <= position["trailing_stop"]
                ):
                    trade = close_position(
                        position,
                        position["trailing_stop"],
                        candle["time"],
                        "TRAILING_STOP",
                    )

                    capital += trade["pnl"]
                    trades.append(trade)
                    position = None
                    continue

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

                if (
                    position["trailing_active"]
                    and position["trailing_stop"] is not None
                    and candle["high"]
                    >= position["trailing_stop"]
                ):
                    trade = close_position(
                        position,
                        position["trailing_stop"],
                        candle["time"],
                        "TRAILING_STOP",
                    )

                    capital += trade["pnl"]
                    trades.append(trade)
                    position = None
                    continue

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
            "trailing_active": False,
            "trailing_stop": None,
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


def summarize(capital, trades):
    realized = [
        t for t in trades
        if t["exit_reason"] != "BACKTEST_END"
    ]

    forced = [
        t for t in trades
        if t["exit_reason"] == "BACKTEST_END"
    ]

    wins = [
        t for t in realized
        if t["pnl"] > 0
    ]

    losses = [
        t for t in realized
        if t["pnl"] < 0
    ]

    gross_profit = sum(
        t["pnl"] for t in wins
    )

    gross_loss = abs(sum(
        t["pnl"] for t in losses
    ))

    profit_factor = (
        gross_profit / gross_loss
        if gross_loss > 0
        else None
    )

    exits = {}

    for trade in realized:
        reason = trade["exit_reason"]

        exits[reason] = (
            exits.get(reason, 0) + 1
        )

    return {
        "capital": capital,
        "realized_pnl": sum(
            t["pnl"] for t in realized
        ),
        "forced_pnl": sum(
            t["pnl"] for t in forced
        ),
        "trades": len(realized),
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": (
            len(wins) / len(realized) * 100
            if realized
            else 0
        ),
        "profit_factor": profit_factor,
        "exits": exits,
    }


def main():
    print("=" * 78)
    print("TRAILING STOP SENSITIVITY")
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

    print()
    print(
        f"Time Exit: {MAX_HOLD_BARS} bars "
        f"(24 hours)"
    )

    print(
        f"Trailing ATR Multiplier: "
        f"{TRAIL_ATR_MULTIPLIER}"
    )

    results = []

    for trail_start in TRAIL_STARTS:
        print()
        print(
            f"Running trail start "
            f"{trail_start * 100:.1f}%..."
        )

        (
            capital,
            trades,
            decisions,
            risk_rejections,
        ) = run_backtest(
            candles,
            trail_start,
        )

        result = summarize(
            capital,
            trades,
        )

        result["trail_start"] = trail_start
        result["risk_rejections"] = risk_rejections

        results.append(result)

    print()
    print("=" * 78)
    print("RESULTS")
    print("=" * 78)

    print(
        f"{'Trail':<10}"
        f"{'Final':>10}"
        f"{'Realized':>12}"
        f"{'Trades':>8}"
        f"{'Wins':>7}"
        f"{'Losses':>8}"
        f"{'WinRate':>9}"
        f"{'PF':>9}"
    )

    print("-" * 78)

    for result in results:
        pf = (
            f"{result['profit_factor']:.3f}"
            if result["profit_factor"] is not None
            else "N/A"
        )

        print(
            f"{result['trail_start'] * 100:>6.1f}%"
            f"{result['capital']:>10.2f}"
            f"{result['realized_pnl']:>+12.3f}"
            f"{result['trades']:>8}"
            f"{result['wins']:>7}"
            f"{result['losses']:>8}"
            f"{result['win_rate']:>8.2f}%"
            f"{pf:>9}"
        )

    print()
    print("-" * 78)
    print("EXIT BREAKDOWN")
    print("-" * 78)

    for result in results:
        print(
            f"Trail {result['trail_start'] * 100:.1f}% | "
            f"{result['exits']}"
        )

    print()
    print("=" * 78)
    print("SENSITIVITY TEST COMPLETE")
    print("=" * 78)


if __name__ == "__main__":
    main()
