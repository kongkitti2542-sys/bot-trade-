from backtest_data_100k import (
    get_historical_candles_100k,
    validate_candles,
)
from incremental_features import IncrementalFeatures
from regime import detect_regime
from strategy import analyze_market
from risk import evaluate_risk

SYMBOL = "BTCUSDT"
INTERVAL = "5m"
CANDLES_NEEDED = 100_000
STARTING_CAPITAL = 1000.0
MAX_HOLD_BARS = 288


def close_position(position, exit_price, exit_time, exit_reason):
    if position["side"] == "BUY":
        pnl = (
            exit_price - position["entry_price"]
        ) * position["position_size"]
    else:
        pnl = (
            position["entry_price"] - exit_price
        ) * position["position_size"]

    return {
        **position,
        "exit_time": exit_time,
        "exit_price": exit_price,
        "pnl": pnl,
        "exit_reason": exit_reason,
    }


def run_backtest(candles):
    capital = STARTING_CAPITAL
    position = None
    trades = []

    decisions = {
        "BUY": 0,
        "SELL": 0,
        "WAIT": 0,
    }

    risk_rejections = 0
    feature_engine = IncrementalFeatures()

    for index, candle in enumerate(candles):
        features = feature_engine.update(candle)

        if index < 200:
            continue

        # ---------------------------------------------------------
        # POSITION MANAGEMENT
        # ---------------------------------------------------------
        if position is not None:
            position["bars_held"] += 1

            # STOP LOSS
            if position["side"] == "BUY":
                if candle["low"] <= position["stop_loss"]:
                    trade = close_position(
                        position,
                        position["stop_loss"],
                        candle["time"],
                        "STOP_LOSS",
                    )
                    capital += trade["pnl"]
                    trades.append(trade)
                    position = None
                    continue

            else:
                if candle["high"] >= position["stop_loss"]:
                    trade = close_position(
                        position,
                        position["stop_loss"],
                        candle["time"],
                        "STOP_LOSS",
                    )
                    capital += trade["pnl"]
                    trades.append(trade)
                    position = None
                    continue

            # TIME EXIT
            if position["bars_held"] >= MAX_HOLD_BARS:
                trade = close_position(
                    position,
                    candle["close"],
                    candle["time"],
                    "TIME_EXIT",
                )
                capital += trade["pnl"]
                trades.append(trade)
                position = None
                continue

            continue

        # ---------------------------------------------------------
        # ENTRY
        # ---------------------------------------------------------
        regime = detect_regime(features)
        decision = analyze_market(features, regime)

        signal = decision["signal"]
        decisions[signal] += 1

        if signal == "WAIT":
            continue

        risk = evaluate_risk(
            decision,
            features,
            capital=capital,
            daily_pnl=0.0,
            open_positions=0,
        )

        if not risk["allowed"]:
            risk_rejections += 1
            continue

        position = {
            "side": signal,
            "entry_time": candle["time"],
            "entry_price": features["close"],
            "position_size": risk["position_size"],
            "stop_loss": risk["stop_loss"],
            "regime": regime,
            "score": decision["score"],
            "bars_held": 0,
        }

    # DATASET END
    if position is not None:
        last = candles[-1]

        trade = close_position(
            position,
            last["close"],
            last["time"],
            "BACKTEST_END",
        )

        capital += trade["pnl"]
        trades.append(trade)

    return capital, trades, decisions, risk_rejections


def pct(value):
    return f"{value * 100:+.3f}%"


def summarize_group(trades):
    if not trades:
        return {
            "count": 0,
            "wins": 0,
            "losses": 0,
            "pnl": 0.0,
            "avg": 0.0,
            "win_rate": 0.0,
        }

    wins = [t for t in trades if t["pnl"] > 0]
    losses = [t for t in trades if t["pnl"] < 0]

    pnl = sum(t["pnl"] for t in trades)

    return {
        "count": len(trades),
        "wins": len(wins),
        "losses": len(losses),
        "pnl": pnl,
        "avg": pnl / len(trades),
        "win_rate": (
            len(wins) / len(trades) * 100
        ),
    }


def print_group(title, groups):
    print()
    print("-" * 78)
    print(title)
    print("-" * 78)

    for name, group in groups.items():
        s = summarize_group(group)

        print(
            f"{name:<22} "
            f"N {s['count']:>5} "
            f"W {s['wins']:>5} "
            f"L {s['losses']:>5} "
            f"WR {s['win_rate']:>6.2f}% "
            f"P/L ${s['pnl']:>+9.3f} "
            f"Avg ${s['avg']:>+8.4f}"
        )


