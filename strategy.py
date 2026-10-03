from data import get_closed_candles
from features import calculate_features
from regime import detect_regime


TRADEABLE_REGIMES = {
    "TREND_UP",
    "TREND_DOWN",
    "BREAKOUT_UP",
    "BREAKOUT_DOWN",
}

PULLBACK_LOOKBACK = 5


def _result(
    signal,
    quality,
    setup,
    regime,
    reasons,
    warnings=None,
    confidence=0,
):
    warnings = warnings or []

    return {
        "signal": signal,
        "score": 0,  # Compatibility only. Not used as a decision gate.
        "confidence": confidence,
        "quality": quality,
        "setup": setup,
        "regime": regime,
        "reasons": reasons,
        "warnings": warnings,
        "audit": {
            "strategy_version": "QUALITY_V2",
            "raw_score": 0,
            "regime": regime,
            "regime_multiplier": 1.0,
            "final_score": 0,
            "base_signal": signal,
            "safety_override": None,
            "final_signal": signal,
            "setup": setup,
            "quality": quality,
        },
    }


def _trend_pullback(candles, direction, ema20, ema50):
    if len(candles) < PULLBACK_LOOKBACK + 2:
        return False, "Insufficient candle history for pullback"

    recent = candles[-(PULLBACK_LOOKBACK + 1):-1]
    current = candles[-1]

    if direction == "BUY":
        touched_ema20 = any(c["low"] <= ema20 for c in recent)
        recovery = current["close"] > recent[-1]["high"]
        held_ema50 = min(c["low"] for c in recent) > ema50

    else:
        touched_ema20 = any(c["high"] >= ema20 for c in recent)
        recovery = current["close"] < recent[-1]["low"]
        held_ema50 = max(c["high"] for c in recent) < ema50

    passed = touched_ema20 and recovery and held_ema50

    if passed:
        return True, "Pullback followed by directional recovery"

    return False, "Pullback/recovery confirmation failed"


