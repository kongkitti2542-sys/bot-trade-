from datetime import datetime

from backtest_oos_time_exit import (
    get_historical_candles_100k,
    validate_candles,
    run_oos_backtest,
    CANDLES_NEEDED,
    OOS_BOUNDARY,
)

STARTING_CAPITAL = 1000.0
MAX_HOLD_BARS = 240
FEE_RATE = 0.0005


def group_stats(trades):
    if not trades:
        return {
            "count": 0,
            "gross_pnl": 0.0,
            "avg_pnl": 0.0,
            "wins": 0,
            "losses": 0,
            "turnover": 0.0,
            "fees": 0.0,
            "net_pnl": 0.0,
        }

    gross_pnl = 0.0
    turnover = 0.0
    fees = 0.0
    wins = 0
    losses = 0

    for t in trades:
        entry = t["entry_price"]
        exit_price = t["exit_price"]
        size = t["position_size"]

        gross_pnl += t["pnl"]

        trade_turnover = (
            entry * size +
            exit_price * size
        )

        trade_fees = trade_turnover * FEE_RATE

        turnover += trade_turnover
        fees += trade_fees

        if t["pnl"] > 0:
            wins += 1
        elif t["pnl"] < 0:
            losses += 1

    net_pnl = gross_pnl - fees

    return {
        "count": len(trades),
        "gross_pnl": gross_pnl,
        "avg_pnl": gross_pnl / len(trades),
        "wins": wins,
        "losses": losses,
        "turnover": turnover,
        "fees": fees,
        "net_pnl": net_pnl,
    }


def print_group(name, trades):
    s = group_stats(trades)

    print(f"\n{name}")
    print("-" * 72)
    print(f"Trades          : {s['count']}")
    print(f"Wins            : {s['wins']}")
    print(f"Losses          : {s['losses']}")
    print(f"Gross P/L       : ${s['gross_pnl']:.4f}")
    print(f"Avg P/L         : ${s['avg_pnl']:.6f}")
    print(f"Turnover        : ${s['turnover']:.4f}")
    print(f"Futures fees    : ${s['fees']:.4f}")
    print(f"Net P/L         : ${s['net_pnl']:.4f}")


def main():
    print("=" * 72)
    print("TRADE ECONOMICS ATTRIBUTION — OOS 20H")
    print("=" * 72)

    candles = get_historical_candles_100k(
        symbol="BTCUSDT",
        interval="5m",
        candles_needed=CANDLES_NEEDED,
    )

    validate_candles(candles)

    boundary = datetime.fromisoformat(
        OOS_BOUNDARY.replace("Z", "+00:00")
    )

    capital, trades, risk_rejections = run_oos_backtest(
        candles=candles,
        max_hold_bars=MAX_HOLD_BARS,
        boundary=boundary,
    )

    realized = [
        t for t in trades
        if t["exit_reason"] != "BACKTEST_END"
    ]

    print(f"\nStarting capital : ${STARTING_CAPITAL:.2f}")
    print(f"Ending capital   : ${capital:.4f}")
    print(f"Realized trades  : {len(realized)}")
    print(f"Risk rejections  : {risk_rejections}")

    print_group("ALL REALIZED", realized)

    for reason in ("STOP_LOSS", "TIME_EXIT"):
        print_group(
            f"EXIT REASON — {reason}",
            [t for t in realized if t["exit_reason"] == reason],
        )

    for side in ("BUY", "SELL"):
        print_group(
            f"SIDE — {side}",
            [t for t in realized if t["side"] == side],
        )

    print_group(
        "WINNERS",
        [t for t in realized if t["pnl"] > 0],
    )

    print_group(
        "LOSERS",
        [t for t in realized if t["pnl"] < 0],
    )

    print("\n" + "=" * 72)
    print("EXIT REASON × RESULT")
    print("=" * 72)

    for reason in ("STOP_LOSS", "TIME_EXIT"):
        subset = [
            t for t in realized
            if t["exit_reason"] == reason
        ]

        winners = [t for t in subset if t["pnl"] > 0]
        losers = [t for t in subset if t["pnl"] < 0]

        print(
            f"{reason:12s} | "
            f"Trades {len(subset):3d} | "
            f"W {len(winners):3d} | "
            f"L {len(losers):3d} | "
            f"Gross ${sum(t['pnl'] for t in subset):9.4f}"
        )

    print("\n" + "=" * 72)
    print("IMPORTANT")
    print("=" * 72)
    print(
        "This is research-only analysis. "
        "No strategy, risk, paper trader, or core file is modified."
    )


if __name__ == "__main__":
    main()
