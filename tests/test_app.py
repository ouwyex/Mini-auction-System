"""End-to-end tests for account roles and the auction process."""
from datetime import datetime, timedelta, timezone
import sqlite3

import pytest
from werkzeug.security import generate_password_hash

from app import app as flask_app
from migrate import migrate
from seed import seed


@pytest.fixture
def client(tmp_path):
    database_path = tmp_path / "test-auction.db"
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


def post(client, url, data=None, **kwargs):
    return client.post(url, data={**(data or {}), "csrf_token": "test-token"}, **kwargs)


def add_user(email, role="user", blocked=0):
    with sqlite3.connect(flask_app.config["DATABASE"]) as connection:
        cursor = connection.execute(
            "INSERT INTO users (email, password_hash, role, is_blocked) VALUES (?, ?, ?, ?)",
            (email, generate_password_hash("password-123"), role, blocked),
        )
        return cursor.lastrowid


def login(client, email, role="user"):
    user_id = add_user(email, role)
    with client.session_transaction() as sess:
        sess["user_id"] = user_id
        sess["csrf_token"] = "test-token"
    return user_id


def create_lot(client, **overrides):
    form = {
        "title": "Test lot", "description": "A useful item", "start_price": "10",
        "bid_step": "2", "closes_at": (datetime.now(timezone.utc) + timedelta(days=2)).strftime("%Y-%m-%dT%H:%M"),
    }
    form.update(overrides)
    return post(client, "/lots/new", form)


def lot_id(title="Test lot", seller_id=None, closes=None):
    if seller_id is None:
        seller_id = add_user("seller@example.com")
    with sqlite3.connect(flask_app.config["DATABASE"]) as connection:
        cursor = connection.execute(
            "INSERT INTO lots (seller_id, title, description, start_price, bid_step, current_price, closes_at) "
            "VALUES (?, ?, 'Description', 10, 2, 10, ?)",
            (seller_id, title, closes or (datetime.now(timezone.utc) + timedelta(days=2)).isoformat()),
        )
        return cursor.lastrowid


def test_registration_creates_user_role_and_duplicate_email_is_rejected(client):
    response = post(client, "/register", {"first_name": "Alex", "last_name": "Smith", "email": "new@example.com", "password": "password-123", "role": "admin"})
    assert response.status_code == 302
    with sqlite3.connect(flask_app.config["DATABASE"]) as connection:
        row = connection.execute("SELECT password_hash, role, first_name, last_name FROM users").fetchone()
    assert row[0] != "password-123" and row[1] == "user" and row[2:] == ("Alex", "Smith")
    duplicate = post(client, "/register", {"first_name": "Alex", "last_name": "Smith", "email": "new@example.com", "password": "password-123"})
    assert b"already exists" in duplicate.data


def test_guest_is_redirected_from_create_and_bid(client):
    assert client.get("/lots/new").status_code == 302
    response = post(client, f"/lots/{lot_id()}/bid", {"amount": "10"})
    assert response.status_code == 302


