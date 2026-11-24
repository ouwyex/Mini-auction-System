"""Tests for item swap offers: offering an item instead of money."""
from datetime import datetime, timedelta, timezone
import sqlite3

import pytest

from app import app as flask_app
from db import ensure_schema
from test_app import add_user, client, create_lot, login, lot_id, post  # noqa: F401  (client is a pytest fixture)


def query(sql, params=()):
    with sqlite3.connect(flask_app.config["DATABASE"]) as connection:
        return connection.execute(sql, params).fetchall()


def run(sql, params=()):
    with sqlite3.connect(flask_app.config["DATABASE"]) as connection:
        connection.execute(sql, params)


def switch_to(client, user_id):
    with client.session_transaction() as sess:
        sess["user_id"] = user_id
        sess["csrf_token"] = "test-token"


def swap_lot(seller_id, title="Swap lot", accepts=1):
    """A lot (start price 10, step 2) whose seller accepts item swaps."""
    lot = lot_id(title, seller_id)
    run("UPDATE lots SET accepts_swaps = ? WHERE id = ?", (accepts, lot))
    return lot


def offer(client, user_id, lot, title="Used phone", description="Works well", value="120", **kwargs):
    switch_to(client, user_id)
    return post(client, f"/lots/{lot}/swap-offers",
                {"item_title": title, "item_description": description, "estimated_value": value}, **kwargs)


def offer_id(user_id, lot):
    return query("SELECT id FROM swap_offers WHERE offerer_id = ? AND lot_id = ? ORDER BY id DESC",
                 (user_id, lot))[0][0]


def statuses(lot):
    return dict(query("SELECT offerer_id, status FROM swap_offers WHERE lot_id = ?", (lot,)))


def messages(user_id):
    return [row[0] for row in query("SELECT message FROM notifications WHERE user_id = ? ORDER BY id", (user_id,))]


def test_seller_chooses_whether_a_lot_accepts_swaps_and_the_home_filter_finds_them(client):
    seller = login(client, "seller@example.com")
    assert create_lot(client, title="Plain lot").status_code == 302
    assert create_lot(client, title="Swap friendly", accepts_swaps="1").status_code == 302
    rows = dict(query("SELECT title, accepts_swaps FROM lots"))
    assert rows == {"Plain lot": 0, "Swap friendly": 1}

    # The detail page and the card both say so, and the checkbox can be changed while the lot is untouched.
    plain = query("SELECT id FROM lots WHERE title = 'Plain lot'")[0][0]
    friendly = query("SELECT id FROM lots WHERE title = 'Swap friendly'")[0][0]
    assert "Accepts item swaps" in client.get(f"/lots/{friendly}").get_data(as_text=True)
    assert "Accepts item swaps" not in client.get(f"/lots/{plain}").get_data(as_text=True)
    form = {"title": "Plain lot", "description": "A useful item", "start_price": "10", "bid_step": "2",
            "closes_at": (datetime.now(timezone.utc) + timedelta(days=2)).strftime("%Y-%m-%dT%H:%M"),
            "accepts_swaps": "1"}
    assert post(client, f"/lots/{plain}/edit", form).status_code == 302
    assert query("SELECT accepts_swaps FROM lots WHERE id = ?", (plain,))[0][0] == 1

    only_swaps = client.get("/?swaps=1").get_data(as_text=True)
    assert "Swap friendly" in only_swaps and "Swaps welcome" in only_swaps
    run("UPDATE lots SET accepts_swaps = 0 WHERE id = ?", (plain,))
    only_swaps = client.get("/?swaps=1").get_data(as_text=True)
    assert "Swap friendly" in only_swaps and "Plain lot" not in only_swaps and "1 lot found" in only_swaps
    assert "Plain lot" in client.get("/").get_data(as_text=True)


