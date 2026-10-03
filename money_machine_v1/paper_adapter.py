def build_paper_decision(candidate, ai, risk):
    return {
        "score": None,
        "confidence": None,
        "regime": None,
        "reasons": [candidate["setup"], "AI_" + ai["decision"], "RISK_" + risk["reason"]],
    }
