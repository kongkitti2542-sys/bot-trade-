from bisect import bisect_right, insort
from collections import deque
from statistics import mean

from market_intelligence_formula_v1 import build_feature_rows
from research_data_cache import load_candles


HORIZON = 20
WINDOW = 2016

FEE_PER_SIDE = 0.0005
SLIPPAGE_PER_SIDE = 0.0002
ROUND_TRIP_COST = 2 * (FEE_PER_SIDE + SLIPPAGE_PER_SIDE)

COMPONENTS = (
    "trend_rank",
    "momentum_rank",
    "volatility_rank",
    "volume_rank",
    "structure_rank",
    "market_quality",
)


def percentile_rank(sorted_values, current):
    if not sorted_values:
        return 50.0

    return (
        bisect_right(sorted_values, current)
        / len(sorted_values)
        * 100.0
    )


class RollingRank:
    def __init__(self, maxlen):
        self.maxlen = maxlen
        self.values = deque()
        self.sorted_values = []

    def add(self, value):
        self.values.append(value)
        insort(self.sorted_values, value)

        if len(self.values) > self.maxlen:
            old = self.values.popleft()
            pos = bisect_right(self.sorted_values, old) - 1
            self.sorted_values.pop(pos)

    def rank(self, current):
        return percentile_rank(
            self.sorted_values,
            current,
        )


def forward_return(candles, candle_index):
    entry_index = candle_index + 1
    exit_index = candle_index + 1 + HORIZON

    if exit_index >= len(candles):
        return None

    entry = float(candles[entry_index]["open"])
    exit_price = float(candles[exit_index]["close"])

    if entry <= 0:
        return None

    return (exit_price - entry) / entry


def summarize(label, values):
    if not values:
        print(f"{label:<34} N=0")
        return

    net = [x - ROUND_TRIP_COST for x in values]

    wins = sum(x > 0 for x in net)
    losses = sum(x < 0 for x in net)

    gross_profit = sum(x for x in values if x > 0)
    gross_loss = -sum(x for x in values if x < 0)

    pf = (
        gross_profit / gross_loss
        if gross_loss > 0
        else float("inf")
    )

    print(
        f"{label:<34} "
        f"N={len(net):5d} "
        f"WR={wins / len(net) * 100:6.2f}% "
        f"Gross={sum(values) * 100:+10.4f}% "
        f"Net={sum(net) * 100:+10.4f}% "
        f"AvgNet={mean(net) * 100:+.4f}% "
        f"PF={pf:.3f}"
    )


def directional_values(group, side):
    if side == "LONG":
        return [x["forward"] for x in group]

    return [-x["forward"] for x in group]


def analyze_component(name, observations):
    ordered = sorted(
        observations,
        key=lambda x: x["metrics"][name],
    )

    n = len(ordered)

    print()
    print("=" * 110)
    print(name.upper())
    print("=" * 110)

    for q in range(5):
        start = (n * q) // 5
        end = (n * (q + 1)) // 5

        group = ordered[start:end]

        if not group:
            continue

        component_values = [
            x["metrics"][name]
            for x in group
        ]

        print(
            f"\nQ{q + 1} "
            f"Range={min(component_values):.2f}-"
            f"{max(component_values):.2f}"
        )

        summarize(
            "LONG",
            directional_values(group, "LONG"),
        )

        summarize(
            "SHORT",
            directional_values(group, "SHORT"),
        )

    midpoint = len(observations) // 2

    first = observations[:midpoint]
    second = observations[midpoint:]

    print()
    print("CHRONOLOGICAL SPLIT")

    for label, group, side in (
        ("FIRST HALF LONG", first, "LONG"),
        ("FIRST HALF SHORT", first, "SHORT"),
        ("SECOND HALF LONG", second, "LONG"),
        ("SECOND HALF SHORT", second, "SHORT"),
    ):
        summarize(
            label,
            directional_values(group, side),
        )


