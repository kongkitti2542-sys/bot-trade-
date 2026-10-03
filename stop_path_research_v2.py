#!/usr/bin/env python3

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

TEST_START = datetime.fromisoformat(
    "2026-05-01T00:00:00+00:00"
)
TEST_END = datetime.fromisoformat(
    "2026-10-01T00:00:00+00:00"
)

HORIZONS = {
    "1h": 12,
    "2h": 24,
    "4h": 48,
    "8h": 96,
    "12h": 144,
    "20h": 240,
}


def make_trade(position, exit_price, exit_time, exit_index, reason):
    side = position["side"]

    if side == "BUY":
        pnl = (
            exit_price - position["entry_price"]
        ) * position["position_size"]
    else:
        pnl = (
            position["entry_price"] - exit_price
        ) * position["position_size"]

    return {
        "trade_id": position["trade_id"],
        "entry_index": position["entry_index"],
        "exit_index": exit_index,
        "entry_time": position["entry_time"],
        "exit_time": exit_time,
        "side": side,
        "entry_price": position["entry_price"],
        "exit_price": exit_price,
        "position_size": position["position_size"],
        "stop_loss": position["stop_loss"],
        "atr": position["atr"],
        "pnl": pnl,
        "exit_reason": reason,
        "score": position["score"],
        "regime": position["regime"],
        "bars_held": position["bars_held"],
        "mfe_pre": position["mfe_pre"],
        "mae_pre": position["mae_pre"],
    }


def extract_baseline(candles):
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

        # --------------------------------------------------
        # Manage existing position
        # --------------------------------------------------

        if position is not None:

            position["bars_held"] += 1

            if position["side"] == "BUY":

                position["mfe_pre"] = max(
                    position["mfe_pre"],
                    candle["high"] - position["entry_price"],
                )

                position["mae_pre"] = max(
                    position["mae_pre"],
                    position["entry_price"] - candle["low"],
                )

                if candle["low"] <= position["stop_loss"]:

                    trade = make_trade(
                        position,
                        position["stop_loss"],
                        candle_time,
                        index,
                        "STOP_LOSS",
                    )

                    capital += trade["pnl"]
                    trades.append(trade)
                    position = None
                    continue

            else:

                position["mfe_pre"] = max(
                    position["mfe_pre"],
                    position["entry_price"] - candle["low"],
                )

                position["mae_pre"] = max(
                    position["mae_pre"],
                    candle["high"] - position["entry_price"],
                )

                if candle["high"] >= position["stop_loss"]:

                    trade = make_trade(
                        position,
                        position["stop_loss"],
                        candle_time,
                        index,
                        "STOP_LOSS",
                    )

                    capital += trade["pnl"]
                    trades.append(trade)
                    position = None
                    continue

            if position["bars_held"] >= MAX_HOLD_BARS:

                trade = make_trade(
                    position,
                    candle["close"],
                    candle_time,
                    index,
                    "TIME_EXIT",
                )

                capital += trade["pnl"]
                trades.append(trade)
                position = None
                continue

            continue

        # --------------------------------------------------
        # Entry
        # --------------------------------------------------

        if candle_time < TEST_START:
            continue

        regime = detect_regime(
            features
        )

        decision = analyze_market(
            features,
            regime,
        )

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

        # Verified from risk.py:
        # stop_distance = atr14 * 2.0
        # position_size = risk_amount / stop_distance

        atr = features["atr14"]

        position = {
            "trade_id": len(trades) + 1,
            "entry_index": index,
            "side": decision["signal"],
            "entry_time": candle_time,
            "entry_price": features["close"],
            "position_size": risk["position_size"],
            "stop_loss": risk["stop_loss"],
            "atr": atr,
            "score": decision["score"],
            "regime": regime,
            "bars_held": 0,
            "mfe_pre": 0.0,
            "mae_pre": 0.0,
        }

    return capital, trades


