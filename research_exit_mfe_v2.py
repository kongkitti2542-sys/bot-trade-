"""
Exit MFE Research V2

Research-only analysis of Money Maker #1 exit opportunity.

Locked research standard:
    BTCUSDT 5m
    7D  = 2,016 closed candles
    30D = 8,640 closed candles

Measures:
    - Average MFE
    - Median MFE
    - P25 / P75 / P90
    - MFE after 0.14% round-trip research cost
    - MFE threshold hit rates
    - Bars to MFE
    - Time to MFE
    - BUY / SELL breakdown
    - Per-candidate records

No execution.
No AI.
No Core modification.
"""

import json
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean, median

from research_groq_30day_compounding_v5_2 import (
    fetch_closed_candles_paginated,
)
from money_maker_01_adapter_v1 import find_candidates
from research_standard_v1 import (
    STANDARD_VERSION,
    SYMBOL,
    INTERVAL,
    WINDOW_7D_CANDLES,
    WINDOW_30D_CANDLES,
)

CANDLE_LIMIT = WINDOW_30D_CANDLES

FEE_PER_SIDE = 0.0005
SLIPPAGE_PER_SIDE = 0.0002
ROUND_TRIP_COST = (
    2 * FEE_PER_SIDE
    + 2 * SLIPPAGE_PER_SIDE
)

TP_THRESHOLDS = (
    0.0014,
    0.0020,
    0.0030,
    0.0050,
    0.0075,
    0.0100,
    0.0150,
    0.0200,
)

OUTPUT_FILE = Path(
    "research_exit_mfe_v2_results.json"
)


def build_candle_index(candles):
    return {
        candle["time"]: index
        for index, candle in enumerate(candles)
    }


def analyze_candidate(
    candidate,
    candle_index,
    candles,
):
    entry_index = candle_index.get(
        candidate["entry_time"]
    )

    exit_index = candle_index.get(
        candidate["planned_exit_time"]
    )

    if entry_index is None or exit_index is None:
        return None

    if exit_index < entry_index:
        return None

    entry = candidate["entry"]

    window = candles[
        entry_index : exit_index + 1
    ]

    if not window:
        return None

    if candidate["signal"] == "BUY":
        mfe_index = max(
            range(entry_index, exit_index + 1),
            key=lambda i: candles[i]["high"],
        )

        max_price = candles[mfe_index]["high"]
        mfe = (max_price - entry) / entry

    elif candidate["signal"] == "SELL":
        mfe_index = min(
            range(entry_index, exit_index + 1),
            key=lambda i: candles[i]["low"],
        )

        min_price = candles[mfe_index]["low"]
        mfe = (entry - min_price) / entry

    else:
        return None

    bars_to_mfe = (
        mfe_index - entry_index + 1
    )

    minutes_to_mfe = (
        bars_to_mfe * 5
    )

    return {
        "signal_time": candidate["signal_time"],
        "entry_time": candidate["entry_time"],
        "planned_exit_time": candidate[
            "planned_exit_time"
        ],
        "signal": candidate["signal"],
        "entry": entry,
        "mfe": mfe,
        "mfe_after_cost": (
            mfe - ROUND_TRIP_COST
        ),
        "mfe_index": mfe_index,
        "bars_held": (
            exit_index - entry_index + 1
        ),
        "bars_to_mfe": bars_to_mfe,
        "minutes_to_mfe": minutes_to_mfe,
        "hours_to_mfe": (
            minutes_to_mfe / 60.0
        ),
        "mfe_time": candles[
            mfe_index
        ]["time"],
    }


def percentile(values, p):
    if not values:
        return None

    values = sorted(values)

    position = (
        (len(values) - 1) * p
    )

    lower = int(position)
    upper = min(
        lower + 1,
        len(values) - 1,
    )

    if lower == upper:
        return values[lower]

    weight = position - lower

    return (
        values[lower] * (1 - weight)
        + values[upper] * weight
    )


