from statistics import mean, median

from block3_event_signature_oos_v1 import (
    build_events,
    build_windows,
    event_summary,
    split_dataset,
)
from block3_analyzer_v1 import build_trade_records
from validate_atr_expansion_ema50 import fetch_closed_candles


FEATURE_KEYS = (
    "expansion_ratio",
    "ema50_distance",
)


def discovery_reference(discovery_events):
    positive = [
        event
        for event in discovery_events
        if event["net_sum"] > 0
    ]

    if not positive:
        return None

    return {
        "expansion_ratio": median(
            event["expansion_ratio"]["mean"]
            for event in positive
        ),
        "ema50_distance": median(
            event["ema50_distance"]["mean"]
            for event in positive
        ),
    }


def classify_event(event, reference):
    expansion_ok = (
        event["expansion_ratio"]["mean"]
        >= reference["expansion_ratio"]
    )

    ema50_ok = (
        event["ema50_distance"]["mean"]
        >= reference["ema50_distance"]
    )

    if expansion_ok and ema50_ok:
        quality = "HIGH"
    elif expansion_ok or ema50_ok:
        quality = "MEDIUM"
    else:
        quality = "LOW"

    return {
        "quality": quality,
        "expansion_ok": expansion_ok,
        "ema50_ok": ema50_ok,
    }


def summarize_quality(events, classifications, quality):
    selected = [
        event
        for event, classification in zip(events, classifications)
        if classification["quality"] == quality
    ]

    if not selected:
        return {
            "events": 0,
            "positive": 0,
            "negative": 0,
            "net_sum": 0.0,
            "avg_net": 0.0,
        }

    nets = [
        event["net_sum"]
        for event in selected
    ]

    return {
        "events": len(selected),
        "positive": sum(1 for value in nets if value > 0),
        "negative": sum(1 for value in nets if value <= 0),
        "net_sum": sum(nets),
        "avg_net": mean(nets),
    }


def print_quality_table(events, classifications, label):
    print()
    print("=" * 72)
    print(label)
    print("=" * 72)

    for index, (event, classification) in enumerate(
        zip(events, classifications),
        start=1,
    ):
        print(
            f"Event {index:<2} "
            f"Quality={classification['quality']:<6} "
            f"Signals={event['signals']:<2} "
            f"Net={event['net_sum']:+.4%} "
            f"ATR={event['expansion_ratio']['mean']:.4f} "
            f"EMA50={event['ema50_distance']['mean']:+.4%}"
        )


def print_summary(events, classifications):
    print()
    print("=" * 72)
    print("QUALITY SUMMARY")
    print("=" * 72)

    for quality in ("HIGH", "MEDIUM", "LOW"):
        summary = summarize_quality(
            events,
            classifications,
            quality,
        )

        print(
            f"{quality:<8} "
            f"Events={summary['events']:<3} "
            f"Positive={summary['positive']:<3} "
            f"Negative={summary['negative']:<3} "
            f"NetSum={summary['net_sum']:+.4%} "
            f"AvgEvent={summary['avg_net']:+.4%}"
        )


def find_event_number(events, target_start):
    for index, event in enumerate(events, start=1):
        if event["start"] == target_start:
            return index

    return None


def main():
    print("=" * 72)
    print("EVENT QUALITY RESEARCH V1")
    print("=" * 72)
    print("Purpose: discovery-trained Event quality classifier")
    print("Mode   : RESEARCH ONLY")
    print()

    candles = fetch_closed_candles()
    records = build_trade_records(candles)

    discovery_records, validation_records = split_dataset(records)

    discovery_events = [
        event_summary(event)
        for event in build_events(
            build_windows(discovery_records)
        )
    ]

    validation_events = [
        event_summary(event)
        for event in build_events(
            build_windows(validation_records)
        )
    ]

    reference = discovery_reference(discovery_events)

    if reference is None:
        print("No positive Discovery Events.")
        return

    print(f"Trade Records       : {len(records)}")
    print(f"Discovery Events    : {len(discovery_events)}")
    print(f"Validation Events   : {len(validation_events)}")
    print()

    print("=" * 72)
    print("DISCOVERY REFERENCE")
    print("=" * 72)

    print(
        f"ATR Expansion Reference : "
        f"{reference['expansion_ratio']:.4f}"
    )

    print(
        f"EMA50 Distance Reference: "
        f"{reference['ema50_distance']:+.4%}"
    )

    discovery_classifications = [
        classify_event(event, reference)
        for event in discovery_events
    ]

    validation_classifications = [
        classify_event(event, reference)
        for event in validation_events
    ]

    print_quality_table(
        discovery_events,
        discovery_classifications,
        "DISCOVERY CLASSIFICATION",
    )

    print_quality_table(
        validation_events,
        validation_classifications,
        "OOS VALIDATION CLASSIFICATION",
    )

    print_summary(
        validation_events,
        validation_classifications,
    )

    print()
    print("=" * 72)
    print("OOS EVENT 21 CHECK")
    print("=" * 72)

    if len(validation_events) >= 21:
        event = validation_events[20]
        classification = validation_classifications[20]

        print(
            f"Event 21: "
            f"Quality={classification['quality']} "
            f"Signals={event['signals']} "
            f"Net={event['net_sum']:+.4%}"
        )

        print(
            f"ATR Expansion : "
            f"{event['expansion_ratio']['mean']:.4f}"
        )

        print(
            f"EMA50 Distance: "
            f"{event['ema50_distance']['mean']:+.4%}"
        )

    print()
    print("=" * 72)
    print("NOTE")
    print("=" * 72)
    print(
        "References are derived from Discovery positive Events only."
    )
    print(
        "Validation results do not modify the references."
    )
    print(
        "This classifier is research-only and is not connected "
        "to Quant, AI, Risk, or live execution."
    )
    print(
        "No future profitability is implied."
    )


if __name__ == "__main__":
    main()