def test_offer_rules_and_validation(client):
    seller = add_user("seller@example.com")
    lot = swap_lot(seller)
    plain = swap_lot(seller, "Money only", accepts=0)
    alice = add_user("alice@example.com")

    assert offer(client, alice, lot).status_code == 302
    row = query("SELECT item_title, item_description, estimated_value, status FROM swap_offers")[0]
    assert row == ("Used phone", "Works well", 120.0, "pending")
    assert "New swap offer" in messages(seller)[0] and "Used phone" in messages(seller)[0]

    # One pending offer per user and lot; the second is refused with a clear message.
    again = offer(client, alice, lot, title="Another", follow_redirects=True)
    assert b"already have a pending swap offer" in again.data
    assert query("SELECT count(*) FROM swap_offers")[0][0] == 1

    # A lot that does not accept swaps, and the seller's own lot, refuse offers.
    assert b"does not accept item swaps" in offer(client, alice, plain, follow_redirects=True).data
    assert b"cannot offer a swap on your own lot" in offer(client, seller, lot, follow_redirects=True).data

    # Bad input never creates a row. The value is optional.
    bob = add_user("bob@example.com")
    for kwargs, expected in (
        ({"title": " "}, b"name of the item"), ({"title": "x" * 121}, b"120 characters"),
        ({"description": ""}, b"Describe the item"), ({"description": "x" * 1001}, b"1000 characters"),
        ({"value": "abc"}, b"must be a number"), ({"value": "-5"}, b"greater than zero"),
        ({"value": "nan"}, b"greater than zero"),
    ):
        response = offer(client, bob, lot, follow_redirects=True, **kwargs)
        assert expected in response.data
    assert query("SELECT count(*) FROM swap_offers WHERE offerer_id = ?", (bob,))[0][0] == 0
    assert offer(client, bob, lot, value="").status_code == 302
    assert query("SELECT estimated_value FROM swap_offers WHERE offerer_id = ?", (bob,))[0][0] is None

    # Guests must log in, administrators cannot take part, and closed lots refuse offers.
    with client.session_transaction() as sess:
        sess.clear()
        sess["csrf_token"] = "test-token"
    guest = post(client, f"/lots/{lot}/swap-offers", {"item_title": "x", "item_description": "y"})
    assert guest.status_code == 302 and "/login" in guest.headers["Location"]
    admin = add_user("admin@example.com", role="admin")
    assert offer(client, admin, lot).status_code == 403
    run("UPDATE lots SET status = 'closed' WHERE id = ?", (lot,))
    carol = add_user("carol@example.com")
    assert b"not active" in offer(client, carol, lot, follow_redirects=True).data


def test_accepting_an_offer_closes_the_lot_rejects_the_rest_and_returns_deposits(client):
    seller = add_user("seller@example.com")
    lot = swap_lot(seller)  # start price 10, so the deposit is 1.00
    alice, bob, carol = (add_user(f"{name}@example.com") for name in ("alice", "bob", "carol"))

    # Alice pays the deposit and bids with money; Bob and Carol offer items.
    switch_to(client, alice)
    post(client, f"/lots/{lot}/deposit")
    post(client, f"/lots/{lot}/bid", {"amount": "10"})
    assert query("SELECT balance FROM users WHERE id = ?", (alice,))[0][0] == 999
    offer(client, bob, lot, title="Road bike")
    offer(client, carol, lot, title="Guitar")
    bob_offer, carol_offer = offer_id(bob, lot), offer_id(carol, lot)

    # Nobody except the seller can answer offers.
    switch_to(client, bob)
    assert post(client, f"/swap-offers/{bob_offer}/accept").status_code == 403
    switch_to(client, alice)
    assert post(client, f"/swap-offers/{carol_offer}/reject").status_code == 403
    assert statuses(lot) == {bob: "pending", carol: "pending"}

    switch_to(client, seller)
    detail = client.get(f"/lots/{lot}").get_data(as_text=True)
    assert "Road bike" in detail and "Guitar" in detail and "Accept" in detail
    response = post(client, f"/swap-offers/{bob_offer}/accept", follow_redirects=True)
    assert b"Swap accepted" in response.data

    assert query("SELECT status FROM lots WHERE id = ?", (lot,))[0][0] == "closed"
    assert statuses(lot) == {bob: "accepted", carol: "rejected"}
    # The bidder's deposit came back in full and shows in the wallet history.
    assert query("SELECT balance FROM users WHERE id = ?", (alice,))[0][0] == 1000
    assert query("SELECT status FROM deposits WHERE user_id = ?", (alice,))[0][0] == "returned"
    last = query("SELECT kind, amount, description FROM wallet_transactions WHERE user_id = ? ORDER BY id DESC",
                 (alice,))[0]
    assert last[0] == "deposit_returned" and last[1] == 1.0 and "Lot swapped" in last[2]
    # Everyone involved is told what happened.
    assert any("was accepted" in text and "seller@example.com" in text for text in messages(bob))
    assert any("not chosen" in text for text in messages(carol))
    assert any("swapped for an item" in text and "1.00" in text for text in messages(alice))

    # The lot page shows the swap instead of a bidding winner; nobody "won" in My bids.
    page = client.get(f"/lots/{lot}").get_data(as_text=True)
    assert "swapped for" in page and "Road bike" in page and "Winner:" not in page
    switch_to(client, alice)
    bids_page = client.get("/my-bids").get_data(as_text=True)
    assert "swapped" in bids_page and "Won" not in bids_page
    assert "swapped" in client.get("/?status=closed").get_data(as_text=True)

    # The lot is finished: a second accept, a late bid, and a late offer are all refused.
    switch_to(client, seller)
    assert b"already been answered" in post(client, f"/swap-offers/{carol_offer}/accept", follow_redirects=True).data
    switch_to(client, alice)
    assert b"not active" in post(client, f"/lots/{lot}/bid", {"amount": "50"}, follow_redirects=True).data
    assert query("SELECT count(*) FROM swap_offers WHERE status = 'accepted'")[0][0] == 1


