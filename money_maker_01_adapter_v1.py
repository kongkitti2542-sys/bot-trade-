"""Money Maker #1 adapter: ATR Expansion + EMA50.

Research/team adapter only.
Does not modify the locked validation source or execution components.
"""

from validate_atr_expansion_ema50 import (
    ATR_EXPANSION_MULTIPLIER,
    ATR_LOOKBACK,
    ATR_PERIOD,
    FEE_PER_SIDE,
    HORIZON,
    RV_THRESHOLD,
    SLIPPAGE_PER_SIDE,
    calculate_atr,
    calculate_ema,
    calculate_relative_volume,
)

NAME = "MONEY_MAKER_01"
SYMBOL = "BTCUSDT"
INTERVAL = "5m"
SIDE = "BUY"
SETUP = "ATR_EXPANSION_EMA50"


def find_candidates(candles):
    """Return candidates using the locked Money Maker #1 conditions."""
    atr = calculate_atr(candles)
    closes = [c["close"] for c in candles]
    ema50 = calculate_ema(closes, 50)
    relative_volume = calculate_relative_volume(candles)

    candidates = []
    start = max(ATR_PERIOD + ATR_LOOKBACK, 50)
    end = len(candles) - HORIZON - 1

    for i in range(start, end + 1):
        if atr[i] is None or ema50[i] is None or relative_volume[i] is None:
            continue

        recent_atr = [
            atr[j]
            for j in range(i - ATR_LOOKBACK, i)
            if atr[j] is not None
        ]

        if len(recent_atr) != ATR_LOOKBACK:
            continue

        avg_recent_atr = sum(recent_atr) / ATR_LOOKBACK
        expansion_ratio = atr[i] / avg_recent_atr
        candle_range = candles[i]["high"] - candles[i]["low"]

        bullish = candles[i]["close"] > candles[i]["open"]
        higher_close = candles[i]["close"] > candles[i - 1]["close"]
        volume_confirmed = relative_volume[i] >= RV_THRESHOLD
        above_ema50 = candles[i]["close"] > ema50[i]

        if not (
            expansion_ratio >= ATR_EXPANSION_MULTIPLIER
            and candle_range >= atr[i]
            and bullish
            and higher_close
            and volume_confirmed
            and above_ema50
        ):
            continue

        entry = candles[i + 1]["open"]
        reference_exit = candles[i + 1 + HORIZON]["close"]

        candidates.append(
            {
                "money_maker": NAME,
                "symbol": SYMBOL,
                "timeframe": INTERVAL,
                "signal": SIDE,
                "setup": SETUP,
                "signal_time": candles[i]["time"],
                "entry_time": candles[i + 1]["time"],
                "entry": entry,
                "planned_horizon_bars": HORIZON,
                "planned_exit_time": candles[i + 1 + HORIZON]["time"],
                "reference_exit": reference_exit,
                "features": {
                    "atr": atr[i],
                    "atr_expansion_ratio": expansion_ratio,
                    "candle_range": candle_range,
                    "relative_volume": relative_volume[i],
                    "ema50": ema50[i],
                    "ema50_distance": (candles[i]["close"] / ema50[i]) - 1,
                    "bullish": bullish,
                    "higher_close": higher_close,
                },
                "research_cost_round_trip": (
                    2 * FEE_PER_SIDE + 2 * SLIPPAGE_PER_SIDE
                ),
            }
        )

    return candidates
