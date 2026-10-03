from collections import Counter, defaultdict
from datetime import datetime

from backtest_data_100k import get_historical_candles_100k, validate_candles
from backtest_oos_time_exit import (
    OOS_BOUNDARY,
    TEST_HOLDS,
    run_oos_backtest,
)


def realized_trades(trades):
    return sorted(
        [
            t for t in trades
            if t["exit_reason"] != "BACKTEST_END"
        ],
        key=lambda t: t["entry_time"],
    )


def classify_pnl(pnl):
    if pnl > 0:
        return "WIN"
    if pnl < 0:
        return "LOSS"
    return "FLAT"


def analyze_reentry(trades):
    trades = realized_trades(trades)

    if len(trades) < 2:
        print("Not enough trades.")
        return

    print(f"Realized trades: {len(trades)}")
    print()

    gaps = []
    transition_counts = Counter()
    exit_to_next_counts = Counter()

    gap_by_previous_exit = defaultdict(list)
    next_pnl_by_previous_exit = defaultdict(list)

    previous_trade = None

    for trade in trades:
        if previous_trade is not None:
            gap_hours = (
                trade["entry_time"]
                - previous_trade["exit_time"]
            ).total_seconds() / 3600

            gaps.append(gap_hours)

            transition = (
                f"{previous_trade['side']}"
                f"->{trade['side']}"
            )

            transition_counts[transition] += 1

            exit_reason = previous_trade["exit_reason"]

            exit_to_next_counts[
                exit_reason
            ] += 1

            gap_by_previous_exit[
                exit_reason
            ].append(gap_hours)

            next_pnl_by_previous_exit[
                exit_reason
            ].append(trade["pnl"])

        previous_trade = trade

    print("RE-ENTRY GAP AFTER EXIT")
    print("-" * 80)

    for threshold in (1, 2, 4, 6, 12, 24):
        count = sum(
            1
            for gap in gaps
            if gap <= threshold
        )

        pct = (
            count / len(gaps) * 100
            if gaps else 0.0
        )

        print(
            f"<= {threshold:>2}h:"
            f" {count:>4}"
            f" ({pct:>6.2f}%)"
        )

    print()

    print("RE-ENTRY BY PREVIOUS EXIT")
    print("-" * 80)

    for exit_reason in (
        "STOP_LOSS",
        "TIME_EXIT",
    ):
        reason_gaps = gap_by_previous_exit.get(
            exit_reason,
            [],
        )

        next_pnls = next_pnl_by_previous_exit.get(
            exit_reason,
            [],
        )

        if not reason_gaps:
            print(
                f"{exit_reason:<12}"
                f" count=0"
            )
            continue

        avg_gap = (
            sum(reason_gaps) / len(reason_gaps)
        )

        avg_next_pnl = (
            sum(next_pnls) / len(next_pnls)
            if next_pnls
            else 0.0
        )

        print(
            f"{exit_reason:<12}"
            f" count={len(reason_gaps):<5}"
            f" avg_gap={avg_gap:>7.3f}h"
            f" next_trade_avg_pnl=${avg_next_pnl:>8.4f}"
        )

    print()

    print("SIDE TRANSITIONS")
    print("-" * 80)

    total_transitions = sum(
        transition_counts.values()
    )

    for transition in (
        "BUY->BUY",
        "BUY->SELL",
        "SELL->BUY",
        "SELL->SELL",
    ):
        count = transition_counts[transition]

        pct = (
            count / total_transitions * 100
            if total_transitions
            else 0.0
        )

        print(
            f"{transition:<10}"
            f" count={count:<5}"
            f" ({pct:>6.2f}%)"
        )

    print()

    print("PREVIOUS TRADE OUTCOME -> NEXT TRADE")
    print("-" * 80)

    outcome_matrix = Counter()

    for previous, current in zip(
        trades,
        trades[1:],
    ):
        previous_outcome = classify_pnl(
            previous["pnl"]
        )

        current_outcome = classify_pnl(
            current["pnl"]
        )

        outcome_matrix[
            (previous_outcome, current_outcome)
        ] += 1

    for previous_outcome in (
        "WIN",
        "LOSS",
        "FLAT",
    ):
        for current_outcome in (
            "WIN",
            "LOSS",
            "FLAT",
        ):
            count = outcome_matrix[
                (previous_outcome, current_outcome)
            ]

            if count:
                print(
                    f"{previous_outcome:<5}"
                    f" -> "
                    f"{current_outcome:<5}"
                    f": {count}"
                )


def main():
    print("=" * 100)
    print("OOS RE-ENTRY / SIGNAL CHURN ANALYSIS")
    print("=" * 100)

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

    boundary = datetime.fromisoformat(
        OOS_BOUNDARY
    )

    print(f"First:         {candles[0]['time']}")
    print(f"Last:          {candles[-1]['time']}")
    print(f"OOS Boundary:  {boundary}")

    for label, bars in TEST_HOLDS.items():
        capital, trades, risk_rejections = run_oos_backtest(
            candles,
            max_hold_bars=bars,
            boundary=boundary,
        )

        print()
        print("=" * 100)
        print(f"TIME EXIT {label} ({bars} bars)")
        print("=" * 100)
        print(f"Ending capital:  ${capital:.2f}")
        print(f"Risk rejections: {risk_rejections}")
        print()

        analyze_reentry(trades)

    print()
    print("=" * 100)
    print("Research only. No Core files were modified.")
    print("=" * 100)


if __name__ == "__main__":
    main()
