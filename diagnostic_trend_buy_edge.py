from collections import deque, defaultdict
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

MAX_HOLD_BARS = 240
OOS_BOUNDARY = "2026-07-21T10:05:00+00:00"

FEE_RATE = 0.0005
SLIPPAGE_RATES = {
    "0.00%": 0.0000,
    "0.02%": 0.0002,
    "0.05%": 0.0005,
}

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

        # Diagnostic fields
        "mae_price": position["mae_price"],
        "mfe_price": position["mfe_price"],
        "mae_pct": position["mae_pct"],
        "mfe_pct": position["mfe_pct"],
        "mfe_1_price": position["mfe_1_price"],
        "mfe_3_price": position["mfe_3_price"],
        "mfe_5_price": position["mfe_5_price"],
        "mfe_1_pct": position["mfe_1_pct"],
        "mfe_3_pct": position["mfe_3_pct"],
        "mfe_5_pct": position["mfe_5_pct"],
    }


def update_excursion(position, candle):
    entry = position["entry_price"]
    side = position["side"]
    bar_number = position["bars_held"]

    if side == "BUY":
        favorable_price = candle["high"] - entry
        adverse_price = candle["low"] - entry

        favorable_pct = (
            favorable_price / entry * 100.0
            if entry != 0
            else 0.0
        )
        adverse_pct = (
            adverse_price / entry * 100.0
            if entry != 0
            else 0.0
        )
    else:
        favorable_price = entry - candle["low"]
        adverse_price = entry - candle["high"]

        favorable_pct = (
            favorable_price / entry * 100.0
            if entry != 0
            else 0.0
        )
        adverse_pct = (
            adverse_price / entry * 100.0
            if entry != 0
            else 0.0
        )

    position["mfe_price"] = max(
        position["mfe_price"],
        favorable_price,
    )
    position["mae_price"] = min(
        position["mae_price"],
        adverse_price,
    )

    position["mfe_pct"] = max(
        position["mfe_pct"],
        favorable_pct,
    )
    position["mae_pct"] = min(
        position["mae_pct"],
        adverse_pct,
    )

    if bar_number <= 1:
        position["mfe_1_price"] = max(
            position["mfe_1_price"],
            favorable_price,
        )
        position["mfe_1_pct"] = max(
            position["mfe_1_pct"],
            favorable_pct,
        )

    if bar_number <= 3:
        position["mfe_3_price"] = max(
            position["mfe_3_price"],
            favorable_price,
        )
        position["mfe_3_pct"] = max(
            position["mfe_3_pct"],
            favorable_pct,
        )

    if bar_number <= 5:
        position["mfe_5_price"] = max(
            position["mfe_5_price"],
            favorable_price,
        )
        position["mfe_5_pct"] = max(
            position["mfe_5_pct"],
            favorable_pct,
        )


def new_position(signal, candle_time, entry_price, risk, regime, setup):
    return {
        "side": signal,
        "entry_time": candle_time,
        "entry_price": entry_price,
        "position_size": risk["position_size"],
        "stop_loss": risk["stop_loss"],
        "regime": regime,
        "setup": setup,
        "bars_held": 0,

        "mae_price": 0.0,
        "mfe_price": 0.0,
        "mae_pct": 0.0,
        "mfe_pct": 0.0,
        "mfe_1_price": 0.0,
        "mfe_3_price": 0.0,
        "mfe_5_price": 0.0,
        "mfe_1_pct": 0.0,
        "mfe_3_pct": 0.0,
        "mfe_5_pct": 0.0,
    }