def test_user_can_create_lot_and_invalid_values_are_rejected(client):
    login(client, "maker@example.com")
    assert create_lot(client).status_code == 302
    response = create_lot(client, start_price="0")
    assert b"greater than zero" in response.data
    past = (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%dT%H:%M")
    response = create_lot(client, closes_at=past)
    assert b"future" in response.data


def test_user_cannot_bid_on_own_lot_and_bid_step_is_enforced(client):
    seller_id = login(client, "seller@example.com")
    own_lot = lot_id(seller_id=seller_id)
    assert b"own lot" in post(client, f"/lots/{own_lot}/bid", {"amount": "10"}, follow_redirects=True).data
    bidder = add_user("bidder@example.com")
    with client.session_transaction() as sess:
        sess["user_id"] = bidder
    assert b"at least 10.00" in post(client, f"/lots/{own_lot}/bid", {"amount": "9"}, follow_redirects=True).data
    response = post(client, f"/lots/{own_lot}/bid", {"amount": "12"})
    assert response.status_code == 302
    with sqlite3.connect(flask_app.config["DATABASE"]) as connection:
        assert connection.execute("SELECT current_price FROM lots WHERE id = ?", (own_lot,)).fetchone()[0] == 12
    assert b"at least 14.00" in post(client, f"/lots/{own_lot}/bid", {"amount": "13"}, follow_redirects=True).data
    with sqlite3.connect(flask_app.config["DATABASE"]) as connection:
        assert connection.execute("SELECT current_price FROM lots WHERE id = ?", (own_lot,)).fetchone()[0] == 12


def test_bid_after_closing_time_is_rejected(client):
    bidder = login(client, "bidder@example.com")
    _ = bidder
    expired = lot_id(closes=(datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat())
    response = post(client, f"/lots/{expired}/bid", {"amount": "10"}, follow_redirects=True)
    assert b"not active" in response.data or b"closed" in response.data


def test_closing_sets_closed_or_unsold_and_earlier_tie_wins(client):
    seller = add_user("seller@example.com")
    first, second = add_user("first@example.com"), add_user("second@example.com")
    expired = lot_id("Expired", seller, (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat())
    unsold = lot_id("No bids", seller, (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat())
    with sqlite3.connect(flask_app.config["DATABASE"]) as connection:
        connection.execute("INSERT INTO bids (lot_id, bidder_id, amount) VALUES (?, ?, 15)", (expired, first))
        connection.execute("INSERT INTO bids (lot_id, bidder_id, amount) VALUES (?, ?, 15)", (expired, second))
    client.get("/")
    with sqlite3.connect(flask_app.config["DATABASE"]) as connection:
        assert connection.execute("SELECT status FROM lots WHERE id = ?", (expired,)).fetchone()[0] == "closed"
        assert connection.execute("SELECT status FROM lots WHERE id = ?", (unsold,)).fetchone()[0] == "unsold"
    response = client.get(f"/lots/{expired}")
    assert b"first@example.com" in response.data and b"Winner" in response.data


def test_ownership_checks_block_other_lots_and_lots_with_bids(client):
    first_owner = login(client, "owner@example.com")
    other_owner = add_user("other@example.com")
    other_lot = lot_id(seller_id=other_owner)
    assert client.get(f"/lots/{other_lot}/edit").status_code == 403
    with sqlite3.connect(flask_app.config["DATABASE"]) as connection:
        connection.execute("INSERT INTO bids (lot_id, bidder_id, amount) VALUES (?, ?, 10)", (other_lot, first_owner))
    own = lot_id(seller_id=first_owner, title="Own")
    with sqlite3.connect(flask_app.config["DATABASE"]) as connection:
        connection.execute("INSERT INTO bids (lot_id, bidder_id, amount) VALUES (?, ?, 10)", (own, other_owner))
    assert client.get(f"/lots/{own}/edit").status_code == 403


def test_blocked_user_cannot_log_in_and_non_admin_cannot_open_admin(client):
    blocked_id = add_user("blocked@example.com", blocked=1)
    response = post(client, "/login", {"email": "blocked@example.com", "password": "password-123"})
    assert b"incorrect" in response.data
    login(client, "plain@example.com")
    assert client.get("/admin").status_code == 403


def test_admin_actions_and_csrf_protection(client):
    admin_id = login(client, "admin@example.com", "admin")
    user_id = add_user("ordinary@example.com")
    response = post(client, "/admin", {"action": "block", "user_id": str(user_id)})
    assert response.status_code == 302
    with sqlite3.connect(flask_app.config["DATABASE"]) as connection:
        assert connection.execute("SELECT is_blocked FROM users WHERE id = ?", (user_id,)).fetchone()[0] == 1
    with client.session_transaction() as sess:
        sess["user_id"] = admin_id
    assert client.post("/admin", data={"action": "unblock", "user_id": str(user_id)}).status_code == 400


def test_seed_has_requested_demo_state(client):
    seed(flask_app.config["DATABASE"])
    response = client.get("/")
    assert response.status_code == 200 and b"Vintage camera" in response.data
    with sqlite3.connect(flask_app.config["DATABASE"]) as connection:
        assert connection.execute("SELECT count(*) FROM users WHERE role = 'user'").fetchone()[0] == 4
        assert connection.execute("SELECT count(*) FROM lots").fetchone()[0] == 6


def test_migration_converts_roles_without_losing_auction_data(tmp_path):
    path = tmp_path / "old.db"
    connection = sqlite3.connect(path)
    connection.executescript("""
        CREATE TABLE users (id INTEGER PRIMARY KEY AUTOINCREMENT, email TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL, role TEXT NOT NULL CHECK(role IN ('buyer','seller','admin')),
            is_blocked INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
        CREATE TABLE lots (id INTEGER PRIMARY KEY, seller_id INTEGER NOT NULL REFERENCES users(id),
            title TEXT NOT NULL, description TEXT NOT NULL, start_price REAL NOT NULL, bid_step REAL NOT NULL,
            current_price REAL NOT NULL, closes_at TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'active',
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
        CREATE TABLE bids (id INTEGER PRIMARY KEY, lot_id INTEGER NOT NULL REFERENCES lots(id),
            bidder_id INTEGER NOT NULL REFERENCES users(id), amount REAL NOT NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
        INSERT INTO users (id,email,password_hash,role) VALUES (1,'seller@example.com','hash','seller');
        INSERT INTO users (id,email,password_hash,role) VALUES (2,'buyer@example.com','hash','buyer');
        INSERT INTO lots (id,seller_id,title,description,start_price,bid_step,current_price,closes_at)
            VALUES (3,1,'Saved lot','Saved',10,2,12,'2099-01-01T00:00:00+00:00');
        INSERT INTO bids (id,lot_id,bidder_id,amount) VALUES (4,3,2,12);
    """)
    connection.commit()
    connection.close()
    migrate(path)
    with sqlite3.connect(path) as connection:
        assert connection.execute("SELECT role FROM users WHERE id = 1").fetchone()[0] == "user"
        assert connection.execute("SELECT role FROM users WHERE id = 2").fetchone()[0] == "user"
        assert connection.execute("SELECT id, seller_id FROM lots").fetchone() == (3, 1)
        assert connection.execute("SELECT id, bidder_id FROM bids").fetchone() == (4, 2)
