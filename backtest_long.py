from backtest_data_long import get_historical_candles_long
from features import calculate_features
from regime import detect_regime
from strategy import analyze_market
from risk import evaluate_risk

SYMBOL = "BTCUSDT"
INTERVAL = "5m"
CANDLES_NEEDED = 20000
STARTING_CAPITAL = 1000.0


def new_regime_stats():
    return {
        "signals": 0,
        "trades": 0,
        "wins": 0,
        "losses": 0,
        "pnl": 0.0,
    }


def calculate_analytics(trades):
    if not trades:
        return {
            "wins": 0,
            "losses": 0,
            "win_rate": 0.0,
            "gross_profit": 0.0,
            "gross_loss": 0.0,
            "profit_factor": 0.0,
            "average_win": 0.0,
            "average_loss": 0.0,
            "largest_win": 0.0,
            "largest_loss": 0.0,
            "max_consecutive_losses": 0,
            "max_drawdown": 0.0,
        }

    pnl_values = [trade["pnl"] for trade in trades]

    wins = [pnl for pnl in pnl_values if pnl > 0]
    losses = [pnl for pnl in pnl_values if pnl < 0]

    gross_profit = sum(wins)
    gross_loss = abs(sum(losses))

    if gross_loss > 0:
        profit_factor = gross_profit / gross_loss
    else:
        profit_factor = float("inf") if gross_profit > 0 else 0.0

    equity = STARTING_CAPITAL
    peak_equity = STARTING_CAPITAL
    max_drawdown = 0.0
    max_consecutive_losses = 0
    current_consecutive_losses = 0

    for trade in trades:
        equity = trade["equity"]
        peak_equity = max(peak_equity, equity)

        drawdown = peak_equity - equity
        trade["drawdown"] = drawdown

        max_drawdown = max(max_drawdown, drawdown)

        if trade["pnl"] < 0:
            current_consecutive_losses += 1
            max_consecutive_losses = max(
                max_consecutive_losses,
                current_consecutive_losses,
            )
        else:
            current_consecutive_losses = 0

    return {
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": (len(wins) / len(trades)) * 100,
        "gross_profit": gross_profit,
        "gross_loss": gross_loss,
        "profit_factor": profit_factor,
        "average_win": (
            sum(wins) / len(wins)
            if wins else 0.0
        ),
        "average_loss": (
            sum(losses) / len(losses)
            if losses else 0.0
        ),
        "largest_win": max(wins) if wins else 0.0,
        "largest_loss": min(losses) if losses else 0.0,
        "max_consecutive_losses": max_consecutive_losses,
        "max_drawdown": max_drawdown,
    }


