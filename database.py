import sqlite3
from pathlib import Path


DB_PATH = Path("trading.db")


def get_connection():
    return sqlite3.connect(DB_PATH)


def initialize_database():
    connection = get_connection()

    # --------------------------------------------------
    # CLOSED TRADES
    # --------------------------------------------------

    connection.execute("""
        CREATE TABLE IF NOT EXISTS trades (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            symbol TEXT NOT NULL,
            side TEXT NOT NULL,
            status TEXT NOT NULL,

            entry_price REAL,
            exit_price REAL,

            position_size REAL,
            position_value REAL,

            stop_loss REAL,

            pnl REAL DEFAULT 0,

            strategy_score REAL,
            confidence REAL,
            regime TEXT,

            reason TEXT,
            exit_reason TEXT
        )
    """)

    # --------------------------------------------------
    # ACCOUNT STATE
    # --------------------------------------------------

    # Backward-compatible migration for cost-aware closed trades.
    # Existing trades remain readable; new trades can store fee/slippage/net P/L.
    existing_columns = {
        row[1] for row in connection.execute("PRAGMA table_info(trades)").fetchall()
    }
    if "fees" not in existing_columns:
        connection.execute("ALTER TABLE trades ADD COLUMN fees REAL")
    if "slippage" not in existing_columns:
        connection.execute("ALTER TABLE trades ADD COLUMN slippage REAL")
    if "net_pnl" not in existing_columns:
        connection.execute("ALTER TABLE trades ADD COLUMN net_pnl REAL")

    connection.execute("""
        CREATE TABLE IF NOT EXISTS account_state (
            id INTEGER PRIMARY KEY CHECK (id = 1),

            starting_capital REAL NOT NULL,
            capital REAL NOT NULL,
            daily_pnl REAL NOT NULL DEFAULT 0,

            updated_at TEXT NOT NULL
        )
    """)

    # --------------------------------------------------
    # OPEN POSITIONS
    # --------------------------------------------------

    connection.execute("""
        CREATE TABLE IF NOT EXISTS open_positions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,

            symbol TEXT NOT NULL,
            side TEXT NOT NULL,

            entry_price REAL NOT NULL,
            position_size REAL NOT NULL,
            position_value REAL NOT NULL,

            stop_loss REAL NOT NULL,

            strategy_score REAL,
            confidence REAL,
            regime TEXT,

            reason TEXT,

            opened_at TEXT NOT NULL
        )
    """)

    connection.commit()
    connection.close()


# ============================================================
# ACCOUNT STATE
# ============================================================

def get_account_state():

    connection = get_connection()

    row = connection.execute("""
        SELECT
            starting_capital,
            capital,
            daily_pnl,
            updated_at
        FROM account_state
        WHERE id = 1
    """).fetchone()

    connection.close()

    if row is None:
        return None

    return {
        "starting_capital": row[0],
        "capital": row[1],
        "daily_pnl": row[2],
        "updated_at": row[3],
    }


def save_account_state(
    starting_capital,
    capital,
    daily_pnl,
    updated_at
):

    connection = get_connection()

    connection.execute("""
        INSERT INTO account_state (
            id,
            starting_capital,
            capital,
            daily_pnl,
            updated_at
        )
        VALUES (1, ?, ?, ?, ?)

        ON CONFLICT(id)
        DO UPDATE SET
            starting_capital = excluded.starting_capital,
            capital = excluded.capital,
            daily_pnl = excluded.daily_pnl,
            updated_at = excluded.updated_at
    """, (
        starting_capital,
        capital,
        daily_pnl,
        updated_at,
    ))

    connection.commit()
    connection.close()


# ============================================================
# OPEN POSITION
# ============================================================

def get_open_position():

    connection = get_connection()

    row = connection.execute("""
        SELECT
            id,
            symbol,
            side,
            entry_price,
            position_size,
            position_value,
            stop_loss,
            strategy_score,
            confidence,
            regime,
            reason,
            opened_at
        FROM open_positions
        ORDER BY id DESC
        LIMIT 1
    """).fetchone()

    connection.close()

    if row is None:
        return None

    return {
        "id": row[0],
        "symbol": row[1],
        "side": row[2],
        "entry_price": row[3],
        "position_size": row[4],
        "position_value": row[5],
        "stop_loss": row[6],
        "strategy_score": row[7],
        "confidence": row[8],
        "regime": row[9],
        "reason": row[10],
        "opened_at": row[11],
    }


def save_open_position(position):

    connection = get_connection()

    connection.execute("""
        INSERT INTO open_positions (
            symbol,
            side,
            entry_price,
            position_size,
            position_value,
            stop_loss,
            strategy_score,
            confidence,
            regime,
            reason,
            opened_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        position["symbol"],
        position["side"],
        position["entry_price"],
        position["position_size"],
        position["position_value"],
        position["stop_loss"],
        position.get("strategy_score"),
        position.get("confidence"),
        position.get("regime"),
        position.get("reason"),
        position["opened_at"],
    ))

    connection.commit()
    connection.close()


def delete_open_position(position_id):

    connection = get_connection()

    connection.execute("""
        DELETE FROM open_positions
        WHERE id = ?
    """, (position_id,))

    connection.commit()
    connection.close()


# ============================================================
# CLOSED TRADE
# ============================================================

def save_trade(trade):

    connection = get_connection()

    connection.execute("""
        INSERT INTO trades (
            timestamp,
            symbol,
            side,
            status,
            entry_price,
            exit_price,
            position_size,
            position_value,
            stop_loss,
            pnl,
            fees,
            slippage,
            net_pnl,
            strategy_score,
            confidence,
            regime,
            reason,
            exit_reason
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        trade["timestamp"],
        trade["symbol"],
        trade["side"],
        trade["status"],
        trade.get("entry_price"),
        trade.get("exit_price"),
        trade.get("position_size"),
        trade.get("position_value"),
        trade.get("stop_loss"),
        trade.get("pnl", 0),
        trade.get("fees"),
        trade.get("slippage"),
        trade.get("net_pnl"),
        trade.get("strategy_score"),
        trade.get("confidence"),
        trade.get("regime"),
        trade.get("reason"),
        trade.get("exit_reason"),
    ))

    connection.commit()
    connection.close()


# ============================================================
# TEST
# ============================================================

if __name__ == "__main__":

    initialize_database()

    print("Database initialized.")

    print()
    print("Account State:")
    print(get_account_state())

    print()
    print("Open Position:")
    print(get_open_position())
