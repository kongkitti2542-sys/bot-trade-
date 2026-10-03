from pathlib import Path
import database
from fx_provider import get_usdthb
from currency_layer import thb_to_usdt
from capital_config import STARTING_CAPITAL_THB


PAPER_DB = Path("paper_thb.db")
THB_CAPITAL = STARTING_CAPITAL_THB


def initialize_paper_account():
    fx = get_usdthb()

    database.DB_PATH = PAPER_DB
    database.initialize_database()

    account = database.get_account_state()

    if account is None:
        usdt_capital = thb_to_usdt(
            THB_CAPITAL,
            fx["usdthb"],
        )

        from datetime import datetime, timezone

        database.save_account_state(
            starting_capital=usdt_capital,
            capital=usdt_capital,
            daily_pnl=0.0,
            updated_at=datetime.now(timezone.utc).isoformat(),
        )

        account = database.get_account_state()

        print("PAPER ACCOUNT CREATED")
        print(f"THB Capital : {THB_CAPITAL:.2f}")
        print(f"USD/THB     : {fx['usdthb']}")
        print(f"Rate Date   : {fx['rate_date']}")
        print(f"USDT Capital: {usdt_capital:.8f}")

    else:
        print("PAPER ACCOUNT EXISTING")
        print(f"DB Capital  : {account['capital']:.8f} USDT")
        print(f"Daily P/L   : {account['daily_pnl']:.8f} USDT")

    return fx, account


def run():
    fx, account = initialize_paper_account()

    print()
    print("=" * 60)
    print("PERSONAL TRADING BOT - THB PAPER WRAPPER")
    print("=" * 60)
    print(f"Paper DB    : {database.DB_PATH.resolve()}")
    print(f"FX          : {fx['usdthb']}")
    print(f"Rate Date   : {fx['rate_date']}")
    print(f"Capital     : {account['capital']:.8f} USDT")
    print(f"Capital THB : {account['capital'] * fx['usdthb']:.2f}")
    print()

    import engine

    engine.run_engine()


if __name__ == "__main__":
    run()
