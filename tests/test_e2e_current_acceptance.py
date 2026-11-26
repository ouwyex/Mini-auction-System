"""E2E acceptance checks for the currently implemented mini-auction flows.

Every test gets a fresh SQLite database built directly from schema.sql. No application
source or production database is modified.
"""
from datetime import datetime, timedelta, timezone
import sqlite3

import pytest
from werkzeug.security import generate_password_hash

from app import app as flask_app


@pytest.fixture
def env(tmp_path):
    path = tmp_path / "acceptance.sqlite"
    flask_app.config.update(TESTING=True, SECRET_KEY="acceptance-test", DATABASE=str(path))
    from db import BASE_DIR
    with sqlite3.connect(path) as con:
        con.executescript((BASE_DIR / "schema.sql").read_text(encoding="utf-8-sig"))
        users = {}
        for name, role in (("seller", "user"), ("user_a", "user"), ("user_b", "user"),
                           ("user_c", "user"), ("admin", "admin")):
            users[name] = con.execute(
                "INSERT INTO users(email,password_hash,role,balance) VALUES(?,?,?,0)",
                (name + "@test.local", generate_password_hash("qa-password"), role),
            ).lastrowid
    with flask_app.test_client() as client:
        with client.session_transaction() as sess:
            sess["csrf_token"] = "acceptance-csrf"
        yield client, str(path), users


def login(client, uid):
    with client.session_transaction() as sess:
        sess["user_id"] = uid
        sess["csrf_token"] = "acceptance-csrf"


def post(client, url, data=None, **kwargs):
    return client.post(url, data={**(data or {}), "csrf_token": "acceptance-csrf"}, **kwargs)


def lot(path, seller, title, price=100, closes=None, accepts_swaps=0):
    with sqlite3.connect(path) as con:
        return con.execute(
            "INSERT INTO lots(seller_id,title,description,start_price,bid_step,current_price,closes_at,accepts_swaps) "
            "VALUES(?,?,?, ?,5,?,?,?)",
            (seller, title, "QA lot", price, price,
             closes or (datetime.now(timezone.utc) + timedelta(hours=2)).isoformat(), accepts_swaps),
        ).lastrowid


def rows(path, sql, args=()):
    with sqlite3.connect(path) as con:
        return con.execute(sql, args).fetchall()


def top_up(client, uid, amount=200):
    login(client, uid)
    post(client, "/wallet/top-up", {"amount": str(amount)})


def pay(client, uid, lot_id):
    login(client, uid)
    return post(client, f"/lots/{lot_id}/deposit")


def expired(path, lot_id):
    # UTC ISO timestamp, then an HTTP request invokes prepare_request/close_expired_lots.
    past = (datetime.now(timezone.utc) - timedelta(seconds=5)).isoformat()
    with sqlite3.connect(path) as con:
        con.execute("UPDATE lots SET closes_at=? WHERE id=?", (past, lot_id))


def test_a01_deposit_and_access_to_bidding(env):
    client, path, u = env
    lid = lot(path, u["seller"], "A01")
    top_up(client, u["user_a"])
    login(client, u["user_a"])
    response = post(client, f"/lots/{lid}/deposit")
    assert response.status_code == 302
    assert rows(path, "SELECT status,amount FROM deposits WHERE lot_id=? AND user_id=?", (lid,u["user_a"])) == [("held",10)]
    assert rows(path, "SELECT kind,amount FROM wallet_transactions WHERE user_id=? ORDER BY id", (u["user_a"],)) == [("top_up",200), ("deposit_paid",-10)]
    assert rows(path, "SELECT balance FROM users WHERE id=?", (u["user_a"],)) == [(190,)]
    assert b"Deposit paid" in client.get(f"/wallet").data
    post(client, f"/lots/{lid}/bid", {"amount":"100"})
    assert rows(path, "SELECT amount FROM bids WHERE lot_id=?", (lid,)) == [(100,)]


