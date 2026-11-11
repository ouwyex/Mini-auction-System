"""Tests for the deposit rule: 10% of the start price must be paid before a user can bid on a lot."""
from datetime import datetime, timedelta, timezone
import sqlite3

import pytest
from werkzeug.security import generate_password_hash

from app import app as flask_app


@pytest.fixture
def client(tmp_path):
    database_path = tmp_path / "test-deposits.db"
    flask_app.config.update(TESTING=True, SECRET_KEY="test-secret", DATABASE=str(database_path))
    with flask_app.app_context():
        from db import BASE_DIR
        connection = sqlite3.connect(database_path)
        connection.executescript((BASE_DIR / "schema.sql").read_text(encoding="utf-8-sig"))
        connection.close()
    with flask_app.test_client() as test_client:
        with test_client.session_transaction() as sess:
            sess["csrf_token"] = "test-token"
        yield test_client


def db():
    return sqlite3.connect(flask_app.config["DATABASE"])


def post(client, url, data=None, **kwargs):
    return client.post(url, data={**(data or {}), "csrf_token": "test-token"}, **kwargs)


def add_user(email, role="user", balance=0.0):
    with db() as connection:
        return connection.execute(
            "INSERT INTO users (email, password_hash, role, balance) VALUES (?, ?, ?, ?)",
            (email, generate_password_hash("password-123"), role, balance),
        ).lastrowid


def login_as(client, user_id):
    with client.session_transaction() as sess:
        sess["user_id"] = user_id
        sess["csrf_token"] = "test-token"


def add_lot(seller_id, start_price=100, closes=None, title="Lot"):
    closes = closes or (datetime.now(timezone.utc) + timedelta(days=2)).isoformat()
    with db() as connection:
        return connection.execute(
            "INSERT INTO lots (seller_id, title, description, start_price, bid_step, current_price, closes_at) "
            "VALUES (?, ?, 'Description', ?, 5, ?, ?)", (seller_id, title, start_price, start_price, closes),
        ).lastrowid


def balance(user_id):
    with db() as connection:
        return connection.execute("SELECT balance FROM users WHERE id = ?", (user_id,)).fetchone()[0]


def deposit_rows(lot_id):
    with db() as connection:
        return connection.execute("SELECT user_id, amount, status FROM deposits WHERE lot_id = ? ORDER BY id", (lot_id,)).fetchall()


def count_bids(lot_id):
    with db() as connection:
        return connection.execute("SELECT count(*) FROM bids WHERE lot_id = ?", (lot_id,)).fetchone()[0]


def test_top_up_adds_to_balance_and_rejects_bad_amounts(client):
    user = add_user("a@example.com")
    login_as(client, user)
    post(client, "/wallet/top-up", {"amount": "250.50"})
    assert balance(user) == 250.5
    for bad in ("0", "-5", "abc", "10001", "nan"):
        response = post(client, "/wallet/top-up", {"amount": bad}, follow_redirects=True)
        assert b"greater than zero" in response.data
    assert balance(user) == 250.5


def test_deposit_is_ten_percent_of_start_price(client):
    seller, buyer = add_user("seller@example.com"), add_user("buyer@example.com", balance=500)
    lot = add_lot(seller, start_price=45)
    login_as(client, buyer)
    assert b"4.50" in client.get(f"/lots/{lot}").data
    post(client, f"/lots/{lot}/deposit")
    assert deposit_rows(lot) == [(buyer, 4.5, "held")]
    assert balance(buyer) == 495.5


def test_bid_without_deposit_is_refused_and_with_deposit_is_accepted(client):
    seller, buyer = add_user("seller@example.com"), add_user("buyer@example.com", balance=100)
    lot = add_lot(seller, start_price=100)
    login_as(client, buyer)
    refused = post(client, f"/lots/{lot}/bid", {"amount": "100"}, follow_redirects=True)
    assert b"Pay the 10.00 deposit" in refused.data and count_bids(lot) == 0
    post(client, f"/lots/{lot}/deposit")
    post(client, f"/lots/{lot}/bid", {"amount": "100"})
    assert count_bids(lot) == 1


def test_deposit_cannot_be_paid_twice(client):
    seller, buyer = add_user("seller@example.com"), add_user("buyer@example.com", balance=100)
    lot = add_lot(seller, start_price=100)
    login_as(client, buyer)
    post(client, f"/lots/{lot}/deposit")
    again = post(client, f"/lots/{lot}/deposit", follow_redirects=True)
    assert b"already paid" in again.data
    assert len(deposit_rows(lot)) == 1 and balance(buyer) == 90


def test_not_enough_balance_changes_nothing(client):
    seller, buyer = add_user("seller@example.com"), add_user("buyer@example.com", balance=5)
    lot = add_lot(seller, start_price=100)
    login_as(client, buyer)
    response = post(client, f"/lots/{lot}/deposit", follow_redirects=True)
    assert b"Not enough balance" in response.data
    assert deposit_rows(lot) == [] and balance(buyer) == 5


def test_seller_cannot_pay_deposit_on_own_lot_and_guest_is_redirected(client):
    seller = add_user("seller@example.com", balance=100)
    lot = add_lot(seller)
    assert post(client, f"/lots/{lot}/deposit").status_code == 302 and client.get("/wallet").status_code == 302
    login_as(client, seller)
    assert b"own lot" in post(client, f"/lots/{lot}/deposit", follow_redirects=True).data
    assert deposit_rows(lot) == [] and balance(seller) == 100


def test_admin_has_no_wallet(client):
    admin = add_user("admin@example.com", role="admin")
    login_as(client, admin)
    assert client.get("/wallet").status_code == 403
    assert post(client, "/wallet/top-up", {"amount": "10"}).status_code == 403


