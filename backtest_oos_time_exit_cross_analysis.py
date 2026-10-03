from backtest_oos_entry_cohort import (
    get_historical_candles_100k,
    validate_candles,
    IncrementalFeatures,
    detect_regime,
    analyze_market,
    evaluate_risk,
    close_position,
    unrealized_pnl_percent,
    pnl_bucket,
    run_analysis,
    CHECKPOINTS,
    OOS_BOUNDARY,
)


def pct(n, total):
    return n / total * 100.0 if total else 0.0


def print_group(title, rows, key_func):
    groups = {}

    for row in rows:
        key = key_func(row)
        groups.setdefault(key, []).append(row)

    print()
    print(title)
    print("-" * 110)

    print(
        f"{'Group':<35}"
        f"{'N':>7}"
        f"{'WIN':>8}"
        f"{'LOSS':>8}"
        f"{'Win%':>10}"
        f"{'Final P/L':>16}"
    )

    for key, subset in groups.items():
        wins = [
            x for x in subset
            if x["final_pnl"] > 0
        ]

        losses = [
            x for x in subset
            if x["final_pnl"] < 0
        ]

        total_pnl = sum(
            x["final_pnl"]
            for x in subset
        )

        print(
            f"{str(key):<35}"
            f"{len(subset):>7}"
            f"{len(wins):>8}"
            f"{len(losses):>8}"
            f"{pct(len(wins), len(subset)):>10.2f}"
            f"{total_pnl:>16.4f}"
        )


def run_cross_analysis(checkpoints, label):
    rows = [
        x for x in checkpoints
        if x["checkpoint"] == label
        and x["final_pnl"] is not None
    ]

    print()
    print("=" * 110)
    print(f"CROSS ANALYSIS — {label}")
    print("=" * 110)

    print(f"Samples: {len(rows)}")

    if not rows:
        return

    # ------------------------------------------------------------
    # Single-variable analysis
    # ------------------------------------------------------------

    print_group(
        "1. Unrealized P/L",
        rows,
        lambda x: x["pnl_bucket"],
    )

    print_group(
        "2. Current Regime",
        rows,
        lambda x: x["entry_regime"],
    )

    print_group(
        "3. Current Score",
        rows,
        lambda x: (
            "<70"
            if abs(x["entry_score"]) < 70
            else "70-84"
            if abs(x["entry_score"]) < 85
            else "85+"
        ),
    )

    print_group(
        "4. Current Signal",
        rows,
        lambda x: x["side"],
    )

    print_group(
        "5. Side",
        rows,
        lambda x: x["side"],
    )

    # ------------------------------------------------------------
    # Two-variable combinations
    # ------------------------------------------------------------

    print_group(
        "6. P/L + Current Regime",
        rows,
        lambda x: (
            f"{x['pnl_bucket']} | "
            f"{x['entry_regime']}"
        ),
    )

    print_group(
        "7. P/L + Score",
        rows,
        lambda x: (
            f"{x['pnl_bucket']} | "
            f"{'<70' if abs(x['entry_score']) < 70 else '70-84' if abs(x['entry_score']) < 85 else '85+'}"
        ),
    )

    print_group(
        "8. P/L + Signal",
        rows,
        lambda x: (
            f"{x['pnl_bucket']} | "
            f"{x['side']}"
        ),
    )

    print_group(
        "9. Regime + Score",
        rows,
        lambda x: (
            f"{x['entry_regime']} | "
            f"{'<70' if abs(x['entry_score']) < 70 else '70-84' if abs(x['entry_score']) < 85 else '85+'}"
        ),
    )

    # ------------------------------------------------------------
    # Focused candidate groups
    # Diagnostic only — NOT trading rules.
    # ------------------------------------------------------------

    print_group(
        "10. Candidate: P/L >= +1%",
        rows,
        lambda x: (
            "P/L >= +1%"
            if x["unrealized_pnl_pct"] >= 1.0
            else "P/L < +1%"
        ),
    )

    print_group(
        "11. Candidate: P/L >= +1% AND abs(score) >= 70",
        rows,
        lambda x: (
            "P/L>=1 & score>=70"
            if (
                x["unrealized_pnl_pct"] >= 1.0
                and abs(x["entry_score"]) >= 70
            )
            else "Other"
        ),
    )

    print_group(
        "12. Candidate: P/L < 0% AND abs(score) < 70",
        rows,
        lambda x: (
            "P/L<0 & score<70"
            if (
                x["unrealized_pnl_pct"] < 0
                and abs(x["entry_score"]) < 70
            )
            else "Other"
        ),
    )


def main():
    print("=" * 110)
    print("OOS TIME EXIT CROSS ANALYSIS")
    print("=" * 110)

    candles = get_historical_candles_100k(
        symbol="BTCUSDT",
        interval="5m",
        candles_needed=100_000,
    )

    valid, reason = validate_candles(candles)

    print(f"Candles:       {len(candles)}")
    print(f"Validation:    {valid}")
    print(f"Reason:        {reason}")

    if not valid:
        raise RuntimeError(
            f"Dataset validation failed: {reason}"
        )

    import datetime

    boundary = datetime.datetime.fromisoformat(
        OOS_BOUNDARY
    )

    print(f"First:         {candles[0]['time']}")
    print(f"Last:          {candles[-1]['time']}")
    print(f"OOS Boundary:  {OOS_BOUNDARY}")
    print()

    _, checkpoints = run_analysis(
        candles,
        boundary,
    )

    for label in [
        "12h",
        "16h",
        "18h",
        "20h",
    ]:
        run_cross_analysis(
            checkpoints,
            label,
        )

    print()
    print("=" * 110)
    print("DIAGNOSTIC ONLY — NO DYNAMIC EXIT RULE CREATED")
    print("NO CORE FILES MODIFIED")
    print("=" * 110)


if __name__ == "__main__":
    main()
