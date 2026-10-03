from collections import OrderedDict
from datetime import datetime

from research_data_cache import load_candles
from incremental_features import IncrementalFeatures
from regime import detect_regime
from strategy import analyze_market
from risk import evaluate_risk


# ============================================================
# RESEARCH ONLY
# Capital × Timeframe × Hold × Slippage
#
# Purpose:
#   Find the economics of the strategy under small capital,
#   while identifying the effect of trade frequency and costs.
#
# Core files are NOT modified.
# ============================================================

CAPITALS_THB = [1000.0, 2000.0]
REFERENCE_USDTHB = 33.58

TIMEFRAMES = OrderedDict([
    ("5m", 5),
    ("15m", 15),
    ("30m", 30),
    ("1h", 60),
    ("4h", 240),
])

HOLD_HOURS_LIST = [12, 20, 24]

FEE_RATE = 0.0005

SLIPPAGE_LEVELS = OrderedDict([
    ("0.00%", 0.0000),
    ("0.02%", 0.0002),
    ("0.05%", 0.0005),
])


def aggregate_candles(candles, minutes):
    if minutes == 5:
        return list(candles)

    bucket_seconds = minutes * 60
    result = []

    current_bucket = None
    current = None

    for candle in candles:
        ts = candle["time"]
        epoch = int(ts.timestamp())
        bucket_epoch = epoch - (epoch % bucket_seconds)

        if current_bucket != bucket_epoch:
            if current is not None:
                result.append(current)

            current_bucket = bucket_epoch

            current = {
                "time": ts.replace(second=0, microsecond=0),
                "open": candle["open"],
                "high": candle["high"],
                "low": candle["low"],
                "close": candle["close"],
                "volume": candle["volume"],
            }
        else:
            current["high"] = max(current["high"], candle["high"])
            current["low"] = min(current["low"], candle["low"])
            current["close"] = candle["close"]
            current["volume"] += candle["volume"]

    if current is not None:
        result.append(current)

    return result


def apply_cost(entry, exit_price, size, side, slippage_rate):
    if side == "BUY":
        entry_exec = entry * (1 + slippage_rate)
        exit_exec = exit_price * (1 - slippage_rate)
        gross = (exit_exec - entry_exec) * size
    else:
        entry_exec = entry * (1 - slippage_rate)
        exit_exec = exit_price * (1 + slippage_rate)
        gross = (entry_exec - exit_exec) * size

    entry_fee = entry_exec * size * FEE_RATE
    exit_fee = exit_exec * size * FEE_RATE

    fees = entry_fee + exit_fee

    slippage = (
        abs(entry_exec - entry) * size
        + abs(exit_exec - exit_price) * size
    )

    net = gross - fees

    return net, gross, fees, slippage