def analyze_market(candles, features, regime):
    """
    Strategy V2 — Quality Trade

    Core setup:
        Trend Pullback / Recovery

    Secondary setup:
        Breakout

    This module decides trade quality only.
    Risk management remains outside this module.
    """

    if not candles:
        return _result(
            "WAIT",
            "REJECTED",
            None,
            regime,
            ["No candle history"],
        )

    price = features["close"]
    ema20 = features["ema20"]
    ema50 = features["ema50"]
    ema200 = features["ema200"]
    rsi = features["rsi14"]
    relative_volume = features["relative_volume"]
    bollinger = features["bollinger"]
    structure = features["structure"]

    required = [
        price,
        ema20,
        ema50,
        ema200,
        rsi,
        relative_volume,
        bollinger,
        structure,
    ]

    if not all(required):
        return _result(
            "WAIT",
            "REJECTED",
            None,
            regime,
            ["Insufficient feature data"],
        )

    if regime not in TRADEABLE_REGIMES:
        return _result(
            "WAIT",
            "REJECTED",
            None,
            regime,
            [f"Regime not tradeable: {regime}"],
        )

    if relative_volume < 0.5:
        return _result(
            "WAIT",
            "REJECTED",
            None,
            regime,
            ["Relative volume too weak"],
            ["Volume below 0.5x"],
        )

    # --------------------------------------------------
    # TREND — Core setup
    # --------------------------------------------------

    if regime == "TREND_UP":
        trend_alignment = (
            price > ema200
            and ema20 > ema50
            and structure["structure"] == "BULLISH"
        )

        if not trend_alignment:
            return _result(
                "WAIT",
                "REJECTED",
                "TREND",
                regime,
                ["Bullish trend alignment failed"],
            )

        if not (50 < rsi < 70):
            return _result(
                "WAIT",
                "REJECTED",
                "TREND",
                regime,
                ["Bullish momentum filter failed"],
                [f"RSI={rsi:.2f}"],
            )

        passed, reason = _trend_pullback(
            candles,
            "BUY",
            ema20,
            ema50,
        )

        if not passed:
            return _result(
                "WAIT",
                "REJECTED",
                "TREND",
                regime,
                [reason],
            )

        return _result(
            "BUY",
            "PASSED",
            "TREND_PULLBACK",
            regime,
            [
                "Bullish trend alignment",
                "Recent pullback detected",
                "Directional recovery confirmed",
                "RSI confirms momentum",
            ],
            confidence=100,
        )

    if regime == "TREND_DOWN":
        trend_alignment = (
            price < ema200
            and ema20 < ema50
            and structure["structure"] == "BEARISH"
        )

        if not trend_alignment:
            return _result(
                "WAIT",
                "REJECTED",
                "TREND",
                regime,
                ["Bearish trend alignment failed"],
            )

        if not (30 < rsi < 50):
            return _result(
                "WAIT",
                "REJECTED",
                "TREND",
                regime,
                ["Bearish momentum filter failed"],
                [f"RSI={rsi:.2f}"],
            )

        passed, reason = _trend_pullback(
            candles,
            "SELL",
            ema20,
            ema50,
        )

        if not passed:
            return _result(
                "WAIT",
                "REJECTED",
                "TREND",
                regime,
                [reason],
            )

        return _result(
            "SELL",
            "PASSED",
            "TREND_PULLBACK",
            regime,
            [
                "Bearish trend alignment",
                "Recent pullback detected",
                "Directional recovery confirmed",
                "RSI confirms momentum",
            ],
            confidence=100,
        )

    # --------------------------------------------------
    # BREAKOUT — Secondary setup
    # --------------------------------------------------

    if regime == "BREAKOUT_UP":
        confirmed = (
            price > bollinger["upper"]
            and relative_volume >= 1.5
            and structure["structure"] == "BULLISH"
            and 50 < rsi < 70
        )

        if not confirmed:
            return _result(
                "WAIT",
                "REJECTED",
                "BREAKOUT",
                regime,
                ["Bullish breakout confirmation failed"],
            )

        return _result(
            "BUY",
            "PASSED",
            "BREAKOUT",
            regime,
            [
                "Bullish breakout confirmed",
                "Price above Bollinger upper band",
                "Volume confirms breakout",
                "Bullish price structure",
                "Momentum not overextended",
            ],
            confidence=100,
        )

    if regime == "BREAKOUT_DOWN":
        confirmed = (
            price < bollinger["lower"]
            and relative_volume >= 1.5
            and structure["structure"] == "BEARISH"
            and 30 < rsi < 50
        )

        if not confirmed:
            return _result(
                "WAIT",
                "REJECTED",
                "BREAKOUT",
                regime,
                ["Bearish breakout confirmation failed"],
            )

        return _result(
            "SELL",
            "PASSED",
            "BREAKOUT",
            regime,
            [
                "Bearish breakout confirmed",
                "Price below Bollinger lower band",
                "Volume confirms breakout",
                "Bearish price structure",
                "Momentum not overextended",
            ],
            confidence=100,
        )

    return _result(
        "WAIT",
        "REJECTED",
        None,
        regime,
        ["No valid quality setup"],
    )


if __name__ == "__main__":
    candles = get_closed_candles(
        symbol="BTCUSDT",
        interval="5m",
        limit=250,
    )

    features = calculate_features(candles)
    regime = detect_regime(features)
    decision = analyze_market(
        candles,
        features,
        regime,
    )

    print()
    print("BTC/USDT - STRATEGY ENGINE V2")
    print("=" * 60)
    print(f"Price:      {features['close']:.2f}")
    print(f"Regime:     {decision['regime']}")
    print(f"Setup:      {decision['setup']}")
    print(f"Quality:    {decision['quality']}")
    print(f"Signal:     {decision['signal']}")
    print(f"Confidence: {decision['confidence']}/100")
    print()

    print("REASONS")
    print("-" * 60)
    for reason in decision["reasons"]:
        print(f"+ {reason}")

    print()
    print("WARNINGS")
    print("-" * 60)

    if decision["warnings"]:
        for warning in decision["warnings"]:
            print(f"! {warning}")
    else:
        print("None")