def analyze_post_stop_paths(candles, trades):

    records = []

    for trade in trades:

        if trade["exit_reason"] != "STOP_LOSS":
            continue

        exit_index = trade["exit_index"]

        future = candles[
            exit_index + 1:
            exit_index + 1 + MAX_HOLD_BARS
        ]

        record = {
            "trade_id": trade["trade_id"],
            "side": trade["side"],
            "score": trade["score"],
            "regime": trade["regime"],
            "entry_price": trade["entry_price"],
            "stop_price": trade["exit_price"],
            "atr": trade["atr"],
            "bars_held_before_stop": trade["bars_held"],
        }

        for label, bars in HORIZONS.items():

            if len(future) >= bars:

                record[f"price_{label}"] = (
                    future[bars - 1]["close"]
                )

                record[f"available_{label}"] = True

            else:

                record[f"price_{label}"] = None
                record[f"available_{label}"] = False

        mfe = 0.0
        mae = 0.0
        reverted = False

        for candle in future:

            if trade["side"] == "BUY":

                mfe = max(
                    mfe,
                    candle["high"]
                    - trade["entry_price"],
                )

                mae = max(
                    mae,
                    trade["entry_price"]
                    - candle["low"],
                )

                if (
                    candle["high"]
                    >= trade["entry_price"]
                ):
                    reverted = True

            else:

                mfe = max(
                    mfe,
                    trade["entry_price"]
                    - candle["low"],
                )

                mae = max(
                    mae,
                    candle["high"]
                    - trade["entry_price"],
                )

                if (
                    candle["low"]
                    <= trade["entry_price"]
                ):
                    reverted = True

        record["mfe_post_20h"] = mfe
        record["mae_post_20h"] = mae

        record["reverted_to_entry"] = reverted

        # Baseline R = ATR * 2.0
        baseline_r = trade["atr"] * 2.0

        if baseline_r > 0:

            record["post_stop_mfe_R"] = (
                mfe / baseline_r
            )

            record["reached_plus_0_5R"] = (
                mfe >= baseline_r * 0.5
            )

            record["reached_plus_1R"] = (
                mfe >= baseline_r
            )

        else:

            record["post_stop_mfe_R"] = None
            record["reached_plus_0_5R"] = False
            record["reached_plus_1R"] = False

        records.append(record)

    return records


def isolated_trace(
    candles,
    baseline_trades,
    multiplier,
):

    results = []

    for baseline in baseline_trades:

        entry_index = baseline["entry_index"]
        side = baseline["side"]
        entry_price = baseline["entry_price"]
        position_size = baseline["position_size"]
        atr = baseline["atr"]

        if side == "BUY":

            new_stop = (
                entry_price
                - atr * multiplier
            )

        else:

            new_stop = (
                entry_price
                + atr * multiplier
            )

        max_index = min(
            entry_index + MAX_HOLD_BARS,
            len(candles) - 1,
        )

        final_trade = None

        for index in range(
            entry_index + 1,
            max_index + 1,
        ):

            candle = candles[index]

            bars_held = index - entry_index

            if (
                side == "BUY"
                and candle["low"] <= new_stop
            ):

                final_trade = (
                    new_stop,
                    "STOP_LOSS",
                    bars_held,
                    index,
                )

                break

            if (
                side == "SELL"
                and candle["high"] >= new_stop
            ):

                final_trade = (
                    new_stop,
                    "STOP_LOSS",
                    bars_held,
                    index,
                )

                break

        if final_trade is None:

            candle = candles[max_index]

            if (
                max_index - entry_index
                >= MAX_HOLD_BARS
            ):

                reason = "TIME_EXIT"

            else:

                reason = "DATA_END"

            final_trade = (
                candle["close"],
                reason,
                max_index - entry_index,
                max_index,
            )

        (
            exit_price,
            exit_reason,
            bars_held,
            exit_index,
        ) = final_trade

        if side == "BUY":

            pnl = (
                exit_price - entry_price
            ) * position_size

        else:

            pnl = (
                entry_price - exit_price
            ) * position_size

        results.append(
            {
                "side": side,
                "entry_price": entry_price,
                "exit_price": exit_price,
                "position_size": position_size,
                "pnl_mid": pnl,
                "exit_reason": exit_reason,
                "bars_held": bars_held,
                "exit_index": exit_index,
            }
        )

    return results


def calculate_costs_and_dd(trades):

    realized = [
        trade
        for trade in trades
        if trade["exit_reason"]
        != "DATA_END"
    ]

    gross_mid = 0.0
    fees = 0.0
    slippage = 0.0

    net_equity = STARTING_CAPITAL
    peak = net_equity
    max_drawdown = 0.0

    for trade in sorted(
        realized,
        key=lambda item: item["exit_index"],
    ):

        entry = trade["entry_price"]
        exit_price = trade["exit_price"]
        size = trade["position_size"]

        if trade["side"] == "BUY":

            entry_exec = (
                entry * (1 + SLIPPAGE_RATE)
            )

            exit_exec = (
                exit_price
                * (1 - SLIPPAGE_RATE)
            )

            adjusted_pnl = (
                exit_exec - entry_exec
            ) * size

        else:

            entry_exec = (
                entry * (1 - SLIPPAGE_RATE)
            )

            exit_exec = (
                exit_price
                * (1 + SLIPPAGE_RATE)
            )

            adjusted_pnl = (
                entry_exec - exit_exec
            ) * size

        trade_fees = (
            entry_exec
            * size
            * FEE_RATE
            +
            exit_exec
            * size
            * FEE_RATE
        )

        trade_slippage = (
            abs(entry_exec - entry)
            * size
            +
            abs(exit_exec - exit_price)
            * size
        )

        gross_mid += trade["pnl_mid"]
        fees += trade_fees
        slippage += trade_slippage

        # Actual net equity path
        net_trade_pnl = (
            adjusted_pnl
            - trade_fees
        )

        net_equity += net_trade_pnl

        if net_equity > peak:
            peak = net_equity

        drawdown = (
            (peak - net_equity) / peak
            if peak > 0
            else 0.0
        )

        max_drawdown = max(
            max_drawdown,
            drawdown,
        )

    net = (
        gross_mid
        - fees
        - slippage
    )

    return {
        "trades": len(realized),
        "gross_mid": gross_mid,
        "fees": fees,
        "slippage": slippage,
        "net": net,
        "equity": STARTING_CAPITAL + net,
        "max_dd_net_pct": max_drawdown * 100,
    }


