"""QA tests written against the team requirements (FR-01, FR-02, BR-01, concurrency)."""
from datetime import datetime, timedelta, timezone
import sqlite3
import threading

from app import app as flask_app
from test_app import client, post, login, lot_id, add_user  # noqa: F401


def db():
    return sqlite3.connect(flask_app.config["DATABASE"], timeout=10)


def test_tc01_fr01_bid_below_minimum_is_rejected(client):
    lid = lot_id()
    login(client, "buyer@example.com")
    post(client, f"/lots/{lid}/bid", {"amount": "10"})          # first bid = start price
    post(client, f"/lots/{lid}/bid", {"amount": "11"})          # needs >= 12 (step 2)
    with db() as c:
        assert c.execute("SELECT COUNT(*) FROM bids").fetchone()[0] == 1


def test_tc02_fr02_bid_in_last_30_seconds_extends_by_2_minutes(client):
    closes = datetime.now(timezone.utc) + timedelta(seconds=15)
    lid = lot_id(closes=closes.isoformat())
    login(client, "buyer@example.com")
    post(client, f"/lots/{lid}/bid", {"amount": "10"})
    with db() as c:
        new_close = datetime.fromisoformat(c.execute("SELECT closes_at FROM lots").fetchone()[0])
    assert new_close >= closes + timedelta(seconds=100), "closing time was NOT extended"


def test_tc03_bid_time_is_set_by_server(client):
    lid = lot_id()
    login(client, "buyer@example.com")
    post(client, f"/lots/{lid}/bid", {"amount": "10", "created_at": "2025-10-12 19:59:55"})
    with db() as c:
        stamp = c.execute("SELECT created_at FROM bids").fetchone()[0]
    assert stamp.startswith(str(datetime.now(timezone.utc).year))


def test_tc04_br01_bid_requires_deposit(client):
    lid = lot_id()
    login(client, "buyer@example.com")
    post(client, f"/lots/{lid}/bid", {"amount": "10"})
    with db() as c:
        tables = {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert "deposits" in tables, "no deposit table / no 10% rule"


def test_tc05_two_parallel_bids_only_one_wins(client):
    lid = lot_id()
    a = add_user("a@example.com"); b = add_user("b@example.com")
    results = []
    def bid(uid):
        with flask_app.test_client() as c:
            with c.session_transaction() as s:
                s["user_id"] = uid; s["csrf_token"] = "test-token"
            results.append(c.post(f"/lots/{lid}/bid", data={"amount": "10", "csrf_token": "test-token"}).status_code)
    ts = [threading.Thread(target=bid, args=(u,)) for u in (a, b)]
    [t.start() for t in ts]; [t.join() for t in ts]
    with db() as c:
        n = c.execute("SELECT COUNT(*) FROM bids").fetchone()[0]
        price = c.execute("SELECT current_price FROM lots").fetchone()[0]
    assert n == 1 and price == 10   # exactly one bid accepted
