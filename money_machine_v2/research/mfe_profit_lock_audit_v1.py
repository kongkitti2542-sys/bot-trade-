import json
from pathlib import Path

from money_machine_v2.research.profit_lock_reconcile import (
    build_candidates,
    simulate_exit,
)
from research_groq_30day_compounding_v5_2 import (
    fetch_closed_candles_paginated,
)
from research_standard_v1 import (
    SYMBOL,
    INTERVAL,
    WINDOW_30D_CANDLES,
)

OUTPUT_FILE = Path(
    "money_machine_v2/research/mfe_profit_lock_audit_v1.json"
)

TRIGGERS = (
    0.0020,
    0.0030,
    0.0050,
    0.0075,
    0.0100,
)

LOCK = 0.0020


def pct(value):
    return value * 100.0


def main():
    candles = fetch_closed_candles_paginated(
        SYMBOL,
        INTERVAL,
        WINDOW_30D_CANDLES,
    )

    records = build_candidates(candles[:-2])

    # Reproduce actual PL_050 overlap behavior.
    selected = []
    active_exit_time = None

    for record in records:
        candidate = record["candidate"]
        entry_time = candidate["entry_time"]

        if (
            active_exit_time is not None
            and entry_time < active_exit_time
        ):
            continue

        exit_result = simulate_exit(
            candidate=candidate,
            entry_index=record["entry_index"],
            fixed_exit_index=record["fixed_exit_index"],
            candles=candles,
            trigger=0.0050,
            lock=LOCK,
        )

        if exit_result is None:
            continue

        actual_exit_time = candles[
            exit_result["exit_index"]
        ]["time"]

        selected.append(
            {
                "record": record,
                "exit_result": exit_result,
                "actual_exit_time": actual_exit_time,
            }
        )

        active_exit_time = actual_exit_time

    rows = []

    for item in selected:
        record = item["record"]
        candidate = record["candidate"]

        entry_index = record["entry_index"]
        exit_index = record["fixed_exit_index"]

        entry = candidate["entry"]

        peak_price = entry
        peak_index = entry_index

        for index in range(
            entry_index,
            exit_index + 1,
        ):
            high = candles[index]["high"]

            if high > peak_price:
                peak_price = high
                peak_index = index

        mfe = (
            peak_price - entry
        ) / entry

        fixed_exit_price = candles[
            exit_index
        ]["close"]

        fixed_return = (
            fixed_exit_price - entry
        ) / entry

        giveback = mfe - fixed_return

        trigger_hits = {}

        for trigger in TRIGGERS:
            trigger_price = entry * (
                1.0 + trigger
            )

            hit_index = None

            for index in range(
                entry_index,
                exit_index + 1,
            ):
                if candles[index]["high"] >= trigger_price:
                    hit_index = index
                    break

            trigger_hits[
                f"{pct(trigger):.2f}%"
            ] = {
                "hit": hit_index is not None,
                "index": hit_index,
                "time": (
                    candles[hit_index]["time"].isoformat()
                    if hit_index is not None
                    else None
                ),
            }

        actual_exit = item["exit_result"]

        actual_return = (
            actual_exit["exit_price"] - entry
        ) / entry

        rows.append(
            {
                "entry_time": candidate[
                    "entry_time"
                ].isoformat(),
                "entry": entry,
                "fixed_exit_time": candidate[
                    "planned_exit_time"
                ].isoformat(),
                "fixed_exit_price": fixed_exit_price,
                "fixed_return_pct": pct(
                    fixed_return
                ),
                "peak_time": candles[
                    peak_index
                ]["time"].isoformat(),
                "peak_price": peak_price,
                "mfe_pct": pct(mfe),
                "giveback_pct": pct(giveback),
                "actual_exit_time": item[
                    "actual_exit_time"
                ].isoformat(),
                "actual_exit_price": actual_exit[
                    "exit_price"
                ],
                "actual_exit_type": actual_exit[
                    "exit_type"
                ],
                "actual_return_pct": pct(
                    actual_return
                ),
                "trigger_hits": trigger_hits,
            }
        )

    summary = {}

    for trigger in TRIGGERS:
        key = f"{pct(trigger):.2f}%"

        hit_rows = [
            row
            for row in rows
            if row["trigger_hits"][key]["hit"]
        ]

        summary[key] = {
            "trigger_hit_count": len(hit_rows),
            "trigger_hit_rate_pct": (
                len(hit_rows) / len(rows) * 100.0
                if rows
                else 0.0
            ),
        }

    mfe_values = [
        row["mfe_pct"]
        for row in rows
    ]

    giveback_values = [
        row["giveback_pct"]
        for row in rows
    ]

    output = {
        "symbol": SYMBOL,
        "interval": INTERVAL,
        "candles": len(candles),
        "resolved_candidates": len(records),
        "actual_pl050_trades": len(rows),
        "summary": {
            "avg_mfe_pct": (
                sum(mfe_values) / len(mfe_values)
                if mfe_values
                else 0.0
            ),
            "max_mfe_pct": (
                max(mfe_values)
                if mfe_values
                else 0.0
            ),
            "avg_giveback_pct": (
                sum(giveback_values)
                / len(giveback_values)
                if giveback_values
                else 0.0
            ),
            "max_giveback_pct": (
                max(giveback_values)
                if giveback_values
                else 0.0
            ),
        },
        "trigger_summary": summary,
        "trades": rows,
    }

    OUTPUT_FILE.write_text(
        json.dumps(
            output,
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    print("=" * 72)
    print("MFE / PROFIT LOCK AUDIT V1")
    print("=" * 72)
    print(f"Candles              : {len(candles)}")
    print(f"Resolved candidates  : {len(records)}")
    print(f"Actual PL_050 trades : {len(rows)}")
    print()
    print(
        f"Average MFE          : "
        f"{output['summary']['avg_mfe_pct']:.6f}%"
    )
    print(
        f"Maximum MFE          : "
        f"{output['summary']['max_mfe_pct']:.6f}%"
    )
    print(
        f"Average Giveback     : "
        f"{output['summary']['avg_giveback_pct']:.6f}%"
    )
    print(
        f"Maximum Giveback     : "
        f"{output['summary']['max_giveback_pct']:.6f}%"
    )
    print()
    print("TRIGGER HITS")

    for key, result in summary.items():
        print(
            f"  {key}: "
            f"{result['trigger_hit_count']} / "
            f"{len(rows)} "
            f"({result['trigger_hit_rate_pct']:.2f}%)"
        )

    print("=" * 72)
    print("Saved:", OUTPUT_FILE)
    print("=" * 72)


if __name__ == "__main__":
    main()