def summarize(values):
    if not values:
        return {
            "count": 0,
            "average": 0.0,
            "min": 0.0,
            "p25": 0.0,
            "median": 0.0,
            "p75": 0.0,
            "p90": 0.0,
            "max": 0.0,
        }

    return {
        "count": len(values),
        "average": mean(values),
        "min": min(values),
        "p25": percentile(values, 0.25),
        "median": median(values),
        "p75": percentile(values, 0.75),
        "p90": percentile(values, 0.90),
        "max": max(values),
    }


def threshold_summary(results):
    total = len(results)

    output = {}

    for threshold in TP_THRESHOLDS:
        count = sum(
            1
            for result in results
            if result["mfe"] >= threshold
        )

        output[f"{threshold:.4f}"] = {
            "threshold_pct": threshold * 100,
            "count": count,
            "total": total,
            "rate_pct": (
                count / total * 100
                if total
                else 0.0
            ),
        }

    return output


def side_summary(results):
    output = {}

    for side in ("BUY", "SELL"):
        side_results = [
            result
            for result in results
            if result["signal"] == side
        ]

        mfe_values = [
            result["mfe"]
            for result in side_results
        ]

        bars_values = [
            result["bars_to_mfe"]
            for result in side_results
        ]

        output[side] = {
            "count": len(side_results),
            "mfe": summarize(mfe_values),
            "bars_to_mfe": summarize(
                bars_values
            ),
        }

    return output


def analyze_window(
    window_name,
    window_candles,
    all_candidates,
):
    candle_index = build_candle_index(
        window_candles
    )

    candidates = [
        candidate
        for candidate in all_candidates
        if candidate["entry_time"]
        in candle_index
    ]

    results = []

    for candidate in candidates:
        result = analyze_candidate(
            candidate,
            candle_index,
            window_candles,
        )

        if result is not None:
            results.append(result)

    mfe_values = [
        result["mfe"]
        for result in results
    ]

    mfe_after_cost_values = [
        result["mfe_after_cost"]
        for result in results
    ]

    bars_to_mfe_values = [
        result["bars_to_mfe"]
        for result in results
    ]

    return {
        "window": window_name,
        "candles": len(window_candles),
        "first_candle": (
            window_candles[0]["time"]
            if window_candles
            else None
        ),
        "last_candle": (
            window_candles[-1]["time"]
            if window_candles
            else None
        ),
        "candidates": len(candidates),
        "resolved": len(results),
        "mfe": summarize(mfe_values),
        "mfe_after_cost": summarize(
            mfe_after_cost_values
        ),
        "bars_to_mfe": summarize(
            bars_to_mfe_values
        ),
        "hours_to_mfe": summarize([
            result["hours_to_mfe"]
            for result in results
        ]),
        "thresholds": threshold_summary(
            results
        ),
        "side_summary": side_summary(
            results
        ),
        "results": results,
    }


def split_windows(candles, window_size):
    windows = []

    for start in range(
        0,
        len(candles),
        window_size,
    ):
        window = candles[
            start : start + window_size
        ]

        if len(window) == window_size:
            windows.append(window)

    return windows


