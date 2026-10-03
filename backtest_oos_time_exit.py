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

    # A position still open at the end is reported as dataset-end,
    # but is not included in realized OOS performance.
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

    stop_losses = [
        t for t in realized
        if t["exit_reason"] == "STOP_LOSS"
    ]

    time_exits = [
        t for t in realized
        if t["exit_reason"] == "TIME_EXIT"
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
        "stop_losses": len(stop_losses),
        "time_exits": len(time_exits),
        "risk_rejections": risk_rejections,
        "dataset_end": sum(
            t["pnl"]
            for t in trades
            if t["exit_reason"] == "BACKTEST_END"
        ),
    }


def main():
    print("=" * 100)
    print("OUT-OF-SAMPLE TIME EXIT")
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

    results = []

    for label, bars in TEST_HOLDS.items():
        capital, trades, risk_rejections = run_oos_backtest(
            candles,
            max_hold_bars=bars,
            boundary=first_time.fromisoformat(OOS_BOUNDARY)
            if False
            else __import__("datetime").datetime.fromisoformat(OOS_BOUNDARY),
        )

        summary = summarize(
            capital,
            trades,
            risk_rejections,
        )

        results.append((label, bars, summary))

    print("-" * 100)
    print(
        f"{'Hold':<8}"
        f"{'Bars':>6}"
        f"{'Final':>12}"
        f"{'P/L':>12}"
        f"{'Trades':>8}"
        f"{'Wins':>7}"
        f"{'Loss':>7}"
        f"{'WR':>9}"
        f"{'PF':>9}"
        f"{'SL':>7}"
        f"{'Time':>8}"
        f"{'End':>10}"
    )
    print("-" * 100)

    for label, bars, summary in results:
        pf = (
            f"{summary['profit_factor']:.3f}"
            if summary["profit_factor"] is not None
            else "N/A"
        )

        print(
            f"{label:<8}"
            f"{bars:>6}"
            f"{summary['final_capital']:>12.2f}"
            f"{summary['realized_pnl']:>12.3f}"
            f"{summary['realized_trades']:>8}"
            f"{summary['wins']:>7}"
            f"{summary['losses']:>7}"
            f"{summary['win_rate']:>8.2f}%"
            f"{pf:>9}"
            f"{summary['stop_losses']:>7}"
            f"{summary['time_exits']:>8}"
            f"{summary['dataset_end']:>10.3f}"
        )

    print("-" * 100)
    print("Research only. No Core files were modified.")


if __name__ == "__main__":
    main()
