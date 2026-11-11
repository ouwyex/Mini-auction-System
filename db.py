"""Small SQLite helpers used by the Flask application."""
import sqlite3
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
DATABASE = BASE_DIR / "auction.db"


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


def ensure_deposit_support(connection):
    """Upgrade an older database: add users.balance and the deposits table if they are missing."""
    columns = {row[1] for row in connection.execute("PRAGMA table_info(users)")}
    if columns and "balance" not in columns:
        connection.execute("ALTER TABLE users ADD COLUMN balance REAL NOT NULL DEFAULT 0")
        connection.commit()
    has_deposits = connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'deposits'"
    ).fetchone()
    if not has_deposits:
        connection.executescript((BASE_DIR / "schema.sql").read_text(encoding="utf-8-sig"))


if __name__ == "__main__":
    init_db()
    print(f"Database ready: {DATABASE}")
