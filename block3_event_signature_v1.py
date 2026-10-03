from statistics import mean, median
from datetime import timedelta

from block3_analyzer_v1 import build_trade_records, split_blocks
from validate_atr_expansion_ema50 import fetch_closed_candles, HORIZON


TIMEFRAME_MINUTES = 5
HOLD_MINUTES = HORIZON * TIMEFRAME_MINUTES


FEATURE_KEYS = (
    "expansion_ratio",
    "range_atr_ratio",
    "relative_volume",
    "ema50_distance",
)


def get_window(record):
    signal_time = record["time"]
    entry_time = signal_time + timedelta(minutes=TIMEFRAME_MINUTES)
    exit_time = entry_time + timedelta(minutes=HOLD_MINUTES)
    return entry_time, exit_time


def build_windows(records):
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

    return windows


def build_events(windows):
    if not windows:
        return []

    events = []
    current = [windows[0]]
    current_end = windows[0]["exit"]

    for window in windows[1:]:
        if window["entry"] < current_end:
            current.append(window)
            current_end = max(current_end, window["exit"])
        else:
            events.append(current)
            current = [window]
            current_end = window["exit"]

    events.append(current)
    return events


def max_overlap(event):
    points = sorted(
        set(
            [window["entry"] for window in event]
            + [window["exit"] for window in event]
        )
    )

    maximum = 0

    for point in points:
        active = [
            window
            for window in event
            if window["entry"] <= point < window["exit"]
        ]

        maximum = max(maximum, len(active))

    return maximum


def feature_summary(event, key):
    values = [
        window["record"][key]
        for window in event
    ]

    return {
        "mean": mean(values),
        "median": median(values),
        "min": min(values),
        "max": max(values),
    }


def event_summary(event):
    signal_nets = [
        window["record"]["net"]
        for window in event
    ]

    return {
        "signals": len(event),
        "max_overlap": max_overlap(event),
        "signal_net_sum": sum(signal_nets),
        "start": event[0]["entry"],
        "end": max(window["exit"] for window in event),
        "features": {
            key: feature_summary(event, key)
            for key in FEATURE_KEYS
        },
    }


def print_feature_line(label, summary):
    print(
        f"{label:<18}"
        f"mean={summary['mean']:<10.4f}"
        f"median={summary['median']:<10.4f}"
        f"min={summary['min']:<10.4f}"
        f"max={summary['max']:<10.4f}"
    )


def print_event(index, summary):
    print(
        f"Event {index:<2} "
        f"Signals={summary['signals']:<2} "
        f"MaxOverlap={summary['max_overlap']:<2} "
        f"SignalNetSum={summary['signal_net_sum']:+.4%}"
    )

    print(f"  Start : {summary['start']}")
    print(f"  End   : {summary['end']}")

    print_feature_line(
        "  ATR Expansion",
        summary["features"]["expansion_ratio"],
    )

    print_feature_line(
        "  Range / ATR",
        summary["features"]["range_atr_ratio"],
    )

    print_feature_line(
        "  Relative Volume",
        summary["features"]["relative_volume"],
    )

    print_feature_line(
        "  Close vs EMA50",
        summary["features"]["ema50_distance"],
    )

    print()


def group_feature_stats(event_summaries, key):
    values = [
        summary["features"][key]["mean"]
        for summary in event_summaries
    ]

    if not values:
        return {
            "mean": 0.0,
            "median": 0.0,
            "min": 0.0,
            "max": 0.0,
        }

    return {
        "mean": mean(values),
        "median": median(values),
        "min": min(values),
        "max": max(values),
    }


def print_group(name, event_summaries):
    print()
    print("=" * 72)
    print(name)
    print("=" * 72)

    if not event_summaries:
        print("No events.")
        return

    total_signals = sum(
        summary["signals"]
        for summary in event_summaries
    )

    total_signal_net = sum(
        summary["signal_net_sum"]
        for summary in event_summaries
    )

    print(f"Events              : {len(event_summaries)}")
    print(f"Signals             : {total_signals}")
    print(f"SignalNetSum        : {total_signal_net:+.4%}")
    print()

    for key, label in (
        ("expansion_ratio", "ATR Expansion"),
        ("range_atr_ratio", "Range / ATR"),
        ("relative_volume", "Relative Volume"),
        ("ema50_distance", "Close vs EMA50"),
    ):
        stats = group_feature_stats(event_summaries, key)

        print(
            f"{label:<18}"
            f"mean={stats['mean']:<10.4f}"
            f"median={stats['median']:<10.4f}"
            f"min={stats['min']:<10.4f}"
            f"max={stats['max']:<10.4f}"
        )


def main():
    print("=" * 72)
    print("BLOCK 3 EVENT SIGNATURE ANALYZER V1")
    print("=" * 72)
    print("Purpose: compare signatures of profitable and losing Events")
    print("Mode   : RESEARCH ONLY")
    print()

    candles = fetch_closed_candles()
    records = build_trade_records(candles)
    blocks = split_blocks(records)

    if len(blocks) < 3:
        print("Block 3 not available.")
        return

    block3 = blocks[2]
    windows = build_windows(block3)
    events = build_events(windows)

    summaries = [
        event_summary(event)
        for event in events
    ]

    print(f"Candles             : {len(candles)}")
    print(f"Block 3 Signals     : {len(block3)}")
    print(f"Holding Period      : {HOLD_MINUTES} minutes")
    print(f"Opportunity Events  : {len(summaries)}")
    print()

    print("=" * 72)
    print("EVENT SIGNATURES")
    print("=" * 72)

    for index, summary in enumerate(summaries, start=1):
        print_event(index, summary)

    positive = [
        summary
        for summary in summaries
        if summary["signal_net_sum"] > 0
    ]

    negative = [
        summary
        for summary in summaries
        if summary["signal_net_sum"] <= 0
    ]

    print_group("POSITIVE EVENTS", positive)
    print_group("NEGATIVE EVENTS", negative)

    print()
    print("=" * 72)
    print("EVENT COMPARISON")
    print("=" * 72)

    for key, label in (
        ("expansion_ratio", "ATR Expansion"),
        ("range_atr_ratio", "Range / ATR"),
        ("relative_volume", "Relative Volume"),
        ("ema50_distance", "Close vs EMA50"),
    ):
        positive_stats = group_feature_stats(positive, key)
        negative_stats = group_feature_stats(negative, key)

        print()
        print(label)
        print(
            f"  Positive Events : "
            f"mean={positive_stats['mean']:.4f} "
            f"median={positive_stats['median']:.4f}"
        )
        print(
            f"  Negative Events : "
            f"mean={negative_stats['mean']:.4f} "
            f"median={negative_stats['median']:.4f}"
        )

    print()
    print("=" * 72)
    print("NOTE")
    print("=" * 72)
    print(
        "This analyzer describes historical Event characteristics only."
    )
    print(
        "It does not establish causality, future profitability, "
        "or a live trading rule."
    )
    print(
        "SignalNetSum is not treated as independent capital return."
    )
    print(
        "No position size, leverage, or capital allocation is assumed."
    )


if __name__ == "__main__":
    main()
