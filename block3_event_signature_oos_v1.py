from datetime import timedelta
from statistics import mean, median

from block3_analyzer_v1 import build_trade_records
from validate_atr_expansion_ema50 import fetch_closed_candles, HORIZON


TIMEFRAME_MINUTES = 5
HOLD_MINUTES = HORIZON * TIMEFRAME_MINUTES

DISCOVERY_RATIO = 0.50

FEATURE_KEYS = (
    "expansion_ratio",
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
        entry, exit_time = get_window(record)

        windows.append(
            {
                "number": number,
                "record": record,
                "entry": entry,
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


def event_summary(event):
    nets = [w["record"]["net"] for w in event]

    result = {
        "signals": len(event),
        "net_sum": sum(nets),
        "start": event[0]["entry"],
        "end": max(w["exit"] for w in event),
    }

    for key in FEATURE_KEYS:
        values = [w["record"][key] for w in event]
        result[key] = {
            "mean": mean(values),
            "median": median(values),
        }

    return result


def split_dataset(records):
    split_index = int(len(records) * DISCOVERY_RATIO)

    discovery_records = records[:split_index]
    validation_records = records[split_index:]

    return discovery_records, validation_records


def summarize_group(name, events):
    print()
    print("=" * 72)
    print(name)
    print("=" * 72)

    if not events:
        print("Events : 0")
        return

    positive = [
        event for event in events
        if event["net_sum"] > 0
    ]

    negative = [
        event for event in events
        if event["net_sum"] <= 0
    ]

    print(f"Events          : {len(events)}")
    print(f"Positive Events : {len(positive)}")
    print(f"Negative Events : {len(negative)}")
    print()

    for label, subset in (
        ("ALL", events),
        ("POSITIVE", positive),
        ("NEGATIVE", negative),
    ):
        if not subset:
            print(f"{label:<10}: N=0")
            continue

        print(f"{label:<10}: N={len(subset)}")

        for key in FEATURE_KEYS:
            values = [
                event[key]["mean"]
                for event in subset
            ]

            print(
                f"  {key:<20}"
                f"mean={mean(values):.4f} "
                f"median={median(values):.4f}"
            )

        print()


def compare_positive_negative(events):
    positive = [
        event for event in events
        if event["net_sum"] > 0
    ]

    negative = [
        event for event in events
        if event["net_sum"] <= 0
    ]

    print("=" * 72)
    print("POSITIVE VS NEGATIVE SIGNATURE")
    print("=" * 72)

    if not positive or not negative:
        print("Insufficient positive/negative event groups.")
        return

    for key in FEATURE_KEYS:
        positive_values = [
            event[key]["mean"]
            for event in positive
        ]

        negative_values = [
            event[key]["mean"]
            for event in negative
        ]

        positive_mean = mean(positive_values)
        negative_mean = mean(negative_values)

        if positive_mean > negative_mean:
            direction = "POSITIVE > NEGATIVE"
        elif positive_mean < negative_mean:
            direction = "POSITIVE < NEGATIVE"
        else:
            direction = "EQUAL"

        print()
        print(key)
        print(
            f"  Positive mean : {positive_mean:.4f}"
        )
        print(
            f"  Negative mean : {negative_mean:.4f}"
        )
        print(
            f"  Direction     : {direction}"
        )


def print_event_list(name, events):
    print()
    print("=" * 72)
    print(name)
    print("=" * 72)

    if not events:
        print("No events.")
        return

    for index, event in enumerate(events, start=1):
        print(
            f"Event {index:<2} "
            f"Signals={event['signals']:<2} "
            f"NetSum={event['net_sum']:+.4%}"
        )
        print(
            f"  {event['start']} -> {event['end']}"
        )


def main():
    print("=" * 72)
    print("BLOCK 3 EVENT SIGNATURE OOS VALIDATOR V1")
    print("=" * 72)
    print("Purpose: chronological discovery -> out-of-sample validation")
    print("Mode   : RESEARCH ONLY")
    print()

    candles = fetch_closed_candles()
    records = build_trade_records(candles)

    if len(records) < 20:
        print("Not enough trade records.")
        return

    discovery_records, validation_records = split_dataset(records)

    discovery_windows = build_windows(discovery_records)
    validation_windows = build_windows(validation_records)

    discovery_events = [
        event_summary(event)
        for event in build_events(discovery_windows)
    ]

    validation_events = [
        event_summary(event)
        for event in build_events(validation_windows)
    ]

    print(f"Candles              : {len(candles)}")
    print(f"Trade Records        : {len(records)}")
    print(f"Discovery Records    : {len(discovery_records)}")
    print(f"Validation Records   : {len(validation_records)}")
    print(f"Holding Period       : {HOLD_MINUTES} minutes")

    print_event_list(
        "DISCOVERY EVENTS",
        discovery_events,
    )

    summarize_group(
        "DISCOVERY SIGNATURE",
        discovery_events,
    )

    print_event_list(
        "VALIDATION EVENTS",
        validation_events,
    )

    summarize_group(
        "VALIDATION SIGNATURE",
        validation_events,
    )

    compare_positive_negative(
        validation_events,
    )

    print()
    print("=" * 72)
    print("OOS CONCLUSION")
    print("=" * 72)

    positive = [
        event for event in validation_events
        if event["net_sum"] > 0
    ]

    negative = [
        event for event in validation_events
        if event["net_sum"] <= 0
    ]

    if positive and negative:
        print(
            "Validation contains both positive and negative Events."
        )
        print(
            "Feature separation is reported descriptively only."
        )
    else:
        print(
            "Validation does not contain enough opposing Event outcomes "
            "for a meaningful separation test."
        )

    print()
    print("No thresholds were fitted from the validation period.")
    print("No Core strategy was modified.")
    print("No live trading rule was created.")
    print("This result does not establish future profitability.")


if __name__ == "__main__":
    main()
