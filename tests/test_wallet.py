"""Tests for wallet history: every top-up and deposit movement is recorded and adds up."""
from datetime import datetime, timedelta, timezone
import sqlite3

from app import app as flask_app
from test_app import add_user, client, lot_id, post  # noqa: F401  (client is a pytest fixture)


def query(sql, params=()):
    with sqlite3.connect(flask_app.config["DATABASE"]) as connection:
        return connection.execute(sql, params).fetchall()


def balance(user_id):
    return query("SELECT balance FROM users WHERE id = ?", (user_id,))[0][0]


def history(user_id):
    return query("SELECT kind, amount, balance_after FROM wallet_transactions WHERE user_id = ? ORDER BY id", (user_id,))


def switch_to(client, user_id):
    with client.session_transaction() as sess:
        sess["user_id"] = user_id
        sess["csrf_token"] = "test-token"


def funded_user(client, email, amount):
    """A user with an empty wallet who tops up through the real top-up route."""
    user_id = add_user(email, balance=0)
    switch_to(client, user_id)
    post(client, "/wallet/top-up", {"amount": str(amount)})
    return user_id


def close_lot(lot):
    past = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
    with sqlite3.connect(flask_app.config["DATABASE"]) as connection:
        connection.execute("UPDATE lots SET closes_at = ? WHERE id = ?", (past, lot))


def assert_history_matches_balances():
    """The core wallet rule: each balance equals the sum of its history and is never negative."""
    for user_id, current in query("SELECT id, balance FROM users"):
        rows = history(user_id)
        assert current >= 0
        assert round(sum(row[1] for row in rows), 2) == round(current, 2)
        if rows:
            assert rows[-1][2] == round(current, 2)


def test_top_up_is_recorded_and_shown_on_the_wallet_page(client):
    user = add_user("saver@example.com", balance=0)
    switch_to(client, user)
    post(client, "/wallet/top-up", {"amount": "50.25"})
    post(client, "/wallet/top-up", {"amount": "10"})
    assert history(user) == [("top_up", 50.25, 50.25), ("top_up", 10.0, 60.25)]

    page = client.get("/wallet").get_data(as_text=True)
    assert "Transaction history" in page and "+50.25" in page and "+10.00" in page and "Balance 60.25" in page

    # A rejected amount changes neither the balance nor the history.
    post(client, "/wallet/top-up", {"amount": "-5"})
    assert balance(user) == 60.25 and len(history(user)) == 2
    assert_history_matches_balances()


def test_paying_a_deposit_is_recorded_and_too_little_money_writes_nothing(client):
    seller = add_user("seller@example.com", balance=0)
    lot = lot_id(seller_id=seller)  # start price 10, so the deposit is 1.00
    buyer = funded_user(client, "buyer@example.com", 5)
    poor = add_user("poor@example.com", balance=0)

    post(client, f"/lots/{lot}/deposit")
    assert history(buyer) == [("top_up", 5.0, 5.0), ("deposit_paid", -1.0, 4.0)]
    assert balance(buyer) == 4
    assert b"Deposit paid" in client.get("/wallet").data

    switch_to(client, poor)
    response = post(client, f"/lots/{lot}/deposit", follow_redirects=True)
    assert b"Not enough balance" in response.data
    assert history(poor) == [] and balance(poor) == 0
    assert query("SELECT count(*) FROM deposits WHERE user_id = ?", (poor,))[0][0] == 0
    assert_history_matches_balances()


def test_closing_returns_losing_deposits_and_the_history_always_adds_up(client):
    seller = add_user("seller@example.com", balance=0)
    lot = lot_id(seller_id=seller)
    winner = funded_user(client, "winner@example.com", 20)
    loser = funded_user(client, "loser@example.com", 20)
    lurker = funded_user(client, "lurker@example.com", 20)  # pays a deposit but never bids

    for user, amount in ((loser, "10"), (winner, "12"), (lurker, None)):
        switch_to(client, user)
        post(client, f"/lots/{lot}/deposit")
        if amount:
            post(client, f"/lots/{lot}/bid", {"amount": amount})
    assert balance(winner) == balance(loser) == balance(lurker) == 19

    close_lot(lot)
    client.get("/")
    client.get("/")  # a second pass must not return anything twice

    # The winner keeps the deposit as part of the purchase, so no money comes back to them.
    assert history(winner) == [("top_up", 20.0, 20.0), ("deposit_paid", -1.0, 19.0)]
    assert [row[0] for row in history(loser)] == ["top_up", "deposit_paid", "deposit_returned"]
    assert [row[0] for row in history(lurker)] == ["top_up", "deposit_paid", "deposit_returned"]
    assert balance(winner) == 19 and balance(loser) == 20 and balance(lurker) == 20
    assert query("SELECT count(*) FROM wallet_transactions WHERE kind = 'deposit_returned'")[0][0] == 2
    assert_history_matches_balances()
