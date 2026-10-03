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

SLIPPAGE_LEVELS = {
    "0.00%": 0.0000,
    "0.02%": 0.0002,
}

WINDOWS = [
    (
        "2026-05",
        datetime.fromisoformat("2026-05-01T00:00:00+00:00"),
        datetime.fromisoformat("2026-06-01T00:00:00+00:00"),
    ),
    (
        "2026-06",
        datetime.fromisoformat("2026-06-01T00:00:00+00:00"),
        datetime.fromisoformat("2026-07-01T00:00:00+00:00"),
    ),
    (
        "2026-07",
        datetime.fromisoformat("2026-07-01T00:00:00+00:00"),
        datetime.fromisoformat("2026-08-01T00:00:00+00:00"),
    ),
    (
        "2026-08",
        datetime.fromisoformat("2026-08-01T00:00:00+00:00"),
        datetime.fromisoformat("2026-09-01T00:00:00+00:00"),
    ),
    (
        "2026-09",
        datetime.fromisoformat("2026-09-01T00:00:00+00:00"),
        datetime.fromisoformat("2026-10-01T00:00:00+00:00"),
    ),
]


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


def run_window(candles, window_start, window_end):
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

        if candle_time < window_start:
            continue

        if candle_time >= window_end:
            break

        regime = detect_regime(features)
        decision = analyze_market(features, regime)

        if decision["signal"] == "WAIT":
            continue

        if not (
            SCORE_MIN
            <= decision["score"]
            <= SCORE_MAX
        ):
            continue

        if regime != "TREND_UP" or decision["signal"] != "BUY":
            continue

        rv = features.get("relative_volume")
        if rv is None or not (1.0 <= rv < 2.0):
            continue

        ema200 = features.get("ema200")
        price = features.get("close")
        if ema200 is None or price is None or (price / ema200 - 1.0) < 0.01:
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
            "score": decision["score"],
            "regime": regime,
            "bars_held": 0,
        }

    realized = [
        trade
        for trade in trades
        if trade["exit_reason"] != "BACKTEST_END"
    ]

    return realized, risk_rejections


def calculate_costs(trades, slippage_rate):
    gross = 0.0
    fees = 0.0
    slippage = 0.0

    for trade in trades:
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

        trade_fee = (
            entry_exec * size * FEE_RATE
            + exit_exec * size * FEE_RATE
        )

        trade_slippage = (
            abs(entry_exec - entry) * size
            + abs(exit_exec - exit_price) * size
        )

        gross += adjusted_gross
        fees += trade_fee
        slippage += trade_slippage

    net = gross - fees

    # The original gross P/L is used for the baseline capital path.
    # Slippage is reported separately and deducted from net.
    net_after_slippage = net - slippage

    return {
        "gross": gross,
        "fees": fees,
        "slippage": slippage,
        "net": net_after_slippage,
        "equity": STARTING_CAPITAL + net_after_slippage,
    }


def main():
    print("=" * 110)
    print("ROLLING FORWARD VALIDATION — SCORE 60-79")
    print("=" * 110)
    print("Dataset: research_cache/btc_usdt_5m_100k.json")
    print("Candidate: Score 60-79")
    print("Hold: 240 bars / 20h")
    print("Fee: 0.05% / side")
    print()

    candles = load_candles("btc_usdt_5m_100k.json")

    print(f"Cached candles: {len(candles)}")
    print(
        f"Dataset range : "
        f"{candles[0]['time']} → {candles[-1]['time']}"
    )
    print()

    print(
        f"{'WINDOW':<10}"
        f"{'TRADES':>8}"
        f"{'GROSS':>14}"
        f"{'FEES':>14}"
        f"{'NET 0%':>14}"
        f"{'EQ 0%':>14}"
        f"{'NET 0.02%':>14}"
        f"{'EQ 0.02%':>14}"
        f"{'RISK REJ':>10}"
    )
    print("-" * 110)

    for label, start, end in WINDOWS:
        trades, risk_rejections = run_window(
            candles,
            start,
            end,
        )

        zero = calculate_costs(
            trades,
            SLIPPAGE_LEVELS["0.00%"],
        )

        stress = calculate_costs(
            trades,
            SLIPPAGE_LEVELS["0.02%"],
        )

        print(
            f"{label:<10}"
            f"{len(trades):>8}"
            f"${zero['gross']:>13.4f}"
            f"${zero['fees']:>13.4f}"
            f"${zero['net']:>13.4f}"
            f"${zero['equity']:>13.4f}"
            f"${stress['net']:>13.4f}"
            f"${stress['equity']:>13.4f}"
            f"{risk_rejections:>10}"
        )

    print("-" * 110)
    print("Research only. No Core files modified.")


if __name__ == "__main__":
    main()
