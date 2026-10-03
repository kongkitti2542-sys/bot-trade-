from backtest_data_100k import get_historical_candles_100k, validate_candles
from incremental_features import IncrementalFeatures
from regime import detect_regime
from strategy import analyze_market
from risk import evaluate_risk

SYMBOL = "BTCUSDT"
INTERVAL = "5m"
CANDLES_NEEDED = 100_000
STARTING_CAPITAL = 1000.0

PERIODS = 12

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


def run_backtest(candles, max_hold_bars):
    capital = STARTING_CAPITAL
    position = None
    trades = []
    risk_rejections = 0
    feature_engine = IncrementalFeatures()

    for index, candle in enumerate(candles):
        features = feature_engine.update(candle)

        if index < 200:
            continue

        if position is not None:
            position["bars_held"] += 1

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

            elif position["side"] == "SELL":
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

            if position["bars_held"] >= max_hold_bars:
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
            "entry_time": candle["time"],
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


def period_stats(trades, start_time, end_time):
    period_trades = [
        trade
        for trade in trades
        if start_time <= trade["entry_time"] < end_time
    ]

    realized = [
        trade
        for trade in period_trades
        if trade["exit_reason"] != "BACKTEST_END"
    ]

    wins = [
        trade for trade in realized
        if trade["pnl"] > 0
    ]

    losses = [
        trade for trade in realized
        if trade["pnl"] < 0
    ]

    gross_profit = sum(
        trade["pnl"] for trade in wins
    )

    gross_loss = abs(sum(
        trade["pnl"] for trade in losses
    ))

    profit_factor = (
        gross_profit / gross_loss
        if gross_loss > 0
        else None
    )

    return {
        "trades": len(realized),
        "wins": len(wins),
        "losses": len(losses),
        "pnl": sum(trade["pnl"] for trade in realized),
        "profit_factor": profit_factor,
    }


def main():
    print("=" * 100)
    print("PERIOD × TIME EXIT RESEARCH")
    print("=" * 100)

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
        raise RuntimeError(
            f"Dataset validation failed: {reason}"
        )

    start_time = candles[0]["time"]
    end_time = candles[-1]["time"]

    total_seconds = (
        end_time - start_time
    ).total_seconds()

    period_seconds = total_seconds / PERIODS

    period_bounds = []

    for number in range(PERIODS):
        period_start = (
            start_time
            + __import__("datetime").timedelta(
                seconds=period_seconds * number
            )
        )

        period_end = (
            end_time
            if number == PERIODS - 1
            else start_time
            + __import__("datetime").timedelta(
                seconds=period_seconds * (number + 1)
            )
        )

        period_bounds.append(
            (number + 1, period_start, period_end)
        )

    for label, bars in TEST_HOLDS.items():
        print()
        print("=" * 100)
        print(f"TIME EXIT: {label} ({bars} bars)")
        print("=" * 100)

        capital, trades, risk_rejections = run_backtest(
            candles,
            max_hold_bars=bars,
        )

        print(
            f"Overall Final Capital: ${capital:.2f} | "
            f"Risk Rejections: {risk_rejections}"
        )

        print("-" * 100)
        print(
            f"{'Period':<8}"
            f"{'Date Range':<25}"
            f"{'Trades':>8}"
            f"{'Wins':>7}"
            f"{'Loss':>7}"
            f"{'P/L':>12}"
            f"{'PF':>8}"
        )
        print("-" * 100)

        for number, period_start, period_end in period_bounds:
            stats = period_stats(
                trades,
                period_start,
                period_end,
            )

            pf = (
                f"{stats['profit_factor']:.3f}"
                if stats["profit_factor"] is not None
                else "N/A"
            )

            date_range = (
                f"{period_start:%Y-%m-%d} → "
                f"{period_end:%Y-%m-%d}"
            )

            print(
                f"P{number:02d}     "
                f"{date_range:<25}"
                f"{stats['trades']:>8}"
                f"{stats['wins']:>7}"
                f"{stats['losses']:>7}"
                f"${stats['pnl']:>11.3f}"
                f"{pf:>8}"
            )

    print()
    print("=" * 100)
    print("PERIOD × TIME EXIT RESEARCH COMPLETE")
    print("=" * 100)


if __name__ == "__main__":
    main()
