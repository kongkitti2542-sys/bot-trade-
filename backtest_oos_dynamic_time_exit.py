from backtest_oos_time_exit import (
    SYMBOL,
    INTERVAL,
    CANDLES_NEEDED,
    STARTING_CAPITAL,
    OOS_BOUNDARY,
    close_position,
    run_oos_backtest,
    summarize,
)
from backtest_data_100k import get_historical_candles_100k, validate_candles
from incremental_features import IncrementalFeatures
from regime import detect_regime
from strategy import analyze_market
from risk import evaluate_risk


DYNAMIC_CHECK_BARS = 144   # 12h
BASELINE_HOLD_BARS = 240   # 20h


def unrealized_pnl_percent(position, current_price):
    if position["side"] == "BUY":
        pnl = (
            current_price - position["entry_price"]
        ) * position["position_size"]
    else:
        pnl = (
            position["entry_price"] - current_price
        ) * position["position_size"]

    capital_basis = position["entry_price"] * position["position_size"]

    if capital_basis <= 0:
        return 0.0

    return (pnl / capital_basis) * 100.0


def run_dynamic_backtest(candles, boundary):
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

            # Stop loss first — same behavior as baseline.
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

            # Dynamic rule:
            # At 12h, close only if unrealized P/L is negative.
            if position["bars_held"] == DYNAMIC_CHECK_BARS:
                pnl_pct = unrealized_pnl_percent(
                    position,
                    candle["close"],
                )

                if pnl_pct < 0.0:
                    trade = close_position(
                        position,
                        candle["close"],
                        candle_time,
                        "DYNAMIC_TIME_EXIT_12H_NEGATIVE",
                    )
                    capital += trade["pnl"]
                    trades.append(trade)
                    position = None
                    continue

            # Baseline 20h time exit for positions that survive 12h.
            if position["bars_held"] >= BASELINE_HOLD_BARS:
                trade = close_position(
                    position,
                    candle["close"],
                    candle_time,
                    "TIME_EXIT_20H",
                )
                capital += trade["pnl"]
                trades.append(trade)
                position = None
                continue

            continue

        # OOS entries begin at the fixed boundary.
        if candle_time < boundary:
            continue

        regime = detect_regime(features)
        decision = analyze_market(features, regime)
        signal = decision["signal"]

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
            "entry_time": candle_time,
            "entry_price": features["close"],
            "position_size": risk["position_size"],
            "stop_loss": risk["stop_loss"],
            "regime": regime,
            "score": decision["score"],
            "bars_held": 0,
        }

    # Same dataset-end handling as baseline.
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


def summarize_dynamic(capital, trades, risk_rejections):
    realized = [
        t for t in trades
        if t["exit_reason"] != "BACKTEST_END"
    ]

    stop_losses = [
        t for t in realized
        if t["exit_reason"] == "STOP_LOSS"
    ]

    dynamic_exits = [
        t for t in realized
        if t["exit_reason"] == "DYNAMIC_TIME_EXIT_12H_NEGATIVE"
    ]

    time_exits = [
        t for t in realized
        if t["exit_reason"] == "TIME_EXIT_20H"
    ]

    wins = [t for t in realized if t["pnl"] > 0]
    losses = [t for t in realized if t["pnl"] < 0]

    gross_profit = sum(t["pnl"] for t in wins)
    gross_loss = abs(sum(t["pnl"] for t in losses))

    profit_factor = (
        gross_profit / gross_loss
        if gross_loss > 0
        else None
    )

    return {
        "final_capital": capital,
        "realized_pnl": sum(t["pnl"] for t in realized),
        "realized_trades": len(realized),
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": (
            len(wins) / len(realized) * 100
            if realized else 0.0
        ),
        "profit_factor": profit_factor,
        "stop_losses": len(stop_losses),
        "dynamic_exits": len(dynamic_exits),
        "time_exits_20h": len(time_exits),
        "risk_rejections": risk_rejections,
        "dataset_end": sum(
            t["pnl"]
            for t in trades
            if t["exit_reason"] == "BACKTEST_END"
        ),
    }


def main():
    print("=" * 110)
    print("OOS DYNAMIC TIME EXIT — RESEARCH ONLY")
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

    import datetime

    boundary = datetime.datetime.fromisoformat(
        OOS_BOUNDARY
    )

    print(f"First:         {candles[0]['time']}")
    print(f"Last:          {candles[-1]['time']}")
    print(f"OOS Boundary:  {OOS_BOUNDARY}")
    print()

    # Baseline — imported existing implementation.
    baseline_capital, baseline_trades, baseline_rejections = (
        run_oos_backtest(
            candles,
            max_hold_bars=BASELINE_HOLD_BARS,
            boundary=boundary,
        )
    )

    baseline = summarize(
        baseline_capital,
        baseline_trades,
        baseline_rejections,
    )

    # Dynamic candidate.
    dynamic_capital, dynamic_trades, dynamic_rejections = (
        run_dynamic_backtest(
            candles,
            boundary,
        )
    )

    dynamic = summarize_dynamic(
        dynamic_capital,
        dynamic_trades,
        dynamic_rejections,
    )

    print("=" * 110)
    print("BASELINE — 20h")
    print("=" * 110)

    for key, value in baseline.items():
        print(f"{key:<22}: {value}")

    print()
    print("=" * 110)
    print("DYNAMIC — 12h NEGATIVE EXIT + 20h OTHERWISE")
    print("=" * 110)

    for key, value in dynamic.items():
        print(f"{key:<22}: {value}")

    print()
    print("=" * 110)
    print("DELTA — DYNAMIC minus BASELINE")
    print("=" * 110)

    print(
        f"{'Final Capital':<22}: "
        f"{dynamic['final_capital'] - baseline['final_capital']:+.4f}"
    )
    print(
        f"{'Realized P/L':<22}: "
        f"{dynamic['realized_pnl'] - baseline['realized_pnl']:+.4f}"
    )
    print(
        f"{'Trades':<22}: "
        f"{dynamic['realized_trades'] - baseline['realized_trades']:+d}"
    )
    print(
        f"{'Wins':<22}: "
        f"{dynamic['wins'] - baseline['wins']:+d}"
    )
    print(
        f"{'Losses':<22}: "
        f"{dynamic['losses'] - baseline['losses']:+d}"
    )
    print(
        f"{'Stop Loss':<22}: "
        f"{dynamic['stop_losses'] - baseline['stop_losses']:+d}"
    )
    print(
        f"{'Risk Rejections':<22}: "
        f"{dynamic['risk_rejections'] - baseline['risk_rejections']:+d}"
    )

    print()
    print("=" * 110)
    print("RESEARCH ONLY — NO CORE FILES MODIFIED")
    print("=" * 110)


if __name__ == "__main__":
    main()
