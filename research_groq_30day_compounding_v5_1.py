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
    "research_groq_30day_compounding_v5_1_results.json"
)

RESEARCH_VERSION = "GROQ_30DAY_ROLLING_COMPOUNDING_V5_1"


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


def simulate_30day_windows(records, starting_pot):
    if not records:
        return []

    from datetime import timedelta

    first_time = records[0]["entry_time"]
    last_time = records[-1]["planned_exit_time"]

    windows = []
    window_start = first_time

    while window_start <= last_time:
        window_end = window_start + timedelta(days=30)

        window_records = [
            record
            for record in records
            if record["entry_time"] >= window_start
            and record["planned_exit_time"] < window_end
        ]

        if window_records:
            trades, equity_curve = simulate_compounding(
                window_records,
                starting_pot,
            )

            if trades:
                ending_pot = trades[-1]["pot_after_thb"]
                summary = calculate_trade_summary(trades)
                drawdown = calculate_drawdown(equity_curve)

                windows.append(
                    {
                        "window_start": window_start.isoformat(),
                        "window_end": window_end.isoformat(),
                        "starting_pot_thb": starting_pot,
                        "ending_pot_thb": ending_pot,
                        "net_profit_thb": (
                            ending_pot - starting_pot
                        ),
                        "return_pct": (
                            (ending_pot - starting_pot)
                            / starting_pot
                            * 100.0
                        ),
                        "trades": len(trades),
                        "win_rate": summary["win_rate"],
                        "max_drawdown_pct": drawdown[
                            "max_drawdown_pct"
                        ],
                        "max_loss_streak": calculate_loss_streak(
                            trades
                        ),
                    }
                )

        window_start = window_end

    return windows


def main():
    print("=" * 72)
    print("GROQ 30-DAY ROLLING FULL-POT COMPOUNDING V5.1")
    print("=" * 72)
    print(f"Symbol          : {SYMBOL}")
    print(f"Interval        : {INTERVAL}")
    print(f"Requested       : {CANDLE_LIMIT:,}")
    print(f"Starting Pot    : {STARTING_POT_THB:,.2f} THB")
    print(
        f"Research Cost   : "
        f"{ROUND_TRIP_COST * 100:.4f}% round trip"
    )
    print("AI              : NOT USED")
    print("Execution       : NONE")
    print("Paper DB        : NOT USED")
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
        print(f"Reason: BINANCE_HTTP_ERROR_{exc.code}")
        return
    except (URLError, TimeoutError) as exc:
        print("RESULT: STOPPED")
        print(
            "Reason: BINANCE_CONNECTION_ERROR_"
            f"{type(exc).__name__}"
        )
        return

    print(
        f"Actual candles returned: {len(candles):,}"
    )

    if not candles:
        print("RESULT: STOPPED")
        print("Reason: NO_CANDLES")
        return

    print("First candle:", candles[0]["time"])
    print("Last candle :", candles[-1]["time"])

    candidates = find_candidates(candles)

    print(
        f"Money Maker candidates: {len(candidates)}"
    )

    records = build_trade_records(
        candidates,
        candles,
    )

    print(
        f"Resolved trade outcomes: {len(records)}"
    )

    if not records:
        print("RESULT: STOPPED")
        print("Reason: NO_RESOLVED_TRADES")
        return

    windows = simulate_30day_windows(
        records,
        STARTING_POT_THB,
    )

    if not windows:
        print("RESULT: STOPPED")
        print("Reason: NO_30DAY_WINDOWS")
        return

    best = max(
        windows,
        key=lambda x: x["return_pct"],
    )

    worst = min(
        windows,
        key=lambda x: x["return_pct"],
    )

    sorted_returns = sorted(
        x["return_pct"]
        for x in windows
    )

    median_return = sorted_returns[
        len(sorted_returns) // 2
    ]

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
        "research_cost_round_trip": ROUND_TRIP_COST,
        "candidates_found": len(candidates),
        "resolved_trades": len(records),
        "windows_count": len(windows),
        "best_30day": best,
        "median_30day_return_pct": median_return,
        "worst_30day": worst,
        "windows": windows,
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
    print("30-DAY WINDOW RESULT")
    print("=" * 72)
    print(f"Windows analyzed : {len(windows)}")

    print("\nBEST 30-DAY WINDOW")
    print(
        f"Period      : "
        f"{best['window_start']} -> "
        f"{best['window_end']}"
    )
    print(
        f"Ending Pot  : "
        f"{best['ending_pot_thb']:,.2f} THB"
    )
    print(
        f"Return      : "
        f"{best['return_pct']:.4f}%"
    )
    print(
        f"Trades      : "
        f"{best['trades']}"
    )
    print(
        f"Win Rate    : "
        f"{best['win_rate']:.2f}%"
    )
    print(
        f"Max DD      : "
        f"{best['max_drawdown_pct']:.4f}%"
    )

    print("\nMEDIAN 30-DAY RETURN")
    print(
        f"{median_return:.4f}%"
    )

    print("\nWORST 30-DAY WINDOW")
    print(
        f"Period      : "
        f"{worst['window_start']} -> "
        f"{worst['window_end']}"
    )
    print(
        f"Ending Pot  : "
        f"{worst['ending_pot_thb']:,.2f} THB"
    )
    print(
        f"Return      : "
        f"{worst['return_pct']:.4f}%"
    )
    print(
        f"Trades      : "
        f"{worst['trades']}"
    )
    print(
        f"Win Rate    : "
        f"{worst['win_rate']:.2f}%"
    )
    print(
        f"Max DD      : "
        f"{worst['max_drawdown_pct']:.4f}%"
    )

    print("=" * 72)
    print("Saved:", OUTPUT_FILE)


if __name__ == "__main__":
    main()
