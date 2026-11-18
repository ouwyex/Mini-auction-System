"""Tests for the home page filter: status, price range, and title search."""
from datetime import datetime, timedelta, timezone
import sqlite3

from app import app as flask_app
from test_app import add_user, client  # noqa: F401  (client is a pytest fixture)


def add_lot(title, price, status="active", seller_id=None, days=2):
    """Insert a lot directly so each test controls price and status."""
    if seller_id is None:
        seller_id = add_user(f"seller-{title.replace(' ', '-').lower()}@example.com")
    closes = (datetime.now(timezone.utc) + timedelta(days=days)).isoformat()
    with sqlite3.connect(flask_app.config["DATABASE"]) as connection:
        return connection.execute(
            "INSERT INTO lots (seller_id, title, description, start_price, bid_step, current_price, closes_at, status) "
            "VALUES (?, ?, 'Description', 5, 1, ?, ?, ?)",
            (seller_id, title, price, closes, status),
        ).lastrowid


def test_price_filter_returns_only_lots_inside_the_range(client):
    add_lot("Cheap pen", 8)
    add_lot("Edge low", 20)
    add_lot("Middle chair", 35.5)
    add_lot("Edge high", 50)
    add_lot("Pricey watch", 120)

    html = client.get("/?min_price=20&max_price=50").get_data(as_text=True)
    # Both limits are inclusive; everything outside the range is absent.
    for shown in ("Edge low", "Middle chair", "Edge high"):
        assert shown in html
    for hidden in ("Cheap pen", "Pricey watch"):
        assert hidden not in html
    assert "3 lots found" in html

    # Only a minimum, then only a maximum.
    only_min = client.get("/?min_price=50").get_data(as_text=True)
    assert "Edge high" in only_min and "Pricey watch" in only_min and "Middle chair" not in only_min
    only_max = client.get("/?max_price=8").get_data(as_text=True)
    assert "Cheap pen" in only_max and "Edge low" not in only_max

    # A range with nothing in it shows the empty message instead of lots.
    nothing = client.get("/?min_price=60&max_price=100").get_data(as_text=True)
    assert "No lots match these filters" in nothing


def test_status_filter_and_title_search_work_together(client):
    add_lot("Brass lamp", 15)
    add_lot("Old lamp", 12, status="closed")
    add_lot("Broken lamp", 3, status="unsold")
    add_lot("Camera", 40, status="closed")
    add_lot("100% cotton shirt", 9)
    add_lot("Plain shirt", 9)

    # No parameters keeps the original behaviour: active lots only.
    default = client.get("/").get_data(as_text=True)
    assert "Brass lamp" in default and "Old lamp" not in default and "Camera" not in default

    closed = client.get("/?status=closed").get_data(as_text=True)
    assert "Old lamp" in closed and "Camera" in closed and "Brass lamp" not in closed

    # Search is case-insensitive and combines with the status filter.
    closed_lamps = client.get("/?status=closed&q=LAMP").get_data(as_text=True)
    assert "Old lamp" in closed_lamps and "Camera" not in closed_lamps and "Broken lamp" not in closed_lamps

    # "all" ignores status, so every lamp is found.
    all_lamps = client.get("/?status=all&q=lamp").get_data(as_text=True)
    assert all(name in all_lamps for name in ("Brass lamp", "Old lamp", "Broken lamp"))

    # % is matched literally, not as a wildcard that matches every title.
    percent = client.get("/?q=%25").get_data(as_text=True)
    assert "100% cotton shirt" in percent and "Plain shirt" not in percent


def test_bad_filter_input_is_reported_and_the_index_is_used(client):
    add_lot("Visible lot", 10)

    bad_number = client.get("/?min_price=abc")
    assert bad_number.status_code == 200
    assert b"Minimum price must be a number" in bad_number.data and b"Visible lot" in bad_number.data

    reversed_range = client.get("/?min_price=50&max_price=5").get_data(as_text=True)
    assert "higher than maximum" in reversed_range and "Visible lot" in reversed_range

    unknown_status = client.get("/?status=bogus").get_data(as_text=True)
    assert "Unknown status filter" in unknown_status and "Visible lot" in unknown_status

    with sqlite3.connect(flask_app.config["DATABASE"]) as connection:
        plan = " ".join(row[3] for row in connection.execute(
            "EXPLAIN QUERY PLAN SELECT id FROM lots WHERE status = ? AND current_price >= ? AND current_price <= ?",
            ("active", 10, 50),
        ))
    assert "idx_lots_status_price" in plan
