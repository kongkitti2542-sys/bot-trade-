"""Research-only MONEY_MAKER_01 upside / TP reach audit V1.

Purpose:
- Locked universe only:
  1) SOLUSDT 30m
  2) ETHUSDT 15m
  3) SOLUSDT 15m
- Entry logic is an exact transcription of MONEY_MAKER_01 baseline.
- Do not optimize or change the entry.
- Measure how far price travels after each entry.
- Measure MFE over 1h/2h/4h/8h.
- Measure fixed TP reach probability and time-to-TP.
- Measure final close after 8h as context only.
- No AI, regime filter, quality gate, Profit Lock, giveback, or production changes.
- Entry uses only candles before the signal; future candles are used only for post-entry outcome measurement.
- This is a diagnostic research audit, not production approval.
"""

import json
import sys
from pathlib import Path
from statistics import median

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from research_groq_30day_compounding_v5_2 import fetch_closed_candles_paginated
from validate_atr_expansion_ema50 import (
    ATR_PERIOD,
    ATR_LOOKBACK,
    ATR_EXPANSION_MULTIPLIER,
    RV_THRESHOLD,
    calculate_atr,
    calculate_ema,
    calculate_relative_volume,
)

UNIVERSE = (
    ("SOLUSDT", "30m"),
    ("ETHUSDT", "15m"),
    ("SOLUSDT", "15m"),
)

WINDOW_DAYS = 30
STARTING_POT_THB = 1500.0
ROUND_TRIP_COST_PCT = 0.14

# Elapsed-time horizons for measuring how far the trade can travel.
MFE_HORIZONS_MINUTES = (60, 120, 240, 480)

# Diagnostic TP ladder only; no TP is selected by this script.
TP_LEVELS_PCT = (0.20, 0.30, 0.50, 0.75, 1.00, 1.50, 2.00, 3.00)

# Context horizon for final close only.
CONTEXT_HORIZON_MINUTES = 480

OUTPUT_FILE = Path(
    "money_machine_v2/research/money_maker_01_upside_tp_reach_audit_v1.json"
)


def bars_for_minutes(timeframe, minutes):
    minutes_per_bar = {
        "15m": 15,
        "30m": 30,
    }[timeframe]
    return minutes // minutes_per_bar


def build_candidates(candles):
    atr = calculate_atr(candles)
    closes = [c["close"] for c in candles]
    ema50 = calculate_ema(closes, 50)
    rv = calculate_relative_volume(candles)

    start = max(ATR_PERIOD + ATR_LOOKBACK, 50)
    rows = []

    # Entry itself needs only signal candle + next candle open.
    end = len(candles) - 2

    for i in range(start, end + 1):
        if atr[i] is None or ema50[i] is None or rv[i] is None:
            continue

        recent = [
            atr[j]
            for j in range(i - ATR_LOOKBACK, i)
            if atr[j] is not None
        ]
        if len(recent) != ATR_LOOKBACK:
            continue

        expansion_ratio = atr[i] / (sum(recent) / ATR_LOOKBACK)
        candle_range = candles[i]["high"] - candles[i]["low"]

        if not (
            expansion_ratio >= ATR_EXPANSION_MULTIPLIER
            and candle_range >= atr[i]
            and candles[i]["close"] > candles[i]["open"]
            and candles[i]["close"] > candles[i - 1]["close"]
            and rv[i] >= RV_THRESHOLD
            and candles[i]["close"] > ema50[i]
        ):
            continue

        rows.append({
            "signal_index": i,
            "entry_index": i + 1,
            "signal_time": candles[i]["time"].isoformat(),
            "entry_time": candles[i + 1]["time"].isoformat(),
            "entry": float(candles[i + 1]["open"]),
            "atr": float(atr[i]),
            "atr_expansion_ratio": float(expansion_ratio),
            "relative_volume": float(rv[i]),
            "ema50": float(ema50[i]),
        })

    return rows