def run_diagnostic(candles, boundary):
    capital = STARTING_CAPITAL_USDT
    position = None
    trades = []
    risk_rejections = 0

    signal_counts = {
        "BUY": 0,
        "SELL": 0,
        "WAIT": 0,
    }

    decision_setup_counts = {
        "TREND": 0,
        "TREND_PULLBACK": 0,
        "BREAKOUT": 0,
        "OTHER": 0,
    }

    actual_setup_counts = {
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

            update_excursion(position, candle)

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
        # Strategy V2 — unchanged
        # --------------------------------------------------
        regime = detect_regime(features)

        decision = analyze_market(
            list(candle_history),
            features,
            regime,
        )

        signal = decision["signal"]
        signal_counts[signal] += 1

        decision_setup = decision.get("setup")

        if decision_setup in decision_setup_counts:
            decision_setup_counts[decision_setup] += 1
        else:
            decision_setup_counts["OTHER"] += 1

        if signal == "WAIT":
            continue

        # --------------------------------------------------
        # Risk Engine — unchanged
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

        setup = decision_setup

        if setup in actual_setup_counts:
            actual_setup_counts[setup] += 1
        else:
            actual_setup_counts["OTHER"] += 1

        position = new_position(
            signal,
            candle_time,
            features["close"],
            risk,
            regime,
            setup,
        )

    return (
        capital,
        trades,
        risk_rejections,
        signal_counts,
        decision_setup_counts,
        actual_setup_counts,
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


def profit_factor(trades):
    gross_profit = sum(
        t["gross_pnl"]
        for t in trades
        if t["gross_pnl"] > 0
    )

    gross_loss = abs(
        sum(
            t["gross_pnl"]
            for t in trades
            if t["gross_pnl"] < 0
        )
    )

    if gross_loss == 0:
        return None

    return gross_profit / gross_loss


def summarize_group(trades):
    wins = [t for t in trades if t["gross_pnl"] > 0]
    losses = [t for t in trades if t["gross_pnl"] < 0]

    gross = sum(t["gross_pnl"] for t in trades)

    return {
        "trades": len(trades),
        "wins": len(wins),
        "losses": len(losses),
        "gross_pnl": gross,
        "profit_factor": profit_factor(trades),
        "avg_gross": (
            gross / len(trades)
            if trades
            else 0.0
        ),
        "avg_mae_pct": (
            sum(t["mae_pct"] for t in trades) / len(trades)
            if trades
            else 0.0
        ),
        "avg_mfe_pct": (
            sum(t["mfe_pct"] for t in trades) / len(trades)
            if trades
            else 0.0
        ),
        "avg_mfe_1_pct": (
            sum(t["mfe_1_pct"] for t in trades) / len(trades)
            if trades
            else 0.0
        ),
        "avg_mfe_3_pct": (
            sum(t["mfe_3_pct"] for t in trades) / len(trades)
            if trades
            else 0.0
        ),
        "avg_mfe_5_pct": (
            sum(t["mfe_5_pct"] for t in trades) / len(trades)
            if trades
            else 0.0
        ),
        "avg_bars": (
            sum(t["bars_held"] for t in trades) / len(trades)
            if trades
            else 0.0
        ),
        "stop_losses": sum(
            t["exit_reason"] == "STOP_LOSS"
            for t in trades
        ),
        "time_exits": sum(
            t["exit_reason"] == "TIME_EXIT"
            for t in trades
        ),
    }


def print_group(title, trades):
    s = summarize_group(trades)

    print()
    print("-" * 100)
    print(title)
    print("-" * 100)

    print(f"Trades:             {s['trades']}")
    print(f"Wins:               {s['wins']}")
    print(f"Losses:             {s['losses']}")
    print(f"Gross P/L:          ${s['gross_pnl']:.6f}")

    if s["profit_factor"] is None:
        print("Profit Factor:      N/A")
    else:
        print(f"Profit Factor:      {s['profit_factor']:.4f}")

    print(f"Avg Gross/Trade:    ${s['avg_gross']:.6f}")
    print(f"Avg MAE:            {s['avg_mae_pct']:.4f}%")
    print(f"Avg MFE:            {s['avg_mfe_pct']:.4f}%")
    print(f"Avg MFE 1 bar:      {s['avg_mfe_1_pct']:.4f}%")
    print(f"Avg MFE 3 bars:     {s['avg_mfe_3_pct']:.4f}%")
    print(f"Avg MFE 5 bars:     {s['avg_mfe_5_pct']:.4f}%")
    print(f"Avg Bars Held:      {s['avg_bars']:.2f}")
    print(f"Stop Losses:        {s['stop_losses']}")
    print(f"Time Exits:         {s['time_exits']}")


def print_cost_analysis(title, trades):
    print()
    print("-" * 100)
    print(f"COST ANALYSIS — {title}")
    print("-" * 100)

    gross = sum(t["gross_pnl"] for t in trades)

    for slip_name, slip_rate in SLIPPAGE_RATES.items():
        net_pnl, fees, slippage = apply_costs(
            trades,
            FEE_RATE,
            slip_rate,
        )

        expectancy = (
            net_pnl / len(trades)
            if trades
            else 0.0
        )

        print(
            f"Slippage {slip_name:<6} | "
            f"Gross ${gross:>10.6f} | "
            f"Net ${net_pnl:>10.6f} | "
            f"Expectancy ${expectancy:>10.6f} | "
            f"Fees ${fees:>9.6f} | "
            f"Slip ${slippage:>9.6f}"
        )


def main():
    print("=" * 100)
    print("OOS QUALITY V2 — ENTRY DIAGNOSTIC / RESEARCH ONLY")
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
        final_capital,
        trades,
        risk_rejections,
        signal_counts,
        decision_setup_counts,
        actual_setup_counts,
    ) = run_diagnostic(candles, boundary)

    print()
    print("=" * 100)
    print("ACTUAL ENTRY COUNT")
    print("=" * 100)
    print(f"BUY:               {signal_counts['BUY']}")
    print(f"SELL:              {signal_counts['SELL']}")
    print(f"WAIT:              {signal_counts['WAIT']}")
    print(f"Risk rejected:     {risk_rejections}")
    print(f"Actual trades:     {len(trades)}")

    print()
    print("=" * 100)
    print("ACTUAL SETUP BREAKDOWN")
    print("=" * 100)
    print(
        f"TREND_PULLBACK:    "
        f"{actual_setup_counts['TREND_PULLBACK']}"
    )
    print(
        f"BREAKOUT:          "
        f"{actual_setup_counts['BREAKOUT']}"
    )
    print(
        f"OTHER:             "
        f"{actual_setup_counts['OTHER']}"
    )

    print()
    print("=" * 100)
    print("NOTE — DECISION LABELS VS ACTUAL ENTRIES")
    print("=" * 100)
    print(
        "Decision setup counts include WAIT decisions carrying a setup label."
    )
    print(
        "Actual setup counts above include only BUY/SELL entries that passed Risk."
    )

    # ------------------------------------------------------
    # EDGE CANDIDATE — TREND_PULLBACK + BUY
    # ------------------------------------------------------
    candidate = [
        t for t in trades
        if t["setup"] == "TREND_PULLBACK"
        and t["side"] == "BUY"
    ]

    print()
    print("=" * 100)
    print("EDGE CANDIDATE — TREND_PULLBACK + BUY")
    print("=" * 100)
    print("Research-only isolation of the existing V2 candidate.")
    print("No strategy, risk, entry, exit, or position-size rules were changed.")
    
    print_group("TREND_PULLBACK + BUY", candidate)
    print_cost_analysis("TREND_PULLBACK + BUY", candidate)

    # ------------------------------------------------------
    # Exit breakdown
    # ------------------------------------------------------
    stop_trades = [
        t for t in candidate
        if t["exit_reason"] == "STOP_LOSS"
    ]

    time_trades = [
        t for t in candidate
        if t["exit_reason"] == "TIME_EXIT"
    ]

    print()
    print("=" * 100)
    print("EDGE CANDIDATE — EXIT BREAKDOWN")
    print("=" * 100)

    print_group("TREND_PULLBACK + BUY — STOP LOSS", stop_trades)
    print_group("TREND_PULLBACK + BUY — TIME EXIT", time_trades)

    # ------------------------------------------------------
    # MFE diagnostic
    # ------------------------------------------------------
    print()
    print("=" * 100)
    print("EDGE CANDIDATE — MFE DIAGNOSTIC")
    print("=" * 100)

    if candidate:
        for threshold in (0.05, 0.10, 0.20, 0.30, 0.50):
            count = sum(
                t["mfe_5_pct"] >= threshold
                for t in candidate
            )
            pct = count / len(candidate) * 100.0
            print(
                f"MFE >= {threshold:.2f}% within 5 bars: "
                f"{count}/{len(candidate)} ({pct:.2f}%)"
            )
    else:
        print("No TREND_PULLBACK + BUY trades found.")

    # ------------------------------------------------------
    # Final candidate summary
    # ------------------------------------------------------
    print()
    print("=" * 100)
    print("EDGE CANDIDATE SUMMARY")
    print("=" * 100)

    candidate_gross = sum(
        t["gross_pnl"]
        for t in candidate
    )

    print(f"Candidate trades:  {len(candidate)}")
    print(f"Candidate gross:   ${candidate_gross:.6f}")

    if candidate:
        print(
            f"Gross expectancy:  "
            f"${candidate_gross / len(candidate):.6f}"
        )
    else:
        print("Gross expectancy:  N/A")

    print()
    print(
        "IMPORTANT: This is an isolation report, not proof of future profitability."
    )
    print(
        "Research only. No Core files modified."
    )
    print("=" * 100)


if __name__ == "__main__":
    main()