def main():
    print("=" * 78)
    print("EXIT ANALYSIS V1")
    print("=" * 78)

    candles = get_historical_candles_100k(
        symbol=SYMBOL,
        interval=INTERVAL,
        candles_needed=CANDLES_NEEDED,
    )

    valid, reason = validate_candles(candles)

    print(f"Candles:     {len(candles)}")
    print(f"Validation:  {valid}")
    print(f"Reason:      {reason}")

    if not valid:
        raise RuntimeError(reason)

    capital, trades, decisions, risk_rejections = run_backtest(
        candles
    )

    realized = [
        t for t in trades
        if t["exit_reason"] != "BACKTEST_END"
    ]

    forced = [
        t for t in trades
        if t["exit_reason"] == "BACKTEST_END"
    ]

    print()
    print("-" * 78)
    print("OVERALL")
    print("-" * 78)

    print(f"Starting Capital : ${STARTING_CAPITAL:.2f}")
    print(f"Final Capital    : ${capital:.2f}")
    print(
        f"Realized P/L     : "
        f"${sum(t['pnl'] for t in realized):+.4f}"
    )
    print(
        f"Dataset-End P/L  : "
        f"${sum(t['pnl'] for t in forced):+.4f}"
    )

    print(f"Realized Trades  : {len(realized)}")
    print(f"BUY Decisions    : {decisions['BUY']}")
    print(f"SELL Decisions   : {decisions['SELL']}")
    print(f"WAIT Decisions   : {decisions['WAIT']}")
    print(f"Risk Rejections  : {risk_rejections}")

    # -------------------------------------------------------------
    # EXIT TYPE
    # -------------------------------------------------------------
    exit_groups = {}

    for trade in realized:
        exit_groups.setdefault(
            trade["exit_reason"], []
        ).append(trade)

    print_group(
        "EXIT TYPE",
        exit_groups,
    )

    # -------------------------------------------------------------
    # SIDE
    # -------------------------------------------------------------
    side_groups = {}

    for trade in realized:
        side_groups.setdefault(
            trade["side"], []
        ).append(trade)

    print_group(
        "SIDE",
        side_groups,
    )

    # -------------------------------------------------------------
    # REGIME
    # -------------------------------------------------------------
    regime_groups = {}

    for trade in realized:
        regime_groups.setdefault(
            trade["regime"], []
        ).append(trade)

    print_group(
        "REGIME",
        regime_groups,
    )

    # -------------------------------------------------------------
    # EXIT TYPE × REGIME
    # -------------------------------------------------------------
    print()
    print("-" * 78)
    print("EXIT TYPE × REGIME")
    print("-" * 78)

    exit_regime_groups = {}

    for trade in realized:
        key = (
            trade["exit_reason"],
            trade["regime"],
        )

        exit_regime_groups.setdefault(
            key, []
        ).append(trade)

    for (exit_reason, regime), group in sorted(
        exit_regime_groups.items()
    ):
        s = summarize_group(group)

        print(
            f"{exit_reason:<12} "
            f"{regime:<18} "
            f"N {s['count']:>5} "
            f"W {s['wins']:>5} "
            f"L {s['losses']:>5} "
            f"WR {s['win_rate']:>6.2f}% "
            f"P/L ${s['pnl']:>+9.3f}"
        )

    # -------------------------------------------------------------
    # HOLDING TIME
    # -------------------------------------------------------------
    hold_groups = {
        "0-12 bars": [],
        "13-48 bars": [],
        "49-144 bars": [],
        "145-287 bars": [],
        "288+ bars": [],
    }

    for trade in realized:
        bars = trade["bars_held"]

        if bars <= 12:
            hold_groups["0-12 bars"].append(trade)
        elif bars <= 48:
            hold_groups["13-48 bars"].append(trade)
        elif bars <= 144:
            hold_groups["49-144 bars"].append(trade)
        elif bars < 288:
            hold_groups["145-287 bars"].append(trade)
        else:
            hold_groups["288+ bars"].append(trade)

    print_group(
        "HOLDING TIME",
        hold_groups,
    )

    # -------------------------------------------------------------
    # TIME EXIT DETAIL
    # -------------------------------------------------------------
    time_exits = [
        t for t in realized
        if t["exit_reason"] == "TIME_EXIT"
    ]

    print()
    print("-" * 78)
    print("TIME EXIT DETAIL")
    print("-" * 78)

    if not time_exits:
        print("No TIME_EXIT trades.")
    else:
        s = summarize_group(time_exits)

        profitable = [
            t for t in time_exits
            if t["pnl"] > 0
        ]

        losing = [
            t for t in time_exits
            if t["pnl"] < 0
        ]

        print(f"Count            : {s['count']}")
        print(f"Wins             : {len(profitable)}")
        print(f"Losses           : {len(losing)}")
        print(f"Win Rate         : {s['win_rate']:.2f}%")
        print(f"Total P/L        : ${s['pnl']:+.4f}")
        print(f"Average P/L      : ${s['avg']:+.4f}")
        print(
            f"Best P/L         : "
            f"${max(t['pnl'] for t in time_exits):+.4f}"
        )
        print(
            f"Worst P/L        : "
            f"${min(t['pnl'] for t in time_exits):+.4f}"
        )

    print()
    print("=" * 78)
    print("EXIT ANALYSIS COMPLETE")
    print("=" * 78)


if __name__ == "__main__":
    main()