def select_non_overlapping(candles, candidates):
    selected = []
    active_until = -1
    skipped = 0

    for c in sorted(candidates, key=lambda x: x["entry_index"]):
        idx = c["entry_index"]
        if idx <= active_until:
            skipped += 1
            continue

        selected.append(c)
        # For this diagnostic, an observation window is 8h.
        # Non-overlap prevents one market move from contributing
        # multiple simultaneous entries.
        active_until = idx + 1

    return selected, skipped


def first_tp_hit(candles, entry_index, entry_price, target_pct, horizon_bars):
    target = entry_price * (1.0 + target_pct / 100.0)
    end = min(entry_index + horizon_bars, len(candles) - 1)

    for i in range(entry_index + 1, end + 1):
        if candles[i]["high"] >= target:
            return {
                "hit": True,
                "bars": i - entry_index,
                "time": candles[i]["time"].isoformat(),
            }

    return {
        "hit": False,
        "bars": None,
        "time": None,
    }


def analyze(candles, candidates, timeframe):
    max_horizon_bars = bars_for_minutes(
        timeframe,
        CONTEXT_HORIZON_MINUTES,
    )

    selected, skipped = select_non_overlapping(candles, candidates)

    rows = []

    for c in selected:
        entry_idx = c["entry_index"]
        entry = c["entry"]

        row = {
            "signal_time": c["signal_time"],
            "entry_time": c["entry_time"],
            "entry": entry,
            "atr": c["atr"],
            "atr_expansion_ratio": c["atr_expansion_ratio"],
            "relative_volume": c["relative_volume"],
            "mfe": {},
            "tp_reach": {},
            "context_8h": {},
        }

        for minutes in MFE_HORIZONS_MINUTES:
            horizon = bars_for_minutes(timeframe, minutes)
            end = min(entry_idx + horizon, len(candles) - 1)

            highs = [
                float(candles[i]["high"])
                for i in range(entry_idx + 1, end + 1)
            ]
            if highs:
                max_high = max(highs)
                mfe_pct = (max_high / entry - 1.0) * 100.0
            else:
                max_high = entry
                mfe_pct = 0.0

            row["mfe"][str(minutes)] = {
                "max_high": max_high,
                "mfe_pct": mfe_pct,
                "bars_observed": max(0, end - entry_idx),
            }

        for tp in TP_LEVELS_PCT:
            row["tp_reach"][str(tp)] = first_tp_hit(
                candles,
                entry_idx,
                entry,
                tp,
                max_horizon_bars,
            )

        context_end = min(
            entry_idx + max_horizon_bars,
            len(candles) - 1,
        )
        final_close = float(candles[context_end]["close"])
        row["context_8h"] = {
            "final_close": final_close,
            "final_close_pct": (final_close / entry - 1.0) * 100.0,
            "bars_observed": context_end - entry_idx,
        }

        rows.append(row)

    return selected, skipped, rows


def summarize(rows):
    summary = {
        "trades": len(rows),
        "mfe": {},
        "tp_reach": {},
        "context_8h": {},
    }

    for minutes in MFE_HORIZONS_MINUTES:
        values = [
            r["mfe"][str(minutes)]["mfe_pct"]
            for r in rows
        ]
        values_sorted = sorted(values)
        summary["mfe"][str(minutes)] = {
            "mean_pct": sum(values) / len(values) if values else 0.0,
            "median_pct": median(values) if values else 0.0,
            "p75_pct": (
                values_sorted[int(0.75 * (len(values_sorted) - 1))]
                if values_sorted else 0.0
            ),
            "p90_pct": (
                values_sorted[int(0.90 * (len(values_sorted) - 1))]
                if values_sorted else 0.0
            ),
            "max_pct": max(values) if values else 0.0,
            "ge_0_30_pct": sum(x >= 0.30 for x in values),
            "ge_0_50_pct": sum(x >= 0.50 for x in values),
            "ge_1_00_pct": sum(x >= 1.00 for x in values),
            "ge_1_50_pct": sum(x >= 1.50 for x in values),
            "ge_2_00_pct": sum(x >= 2.00 for x in values),
        }

    for tp in TP_LEVELS_PCT:
        key = str(tp)
        events = [
            r["tp_reach"][key]
            for r in rows
        ]
        hits = [e for e in events if e["hit"]]
        hit_bars = [e["bars"] for e in hits]

        summary["tp_reach"][key] = {
            "hits": len(hits),
            "hit_rate_pct": (
                len(hits) / len(events) * 100.0
                if events else 0.0
            ),
            "median_bars_to_hit": (
                median(hit_bars)
                if hit_bars else None
            ),
            "min_bars_to_hit": (
                min(hit_bars)
                if hit_bars else None
            ),
            "max_bars_to_hit": (
                max(hit_bars)
                if hit_bars else None
            ),
        }

    closes = [
        r["context_8h"]["final_close_pct"]
        for r in rows
    ]
    summary["context_8h"] = {
        "mean_final_close_pct": (
            sum(closes) / len(closes) if closes else 0.0
        ),
        "median_final_close_pct": (
            median(closes) if closes else 0.0
        ),
        "positive_final_close": sum(x > 0 for x in closes),
        "negative_or_flat_final_close": sum(x <= 0 for x in closes),
    }

    return summary


