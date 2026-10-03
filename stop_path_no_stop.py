from datetime import datetime
from incremental_features import IncrementalFeatures
from regime import detect_regime
from strategy import analyze_market
from risk import evaluate_risk
from research_data_cache import load_candles

STARTING_CAPITAL = 1000.0
MAX_HOLD_BARS = 240
FEE_RATE = 0.0005
SLIPPAGE_RATE = 0.0002

SCORE_MIN = 60
SCORE_MAX = 79

TEST_START = datetime.fromisoformat("2026-05-01T00:00:00+00:00")
TEST_END = datetime.fromisoformat("2026-10-01T00:00:00+00:00")


def pnl_mid(side, entry, exit_price, size):
    if side == "BUY":
        return (exit_price - entry) * size
    return (entry - exit_price) * size


def execution_costs(side, entry, exit_price, size):
    if side == "BUY":
        entry_exec = entry * (1 + SLIPPAGE_RATE)
        exit_exec = exit_price * (1 - SLIPPAGE_RATE)
    else:
        entry_exec = entry * (1 - SLIPPAGE_RATE)
        exit_exec = exit_price * (1 + SLIPPAGE_RATE)

    fees = (
        entry_exec * size * FEE_RATE
        + exit_exec * size * FEE_RATE
    )

    slippage = (
        abs(entry_exec - entry) * size
        + abs(exit_exec - exit_price) * size
    )

    adjusted_pnl = pnl_mid(
        side,
        entry_exec,
        exit_exec,
        size,
    )

    net = adjusted_pnl - fees

    return {
        "entry_exec": entry_exec,
        "exit_exec": exit_exec,
        "fees": fees,
        "slippage": slippage,
        "net": net,
    }


def extract_baseline(candles):
    """
    Reproduce the baseline entry/exit process from
    rolling_forward_continuous.py.

    The returned trades contain the exact baseline
    entry set required for the NO-STOP counterfactual.
    """

    capital = STARTING_CAPITAL
    position = None
    trades = []

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

                    exit_price = position["stop_loss"]
                    pnl = pnl_mid(
                        "BUY",
                        position["entry_price"],
                        exit_price,
                        position["position_size"],
                    )

                    trade = {
                        **position,
                        "exit_index": index,
                        "exit_time": candle_time,
                        "exit_price": exit_price,
                        "pnl": pnl,
                        "exit_reason": "STOP_LOSS",
                    }

                    capital += pnl
                    trades.append(trade)
                    position = None
                    continue

            else:

                if candle["high"] >= position["stop_loss"]:

                    exit_price = position["stop_loss"]
                    pnl = pnl_mid(
                        "SELL",
                        position["entry_price"],
                        exit_price,
                        position["position_size"],
                    )

                    trade = {
                        **position,
                        "exit_index": index,
                        "exit_time": candle_time,
                        "exit_price": exit_price,
                        "pnl": pnl,
                        "exit_reason": "STOP_LOSS",
                    }

                    capital += pnl
                    trades.append(trade)
                    position = None
                    continue

            if position["bars_held"] >= MAX_HOLD_BARS:

                exit_price = candle["close"]

                pnl = pnl_mid(
                    position["side"],
                    position["entry_price"],
                    exit_price,
                    position["position_size"],
                )

                trade = {
                    **position,
                    "exit_index": index,
                    "exit_time": candle_time,
                    "exit_price": exit_price,
                    "pnl": pnl,
                    "exit_reason": "TIME_EXIT",
                }

                capital += pnl
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
            continue

        position = {
            "entry_index": index,
            "entry_time": candle_time,
            "side": decision["signal"],
            "entry_price": features["close"],
            "position_size": risk["position_size"],
            "stop_loss": risk["stop_loss"],
            "score": decision["score"],
            "regime": regime,
            "atr": features["atr14"],
            "bars_held": 0,
        }

    return trades


