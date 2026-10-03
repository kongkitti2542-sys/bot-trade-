"""
Groq 30-Day Full-Pot Compounding V5

Research-only simulation.

Goal:
- Use the real Money Maker #1 candidates.
- Process candidates chronologically.
- Start with a fixed THB pot.
- Compound the pot after every completed trade.
- Apply research fee + slippage costs.
- Do not use AI decisions.
- Do not execute real or paper orders.
- Do not modify Core, Money Maker, Risk, PaperTrader, Position Manager,
  Groq Judge, V4, or any existing production/research file.

Important:
This is a mechanical compounding simulation from historical candidates.
It is NOT a production performance claim or a forecast.
"""

import json
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

from money_maker_01_adapter_v1 import find_candidates
from risk import evaluate_risk
from capital_config import REFERENCE_USDTHB


SYMBOL = "BTCUSDT"
INTERVAL = "5m"

CANDLE_LIMIT = 100_000
BINANCE_URL = "https://api.binance.com/api/v3/klines"
BINANCE_PAGE_LIMIT = 1000

STARTING_POT_THB = 1500.0

# Same research cost assumption used by V4/Money Maker #1.
FEE_PER_SIDE = 0.0005
SLIPPAGE_PER_SIDE = 0.0002
ROUND_TRIP_COST = (2 * FEE_PER_SIDE) + (2 * SLIPPAGE_PER_SIDE)

OUTPUT_FILE = Path(
    "research_groq_30day_compounding_v5_2_results.json"
)

RESEARCH_VERSION = "GROQ_CONTINUOUS_RISK_COMPOUNDING_V5_2"


def fetch_closed_candles_paginated(symbol, interval, limit):
    raw_candles = []
    end_time = None

    while len(raw_candles) < limit + 1:
        page_limit = min(
            BINANCE_PAGE_LIMIT,
            limit + 1 - len(raw_candles),
        )

        params = [
            f"symbol={symbol}",
            f"interval={interval}",
            f"limit={page_limit}",
        ]

        if end_time is not None:
            params.append(f"endTime={end_time}")

        url = BINANCE_URL + "?" + "&".join(params)

        request = Request(
            url,
            headers={
                "User-Agent": "personal-trading-bot-research/1.0",
            },
            method="GET",
        )

        with urlopen(request, timeout=15) as response:
            page = json.loads(
                response.read().decode("utf-8")
            )

        if not page:
            break

        raw_candles.extend(page)

        oldest_open_time = page[0][0]
        end_time = oldest_open_time - 1

        if len(page) < page_limit:
            break

    unique = {
        candle[0]: candle
        for candle in raw_candles
    }

    ordered = [
        unique[key]
        for key in sorted(unique)
    ]

    if not ordered:
        return []

    ordered = ordered[:-1]
    ordered = ordered[-limit:]

    candles = []

    for candle in ordered:
        candles.append(
            {
                "time": datetime.fromtimestamp(
                    candle[0] / 1000,
                    tz=timezone.utc,
                ),
                "open": float(candle[1]),
                "high": float(candle[2]),
                "low": float(candle[3]),
                "close": float(candle[4]),
                "volume": float(candle[5]),
            }
        )

    return candles


def find_candle_index(candles):
    return {
        candle["time"]: index
        for index, candle in enumerate(candles)
    }


def historical_return(candidate, candle_index, candles):
    exit_index = candle_index.get(
        candidate["planned_exit_time"]
    )

    if exit_index is None:
        return None

    entry = candidate["entry"]
    exit_price = candles[exit_index]["close"]

    if candidate["signal"] == "BUY":
        return (exit_price - entry) / entry

    if candidate["signal"] == "SELL":
        return (entry - exit_price) / entry

    return None


def net_return(gross_return):
    if gross_return is None:
        return None

    return gross_return - ROUND_TRIP_COST


def build_trade_records(candidates, candles):
    candle_index = find_candle_index(candles)

    records = []

    for candidate in candidates:
        gross = historical_return(
            candidate,
            candle_index,
            candles,
        )

        net = net_return(gross)

        if net is None:
            continue

        records.append(
            {
                "signal_time": candidate["signal_time"],
                "entry_time": candidate["entry_time"],
                "planned_exit_time": candidate[
                    "planned_exit_time"
                ],
                "signal": candidate["signal"],
                "setup": candidate["setup"],
                "entry": candidate["entry"],
                "reference_exit": candidate[
                    "reference_exit"
                ],
                "atr": candidate["features"]["atr"],
                "gross_return": gross,
                "net_return": net,
            }
        )

    records.sort(
        key=lambda record: record["entry_time"]
    )

    return records


