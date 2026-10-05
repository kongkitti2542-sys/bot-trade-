"""Research-only MONEY_MAKER_01 field test across multiple USDT markets.

Purpose:
- Determine whether current MONEY_MAKER_01 edge is BTC-specific or the setup itself.
- Keep MONEY_MAKER_01 entry rules EXACTLY unchanged.
- Compare BTCUSDT, ETHUSDT, BNBUSDT, SOLUSDT on identical research rules.

Rules:
- Spot Binance closed candles, 5m.
- Windows: 1D=288, 7D=2016, 30D=8640.
- H10 evaluation horizon.
- Starting Pot 1500 THB per symbol/window.
- Dynamic position sizing from current Pot.
- Profit/loss flows into next trade.
- Same 0.14% round-trip research cost.
- Overlap blocked.
- No AI, no Profit Lock, no Giveback, no regime filter, no quality gate.
- No production changes.
- This is a field diagnostic, not a production approval.
"""

import json
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from research_groq_30day_compounding_v5_2 import fetch_closed_candles_paginated
from validate_atr_expansion_ema50 import (
    ATR_PERIOD,
    ATR_LOOKBACK,
    FEE_PER_SIDE,
    SLIPPAGE_PER_SIDE,
    calculate_atr,
    calculate_ema,
    calculate_relative_volume,
)
from risk import evaluate_risk
from capital_config import REFERENCE_USDTHB

SYMBOLS = ("BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT")
INTERVAL = "5m"
WINDOWS = {"1D": 288, "7D": 2016, "30D": 8640}
HORIZON = 10
STARTING_POT_THB = 1500.0
ROUND_TRIP_COST = 2 * FEE_PER_SIDE + 2 * SLIPPAGE_PER_SIDE

BASE_ATR_EXPANSION = 1.25
BASE_RV_THRESHOLD = 1.50
EMA_PERIOD = 50
CANDLE_RANGE_ATR_MIN = 1.0

OUTPUT_FILE = Path("money_machine_v2/research/money_maker_01_field_test_v1.json")


def build_candidates(candles):
    atr = calculate_atr(candles)
    closes = [c["close"] for c in candles]
    ema50 = calculate_ema(closes, EMA_PERIOD)
    rv = calculate_relative_volume(candles)
    start = max(ATR_PERIOD + ATR_LOOKBACK, EMA_PERIOD)
    end = len(candles) - HORIZON - 2
    rows = []

    for i in range(start, max(start, end + 1)):
        if atr[i] is None or ema50[i] is None or rv[i] is None:
            continue
        recent = [atr[j] for j in range(i - ATR_LOOKBACK, i) if atr[j] is not None]
        if len(recent) != ATR_LOOKBACK:
            continue
        expansion = atr[i] / (sum(recent) / ATR_LOOKBACK)
        candle_range = candles[i]["high"] - candles[i]["low"]
        if candle_range <= 0:
            continue
        if not (
            expansion >= BASE_ATR_EXPANSION
            and candle_range >= atr[i] * CANDLE_RANGE_ATR_MIN
            and candles[i]["close"] > candles[i]["open"]
            and candles[i]["close"] > candles[i - 1]["close"]
            and rv[i] >= BASE_RV_THRESHOLD
            and candles[i]["close"] > ema50[i]
        ):
            continue
        rows.append({
            "signal_time": candles[i]["time"],
            "entry_time": candles[i + 1]["time"],
            "entry": candles[i + 1]["open"],
            "atr": atr[i],
        })
    return rows


def select_non_overlapping(candles, candidates):
    index = {c["time"]: i for i, c in enumerate(candles)}
    selected = []
    active_exit = -1
    skipped = 0
    for c in sorted(candidates, key=lambda x: x["entry_time"]):
        idx = index[c["entry_time"]]
        if idx < active_exit:
            skipped += 1
            continue
        selected.append((c, idx))
        active_exit = idx + HORIZON
    return selected, skipped


