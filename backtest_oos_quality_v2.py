from collections import deque
from datetime import datetime, timezone

from backtest_data_100k import (
    get_historical_candles_100k,
    validate_candles,
)
from incremental_features import IncrementalFeatures
from regime import detect_regime
from strategy import analyze_market
from risk import evaluate_risk
from capital_config import STARTING_CAPITAL_USDT


SYMBOL = "BTCUSDT"
INTERVAL = "5m"
CANDLES_NEEDED = 100_000

# Research baseline only.
# This file does NOT change Strategy V2 or Risk Manager.
MAX_HOLD_BARS = 240  # 20h
OOS_BOUNDARY = "2026-07-21T10:05:00+00:00"

# Research cost assumptions only.
FEE_RATE = 0.0005       # 0.05% each side
SLIPPAGE_RATES = {
    "0.00%": 0.0000,
    "0.02%": 0.0002,
    "0.05%": 0.0005,
}

# Strategy V2 needs recent candle history for Pullback / Recovery detection.
HISTORY_SIZE = 250


def close_position(position, exit_price, exit_time, exit_reason):
    if position["side"] == "BUY":
        gross_pnl = (
            exit_price - position["entry_price"]
        ) * position["position_size"]
    else:
        gross_pnl = (
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
        "setup": position["setup"],
        "bars_held": position["bars_held"],
        "gross_pnl": gross_pnl,
        "exit_reason": exit_reason,
    }


def run_oos_backtest(candles, boundary):
    capital = STARTING_CAPITAL_USDT
    position = None
    trades = []
    risk_rejections = 0

    signal_counts = {
        "BUY": 0,
        "SELL": 0,
        "WAIT": 0,
    }

    setup_counts = {
        "TREND_PULLBACK": 0,
        "BREAKOUT": 0,
        "OTHER": 0,
    }

    feature_engine = IncrementalFeatures()
    candle_history = deque(maxlen=HISTORY_SIZE)

    for index, candle in enumerate(candles):
        features = feature_engine.update(candle)
        candle_history.append(candle)

        if index < 200:
            continue

        candle_time = candle["time"]

        # --------------------------------------------------
        # Manage existing position first
        # --------------------------------------------------
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
                    capital += trade["gross_pnl"]
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
                    capital += trade["gross_pnl"]
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
                capital += trade["gross_pnl"]
                trades.append(trade)
                position = None
                continue

            continue

        # --------------------------------------------------
        # OOS entry boundary
        # --------------------------------------------------
        if candle_time < boundary:
            continue

        # --------------------------------------------------
        # Strategy V2
        # --------------------------------------------------
        regime = detect_regime(features)

        decision = analyze_market(
            list(candle_history),
            features,
            regime,
        )

        signal = decision["signal"]
        signal_counts[signal] += 1

        setup = decision.get("setup")

        if setup == "TREND_PULLBACK":
            setup_counts["TREND_PULLBACK"] += 1
        elif setup == "BREAKOUT":
            setup_counts["BREAKOUT"] += 1
        else:
            setup_counts["OTHER"] += 1

        if signal == "WAIT":
            continue

        # --------------------------------------------------
        # Risk Engine
        # --------------------------------------------------
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
            "entry_time": candle_time,
            "entry_price": features["close"],
            "position_size": risk["position_size"],
            "stop_loss": risk["stop_loss"],
            "regime": regime,
            "setup": setup,
            "bars_held": 0,
        }

    # Do not count an unfinished position as realized performance.
    dataset_end_pnl = 0.0

    return (
        capital,
        trades,
        risk_rejections,
        signal_counts,
        setup_counts,
        dataset_end_pnl,
    )


def apply_costs(trades, fee_rate, slippage_rate):
    net_pnl = 0.0
    total_fees = 0.0
    total_slippage = 0.0

    for trade in trades:
        entry = trade["entry_price"]
        exit_price = trade["exit_price"]
        size = trade["position_size"]
        side = trade["side"]

        if side == "BUY":
            entry_slip_price = entry * (1 + slippage_rate)
            exit_slip_price = exit_price * (1 - slippage_rate)

            gross = (
                exit_slip_price - entry_slip_price
            ) * size

        else:
            entry_slip_price = entry * (1 - slippage_rate)
            exit_slip_price = exit_price * (1 + slippage_rate)

            gross = (
                entry_slip_price - exit_slip_price
            ) * size

        entry_fee = entry_slip_price * size * fee_rate
        exit_fee = exit_slip_price * size * fee_rate

        slippage_cost = (
            abs(entry_slip_price - entry) * size
            + abs(exit_slip_price - exit_price) * size
        )

        total_fees += entry_fee + exit_fee
        total_slippage += slippage_cost
        net_pnl += gross - entry_fee - exit_fee

    return net_pnl, total_fees, total_slippage


