"""
Profit Lock Research V1

Research-only simulation for converting favorable price movement
(MFE) into realized profit.

Standard:
    BTCUSDT 5m
    7D  = 2,016 closed candles
    30D = 8,640 closed candles

Rules:
    - Money Maker #1 entry
    - Real Risk Manager sizing
    - Position overlap blocked
    - 0.14% round-trip research cost
    - Fixed-horizon fallback
    - No AI
    - No execution
    - No Paper DB
    - No Core modification
"""

import json
from datetime import datetime, timezone
from pathlib import Path

from money_maker_01_adapter_v1 import find_candidates
from risk import evaluate_risk
from capital_config import REFERENCE_USDTHB

from research_groq_30day_compounding_v5_2 import (
    fetch_closed_candles_paginated,
)

from research_standard_v1 import (
    STANDARD_VERSION,
    SYMBOL,
    INTERVAL,
    WINDOW_7D_CANDLES,
    WINDOW_30D_CANDLES,
)

CANDLE_LIMIT = WINDOW_30D_CANDLES

STARTING_POT_THB = 1500.0

FEE_PER_SIDE = 0.0005
SLIPPAGE_PER_SIDE = 0.0002
ROUND_TRIP_COST = (
    2 * FEE_PER_SIDE
    + 2 * SLIPPAGE_PER_SIDE
)

PROFIT_LOCKS = (
    {
        "name": "PL_020_LOCK_005",
        "trigger": 0.0020,
        "lock": 0.0005,
    },
    {
        "name": "PL_030_LOCK_010",
        "trigger": 0.0030,
        "lock": 0.0010,
    },
    {
        "name": "PL_050_LOCK_020",
        "trigger": 0.0050,
        "lock": 0.0020,
    },
    {
        "name": "PL_075_LOCK_030",
        "trigger": 0.0075,
        "lock": 0.0030,
    },
    {
        "name": "PL_100_LOCK_050",
        "trigger": 0.0100,
        "lock": 0.0050,
    },
)

OUTPUT_FILE = Path(
    "money_machine_v2/research/profit_lock_reconcile_results.json"
)


def build_candle_index(candles):
    return {
        candle["time"]: index
        for index, candle in enumerate(candles)
    }


def simulate_exit(
    candidate,
    entry_index,
    fixed_exit_index,
    candles,
    trigger,
    lock,
):
    entry = candidate["entry"]
    side = candidate["signal"]

    if side == "BUY":
        trigger_price = entry * (1.0 + trigger)
        lock_price = entry * (1.0 + lock)

        activated = False

        for index in range(
            entry_index,
            fixed_exit_index + 1,
        ):
            candle = candles[index]

            if not activated:
                if candle["high"] >= trigger_price:
                    activated = True
                    continue

            if activated:
                if candle["low"] <= lock_price:
                    return {
                        "exit_index": index,
                        "exit_price": lock_price,
                        "exit_type": "PROFIT_LOCK",
                        "triggered": True,
                    }

        return {
            "exit_index": fixed_exit_index,
            "exit_price": candles[
                fixed_exit_index
            ]["close"],
            "exit_type": "FIXED_FALLBACK",
            "triggered": False,
        }

    if side == "SELL":
        trigger_price = entry * (1.0 - trigger)
        lock_price = entry * (1.0 - lock)

        activated = False

        for index in range(
            entry_index,
            fixed_exit_index + 1,
        ):
            candle = candles[index]

            if not activated:
                if candle["low"] <= trigger_price:
                    activated = True
                    continue

            if activated:
                if candle["high"] >= lock_price:
                    return {
                        "exit_index": index,
                        "exit_price": lock_price,
                        "exit_type": "PROFIT_LOCK",
                        "triggered": True,
                    }

        return {
            "exit_index": fixed_exit_index,
            "exit_price": candles[
                fixed_exit_index
            ]["close"],
            "exit_type": "FIXED_FALLBACK",
            "triggered": False,
        }

    return None


def calculate_gross_return(
    side,
    entry,
    exit_price,
):
    if side == "BUY":
        return (
            exit_price - entry
        ) / entry

    if side == "SELL":
        return (
            entry - exit_price
        ) / entry

    return None


def build_candidates(
    candles,
):
    candidates = find_candidates(candles)

    index = build_candle_index(candles)

    records = []

    for candidate in candidates:
        entry_index = index.get(
            candidate["entry_time"]
        )

        fixed_exit_index = index.get(
            candidate["planned_exit_time"]
        )

        if entry_index is None:
            continue

        if fixed_exit_index is None:
            continue

        if fixed_exit_index < entry_index:
            continue

        records.append(
            {
                "candidate": candidate,
                "entry_index": entry_index,
                "fixed_exit_index": fixed_exit_index,
            }
        )

    records.sort(
        key=lambda row:
        row["candidate"]["entry_time"]
    )

    return records