def build_fast_metrics(rows):
    trend_window = RollingRank(WINDOW)
    momentum_window = RollingRank(WINDOW)
    volatility_window = RollingRank(WINDOW)
    volume_window = RollingRank(WINDOW)
    structure_window = RollingRank(WINDOW)

    metrics_by_time = {}

    for row in rows:
        price = row["price"]
        ema200 = row["ema200"]
        ema20 = row["ema20"]
        ema50 = row["ema50"]
        atr = row["atr"]
        atr_pct = row["atr_pct"]
        rv = row["rv"]
        bb_width = row["bb_width"]

        trend_raw = abs(price - ema200) / atr
        momentum_raw = abs(ema20 - ema50) / atr

        trend_window.add(trend_raw)
        momentum_window.add(momentum_raw)
        volatility_window.add(atr_pct)
        volume_window.add(rv)

        # calculate_metrics() ranks current BB width against
        # the rolling BB-width distribution. The common
        # division by the rolling median does not change rank.
        structure_window.add(bb_width)

        trend_rank = trend_window.rank(trend_raw)
        momentum_rank = momentum_window.rank(momentum_raw)
        volatility_rank = volatility_window.rank(atr_pct)
        volume_rank = volume_window.rank(rv)
        structure_rank = structure_window.rank(bb_width)

        market_quality = (
            trend_rank * 0.30
            + momentum_rank * 0.20
            + volatility_rank * 0.25
            + volume_rank * 0.15
            + structure_rank * 0.10
        )

        metrics_by_time[row["time"]] = {
            "trend_rank": trend_rank,
            "momentum_rank": momentum_rank,
            "volatility_rank": volatility_rank,
            "volume_rank": volume_rank,
            "structure_rank": structure_rank,
            "market_quality": market_quality,
            "trend_raw": trend_raw,
            "momentum_raw": momentum_raw,
            "atr_pct": atr_pct,
            "rv": rv,
        }

    return metrics_by_time


def main():
    candles = load_candles()

    rows = build_feature_rows(candles)

    print("=" * 110)
    print("MARKET INTELLIGENCE FORWARD EDGE RESEARCH")
    print("FAST ROLLING VERSION")
    print("RESEARCH ONLY — NO CORE FILES MODIFIED")
    print("=" * 110)
    print(f"Candles:             {len(candles)}")
    print(f"Feature rows:        {len(rows)}")
    print(f"Rolling window:      {WINDOW}")
    print(f"Forward horizon:     {HORIZON} bars")
    print(
        f"Round-trip cost:     "
        f"{ROUND_TRIP_COST * 100:.2f}%"
    )

    if not rows:
        print("NO_FEATURE_ROWS")
        return

    print()
    print("Building rolling MI metrics...")

    metrics_by_time = build_fast_metrics(rows)

    print(
        f"MI metrics built:    "
        f"{len(metrics_by_time)}"
    )

    observations = []

    row_index_by_time = {
        row["time"]: index
        for index, row in enumerate(rows)
    }

    for candle_index, candle in enumerate(candles):
        candle_time = candle["time"]

        metrics = metrics_by_time.get(candle_time)

        if metrics is None:
            continue

        forward = forward_return(
            candles,
            candle_index,
        )

        if forward is None:
            continue

        observations.append(
            {
                "time": candle_time,
                "metrics": metrics,
                "forward": forward,
            }
        )

    print(
        f"Forward observations: "
        f"{len(observations)}"
    )

    if not observations:
        print("NO_DATA")
        return

    for component in COMPONENTS:
        analyze_component(
            component,
            observations,
        )

    print()
    print("=" * 110)
    print("OVERALL FORWARD RETURN")
    print("=" * 110)

    summarize(
        "ALL LONG",
        directional_values(
            observations,
            "LONG",
        ),
    )

    summarize(
        "ALL SHORT",
        directional_values(
            observations,
            "SHORT",
        ),
    )

    print()
    print("=" * 110)
    print("IMPORTANT")
    print("=" * 110)
    print("This is descriptive research.")
    print("No component threshold is selected automatically.")
    print("No parameter optimization was performed.")
    print("No Strategy/Risk/Engine/Core file was modified.")
    print("=" * 110)


if __name__ == "__main__":
    main()
