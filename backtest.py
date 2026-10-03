from backtest_data import get_historical_candles
from features import calculate_features
from regime import detect_regime
from strategy import analyze_market
from risk import evaluate_risk

SYMBOL = "BTCUSDT"
INTERVAL = "5m"
LIMIT = 1000

STARTING_CAPITAL = 1000.0


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

    win_rate = (len(wins) / len(trades)) * 100

    average_win = (
        sum(wins) / len(wins)
        if wins
        else 0.0
    )

    average_loss = (
        sum(losses) / len(losses)
        if losses
        else 0.0
    )

    largest_win = max(wins) if wins else 0.0
    largest_loss = min(losses) if losses else 0.0

    max_consecutive_losses = 0
    current_consecutive_losses = 0

    for pnl in pnl_values:
        if pnl < 0:
            current_consecutive_losses += 1
            max_consecutive_losses = max(
                max_consecutive_losses,
                current_consecutive_losses,
            )
        else:
            current_consecutive_losses = 0

    equity = STARTING_CAPITAL
    peak_equity = STARTING_CAPITAL
    max_drawdown = 0.0

    for trade in trades:
        equity = trade["equity"]

        peak_equity = max(
            peak_equity,
            equity,
        )

        drawdown = peak_equity - equity

        trade["drawdown"] = drawdown

        max_drawdown = max(
            max_drawdown,
            drawdown,
        )

    return {
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": win_rate,
        "gross_profit": gross_profit,
        "gross_loss": gross_loss,
        "profit_factor": profit_factor,
        "average_win": average_win,
        "average_loss": average_loss,
        "largest_win": largest_win,
        "largest_loss": largest_loss,
        "max_consecutive_losses": max_consecutive_losses,
        "max_drawdown": max_drawdown,
    }


def run_backtest():
    print("=" * 60)
    print("PERSONAL TRADING BOT - BACKTEST V1.2")
    print("=" * 60)

    candles = get_historical_candles(
        symbol=SYMBOL,
        interval=INTERVAL,
        limit=LIMIT,
    )

    print(f"\nCandles: {len(candles)}")

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

                trades.append({
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
                    "drawdown": 0.0,
                })

                position = None

            continue

        # --------------------------------------------------
        # 2. FEATURES
        # --------------------------------------------------
        features = calculate_features(history)

        # --------------------------------------------------
        # 3. MARKET REGIME
        # --------------------------------------------------
        regime = detect_regime(features)

        # --------------------------------------------------
        # 4. STRATEGY
        # --------------------------------------------------
        decision = analyze_market(
            features,
            regime,
        )

        signal_counts[decision["signal"]] += 1

        if decision["signal"] == "WAIT":
            strategy_waits += 1
            continue

        # --------------------------------------------------
        # 5. RISK MANAGER
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
        # 6. OPEN SIMULATED POSITION
        # --------------------------------------------------
        stop_distance = abs(
            features["close"] - risk["stop_loss"]
        )

        position = {
            "side": decision["signal"],
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
    # 7. CLOSE REMAINING POSITION AT LAST CLOSE
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

        trades.append({
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
            "drawdown": 0.0,
        })

        position = None

    # ------------------------------------------------------
    # 8. ANALYTICS
    # ------------------------------------------------------
    analytics = calculate_analytics(trades)

    total_pnl = capital - STARTING_CAPITAL

    print("\n" + "=" * 60)
    print("BACKTEST RESULTS")
    print("=" * 60)

    print(f"Starting Capital:       ${STARTING_CAPITAL:.2f}")
    print(f"Final Capital:          ${capital:.2f}")
    print(f"Total P/L:              ${total_pnl:.4f}")
    print(f"Trades:                 {len(trades)}")
    print(f"Wins:                   {analytics['wins']}")
    print(f"Losses:                 {analytics['losses']}")
    print(f"Win Rate:               {analytics['win_rate']:.2f}%")

    print("\nRisk / Return Analytics:")
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

    print("\nTrade Detail:")
    print("-" * 60)

    if not trades:
        print("No trades.")
    else:
        for number, trade in enumerate(
            trades,
            start=1,
        ):
            print(f"\nTrade #{number}")
            print(f"Side:           {trade['side']}")
            print(f"Entry Time:     {trade['entry_time']}")
            print(f"Exit Time:      {trade['exit_time']}")
            print(f"Regime:         {trade['regime']}")
            print(f"Score:          {trade['score']}")
            print(f"Confidence:     {trade['confidence']}")
            print(
                f"Entry:          "
                f"{trade['entry_price']:.2f}"
            )
            print(
                f"Exit:           "
                f"{trade['exit_price']:.2f}"
            )
            print(
                f"Stop Loss:      "
                f"{trade['stop_loss']:.2f}"
            )
            print(
                f"Stop Distance:  "
                f"{trade['stop_distance']:.2f}"
            )
            print(
                f"Position Value: "
                f"${trade['position_value']:.4f}"
            )
            print(
                f"P/L:            "
                f"${trade['pnl']:.4f}"
            )
            print(
                f"Equity:         "
                f"${trade['equity']:.4f}"
            )
            print(
                f"Drawdown:       "
                f"${trade['drawdown']:.4f}"
            )
            print(
                f"Exit Reason:    "
                f"{trade['exit_reason']}"
            )


if __name__ == "__main__":
    run_backtest()
