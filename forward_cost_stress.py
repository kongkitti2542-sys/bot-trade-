from datetime import datetime

from backtest_data_100k import validate_candles
from research_data_cache import load_candles
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

VALIDATION_BOUNDARY = datetime.fromisoformat(
    "2026-07-23T04:45:00+00:00"
)

SLIPPAGE_LEVELS = {
    "0.00%": 0.0000,
    "0.02%": 0.0002,
    "0.05%": 0.0005,
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
                    trades.append(
                        close_position(
                            position,
                            position["stop_loss"],
                            candle_time,
                            "STOP_LOSS",
                        )
                    )
                    capital += trades[-1]["pnl"]
                    position = None
                    continue

            elif position["side"] == "SELL":
                if candle["high"] >= position["stop_loss"]:
                    trades.append(
                        close_position(
                            position,
                            position["stop_loss"],
                            candle_time,
                            "STOP_LOSS",
                        )
                    )
                    capital += trades[-1]["pnl"]
                    position = None
                    continue

            if position["bars_held"] >= MAX_HOLD_BARS:
                trades.append(
                    close_position(
                        position,
                        candle["close"],
                        candle_time,
                        "TIME_EXIT",
                    )
                )
                capital += trades[-1]["pnl"]
                position = None
                continue

            continue

        if candle_time < VALIDATION_BOUNDARY:
            continue

        regime = detect_regime(features)
        decision = analyze_market(features, regime)

        if decision["signal"] == "WAIT":
            continue

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

    return trades, risk_rejections


def calculate_costs(trades, slippage_rate):
    realized = [
        t for t in trades
        if t["exit_reason"] != "BACKTEST_END"
    ]

    gross = sum(t["pnl"] for t in realized)
    fees = 0.0
    slippage = 0.0

    for t in realized:
        entry = t["entry_price"]
        exit_price = t["exit_price"]
        size = t["position_size"]

        if t["side"] == "BUY":
            entry_exec = entry * (1 + slippage_rate)
            exit_exec = exit_price * (1 - slippage_rate)

            adjusted_gross = (
                exit_exec - entry_exec
            ) * size
        else:
            entry_exec = entry * (1 - slippage_rate)
            exit_exec = exit_price * (1 + slippage_rate)

            adjusted_gross = (
                entry_exec - exit_exec
            ) * size

        fees += (
            entry_exec * size * FEE_RATE
            + exit_exec * size * FEE_RATE
        )

        slippage += (
            abs(entry_exec - entry) * size
            + abs(exit_exec - exit_price) * size
        )

    net = gross - fees - slippage

    return {
        "trades": len(realized),
        "gross": gross,
        "fees": fees,
        "slippage": slippage,
        "net": net,
        "equity": STARTING_CAPITAL + net,
    }


def main():
    print("=" * 100)
    print("FORWARD SCORE 60-79 — COST STRESS TEST")
    print("=" * 100)

    candles = load_candles("btc_usdt_5m_100k.json")

    validation = validate_candles(candles)

    if not validation["valid"]:
        raise RuntimeError(
            f"Dataset validation failed: {validation['reason']}"
        )

    trades, risk_rejections = run_filtered_backtest(candles)

    print(f"Candles          : {len(candles)}")
    print(f"Validation start : {VALIDATION_BOUNDARY}")
    print(f"Fee              : {FEE_RATE * 100:.2f}% / side")
    print(f"Risk rejections  : {risk_rejections}")
    print()

    print("-" * 100)
    print(
        f"{'SLIPPAGE':<12}"
        f"{'TRADES':>8}"
        f"{'GROSS':>14}"
        f"{'FEES':>14}"
        f"{'SLIPPAGE':>14}"
        f"{'NET':>14}"
        f"{'EQUITY':>14}"
    )
    print("-" * 100)

    for label, rate in SLIPPAGE_LEVELS.items():
        r = calculate_costs(trades, rate)

        print(
            f"{label:<12}"
            f"{r['trades']:>8}"
            f"${r['gross']:>13.4f}"
            f"${r['fees']:>13.4f}"
            f"${r['slippage']:>13.4f}"
            f"${r['net']:>13.4f}"
            f"${r['equity']:>13.4f}"
        )

    print("-" * 100)
    print("Research only. No Core files modified.")


if __name__ == "__main__":
    main()