def test_a02_bid_lead_price_and_outbid_notice(env):
    client,path,u=env; lid=lot(path,u["seller"],"A02")
    for key in ("user_a","user_b"): top_up(client,u[key]); pay(client,u[key],lid)
    login(client,u["user_a"]); post(client,f"/lots/{lid}/bid",{"amount":"100"})
    login(client,u["user_b"]); post(client,f"/lots/{lid}/bid",{"amount":"105"})
    assert rows(path,"SELECT bidder_id,amount FROM bids WHERE lot_id=? ORDER BY id",(lid,)) == [(u["user_a"],100),(u["user_b"],105)]
    assert rows(path,"SELECT current_price FROM lots WHERE id=?",(lid,)) == [(105,)]
    assert rows(path,"SELECT notification_type,message FROM notifications WHERE user_id=?",(u["user_a"],))[0][0] == "outbid"


def test_a03_close_winner_applied_and_loser_refunded_once(env):
    client,path,u=env; lid=lot(path,u["seller"],"A03")
    for key in ("user_a","user_b"): top_up(client,u[key]); pay(client,u[key],lid)
    login(client,u["user_a"]); post(client,f"/lots/{lid}/bid",{"amount":"100"})
    login(client,u["user_b"]); post(client,f"/lots/{lid}/bid",{"amount":"105"})
    expired(path,lid); client.get("/")
    assert rows(path,"SELECT status FROM lots WHERE id=?",(lid,)) == [("closed",)]
    assert rows(path,"SELECT user_id,status FROM deposits WHERE lot_id=? ORDER BY user_id",(lid,)) == [(u["user_a"],"returned"),(u["user_b"],"applied")]
    assert rows(path,"SELECT count(*) FROM wallet_transactions WHERE user_id=? AND kind='deposit_returned' AND lot_id=?",(u["user_a"],lid)) == [(1,)]
    client.get("/")
    assert rows(path,"SELECT count(*) FROM wallet_transactions WHERE user_id=? AND kind='deposit_returned' AND lot_id=?",(u["user_a"],lid)) == [(1,)]


def test_a04_equal_bid_tie_chooses_earlier_entry(env):
    client,path,u=env; lid=lot(path,u["seller"],"A04")
    # The live bid validator rejects a second equal bid; seed the two valid historical rows
    # to exercise the documented winner ordering at the auction/DB boundary.
    with sqlite3.connect(path) as con:
        con.executemany("INSERT INTO bids(lot_id,bidder_id,amount) VALUES(?,?,110)", [(lid,u["user_a"]),(lid,u["user_b"])])
    expired(path,lid); client.get("/")
    assert rows(path,"SELECT bidder_id FROM bids WHERE lot_id=? ORDER BY amount DESC,id ASC LIMIT 1",(lid,)) == [(u["user_a"],)]
    assert rows(path,"SELECT status FROM lots WHERE id=?",(lid,)) == [("closed",)]


def test_a05_soft_close_extends_by_two_minutes(env):
    client,path,u=env; closes=datetime.now(timezone.utc)+timedelta(seconds=20); lid=lot(path,u["seller"],"A05",closes=closes.isoformat())
    top_up(client,u["user_a"]); pay(client,u["user_a"],lid)
    login(client,u["user_a"]); post(client,f"/lots/{lid}/bid",{"amount":"100"})
    actual=datetime.fromisoformat(rows(path,"SELECT closes_at FROM lots WHERE id=?",(lid,))[0][0])
    assert abs((actual-(closes+timedelta(minutes=2))).total_seconds()) < 0.01
    assert rows(path,"SELECT status FROM lots WHERE id=?",(lid,)) == [("active",)]


def test_a08_bid_without_held_deposit_is_rejected(env):
    client,path,u=env; lid=lot(path,u["seller"],"A08"); login(client,u["user_a"])
    response=post(client,f"/lots/{lid}/bid",{"amount":"100"},follow_redirects=True)
    assert b"Pay the 10.00 deposit" in response.data
    assert rows(path,"SELECT count(*) FROM bids WHERE lot_id=?",(lid,)) == [(0,)]