def build_no_stop_trade(candles, baseline_trade):

    entry_index = baseline_trade["entry_index"]

    target_index = entry_index + MAX_HOLD_BARS

    if target_index >= len(candles):
        return {
            "status": "DATA_END_CENSORED",
            "trade_id": None,
        }

    exit_candle = candles[target_index]

    return {
        "status": "COMPLETED_20H",
        "entry_index": entry_index,
        "exit_index": target_index,
        "entry_time": baseline_trade["entry_time"],
        "exit_time": exit_candle["time"],
        "side": baseline_trade["side"],
        "entry_price": baseline_trade["entry_price"],
        "exit_price": exit_candle["close"],
        "position_size": baseline_trade["position_size"],
        "score": baseline_trade["score"],
        "regime": baseline_trade["regime"],
        "baseline_exit_reason": baseline_trade["exit_reason"],
    }


def calculate_portfolio(trades):

    ordered = sorted(
        trades,
        key=lambda x: x["exit_time"],
    )

    equity = STARTING_CAPITAL
    peak = equity
    max_dd = 0.0

    gross = 0.0
    fees = 0.0
    slippage = 0.0
    net = 0.0

    wins = 0
    losses = 0

    for trade in ordered:

        components = execution_costs(
            trade["side"],
            trade["entry_price"],
            trade["exit_price"],
            trade["position_size"],
        )

        trade["gross_mid"] = pnl_mid(
            trade["side"],
            trade["entry_price"],
            trade["exit_price"],
            trade["position_size"],
        )

        trade["fees"] = components["fees"]
        trade["slippage"] = components["slippage"]
        trade["net_pnl"] = components["net"]

        gross += trade["gross_mid"]
        fees += trade["fees"]
        slippage += trade["slippage"]
        net += trade["net_pnl"]

        equity += trade["net_pnl"]

        if trade["net_pnl"] > 0:
            wins += 1
        elif trade["net_pnl"] < 0:
            losses += 1

        peak = max(peak, equity)

        dd = (
            (peak - equity) / peak
            if peak > 0
            else 0.0
        )

        max_dd = max(max_dd, dd)

    return {
        "trades": len(ordered),
        "wins": wins,
        "losses": losses,
        "gross": gross,
        "fees": fees,
        "slippage": slippage,
        "net": net,
        "equity": STARTING_CAPITAL + net,
        "max_dd": max_dd,
    }


