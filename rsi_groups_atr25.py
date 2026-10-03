from datetime import datetime

from incremental_features import IncrementalFeatures
from regime import detect_regime
from strategy import analyze_market
from risk_atr25_research import evaluate_risk
from research_data_cache import load_candles


STARTING_CAPITAL = 1000.0
MAX_HOLD_BARS = 240
FEE_RATE = 0.0005

SCORE_MIN = 60
SCORE_MAX = 79

TEST_START = datetime.fromisoformat(
    "2026-05-01T00:00:00+00:00"
)

TEST_END = datetime.fromisoformat(
    "2026-10-01T00:00:00+00:00"
)

SLIPPAGE_LEVELS = {
    "0.00%": 0.0000,
    "0.02%": 0.0002,
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
        "pnl": pnl,
        "exit_reason": exit_reason,
        "score": position["score"],
        "regime": position["regime"],
        "bars_held": position["bars_held"],
    }


def run_continuous_backtest(candles):
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

        if candle_time >= TEST_END:
            break

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

        if candle_time < TEST_START:
            continue

        regime = detect_regime(features)
        decision = analyze_market(features, regime)

        if decision["signal"] == "WAIT":
            continue

        if regime != "TREND_UP" or decision["signal"] != "BUY":
            continue

        rv = features.get("relative_volume")
        if rv is None or not (1.0 <= rv < 2.0):
            continue

        if not (
            SCORE_MIN
            <= decision["score"]
            <= SCORE_MAX
        ):
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

        entry_rsi = features.get("rsi14")
        position = {
            "side": decision["signal"],
            "entry_time": candle_time,
            "entry_price": features["close"],
            "position_size": risk["position_size"],
            "stop_loss": risk["stop_loss"],
            "score": decision["score"],
            "regime": regime,
            "bars_held": 0,
            "entry_rsi": entry_rsi,
        }

    if position is not None:
        last_candle = next(
            candle
            for candle in reversed(candles)
            if candle["time"] < TEST_END
        )

        trade = close_position(
            position,
            last_candle["close"],
            last_candle["time"],
            "BACKTEST_END",
        )

        capital += trade["pnl"]
        trades.append(trade)

    return capital, trades, risk_rejections


def calculate_costs(trades, slippage_rate):
    realized = [
        trade
        for trade in trades
        if trade["exit_reason"] != "BACKTEST_END"
    ]

    gross = 0.0
    fees = 0.0
    slippage = 0.0

    for trade in realized:
        entry = trade["entry_price"]
        exit_price = trade["exit_price"]
        size = trade["position_size"]

        if trade["side"] == "BUY":
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

        trade_fees = (
            entry_exec * size * FEE_RATE
            + exit_exec * size * FEE_RATE
        )

        trade_slippage = (
            abs(entry_exec - entry) * size
            + abs(exit_exec - exit_price) * size
        )

        gross += adjusted_gross
        fees += trade_fees
        slippage += trade_slippage

    net = gross - fees - slippage

    return {
        "trades": len(realized),
        "gross": gross,
        "fees": fees,
        "slippage": slippage,
        "net": net,
        "equity": STARTING_CAPITAL + net,
    }


def calculate_max_drawdown(trades):
    equity = STARTING_CAPITAL
    peak = equity
    max_drawdown = 0.0

    for trade in sorted(
        trades,
        key=lambda item: item["exit_time"],
    ):
        if trade["exit_reason"] == "BACKTEST_END":
            continue

        equity += trade["pnl"]

        if equity > peak:
            peak = equity

        drawdown = (
            (peak - equity) / peak
            if peak > 0
            else 0.0
        )

        max_drawdown = max(
            max_drawdown,
            drawdown,
        )

    return max_drawdown


def main():
    print("=" * 110)
    print("CONTINUOUS FORWARD VALIDATION — SCORE 60-79")
    print("=" * 110)
    print("Dataset: research_cache/btc_usdt_5m_100k.json")
    print(f"Test: {TEST_START} → {TEST_END}")
    print("Candidate: Score 60-79")
    print("Hold: 240 bars / 20h")
    print("Fee: 0.05% / side")
    print()

    candles = load_candles(
        "btc_usdt_5m_100k.json"
    )

    print(f"Cached candles: {len(candles)}")
    print(
        f"Dataset range: "
        f"{candles[0]['time']} → {candles[-1]['time']}"
    )
    print()

    capital, trades, risk_rejections = (
        run_continuous_backtest(candles)
    )

    print(f"Gross capital path : ${capital:.4f}")
    print(f"All closed trades  : {len(trades)}")
    print(f"Risk rejections    : {risk_rejections}")
    print(
        f"Max drawdown       : "
        f"{calculate_max_drawdown(trades) * 100:.2f}%"
    )
    print()

    print(
        f"{'SLIPPAGE':<12}"
        f"{'TRADES':>8}"
        f"{'GROSS':>14}"
        f"{'FEES':>14}"
        f"{'SLIPPAGE':>14}"
        f"{'NET':>14}"
        f"{'EQUITY':>14}"
    )

    print("-" * 110)

    for label, rate in SLIPPAGE_LEVELS.items():
        result = calculate_costs(
            trades,
            rate,
        )

        print(
            f"{label:<12}"
            f"{result['trades']:>8}"
            f"${result['gross']:>13.4f}"
            f"${result['fees']:>13.4f}"
            f"${result['slippage']:>13.4f}"
            f"${result['net']:>13.4f}"
            f"${result['equity']:>13.4f}"
        )

    print("-" * 110)

    print()
    print("Exit breakdown:")

    for reason in (
        "STOP_LOSS",
        "TIME_EXIT",
        "BACKTEST_END",
    ):
        subset = [
            trade
            for trade in trades
            if trade["exit_reason"] == reason
        ]

        print(
            f"{reason:15s}"
            f"{len(subset):4d} trades "
            f"Gross=${sum(t['pnl'] for t in subset):10.4f}"
        )

    print()
    print("Research only. No Core files modified.")


if __name__ == "__main__":
    main()
