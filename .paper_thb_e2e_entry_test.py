from pathlib import Path
from datetime import datetime, timezone
import database

TEST_DB = Path(".paper_thb_e2e_entry.db")
THB_CAPITAL = 1000.0
USDTHB = 33.515
USDT_CAPITAL = THB_CAPITAL / USDTHB

database.DB_PATH = TEST_DB
if TEST_DB.exists():
    TEST_DB.unlink()

database.initialize_database()

database.save_account_state(
    starting_capital=USDT_CAPITAL,
    capital=USDT_CAPITAL,
    daily_pnl=0.0,
    updated_at=datetime.now(timezone.utc).isoformat(),
)

import engine

def forced_buy_strategy(features, regime):
    return {
        "signal": "BUY",
        "score": 100,
        "confidence": 100,
        "regime": regime,
        "reasons": ["E2E_TEST_FORCE_BUY"],
        "warnings": [],
        "audit": {
            "raw_score": 100,
            "regime": regime,
            "regime_multiplier": 1.0,
            "final_score": 100,
            "base_signal": "BUY",
            "safety_override": None,
            "final_signal": "BUY",
        },
    }

engine.analyze_market = forced_buy_strategy

print("=" * 70)
print("E2E TEST: RISK APPROVED -> OPEN POSITION")
print("=" * 70)
print(f"DB: {TEST_DB}")
print(f"THB Capital: {THB_CAPITAL:.2f}")
print(f"USDT Capital: {USDT_CAPITAL:.8f}")
print()

engine.run_engine()

position = database.get_open_position()

print()
print("=" * 70)
print("ASSERTIONS")
print("=" * 70)

if position is None:
    print("FAIL: No open position was created")
    raise SystemExit(1)

required = (
    "symbol",
    "side",
    "entry_price",
    "position_size",
    "position_value",
    "stop_loss",
)

missing = [key for key in required if key not in position]

if missing:
    print(f"FAIL: Missing position fields: {missing}")
    raise SystemExit(1)

if position["side"] != "BUY":
    print(f"FAIL: Expected BUY, got {position['side']}")
    raise SystemExit(1)

if position["position_size"] <= 0:
    print("FAIL: Invalid position size")
    raise SystemExit(1)

if position["position_value"] <= 0:
    print("FAIL: Invalid position value")
    raise SystemExit(1)

if position["stop_loss"] <= 0:
    print("FAIL: Invalid stop loss")
    raise SystemExit(1)

print("PASS: Risk approved and position opened")
print(f"Side: {position['side']}")
print(f"Entry: {position['entry_price']}")
print(f"Size: {position['position_size']}")
print(f"Value: {position['position_value']}")
print(f"Stop Loss: {position['stop_loss']}")
print(f"Position ID: {position['id']}")
