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
MAX_HOLD_BARS = 240  # 20h

TP_LEVELS = {
    "NO_TP": None,
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
    if tp_percent is None:
        return None

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

            if position["side"] == "BUY":
                stop_hit = candle["low"] <= position["stop_loss"]
                tp_hit = (
                    tp_price is not None
                    and candle["high"] >= tp_price
                )

                # Conservative same-candle rule:
                # SL is assumed to occur before TP.
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

            else:
                stop_hit = candle["high"] >= position["stop_loss"]
                tp_hit = (
                    tp_price is not None
                    and candle["low"] <= tp_price
                )

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


def pct(value, total):
    if total == 0:
        return 0.0
    return value / total * 100.0


def analyze(label, capital, trades, risk_rejections):
    realized = [
        t for t in trades
        if t["exit_reason"] != "BACKTEST_END"
    ]

    by_reason = {}

    for reason in [
        "TAKE_PROFIT",
        "TIME_EXIT",
        "STOP_LOSS",
    ]:
        subset = [
            t for t in realized
            if t["exit_reason"] == reason
        ]

        pnl = sum(t["pnl"] for t in subset)
        wins = sum(1 for t in subset if t["pnl"] > 0)
        losses = sum(1 for t in subset if t["pnl"] < 0)

        by_reason[reason] = {
            "count": len(subset),
            "pnl": pnl,
            "wins": wins,
            "losses": losses,
        }

    winners = [t for t in realized if t["pnl"] > 0]
    losers = [t for t in realized if t["pnl"] < 0]

    gross_profit = sum(t["pnl"] for t in winners)
    gross_loss = abs(sum(t["pnl"] for t in losers))

    pf = (
        gross_profit / gross_loss
        if gross_loss > 0
        else None
    )

    # Concentration of winner P/L.
    winner_sorted = sorted(
        winners,
        key=lambda t: t["pnl"],
        reverse=True,
    )

    top5 = sum(t["pnl"] for t in winner_sorted[:5])
    top10 = sum(t["pnl"] for t in winner_sorted[:10])

    print()
    print("=" * 100)
    print(label)
    print("=" * 100)

    print(f"Final Capital:     ${capital:.2f}")
    print(f"Realized P/L:      ${sum(t['pnl'] for t in realized):.4f}")
    print(f"Realized Trades:   {len(realized)}")
    print(f"Wins:              {len(winners)}")
    print(f"Losses:            {len(losers)}")
    print(f"Win Rate:          {pct(len(winners), len(realized)):.2f}%")
    print(
        f"Profit Factor:     "
        f"{pf:.3f}" if pf is not None else "Profit Factor:     N/A"
    )
    print(f"Risk Rejections:   {risk_rejections}")

    print()
    print("EXIT ATTRIBUTION")
    print("-" * 100)
    print(
        f"{'Exit':<16}"
        f"{'Count':>10}"
        f"{'Wins':>10}"
        f"{'Losses':>10}"
        f"{'P/L':>16}"
    )

    for reason in [
        "TAKE_PROFIT",
        "TIME_EXIT",
        "STOP_LOSS",
    ]:
        item = by_reason[reason]

        print(
            f"{reason:<16}"
            f"{item['count']:>10}"
            f"{item['wins']:>10}"
            f"{item['losses']:>10}"
            f"{item['pnl']:>16.4f}"
        )

    print()
    print("WINNER CONCENTRATION")
    print("-" * 100)
    print(f"Gross winner P/L:  ${gross_profit:.4f}")
    print(f"Top 5 winners:     ${top5:.4f}")
    print(f"Top 10 winners:    ${top10:.4f}")

    if gross_profit > 0:
        print(
            f"Top 5 share:       "
            f"{top5 / gross_profit * 100:.2f}%"
        )
        print(
            f"Top 10 share:      "
            f"{top10 / gross_profit * 100:.2f}%"
        )

    print()
    print("TP WINNER DETAILS")
    print("-" * 100)

    tp_winners = [
        t for t in realized
        if t["exit_reason"] == "TAKE_PROFIT"
        and t["pnl"] > 0
    ]

    for trade in sorted(
        tp_winners,
        key=lambda t: t["pnl"],
        reverse=True,
    )[:10]:
        print(
            f"{trade['entry_time']} "
            f"{trade['side']:<4} "
            f"{trade['regime']:<15} "
            f"score={trade['score']:>3} "
            f"hold={trade['bars_held']:>3} "
            f"P/L=${trade['pnl']:.4f}"
        )

    return {
        "label": label,
        "capital": capital,
        "realized_pnl": sum(t["pnl"] for t in realized),
        "realized_trades": len(realized),
        "wins": len(winners),
        "losses": len(losers),
        "profit_factor": pf,
        "tp_pnl": by_reason["TAKE_PROFIT"]["pnl"],
        "time_pnl": by_reason["TIME_EXIT"]["pnl"],
        "sl_pnl": by_reason["STOP_LOSS"]["pnl"],
    }


def main():
    print("=" * 100)
    print("OOS TAKE PROFIT ATTRIBUTION")
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

    import datetime

    boundary = datetime.datetime.fromisoformat(
        OOS_BOUNDARY
    )

    print(f"First:         {candles[0]['time']}")
    print(f"Last:          {candles[-1]['time']}")
    print(f"OOS Boundary:  {OOS_BOUNDARY}")
    print(f"Time Exit:     {MAX_HOLD_BARS} bars / 20h")

    results = []

    for label, tp_percent in TP_LEVELS.items():
        capital, trades, risk_rejections = run_oos_backtest(
            candles,
            tp_percent=tp_percent,
            boundary=boundary,
        )

        result = analyze(
            label,
            capital,
            trades,
            risk_rejections,
        )

        results.append(result)

    print()
    print("=" * 100)
    print("COMPARISON")
    print("=" * 100)

    print(
        f"{'Model':<10}"
        f"{'Final':>12}"
        f"{'P/L':>12}"
        f"{'Trades':>9}"
        f"{'Wins':>8}"
        f"{'Losses':>9}"
        f"{'PF':>9}"
        f"{'TP P/L':>12}"
        f"{'Time P/L':>12}"
        f"{'SL P/L':>12}"
    )

    print("-" * 100)

    for r in results:
        pf = (
            f"{r['profit_factor']:.3f}"
            if r["profit_factor"] is not None
            else "N/A"
        )

        print(
            f"{r['label']:<10}"
            f"{r['capital']:>12.2f}"
            f"{r['realized_pnl']:>12.4f}"
            f"{r['realized_trades']:>9}"
            f"{r['wins']:>8}"
            f"{r['losses']:>9}"
            f"{pf:>9}"
            f"{r['tp_pnl']:>12.4f}"
            f"{r['time_pnl']:>12.4f}"
            f"{r['sl_pnl']:>12.4f}"
        )


if __name__ == "__main__":
    main()
