"""Fill the local database with repeatable data for a classroom demo."""
from datetime import datetime, timedelta, timezone
import sqlite3

from werkzeug.security import generate_password_hash

from db import BASE_DIR, DATABASE


def seed(database_path=DATABASE):
    connection = sqlite3.connect(database_path)
    connection.execute("PRAGMA foreign_keys = ON")
    schema = (BASE_DIR / "schema.sql").read_text(encoding="utf-8-sig")
    connection.executescript(schema)
    # Seed data is resettable demo content; this is not used by the migration.
    connection.execute("DELETE FROM bids")
    connection.execute("DELETE FROM lots")
    connection.execute("DELETE FROM users")
    accounts = [("admin@example.com", "admin-demo", "admin")] + [
        (f"user{i}@example.com", "user-demo", "user") for i in range(1, 5)
    ]
    ids = {}
    for email, password, role in accounts:
        cursor = connection.execute(
            "INSERT INTO users (email, password_hash, role) VALUES (?, ?, ?)",
            (email, generate_password_hash(password), role),
        )
        ids[email] = cursor.lastrowid

    now = datetime.now(timezone.utc)
    sample_lots = [
        ("Vintage camera", "A working film camera in good condition.", 45, 5, 1, 2),
        ("Desk lamp", "Adjustable metal desk lamp.", 18, 2, 2, 3),
        ("Vinyl record set", "Five classic jazz records.", 30, 3, 1, 4),
        ("Mountain backpack", "A sturdy 40 litre hiking pack.", 25, 2.5, 2, -2),
        ("Mechanical keyboard", "Compact keyboard with tactile switches.", 50, 5, 3, -3),
        ("Board game bundle", "A family game night collection.", 12, 1, 4, 4),
    ]
    lot_ids = []
    for title, description, price, step, seller_num, day_offset in sample_lots:
        cursor = connection.execute(
            "INSERT INTO lots (seller_id, title, description, start_price, bid_step, current_price, closes_at, status) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (ids[f"user{seller_num}@example.com"], title, description, price, step, price,
             (now + timedelta(days=day_offset)).isoformat(), "active"),
        )
        lot_ids.append(cursor.lastrowid)

    # One active lot with bids, one expired lot with bids, and one expired unsold lot.
    bid_rows = [(0, 2, 50), (0, 3, 55), (3, 1, 27.5), (3, 2, 30)]
    for lot_index, bidder_num, amount in bid_rows:
        connection.execute(
            "INSERT INTO bids (lot_id, bidder_id, amount) VALUES (?, ?, ?)",
            (lot_ids[lot_index], ids[f"user{bidder_num}@example.com"], amount),
        )
        connection.execute("UPDATE lots SET current_price = ? WHERE id = ?", (amount, lot_ids[lot_index]))
    connection.commit()
    connection.close()
    print("Seeded 1 admin, 4 users, 6 lots, and 4 bids.")
    print("Demo passwords: admin-demo and user-demo.")


if __name__ == "__main__":
    seed()