def position_value(candidate, pot):
    risk = evaluate_risk(
        decision={"signal": "BUY", "confidence": 0, "quality": "PASSED"},
        features={"close": candidate["entry"], "atr14": candidate["atr"]},
        capital=pot / REFERENCE_USDTHB,
        daily_pnl=0.0,
        open_positions=0,
    )
    if not risk.get("allowed"):
        raise RuntimeError(f"RISK_REJECTED: {risk.get('reason')}")
    return float(risk["position_value"]) * REFERENCE_USDTHB


def simulate(candles, candidates):
    selected, skipped = select_non_overlapping(candles, candidates)
    pot = STARTING_POT_THB
    trades = []
    daily = defaultdict(float)

    for n, (candidate, entry_idx) in enumerate(selected, 1):
        exit_idx = entry_idx + HORIZON
        if exit_idx >= len(candles):
            continue
        pv = position_value(candidate, pot)
        gross_return = (candles[exit_idx]["close"] - candidate["entry"]) / candidate["entry"]
        gross = pv * gross_return
        cost = pv * ROUND_TRIP_COST
        net = gross - cost
        pot += net
        day = candidate["entry_time"].date().isoformat()
        daily[day] += net
        trades.append({
            "trade_number": n,
            "entry_time": candidate["entry_time"].isoformat(),
            "exit_time": candles[exit_idx]["time"].isoformat(),
            "entry_price": candidate["entry"],
            "exit_price": candles[exit_idx]["close"],
            "net_pnl_thb": net,
            "pot_after_thb": pot,
        })

    wins = [t["net_pnl_thb"] for t in trades if t["net_pnl_thb"] > 0]
    losses = [t["net_pnl_thb"] for t in trades if t["net_pnl_thb"] < 0]
    gp = sum(wins)
    gl = abs(sum(losses))
    days = list(daily.values())

    return {
        "candidates": len(candidates),
        "trades": len(trades),
        "skipped_overlap": skipped,
        "wins": len(wins),
        "losses": len(losses),
        "win_rate_pct": (len(wins) / len(trades) * 100.0) if trades else 0.0,
        "profit_factor": (gp / gl) if gl else None,
        "net_profit_thb": pot - STARTING_POT_THB,
        "ending_pot_thb": pot,
        "active_days": len(days),
        "positive_days": sum(1 for x in days if x > 0),
        "positive_day_rate_pct": (sum(1 for x in days if x > 0) / len(days) * 100.0) if days else 0.0,
        "avg_daily_net_thb": (sum(days) / len(days)) if days else 0.0,
    }


def main():
    output = {
        "research_version": "MONEY_MAKER_01_FIELD_TEST_V1",
        "standard": {
            "symbols": list(SYMBOLS),
            "interval": INTERVAL,
            "windows": WINDOWS,
            "horizon_bars": HORIZON,
            "starting_pot_thb": STARTING_POT_THB,
            "round_trip_cost_pct": ROUND_TRIP_COST * 100.0,
            "position_size_policy": "DYNAMIC_FROM_CURRENT_POT",
            "pot_compounding": "PROFIT_AND_LOSS_FLOW_TO_NEXT_TRADE",
            "entry_rules": "EXACT_MONEY_MAKER_01_BASELINE",
            "entry_overlap": "BLOCKED",
            "lookahead_blocked": True,
            "ai_used": False,
            "regime_filter": False,
            "quality_gate": False,
            "production_changed": False,
        },
        "results": {},
    }

    for symbol in SYMBOLS:
        output["results"][symbol] = {}
        for window, limit in WINDOWS.items():
            print(f"Fetching {symbol} {window}...")
            candles = fetch_closed_candles_paginated(symbol, INTERVAL, limit)
            candidates = build_candidates(candles)
            output["results"][symbol][window] = simulate(candles, candidates)

    OUTPUT_FILE.write_text(json.dumps(output, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Saved: {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
