from collections import defaultdict
from incremental_features import IncrementalFeatures
from regime import detect_regime
from strategy import analyze_market
from risk import evaluate_risk
from research_data_cache import load_candles

TEST_START = __import__("datetime").datetime.fromisoformat("2026-05-01T00:00:00+00:00")
TEST_END = __import__("datetime").datetime.fromisoformat("2026-10-01T00:00:00+00:00")
MAX_HOLD_BARS = 240
STARTING_CAPITAL = 1000.0

candles = load_candles("btc_usdt_5m_100k.json")
fe = IncrementalFeatures()
capital = STARTING_CAPITAL
position = None
rows = []

for i, candle in enumerate(candles):
    features = fe.update(candle)

    if i < 200:
        continue

    t = candle["time"]

    if t >= TEST_END:
        break

    if position is not None:
        position["bars"] += 1

        hit = (
            candle["low"] <= position["stop"]
            if position["side"] == "BUY"
            else candle["high"] >= position["stop"]
        )

        if hit:
            exit_price = position["stop"]
            pnl = (exit_price - position["entry"]) * position["size"]
            rows.append({**position, "exit": exit_price, "pnl": pnl, "exit_reason": "STOP_LOSS"})
            capital += pnl
            position = None
            continue

        if position["bars"] >= MAX_HOLD_BARS:
            exit_price = candle["close"]
            pnl = (exit_price - position["entry"]) * position["size"]
            rows.append({**position, "exit": exit_price, "pnl": pnl, "exit_reason": "TIME_EXIT"})
            capital += pnl
            position = None

        continue

    if t < TEST_START:
        continue

    regime = detect_regime(features)
    decision = analyze_market(features, regime)

    if decision["signal"] != "BUY":
        continue

    if regime != "TREND_UP":
        continue

    if not (60 <= decision["score"] <= 79):
        continue

    risk = evaluate_risk(
        decision,
        features,
        capital=capital,
        daily_pnl=0.0,
        open_positions=0,
    )

    if not risk["allowed"]:
        continue

    position = {
        "entry_time": t,
        "entry": features["close"],
        "size": risk["position_size"],
        "stop": risk["stop_loss"],
        "score": decision["score"],
        "rsi": features.get("rsi14"),
        "atr_pct": (
            features["atr14"] / features["close"]
            if features.get("atr14") and features.get("close")
            else None
        ),
        "relative_volume": features.get("relative_volume"),
        "structure": features.get("price_structure"),
        "regime": regime,
        "side": "BUY",
        "bars": 0,
    }

print("=" * 80)
print("ENTRY FEATURE ANALYSIS — TREND_UP + BUY")
print("=" * 80)
print("Trades:", len(rows))

def show(name, fn):
    vals = [x for x in rows if fn(x) is not None]
    if not vals:
        print(name, ": no data")
        return
    pnls = [x["pnl"] for x in vals]
    print(
        f"{name:20s} N={len(vals):3d} "
        f"W={sum(p > 0 for p in pnls):3d} "
        f"L={sum(p <= 0 for p in pnls):3d} "
        f"Gross=${sum(pnls):8.3f}"
    )

show("RSI < 60", lambda x: x["rsi"] if x["rsi"] is not None and x["rsi"] < 60 else None)
show("RSI 60-70", lambda x: x["rsi"] if x["rsi"] is not None and 60 <= x["rsi"] < 70 else None)
show("RSI 70+", lambda x: x["rsi"] if x["rsi"] is not None and x["rsi"] >= 70 else None)
show("RV < 1", lambda x: x["relative_volume"] if x["relative_volume"] is not None and x["relative_volume"] < 1 else None)
show("RV 1-2", lambda x: x["relative_volume"] if x["relative_volume"] is not None and 1 <= x["relative_volume"] < 2 else None)
show("RV 2+", lambda x: x["relative_volume"] if x["relative_volume"] is not None and x["relative_volume"] >= 2 else None)

print("=" * 80)