def main():
    print("=" * 72)
    print("EXIT MFE RESEARCH V2")
    print("STANDARD RESEARCH WINDOWS")
    print("=" * 72)

    print(f"Symbol            : {SYMBOL}")
    print(f"Interval          : {INTERVAL}")
    print(
        f"Research Standard : {STANDARD_VERSION}"
    )
    print(
        f"7D Window         : "
        f"{WINDOW_7D_CANDLES:,} candles"
    )
    print(
        f"30D Window        : "
        f"{WINDOW_30D_CANDLES:,} candles"
    )
    print(
        f"Fetch Limit       : "
        f"{CANDLE_LIMIT:,} candles"
    )
    print(
        f"Research Cost     : "
        f"{ROUND_TRIP_COST * 100:.4f}% RT"
    )
    print(
        "MFE               : "
        "Maximum Favorable Excursion"
    )
    print(
        "Windowing         : "
        "NON-OVERLAPPING"
    )
    print("=" * 72)

    print(
        "Fetching standard research dataset..."
    )

    candles = fetch_closed_candles_paginated(
        SYMBOL,
        INTERVAL,
        CANDLE_LIMIT,
    )

    print(
        f"Candles returned  : {len(candles):,}"
    )

    if len(candles) < WINDOW_7D_CANDLES:
        print("RESULT: STOPPED")
        print("Reason: INSUFFICIENT_7D_DATA")
        return

    print(
        "First candle      :",
        candles[0]["time"],
    )

    print(
        "Last candle       :",
        candles[-1]["time"],
    )

    candidates = find_candidates(
        candles
    )

    print(
        f"Candidates        : {len(candidates)}"
    )

    all_results = {
        "7D": [],
        "30D": [],
    }

    for window_name, window_size in (
        ("7D", WINDOW_7D_CANDLES),
        ("30D", WINDOW_30D_CANDLES),
    ):
        windows = split_windows(
            candles,
            window_size,
        )

        for index, window in enumerate(
            windows,
            start=1,
        ):
            label = (
                f"{window_name}_W"
                f"{index:02d}"
            )

            analysis = analyze_window(
                label,
                window,
                candidates,
            )

            all_results[
                window_name
            ].append(analysis)

    output = {
        "research_version": (
            "EXIT_MFE_RESEARCH_V2"
        ),
        "generated_at": datetime.now(
            timezone.utc
        ).isoformat(),
        "research_standard": (
            STANDARD_VERSION
        ),
        "symbol": SYMBOL,
        "interval": INTERVAL,
        "windowing": (
            "NON_OVERLAPPING"
        ),
        "window_sizes": {
            "7D": WINDOW_7D_CANDLES,
            "30D": WINDOW_30D_CANDLES,
        },
        "research_cost_round_trip": (
            ROUND_TRIP_COST
        ),
        "actual_candles": len(candles),
        "candidates_found": len(
            candidates
        ),
        "windows": all_results,
    }

    OUTPUT_FILE.write_text(
        json.dumps(
            output,
            indent=2,
            ensure_ascii=False,
            default=str,
        ),
        encoding="utf-8",
    )

    print("=" * 72)
    print("MFE STANDARD RESEARCH RESULT")
    print("=" * 72)

    for window_name in ("7D", "30D"):
        print()
        print(
            f"### {window_name}"
        )

        for row in all_results[
            window_name
        ]:
            mfe = row["mfe"]
            after_cost = row[
                "mfe_after_cost"
            ]
            bars = row[
                "bars_to_mfe"
            ]
            hours = row[
                "hours_to_mfe"
            ]

            print(
                f"{row['window']}: "
                f"N={row['resolved']} "
                f"AvgMFE={mfe['average'] * 100:.4f}% "
                f"Median={mfe['median'] * 100:.4f}% "
                f"P75={mfe['p75'] * 100:.4f}% "
                f"P90={mfe['p90'] * 100:.4f}% "
                f"Max={mfe['max'] * 100:.4f}%"
            )

            print(
                f"  AfterCost Median="
                f"{after_cost['median'] * 100:.4f}% "
                f"AvgBars={bars['average']:.2f} "
                f"MedianBars={bars['median']:.2f} "
                f"MedianHours={hours['median']:.2f}"
            )

            print(
                "  Thresholds:",
                " ".join(
                    f"{threshold['threshold_pct']:.2f}%="
                    f"{threshold['rate_pct']:.2f}%"
                    for threshold in row[
                        "thresholds"
                    ].values()
                ),
            )

    print()
    print("=" * 72)
    print("Saved:", OUTPUT_FILE)
    print("=" * 72)


if __name__ == "__main__":
    main()
