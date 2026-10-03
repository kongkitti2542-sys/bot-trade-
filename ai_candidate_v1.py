"""
AI Candidate Adapter V1

Research-only adapter.
Does not modify Strategy, Risk, Engine, or execution.
Only PASSED BUY/SELL decisions become AI candidates.
"""

REQUIRED_SIGNALS = {"BUY", "SELL"}
REQUIRED_QUALITY = "PASSED"


def build_candidate(features, decision, symbol, timeframe):
    """
    Convert an existing Quant decision + feature snapshot
    into a clean candidate payload for the AI Judge.

    Returns:
        dict for a valid BUY/SELL PASSED candidate
        None for WAIT/REJECTED/non-tradeable decisions
    """

    if not isinstance(features, dict):
        raise TypeError("features must be a dict")

    if not isinstance(decision, dict):
        raise TypeError("decision must be a dict")

    signal = decision.get("signal")
    quality = decision.get("quality")

    if signal not in REQUIRED_SIGNALS:
        return None

    if quality != REQUIRED_QUALITY:
        return None

    bollinger = features.get("bollinger")
    structure = features.get("structure")

    if not isinstance(bollinger, dict):
        raise ValueError("Missing bollinger feature data")

    if not isinstance(structure, dict):
        raise ValueError("Missing structure feature data")

    candidate = {
        "symbol": symbol,
        "timeframe": timeframe,
        "signal": signal,
        "quality": quality,
        "setup": decision.get("setup"),
        "regime": decision.get("regime"),
        "confidence": decision.get("confidence"),
        "reasons": list(decision.get("reasons") or []),
        "warnings": list(decision.get("warnings") or []),
        "market": {
            "time": features.get("time"),
            "price": features.get("close"),
            "ema20": features.get("ema20"),
            "ema50": features.get("ema50"),
            "ema200": features.get("ema200"),
            "trend": features.get("trend"),
            "rsi14": features.get("rsi14"),
            "atr14": features.get("atr14"),
            "relative_volume": features.get("relative_volume"),
            "structure": structure,
            "bollinger": bollinger,
        },
    }

    return candidate


if __name__ == "__main__":
    print("AI CANDIDATE ADAPTER V1")
    print("Status: READY")
    print("Core modified: NO")