def summarize(trades):
    wins = [t for t in trades if t["gross_pnl"] > 0]
    losses = [t for t in trades if t["gross_pnl"] < 0]

    gross_profit = sum(t["gross_pnl"] for t in wins)
    gross_loss = abs(sum(t["gross_pnl"] for t in losses))

    profit_factor = (
        gross_profit / gross_loss
        if gross_loss > 0
        else None
    )

    return {
        "trades": len(trades),
        "wins": len(wins),
        "losses": len(losses),
        "gross_pnl": sum(t["gross_pnl"] for t in trades),
        "profit_factor": profit_factor,
        "stop_losses": sum(
            t["exit_reason"] == "STOP_LOSS"
            for t in trades
        ),
        "time_exits": sum(
            t["exit_reason"] == "TIME_EXIT"
            for t in trades
        ),
    }


def main():
    print("=" * 100)
    print("OOS QUALITY V2 — RESEARCH ONLY")
    print("=" * 100)

    candles = get_historical_candles_100k(
        symbol=SYMBOL,
        interval=INTERVAL,
        candles_needed=CANDLES_NEEDED,
    )

    valid, reason = validate_candles(candles)

    print(f"Candles:        {len(candles)}")
    print(f"Validation:     {valid}")
    print(f"Reason:         {reason}")
    print(f"OOS Boundary:   {OOS_BOUNDARY}")
    print(f"Starting Pot:   ${STARTING_CAPITAL_USDT:.4f}")
    print(f"Max Hold:       {MAX_HOLD_BARS} bars / 20h")
    print(f"History Size:   {HISTORY_SIZE} candles")

    if not valid:
        raise RuntimeError(
            f"Dataset validation failed: {reason}"
        )

    boundary = datetime.fromisoformat(
        OOS_BOUNDARY
    ).astimezone(timezone.utc)

    (
        baseline_capital,
        trades,
        risk_rejections,
        signal_counts,
        setup_counts,
        dataset_end_pnl,
    ) = run_oos_backtest(candles, boundary)

    summary = summarize(trades)

    print()
    print("=" * 100)
    print("SIGNAL / SETUP")
    print("=" * 100)
    print(f"BUY:               {signal_counts['BUY']}")
    print(f"SELL:              {signal_counts['SELL']}")
    print(f"WAIT:              {signal_counts['WAIT']}")
    print(f"TREND_PULLBACK:    {setup_counts['TREND_PULLBACK']}")
    print(f"BREAKOUT:          {setup_counts['BREAKOUT']}")
    print(f"Other:             {setup_counts['OTHER']}")
    print(f"Risk rejected:     {risk_rejections}")

    print()
    print("=" * 100)
    print("GROSS OOS RESULT — BEFORE COST")
    print("=" * 100)
    print(f"Trades:             {summary['trades']}")
    print(f"Wins:               {summary['wins']}")
    print(f"Losses:             {summary['losses']}")
    print(f"Gross P/L:          ${summary['gross_pnl']:.4f}")

    if summary["profit_factor"] is None:
        print("Profit Factor:      N/A")
    else:
        print(f"Profit Factor:      {summary['profit_factor']:.4f}")

    print(f"Stop Losses:        {summary['stop_losses']}")
    print(f"Time Exits:         {summary['time_exits']}")

    print()
    print("=" * 100)
    print("NET COST GATE")
    print("=" * 100)

    for slip_name, slip_rate in SLIPPAGE_RATES.items():
        net_pnl, fees, slippage = apply_costs(
            trades,
            FEE_RATE,
            slip_rate,
        )

        final_pot = STARTING_CAPITAL_USDT + net_pnl

        print(
            f"Slippage {slip_name:<6} | "
            f"Final Pot ${final_pot:>10.4f} | "
            f"Net P/L ${net_pnl:>9.4f} | "
            f"Fees ${fees:>8.4f} | "
            f"Slippage ${slippage:>8.4f}"
        )

    print()
    print("=" * 100)
    print("RESEARCH ONLY — NO CORE FILES MODIFIED")
    print("=" * 100)


if __name__ == "__main__":
    main()