def test_closing_applies_winner_deposit_and_returns_the_others(client):
    seller = add_user("seller@example.com")
    winner, loser = add_user("winner@example.com", balance=100), add_user("loser@example.com", balance=100)
    lot = add_lot(seller, start_price=100)
    for user in (winner, loser):
        login_as(client, user)
        post(client, f"/lots/{lot}/deposit")
    login_as(client, loser); post(client, f"/lots/{lot}/bid", {"amount": "100"})
    login_as(client, winner); post(client, f"/lots/{lot}/bid", {"amount": "105"})
    with db() as connection:
        connection.execute("UPDATE lots SET closes_at = ? WHERE id = ?",
                           ((datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat(), lot))
    client.get("/")
    assert dict((u, s) for u, _, s in deposit_rows(lot)) == {winner: "applied", loser: "returned"}
    assert balance(winner) == 90 and balance(loser) == 100


def test_unsold_lot_returns_deposits_of_users_who_never_bid(client):
    seller, buyer = add_user("seller@example.com"), add_user("buyer@example.com", balance=100)
    lot = add_lot(seller, start_price=100)
    login_as(client, buyer)
    post(client, f"/lots/{lot}/deposit")
    with db() as connection:
        connection.execute("UPDATE lots SET closes_at = ? WHERE id = ?",
                           ((datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat(), lot))
    client.get("/")
    assert deposit_rows(lot) == [(buyer, 10.0, "returned")] and balance(buyer) == 100


def test_cancelling_a_lot_refunds_deposits(client):
    seller, buyer = add_user("seller@example.com"), add_user("buyer@example.com", balance=100)
    lot = add_lot(seller, start_price=100)
    login_as(client, buyer)
    post(client, f"/lots/{lot}/deposit")
    assert balance(buyer) == 90
    login_as(client, seller)
    assert post(client, f"/lots/{lot}/cancel").status_code == 302
    assert balance(buyer) == 100 and deposit_rows(lot) == []
    with db() as connection:
        assert connection.execute("SELECT count(*) FROM lots WHERE id = ?", (lot,)).fetchone()[0] == 0


def test_lot_with_paid_deposits_cannot_be_edited(client):
    seller, buyer = add_user("seller@example.com"), add_user("buyer@example.com", balance=100)
    lot = add_lot(seller, start_price=100)
    login_as(client, buyer)
    post(client, f"/lots/{lot}/deposit")
    login_as(client, seller)
    assert client.get(f"/lots/{lot}/edit").status_code == 403


def test_admin_deleting_a_lot_refunds_deposits(client):
    seller, buyer = add_user("seller@example.com"), add_user("buyer@example.com", balance=100)
    admin = add_user("admin@example.com", role="admin")
    lot = add_lot(seller, start_price=100)
    login_as(client, buyer)
    post(client, f"/lots/{lot}/deposit"); post(client, f"/lots/{lot}/bid", {"amount": "100"})
    assert balance(buyer) == 90
    login_as(client, admin)
    post(client, "/admin", {"action": "delete_lot", "lot_id": str(lot)})
    assert balance(buyer) == 100 and deposit_rows(lot) == [] and count_bids(lot) == 0


def test_wallet_and_lot_pages_show_deposit_information(client):
    seller, buyer = add_user("seller@example.com"), add_user("buyer@example.com", balance=100)
    lot = add_lot(seller, start_price=100, title="Antique clock")
    login_as(client, buyer)
    page = client.get(f"/lots/{lot}").data
    assert b"Pay deposit 10.00" in page and b"Place your bid" not in page   # no bid form before the deposit
    post(client, f"/lots/{lot}/deposit")
    page = client.get(f"/lots/{lot}").data
    assert b"is held" in page and b"Place your bid" in page
    wallet = client.get("/wallet").data
    assert b"Antique clock" in wallet and b"Held" in wallet and b"90.00" in wallet


def test_database_rejects_duplicate_or_invalid_deposit_rows(client):
    seller, buyer = add_user("seller@example.com"), add_user("buyer@example.com")
    lot = add_lot(seller)
    connection = sqlite3.connect(flask_app.config["DATABASE"])
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("INSERT INTO deposits (lot_id, user_id, amount) VALUES (?, ?, 10)", (lot, buyer))
    for sql, args in (
        ("INSERT INTO deposits (lot_id, user_id, amount) VALUES (?, ?, 10)", (lot, buyer)),      # same user and lot twice
        ("INSERT INTO deposits (lot_id, user_id, amount) VALUES (?, ?, 0)", (lot, seller)),      # amount must be positive
        ("INSERT INTO deposits (lot_id, user_id, amount, status) VALUES (?, ?, 5, 'lost')", (lot, seller)),  # unknown status
        ("INSERT INTO deposits (lot_id, user_id, amount) VALUES (999, ?, 5)", (seller,)),        # lot must exist
    ):
        try:
            connection.execute(sql, args)
        except sqlite3.IntegrityError:
            continue
        raise AssertionError(f"the database accepted: {sql}")
    connection.close()


def test_seed_creates_consistent_deposits(client):
    from seed import seed
    seed(flask_app.config["DATABASE"])
    with db() as connection:
        assert connection.execute("SELECT count(*) FROM deposits").fetchone()[0] == 4
        # every bidder in the demo data has a deposit for the lot they bid on
        missing = connection.execute(
            "SELECT count(*) FROM bids WHERE NOT EXISTS (SELECT 1 FROM deposits d WHERE d.lot_id = bids.lot_id AND d.user_id = bids.bidder_id)"
        ).fetchone()[0]
        assert missing == 0
