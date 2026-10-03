from statistics import mean, median
from research_data_cache import load_candles

LOOKBACK = 12
HORIZON = 20

FEE_PER_SIDE = 0.0005
SLIPPAGE_PER_SIDE = 0.0002
ROUND_TRIP_COST = 2 * (FEE_PER_SIDE + SLIPPAGE_PER_SIDE)

THRESHOLDS = (
    0.10,
    0.20,
    0.25,
    0.30,
    0.35,
    0.40,
    0.50,
    0.60,
    0.70,
)


def efficiency_ratio(closes, index, n=LOOKBACK):
    if index < n:
        return None

    net_move = abs(closes[index] - closes[index - n])

    path = 0.0
    for i in range(index - n + 1, index + 1):
        path += abs(closes[i] - closes[i - 1])

    if path <= 0:
        return 0.0

    return net_move / path


def forward_return(candles, index, horizon=HORIZON):
    entry_index = index + 1
    exit_index = index + 1 + horizon

    if exit_index >= len(candles):
        return None

    entry = candles[entry_index]["open"]
    exit_price = candles[exit_index]["close"]

    if entry <= 0:
        return None

    return (exit_price - entry) / entry


def summarize(label, values):
    if not values:
        print(f"{label:<24} N=0")
        return

    net_values = [x - ROUND_TRIP_COST for x in values]

    wins = sum(1 for x in net_values if x > 0)
    losses = sum(1 for x in net_values if x < 0)

    gross = sum(values)
    net = sum(net_values)

    gross_profit = sum(x for x in values if x > 0)
    gross_loss = -sum(x for x in values if x < 0)

    pf = (
        gross_profit / gross_loss
        if gross_loss > 0
        else float("inf")
    )

    print(
        f"{label:<24} "
        f"N={len(values):4d} "
        f"W={wins:4d} "
        f"L={losses:4d} "
        f"WR={wins / len(values) * 100:6.2f}% "
        f"Gross={gross * 100:+9.4f}% "
        f"Net={net * 100:+9.4f}% "
        f"AvgNet={mean(net_values) * 100:+8.4f}% "
        f"PF={pf:.3f}"
    )


def build_observations(candles):
    closes = [float(c["close"]) for c in candles]

    observations = []

    for i in range(len(candles)):
        er = efficiency_ratio(closes, i)

        if er is None:
            continue

        ret = forward_return(candles, i)

        if ret is None:
            continue

        observations.append(
            {
                "index": i,
                "er": er,
                "return": ret,
            }
        )

    return observations


def main():
    candles = load_candles()

    observations = build_observations(candles)

    print("=" * 120)
    print("EFFICIENCY RATIO × FORWARD NET EDGE")
    print("RESEARCH ONLY — NO CORE FILES MODIFIED")
    print("=" * 120)
    print(f"Candles:             {len(candles)}")
    print(f"Observations:        {len(observations)}")
    print(f"ER lookback:         {LOOKBACK} bars")
    print(f"Forward horizon:     {HORIZON} bars")
    print(
        f"Round-trip cost:     "
        f"{ROUND_TRIP_COST * 100:.2f}%"
    )
    print()

    if not observations:
        print("NO_DATA")
        return

    print("=" * 120)
    print("ALL OBSERVATIONS — ER THRESHOLDS")
    print("=" * 120)

    for threshold in THRESHOLDS:
        group = [
            x["return"]
            for x in observations
            if x["er"] >= threshold
        ]

        summarize(f"ER >= {threshold:.2f}", group)

    print()

    print("=" * 120)
    print("ER QUANTILES")
    print("=" * 120)

    ordered = sorted(observations, key=lambda x: x["er"])
    n = len(ordered)

    for q in range(5):
        start = (n * q) // 5
        end = (n * (q + 1)) // 5

        group = ordered[start:end]

        if not group:
            continue

        values = [x["return"] for x in group]

        er_values = [x["er"] for x in group]

        summarize(
            f"Q{q + 1} "
            f"ER {min(er_values):.3f}-{max(er_values):.3f}",
            values,
        )

    print()

    print("=" * 120)
    print("CHRONOLOGICAL HALF SPLIT")
    print("=" * 120)

    midpoint = len(observations) // 2

    first = observations[:midpoint]
    second = observations[midpoint:]

    for label, group in (
        ("FIRST HALF", first),
        ("SECOND HALF", second),
    ):
        values = [x["return"] for x in group]
        summarize(label, values)

    print()

    print("=" * 120)
    print("ER >= 0.50 — CHRONOLOGICAL SPLIT")
    print("=" * 120)

    for label, group in (
        ("FIRST HALF", first),
        ("SECOND HALF", second),
    ):
        values = [
            x["return"]
            for x in group
            if x["er"] >= 0.50
        ]

        summarize(label, values)

    print()

    print("=" * 120)
    print("ER >= 0.60 — CHRONOLOGICAL SPLIT")
    print("=" * 120)

    for label, group in (
        ("FIRST HALF", first),
        ("SECOND HALF", second),
    ):
        values = [
            x["return"]
            for x in group
            if x["er"] >= 0.60
        ]

        summarize(label, values)

    print()

    print("=" * 120)
    print("DIRECTIONAL VIEW")
    print("=" * 120)

    for threshold in (0.30, 0.40, 0.50, 0.60):
        selected = [
            x
            for x in observations
            if x["er"] >= threshold
        ]

        long_values = [
            x["return"]
            for x in selected
            if x["return"] > 0
        ]

        short_values = [
            -x["return"]
            for x in selected
            if x["return"] < 0
        ]

        print()
        print(f"ER >= {threshold:.2f}")
        summarize("LONG candidates", long_values)
        summarize("SHORT candidates", short_values)

    print()

    print("=" * 120)
    print("INTERPRETATION RULE")
    print("=" * 120)
    print("This test measures descriptive ER/forward-return association.")
    print("No threshold is selected automatically.")
    print("No Core strategy/risk/execution file was modified.")
    print("No parameter optimization was performed.")
    print("=" * 120)


if __name__ == "__main__":
    main()
