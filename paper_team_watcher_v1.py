"""Paper Team Watcher V1 — One-shot research/paper monitor.

One cycle only.
Does not execute paper orders.
Processes each Money Maker signal_time only once within this run.
Uses closed candles only.
"""

from data import get_closed_candles
from money_maker_01_adapter_v1 import find_candidates
from money_team_v1 import evaluate_candidate
from paper_trader import PaperTrader


WATCHER_VERSION = "PAPER_TEAM_WATCHER_V1"
SYMBOL = "BTCUSDT"
INTERVAL = "5m"
CANDLE_LIMIT = 10000


def _find_signal_candle(candles, signal_time):
    for candle in candles:
        if candle["time"] == signal_time:
            return candle
    return None


def run_once():
    print("=" * 72)
    print(WATCHER_VERSION)
    print("=" * 72)
    print(f"Market       : {SYMBOL} {INTERVAL}")
    print(f"Candles      : {CANDLE_LIMIT}")
    print("Execution    : DISABLED")
    print("Mode         : ONE-SHOT")
    print()

    candles = get_closed_candles(
        symbol=SYMBOL,
        interval=INTERVAL,
        limit=CANDLE_LIMIT,
    )

    if not candles:
        print("RESULT: WAIT")
        print("Reason: NO_CLOSED_CANDLES")
        return

    latest_candle = candles[-1]

    print("Latest closed candle:", latest_candle["time"])
    print("Latest close:", latest_candle["close"])
    print()

    candidates = find_candidates(candles)

    if not candidates:
        print("RESULT: WAIT")
        print("Reason: NO_MONEY_MAKER_CANDIDATE")
        return

    # Only the newest candidate is relevant for a one-shot market check.
    candidate = max(
        candidates,
        key=lambda item: item["signal_time"],
    )

    if candidate["signal_time"] != latest_candle["time"]:
        print("RESULT: WAIT")
        print("Reason: STALE_CANDIDATE")
        print("Candidate time:", candidate["signal_time"])
        print("Latest candle :", latest_candle["time"])
        print("AI call       : NOT RUN")
        print("Risk          : NOT RUN")
        print("Execution     : NOT RUN")
        return

    signal_candle = _find_signal_candle(
        candles,
        candidate["signal_time"],
    )

    if signal_candle is None:
        print("RESULT: WAIT")
        print("Reason: SIGNAL_CANDLE_NOT_FOUND")
        return

    print("Candidate signal:", candidate["signal_time"])
    print("Candidate signal:", candidate["signal"])
    print("Candidate setup :", candidate["setup"])
    print("Candidate entry :", candidate["entry"])
    print()

    trader = PaperTrader()

    if trader.position is not None:
        print("RESULT: WAIT")
        print("Reason: POSITION_ALREADY_OPEN")
        print("Execution: NOT RUN")
        return

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
    print()

    print("PAPER EXECUTION: NOT RUN")
    print("Position after check:", trader.position)


if __name__ == "__main__":
    run_once()
