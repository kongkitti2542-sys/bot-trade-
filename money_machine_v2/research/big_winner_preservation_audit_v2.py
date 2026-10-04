import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from research_groq_30day_compounding_v5_2 import fetch_closed_candles_paginated
from research_standard_v1 import SYMBOL, INTERVAL, WINDOW_30D_CANDLES
from money_machine_v2.research.safe_money_maker_01_adapter_v1 import find_candidates


OUTPUT_FILE = Path(
    "money_machine_v2/research/big_winner_preservation_audit_v2.json"
)

BIG_WINNER_MFE = 0.01
GIVEBACK_LEVELS = [0.002, 0.003, 0.005]
HORIZON = 20


def build_records(candles):
    index = {c["time"]: i for i, c in enumerate(candles)}
    rows = []

    for candidate in find_candidates(candles):
        entry_index = index.get(candidate["entry_time"])

        if entry_index is None:
            continue

        end_index = min(
            entry_index + HORIZON,
            len(candles) - 1,
        )

        rows.append({
            "candidate": candidate,
            "entry_index": entry_index,
            "end_index": end_index,
        })

    return sorted(
        rows,
        key=lambda r: r["candidate"]["entry_time"],
    )


def analyze_trade(record, candles):
    candidate = record["candidate"]
    entry = float(candidate["entry"])

    peak = entry

    observations = []

    for i in range(
        record["entry_index"] + 1,
        record["end_index"] + 1,
    ):
        candle = candles[i]

        if candle["high"] > peak:
            peak = candle["high"]

        mfe = peak / entry - 1.0

        giveback = (
            (peak - candle["close"]) / peak
            if peak > 0
            else 0.0
        )

        observations.append({
            "index": i,
            "time": candle["time"].isoformat(),
            "close": float(candle["close"]),
            "peak": float(peak),
            "mfe_pct": mfe * 100.0,
            "giveback_pct": giveback * 100.0,
        })

    max_mfe = max(
        (x["mfe_pct"] for x in observations),
        default=0.0,
    )

    row = {
        "entry_time": candidate["entry_time"].isoformat(),
        "entry": entry,
        "max_mfe_pct": max_mfe,
        "big_winner": max_mfe >= BIG_WINNER_MFE * 100.0,
        "giveback_events": {},
    }

    if not row["big_winner"]:
        return row

    for level in GIVEBACK_LEVELS:
        level_pct = level * 100.0

        hits = [
            x for x in observations
            if x["mfe_pct"] >= BIG_WINNER_MFE * 100.0
            and x["giveback_pct"] >= level_pct
        ]

        key = str(level_pct)

        if not hits:
            row["giveback_events"][key] = {
                "hit": False,
            }
            continue

        hit = hits[0]
        hit_index = hit["index"]
        hit_close = hit["close"]

        future = candles[
            hit_index + 1:
            record["end_index"] + 1
        ]

        future_highs = [
            float(c["high"])
            for c in future
        ]

        future_closes = [
            float(c["close"])
            for c in future
        ]

        max_future_high = (
            max(future_highs)
            if future_highs
            else hit_close
        )

        max_future_close = (
            max(future_closes)
            if future_closes
            else hit_close
        )

        additional_upside_high = (
            max_future_high / hit_close - 1.0
        )

        additional_upside_close = (
            max_future_close / hit_close - 1.0
        )

        final_close = (
            float(candles[record["end_index"]]["close"])
        )

        row["giveback_events"][key] = {
            "hit": True,
            "time": hit["time"],
            "close_at_hit": hit_close,
            "profit_at_hit_pct": (
                (hit_close / entry - 1.0) * 100.0
            ),
            "peak_at_hit": hit["peak"],
            "mfe_at_hit_pct": hit["mfe_pct"],
            "giveback_at_hit_pct": hit["giveback_pct"],
            "bars_remaining": (
                record["end_index"] - hit_index
            ),
            "max_future_high": max_future_high,
            "max_future_high_pct_from_entry": (
                (max_future_high / entry - 1.0) * 100.0
            ),
            "additional_upside_high_pct": (
                additional_upside_high * 100.0
            ),
            "max_future_close": max_future_close,
            "max_future_close_pct_from_entry": (
                (max_future_close / entry - 1.0) * 100.0
            ),
            "additional_upside_close_pct": (
                additional_upside_close * 100.0
            ),
            "final_close": final_close,
            "final_close_pct_from_entry": (
                (final_close / entry - 1.0) * 100.0
            ),
        }

    return row