def main():

    candles = load_candles(
        "btc_usdt_5m_100k.json"
    )

    baseline = extract_baseline(candles)

    baseline_completed = [
        t for t in baseline
        if (
            t["entry_index"] + MAX_HOLD_BARS
            < len(candles)
        )
    ]

    no_stop = []

    censored = []

    for trade in baseline:

        result = build_no_stop_trade(
            candles,
            trade,
        )

        if result["status"] == "COMPLETED_20H":
            no_stop.append(result)
        else:
            censored.append(trade)

    # --------------------------------------------------
    # Baseline paired subset
    #
    # IMPORTANT:
    # For a fair paired comparison, baseline must use
    # exactly the same completed-entry subset as No-Stop.
    # --------------------------------------------------

    completed_ids = {
        (
            t["entry_index"],
            t["entry_time"],
            t["side"],
        )
        for t in no_stop
    }

    baseline_paired = [
        t for t in baseline
        if (
            t["entry_index"],
            t["entry_time"],
            t["side"],
        ) in completed_ids
    ]

    no_stop_metrics = calculate_portfolio(
        no_stop
    )

    baseline_metrics = calculate_portfolio(
        [
            {
                "entry_index": t["entry_index"],
                "exit_index": t["exit_index"],
                "entry_time": t["entry_time"],
                "exit_time": t["exit_time"],
                "side": t["side"],
                "entry_price": t["entry_price"],
                "exit_price": t["exit_price"],
                "position_size": t["position_size"],
                "score": t["score"],
                "regime": t["regime"],
            }
            for t in baseline_paired
        ]
    )

    # --------------------------------------------------
    # Identity check
    #
    # Baseline TIME_EXIT trades should have exactly the
    # same exit price/time as NO-STOP 20H.
    # --------------------------------------------------

    identity_total = 0
    identity_match = 0
    identity_mismatch = []

    no_stop_map = {
        (
            t["entry_index"],
            t["entry_time"],
            t["side"],
        ): t
        for t in no_stop
    }

    for trade in baseline_paired:

        if trade["exit_reason"] != "TIME_EXIT":
            continue

        identity_total += 1

        key = (
            trade["entry_index"],
            trade["entry_time"],
            trade["side"],
        )

        ns = no_stop_map[key]

        same_exit_index = (
            trade["exit_index"]
            == ns["exit_index"]
        )

        same_exit_price = (
            trade["exit_price"]
            == ns["exit_price"]
        )

        if same_exit_index and same_exit_price:
            identity_match += 1
        else:
            identity_mismatch.append(
                {
                    "entry_index": trade["entry_index"],
                    "baseline_exit_index": trade["exit_index"],
                    "no_stop_exit_index": ns["exit_index"],
                    "baseline_exit_price": trade["exit_price"],
                    "no_stop_exit_price": ns["exit_price"],
                }
            )

    delta_net = (
        no_stop_metrics["net"]
        - baseline_metrics["net"]
    )

    sva = (
        baseline_metrics["net"]
        - no_stop_metrics["net"]
    )

    print("=" * 100)
    print("NO-STOP 20H COUNTERFACTUAL — EXPERIMENT A")
    print("=" * 100)

    print(f"Candles                 : {len(candles)}")
    print(f"Baseline entries        : {len(baseline)}")
    print(f"Completed 20H           : {len(no_stop)}")
    print(f"Data censored           : {len(censored)}")
    print()

    print("-" * 100)
    print("BASELINE — SAME COMPLETED ENTRY SUBSET")
    print("-" * 100)

    print(f"Trades                  : {baseline_metrics['trades']}")
    print(f"Wins                    : {baseline_metrics['wins']}")
    print(f"Losses                  : {baseline_metrics['losses']}")
    print(f"Gross Mid P/L           : ${baseline_metrics['gross']:.4f}")
    print(f"Fees                    : ${baseline_metrics['fees']:.4f}")
    print(f"Slippage                : ${baseline_metrics['slippage']:.4f}")
    print(f"Net P/L                 : ${baseline_metrics['net']:.4f}")
    print(f"Net Equity              : ${baseline_metrics['equity']:.4f}")
    print(f"Net Max Drawdown        : {baseline_metrics['max_dd'] * 100:.2f}%")

    print()

    print("-" * 100)
    print("NO-STOP — PURE 20H TIME EXIT")
    print("-" * 100)

    print(f"Trades                  : {no_stop_metrics['trades']}")
    print(f"Wins                    : {no_stop_metrics['wins']}")
    print(f"Losses                  : {no_stop_metrics['losses']}")
    print(f"Gross Mid P/L           : ${no_stop_metrics['gross']:.4f}")
    print(f"Fees                    : ${no_stop_metrics['fees']:.4f}")
    print(f"Slippage                : ${no_stop_metrics['slippage']:.4f}")
    print(f"Net P/L                 : ${no_stop_metrics['net']:.4f}")
    print(f"Net Equity              : ${no_stop_metrics['equity']:.4f}")
    print(f"Net Max Drawdown        : {no_stop_metrics['max_dd'] * 100:.2f}%")

    print()

    print("-" * 100)
    print("COUNTERFACTUAL COMPARISON")
    print("-" * 100)

    print(
        f"No-Stop Net - Baseline Net : "
        f"${delta_net:.4f}"
    )

    print(
        f"Stop Value Added (SVA)     : "
        f"${sva:.4f}"
    )

    print()

    print("-" * 100)
    print("IDENTITY CHECK — BASELINE TIME EXIT")
    print("-" * 100)

    print(
        f"Baseline TIME_EXIT trades : "
        f"{identity_total}"
    )

    print(
        f"Exact matches             : "
        f"{identity_match}"
    )

    print(
        f"Mismatches                : "
        f"{len(identity_mismatch)}"
    )

    if identity_mismatch:
        print("WARNING: identity check FAILED")

        for item in identity_mismatch[:5]:
            print(item)
    else:
        print("PASS: all baseline TIME_EXIT trades match.")

    print()

    print("-" * 100)
    print("DATA BOUNDARY")
    print("-" * 100)

    for trade in censored:
        print(
            f"CENSORED | "
            f"{trade['entry_time']} | "
            f"{trade['side']} | "
            f"entry_index={trade['entry_index']}"
        )

    print("=" * 100)


if __name__ == "__main__":
    main()
