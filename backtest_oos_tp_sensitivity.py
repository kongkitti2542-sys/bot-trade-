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

MAX_HOLD_BARS = 240  # 20h baseline

TP_LEVELS = {
    "TP_1.0": 0.010,
    "TP_1.5": 0.015,
    "TP_2.0": 0.020,
    "TP_3.0": 0.030,
    "TP_4.0": 0.040,
    "TP_5.0": 0.050,
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


def get_tp_price(position, tp_percent):
    entry = position["entry_price"]

    if position["side"] == "BUY":
        return entry * (1.0 + tp_percent)

    return entry * (1.0 - tp_percent)


def run_oos_backtest(candles, tp_percent, boundary):
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

            tp_price = get_tp_price(position, tp_percent)

            # Conservative rule:
            # if TP and SL are both touched in the same candle,
            # assume STOP_LOSS happened first.
            if position["side"] == "BUY":
                stop_hit = candle["low"] <= position["stop_loss"]
                tp_hit = candle["high"] >= tp_price

                if stop_hit:
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

                if tp_hit:
                    trade = close_position(
                        position,
                        tp_price,
                        candle_time,
                        "TAKE_PROFIT",
                    )
                    capital += trade["pnl"]
                    trades.append(trade)
                    position = None
                    continue

            elif position["side"] == "SELL":
                stop_hit = candle["high"] >= position["stop_loss"]
                tp_hit = candle["low"] <= tp_price

                if stop_hit:
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

                if tp_hit:
                    trade = close_position(
                        position,
                        tp_price,
                        candle_time,
                        "TAKE_PROFIT",
                    )
                    capital += trade["pnl"]
                    trades.append(trade)
                    position = None
                    continue

            if position["bars_held"] >= MAX_HOLD_BARS:
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


def summarize(capital, trades, risk_rejections):
    realized = [
        t for t in trades
        if t["exit_reason"] != "BACKTEST_END"
    ]

    wins = [
        t for t in realized
        if t["pnl"] > 0
    ]

    losses = [
        t for t in realized
        if t["pnl"] < 0
    ]

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
        "stop_losses": sum(
            1 for t in realized
            if t["exit_reason"] == "STOP_LOSS"
        ),
        "take_profits": sum(
            1 for t in realized
            if t["exit_reason"] == "TAKE_PROFIT"
        ),
        "time_exits": sum(
            1 for t in realized
            if t["exit_reason"] == "TIME_EXIT"
        ),
        "risk_rejections": risk_rejections,
        "dataset_end": sum(
            t["pnl"]
            for t in trades
            if t["exit_reason"] == "BACKTEST_END"
        ),
    }


def main():
    print("=" * 110)
    print("OUT-OF-SAMPLE TAKE PROFIT SENSITIVITY")
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

    boundary = datetime.datetime.fromisoformat(OOS_BOUNDARY)

    print(f"First:         {candles[0]['time']}")
    print(f"Last:          {candles[-1]['time']}")
    print(f"OOS Boundary:  {OOS_BOUNDARY}")
    print(f"Time Exit:     {MAX_HOLD_BARS} bars / 20h")
    print()

    print(
        f"{'TP':<10}"
        f"{'Final':>12}"
        f"{'P/L':>12}"
        f"{'Trades':>9}"
        f"{'Wins':>7}"
        f"{'Losses':>8}"
        f"{'WR%':>9}"
        f"{'PF':>9}"
        f"{'SL':>7}"
        f"{'TP Hit':>8}"
        f"{'Time':>8}"
    )

    print("-" * 110)

    for label, tp_percent in TP_LEVELS.items():
        capital, trades, risk_rejections = run_oos_backtest(
            candles,
            tp_percent=tp_percent,
            boundary=boundary,
        )

        summary = summarize(
            capital,
            trades,
            risk_rejections,
        )

        pf = (
            f"{summary['profit_factor']:.3f}"
            if summary["profit_factor"] is not None
            else "N/A"
        )

        print(
            f"{label:<10}"
            f"{summary['final_capital']:>12.2f}"
            f"{summary['realized_pnl']:>12.4f}"
            f"{summary['realized_trades']:>9}"
            f"{summary['wins']:>7}"
            f"{summary['losses']:>8}"
            f"{summary['win_rate']:>9.2f}"
            f"{pf:>9}"
            f"{summary['stop_losses']:>7}"
            f"{summary['take_profits']:>8}"
            f"{summary['time_exits']:>8}"
        )


if __name__ == "__main__":
    main()