def simulate_compounding(records, starting_pot):
    pot = starting_pot

    equity_curve = [
        {
            "time": records[0]["entry_time"].isoformat()
            if records
            else None,
            "pot_thb": pot,
        }
    ]

    completed = []

    for index, record in enumerate(records, start=1):
        pot_before = pot

        pot = pot * (1.0 + record["net_return"])

        record_result = {
            "trade_number": index,
            "signal_time": record["signal_time"].isoformat(),
            "entry_time": record["entry_time"].isoformat(),
            "planned_exit_time": record[
                "planned_exit_time"
            ].isoformat(),
            "signal": record["signal"],
            "setup": record["setup"],
            "entry": record["entry"],
            "reference_exit": record[
                "reference_exit"
            ],
            "gross_return": record["gross_return"],
            "net_return": record["net_return"],
            "pot_before_thb": pot_before,
            "pot_after_thb": pot,
            "pnl_thb": pot - pot_before,
        }

        completed.append(record_result)

        equity_curve.append(
            {
                "time": record[
                    "planned_exit_time"
                ].isoformat(),
                "pot_thb": pot,
            }
        )

    return completed, equity_curve


def calculate_drawdown(equity_curve):
    if not equity_curve:
        return {
            "max_drawdown_thb": 0.0,
            "max_drawdown_pct": 0.0,
        }

    peak = equity_curve[0]["pot_thb"]
    max_drawdown_thb = 0.0
    max_drawdown_pct = 0.0

    for point in equity_curve:
        pot = point["pot_thb"]

        if pot > peak:
            peak = pot

        drawdown_thb = pot - peak
        drawdown_pct = (
            drawdown_thb / peak
            if peak > 0
            else 0.0
        )

        if drawdown_thb < max_drawdown_thb:
            max_drawdown_thb = drawdown_thb

        if drawdown_pct < max_drawdown_pct:
            max_drawdown_pct = drawdown_pct

    return {
        "max_drawdown_thb": max_drawdown_thb,
        "max_drawdown_pct": max_drawdown_pct * 100.0,
    }


def calculate_loss_streak(trades):
    current = 0
    maximum = 0

    for trade in trades:
        if trade["pnl_thb"] < 0:
            current += 1
            maximum = max(maximum, current)
        else:
            current = 0

    return maximum


def calculate_trade_summary(trades):
    if not trades:
        return {
            "trades": 0,
            "wins": 0,
            "losses": 0,
            "win_rate": 0.0,
            "gross_return_sum_pct": 0.0,
            "net_return_sum_pct": 0.0,
        }

    wins = sum(
        1
        for trade in trades
        if trade["pnl_thb"] > 0
    )

    losses = sum(
        1
        for trade in trades
        if trade["pnl_thb"] < 0
    )

    return {
        "trades": len(trades),
        "wins": wins,
        "losses": losses,
        "win_rate": wins / len(trades) * 100.0,
        "gross_return_sum_pct": (
            sum(
                trade["gross_return"]
                for trade in trades
            )
            * 100.0
        ),
        "net_return_sum_pct": (
            sum(
                trade["net_return"]
                for trade in trades
            )
            * 100.0
        ),
    }


