"""Paper Team Continuous Watcher V1.

Continuous market monitoring for BTCUSDT 5m.

- Uses closed candles only.
- Processes each new closed candle once.
- Uses Money Maker #1 -> Money Team V1.
- Monitors an existing PaperTrader position through Position Manager.
- Execution is intentionally disabled in V1.
"""

import time

from data import get_closed_candles
from money_maker_01_adapter_v1 import find_candidates
from money_team_v1 import evaluate_candidate
from paper_trader import PaperTrader
from position_manager import monitor_position


WATCHER_VERSION = "PAPER_TEAM_WATCHER_CONTINUOUS_V1"
SYMBOL = "BTCUSDT"
INTERVAL = "5m"
CANDLE_LIMIT = 10000
POLL_SECONDS = 15


def _find_signal_candle(candles, signal_time):
    for candle in candles:
        if candle["time"] == signal_time:
            return candle
    return None


def _latest_candidate(candles):
    candidates = find_candidates(candles)

    if not candidates:
        return None

    return max(
        candidates,
        key=lambda item: item["signal_time"],
    )


def run_cycle(trader, processed_candle_time):
    candles = get_closed_candles(
        symbol=SYMBOL,
        interval=INTERVAL,
        limit=CANDLE_LIMIT,
    )

    if not candles:
        return processed_candle_time

    latest_candle = candles[-1]
    latest_time = latest_candle["time"]

    # No new closed candle.
    if processed_candle_time == latest_time:
        return processed_candle_time

    print()
    print("=" * 72)
    print("NEW CLOSED CANDLE")
    print("Time :", latest_time)
    print("Close:", latest_candle["close"])
    print("=" * 72)

    # Always monitor an existing position first.
    if trader.position is not None:
        triggered, result = monitor_position(
            trader=trader,
            current_price=latest_candle["close"],
        )

        print("POSITION MONITOR")
        print("Triggered:", triggered)
        print("Result   :", result)
        print("Capital  :", trader.capital)
        print("Daily P/L:", trader.daily_pnl)

        # One position is already handled. Do not evaluate a new entry.
        return latest_time

    candidate = _latest_candidate(candles)

    if candidate is None:
        print("RESULT: WAIT")
        print("Reason: NO_MONEY_MAKER_CANDIDATE")
        return latest_time

    if candidate["signal_time"] != latest_time:
        print("RESULT: WAIT")
        print("Reason: STALE_CANDIDATE")
        print("Candidate:", candidate["signal_time"])
        print("Latest   :", latest_time)
        print("AI call  : NOT RUN")
        print("Risk     : NOT RUN")
        print("Execution: NOT RUN")
        return latest_time

    signal_candle = _find_signal_candle(
        candles,
        candidate["signal_time"],
    )

    if signal_candle is None:
        print("RESULT: WAIT")
        print("Reason: SIGNAL_CANDLE_NOT_FOUND")
        return latest_time

    print("NEW CANDIDATE")
    print("Signal:", candidate["signal"])
    print("Setup :", candidate["setup"])
    print("Entry :", candidate["entry"])

    result = evaluate_candidate(
        candidate=candidate,
        signal_candle=signal_candle,
        capital=trader.capital,
        daily_pnl=trader.daily_pnl,
        open_positions=0,
    )

    print("AI decision:", result["ai"]["decision"])
    print("AI quality :", result["ai"]["quality"])
    print("AI source  :", result["ai"].get("source"))
    print("Risk       :", result["risk"])
    print("Final      :", result["final_decision"])
    print("Reason     :", result["final_reason"])
    print("Execution  : DISABLED")

    return latest_time


def main():
    print("=" * 72)
    print(WATCHER_VERSION)
    print("=" * 72)
    print(f"Market       : {SYMBOL} {INTERVAL}")
    print(f"Poll         : {POLL_SECONDS}s")
    print(f"Candles      : {CANDLE_LIMIT}")
    print("Execution    : DISABLED")
    print("Mode         : CONTINUOUS")
    print("Stop         : Ctrl+C")
    print("=" * 72)

    trader = PaperTrader()

    # Start from the current closed candle so an old historical candle
    # is not immediately treated as a new live signal.
    initial_candles = get_closed_candles(
        symbol=SYMBOL,
        interval=INTERVAL,
        limit=CANDLE_LIMIT,
    )

    if not initial_candles:
        print("No closed candles available.")
        return

    processed_candle_time = initial_candles[-1]["time"]

    print("Watcher started.")
    print("Baseline closed candle:", processed_candle_time)
    print("Paper position:", trader.position)

    try:
        while True:
            processed_candle_time = run_cycle(
                trader,
                processed_candle_time,
            )
            time.sleep(POLL_SECONDS)

    except KeyboardInterrupt:
        print()
        print("=" * 72)
        print("WATCHER STOPPED")
        print("=" * 72)
        print("Capital :", trader.capital)
        print("Daily P/L:", trader.daily_pnl)
        print("Position:", trader.position)


if __name__ == "__main__":
    main()