def simulate_strategy(
    records,
    starting_pot_thb,
    trigger,
    lock,
):
    pot_thb = starting_pot_thb
    active_exit_time = None

    trades = []
    skipped_overlap = 0

    for record in records:
        candidate = record["candidate"]

        entry_time = candidate[
            "entry_time"
        ]

        fixed_exit_time = candidate[
            "planned_exit_time"
        ]

        if (
            active_exit_time is not None
            and entry_time < active_exit_time
        ):
            skipped_overlap += 1
            continue

        capital_usdt = (
            pot_thb / REFERENCE_USDTHB
        )

        decision = {
            "signal": candidate["signal"],
            "confidence": 0,
            "quality": "PASSED",
        }

        features = {
            "close": candidate["entry"],
            "atr14": candidate[
                "features"
            ]["atr"],
        }

        risk = evaluate_risk(
            decision=decision,
            features=features,
            capital=capital_usdt,
            daily_pnl=0.0,
            open_positions=0,
        )

        if not risk.get("allowed"):
            continue

        position_value_usdt = float(
            risk["position_value"]
        )

        position_value_thb = (
            position_value_usdt
            * REFERENCE_USDTHB
        )

        exit_result = simulate_exit(
            candidate=candidate,
            entry_index=record[
                "entry_index"
            ],
            fixed_exit_index=record[
                "fixed_exit_index"
            ],
            candles=GLOBAL_CANDLES,
            trigger=trigger,
            lock=lock,
        )

        if exit_result is None:
            continue

        gross_return = calculate_gross_return(
            candidate["signal"],
            candidate["entry"],
            exit_result["exit_price"],
        )

        if gross_return is None:
            continue

        gross_pnl_thb = (
            position_value_thb
            * gross_return
        )

        cost_thb = (
            position_value_thb
            * ROUND_TRIP_COST
        )

        net_pnl_thb = (
            gross_pnl_thb
            - cost_thb
        )

        pot_before = pot_thb
        pot_thb += net_pnl_thb

        trades.append(
            {
                "trade_number": len(trades) + 1,
                "signal_time": candidate[
                    "signal_time"
                ].isoformat(),
                "entry_time": entry_time.isoformat(),
                "fixed_exit_time": fixed_exit_time.isoformat(),
                "actual_exit_time": candles_time(
                    exit_result["exit_index"]
                ).isoformat(),
                "signal": candidate["signal"],
                "setup": candidate["setup"],
                "entry": candidate["entry"],
                "exit_price": exit_result[
                    "exit_price"
                ],
                "exit_type": exit_result[
                    "exit_type"
                ],
                "triggered": exit_result[
                    "triggered"
                ],
                "gross_return": gross_return,
                "position_value_thb": position_value_thb,
                "gross_pnl_thb": gross_pnl_thb,
                "cost_thb": cost_thb,
                "net_pnl_thb": net_pnl_thb,
                "pot_before_thb": pot_before,
                "pot_after_thb": pot_thb,
            }
        )

        active_exit_time = candles_time(
            exit_result["exit_index"]
        )

    return trades, skipped_overlap


def candles_time(index):
    return GLOBAL_CANDLES[index]["time"]


def calculate_drawdown(
    trades,
    starting_pot,
):
    peak = starting_pot
    max_dd = 0.0

    for trade in trades:
        pot = trade["pot_after_thb"]

        if pot > peak:
            peak = pot

        if peak > 0:
            dd = (
                pot - peak
            ) / peak

            max_dd = min(
                max_dd,
                dd,
            )

    return max_dd * 100.0


def summarize(
    trades,
    skipped_overlap,
    starting_pot,
):
    if not trades:
        return {
            "trades": 0,
            "wins": 0,
            "losses": 0,
            "win_rate": 0.0,
            "ending_pot_thb": starting_pot,
            "net_profit_thb": 0.0,
            "return_pct": 0.0,
            "max_drawdown_pct": 0.0,
            "profit_lock_exits": 0,
            "fallback_exits": 0,
            "skipped_overlap": skipped_overlap,
        }

    wins = sum(
        1
        for trade in trades
        if trade["net_pnl_thb"] > 0
    )

    losses = sum(
        1
        for trade in trades
        if trade["net_pnl_thb"] < 0
    )

    ending_pot = trades[-1][
        "pot_after_thb"
    ]

    profit_lock_exits = sum(
        1
        for trade in trades
        if trade["exit_type"]
        == "PROFIT_LOCK"
    )

    fallback_exits = sum(
        1
        for trade in trades
        if trade["exit_type"]
        == "FIXED_FALLBACK"
    )

    net_profit = (
        ending_pot
        - starting_pot
    )

    return {
        "trades": len(trades),
        "wins": wins,
        "losses": losses,
        "win_rate": (
            wins / len(trades) * 100.0
        ),
        "ending_pot_thb": ending_pot,
        "net_profit_thb": net_profit,
        "return_pct": (
            net_profit
            / starting_pot
            * 100.0
        ),
        "max_drawdown_pct": calculate_drawdown(
            trades,
            starting_pot,
        ),
        "profit_lock_exits": (
            profit_lock_exits
        ),
        "fallback_exits": fallback_exits,
        "skipped_overlap": skipped_overlap,
        "gross_pnl_thb": sum(
            trade["gross_pnl_thb"]
            for trade in trades
        ),
        "cost_thb": sum(
            trade["cost_thb"]
            for trade in trades
        ),
        "net_pnl_thb": sum(
            trade["net_pnl_thb"]
            for trade in trades
        ),
    }