def simulate_continuous_risk_compounding(
    records,
    starting_pot_thb,
):
    pot_thb = starting_pot_thb
    active_exit_time = None
    trades = []
    skipped_overlapping = 0

    for record in records:
        entry_time = record["entry_time"]
        exit_time = record["planned_exit_time"]

        if (
            active_exit_time is not None
            and entry_time < active_exit_time
        ):
            skipped_overlapping += 1
            continue

        capital_usdt = pot_thb / REFERENCE_USDTHB

        decision = {
            "signal": record["signal"],
            "confidence": 0,
            "quality": "PASSED",
        }

        features = {
            "close": record["entry"],
            "atr14": record["atr"],
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

        gross_pnl_thb = (
            position_value_thb
            * record["gross_return"]
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
        pot_thb = pot_thb + net_pnl_thb

        trades.append(
            {
                "trade_number": len(trades) + 1,
                "signal_time": record[
                    "signal_time"
                ].isoformat(),
                "entry_time": entry_time.isoformat(),
                "planned_exit_time": exit_time.isoformat(),
                "signal": record["signal"],
                "setup": record["setup"],
                "entry": record["entry"],
                "reference_exit": record[
                    "reference_exit"
                ],
                "gross_return": record["gross_return"],
                "position_value_usdt": position_value_usdt,
                "position_value_thb": position_value_thb,
                "gross_pnl_thb": gross_pnl_thb,
                "cost_thb": cost_thb,
                "net_pnl_thb": net_pnl_thb,
                "pot_before_thb": pot_before,
                "pot_after_thb": pot_thb,
                "risk": risk,
            }
        )

        active_exit_time = exit_time

    return trades, skipped_overlapping


def calculate_equity_curve(trades, starting_pot_thb):
    curve = [
        {
            "time": (
                trades[0]["entry_time"]
                if trades
                else None
            ),
            "pot_thb": starting_pot_thb,
        }
    ]

    for trade in trades:
        curve.append(
            {
                "time": trade[
                    "planned_exit_time"
                ],
                "pot_thb": trade[
                    "pot_after_thb"
                ],
            }
        )

    return curve


def calculate_risk_drawdown(trades, starting_pot_thb):
    curve = calculate_equity_curve(
        trades,
        starting_pot_thb,
    )

    peak = starting_pot_thb
    max_dd_thb = 0.0
    max_dd_pct = 0.0

    for point in curve:
        pot = point["pot_thb"]

        if pot > peak:
            peak = pot

        dd_thb = pot - peak
        dd_pct = (
            dd_thb / peak
            if peak > 0
            else 0.0
        )

        if dd_thb < max_dd_thb:
            max_dd_thb = dd_thb

        if dd_pct < max_dd_pct:
            max_dd_pct = dd_pct

    return {
        "max_drawdown_thb": max_dd_thb,
        "max_drawdown_pct": max_dd_pct * 100.0,
    }


def calculate_trade_stats(trades):
    if not trades:
        return {
            "trades": 0,
            "wins": 0,
            "losses": 0,
            "win_rate": 0.0,
            "total_gross_pnl_thb": 0.0,
            "total_cost_thb": 0.0,
            "total_net_pnl_thb": 0.0,
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

    return {
        "trades": len(trades),
        "wins": wins,
        "losses": losses,
        "win_rate": (
            wins / len(trades) * 100.0
        ),
        "total_gross_pnl_thb": sum(
            trade["gross_pnl_thb"]
            for trade in trades
        ),
        "total_cost_thb": sum(
            trade["cost_thb"]
            for trade in trades
        ),
        "total_net_pnl_thb": sum(
            trade["net_pnl_thb"]
            for trade in trades
        ),
    }


def calculate_loss_streak_v52(trades):
    current = 0
    maximum = 0

    for trade in trades:
        if trade["net_pnl_thb"] < 0:
            current += 1
            maximum = max(
                maximum,
                current,
            )
        else:
            current = 0

    return maximum


def main():
    print("=" * 72)
    print("GROQ CONTINUOUS RISK COMPOUNDING V5.2")
    print("=" * 72)
    print(f"Symbol          : {SYMBOL}")
    print(f"Interval        : {INTERVAL}")
    print(f"Requested       : {CANDLE_LIMIT:,}")
    print(
        f"Starting Pot    : "
        f"{STARTING_POT_THB:,.2f} THB"
    )
    print(
        f"Research Cost   : "
        f"{ROUND_TRIP_COST * 100:.4f}% round trip"
    )
    print(
        f"Reference FX    : "
        f"{REFERENCE_USDTHB:.2f} THB/USDT"
    )
    print("AI              : NOT USED")
    print("Risk Manager     : REAL")
    print("Position overlap : BLOCKED")
    print("Execution        : NONE")
    print("Paper DB         : NOT USED")
    print("=" * 72)

    print("Fetching historical candles...")

    try:
        candles = fetch_closed_candles_paginated(
            SYMBOL,
            INTERVAL,
            CANDLE_LIMIT,
        )
    except HTTPError as exc:
        print("RESULT: STOPPED")
        print(
            f"Reason: BINANCE_HTTP_ERROR_{exc.code}"
        )
        return
    except (URLError, TimeoutError) as exc:
        print("RESULT: STOPPED")
        print(
            "Reason: BINANCE_CONNECTION_ERROR_"
            f"{type(exc).__name__}"
        )
        return

    print(
        f"Actual candles returned: "
        f"{len(candles):,}"
    )

    if not candles:
        print("RESULT: STOPPED")
        print("Reason: NO_CANDLES")
        return

    print(
        "First candle:",
        candles[0]["time"],
    )
    print(
        "Last candle :",
        candles[-1]["time"],
    )

    candidates = find_candidates(candles)

    print(
        f"Money Maker candidates: "
        f"{len(candidates)}"
    )

    records = build_trade_records(
        candidates,
        candles,
    )

    print(
        f"Resolved trade outcomes: "
        f"{len(records)}"
    )

    if not records:
        print("RESULT: STOPPED")
        print("Reason: NO_RESOLVED_TRADES")
        return

    trades, skipped_overlapping = (
        simulate_continuous_risk_compounding(
            records,
            STARTING_POT_THB,
        )
    )

    if not trades:
        print("RESULT: STOPPED")
        print("Reason: NO_RISK_APPROVED_TRADES")
        return

    final_pot = trades[-1][
        "pot_after_thb"
    ]

    stats = calculate_trade_stats(
        trades
    )

    drawdown = calculate_risk_drawdown(
        trades,
        STARTING_POT_THB,
    )

    max_loss_streak = (
        calculate_loss_streak_v52(
            trades
        )
    )

    net_profit = (
        final_pot
        - STARTING_POT_THB
    )

    total_return_pct = (
        net_profit
        / STARTING_POT_THB
        * 100.0
    )

    output = {
        "research_version": RESEARCH_VERSION,
        "generated_at": datetime.now(
            timezone.utc
        ).isoformat(),
        "symbol": SYMBOL,
        "interval": INTERVAL,
        "requested_candle_limit": CANDLE_LIMIT,
        "actual_candles": len(candles),
        "first_candle": candles[
            0
        ]["time"].isoformat(),
        "last_candle": candles[
            -1
        ]["time"].isoformat(),
        "starting_pot_thb": STARTING_POT_THB,
        "reference_usdthb": REFERENCE_USDTHB,
        "research_cost_round_trip": (
            ROUND_TRIP_COST
        ),
        "candidates_found": len(
            candidates
        ),
        "resolved_trade_outcomes": len(
            records
        ),
        "risk_approved_trades": len(
            trades
        ),
        "skipped_overlapping": (
            skipped_overlapping
        ),
        "trade_stats": stats,
        "ending_pot_thb": final_pot,
        "net_profit_thb": net_profit,
        "total_return_pct": (
            total_return_pct
        ),
        "max_drawdown": drawdown,
        "max_loss_streak": (
            max_loss_streak
        ),
        "trades": trades,
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
    print("V5.2 CONTINUOUS COMPOUNDING RESULT")
    print("=" * 72)
    print(
        f"Starting Pot : "
        f"{STARTING_POT_THB:,.2f} THB"
    )
    print(
        f"Ending Pot   : "
        f"{final_pot:,.2f} THB"
    )
    print(
        f"Net Profit   : "
        f"{net_profit:,.2f} THB"
    )
    print(
        f"Return       : "
        f"{total_return_pct:.4f}%"
    )
    print(
        f"Candidates   : "
        f"{len(candidates)}"
    )
    print(
        f"Trades       : "
        f"{len(trades)}"
    )
    print(
        f"Skipped Overlap : "
        f"{skipped_overlapping}"
    )
    print(
        f"Win Rate     : "
        f"{stats['win_rate']:.2f}%"
    )
    print(
        f"Gross P/L    : "
        f"{stats['total_gross_pnl_thb']:,.2f} THB"
    )
    print(
        f"Total Cost   : "
        f"{stats['total_cost_thb']:,.2f} THB"
    )
    print(
        f"Net P/L      : "
        f"{stats['total_net_pnl_thb']:,.2f} THB"
    )
    print(
        f"Max DD       : "
        f"{drawdown['max_drawdown_pct']:.4f}%"
    )
    print(
        f"Loss Streak  : "
        f"{max_loss_streak}"
    )
    print("=" * 72)
    print("Saved:", OUTPUT_FILE)


if __name__ == "__main__":
    main()
