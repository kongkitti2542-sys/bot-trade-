from backtest_data_100k import get_historical_candles_100k, validate_candles
from features import calculate_features
from regime import detect_regime
from strategy import analyze_market
from risk import evaluate_risk

SYMBOL = "BTCUSDT"
INTERVAL = "5m"
CANDLES_NEEDED = 100_000
STARTING_CAPITAL = 1000.0

MAX_HOLD_BARS = 288  # 24 hours on 5-minute candles


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


def run_backtest(candles):
    capital = STARTING_CAPITAL
    position = None
    trades = []

    decisions = {
        "BUY": 0,
        "SELL": 0,
        "WAIT": 0,
    }

    risk_rejections = 0

    for index in range(len(candles)):
        if index < 200:
            continue

        candle = candles[index]
        history = candles[:index + 1]

        # ---------------------------------------------------------
        # POSITION MANAGEMENT
        # ---------------------------------------------------------
        if position is not None:
            position["bars_held"] += 1

            # Stop Loss has priority.
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

    # -------------------------------------------------------------
    # DATASET-END EXIT
    # -------------------------------------------------------------
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

    return capital, trades, decisions, risk_rejections


def print_results(capital, trades, decisions, risk_rejections):
    realized = [
        trade
        for trade in trades
        if trade["exit_reason"] != "BACKTEST_END"
    ]

    forced = [
        trade
        for trade in trades
        if trade["exit_reason"] == "BACKTEST_END"
    ]

    wins = [
        trade
        for trade in realized
        if trade["pnl"] > 0
    ]

    losses = [
        trade
        for trade in realized
        if trade["pnl"] < 0
    ]

    realized_pnl = sum(trade["pnl"] for trade in realized)
    forced_pnl = sum(trade["pnl"] for trade in forced)

    gross_profit = sum(
        trade["pnl"]
        for trade in wins
    )

    gross_loss = abs(sum(
        trade["pnl"]
        for trade in losses
    ))

    profit_factor = (
        gross_profit / gross_loss
        if gross_loss > 0
        else None
    )

    print()
    print("=" * 70)
    print("TIME EXIT BACKTEST")
    print("=" * 70)

    print(f"Starting Capital : ${STARTING_CAPITAL:.2f}")
    print(f"Final Capital    : ${capital:.2f}")
    print(f"Realized P/L     : ${realized_pnl:+.4f}")
    print(f"Dataset-End P/L  : ${forced_pnl:+.4f}")

    print()
    print(f"Realized Trades  : {len(realized)}")
    print(f"Wins             : {len(wins)}")
    print(f"Losses           : {len(losses)}")

    if realized:
        print(
            f"Win Rate         : "
            f"{len(wins) / len(realized) * 100:.2f}%"
        )

    if profit_factor is not None:
        print(f"Profit Factor    : {profit_factor:.4f}")
    else:
        print("Profit Factor    : N/A")

    print()
    print(f"BUY Decisions    : {decisions['BUY']}")
    print(f"SELL Decisions   : {decisions['SELL']}")
    print(f"WAIT Decisions   : {decisions['WAIT']}")
    print(f"Risk Rejections  : {risk_rejections}")

    print()
    print("-" * 70)
    print("EXIT REASONS")
    print("-" * 70)

    exit_counts = {}

    for trade in trades:
        reason = trade["exit_reason"]
        exit_counts[reason] = exit_counts.get(reason, 0) + 1

    for reason, count in sorted(exit_counts.items()):
        print(f"{reason:<20} {count}")

    print()
    print("-" * 70)
    print("REALIZED TRADES")
    print("-" * 70)

    for number, trade in enumerate(realized, start=1):
        print(
            f"#{number:02d} "
            f"{trade['side']:4s} "
            f"{trade['regime']:14s} "
            f"Score {trade['score']:>4} "
            f"Bars {trade['bars_held']:>5} "
            f"P/L ${trade['pnl']:+.4f} "
            f"{trade['exit_reason']}"
        )

    print()
    print("=" * 70)


def main():
    print("=" * 70)
    print("LOADING 100K DATA")
    print("=" * 70)

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

    capital, trades, decisions, risk_rejections = run_backtest(
        candles
    )

    print_results(
        capital,
        trades,
        decisions,
        risk_rejections,
    )


if __name__ == "__main__":
    main()