def test_reject_and_withdraw_keep_the_lot_open_and_allow_a_new_offer(client):
    seller = add_user("seller@example.com")
    lot = swap_lot(seller)
    alice, bob = add_user("alice@example.com"), add_user("bob@example.com")
    offer(client, alice, lot, title="Lamp")
    offer(client, bob, lot, title="Chair")

    switch_to(client, seller)
    assert b"Swap offer rejected" in post(
        client, f"/swap-offers/{offer_id(alice, lot)}/reject", follow_redirects=True).data
    assert statuses(lot) == {alice: "rejected", bob: "pending"}
    assert query("SELECT status FROM lots WHERE id = ?", (lot,))[0][0] == "active"
    assert any("rejected" in text for text in messages(alice))

    # Bob can withdraw his own offer, but nobody else's.
    switch_to(client, alice)
    assert post(client, f"/swap-offers/{offer_id(bob, lot)}/withdraw").status_code == 403
    switch_to(client, bob)
    assert b"withdrawn" in post(client, f"/swap-offers/{offer_id(bob, lot)}/withdraw", follow_redirects=True).data
    assert statuses(lot)[bob] == "withdrawn"

    # After a rejection or a withdrawal a new offer is allowed again (the unique index only covers pending offers).
    assert offer(client, alice, lot, title="Better lamp").status_code == 302
    assert offer(client, bob, lot, title="Better chair").status_code == 302
    pending = query("SELECT count(*) FROM swap_offers WHERE lot_id = ? AND status = 'pending'", (lot,))[0][0]
    assert pending == 2

    # The offerer sees the status of an earlier offer, and My swaps lists all of them.
    page = client.get("/my-swaps").get_data(as_text=True)
    assert "Better chair" in page and "withdrawn" in page


def test_unanswered_offers_expire_when_the_lot_closes_by_time(client):
    seller = add_user("seller@example.com")
    lot = swap_lot(seller)
    alice, bob = add_user("alice@example.com"), add_user("bob@example.com")
    switch_to(client, bob)
    post(client, f"/lots/{lot}/deposit")
    post(client, f"/lots/{lot}/bid", {"amount": "10"})
    offer(client, alice, lot)

    past = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
    run("UPDATE lots SET closes_at = ? WHERE id = ?", (past, lot))
    client.get("/")  # the next request closes the lot

    # The money auction ended normally: Bob won and his deposit was applied.
    assert query("SELECT status FROM lots WHERE id = ?", (lot,))[0][0] == "closed"
    assert query("SELECT status FROM deposits WHERE user_id = ?", (bob,))[0][0] == "applied"
    assert statuses(lot) == {alice: "expired"}
    assert any("ended before the seller answered" in text for text in messages(alice))
    # An expired offer cannot be accepted any more.
    switch_to(client, seller)
    response = post(client, f"/swap-offers/{offer_id(alice, lot)}/accept", follow_redirects=True)
    assert b"already been answered" in response.data
    assert "Winner:" in client.get(f"/lots/{lot}").get_data(as_text=True)