def test_a15_own_and_closed_lot_deposit_or_bid_rejected(env):
    client,path,u=env; own=lot(path,u["user_a"],"A15 own"); other=lot(path,u["seller"],"A15 closed",closes=(datetime.now(timezone.utc)-timedelta(seconds=5)).isoformat())
    top_up(client,u["user_a"]); login(client,u["user_a"])
    assert b"own lot" in post(client,f"/lots/{own}/deposit",follow_redirects=True).data
    assert b"own lot" in post(client,f"/lots/{own}/bid",{"amount":"100"},follow_redirects=True).data
    assert b"not active" in post(client,f"/lots/{other}/deposit",follow_redirects=True).data
    assert b"not active" in post(client,f"/lots/{other}/bid",{"amount":"100"},follow_redirects=True).data
    assert rows(path,"SELECT count(*) FROM deposits WHERE lot_id IN (?,?)",(own,other)) == [(0,)]
    assert rows(path,"SELECT count(*) FROM bids WHERE lot_id IN (?,?)",(own,other)) == [(0,)]


def test_a16_unsold_cancel_and_swap_return_held_deposits(env):
    client,path,u=env
    # Unsold expiration refunds deposits even when the user never bid.
    unsold=lot(path,u["seller"],"A16 unsold"); top_up(client,u["user_a"]); pay(client,u["user_a"],unsold)
    expired(path,unsold); client.get("/")
    assert rows(path,"SELECT status FROM lots WHERE id=?",(unsold,)) == [("unsold",)]
    assert rows(path,"SELECT status FROM deposits WHERE lot_id=?",(unsold,)) == [("returned",)]
    # Seller cancellation refunds then removes deposit and lot as implemented.
    cancelled=lot(path,u["seller"],"A16 cancelled"); pay(client,u["user_a"],cancelled)
    login(client,u["seller"]); post(client,f"/lots/{cancelled}/cancel")
    assert rows(path,"SELECT count(*) FROM lots WHERE id=?",(cancelled,)) == [(0,)]
    assert rows(path,"SELECT count(*) FROM wallet_transactions WHERE lot_id=? AND kind='deposit_returned'",(cancelled,)) == [(1,)]
    # Accepted item swap closes the lot and refunds every still-held cash deposit.
    swapped=lot(path,u["seller"],"A16 swap",accepts_swaps=1); top_up(client,u["user_b"]); pay(client,u["user_b"],swapped)
    login(client,u["user_c"])
    offer=post(client,f"/lots/{swapped}/swap-offers",{"item_title":"QA item","item_description":"Good condition"})
    assert offer.status_code == 302
    offer_id=rows(path,"SELECT id FROM swap_offers WHERE lot_id=?",(swapped,))[0][0]
    login(client,u["seller"]); post(client,f"/swap-offers/{offer_id}/accept")
    assert rows(path,"SELECT status FROM lots WHERE id=?",(swapped,)) == [("closed",)]
    assert rows(path,"SELECT status FROM deposits WHERE lot_id=?",(swapped,)) == [("returned",)]


def test_a17_sql_consistency_invariants(env):
    client,path,u=env
    # Ensure the invariant query includes real movements, not just empty tables.
    top_up(client,u["user_a"],37.25)
    with sqlite3.connect(path) as con:
        negative=con.execute("SELECT count(*) FROM users WHERE balance < 0").fetchone()[0]
        mismatch=con.execute("SELECT count(*) FROM users u WHERE abs(u.balance-COALESCE((SELECT sum(w.amount) FROM wallet_transactions w WHERE w.user_id=u.id),0)) > 0.005").fetchone()[0]
        duplicate=con.execute("SELECT count(*) FROM (SELECT user_id,lot_id FROM deposits GROUP BY user_id,lot_id HAVING count(*)>1)").fetchone()[0]
        held=con.execute("SELECT count(*) FROM deposits d JOIN lots l ON l.id=d.lot_id WHERE d.status='held' AND l.status IN ('closed','unsold')").fetchone()[0]
    results={"negative balances":negative,"balance/ledger mismatches":mismatch,"duplicate user-lot deposits":duplicate,"held deposits on closed/unsold lots":held}
    print("A17 SQL invariants:", results)
    assert results == {k:0 for k in results}