def summarize(rows):
    winners = [
        r for r in rows
        if r["big_winner"]
    ]

    summary = {
        "all_candidates": len(rows),
        "big_winners": len(winners),
        "big_winner_rate_pct": (
            len(winners) / len(rows) * 100.0
            if rows else 0.0
        ),
        "giveback_levels": {},
    }

    for level in GIVEBACK_LEVELS:
        key = str(level * 100.0)

        events = [
            r["giveback_events"][key]
            for r in winners
            if r["giveback_events"][key]["hit"]
        ]

        additional_high = [
            x["additional_upside_high_pct"]
            for x in events
            if x["bars_remaining"] > 0
        ]

        additional_close = [
            x["additional_upside_close_pct"]
            for x in events
            if x["bars_remaining"] > 0
        ]

        final_results = [
            x["final_close_pct_from_entry"]
            for x in events
        ]

        summary["giveback_levels"][key] = {
            "hits": len(events),
            "avg_profit_at_hit_pct": (
                sum(
                    x["profit_at_hit_pct"]
                    for x in events
                ) / len(events)
                if events else 0.0
            ),
            "avg_additional_upside_high_pct": (
                sum(additional_high) / len(additional_high)
                if additional_high else 0.0
            ),
            "max_additional_upside_high_pct": (
                max(additional_high)
                if additional_high else 0.0
            ),
            "avg_additional_upside_close_pct": (
                sum(additional_close) / len(additional_close)
                if additional_close else 0.0
            ),
            "max_additional_upside_close_pct": (
                max(additional_close)
                if additional_close else 0.0
            ),
            "future_high_ge_0_50pct": sum(
                x >= 0.50
                for x in additional_high
            ),
            "future_high_ge_1_00pct": sum(
                x >= 1.00
                for x in additional_high
            ),
            "final_positive": sum(
                x > 0
                for x in final_results
            ),
            "final_negative": sum(
                x <= 0
                for x in final_results
            ),
        }

    return summary


def main():
    print("=" * 72)
    print("BIG WINNER PRESERVATION AUDIT V2")
    print("=" * 72)
    print(f"Symbol       : {SYMBOL}")
    print(f"Interval     : {INTERVAL}")
    print(f"Candles      : {WINDOW_30D_CANDLES:,}")
    print(f"Big Winner   : MFE >= {BIG_WINNER_MFE * 100:.2f}%")
    print("Lookahead    : BLOCKED")
    print("Profit Lock  : NOT USED")
    print("=" * 72)

    candles = fetch_closed_candles_paginated(
        SYMBOL,
        INTERVAL,
        WINDOW_30D_CANDLES,
    )

    records = build_records(candles)

    rows = [
        analyze_trade(record, candles)
        for record in records
    ]

    summary = summarize(rows)

    output = {
        "standard": {
            "symbol": SYMBOL,
            "interval": INTERVAL,
            "candles": len(candles),
            "horizon_bars": HORIZON,
            "big_winner_mfe_pct": BIG_WINNER_MFE * 100.0,
            "lookahead": False,
            "profit_lock_used": False,
        },
        "summary": summary,
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

    print()
    print("RESULT")
    print("-" * 72)
    print(f"Candidates   : {summary['all_candidates']}")
    print(f"Big Winners  : {summary['big_winners']}")
    print(
        f"Winner Rate  : "
        f"{summary['big_winner_rate_pct']:.2f}%"
    )

    for level, data in summary["giveback_levels"].items():
        print(
            f"Giveback {level}% : "
            f"hits={data['hits']} "
            f"avg_profit_at_hit="
            f"{data['avg_profit_at_hit_pct']:.2f}% "
            f"avg_additional_high="
            f"{data['avg_additional_upside_high_pct']:.2f}% "
            f"max_additional_high="
            f"{data['max_additional_upside_high_pct']:.2f}%"
        )

    print(f"Saved        : {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
