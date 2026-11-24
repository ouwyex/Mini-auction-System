"""Small SQLite helpers used by the Flask application."""
import sqlite3
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
DATABASE = BASE_DIR / "auction.db"

# Columns added after the first version; ensure_schema adds them to older databases.
LATER_USER_COLUMNS = {
    "first_name": "TEXT",
    "last_name": "TEXT",
    "balance": "REAL NOT NULL DEFAULT 0 CHECK (balance >= 0)",
}
# Same idea for the lots table (item swaps).
LATER_LOT_COLUMNS = {
    "accepts_swaps": "INTEGER NOT NULL DEFAULT 0 CHECK (accepts_swaps IN (0, 1))",
}


def get_db():
    """Open a connection for the current request and enforce foreign keys."""
    connection = sqlite3.connect(DATABASE)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def init_db():
    """Create tables from schema.sql if they do not already exist."""
    with get_db() as connection:
        schema = (BASE_DIR / "schema.sql").read_text(encoding="utf-8-sig")
        connection.executescript(schema)


def ensure_schema(connection):
    """Bring an older database up to date without touching its data.

    Creates missing tables and indexes (deposits, wallet_transactions, swap_offers, filter index),
    adds the profile and balance columns to an existing users table, and adds lots.accepts_swaps.
    """
    # An interim version stored bid holds in wallet_transactions with different types.
    # Keep that table as a backup instead of deleting it, then create the current one.
    old = connection.execute("SELECT sql FROM sqlite_master WHERE name = 'wallet_transactions'").fetchone()
    if old and "bid_hold" in old[0]:
        connection.execute("DROP INDEX IF EXISTS idx_wallet_user")
        connection.execute("DROP INDEX IF EXISTS idx_wallet_bid")
        connection.execute("ALTER TABLE wallet_transactions RENAME TO wallet_transactions_old_backup")
    connection.executescript((BASE_DIR / "schema.sql").read_text(encoding="utf-8-sig"))
    existing = {row[1] for row in connection.execute("PRAGMA table_info(users)")}
    for column, definition in LATER_USER_COLUMNS.items():
        if column not in existing:
            connection.execute(f"ALTER TABLE users ADD COLUMN {column} {definition}")
    existing_lot_columns = {row[1] for row in connection.execute("PRAGMA table_info(lots)")}
    for column, definition in LATER_LOT_COLUMNS.items():
        if column not in existing_lot_columns:
            connection.execute(f"ALTER TABLE lots ADD COLUMN {column} {definition}")
    connection.commit()


if __name__ == "__main__":
    init_db()
    print(f"Database ready: {DATABASE}")
