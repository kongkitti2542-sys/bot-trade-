import tempfile
from pathlib import Path

import database
from fx_provider import get_usdthb
from paper_capital_adapter import PaperCapitalAdapter
from paper_trader import PaperTrader


THB_CAPITAL = 1500.0

original_db = database.DB_PATH

with tempfile.TemporaryDirectory() as tmp:
    database.DB_PATH = Path(tmp) / "paper_thb_flow.db"

    fx = get_usdthb()
    adapter = PaperCapitalAdapter(
        thb_budget=THB_CAPITAL,
        usdthb=fx["usdthb"],
    )

    trader = PaperTrader(
        starting_capital=adapter.usdt_budget
    )

    print("PAPER THB → USDT FLOW TEST")
    print("=" * 60)
    print("FX:", fx["usdthb"])
    print("Rate Date:", fx["rate_date"])
    print("THB Capital:", THB_CAPITAL)
    print("USDT Capital:", round(adapter.usdt_budget, 8))
    print("Trader Capital:", round(trader.capital, 8))

    assert abs(trader.capital - adapter.usdt_budget) < 1e-9
    assert trader.position is None

    print()
    print("PASS: THB CAPITAL ENTERS PAPER TRADER AS USDT")

database.DB_PATH = original_db
