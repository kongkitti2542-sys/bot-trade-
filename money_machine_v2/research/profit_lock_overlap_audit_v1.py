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

RESULT_FILE = Path(
    "money_machine_v2/research/profit_lock_reconcile_results.json"
)

OUTPUT_FILE = Path(
    "money_machine_v2/research/profit_lock_overlap_audit_v1.json"
)

candles = fetch_closed_candles_paginated(
    SYMBOL,
    INTERVAL,
    WINDOW_30D_CANDLES,
)

records = build_candidates(candles[:-1])

# ------------------------------------------------------------------
# A) Fixed-horizon overlap blocking
# ------------------------------------------------------------------

fixed_trades = []
fixed_skipped = 0
active_fixed_exit = None

for record in records:
    candidate = record["candidate"]
    entry_time = candidate["entry_time"]
    fixed_exit_time = candidate["planned_exit_time"]

    if (
        active_fixed_exit is not None
        and entry_time < active_fixed_exit
    ):
        fixed_skipped += 1
        continue

    fixed_trades.append(record)
    active_fixed_exit = fixed_exit_time

# ------------------------------------------------------------------
# B) Actual PL_050 Profit-Lock overlap blocking
# ------------------------------------------------------------------

PL_TRIGGER = 0.005
PL_LOCK = 0.002

actual_trades = []
actual_skipped = 0
active_actual_exit = None

for record in records:
    candidate = record["candidate"]
    entry_time = candidate["entry_time"]

    if (
        active_actual_exit is not None
        and entry_time < active_actual_exit
    ):
        actual_skipped += 1
        continue

    exit_result = simulate_exit(
        candidate=candidate,
        entry_index=record["entry_index"],
        fixed_exit_index=record["fixed_exit_index"],
        candles=candles,
        trigger=PL_TRIGGER,
        lock=PL_LOCK,
    )

    if exit_result is None:
        continue

    actual_exit_time = candles[
        exit_result["exit_index"]
    ]["time"]

    actual_trades.append({
        "record": record,
        "actual_exit_time": actual_exit_time,
        "exit_type": exit_result["exit_type"],
    })

    active_actual_exit = actual_exit_time

fixed_entries = {
    r["candidate"]["entry_time"]
    for r in fixed_trades
}

actual_entries = {
    r["record"]["candidate"]["entry_time"]
    for r in actual_trades
}

only_fixed = sorted(
    fixed_entries - actual_entries
)

only_actual = sorted(
    actual_entries - fixed_entries
)

# ------------------------------------------------------------------
# Stored research PL_050
# ------------------------------------------------------------------

stored = json.loads(
    RESULT_FILE.read_text(encoding="utf-8")
)

stored_rows = []

for window in stored["windows"].get("30D", []):
    strategy = window["strategies"]["PL_050_LOCK_020"]

    for trade in strategy["trades_detail"]:
        stored_rows.append({
            "entry_time": trade["entry_time"],
            "actual_exit_time": trade["actual_exit_time"],
            "exit_type": trade["exit_type"],
            "fixed_exit_time": trade["fixed_exit_time"],
        })

output = {
    "symbol": SYMBOL,
    "interval": INTERVAL,
    "candles": len(candles),
    "resolved_candidates": len(records),

    "fixed_horizon": {
        "trades": len(fixed_trades),
        "skipped_overlap": fixed_skipped,
    },

    "actual_profit_lock_pl050": {
        "trades": len(actual_trades),
        "skipped_overlap": actual_skipped,
    },

    "entry_difference": {
        "only_fixed_horizon": [
            t.isoformat()
            for t in only_fixed
        ],
        "only_actual_profit_lock": [
            t.isoformat()
            for t in only_actual
        ],
    },

    "stored_research_pl050": {
        "trades": len(stored_rows),
        "rows": stored_rows,
    },
}

OUTPUT_FILE.write_text(
    json.dumps(
        output,
        indent=2,
        ensure_ascii=False,
        default=str,
    ),
    encoding="utf-8",
)

print("=" * 72)
print("PROFIT LOCK OVERLAP AUDIT V1")
print("=" * 72)
print(f"Candles                 : {len(candles)}")
print(f"Resolved candidates     : {len(records)}")
print(f"Fixed-horizon trades    : {len(fixed_trades)}")
print(f"Fixed-horizon skipped   : {fixed_skipped}")
print(f"Actual PL_050 trades    : {len(actual_trades)}")
print(f"Actual PL_050 skipped   : {actual_skipped}")
print(f"Only fixed-horizon      : {len(only_fixed)}")
print(f"Only actual Profit Lock : {len(only_actual)}")
print(f"Stored research PL_050  : {len(stored_rows)}")
print("=" * 72)
print(f"Saved: {OUTPUT_FILE}")
