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


def events_from_windows(windows):
    """
    Combine overlapping signal windows into one Opportunity Event.

    An event continues while the next signal starts before the
    previous event has completely ended.
    """
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


def event_overlap(event):
    points = sorted(
        set(
            [w["entry"] for w in event]
            + [w["exit"] for w in event]
        )
    )

    maximum = 0

    for point in points:
        active = [
            w
            for w in event
            if w["entry"] <= point < w["exit"]
        ]

        maximum = max(maximum, len(active))

    return maximum


def print_event(event, index):
    first = event[0]
    last = event[-1]

    signal_entry = first["entry"]
    event_exit = max(w["exit"] for w in event)

    summed_net = sum(
        w["record"]["net"]
        for w in event
    )

    max_overlap = event_overlap(event)

    print(
        f"Event {index}: "
        f"Signals={len(event)} "
        f"MaxOverlap={max_overlap} "
        f"SignalNetSum={summed_net:+.4%}"
    )

    print(f"  Start       : {signal_entry}")
    print(f"  End         : {event_exit}")
    print(
        "  Signals     : "
        + ", ".join(str(w["number"]) for w in event)
    )

    print()


def main():
    print("=" * 72)
    print("BLOCK 3 EVENT ANALYZER V1")
    print("=" * 72)
    print("Purpose: convert overlapping signals into Opportunity Events")
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
    events = events_from_windows(windows)

    print(f"Candles             : {len(candles)}")
    print(f"Block 3 Signals     : {len(block3)}")
    print(f"Holding Period      : {HOLD_MINUTES} minutes")
    print(f"Opportunity Events  : {len(events)}")
    print()

    print("=" * 72)
    print("OPPORTUNITY EVENTS")
    print("=" * 72)

    for index, event in enumerate(events, start=1):
        print_event(event, index)

    print("=" * 72)
    print("EVENT SUMMARY")
    print("=" * 72)

    positive_events = 0
    negative_events = 0
    single_signal_events = 0
    multi_signal_events = 0

    total_signal_net = sum(
        record["net"]
        for record in block3
    )

    for event in events:
        event_net = sum(
            w["record"]["net"]
            for w in event
        )

        if event_net > 0:
            positive_events += 1
        elif event_net < 0:
            negative_events += 1

        if len(event) == 1:
            single_signal_events += 1
        else:
            multi_signal_events += 1

    print(f"Total Events        : {len(events)}")
    print(f"Positive Events     : {positive_events}")
    print(f"Negative Events     : {negative_events}")
    print(f"Single-signal       : {single_signal_events}")
    print(f"Multi-signal        : {multi_signal_events}")
    print(f"Original Signal Net : {total_signal_net:+.4%}")

    print()
    print("=" * 72)
    print("IMPORTANT")
    print("=" * 72)
    print(
        "SignalNetSum is shown only as a reference. "
        "It is NOT treated as independent capital returns."
    )
    print(
        "This analyzer is research-only and does not establish "
        "a live trading rule."
    )


if __name__ == "__main__":
    main()
