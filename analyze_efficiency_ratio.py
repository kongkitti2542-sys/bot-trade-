from statistics import median
from research_data_cache import load_candles


LOOKBACK = 12


def efficiency_ratio(closes, n=LOOKBACK):
    if len(closes) < n + 1:
        return None

    net_move = abs(closes[-1] - closes[-1 - n])

    path = 0.0
    for i in range(len(closes) - n, len(closes)):
        path += abs(closes[i] - closes[i - 1])

    if path <= 0:
        return 0.0

    return net_move / path


def percentile(values, p):
    if not values:
        return None

    values = sorted(values)
    index = (len(values) - 1) * p
    lower = int(index)
    upper = min(lower + 1, len(values) - 1)

    if lower == upper:
        return values[lower]

    weight = index - lower
    return (
        values[lower] * (1 - weight)
        + values[upper] * weight
    )


def main():
    candles = load_candles()

    closes = []
    values = []

    for candle in candles:
        closes.append(float(candle["close"]))

        er = efficiency_ratio(closes)

        if er is not None:
            values.append(er)

    print("=" * 70)
    print("EFFICIENCY RATIO RESEARCH")
    print("=" * 70)
    print(f"Candles:       {len(candles)}")
    print(f"ER observations: {len(values)}")
    print(f"Lookback:      {LOOKBACK} bars")
    print()

    if not values:
        print("NO_DATA")
        return

    values_sorted = sorted(values)

    print("DISTRIBUTION")
    print("-" * 70)

    for label, p in (
        ("P01", 0.01),
        ("P05", 0.05),
        ("P10", 0.10),
        ("P25", 0.25),
        ("P50", 0.50),
        ("P75", 0.75),
        ("P90", 0.90),
        ("P95", 0.95),
        ("P99", 0.99),
    ):
        print(
            f"{label}: "
            f"{percentile(values_sorted, p):.6f}"
        )

    print()
    print(
        f"MIN:    {values_sorted[0]:.6f}"
    )
    print(
        f"MEDIAN: {median(values_sorted):.6f}"
    )
    print(
        f"MAX:    {values_sorted[-1]:.6f}"
    )

    print()
    print("CANDIDATE THRESHOLDS")
    print("-" * 70)

    for threshold in (
        0.10,
        0.20,
        0.25,
        0.30,
        0.35,
        0.40,
        0.50,
        0.60,
        0.70,
    ):
        count = sum(
            1 for value in values
            if value >= threshold
        )

        pct = count / len(values) * 100

        print(
            f"ER >= {threshold:.2f}: "
            f"{count:6d} "
            f"({pct:6.2f}%)"
        )

    print()
    print("=" * 70)
    print("RESEARCH ONLY")
    print("No trading rules modified.")
    print("=" * 70)


if __name__ == "__main__":
    main()
