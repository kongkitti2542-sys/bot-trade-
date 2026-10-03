from money_maker_01_adapter_v1 import find_candidates
from groq_judge_v1 import judge
from risk import evaluate_risk
from money_machine_v1.paper_adapter import build_paper_decision


def evaluate(candles, capital, daily_pnl=0.0, open_positions=0):
    candidates = find_candidates(candles)
    results = []
    for candidate in candidates:
        ai = judge(candidate)
        if ai.get("decision") != "PASS":
            results.append({"candidate": candidate, "ai": ai, "risk": None, "final_decision": "WAIT"})
            continue
        decision = {"signal": candidate["signal"], "confidence": 0, "quality": "PASSED"}
        features = {"close": candidate["entry"], "atr14": candidate["features"]["atr"]}
        risk = evaluate_risk(decision, features, capital=capital, daily_pnl=daily_pnl, open_positions=open_positions)
        results.append({"candidate": candidate, "ai": ai, "risk": risk, "final_decision": "RISK_APPROVED" if risk.get("allowed") else "WAIT", "paper_decision": build_paper_decision(candidate, ai, risk) if risk.get("allowed") else None})
    return results