def run_backtest():
    print("=" * 60)
    print("PERSONAL TRADING BOT - LONG BACKTEST V1.0")
    print("=" * 60)

    candles = get_historical_candles_long(
        symbol=SYMBOL,
        interval=INTERVAL,
        candles_needed=CANDLES_NEEDED,
    )

    print(f"\nCandles: {len(candles)}")

    if len(candles) < 200:
        raise RuntimeError(
            "Not enough candles for EMA200."
        )

    capital = STARTING_CAPITAL
    daily_pnl = 0.0
    position = None

    trades = []

    signal_counts = {
        "BUY": 0,
        "SELL": 0,
        "WAIT": 0,
    }

    strategy_waits = 0
    risk_rejections = 0

    regime_stats = {}

    for index in range(len(candles)):
        history = candles[:index + 1]

        if len(history) < 200:
            continue

        current_candle = candles[index]

        # --------------------------------------------------
        # 1. MANAGE EXISTING POSITION
        # --------------------------------------------------
        if position is not None:
            stop_hit = False

            if position["side"] == "BUY":
                stop_hit = (
                    current_candle["low"]
                    <= position["stop_loss"]
                )

            elif position["side"] == "SELL":
                stop_hit = (
                    current_candle["high"]
                    >= position["stop_loss"]
                )

            if stop_hit:
                exit_price = position["stop_loss"]

                if position["side"] == "BUY":
                    pnl = (
                        exit_price
                        - position["entry_price"]
                    ) * position["position_size"]
                else:
                    pnl = (
                        position["entry_price"]
                        - exit_price
                    ) * position["position_size"]

                capital += pnl
                daily_pnl += pnl

                trade = {
                    "side": position["side"],
                    "entry_time": position["entry_time"],
                    "exit_time": current_candle["time"],
                    "entry_price": position["entry_price"],
                    "exit_price": exit_price,
                    "position_size": position["position_size"],
                    "position_value": position["position_value"],
                    "stop_loss": position["stop_loss"],
                    "stop_distance": position["stop_distance"],
                    "score": position["score"],
                    "confidence": position["confidence"],
                    "regime": position["regime"],
                    "pnl": pnl,
                    "exit_reason": "STOP_LOSS",
                    "equity": capital,
                }

                trades.append(trade)

                stats = regime_stats[
                    position["regime"]
                ]

                stats["trades"] += 1
                stats["pnl"] += pnl

                if pnl > 0:
                    stats["wins"] += 1
                elif pnl < 0:
                    stats["losses"] += 1

                position = None

            continue

        # --------------------------------------------------
        # 2. FEATURES
        # --------------------------------------------------
        features = calculate_features(history)

        # --------------------------------------------------
        # 3. REGIME
        # --------------------------------------------------
        regime = detect_regime(features)

        if regime not in regime_stats:
            regime_stats[regime] = new_regime_stats()

        # --------------------------------------------------
        # 4. STRATEGY
        # --------------------------------------------------
        decision = analyze_market(
            features,
            regime,
        )

        signal = decision["signal"]

        signal_counts[signal] += 1

        if signal == "WAIT":
            strategy_waits += 1
            continue

        regime_stats[regime]["signals"] += 1

        # --------------------------------------------------
        # 5. RISK
        # --------------------------------------------------
        risk = evaluate_risk(
            decision=decision,
            features=features,
            capital=capital,
            daily_pnl=daily_pnl,
            open_positions=0,
        )

        if not risk["allowed"]:
            risk_rejections += 1
            continue

        # --------------------------------------------------
        # 6. OPEN POSITION
        # --------------------------------------------------
        stop_distance = abs(
            features["close"] - risk["stop_loss"]
        )

        position = {
            "side": signal,
            "entry_time": current_candle["time"],
            "entry_price": features["close"],
            "position_size": risk["position_size"],
            "position_value": risk["position_value"],
            "stop_loss": risk["stop_loss"],
            "stop_distance": stop_distance,
            "score": decision["score"],
            "confidence": decision["confidence"],
            "regime": decision["regime"],
        }

    # ------------------------------------------------------
    # 7. CLOSE REMAINING POSITION
    # ------------------------------------------------------
    if position is not None:
        exit_price = candles[-1]["close"]

        if position["side"] == "BUY":
            pnl = (
                exit_price
                - position["entry_price"]
            ) * position["position_size"]
        else:
            pnl = (
                position["entry_price"]
                - exit_price
            ) * position["position_size"]

        capital += pnl

        trade = {
            "side": position["side"],
            "entry_time": position["entry_time"],
            "exit_time": candles[-1]["time"],
            "entry_price": position["entry_price"],
            "exit_price": exit_price,
            "position_size": position["position_size"],
            "position_value": position["position_value"],
            "stop_loss": position["stop_loss"],
            "stop_distance": position["stop_distance"],
            "score": position["score"],
            "confidence": position["confidence"],
            "regime": position["regime"],
            "pnl": pnl,
            "exit_reason": "BACKTEST_END",
            "equity": capital,
        }

        trades.append(trade)

        stats = regime_stats[position["regime"]]

        stats["trades"] += 1
        stats["pnl"] += pnl

        if pnl > 0:
            stats["wins"] += 1
        elif pnl < 0:
            stats["losses"] += 1

    # ------------------------------------------------------
    # 8. ANALYTICS
    # ------------------------------------------------------
    analytics = calculate_analytics(trades)

    total_pnl = capital - STARTING_CAPITAL

    print("\n" + "=" * 60)
    print("OVERALL RESULTS")
    print("=" * 60)

    print(f"Starting Capital:       ${STARTING_CAPITAL:.2f}")
    print(f"Final Capital:          ${capital:.2f}")
    print(f"Total P/L:              ${total_pnl:.4f}")
    print(f"Trades:                 {len(trades)}")
    print(f"Wins:                   {analytics['wins']}")
    print(f"Losses:                 {analytics['losses']}")
    print(f"Win Rate:               {analytics['win_rate']:.2f}%")

    print("\nRisk / Return:")
    print(f"Gross Profit:           ${analytics['gross_profit']:.4f}")
    print(f"Gross Loss:             ${analytics['gross_loss']:.4f}")
    print(f"Profit Factor:          {analytics['profit_factor']:.4f}")
    print(f"Average Win:            ${analytics['average_win']:.4f}")
    print(f"Average Loss:           ${analytics['average_loss']:.4f}")
    print(f"Largest Win:            ${analytics['largest_win']:.4f}")
    print(f"Largest Loss:           ${analytics['largest_loss']:.4f}")
    print(
        "Max Consecutive Losses: "
        f"{analytics['max_consecutive_losses']}"
    )
    print(f"Max Drawdown:           ${analytics['max_drawdown']:.4f}")

    print("\nDecision Flow:")
    print(f"BUY Signals:            {signal_counts['BUY']}")
    print(f"SELL Signals:           {signal_counts['SELL']}")
    print(f"WAIT Signals:           {signal_counts['WAIT']}")
    print(f"Strategy WAIT:          {strategy_waits}")
    print(f"Risk Rejections:        {risk_rejections}")

    print("\n" + "=" * 60)
    print("RESULTS BY MARKET REGIME")
    print("=" * 60)

    for regime, stats in sorted(regime_stats.items()):
        trades_count = stats["trades"]

        if trades_count > 0:
            win_rate = (
                stats["wins"]
                / trades_count
                * 100
            )
        else:
            win_rate = 0.0

        print(f"\n{regime}")
        print(f"  Signals:      {stats['signals']}")
        print(f"  Trades:       {trades_count}")
        print(f"  Wins:         {stats['wins']}")
        print(f"  Losses:       {stats['losses']}")
        print(f"  Win Rate:     {win_rate:.2f}%")
        print(f"  P/L:          ${stats['pnl']:.4f}")

    print("\n" + "=" * 60)
    print("TRADE SUMMARY")
    print("=" * 60)

    if not trades:
        print("No trades.")
    else:
        for number, trade in enumerate(
            trades,
            start=1,
        ):
            print(
                f"#{number:03d} "
                f"{trade['side']:4s} "
                f"{trade['regime']:15s} "
                f"Score={trade['score']:3d} "
                f"PnL=${trade['pnl']: .4f} "
                f"{trade['exit_reason']}"
            )


if __name__ == "__main__":
    run_backtest()