def split_windows(
    candles,
    window_size,
):
    windows = []

    for start in range(
        0,
        len(candles),
        window_size,
    ):
        window = candles[
            start:start + window_size
        ]

        if len(window) == window_size:
            windows.append(window)

    return windows


def main():
    global GLOBAL_CANDLES

    print("=" * 72)
    print("PROFIT LOCK RESEARCH V1")
    print("STANDARD RESEARCH WINDOWS")
    print("=" * 72)

    print(
        f"Standard : {STANDARD_VERSION}"
    )
    print(
        f"Symbol   : {SYMBOL}"
    )
    print(
        f"Interval : {INTERVAL}"
    )
    print(
        f"7D       : {WINDOW_7D_CANDLES:,} candles"
    )
    print(
        f"30D      : {WINDOW_30D_CANDLES:,} candles"
    )
    print(
        f"Cost     : "
        f"{ROUND_TRIP_COST * 100:.4f}% RT"
    )
    print(
        "Risk     : REAL"
    )
    print(
        "Overlap  : BLOCKED"
    )
    print(
        "AI       : NOT USED"
    )
    print(
        "Execution: NONE"
    )
    print("=" * 72)

    GLOBAL_CANDLES = (
        fetch_closed_candles_paginated(
            SYMBOL,
            INTERVAL,
            CANDLE_LIMIT,
        )
    )

    print(
        f"Candles returned : "
        f"{len(GLOBAL_CANDLES):,}"
    )

    candidates = build_candidates(
        GLOBAL_CANDLES
    )

    print(
        f"Resolved candidates : "
        f"{len(candidates)}"
    )

    output = {
        "research_version": (
            "PROFIT_LOCK_RESEARCH_V1"
        ),
        "generated_at": datetime.now(
            timezone.utc
        ).isoformat(),
        "research_standard": (
            STANDARD_VERSION
        ),
        "symbol": SYMBOL,
        "interval": INTERVAL,
        "cost_round_trip": ROUND_TRIP_COST,
        "starting_pot_thb": STARTING_POT_THB,
        "windows": {},
    }

    for window_name, window_size in (
        ("7D", WINDOW_7D_CANDLES),
        ("30D", WINDOW_30D_CANDLES),
    ):
        window_rows = []

        for index, window in enumerate(
            split_windows(
                GLOBAL_CANDLES,
                window_size,
            ),
            start=1,
        ):
            window_start = window[0]["time"]
            window_end = window[-1]["time"]

            window_records = [
                record
                for record in candidates
                if (
                    record["candidate"][
                        "entry_time"
                    ] >= window_start
                    and record["candidate"][
                        "entry_time"
                    ] <= window_end
                    and record["candidate"][
                        "planned_exit_time"
                    ] <= window_end
                )
            ]

            row = {
                "window": (
                    f"{window_name}_W"
                    f"{index:02d}"
                ),
                "first_candle": (
                    window_start.isoformat()
                ),
                "last_candle": (
                    window_end.isoformat()
                ),
                "candidate_count": len(
                    window_records
                ),
                "strategies": {},
            }

            for strategy in PROFIT_LOCKS:
                trades, skipped = (
                    simulate_strategy(
                        window_records,
                        STARTING_POT_THB,
                        strategy["trigger"],
                        strategy["lock"],
                    )
                )

                row["strategies"][
                    strategy["name"]
                ] = {
                    "trigger": strategy[
                        "trigger"
                    ],
                    "lock": strategy[
                        "lock"
                    ],
                    **summarize(
                        trades,
                        skipped,
                        STARTING_POT_THB,
                    ),
                    "trades_detail": trades,
                }

            window_rows.append(row)

        output["windows"][
            window_name
        ] = window_rows

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
    print("PROFIT LOCK RESULT")
    print("=" * 72)

    for window_name in (
        "7D",
        "30D",
    ):
        print()
        print(
            f"### {window_name}"
        )

        for row in output[
            "windows"
        ][window_name]:
            print(
                row["window"],
                f"N={row['candidate_count']}",
            )

            for strategy in PROFIT_LOCKS:
                result = row[
                    "strategies"
                ][strategy["name"]]

                print(
                    f"  "
                    f"{strategy['name']}: "
                    f"Trades={result['trades']} "
                    f"WR={result['win_rate']:.2f}% "
                    f"Return={result['return_pct']:.4f}% "
                    f"EndPot={result['ending_pot_thb']:.2f} "
                    f"DD={result['max_drawdown_pct']:.4f}% "
                    f"Lock={result['profit_lock_exits']} "
                    f"Fallback={result['fallback_exits']}"
                )

    print()
    print(
        "Saved:",
        OUTPUT_FILE,
    )
    print("=" * 72)


if __name__ == "__main__":
    main()