def test_cancelling_or_deleting_a_lot_removes_its_offers(client):
    seller = add_user("seller@example.com")
    alice = add_user("alice@example.com")
    cancelled, removed = swap_lot(seller, "Cancelled"), swap_lot(seller, "Removed")
    offer(client, alice, cancelled)
    offer(client, alice, removed)

    # A lot with offers cannot be edited, because the offers were made under its current terms.
    switch_to(client, seller)
    edit = client.get(f"/lots/{cancelled}/edit")
    assert edit.status_code == 403 and b"swap offers cannot be edited" in edit.data

    post(client, f"/lots/{cancelled}/cancel")
    assert query("SELECT count(*) FROM lots WHERE id = ?", (cancelled,))[0][0] == 0
    assert query("SELECT count(*) FROM swap_offers WHERE lot_id = ?", (cancelled,))[0][0] == 0
    assert any("Lot cancelled" in text for text in messages(alice))

    admin = add_user("admin@example.com", role="admin")
    switch_to(client, admin)
    post(client, "/admin", {"action": "delete_lot", "lot_id": str(removed)})
    assert query("SELECT count(*) FROM lots WHERE id = ?", (removed,))[0][0] == 0
    assert query("SELECT count(*) FROM swap_offers")[0][0] == 0
    assert any("Lot removed" in text for text in messages(alice))


def test_database_rules_for_swap_offers(client):
    seller = add_user("seller@example.com")
    lot = swap_lot(seller)
    alice = add_user("alice@example.com")

    def insert(status="pending", value=None, offerer=alice):
        run("INSERT INTO swap_offers (lot_id, offerer_id, item_title, item_description, estimated_value, status) "
            "VALUES (?, ?, 'Item', 'Description', ?, ?)", (lot, offerer, value, status))

    insert()
    with pytest.raises(sqlite3.IntegrityError):   # a second pending offer by the same user
        insert()
    insert("rejected")                            # old answered offers do not block a new one
    with pytest.raises(sqlite3.IntegrityError):   # unknown status
        insert("maybe", offerer=add_user("bob@example.com"))
    with pytest.raises(sqlite3.IntegrityError):   # value must be positive when given
        insert(value=0, offerer=add_user("carol@example.com"))
    with pytest.raises(sqlite3.IntegrityError):   # accepts_swaps is only 0 or 1
        run("UPDATE lots SET accepts_swaps = 2 WHERE id = ?", (lot,))
    insert("accepted", offerer=add_user("dave@example.com"))
    with pytest.raises(sqlite3.IntegrityError):   # at most one accepted offer per lot
        insert("accepted", offerer=add_user("erin@example.com"))


def test_an_older_database_is_upgraded_without_losing_lots(tmp_path):
    path = tmp_path / "old.db"
    old = sqlite3.connect(path)
    old.row_factory = sqlite3.Row
    old.executescript(
        "CREATE TABLE users (id INTEGER PRIMARY KEY AUTOINCREMENT, email TEXT NOT NULL UNIQUE, "
        "password_hash TEXT NOT NULL, role TEXT NOT NULL, is_blocked INTEGER NOT NULL DEFAULT 0, "
        "created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);"
        "CREATE TABLE lots (id INTEGER PRIMARY KEY AUTOINCREMENT, seller_id INTEGER NOT NULL, title TEXT NOT NULL, "
        "description TEXT NOT NULL, start_price REAL NOT NULL, bid_step REAL NOT NULL, current_price REAL NOT NULL, "
        "closes_at TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'active', "
        "created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);"
        "INSERT INTO users (email, password_hash, role) VALUES ('a@example.com', 'x', 'user');"
        "INSERT INTO lots (seller_id, title, description, start_price, bid_step, current_price, closes_at) "
        "VALUES (1, 'Old lot', 'Kept', 5, 1, 5, '2030-01-01T00:00:00+00:00');"
    )
    ensure_schema(old)
    ensure_schema(old)  # running it twice is harmless
    assert [tuple(row) for row in old.execute("SELECT title, accepts_swaps FROM lots")] == [("Old lot", 0)]
    assert old.execute("SELECT count(*) FROM swap_offers").fetchone()[0] == 0
    old.close()
