"""Tests for in-app notifications: a user is told when someone outbids them."""
import sqlite3

from app import app as flask_app
from test_app import add_user, client, lot_id, post  # noqa: F401  (client is a pytest fixture)


def query(sql, params=()):
    with sqlite3.connect(flask_app.config["DATABASE"]) as connection:
        return connection.execute(sql, params).fetchall()


def switch_to(client, user_id):
    with client.session_transaction() as sess:
        sess["user_id"] = user_id
        sess["csrf_token"] = "test-token"


def bid(client, user_id, lot, amount):
    """Pay the lot's deposit once, then place a bid as this user."""
    switch_to(client, user_id)
    post(client, f"/lots/{lot}/deposit")
    post(client, f"/lots/{lot}/bid", {"amount": str(amount)})


def test_outbid_user_gets_a_notification_with_the_new_price(client):
    seller = add_user("seller@example.com")
    lot = lot_id("Brass lamp", seller)  # start price 10, step 2
    alice, bob = add_user("alice@example.com"), add_user("bob@example.com")

    bid(client, alice, lot, 10)
    assert query("SELECT count(*) FROM notifications")[0][0] == 0  # the first bid outbids nobody
    bid(client, bob, lot, 14)

    rows = query("SELECT user_id, lot_id, notification_type, is_read, message FROM notifications")
    assert len(rows) == 1
    user_id, lot_ref, kind, is_read, message = rows[0]
    assert (user_id, lot_ref, kind, is_read) == (alice, lot, "outbid", 0)
    assert "Brass lamp" in message and "14.00" in message


def test_raising_your_own_bid_does_not_notify_you_and_new_leader_is_not_notified(client):
    lot = lot_id("Desk", add_user("seller@example.com"))
    alice, bob = add_user("alice@example.com"), add_user("bob@example.com")

    bid(client, alice, lot, 10)
    bid(client, alice, lot, 12)  # outbidding yourself is not news
    assert query("SELECT count(*) FROM notifications")[0][0] == 0

    bid(client, bob, lot, 14)
    assert query("SELECT user_id FROM notifications") == [(alice,)]  # only the previous leader


def test_notification_page_unread_count_and_ownership_of_mark_read(client):
    lot = lot_id("Clock", add_user("seller@example.com"))
    alice, bob = add_user("alice@example.com"), add_user("bob@example.com")
    bid(client, alice, lot, 10)
    bid(client, bob, lot, 12)
    note_id = query("SELECT id FROM notifications")[0][0]

    # Alice sees the unread badge and the message; Bob has nothing.
    switch_to(client, alice)
    assert b'notification-count">1<' in client.get("/").data
    page = client.get("/notifications").get_data(as_text=True)
    assert "outbid" in page and "Clock" in page and "Unread" in page
    switch_to(client, bob)
    assert b"You have no notifications yet" in client.get("/notifications").data

    # Bob cannot mark Alice's notification as read; Alice can.
    post(client, f"/notifications/{note_id}/read")
    assert query("SELECT is_read FROM notifications WHERE id = ?", (note_id,)) == [(0,)]
    switch_to(client, alice)
    post(client, f"/notifications/{note_id}/read")
    assert query("SELECT is_read FROM notifications WHERE id = ?", (note_id,)) == [(1,)]
    assert b"notification-count" not in client.get("/").data

    # Guests are sent to log in.
    client.post("/logout", data={"csrf_token": "test-token"})
    assert client.get("/notifications").status_code == 302
