from backtest_data_long import get_historical_candles_long
from features import calculate_features
from regime import detect_regime
from strategy import analyze_market
from risk import evaluate_risk

SYMBOL = "BTCUSDT"
INTERVAL = "5m"
CANDLES_NEEDED = 20000

STARTING_CAPITAL = 1000.0


def empty_trade():
    return {
        "side": None,
        "entry_time": None,
        "exit_time": None,
        "entry_price": 0.0,
        "exit_price": 0.0,
        "position_size": 0.0,
        "position_value": 0.0,
        "stop_loss": 0.0,
        "stop_distance": 0.0,
        "score": 0,
        "confidence": 0,
        "regime": None,
        "pnl": 0.0,
        "exit_reason": None,
        "bars_held": 0,
        "mfe": 0.0,
        "mae": 0.0,
        "equity": 0.0,
    }


def calculate_trade_metrics(trade):
    entry = trade["entry_price"]
    side = trade["side"]

    if entry <= 0:
        trade["mfe"] = 0.0
        trade["mae"] = 0.0
        return

    if side == "BUY":
        trade["mfe"] = (
            trade["max_favorable_price"] - entry
        ) / entry

        trade["mae"] = (
            trade["max_adverse_price"] - entry
        ) / entry

    elif side == "SELL":
        trade["mfe"] = (
            entry - trade["max_favorable_price"]
        ) / entry

        trade["mae"] = (
            entry - trade["max_adverse_price"]
        ) / entry


