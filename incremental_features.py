from collections import deque
from features import calculate_features


class IncrementalFeatures:
    """
    Incremental implementation of the existing features.py calculations.

    Purpose:
    - Avoid recalculating the entire candle history every bar.
    - Preserve the existing indicator definitions.
    - Validate against calculate_features() before using in backtests.
    """

    def __init__(self):
        self.candles = deque(maxlen=1000)
        self.closes = deque(maxlen=1000)
        self.volumes = deque(maxlen=1000)

        self.ema20 = None
        self.ema50 = None
        self.ema200 = None

        self.rsi14 = None
        self.avg_gain = None
        self.avg_loss = None

        self.atr14 = None

        self._prev_close = None
        self._tr_values = deque(maxlen=14)

    @staticmethod
    def _ema_update(previous, price, period):
        multiplier = 2 / (period + 1)
        return (price - previous) * multiplier + previous

    def update(self, candle):
        self.candles.append(candle)

        close = candle["close"]
        volume = candle["volume"]

        self.closes.append(close)
        self.volumes.append(volume)

        # ---------------------------------------------------------
        # EMA
        # ---------------------------------------------------------
        if len(self.closes) == 20:
            self.ema20 = sum(list(self.closes)[-20:]) / 20
        elif len(self.closes) > 20:
            self.ema20 = self._ema_update(
                self.ema20,
                close,
                20,
            )

        if len(self.closes) == 50:
            self.ema50 = sum(list(self.closes)[-50:]) / 50
        elif len(self.closes) > 50:
            self.ema50 = self._ema_update(
                self.ema50,
                close,
                50,
            )

        if len(self.closes) == 200:
            self.ema200 = sum(list(self.closes)[-200:]) / 200
        elif len(self.closes) > 200:
            self.ema200 = self._ema_update(
                self.ema200,
                close,
                200,
            )

        # ---------------------------------------------------------
        # RSI 14
        # ---------------------------------------------------------
        if self._prev_close is not None:
            change = close - self._prev_close
            gain = max(change, 0)
            loss = max(-change, 0)

            if len(self.closes) == 15:
                gains = []
                losses = []

                close_list = list(self.closes)

                for i in range(1, len(close_list)):
                    delta = close_list[i] - close_list[i - 1]
                    gains.append(max(delta, 0))
                    losses.append(max(-delta, 0))

                self.avg_gain = sum(gains[:14]) / 14
                self.avg_loss = sum(losses[:14]) / 14

            elif len(self.closes) > 15:
                self.avg_gain = (
                    (self.avg_gain * 13) + gain
                ) / 14

                self.avg_loss = (
                    (self.avg_loss * 13) + loss
                ) / 14

            if self.avg_loss is not None:
                if self.avg_loss == 0:
                    self.rsi14 = 100.0
                else:
                    rs = self.avg_gain / self.avg_loss
                    self.rsi14 = 100 - (100 / (1 + rs))

        self._prev_close = close

        # ---------------------------------------------------------
        # ATR 14
        # ---------------------------------------------------------
        if len(self.candles) >= 2:
            previous = list(self.candles)[-2]

            true_range = max(
                candle["high"] - candle["low"],
                abs(
                    candle["high"]
                    - previous["close"]
                ),
                abs(
                    candle["low"]
                    - previous["close"]
                ),
            )

            self._tr_values.append(true_range)

            if len(self._tr_values) == 14:
                self.atr14 = sum(self._tr_values) / 14
            elif len(self._tr_values) > 14:
                self.atr14 = sum(self._tr_values) / 14

        # ---------------------------------------------------------
        # Bollinger Bands
        # ---------------------------------------------------------
        bb = None

        if len(self.closes) >= 20:
            window = list(self.closes)[-20:]

            middle = sum(window) / 20

            variance = sum(
                (price - middle) ** 2
                for price in window
            ) / 20

            standard_deviation = variance ** 0.5

            upper = middle + 2 * standard_deviation
            lower = middle - 2 * standard_deviation

            width = (
                (upper - lower) / middle
                if middle != 0
                else 0
            )

            bb = {
                "middle": middle,
                "upper": upper,
                "lower": lower,
                "width": width,
            }

        # ---------------------------------------------------------
        # Relative Volume
        # ---------------------------------------------------------
        relative_volume = None

        if len(self.volumes) >= 21:
            volume_list = list(self.volumes)

            average_volume = (
                sum(volume_list[-21:-1]) / 20
            )

            if average_volume == 0:
                relative_volume = 0
            else:
                relative_volume = (
                    volume_list[-1] / average_volume
                )

        # ---------------------------------------------------------
        # Price Structure
        # ---------------------------------------------------------
        structure = None

        if len(self.candles) >= 10:
            candle_list = list(self.candles)

            previous = candle_list[-10:-5]
            current = candle_list[-5:]

            previous_high = max(
                c["high"] for c in previous
            )
            previous_low = min(
                c["low"] for c in previous
            )

            current_high = max(
                c["high"] for c in current
            )
            current_low = min(
                c["low"] for c in current
            )

            higher_high = current_high > previous_high
            higher_low = current_low > previous_low
            lower_high = current_high < previous_high
            lower_low = current_low < previous_low

            if higher_high and higher_low:
                structure_name = "BULLISH"
            elif lower_high and lower_low:
                structure_name = "BEARISH"
            else:
                structure_name = "MIXED"

            structure = {
                "higher_high": higher_high,
                "higher_low": higher_low,
                "lower_high": lower_high,
                "lower_low": lower_low,
                "structure": structure_name,
            }

        # ---------------------------------------------------------
        # Trend
        # ---------------------------------------------------------
        if (
            self.ema20 is not None
            and self.ema50 is not None
            and self.ema200 is not None
        ):
            if (
                self.ema20
                > self.ema50
                > self.ema200
            ):
                trend = "UP"
            elif (
                self.ema20
                < self.ema50
                < self.ema200
            ):
                trend = "DOWN"
            else:
                trend = "MIXED"
        else:
            trend = "UNKNOWN"

        return {
            "time": candle["time"],
            "close": close,
            "ema20": self.ema20,
            "ema50": self.ema50,
            "ema200": self.ema200,
            "trend": trend,
            "rsi14": self.rsi14,
            "atr14": self.atr14,
            "bollinger": bb,
            "relative_volume": relative_volume,
            "structure": structure,
        }