def run_backtest(candles, capital_usdt, timeframe_minutes,
                 hold_hours, slippage_rate):

    capital = capital_usdt
    position = None
    trades = []

    feature_engine = IncrementalFeatures()
    max_hold_bars = (hold_hours * 60) // timeframe_minutes

    for index, candle in enumerate(candles):

        features = feature_engine.update(candle)

        if index < 200:
            continue

        candle_time = candle["time"]

        # ----------------------------------------------------
        # Existing position
        # ----------------------------------------------------
        if position is not None:

            position["bars_held"] += 1

            stopped = False

            if position["side"] == "BUY":
                if candle["low"] <= position["stop_loss"]:
                    exit_price = position["stop_loss"]
                    exit_reason = "STOP_LOSS"
                    stopped = True

            else:
                if candle["high"] >= position["stop_loss"]:
                    exit_price = position["stop_loss"]
                    exit_reason = "STOP_LOSS"
                    stopped = True

            timed_out = (
                not stopped
                and position["bars_held"] >= max_hold_bars
            )

            if stopped or timed_out:

                if timed_out:
                    exit_price = candle["close"]
                    exit_reason = "TIME_EXIT"

                net, gross, fees, slip = apply_cost(
                    position["entry_price"],
                    exit_price,
                    position["position_size"],
                    position["side"],
                    slippage_rate,
                )

                capital += net

                trades.append({
                    "side": position["side"],
                    "entry_price": position["entry_price"],
                    "exit_price": exit_price,
                    "position_size": position["position_size"],
                    "gross": gross,
                    "fees": fees,
                    "slippage": slip,
                    "net": net,
                    "exit_reason": exit_reason,
                    "bars_held": position["bars_held"],
                })

                position = None
                continue

            continue

        # ----------------------------------------------------
        # New entry
        # ----------------------------------------------------
        regime = detect_regime(features)
        decision = analyze_market(features, regime)

        if decision["signal"] == "WAIT":
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
            "side": decision["signal"],
            "entry_price": features["close"],
            "position_size": risk["position_size"],
            "stop_loss": risk["stop_loss"],
            "bars_held": 0,
        }

    realized = trades

    wins = [t for t in realized if t["net"] > 0]
    losses = [t for t in realized if t["net"] < 0]

    gross_profit = sum(t["net"] for t in wins)
    gross_loss = abs(sum(t["net"] for t in losses))

    pf = (
        gross_profit / gross_loss
        if gross_loss > 0
        else None
    )

    gross = sum(t["gross"] for t in realized)
    fees = sum(t["fees"] for t in realized)
    slippage = sum(t["slippage"] for t in realized)
    net = sum(t["net"] for t in realized)

    turnover = sum(
        t["entry_price"] * t["position_size"]
        + t["exit_price"] * t["position_size"]
        for t in realized
    )

    avg_net = (
        net / len(realized)
        if realized else 0.0
    )

    return {
        "trades": len(realized),
        "wins": len(wins),
        "losses": len(losses),
        "wr": (
            len(wins) / len(realized) * 100
            if realized else 0.0
        ),
        "gross": gross,
        "fees": fees,
        "slippage": slippage,
        "net": net,
        "net_pct": (
            net / capital_usdt * 100
            if capital_usdt else 0.0
        ),
        "avg_net": avg_net,
        "pf": pf,
        "turnover": turnover,
        "stop": sum(
            1 for t in realized
            if t["exit_reason"] == "STOP_LOSS"
        ),
        "time": sum(
            1 for t in realized
            if t["exit_reason"] == "TIME_EXIT"
        ),
    }


def print_group(rows, capital_thb):

    print()
    print("=" * 150)
    print(f"CAPITAL = THB {capital_thb:,.0f}")
    print("=" * 150)

    print(
        f"{'TF':<6}"
        f"{'Hold':>7}"
        f"{'Slip':>8}"
        f"{'Trades':>8}"
        f"{'WR':>8}"
        f"{'Gross':>11}"
        f"{'Fees':>10}"
        f"{'Slip$':>10}"
        f"{'Net':>11}"
        f"{'Net%':>9}"
        f"{'Avg/Tr':>10}"
        f"{'PF':>8}"
        f"{'Turnover':>13}"
    )

    print("-" * 150)

    for row in rows:
        pf = (
            f"{row['pf']:.3f}"
            if row["pf"] is not None
            else "N/A"
        )

        print(
            f"{row['tf']:<6}"
            f"{row['hold']:>6}h"
            f"{row['slip_name']:>8}"
            f"{row['trades']:>8}"
            f"{row['wr']:>7.2f}%"
            f"{row['gross']:>11.3f}"
            f"{row['fees']:>10.3f}"
            f"{row['slippage']:>10.3f}"
            f"{row['net']:>11.3f}"
            f"{row['net_pct']:>8.2f}%"
            f"{row['avg_net']:>10.4f}"
            f"{pf:>8}"
            f"{row['turnover']:>13.2f}"
        )


