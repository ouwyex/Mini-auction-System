"""Safely migrate existing auction databases to the unified user role."""
import sqlite3

from db import BASE_DIR, DATABASE


def migrate(database_path=DATABASE):
    """Convert buyer/seller roles without changing user, lot, or bid IDs."""
    connection = sqlite3.connect(database_path)
    try:
        connection.execute("PRAGMA foreign_keys = OFF")
        connection.execute("BEGIN IMMEDIATE")
        users_sql = connection.execute(
            "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'users'"
        ).fetchone()
        if users_sql and "'buyer'" in users_sql[0]:
            connection.execute(
                "CREATE TABLE users_new ("
                "id INTEGER PRIMARY KEY AUTOINCREMENT, email TEXT NOT NULL UNIQUE, "
                "password_hash TEXT NOT NULL, "
                "role TEXT NOT NULL CHECK (role IN ('user', 'admin')), "
                "is_blocked INTEGER NOT NULL DEFAULT 0 CHECK (is_blocked IN (0, 1)), "
                "created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)"
            )
            connection.execute(
                "INSERT INTO users_new (id, email, password_hash, role, is_blocked, created_at) "
                "SELECT id, email, password_hash, CASE WHEN role IN ('buyer', 'seller') "
                "THEN 'user' ELSE role END, is_blocked, created_at FROM users"
            )
            connection.execute("DROP TABLE users")
            connection.execute("ALTER TABLE users_new RENAME TO users")
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()
    connection = sqlite3.connect(database_path)
    try:
        connection.executescript((BASE_DIR / "schema.sql").read_text(encoding="utf-8-sig"))
    finally:
        connection.close()
    print("Database migration complete; existing accounts and auction data were preserved.")


if __name__ == "__main__":
    migrate()
