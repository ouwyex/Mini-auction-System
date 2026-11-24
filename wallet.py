"""Wallet and deposit helpers.

Rules:
- Before bidding on a lot, a user pays a deposit of 10% of its start price from
  their wallet balance. A user can pay only one deposit per lot (UNIQUE in the database).
- When the lot closes, the winner's deposit is applied to the purchase and every other
  deposit is returned to its owner's balance.
- A balance can never go below zero (checked here and by a CHECK constraint).
- Every change to users.balance writes exactly one wallet_transactions row, so a
  balance always equals the sum of that user's history amounts.

All helpers work inside the caller's transaction and never commit.
"""

TOP_UP = "top_up"
DEPOSIT_PAID = "deposit_paid"
DEPOSIT_RETURNED = "deposit_returned"

LABELS = {
    TOP_UP: "Top-up",
    DEPOSIT_PAID: "Deposit paid",
    DEPOSIT_RETURNED: "Deposit returned",
}
CREDIT_KINDS = {TOP_UP, DEPOSIT_RETURNED}
MAX_TOP_UP = 10000.00
DEPOSIT_RATE = 0.10


class InsufficientFunds(ValueError):
    """Raised when a debit would take a balance below zero."""


def get_balance(database, user_id):
    row = database.execute("SELECT balance FROM users WHERE id = ?", (user_id,)).fetchone()
    return row["balance"] if row else 0.0


def record(database, user_id, kind, amount, description, lot_id=None):
    """Apply one money movement and write its history row. Returns the new balance."""
    if kind not in LABELS:
        raise ValueError("Unknown wallet transaction type.")
    amount = round(float(amount), 2)
    if amount == 0 or (amount > 0) != (kind in CREDIT_KINDS):
        raise ValueError("Wallet amount has the wrong sign for this transaction type.")
    current = get_balance(database, user_id)
    new_balance = round(current + amount, 2)
    if new_balance < 0:
        raise InsufficientFunds(
            f"Not enough balance: the deposit is {abs(amount):.2f} but you have {current:.2f}. "
            "Top up your wallet first."
        )
    database.execute("UPDATE users SET balance = ? WHERE id = ?", (new_balance, user_id))
    database.execute(
        "INSERT INTO wallet_transactions (user_id, kind, amount, balance_after, lot_id, description) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (user_id, kind, amount, new_balance, lot_id, description),
    )
    return new_balance


def top_up(database, user_id, amount):
    """Add demo money to a wallet (there is no real payment provider)."""
    return record(database, user_id, TOP_UP, amount, "Wallet top-up")


def deposit_amount(start_price):
    """10% of the start price, in whole cents and never below 0.01."""
    return max(0.01, round(start_price * DEPOSIT_RATE, 2))


def pay_deposit(database, user_id, lot):
    """Take the lot's deposit from the user's balance and store it as held. Returns the amount."""
    if database.execute("SELECT 1 FROM deposits WHERE lot_id = ? AND user_id = ?", (lot["id"], user_id)).fetchone():
        raise ValueError("You have already paid the deposit for this lot.")
    amount = deposit_amount(lot["start_price"])
    record(database, user_id, DEPOSIT_PAID, -amount, f'Deposit for "{lot["title"]}"', lot["id"])
    database.execute("INSERT INTO deposits (lot_id, user_id, amount) VALUES (?, ?, ?)", (lot["id"], user_id, amount))
    return amount


def _return(database, deposit, title, reason):
    record(database, deposit["user_id"], DEPOSIT_RETURNED, deposit["amount"],
           f'{reason}: "{title}"', deposit["lot_id"])
    database.execute("UPDATE deposits SET status = 'returned' WHERE id = ?", (deposit["id"],))


def settle_lot(database, lot, winner_id, reason="Lot closed"):
    """Close out a lot's deposits: the winner's is applied, all other held deposits are returned."""
    held = database.execute("SELECT * FROM deposits WHERE lot_id = ? AND status = 'held'", (lot["id"],)).fetchall()
    for deposit in held:
        if deposit["user_id"] == winner_id:
            database.execute("UPDATE deposits SET status = 'applied' WHERE id = ?", (deposit["id"],))
        else:
            _return(database, deposit, lot["title"], reason)


def remove_lot_deposits(database, lot, reason):
    """Refund held deposits and delete all deposit rows so the lot can be deleted."""
    held = database.execute("SELECT * FROM deposits WHERE lot_id = ? AND status = 'held'", (lot["id"],)).fetchall()
    for deposit in held:
        _return(database, deposit, lot["title"], reason)
    database.execute("DELETE FROM deposits WHERE lot_id = ?", (lot["id"],))


def user_deposits(database, user_id):
    """The user's deposits with lot titles, newest first, plus the total still held."""
    rows = database.execute(
        "SELECT deposits.lot_id, deposits.amount, deposits.status, lots.title FROM deposits "
        "JOIN lots ON lots.id = deposits.lot_id WHERE deposits.user_id = ? ORDER BY deposits.id DESC",
        (user_id,),
    ).fetchall()
    return rows, round(sum(row["amount"] for row in rows if row["status"] == "held"), 2)


def history(database, user_id, limit=100):
    """Newest history rows first."""
    return database.execute(
        "SELECT id, kind, amount, balance_after, lot_id, description, created_at "
        "FROM wallet_transactions WHERE user_id = ? ORDER BY id DESC LIMIT ?",
        (user_id, limit),
    ).fetchall()
