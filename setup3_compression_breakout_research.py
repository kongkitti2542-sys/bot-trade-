"""Research-only: Setup 3 Volatility Compression Breakout.

Baseline hypothesis:
Compression -> breakout -> volume expansion.

Signal is evaluated at candle close; entry is next candle open.
Research only. Does not modify Core strategy/risk/execution/database files.
"""

import numpy as np

from backtest_data_100k import get_historical_candles_100k, validate_candles


SYMBOL = "BTCUSDT"
INTERVAL = "5m"
CANDLES_NEEDED = 100_000
OOS_BOUNDARY = "2026-07-21T10:05:00+00:00"
STARTING_CAPITAL_USDT = 44.669446

COMPRESSION_BARS = 10
BREAKOUT_LOOKBACK = 20
ATR_N = 14
RELVOL_N = 20

COMPRESSION_RATIO = 0.70
RELVOL_MIN = 1.50

SL_ATR = 0.50
TP_R = 1.50
MAX_HOLD_BARS = 48

FEE_RATE = 0.0005
SLIPPAGE_RATES = {
    "0.00%": 0.0,
    "0.02%": 0.0002,
    "0.05%": 0.0005,
}


def _atr(high, low, close, period):
    high = np.asarray(high, dtype=float)
    low = np.asarray(low, dtype=float)
    close = np.asarray(close, dtype=float)

    if len(close) == 0:
        return np.array([], dtype=float)

    prev_close = np.empty_like(close)
    prev_close[0] = close[0]
    prev_close[1:] = close[:-1]

    tr = np.maximum(
        high - low,
        np.maximum(
            np.abs(high - prev_close),
            np.abs(low - prev_close),
        ),
    )

    atr = np.full(len(tr), np.nan)

    if len(tr) >= period:
        atr[period - 1] = np.mean(tr[:period])

        for i in range(period, len(tr)):
            atr[i] = (
                atr[i - 1] * (period - 1) + tr[i]
            ) / period

    return atr


def prepare(candles):
    n = len(candles)

    open_ = np.array([float(c["open"]) for c in candles])
    high = np.array([float(c["high"]) for c in candles])
    low = np.array([float(c["low"]) for c in candles])
    close = np.array([float(c["close"]) for c in candles])
    volume = np.array([float(c["volume"]) for c in candles])

    atr = _atr(high, low, close, ATR_N)

    signal = np.zeros(n, dtype=int)

    for i in range(
        max(ATR_N, RELVOL_N, BREAKOUT_LOOKBACK + COMPRESSION_BARS),
        n,
    ):
        compression_start = i - COMPRESSION_BARS
        compression_end = i

        previous_start = i - BREAKOUT_LOOKBACK
        previous_end = i - COMPRESSION_BARS

        compressed_high = np.max(
            high[compression_start:compression_end]
        )
        compressed_low = np.min(
            low[compression_start:compression_end]
        )

        compressed_range = (
            compressed_high - compressed_low
        )

        previous_high = np.max(
            high[previous_start:previous_end]
        )
        previous_low = np.min(
            low[previous_start:previous_end]
        )

        previous_range = previous_high - previous_low

        if previous_range <= 0:
            continue

        compression_ok = (
            compressed_range
            <= previous_range * COMPRESSION_RATIO
        )

        avg_volume = np.mean(
            volume[i - RELVOL_N:i]
        )

        if avg_volume <= 0:
            continue

        relative_volume = volume[i] / avg_volume

        if not compression_ok:
            continue

        breakout_up = (
            close[i] > previous_high
            and relative_volume >= RELVOL_MIN
        )

        breakout_down = (
            close[i] < previous_low
            and relative_volume >= RELVOL_MIN
        )

        if breakout_up and not breakout_down:
            signal[i] = 1
        elif breakout_down and not breakout_up:
            signal[i] = -1

    return {
        "open": open_,
        "high": high,
        "low": low,
        "close": close,
        "volume": volume,
        "atr": atr,
        "signal": signal,
    }


