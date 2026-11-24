"""Fill the local database with repeatable data for a classroom demo."""
from datetime import datetime, timedelta, timezone
import sqlite3

from werkzeug.security import generate_password_hash

import swaps
import wallet
from db import DATABASE, ensure_schema


def seed(database_path=DATABASE):
    connection = sqlite3.connect(database_path)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    ensure_schema(connection)
    # Seed data is resettable demo content; this is not used by the migration.
    connection.execute("DELETE FROM notifications")
    connection.execute("DELETE FROM swap_offers")
    connection.execute("DELETE FROM deposits")
    connection.execute("DELETE FROM wallet_transactions")
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
        if role == "user":
            wallet.top_up(connection, cursor.lastrowid, 500)

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
    # Every bidder pays the lot's deposit first, exactly like a real user would.
    bid_rows = [(0, 2, 50), (0, 3, 55), (3, 1, 27.5), (3, 3, 30)]
    for lot_index, bidder_num, amount in bid_rows:
        lot_id = lot_ids[lot_index]
        bidder_id = ids[f"user{bidder_num}@example.com"]
        if not connection.execute("SELECT 1 FROM deposits WHERE lot_id = ? AND user_id = ?", (lot_id, bidder_id)).fetchone():
            lot = connection.execute("SELECT id, title, start_price FROM lots WHERE id = ?", (lot_id,)).fetchone()
            wallet.pay_deposit(connection, bidder_id, lot)
        connection.execute("INSERT INTO bids (lot_id, bidder_id, amount) VALUES (?, ?, ?)", (lot_id, bidder_id, amount))
        connection.execute("UPDATE lots SET current_price = ? WHERE id = ?", (amount, lot_id))

    # Two lots accept item swaps; the board game bundle already has one pending offer from user1.
    for lot_index in (1, 5):
        connection.execute("UPDATE lots SET accepts_swaps = 1 WHERE id = ?", (lot_ids[lot_index],))
    swap_lot = connection.execute("SELECT * FROM lots WHERE id = ?", (lot_ids[5],)).fetchone()
    swaps.create_offer(connection, swap_lot, ids["user1@example.com"], "Chess set",
                       "Wooden chess set with all pieces, lightly used.", 15)
    connection.commit()
    connection.close()
    print("Seeded 1 admin, 4 users (500.00 wallet top-up each), 6 lots, 4 bids, 4 deposits, and 1 swap offer.")
    print("Demo passwords: admin-demo and user-demo.")


if __name__ == "__main__":
    seed()
