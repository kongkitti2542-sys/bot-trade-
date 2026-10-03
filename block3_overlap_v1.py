from datetime import timedelta

from block3_analyzer_v1 import build_trade_records, split_blocks
from validate_atr_expansion_ema50 import fetch_closed_candles, HORIZON


TIMEFRAME_MINUTES = 5
HOLD_MINUTES = HORIZON * TIMEFRAME_MINUTES


def get_window(record):
    signal_time = record["time"]
    entry_time = signal_time + timedelta(minutes=TIMEFRAME_MINUTES)
    exit_time = entry_time + timedelta(minutes=HOLD_MINUTES)

    return entry_time, exit_time


def analyze_overlap(records):
    windows = []

    for number, record in enumerate(records, start=1):
        entry_time, exit_time = get_window(record)

        windows.append(
            {
                "number": number,
                "record": record,
                "entry": entry_time,
                "exit": exit_time,
            }
        )

    max_overlap = 0
    max_points = []

    for window in windows:
        active = [
            other
            for other in windows
            if other["entry"] <= window["entry"] < other["exit"]
        ]

        overlap = len(active)

        if overlap > max_overlap:
            max_overlap = overlap
            max_points = [window["entry"]]
        elif overlap == max_overlap:
            max_points.append(window["entry"])

    return windows, max_overlap, max_points


def print_window_table(windows):
    print(
        f"{'#':<4}"
        f"{'SIGNAL TIME':<24}"
        f"{'ENTRY':<24}"
        f"{'EXIT':<24}"
        f"{'NET':>10}"
    )

    print("-" * 110)

    for window in windows:
        record = window["record"]

        print(
            f"{window['number']:<4}"
            f"{str(record['time']):<24}"
            f"{str(window['entry']):<24}"
            f"{str(window['exit']):<24}"
            f"{record['net']:>9.3%}"
        )


def print_overlap_timeline(windows):
    points = sorted(
        set(
            [w["entry"] for w in windows]
            + [w["exit"] for w in windows]
        )
    )

    print()
    print("OVERLAP TIMELINE")
    print("-" * 72)

    maximum = 0

    for point in points:
        active = [
            w
            for w in windows
            if w["entry"] <= point < w["exit"]
        ]

        count = len(active)

        if count > maximum:
            maximum = count

        if count > 0:
            ids = ",".join(str(w["number"]) for w in active)

            print(
                f"{point}  "
                f"Active={count:<2} "
                f"Signals=[{ids}]"
            )

    print()
    print(f"Maximum Concurrent Signals : {maximum}")


def main():
    print("=" * 72)
    print("BLOCK 3 OVERLAP ANALYZER V1")
    print("=" * 72)
    print("Purpose: measure overlapping positions inside winning clusters")
    print("Mode   : RESEARCH ONLY")
    print()

    candles = fetch_closed_candles()
    records = build_trade_records(candles)
    blocks = split_blocks(records)

    if len(blocks) < 3:
        print("Block 3 not available.")
        return

    block3 = blocks[2]

    print(f"Candles             : {len(candles)}")
    print(f"Block 3 Trades      : {len(block3)}")
    print(f"Holding Period      : {HOLD_MINUTES} minutes")
    print()

    windows, max_overlap, max_points = analyze_overlap(block3)

    print_window_table(windows)

    print()
    print("=" * 72)
    print("OVERLAP RESULT")
    print("=" * 72)

    print(f"Maximum Concurrent  : {max_overlap}")
    print(f"Peak Points         : {len(max_points)}")

    if max_points:
        for point in max_points:
            print(f"  {point}")

    print_overlap_timeline(windows)

    print()
    print("=" * 72)
    print("CLUSTER WINDOWS")
    print("=" * 72)

    positive_runs = []
    current = []

    for window in windows:
        if window["record"]["net"] > 0:
            current.append(window)
        else:
            if current:
                positive_runs.append(current)
                current = []

    if current:
        positive_runs.append(current)

    for index, run in enumerate(positive_runs, start=1):
        total_net = sum(w["record"]["net"] for w in run)

        run_windows, run_max, _ = analyze_overlap(
            [w["record"] for w in run]
        )

        print(
            f"Cluster {index}: "
            f"Trades={len(run)} "
            f"Net={total_net:+.4%} "
            f"MaxOverlap={run_max}"
        )

        print(
            f"  Start : {run[0]['entry']}"
        )
        print(
            f"  End   : {run[-1]['exit']}"
        )

    print()
    print("=" * 72)
    print("NOTE")
    print("=" * 72)
    print("No position size, leverage, or capital allocation is assumed.")
    print("This test only measures the actual historical signal overlap.")
    print("It does not establish a live trading rule.")


if __name__ == "__main__":
    main()
