from statistics import median

from research_groq_30day_compounding_v5_2 import fetch_closed_candles_paginated
from money_maker_01_adapter_v1 import find_candidates


SYMBOL = "BTCUSDT"
INTERVAL = "5m"
CANDLE_LIMIT = 100_000


def build_candle_index(candles):
    return {
        candle["time"]: index
        for index, candle in enumerate(candles)
    }


def analyze_candidate(candidate, candle_index, candles):
    entry_index = candle_index.get(candidate["entry_time"])
    exit_index = candle_index.get(candidate["planned_exit_time"])

    if entry_index is None or exit_index is None:
        return None

    if exit_index < entry_index:
        return None

    entry = candidate["entry"]

    window = candles[entry_index : exit_index + 1]

    if not window:
        return None

    if candidate["signal"] == "BUY":
        max_high = max(c["high"] for c in window)
        min_low = min(c["low"] for c in window)
        fixed_exit = window[-1]["close"]

        mfe = (max_high - entry) / entry
        mae = (min_low - entry) / entry
        fixed_return = (fixed_exit - entry) / entry

    elif candidate["signal"] == "SELL":
        max_high = max(c["high"] for c in window)
        min_low = min(c["low"] for c in window)
        fixed_exit = window[-1]["close"]

        mfe = (entry - min_low) / entry
        mae = (entry - max_high) / entry
        fixed_return = (entry - fixed_exit) / entry

    else:
        return None

    return {
        "signal_time": candidate["signal_time"],
        "entry_time": candidate["entry_time"],
        "planned_exit_time": candidate["planned_exit_time"],
        "signal": candidate["signal"],
        "entry": entry,
        "fixed_exit": fixed_exit,
        "mfe": mfe,
        "mae": mae,
        "fixed_return": fixed_return,
        "bars_held": exit_index - entry_index + 1,
    }


def percentile(values, p):
    if not values:
        return None

    values = sorted(values)

    position = (len(values) - 1) * p
    lower = int(position)
    upper = min(lower + 1, len(values))

    if lower == upper:
        return values[lower]

    weight = position - lower
    return values[lower] * (1 - weight) + values[upper] * weight


def pct(value):
    return f"{value * 100:.4f}%"


def summarize(values):
    return {
        "min": min(values),
        "p25": percentile(values, 0.25),
        "median": median(values),
        "p75": percentile(values, 0.75),
        "p90": percentile(values, 0.90),
        "max": max(values),
    }


def print_distribution(name, values):
    summary = summarize(values)

    print(f"{name}")
    print(f"  Min    : {pct(summary['min'])}")
    print(f"  P25    : {pct(summary['p25'])}")
    print(f"  Median : {pct(summary['median'])}")
    print(f"  P75    : {pct(summary['p75'])}")
    print(f"  P90    : {pct(summary['p90'])}")
    print(f"  Max    : {pct(summary['max'])}")


def main():
    print("=" * 72)
    print("EXIT FORENSICS V1")
    print("=" * 72)
    print(f"Symbol   : {SYMBOL}")
    print(f"Interval : {INTERVAL}")
    print(f"Candles  : {CANDLE_LIMIT}")
    print("Entry    : MONEY_MAKER_01")
    print("Exit     : FIXED HORIZON — ANALYSIS ONLY")
    print("=" * 72)

    candles = fetch_closed_candles_paginated(
        SYMBOL,
        INTERVAL,
        CANDLE_LIMIT,
    )

    print(f"Candles returned: {len(candles)}")

    candidates = find_candidates(candles)
    print(f"Candidates      : {len(candidates)}")

    candle_index = build_candle_index(candles)

    results = []

    for candidate in candidates:
        result = analyze_candidate(
            candidate,
            candle_index,
            candles,
        )

        if result is not None:
            results.append(result)

    print(f"Resolved        : {len(results)}")
    print()

    if not results:
        print("No resolved candidates.")
        return

    mfe_values = [r["mfe"] for r in results]
    mae_values = [r["mae"] for r in results]
    fixed_values = [r["fixed_return"] for r in results]

    print("=" * 72)
    print("MFE — MAXIMUM FAVORABLE EXCURSION")
    print("=" * 72)
    print_distribution("MFE", mfe_values)
    print()

    print("=" * 72)
    print("MAE — MAXIMUM ADVERSE EXCURSION")
    print("=" * 72)
    print_distribution("MAE", mae_values)
    print()

    print("=" * 72)
    print("FIXED EXIT RETURN")
    print("=" * 72)
    print_distribution("Fixed Exit", fixed_values)
    print()

    print("=" * 72)
    print("PROFIT OPPORTUNITY COUNTS")
    print("=" * 72)

    for threshold in (0.002, 0.003, 0.005, 0.0075, 0.010, 0.015, 0.020):
        count = sum(1 for value in mfe_values if value >= threshold)
        print(
            f"MFE >= {threshold * 100:5.2f}% : "
            f"{count:4d}/{len(results)} "
            f"({count / len(results) * 100:6.2f}%)"
        )

    print()

    print("=" * 72)
    print("PROFIT WAS AVAILABLE BUT FIXED EXIT DID NOT CAPTURE IT")
    print("=" * 72)

    for threshold in (0.003, 0.005, 0.0075, 0.010):
        opportunities = [
            r for r in results
            if r["mfe"] >= threshold
            and r["fixed_return"] < threshold
        ]

        print(
            f"MFE >= {threshold * 100:5.2f}% "
            f"but fixed exit < threshold : "
            f"{len(opportunities):4d}/{len(results)} "
            f"({len(opportunities) / len(results) * 100:6.2f}%)"
        )

    print()

    print("=" * 72)
    print("MFE VS FIXED EXIT")
    print("=" * 72)

    positive_mfe = [
        r["mfe"]
        for r in results
        if r["mfe"] > 0
    ]

    positive_fixed = [
        r["fixed_return"]
        for r in results
        if r["fixed_return"] > 0
    ]

    print(f"Trades with MFE > 0       : {len(positive_mfe)}")
    print(f"Trades with Fixed Exit >0 : {len(positive_fixed)}")

    print()
    print("=" * 72)
    print("IMPORTANT")
    print("=" * 72)
    print("This is forensic analysis only.")
    print("No TP, trailing stop, stop-loss, or execution logic is tested.")
    print("No Core files were modified.")
    print("=" * 72)


if __name__ == "__main__":
    main()