def backtest(data, candles, boundary):
    boundary_ts = np.datetime64(boundary)

    trades = []

    i = max(
        ATR_N,
        RELVOL_N,
        BREAKOUT_LOOKBACK + COMPRESSION_BARS,
    )

    while i < len(candles) - 1:

        signal_time = np.datetime64(
            candles[i]["time"]
        )

        if (
            signal_time < boundary_ts
            or data["signal"][i] == 0
        ):
            i += 1
            continue

        side = int(data["signal"][i])

        entry_idx = i + 1
        entry = data["open"][entry_idx]
        atr = data["atr"][i]

        if not np.isfinite(atr) or atr <= 0:
            i += 1
            continue

        risk_distance = SL_ATR * atr

        if side == 1:
            stop = entry - risk_distance
            target = entry + risk_distance * TP_R
        else:
            stop = entry + risk_distance
            target = entry - risk_distance * TP_R

        end = min(
            entry_idx + MAX_HOLD_BARS,
            len(candles) - 1,
        )

        exit_price = None
        exit_reason = "TIME_EXIT"
        exit_idx = end

        for j in range(entry_idx, end + 1):

            high = data["high"][j]
            low = data["low"][j]

            # Same-bar collision: stop first.
            if side == 1:

                if low <= stop:
                    exit_price = stop
                    exit_reason = "STOP_LOSS"
                    exit_idx = j
                    break

                if high >= target:
                    exit_price = target
                    exit_reason = "TAKE_PROFIT"
                    exit_idx = j
                    break

            else:

                if high >= stop:
                    exit_price = stop
                    exit_reason = "STOP_LOSS"
                    exit_idx = j
                    break

                if low <= target:
                    exit_price = target
                    exit_reason = "TAKE_PROFIT"
                    exit_idx = j
                    break

        if exit_price is None:
            exit_price = data["close"][end]

        gross_return = (
            side
            * (exit_price - entry)
            / entry
        )

        trades.append(
            {
                "signal_idx": i,
                "entry_idx": entry_idx,
                "exit_idx": exit_idx,
                "signal_time": candles[i]["time"],
                "entry_time": candles[entry_idx]["time"],
                "exit_time": candles[exit_idx]["time"],
                "side": (
                    "BUY"
                    if side == 1
                    else "SELL"
                ),
                "entry_price": float(entry),
                "exit_price": float(exit_price),
                "stop_loss": float(stop),
                "take_profit": float(target),
                "bars_held": (
                    exit_idx - entry_idx
                ),
                "gross_return": float(
                    gross_return
                ),
                "exit_reason": exit_reason,
            }
        )

        # One position at a time.
        i = exit_idx + 1

    return trades


def stats(trades):

    if not trades:
        return {
            "n": 0,
            "wins": 0,
            "losses": 0,
            "gross": 0.0,
            "pf": None,
        }

    wins = [
        t for t in trades
        if t["gross_return"] > 0
    ]

    losses = [
        t for t in trades
        if t["gross_return"] < 0
    ]

    gross_profit = sum(
        t["gross_return"]
        for t in wins
    )

    gross_loss = abs(
        sum(
            t["gross_return"]
            for t in losses
        )
    )

    return {
        "n": len(trades),
        "wins": len(wins),
        "losses": len(losses),
        "gross": sum(
            t["gross_return"]
            for t in trades
        ),
        "pf": (
            gross_profit / gross_loss
            if gross_loss > 0
            else None
        ),
    }


def print_stats(name, trades):

    s = stats(trades)

    pf = (
        "N/A"
        if s["pf"] is None
        else f"{s['pf']:.4f}"
    )

    print(
        f"{name:<18} "
        f"N={s['n']:>4} "
        f"W={s['wins']:>4} "
        f"L={s['losses']:>4} "
        f"Gross={s['gross'] * 100:+.4f}% "
        f"PF={pf}"
    )


def apply_costs(
    trades,
    slippage_rate,
):

    net_return = 0.0
    fee_return = 0.0
    slippage_return = 0.0

    for t in trades:

        side = (
            1
            if t["side"] == "BUY"
            else -1
        )

        entry = t["entry_price"]
        exit_price = t["exit_price"]

        entry_exec = (
            entry
            * (1 + side * slippage_rate)
        )

        exit_exec = (
            exit_price
            * (1 - side * slippage_rate)
        )

        gross_after_slip = (
            side
            * (exit_exec - entry_exec)
            / entry_exec
        )

        fees = 2 * FEE_RATE

        net_return += (
            gross_after_slip - fees
        )

        fee_return += fees

        slippage_return += (
            abs(entry_exec - entry)
            / entry
            +
            abs(exit_exec - exit_price)
            / exit_price
        )

    return (
        net_return,
        fee_return,
        slippage_return,
    )


