from backtest_data_100k import get_historical_candles_100k
from incremental_features import IncrementalFeatures
from regime import detect_regime
from strategy import analyze_market
from risk import evaluate_risk

STARTING_CAPITAL = 1000.0
OOS_BOUNDARY = "2026-07-21T10:05:00+00:00"
MAX_TRADES = 10


def main():
    print("=" * 70)
    print("HISTORICAL PAPER SMOKE TEST — RESEARCH ONLY")
    print("=" * 70)

    candles = get_historical_candles_100k(
        symbol="BTCUSDT",
        interval="5m",
        candles_needed=100_000,
    )

    print(f"Candles: {len(candles)}")
    print(f"Paper Capital: ฿{STARTING_CAPITAL:.2f}")
    print(f"OOS Boundary: {OOS_BOUNDARY}")

    capital = STARTING_CAPITAL
    position = None
    trades = []
    feature_engine = IncrementalFeatures()

    for index, candle in enumerate(candles):
        features = feature_engine.update(candle)

        if index < 200:
            continue

        candle_time = candle["time"]

        if candle_time.isoformat() < OOS_BOUNDARY:
            continue

        if position is not None:
            if position["side"] == "BUY":
                if candle["low"] <= position["stop_loss"]:
                    exit_price = position["stop_loss"]
                    pnl = (
                        exit_price - position["entry_price"]
                    ) * position["position_size"]

                    capital += pnl

                    trades.append({
                        "side": position["side"],
                        "entry": position["entry_price"],
                        "exit": exit_price,
                        "pnl": pnl,
                        "reason": "STOP_LOSS",
                    })

                    position = None

            elif position["side"] == "SELL":
                if candle["high"] >= position["stop_loss"]:
                    exit_price = position["stop_loss"]
                    pnl = (
                        position["entry_price"] - exit_price
                    ) * position["position_size"]

                    capital += pnl

                    trades.append({
                        "side": position["side"],
                        "entry": position["entry_price"],
                        "exit": exit_price,
                        "pnl": pnl,
                        "reason": "STOP_LOSS",
                    })

                    position = None

            continue

        regime = detect_regime(features)
        decision = analyze_market(features, regime)

        if decision["signal"] == "WAIT":
            continue

        risk = evaluate_risk(
            decision=decision,
            features=features,
            capital=capital,
            daily_pnl=0.0,
            open_positions=0,
        )

        if not risk["allowed"]:
            continue

        position = {
            "side": decision["signal"],
            "entry_price": features["close"],
            "position_size": risk["position_size"],
            "stop_loss": risk["stop_loss"],
        }

        print()
        print(
            f"ENTRY #{len(trades) + 1}: "
            f"{position['side']} @ {position['entry_price']:.2f}"
        )
        print(f"Stop Loss: {position['stop_loss']:.2f}")

        if len(trades) >= MAX_TRADES:
            break

    print()
    print("=" * 70)
    print("RESULT")
    print("=" * 70)
    print(f"Starting Capital: ฿{STARTING_CAPITAL:.2f}")
    print(f"Ending Capital:   ฿{capital:.4f}")
    print(f"Closed Trades:    {len(trades)}")

    if trades:
        wins = sum(1 for trade in trades if trade["pnl"] > 0)
        losses = sum(1 for trade in trades if trade["pnl"] < 0)

        print(f"Wins:             {wins}")
        print(f"Losses:           {losses}")

        for index, trade in enumerate(trades, start=1):
            print(
                f"Trade {index}: "
                f"{trade['side']} "
                f"P/L ฿{trade['pnl']:.4f} "
                f"{trade['reason']}"
            )

    if position is not None:
        print("Open Position:    YES")
    else:
        print("Open Position:    NO")

    print()
    print("HISTORICAL PAPER SMOKE TEST: PASS")


if __name__ == "__main__":
    main()
