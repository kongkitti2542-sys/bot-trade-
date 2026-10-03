import random

from compare_vol_volume_periods import (
    DISCOVERY_START,
    DISCOVERY_END,
    VALIDATION_START,
    VALIDATION_END,
    load_candles,
    run_period,
)

N_PERMUTATIONS = 10000
SEED = 20261001

STATES = (
    "LOW×LOW",
    "LOW×MID",
    "LOW×HIGH",
    "MID×LOW",
    "MID×MID",
    "MID×HIGH",
    "HIGH×LOW",
    "HIGH×MID",
    "HIGH×HIGH",
)


def observed_cells(trades):
    result = {}

    for state in STATES:
        vol, volume = state.split("×")

        group = [
            t for t in trades
            if t["vol_state"] == vol
            and t["volume_state"] == volume
        ]

        net = sum(t["net"] for t in group)

        result[state] = {
            "n": len(group),
            "net": net,
            "net_per_trade": net / len(group) if group else 0.0,
        }

    return result


def permutation_test(trades, rng):
    net_values = [t["net"] for t in trades]

    labels = []

    for state in STATES:
        vol, volume = state.split("×")

        count = sum(
            1
            for t in trades
            if t["vol_state"] == vol
            and t["volume_state"] == volume
        )

        labels.extend([state] * count)

    if len(labels) != len(net_values):
        raise RuntimeError(
            "Label count does not match trade count."
        )

    rng.shuffle(labels)

    cell_sums = {state: 0.0 for state in STATES}
    cell_counts = {state: 0 for state in STATES}

    for net, label in zip(net_values, labels):
        cell_sums[label] += net
        cell_counts[label] += 1

    cell_net_per_trade = {
        state: (
            cell_sums[state] / cell_counts[state]
            if cell_counts[state] > 0
            else 0.0
        )
        for state in STATES
    }

    return cell_net_per_trade


def run_test(name, trades):
    observed = observed_cells(trades)

    target = "HIGH×MID"

    observed_target = observed[target]["net_per_trade"]

    better_target = 0
    better_any = 0

    target_distribution = []
    max_distribution = []

    rng = random.Random(SEED)

    for _ in range(N_PERMUTATIONS):
        result = permutation_test(trades, rng)

        target_random = result[target]
        max_random = max(result.values())

        target_distribution.append(target_random)
        max_distribution.append(max_random)

        if target_random >= observed_target:
            better_target += 1

        if max_random >= observed_target:
            better_any += 1

    p_target = (
        (better_target + 1)
        / (N_PERMUTATIONS + 1)
    )

    p_max = (
        (better_any + 1)
        / (N_PERMUTATIONS + 1)
    )

    print()
    print("=" * 100)
    print(name)
    print("=" * 100)

    print(
        f"Trades:                 {len(trades)}"
    )
    print(
        f"Permutations:            {N_PERMUTATIONS}"
    )
    print(
        f"Observed HIGH×MID N:     {observed[target]['n']}"
    )
    print(
        f"Observed HIGH×MID Net:   "
        f"{observed_target:+.6f} / trade"
    )
    print()

    print(
        f"Unadjusted p-value:      {p_target:.6f}"
    )
    print(
        f"Max-cell adjusted p:     {p_max:.6f}"
    )

    print()
    print("Observed 9-cell Net / Trade")
    print("-" * 60)

    for state in STATES:
        print(
            f"{state:<12}"
            f"N={observed[state]['n']:>4} "
            f"Net/Trade={observed[state]['net_per_trade']:+.6f}"
        )

    print()
    print(
        "Interpretation:"
    )
    print(
        "Unadjusted p tests HIGH×MID against its own "
        "random-label distribution."
    )
    print(
        "Max-cell adjusted p accounts for the fact that "
        "we inspected all 9 cells before focusing on HIGH×MID."
    )


def main():
    candles = load_candles()

    discovery, discovery_rej = run_period(
        candles,
        DISCOVERY_START,
        DISCOVERY_END,
    )

    validation, validation_rej = run_period(
        candles,
        VALIDATION_START,
        VALIDATION_END,
    )

    print("=" * 100)
    print("FULL-GRID PERMUTATION TEST")
    print("=" * 100)
    print("Research only.")
    print("No Core files modified.")
    print()
    print(
        f"Discovery risk rejections:  {discovery_rej}"
    )
    print(
        f"Validation risk rejections: {validation_rej}"
    )

    run_test("DISCOVERY", discovery)
    run_test("VALIDATION", validation)

    print()
    print("=" * 100)
    print("END OF PERMUTATION TEST")
    print("=" * 100)


if __name__ == "__main__":
    main()