def main():

    candles = load_candles(
        "btc_usdt_5m_100k.json"
    )

    baseline_capital, trades = (
        extract_baseline(candles)
    )

    stop_trades = [
        trade
        for trade in trades
        if trade["exit_reason"]
        == "STOP_LOSS"
    ]

    time_trades = [
        trade
        for trade in trades
        if trade["exit_reason"]
        == "TIME_EXIT"
    ]

    print("=" * 100)
    print(
        "STOP PATH RESEARCH V2 — RESEARCH ONLY"
    )
    print("=" * 100)

    print(
        f"Candles: {len(candles)}"
    )

    print(
        f"Test: {TEST_START} -> {TEST_END}"
    )

    print(
        f"Baseline trades: {len(trades)}"
    )

    print(
        f"Baseline stops: {len(stop_trades)}"
    )

    print(
        f"Baseline time exits: {len(time_trades)}"
    )

    print(
        f"Baseline gross capital: "
        f"${baseline_capital:.4f}"
    )

    # ------------------------------------------------------
    # POST STOP
    # ------------------------------------------------------

    records = analyze_post_stop_paths(
        candles,
        trades,
    )

    print()
    print("-" * 100)
    print("POST-STOP PATH")
    print("-" * 100)

    print(
        f"Stop records: {len(records)}"
    )

    if records:

        reverted = sum(
            r["reverted_to_entry"]
            for r in records
        )

        plus_half_r = sum(
            r["reached_plus_0_5R"]
            for r in records
        )

        plus_one_r = sum(
            r["reached_plus_1R"]
            for r in records
        )

        total = len(records)

        print(
            f"Reverted to entry within available 20h: "
            f"{reverted}/{total} "
            f"({reverted / total * 100:.2f}%)"
        )

        print(
            f"Reached +0.5R after stop: "
            f"{plus_half_r}/{total} "
            f"({plus_half_r / total * 100:.2f}%)"
        )

        print(
            f"Reached +1.0R after stop: "
            f"{plus_one_r}/{total} "
            f"({plus_one_r / total * 100:.2f}%)"
        )

    print()
    print("HORIZON DATA AVAILABILITY")

    for label in HORIZONS:

        available = sum(
            r[f"available_{label}"]
            for r in records
        )

        print(
            f"{label:>4}: "
            f"{available}/{len(records)}"
        )

    # ------------------------------------------------------
    # ATR TRACE
    # ------------------------------------------------------

    print()
    print("-" * 100)
    print(
        "ISOLATED ATR TRACE "
        "(SAME BASELINE ENTRIES + SAME POSITION SIZE)"
    )
    print("-" * 100)

    print(
        f"{'ATR':>6}"
        f"{'TRADES':>8}"
        f"{'STOPS':>8}"
        f"{'TIME':>8}"
        f"{'GROSS':>13}"
        f"{'FEES':>12}"
        f"{'SLIP':>12}"
        f"{'NET':>13}"
        f"{'EQUITY':>13}"
        f"{'NET DD':>10}"
    )

    print("-" * 105)

    for multiplier in (
        2.0,
        2.5,
        3.0,
    ):

        trace = isolated_trace(
            candles,
            trades,
            multiplier,
        )

        costs = calculate_costs_and_dd(
            trace
        )

        stops = sum(
            t["exit_reason"]
            == "STOP_LOSS"
            for t in trace
        )

        times = sum(
            t["exit_reason"]
            == "TIME_EXIT"
            for t in trace
        )

        print(
            f"{multiplier:>6.1f}"
            f"{costs['trades']:>8}"
            f"{stops:>8}"
            f"{times:>8}"
            f"{costs['gross_mid']:>13.4f}"
            f"{costs['fees']:>12.4f}"
            f"{costs['slippage']:>12.4f}"
            f"{costs['net']:>13.4f}"
            f"{costs['equity']:>13.4f}"
            f"{costs['max_dd_net_pct']:>9.2f}%"
        )

    print("=" * 100)


if __name__ == "__main__":
    main()