def main():
    output = {
        "research_version": "MONEY_MAKER_01_UPSIDE_TP_REACH_AUDIT_V1",
        "standard": {
            "locked_universe": [
                {"symbol": "SOLUSDT", "timeframe": "30m"},
                {"symbol": "ETHUSDT", "timeframe": "15m"},
                {"symbol": "SOLUSDT", "timeframe": "15m"},
            ],
            "window_days": WINDOW_DAYS,
            "starting_pot_thb": STARTING_POT_THB,
            "round_trip_cost_pct": ROUND_TRIP_COST_PCT,
            "entry_logic": {
                "atr_period": ATR_PERIOD,
                "atr_lookback": ATR_LOOKBACK,
                "atr_expansion_multiplier": ATR_EXPANSION_MULTIPLIER,
                "candle_range_at_least_atr": True,
                "bullish": True,
                "higher_close": True,
                "relative_volume_at_least": RV_THRESHOLD,
                "close_above_ema50": True,
                "entry": "NEXT_CANDLE_OPEN",
            },
            "mfe_horizons_minutes": list(MFE_HORIZONS_MINUTES),
            "tp_levels_pct": list(TP_LEVELS_PCT),
            "context_horizon_minutes": CONTEXT_HORIZON_MINUTES,
            "entry_lookahead": False,
            "future_used_only_for_outcome": True,
            "ai_used": False,
            "production_changed": False,
        },
        "results": {},
    }

    for symbol, timeframe in UNIVERSE:
        key = f"{symbol}_{timeframe}"
        print("=" * 72)
        print(f"UPSIDE / TP AUDIT: {symbol} {timeframe}")
        print("=" * 72)

        bars = (WINDOW_DAYS * 1440) // {
            "15m": 15,
            "30m": 30,
        }[timeframe]

        candles = fetch_closed_candles_paginated(
            symbol,
            timeframe,
            bars,
        )

        candidates = build_candidates(candles)
        selected, skipped, rows = analyze(
            candles,
            candidates,
            timeframe,
        )
        summary = summarize(rows)

        output["results"][key] = {
            "symbol": symbol,
            "timeframe": timeframe,
            "candles": len(candles),
            "candidates": len(candidates),
            "selected_non_overlapping": len(selected),
            "skipped_overlap": skipped,
            "summary": summary,
            "trades": rows,
        }

        print(f"Candles       : {len(candles):,}")
        print(f"Candidates    : {len(candidates)}")
        print(f"Selected      : {len(selected)}")
        print(f"Overlap skip  : {skipped}")
        for tp, data in summary["tp_reach"].items():
            print(
                f"TP +{tp}%       : "
                f"{data['hits']}/{summary['trades']} "
                f"({data['hit_rate_pct']:.2f}%)"
            )
        print()

    OUTPUT_FILE.write_text(
        json.dumps(output, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    print(f"Saved: {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
