from compounding_session_v1 import (
    load_candles,
    aggregate_4h,
    build_feature_rows,
    run_session,
    STARTING_CAPITAL_USDT,
    REFERENCE_USDTHB,
    SESSION_BARS,
)

TARGETS = [0.05, 0.10, 0.15]


def main():
    print("=" * 72)
    print("24H SESSION TARGET RESEARCH V1")
    print("=" * 72)

    source_candles = load_candles()
    candles = aggregate_4h(source_candles)

    print(f"Source 5m candles : {len(source_candles):,}")
    print(f"Complete 4H bars  : {len(candles):,}")

    if not candles:
        raise RuntimeError("NO_COMPLETE_4H_CANDLES")

    feature_rows = build_feature_rows(candles)

    total_sessions = len(feature_rows) // SESSION_BARS

    print(f"Complete sessions : {total_sessions:,}")
    print(f"Starting capital  : {STARTING_CAPITAL_USDT:.8f} USDT")
    print()

    capital = STARTING_CAPITAL_USDT

    session_results = []

    for session_number in range(total_sessions):
        start = session_number * SESSION_BARS
        end = start + SESSION_BARS

        session_rows = feature_rows[start:end]

        session_start_capital = capital

        session_capital, trades = run_session(
            session_rows,
            session_start_capital,
        )

        net = session_capital - session_start_capital

        return_pct = (
            net / session_start_capital * 100
            if session_start_capital > 0
            else 0.0
        )

        # Capital path inside the session.
        # run_session returns only the final value, so this section
        # uses completed trade P/L to reconstruct the realized capital path.
        running_capital = session_start_capital
        max_intraday_capital = running_capital

        for trade in trades:
            running_capital += trade["net_pnl"]

            if running_capital > max_intraday_capital:
                max_intraday_capital = running_capital

        peak_return_pct = (
            (max_intraday_capital / session_start_capital - 1) * 100
            if session_start_capital > 0
            else 0.0
        )

        session_results.append(
            {
                "session": session_number + 1,
                "start": session_rows[0]["candle"]["time"],
                "end": session_rows[-1]["candle"]["time"],
                "start_capital": session_start_capital,
                "end_capital": session_capital,
                "net": net,
                "return_pct": return_pct,
                "peak_return_pct": peak_return_pct,
                "trades": len(trades),
            }
        )

        capital = session_capital

    print("-" * 72)
    print("SESSION TARGET RESULTS")
    print("-" * 72)

    for target in TARGETS:
        target_pct = target * 100

        reached = [
            x
            for x in session_results
            if x["peak_return_pct"] >= target_pct
        ]

        finished = [
            x
            for x in session_results
            if x["return_pct"] >= target_pct
        ]

        print(
            f"Target +{target_pct:.0f}% | "
            f"Reached intraday: {len(reached):3d}/{total_sessions} "
            f"({len(reached) / total_sessions * 100:.2f}%) | "
            f"Finished >= target: {len(finished):3d}/{total_sessions} "
            f"({len(finished) / total_sessions * 100:.2f}%)"
        )

    print()
    print("-" * 72)
    print("SESSION DISTRIBUTION")
    print("-" * 72)

    buckets = [
        ("< 0%", lambda r: r["return_pct"] < 0),
        ("0% to <5%", lambda r: 0 <= r["return_pct"] < 5),
        ("5% to <10%", lambda r: 5 <= r["return_pct"] < 10),
        ("10% to <15%", lambda r: 10 <= r["return_pct"] < 15),
        (">= 15%", lambda r: r["return_pct"] >= 15),
    ]

    for label, condition in buckets:
        count = sum(1 for x in session_results if condition(x))

        print(
            f"{label:12s}: "
            f"{count:3d}/{total_sessions} "
            f"({count / total_sessions * 100:.2f}%)"
        )

    print()
    print("-" * 72)
    print("OVERALL COMPOUNDING RESULT")
    print("-" * 72)

    print(f"Final Capital     : {capital:.8f} USDT")
    print(f"Final Capital THB : {capital * REFERENCE_USDTHB:.2f} THB")

    total_return = (
        (capital / STARTING_CAPITAL_USDT - 1) * 100
    )

    print(f"Total Return      : {total_return:+.2f}%")

    best_session = max(
        session_results,
        key=lambda x: x["return_pct"],
    )

    worst_session = min(
        session_results,
        key=lambda x: x["return_pct"],
    )

    print()
    print("Best Session:")
    print(
        f"  #{best_session['session']:03d} | "
        f"{best_session['start']} -> {best_session['end']} | "
        f"Trades {best_session['trades']} | "
        f"Return {best_session['return_pct']:+.2f}% | "
        f"Peak {best_session['peak_return_pct']:+.2f}%"
    )

    print("Worst Session:")
    print(
        f"  #{worst_session['session']:03d} | "
        f"{worst_session['start']} -> {worst_session['end']} | "
        f"Trades {worst_session['trades']} | "
        f"Return {worst_session['return_pct']:+.2f}% | "
        f"Peak {worst_session['peak_return_pct']:+.2f}%"
    )

    print()
    print("-" * 72)
    print("TOP 10 SESSIONS BY FINAL RETURN")
    print("-" * 72)

    for result in sorted(
        session_results,
        key=lambda x: x["return_pct"],
        reverse=True,
    )[:10]:
        print(
            f"Session {result['session']:03d} | "
            f"Return {result['return_pct']:+7.2f}% | "
            f"Peak {result['peak_return_pct']:+7.2f}% | "
            f"Trades {result['trades']:2d} | "
            f"Net {result['net']:+.6f} USDT"
        )


if __name__ == "__main__":
    main()
