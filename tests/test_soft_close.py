"""Tests for FR-02: a bid in the last 30 seconds extends the auction by 2 minutes."""
from datetime import datetime, timedelta, timezone
import sqlite3

from app import app as flask_app
from test_app import add_user, client, lot_id, post  # noqa: F401  (client is a pytest fixture)


def closing_time(lot):
    with sqlite3.connect(flask_app.config["DATABASE"]) as connection:
        return datetime.fromisoformat(connection.execute("SELECT closes_at FROM lots WHERE id = ?", (lot,)).fetchone()[0])


def login_and_pay(client, lot, email="buyer@example.com"):
    user = add_user(email)
    with client.session_transaction() as sess:
        sess["user_id"] = user
        sess["csrf_token"] = "test-token"
    post(client, f"/lots/{lot}/deposit")


def test_bid_far_from_closing_does_not_extend_the_auction(client):
    closes = datetime.now(timezone.utc) + timedelta(minutes=10)
    lot = lot_id(closes=closes.isoformat())
    login_and_pay(client, lot)
    post(client, f"/lots/{lot}/bid", {"amount": "10"})
    assert closing_time(lot) == closes


def test_late_bids_extend_each_time_and_the_message_says_so(client):
    closes = datetime.now(timezone.utc) + timedelta(seconds=20)
    lot = lot_id(closes=closes.isoformat())
    login_and_pay(client, lot)
    first = post(client, f"/lots/{lot}/bid", {"amount": "10"}, follow_redirects=True)
    assert b"extended by 2 minutes" in first.data
    assert closing_time(lot) == closes + timedelta(minutes=2)

    # The auction is now more than 30 seconds from closing, so the next bid does not extend it again.
    post(client, f"/lots/{lot}/bid", {"amount": "12"})
    assert closing_time(lot) == closes + timedelta(minutes=2)
