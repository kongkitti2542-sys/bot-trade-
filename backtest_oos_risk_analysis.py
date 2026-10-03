from datetime import datetime, timezone

from backtest_data_100k import get_historical_candles_100k, validate_candles
from backtest_oos_time_exit import (
    STARTING_CAPITAL,
    OOS_BOUNDARY,
    TEST_HOLDS,
    run_oos_backtest,
)


def calculate_risk_metrics(trades):
    realized = [
        t for t in trades
        if t["exit_reason"] != "BACKTEST_END"
    ]

    equity = STARTING_CAPITAL
    peak = equity
    max_drawdown = 0.0
    max_drawdown_pct = 0.0

    largest_win = None
    largest_loss = None

    current_loss_streak = 0
    max_loss_streak = 0

    for trade in realized:
        pnl = trade["pnl"]
        equity += pnl

        if largest_win is None or pnl > largest_win:
            largest_win = pnl

        if largest_loss is None or pnl < largest_loss:
            largest_loss = pnl

        if pnl < 0:
            current_loss_streak += 1
            max_loss_streak = max(
                max_loss_streak,
                current_loss_streak,
            )
        elif pnl > 0:
            current_loss_streak = 0

        if equity > peak:
            peak = equity

        drawdown = peak - equity

        if drawdown > max_drawdown:
            max_drawdown = drawdown

        if peak > 0:
            drawdown_pct = drawdown / peak * 100
            max_drawdown_pct = max(
                max_drawdown_pct,
                drawdown_pct,
            )

    return {
        "realized_trades": len(realized),
        "ending_equity": equity,
        "max_drawdown": max_drawdown,
        "max_drawdown_pct": max_drawdown_pct,
        "largest_win": largest_win or 0.0,
        "largest_loss": largest_loss or 0.0,
        "max_loss_streak": max_loss_streak,
    }


def calculate_period_breakdown(trades, boundary, end_time):
    realized = [
        t for t in trades
        if t["exit_reason"] != "BACKTEST_END"
        and t["entry_time"] >= boundary
        and t["entry_time"] <= end_time
    ]

    total_seconds = (
        end_time - boundary
    ).total_seconds()

    periods = []

    for period_index in range(4):
        start_ratio = period_index / 4
        end_ratio = (period_index + 1) / 4

        start = boundary + (
            end_time - boundary
        ) * start_ratio

        end = boundary + (
            end_time - boundary
        ) * end_ratio

        period_trades = [
            t for t in realized
            if (
                t["entry_time"] >= start
                and (
                    t["entry_time"] < end
                    or period_index == 3
                    and t["entry_time"] <= end
                )
            )
        ]

        wins = [
            t for t in period_trades
            if t["pnl"] > 0
        ]

        losses = [
            t for t in period_trades
            if t["pnl"] < 0
        ]

        gross_profit = sum(
            t["pnl"] for t in wins
        )

        gross_loss = abs(sum(
            t["pnl"] for t in losses
        ))

        profit_factor = (
            gross_profit / gross_loss
            if gross_loss > 0
            else None
        )

        periods.append({
            "index": period_index + 1,
            "start": start,
            "end": end,
            "trades": len(period_trades),
            "wins": len(wins),
            "losses": len(losses),
            "pnl": sum(
                t["pnl"] for t in period_trades
            ),
            "profit_factor": profit_factor,
        })

    return periods


def main():
    print("=" * 100)
    print("OOS RISK ANALYSIS")
    print("=" * 100)

    candles = get_historical_candles_100k(
        symbol="BTCUSDT",
        interval="5m",
        candles_needed=100_000,
    )

    valid, reason = validate_candles(candles)

    print(f"Candles:       {len(candles)}")
    print(f"Validation:    {valid}")
    print(f"Reason:        {reason}")

    if not valid:
        raise RuntimeError(
            f"Dataset validation failed: {reason}"
        )

    if not candles:
        raise RuntimeError("No candles returned.")

    boundary = datetime.fromisoformat(
        OOS_BOUNDARY
    )

    first_time = candles[0]["time"]
    last_time = candles[-1]["time"]

    print(f"First:         {first_time}")
    print(f"Last:          {last_time}")
    print(f"OOS Boundary:  {boundary}")
    print()

    for label, bars in TEST_HOLDS.items():
        capital, trades, risk_rejections = run_oos_backtest(
            candles,
            max_hold_bars=bars,
            boundary=boundary,
        )

        metrics = calculate_risk_metrics(trades)

        periods = calculate_period_breakdown(
            trades,
            boundary,
            last_time,
        )

        print("=" * 100)
        print(f"TIME EXIT {label} ({bars} bars)")
        print("=" * 100)

        print(f"Ending Equity:       ${metrics['ending_equity']:.2f}")
        print(f"Realized Trades:     {metrics['realized_trades']}")
        print(f"Max Drawdown:        ${metrics['max_drawdown']:.2f}")
        print(f"Max Drawdown %:      {metrics['max_drawdown_pct']:.2f}%")
        print(f"Largest Win:         ${metrics['largest_win']:.4f}")
        print(f"Largest Loss:        ${metrics['largest_loss']:.4f}")
        print(f"Max Loss Streak:     {metrics['max_loss_streak']}")
        print(f"Risk Rejections:     {risk_rejections}")
        print()

        print(
            f"{'Period':<8}"
            f"{'Start':<22}"
            f"{'End':<22}"
            f"{'Trades':>8}"
            f"{'Wins':>7}"
            f"{'Loss':>7}"
            f"{'P/L':>12}"
            f"{'PF':>9}"
        )

        print("-" * 100)

        for period in periods:
            pf = (
                f"{period['profit_factor']:.3f}"
                if period["profit_factor"] is not None
                else "N/A"
            )

            print(
                f"P{period['index']:<7}"
                f"{str(period['start']):<22}"
                f"{str(period['end']):<22}"
                f"{period['trades']:>8}"
                f"{period['wins']:>7}"
                f"{period['losses']:>7}"
                f"{period['pnl']:>12.3f}"
                f"{pf:>9}"
            )

        print()

    print("=" * 100)
    print("Research only. No Core files were modified.")
    print("=" * 100)


if __name__ == "__main__":
    main()