def compare_values(name, original, incremental, tolerance=1e-9):
    if original is None or incremental is None:
        return original == incremental

    return abs(original - incremental) <= tolerance


def compare_features(original, incremental):
    checks = []

    numeric_fields = [
        "close",
        "ema20",
        "ema50",
        "ema200",
        "rsi14",
        "atr14",
        "relative_volume",
    ]

    for field in numeric_fields:
        checks.append(
            (
                field,
                compare_values(
                    field,
                    original[field],
                    incremental[field],
                ),
            )
        )

    checks.append(
        (
            "trend",
            original["trend"] == incremental["trend"],
        )
    )

    if original["bollinger"] is None:
        checks.append(
            (
                "bollinger",
                incremental["bollinger"] is None,
            )
        )
    else:
        for field in [
            "middle",
            "upper",
            "lower",
            "width",
        ]:
            checks.append(
                (
                    f"bollinger.{field}",
                    compare_values(
                        field,
                        original["bollinger"][field],
                        incremental["bollinger"][field],
                    ),
                )
            )

    if original["structure"] is None:
        checks.append(
            (
                "structure",
                incremental["structure"] is None,
            )
        )
    else:
        checks.append(
            (
                "structure",
                original["structure"]
                == incremental["structure"],
            )
        )

    return checks


def main():
    from backtest_data_100k import (
        get_historical_candles_100k,
        validate_candles,
    )

    print("=" * 70)
    print("INCREMENTAL FEATURE VALIDATION")
    print("=" * 70)

    candles = get_historical_candles_100k(
        symbol="BTCUSDT",
        interval="5m",
        candles_needed=100_000,
    )

    valid, reason = validate_candles(candles)

    print(f"Candles:     {len(candles)}")
    print(f"Validation:  {valid}")
    print(f"Reason:      {reason}")

    if not valid:
        raise RuntimeError(reason)

    engine = IncrementalFeatures()

    checkpoints = {
        200,
        500,
        1000,
        5000,
        10000,
        25000,
        50000,
        75000,
        len(candles) - 1,
    }

    failures = 0

    for index, candle in enumerate(candles):
        incremental = engine.update(candle)

        if index not in checkpoints:
            continue

        original = calculate_features(
            candles[:index + 1]
        )

        checks = compare_features(
            original,
            incremental,
        )

        failed = [
            name
            for name, passed in checks
            if not passed
        ]

        if failed:
            failures += 1

            print()
            print(f"CHECKPOINT {index}: FAIL")
            print("Fields:", ", ".join(failed))

            for field in failed:
                if field in incremental:
                    print(
                        f"{field}: "
                        f"original={original[field]} "
                        f"incremental={incremental[field]}"
                    )
        else:
            print(
                f"Checkpoint {index:>6}: PASS"
            )

    print()
    print("=" * 70)

    if failures == 0:
        print("VALIDATION RESULT: PASS")
        print("Incremental features match the existing features.py.")
    else:
        print(
            f"VALIDATION RESULT: FAIL "
            f"({failures} checkpoint(s))"
        )

    print("=" * 70)


if __name__ == "__main__":
    main()
