"""
Research Standard V1

Locked research-window standard for the personal trading bot.

BTCUSDT 5m:
    7D  = 2,016 closed candles
    30D = 8,640 closed candles

100K historical datasets remain DISCOVERY_ONLY
and are not part of the standard validation protocol.
"""

STANDARD_VERSION = "RESEARCH_STANDARD_V1"

SYMBOL = "BTCUSDT"
INTERVAL = "5m"

CANDLES_PER_HOUR = 12
HOURS_PER_DAY = 24

WINDOW_7D_DAYS = 7
WINDOW_30D_DAYS = 30

WINDOW_7D_CANDLES = (
    CANDLES_PER_HOUR
    * HOURS_PER_DAY
    * WINDOW_7D_DAYS
)

WINDOW_30D_CANDLES = (
    CANDLES_PER_HOUR
    * HOURS_PER_DAY
    * WINDOW_30D_DAYS
)

DISCOVERY_CANDLE_LIMIT = 100_000
DISCOVERY_STATUS = "DISCOVERY_ONLY"

WINDOWS = {
    "7D": WINDOW_7D_CANDLES,
    "30D": WINDOW_30D_CANDLES,
}


def get_window_candles(window_name):
    if window_name not in WINDOWS:
        raise ValueError(
            f"Unsupported research window: {window_name}"
        )

    return WINDOWS[window_name]


def describe_window(window_name):
    candles = get_window_candles(window_name)

    return {
        "standard_version": STANDARD_VERSION,
        "symbol": SYMBOL,
        "interval": INTERVAL,
        "window": window_name,
        "candles": candles,
        "status": "STANDARD_VALIDATION",
    }


def validate_window_size(window_name, actual_candles):
    expected = get_window_candles(window_name)

    return {
        "valid": actual_candles == expected,
        "expected": expected,
        "actual": actual_candles,
        "window": window_name,
    }