def run_backtest():
    print("=" * 60)
    print("PERSONAL TRADING BOT - RESEARCH BACKTEST V2.0")
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
    position = None

    trades = []

    signal_counts = {
        "BUY": 0,
        "SELL": 0,
        "WAIT": 0,
    }

    strategy_waits = 0
    risk_rejections = 0

    daily_pnl = 0.0
    current_day = None

    for index in range(len(candles)):
        history = candles[:index + 1]
        current_candle = candles[index]

        if len(history) < 200:
            continue

        candle_day = current_candle["time"].date()

        # --------------------------------------------------
        # DAILY P/L RESET
        # --------------------------------------------------
        if current_day != candle_day:
            current_day = candle_day
            daily_pnl = 0.0

        # --------------------------------------------------
        # EXISTING POSITION
        # --------------------------------------------------
        if position is not None:
            position["bars_held"] += 1

            if position["side"] == "BUY":
                position["max_favorable_price"] = max(
                    position["max_favorable_price"],
                    current_candle["high"],
                )

                position["max_adverse_price"] = min(
                    position["max_adverse_price"],
                    current_candle["low"],
                )

                stop_hit = (
                    current_candle["low"]
                    <= position["stop_loss"]
                )

            else:
                position["max_favorable_price"] = min(
                    position["max_favorable_price"],
                    current_candle["low"],
                )

                position["max_adverse_price"] = max(
                    position["max_adverse_price"],
                    current_candle["high"],
                )

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

                trade = empty_trade()

                trade.update({
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
                    "bars_held": position["bars_held"],
                    "equity": capital,
                    "max_favorable_price": position[
                        "max_favorable_price"
                    ],
                    "max_adverse_price": position[
                        "max_adverse_price"
                    ],
                })

                calculate_trade_metrics(trade)

                trades.append(trade)

                position = None

            continue

        # --------------------------------------------------
        # FEATURES
        # --------------------------------------------------
        features = calculate_features(history)

        # --------------------------------------------------
        # REGIME
        # --------------------------------------------------
        regime = detect_regime(features)

        # --------------------------------------------------
        # STRATEGY
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
        # RISK
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
        # OPEN POSITION
        # --------------------------------------------------
        position = {
            "side": decision["signal"],
            "entry_time": current_candle["time"],
            "entry_price": features["close"],
            "position_size": risk["position_size"],
            "position_value": risk["position_value"],
            "stop_loss": risk["stop_loss"],
            "stop_distance": abs(
                features["close"]
                - risk["stop_loss"]
            ),
            "score": decision["score"],
            "confidence": decision["confidence"],
            "regime": decision["regime"],
            "bars_held": 0,
            "max_favorable_price": features["close"],
            "max_adverse_price": features["close"],
        }

    # ------------------------------------------------------
    # OPEN POSITION AT DATASET END
    # ------------------------------------------------------
    if position is not None:
        last_candle = candles[-1]
        exit_price = last_candle["close"]

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

        trade = empty_trade()

        trade.update({
            "side": position["side"],
            "entry_time": position["entry_time"],
            "exit_time": last_candle["time"],
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
            "bars_held": position["bars_held"],
            "equity": capital,
            "max_favorable_price": position[
                "max_favorable_price"
            ],
            "max_adverse_price": position[
                "max_adverse_price"
            ],
        })

        calculate_trade_metrics(trade)

        trades.append(trade)

    # ------------------------------------------------------
    # RESULTS
    # ------------------------------------------------------
    realized_trades = [
        trade
        for trade in trades
        if trade["exit_reason"] != "BACKTEST_END"
    ]

    forced_end_trades = [
        trade
        for trade in trades
        if trade["exit_reason"] == "BACKTEST_END"
    ]

    realized_pnl = sum(
        trade["pnl"]
        for trade in realized_trades
    )

    forced_end_pnl = sum(
        trade["pnl"]
        for trade in forced_end_trades
    )

    total_pnl = capital - STARTING_CAPITAL

    wins = [
        trade
        for trade in realized_trades
        if trade["pnl"] > 0
    ]

    losses = [
        trade
        for trade in realized_trades
        if trade["pnl"] < 0
    ]

    gross_profit = sum(
        trade["pnl"] for trade in wins
    )

    gross_loss = abs(sum(
        trade["pnl"] for trade in losses
    ))

    if gross_loss > 0:
        profit_factor = (
            gross_profit / gross_loss
        )
    else:
        profit_factor = float("inf")

    print("\n" + "=" * 60)
    print("RESEARCH RESULTS")
    print("=" * 60)

    print(f"Starting Capital:       ${STARTING_CAPITAL:.2f}")
    print(f"Final Capital:          ${capital:.2f}")
    print(f"Total P/L:              ${total_pnl:.4f}")

    print("\nRealized Trades:")
    print(f"Trades:                 {len(realized_trades)}")
    print(f"Wins:                   {len(wins)}")
    print(f"Losses:                 {len(losses)}")

    if realized_trades:
        print(
            "Win Rate:               "
            f"{len(wins) / len(realized_trades) * 100:.2f}%"
        )
    else:
        print("Win Rate:               0.00%")

    print(f"Gross Profit:           ${gross_profit:.4f}")
    print(f"Gross Loss:             ${gross_loss:.4f}")
    print(f"Profit Factor:          {profit_factor:.4f}")

    print("\nForced Dataset-End Close:")
    print(f"Trades:                 {len(forced_end_trades)}")
    print(f"P/L:                    ${forced_end_pnl:.4f}")

    print("\nDecision Flow:")
    print(f"BUY Signals:            {signal_counts['BUY']}")
    print(f"SELL Signals:           {signal_counts['SELL']}")
    print(f"WAIT Signals:           {signal_counts['WAIT']}")
    print(f"Strategy WAIT:          {strategy_waits}")
    print(f"Risk Rejections:        {risk_rejections}")

    print("\nTrade Research Detail:")
    print("-" * 60)

    for number, trade in enumerate(
        trades,
        start=1,
    ):
        print(
            f"\nTrade #{number}"
        )
        print(
            f"Side:           {trade['side']}"
        )
        print(
            f"Regime:         {trade['regime']}"
        )
        print(
            f"Score:          {trade['score']}"
        )
        print(
            f"Confidence:     {trade['confidence']}"
        )
        print(
            f"Entry:          {trade['entry_price']:.2f}"
        )
        print(
            f"Exit:           {trade['exit_price']:.2f}"
        )
        print(
            f"Stop:           {trade['stop_loss']:.2f}"
        )
        print(
            f"Bars Held:      {trade['bars_held']}"
        )
        print(
            f"MFE:            {trade['mfe'] * 100:.4f}%"
        )
        print(
            f"MAE:            {trade['mae'] * 100:.4f}%"
        )
        print(
            f"P/L:            ${trade['pnl']:.4f}"
        )
        print(
            f"Equity:         ${trade['equity']:.4f}"
        )
        print(
            f"Exit Reason:    {trade['exit_reason']}"
        )


if __name__ == "__main__":
    run_backtest()