def run(candles):

    valid, reason = validate_candles(
        candles
    )

    print("=" * 100)
    print(
        "SETUP 3 — VOLATILITY COMPRESSION BREAKOUT"
    )
    print(
        "RESEARCH ONLY — NO CORE FILES MODIFIED"
    )
    print("=" * 100)

    print(
        f"Candles:        {len(candles)}"
    )
    print(
        f"Validation:     {valid}"
    )
    print(
        f"Reason:         {reason}"
    )
    print(
        f"OOS Boundary:   {OOS_BOUNDARY}"
    )
    print(
        f"Starting Pot:   ${STARTING_CAPITAL_USDT:.4f}"
    )
    print(
        f"Compression:    {COMPRESSION_BARS} bars"
    )
    print(
        f"Breakout:       {BREAKOUT_LOOKBACK} bars"
    )
    print(
        f"Compression:    <= {COMPRESSION_RATIO:.2f}"
        " of prior range"
    )
    print(
        f"Rel Volume:     >= {RELVOL_MIN:.2f}"
    )
    print(
        f"SL:             {SL_ATR:.2f} ATR"
    )
    print(
        f"TP:             {TP_R:.2f}R"
    )
    print(
        f"Max Hold:       {MAX_HOLD_BARS} bars / 4h"
    )

    if not valid:
        raise RuntimeError(
            f"Dataset validation failed: {reason}"
        )

    data = prepare(candles)

    trades = backtest(
        data,
        candles,
        OOS_BOUNDARY,
    )

    if not trades:
        print("No trades.")
        return

    split = len(trades) // 2

    first_half = trades[:split]
    second_half = trades[split:]

    print()
    print("=" * 100)
    print("RESULT")
    print("=" * 100)

    print_stats(
        "ALL OOS",
        trades,
    )

    print_stats(
        "FIRST HALF",
        first_half,
    )

    print_stats(
        "SECOND HALF",
        second_half,
    )

    print_stats(
        "LONG",
        [
            t for t in trades
            if t["side"] == "BUY"
        ],
    )

    print_stats(
        "SHORT",
        [
            t for t in trades
            if t["side"] == "SELL"
        ],
    )

    reasons = {}

    for t in trades:
        reasons[t["exit_reason"]] = (
            reasons.get(
                t["exit_reason"],
                0,
            )
            + 1
        )

    print(
        "Exit reasons:",
        reasons,
    )

    print(
        "Average bars held: "
        f"{sum(t['bars_held'] for t in trades) / len(trades):.2f}"
    )

    print()
    print("=" * 100)
    print("NET COST GATE")
    print("=" * 100)

    for name, slip in SLIPPAGE_RATES.items():

        net, fees, slippage = (
            apply_costs(
                trades,
                slip,
            )
        )

        final_pot = (
            STARTING_CAPITAL_USDT
            * (1 + net)
        )

        print(
            f"Slippage {name:<6} | "
            f"Final Pot ${final_pot:>10.4f} | "
            f"Net Return {net * 100:+.4f}% | "
            f"Fees(Return) {fees * 100:+.4f}% | "
            f"Slippage(Return) {slippage * 100:+.4f}%"
        )

    print()
    print("=" * 100)
    print("RESEARCH DECISION")
    print("=" * 100)

    net_002, _, _ = apply_costs(
        trades,
        0.0002,
    )

    second = stats(
        second_half
    )

    if (
        second["gross"] > 0
        and net_002 > 0
    ):
        print(
            "Candidate survives initial "
            "chronological/cost screen."
        )
    else:
        print(
            "Candidate fails initial "
            "chronological/cost screen — KILL."
        )

    print("=" * 100)


if __name__ == "__main__":

    candles = get_historical_candles_100k(
        symbol=SYMBOL,
        interval=INTERVAL,
        candles_needed=CANDLES_NEEDED,
    )

    run(candles)
