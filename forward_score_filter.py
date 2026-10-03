from datetime import datetime

from backtest_data_100k import get_historical_candles_100k, validate_candles
from incremental_features import IncrementalFeatures
from regime import detect_regime
from strategy import analyze_market
from risk import evaluate_risk

SYMBOL = "BTCUSDT"
INTERVAL = "5m"
CANDLES_NEEDED = 100000

STARTING_CAPITAL = 1000.0
MAX_HOLD_BARS = 240
FEE_RATE = 0.0005

# Forward validation begins here.
VALIDATION_BOUNDARY = datetime.fromisoformat(
    "2026-07-23T04:45:00+00:00"
)


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


def run_filtered_backtest(candles):
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

        if candle_time < VALIDATION_BOUNDARY:
            continue

        regime = detect_regime(features)
        decision = analyze_market(features, regime)

        if decision["signal"] == "WAIT":
            continue

        # Candidate filter selected from prior research.
        # Only scores 60-79 are allowed to enter.
        if not (60 <= decision["score"] <= 79):
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


def calculate_costs(trades):
    realized = [
        t for t in trades
        if t["exit_reason"] != "BACKTEST_END"
    ]

    gross = sum(t["pnl"] for t in realized)

    fees = sum(
        (
            t["entry_price"] * t["position_size"]
            + t["exit_price"] * t["position_size"]
        ) * FEE_RATE
        for t in realized
    )

    net = gross - fees

    wins = [t for t in realized if t["pnl"] > 0]
    losses = [t for t in realized if t["pnl"] < 0]

    gross_profit = sum(t["pnl"] for t in wins)
    gross_loss = abs(sum(t["pnl"] for t in losses))

    pf = (
        gross_profit / gross_loss
        if gross_loss > 0
        else float("inf")
    )

    return {
        "realized": realized,
        "gross": gross,
        "fees": fees,
        "net": net,
        "final_net_equity": STARTING_CAPITAL + net,
        "wins": len(wins),
        "losses": len(losses),
        "pf": pf,
    }


def main():
    print("=" * 90)
    print("FORWARD SCORE 60-79 VALIDATION")
    print("=" * 90)

    candles = get_historical_candles_100k(
        symbol=SYMBOL,
        interval=INTERVAL,
        candles_needed=CANDLES_NEEDED,
    )

    valid, reason = validate_candles(candles)

    if not valid:
        raise RuntimeError(
            f"Dataset validation failed: {reason}"
        )

    print(f"Candles       : {len(candles)}")
    print(f"Dataset first : {candles[0]['time']}")
    print(f"Dataset last  : {candles[-1]['time']}")
    print(f"Validation    : {VALIDATION_BOUNDARY}")
    print(f"Hold          : {MAX_HOLD_BARS} bars / 20h")
    print(f"Fee           : {FEE_RATE * 100:.2f}% taker")
    print()

    capital, trades, risk_rejections = run_filtered_backtest(
        candles
    )

    result = calculate_costs(trades)

    print("-" * 90)
    print(f"Gross ending capital : ${capital:.4f}")
    print(f"Realized trades      : {len(result['realized'])}")
    print(f"Wins                 : {result['wins']}")
    print(f"Losses               : {result['losses']}")
    print(f"Gross P/L            : ${result['gross']:.4f}")
    print(f"Fees                 : ${result['fees']:.4f}")
    print(f"NET P/L AFTER FEE    : ${result['net']:.4f}")
    print(f"NET EQUITY           : ${result['final_net_equity']:.4f}")
    print(f"Profit Factor        : {result['pf']:.4f}")
    print(f"Risk rejections      : {risk_rejections}")
    print("-" * 90)

    print()
    print("Exit breakdown:")

    for reason in ("STOP_LOSS", "TIME_EXIT", "BACKTEST_END"):
        subset = [
            t for t in trades
            if t["exit_reason"] == reason
        ]

        print(
            f"{reason:15s} "
            f"{len(subset):4d} trades "
            f"Gross=${sum(t['pnl'] for t in subset):10.4f}"
        )

    print()
    print("Research only. No Core files modified.")


if __name__ == "__main__":
    main()
