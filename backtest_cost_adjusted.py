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

# Cost assumptions — change only for experiments.
FEE_RATE = 0.0
SLIPPAGE_RATE = 0.0


def apply_execution_price(price, side, is_entry):
    if side == "BUY":
        if is_entry:
            return price * (1 + SLIPPAGE_RATE)
        return price * (1 - SLIPPAGE_RATE)

    if is_entry:
        return price * (1 - SLIPPAGE_RATE)
    return price * (1 + SLIPPAGE_RATE)


def calculate_fee(price, position_size):
    return price * position_size * FEE_RATE


def close_position(position, exit_price, exit_time, exit_reason):
    side = position["side"]

    execution_price = apply_execution_price(
        exit_price,
        side,
        is_entry=False,
    )

    if side == "BUY":
        gross_pnl = (
            execution_price - position["entry_price"]
        ) * position["position_size"]
    else:
        gross_pnl = (
            position["entry_price"] - execution_price
        ) * position["position_size"]

    exit_fee = calculate_fee(
        execution_price,
        position["position_size"],
    )

    net_pnl = gross_pnl - exit_fee

    return {
        "entry_time": position["entry_time"],
        "exit_time": exit_time,
        "side": side,
        "entry_price": position["entry_price"],
        "exit_price": execution_price,
        "position_size": position["position_size"],
        "regime": position["regime"],
        "score": position["score"],
        "bars_held": position["bars_held"],
        "gross_pnl": gross_pnl,
        "entry_fee": position["entry_fee"],
        "exit_fee": exit_fee,
        "fees": position["entry_fee"] + exit_fee,
        "slippage_cost": position["slippage_cost"],
        "pnl": net_pnl,
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

        # -----------------------------------------------------
        # POSITION MANAGEMENT
        # -----------------------------------------------------
        if position is not None:
            position["bars_held"] += 1

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

            elif position["side"] == "SELL":
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

            # -------------------------------------------------
            # TIME EXIT
            # -------------------------------------------------
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

        # -----------------------------------------------------
        # ENTRY
        # -----------------------------------------------------
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

        raw_entry_price = features["close"]
        entry_price = apply_execution_price(
            raw_entry_price,
            signal,
            is_entry=True,
        )

        entry_fee = calculate_fee(
            entry_price,
            risk["position_size"],
        )

        slippage_cost = abs(
            entry_price - raw_entry_price
        ) * risk["position_size"]

        position = {
            "side": signal,
            "entry_time": candle["time"],
            "entry_price": entry_price,
            "position_size": risk["position_size"],
            "stop_loss": risk["stop_loss"],
            "regime": regime,
            "score": decision["score"],
            "bars_held": 0,
            "entry_fee": entry_fee,
            "slippage_cost": slippage_cost,
        }

        capital -= entry_fee

    # ---------------------------------------------------------
    # DATASET-END EXIT
    # ---------------------------------------------------------
    if position is not None:
        last_candle = candles[-1]

        trade = close_position(
            position,
            last_candle["close"],
            last_candle["time"],
            "BACKTEST_END",
        )

        capital += trade["pnl"]
        trades.append(trade)

    return capital, trades, decisions, risk_rejections


def print_results(
    capital,
    trades,
    decisions,
    risk_rejections,
):
    realized = [
        trade
        for trade in trades
        if trade["exit_reason"] != "BACKTEST_END"
    ]

    forced = [
        trade
        for trade in trades
        if trade["exit_reason"] == "BACKTEST_END"
    ]

    wins = [
        trade
        for trade in realized
        if trade["pnl"] > 0
    ]

    losses = [
        trade
        for trade in realized
        if trade["pnl"] < 0
    ]

    gross_pnl = sum(
        trade["gross_pnl"]
        for trade in realized
    )

    net_pnl = sum(
        trade["pnl"]
        for trade in realized
    )

    total_fees = sum(
        trade["fees"]
        for trade in trades
    )

    total_slippage = sum(
        trade["slippage_cost"]
        for trade in trades
    )

    gross_profit = sum(
        trade["pnl"]
        for trade in wins
    )

    gross_loss = abs(
        sum(
            trade["pnl"]
            for trade in losses
        )
    )

    profit_factor = (
        gross_profit / gross_loss
        if gross_loss > 0
        else None
    )

    print()
    print("=" * 70)
    print("COST-ADJUSTED TIME EXIT BACKTEST")
    print("=" * 70)

    print(f"Max Hold Bars    : {MAX_HOLD_BARS}")
    print(f"Max Hold Time    : 24 hours")
    print(f"Starting Capital : ${STARTING_CAPITAL:.2f}")

    print()
    print("COST ASSUMPTIONS")
    print("-" * 70)
    print(f"Fee Rate         : {FEE_RATE * 100:.4f}%")
    print(f"Slippage Rate    : {SLIPPAGE_RATE * 100:.4f}%")

    print()
    print("RESULT")
    print("-" * 70)
    print(f"Final Capital    : ${capital:.2f}")
    print(f"Realized Gross   : ${gross_pnl:+.4f}")
    print(f"Realized Net     : ${net_pnl:+.4f}")
    print(f"Total Fees       : ${total_fees:.4f}")
    print(f"Total Slippage   : ${total_slippage:.4f}")

    if realized:
        print(f"Realized Trades  : {len(realized)}")
        print(f"Wins             : {len(wins)}")
        print(f"Losses           : {len(losses)}")
        print(
            f"Win Rate         : "
            f"{len(wins) / len(realized) * 100:.2f}%"
        )

    if profit_factor is not None:
        print(f"Profit Factor    : {profit_factor:.4f}")
    else:
        print("Profit Factor    : N/A")

    print()
    print(f"BUY Decisions    : {decisions['BUY']}")
    print(f"SELL Decisions   : {decisions['SELL']}")
    print(f"WAIT Decisions   : {decisions['WAIT']}")
    print(f"Risk Rejections  : {risk_rejections}")

    forced_pnl = sum(
        trade["pnl"]
        for trade in forced
    )

    print(f"Dataset-End P/L  : ${forced_pnl:+.4f}")

    print()
    print("=" * 70)
    print("BACKTEST COMPLETE")
    print("=" * 70)


def main():
    print("=" * 70)
    print("LOADING 100K DATA")
    print("=" * 70)

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
        raise RuntimeError(
            f"Dataset validation failed: {reason}"
        )

    capital, trades, decisions, risk_rejections = (
        run_backtest(candles)
    )

    print_results(
        capital,
        trades,
        decisions,
        risk_rejections,
    )


if __name__ == "__main__":
    main()