def main():

    print("=" * 150)
    print("CAPITAL × TIMEFRAME × HOLD × COST MATRIX")
    print("=" * 150)

    candles_5m = load_candles()

    print(f"Source candles : {len(candles_5m):,}")
    print(f"Reference FX   : {REFERENCE_USDTHB:.2f} THB/USD")
    print(f"Fee            : {FEE_RATE * 100:.3f}% each side")
    print(f"Capital cases  : {CAPITALS_THB}")
    print(f"Timeframes     : {list(TIMEFRAMES.keys())}")
    print(f"Hold hours     : {HOLD_HOURS_LIST}")
    print(f"Slippage       : {list(SLIPPAGE_LEVELS.keys())}")

    aggregated = {}

    for tf, minutes in TIMEFRAMES.items():
        print(f"Preparing {tf} ...")
        aggregated[tf] = aggregate_candles(
            candles_5m,
            minutes,
        )

    all_results = []

    for capital_thb in CAPITALS_THB:

        capital_usdt = (
            capital_thb / REFERENCE_USDTHB
        )

        rows = []

        for tf, minutes in TIMEFRAMES.items():

            candles = aggregated[tf]

            for hold_hours in HOLD_HOURS_LIST:

                for slip_name, slip_rate in SLIPPAGE_LEVELS.items():

                    result = run_backtest(
                        candles=candles,
                        capital_usdt=capital_usdt,
                        timeframe_minutes=minutes,
                        hold_hours=hold_hours,
                        slippage_rate=slip_rate,
                    )

                    row = {
                        "capital_thb": capital_thb,
                        "tf": tf,
                        "hold": hold_hours,
                        "slip_name": slip_name,
                        **result,
                    }

                    rows.append(row)
                    all_results.append(row)

        print_group(rows, capital_thb)

    # --------------------------------------------------------
    # Capital comparison at each configuration
    # --------------------------------------------------------

    print()
    print("=" * 150)
    print("CAPITAL COMPARISON — SAME CONFIGURATION")
    print("=" * 150)

    print(
        f"{'TF':<6}"
        f"{'Hold':>7}"
        f"{'Slip':>8}"
        f"{'1k Net':>12}"
        f"{'1k %':>9}"
        f"{'2k Net':>12}"
        f"{'2k %':>9}"
        f"{'Net Ratio':>11}"
        f"{'Trade Δ':>9}"
    )

    print("-" * 150)

    index = {}

    for row in all_results:
        key = (
            row["capital_thb"],
            row["tf"],
            row["hold"],
            row["slip_name"],
        )
        index[key] = row

    for tf in TIMEFRAMES:
        for hold in HOLD_HOURS_LIST:
            for slip_name in SLIPPAGE_LEVELS:

                a = index[(1000.0, tf, hold, slip_name)]
                b = index[(2000.0, tf, hold, slip_name)]

                ratio = (
                    b["net"] / a["net"]
                    if abs(a["net"]) > 1e-12
                    else None
                )

                ratio_text = (
                    f"{ratio:.2f}"
                    if ratio is not None
                    else "N/A"
                )

                print(
                    f"{tf:<6}"
                    f"{hold:>6}h"
                    f"{slip_name:>8}"
                    f"{a['net']:>12.3f}"
                    f"{a['net_pct']:>8.2f}%"
                    f"{b['net']:>12.3f}"
                    f"{b['net_pct']:>8.2f}%"
                    f"{ratio_text:>11}"
                    f"{b['trades'] - a['trades']:>9}"
                )

    # --------------------------------------------------------
    # Summary: identify configurations that survive 0.02%
    # slippage at BOTH capital levels.
    # --------------------------------------------------------

    print()
    print("=" * 150)
    print("ROBUSTNESS SCREEN — BOTH CAPITAL LEVELS")
    print("=" * 150)

    candidates = []

    for tf in TIMEFRAMES:
        for hold in HOLD_HOURS_LIST:

            a = index[(1000.0, tf, hold, "0.02%")]
            b = index[(2000.0, tf, hold, "0.02%")]

            if a["net"] > 0 and b["net"] > 0:
                candidates.append((tf, hold, a, b))

    if not candidates:
        print("No configuration is positive at BOTH capital levels under 0.02% slippage.")

    else:
        print(
            f"{'TF':<6}"
            f"{'Hold':>7}"
            f"{'1k Net':>12}"
            f"{'1k %':>9}"
            f"{'2k Net':>12}"
            f"{'2k %':>9}"
            f"{'1k PF':>9}"
            f"{'2k PF':>9}"
        )

        for tf, hold, a, b in candidates:
            pf_a = (
                f"{a['pf']:.3f}"
                if a["pf"] is not None
                else "N/A"
            )

            pf_b = (
                f"{b['pf']:.3f}"
                if b["pf"] is not None
                else "N/A"
            )

            print(
                f"{tf:<6}"
                f"{hold:>6}h"
                f"{a['net']:>12.3f}"
                f"{a['net_pct']:>8.2f}%"
                f"{b['net']:>12.3f}"
                f"{b['net_pct']:>8.2f}%"
                f"{pf_a:>9}"
                f"{pf_b:>9}"
            )

    print()
    print("=" * 150)
    print("RESEARCH ONLY — NO CORE FILES MODIFIED")
    print("=" * 150)
    print("Capital is a scenario variable, not a strategy optimization target.")
    print("No configuration is declared profitable from this matrix alone.")
    print("Next validation must be temporal and must use frozen choices.")


if __name__ == "__main__":
    main()
