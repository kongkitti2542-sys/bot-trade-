from backtest_data_100k import get_historical_candles_100k, validate_candles
from features import calculate_features
from regime import detect_regime
from strategy import analyze_market
from risk import evaluate_risk

SYMBOL = "BTCUSDT"
INTERVAL = "5m"
CANDLES_NEEDED = 100_000
STARTING_CAPITAL = 1000.0
PERIODS = 12


def run_backtest(candles):
    capital = STARTING_CAPITAL
    position = None
    trades = []
    decisions = {
        "BUY": 0,
        "SELL": 0,
        "WAIT": 0,
    }

    for index in range(len(candles)):
        if index < 200:
            continue

        candle = candles[index]
        history = candles[:index + 1]

        if position is not None:
            if position["side"] == "BUY":
                if candle["low"] <= position["stop_loss"]:
                    exit_price = position["stop_loss"]
                    pnl = (
                        exit_price - position["entry_price"]
                    ) * position["position_size"]

                    trades.append({
                        "entry_time": position["entry_time"],
                        "exit_time": candle["time"],
                        "side": "BUY",
                        "regime": position["regime"],
                        "score": position["score"],
                        "pnl": pnl,
                        "exit_reason": "STOP_LOSS",
                    })

                    capital += pnl
                    position = None

            elif position["side"] == "SELL":
                if candle["high"] >= position["stop_loss"]:
                    exit_price = position["stop_loss"]
                    pnl = (
                        position["entry_price"] - exit_price
                    ) * position["position_size"]

                    trades.append({
                        "entry_time": position["entry_time"],
                        "exit_time": candle["time"],
                        "side": "SELL",
                        "regime": position["regime"],
                        "score": position["score"],
                        "pnl": pnl,
                        "exit_reason": "STOP_LOSS",
                    })

                    capital += pnl
                    position = None

            continue

        features = calculate_features(history)
        regime = detect_regime(features)
        decision = analyze_market(features, regime)

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
            continue

        position = {
            "side": signal,
            "entry_time": candle["time"],
            "entry_price": features["close"],
            "position_size": risk["position_size"],
            "stop_loss": risk["stop_loss"],
            "regime": regime,
            "score": decision["score"],
        }

    # Dataset-end position is deliberately separated.
    if position is not None:
        last_price = candles[-1]["close"]

        if position["side"] == "BUY":
            pnl = (
                last_price - position["entry_price"]
            ) * position["position_size"]
        else:
            pnl = (
                position["entry_price"] - last_price
            ) * position["position_size"]

        trades.append({
            "entry_time": position["entry_time"],
            "exit_time": candles[-1]["time"],
            "side": position["side"],
            "regime": position["regime"],
            "score": position["score"],
            "pnl": pnl,
            "exit_reason": "BACKTEST_END",
        })

        capital += pnl

    return capital, trades, decisions


def period_stats(trades, start_time, end_time):
    period_trades = [
        trade for trade in trades
        if start_time <= trade["entry_time"] < end_time
    ]

    realized = [
        trade for trade in period_trades
        if trade["exit_reason"] != "BACKTEST_END"
    ]

    forced = [
        trade for trade in period_trades
        if trade["exit_reason"] == "BACKTEST_END"
    ]

    realized_pnl = sum(t["pnl"] for t in realized)
    forced_pnl = sum(t["pnl"] for t in forced)

    wins = sum(1 for t in realized if t["pnl"] > 0)
    losses = sum(1 for t in realized if t["pnl"] < 0)

    gross_profit = sum(
        t["pnl"] for t in realized if t["pnl"] > 0
    )

    gross_loss = abs(sum(
        t["pnl"] for t in realized if t["pnl"] < 0
    ))

    if gross_loss > 0:
        profit_factor = gross_profit / gross_loss
    else:
        profit_factor = None

    return {
        "trades": len(realized),
        "wins": wins,
        "losses": losses,
        "pnl": realized_pnl,
        "forced_pnl": forced_pnl,
        "profit_factor": profit_factor,
    }


def main():
    print("=" * 70)
    print("PERIOD ANALYSIS BACKTEST")
    print("=" * 70)

    candles = get_historical_candles_100k(
        symbol=SYMBOL,
        interval=INTERVAL,
        candles_needed=CANDLES_NEEDED,
    )

    valid, reason = validate_candles(candles)

    print(f"Candles:    {len(candles)}")
    print(f"Validation: {valid}")
    print(f"Reason:      {reason}")

    if not valid:
        raise RuntimeError(
            f"Dataset validation failed: {reason}"
        )

    final_capital, trades, decisions = run_backtest(candles)

    total_realized = sum(
        t["pnl"]
        for t in trades
        if t["exit_reason"] != "BACKTEST_END"
    )

    forced_end = sum(
        t["pnl"]
        for t in trades
        if t["exit_reason"] == "BACKTEST_END"
    )

    print()
    print("-" * 70)
    print("OVERALL")
    print("-" * 70)
    print(f"Starting Capital : ${STARTING_CAPITAL:.2f}")
    print(f"Final Capital    : ${final_capital:.2f}")
    print(f"Realized P/L     : ${total_realized:+.4f}")
    print(f"Dataset-End P/L  : ${forced_end:+.4f}")
    print(f"Total Trades     : {len(trades)}")
    print(f"BUY Decisions    : {decisions['BUY']}")
    print(f"SELL Decisions   : {decisions['SELL']}")
    print(f"WAIT Decisions   : {decisions['WAIT']}")

    start_time = candles[0]["time"]
    end_time = candles[-1]["time"]

    total_seconds = (end_time - start_time).total_seconds()
    period_seconds = total_seconds / PERIODS

    print()
    print("-" * 70)
    print(f"PERIOD ANALYSIS ({PERIODS} EQUAL PERIODS)")
    print("-" * 70)

    for number in range(PERIODS):
        period_start = start_time + __import__("datetime").timedelta(
            seconds=period_seconds * number
        )

        period_end = (
            end_time
            if number == PERIODS - 1
            else start_time + __import__("datetime").timedelta(
                seconds=period_seconds * (number + 1)
            )
        )

        stats = period_stats(
            trades,
            period_start,
            period_end,
        )

        pf = (
            f"{stats['profit_factor']:.2f}"
            if stats["profit_factor"] is not None
            else "N/A"
        )

        print(
            f"P{number + 1:02d} | "
            f"{period_start:%Y-%m-%d} → {period_end:%Y-%m-%d} | "
            f"Trades {stats['trades']:2d} | "
            f"W {stats['wins']:2d} | "
            f"L {stats['losses']:2d} | "
            f"P/L ${stats['pnl']:+.2f} | "
            f"Forced ${stats['forced_pnl']:+.2f} | "
            f"PF {pf}"
        )

    print()
    print("=" * 70)
    print("PERIOD ANALYSIS COMPLETE")
    print("=" * 70)


if __name__ == "__main__":
    main()
