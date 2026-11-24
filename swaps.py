"""Item swap offers.

Rules:
- A seller can mark a lot "accepts swaps" when creating it. Other users may then offer one of
  their own items instead of bidding money. The seller reads the offers and chooses.
- An offer needs no deposit, because no money moves. It stays `pending` until the seller
  accepts or rejects it, the offerer withdraws it, or the lot closes (then it is `expired`).
- Accepting an offer closes the lot immediately. Every other pending offer is rejected and
  every held deposit is returned in full. The lot keeps status `closed`; the accepted row in
  `swap_offers` is what marks it as swapped.
- A user has at most one pending offer per lot and a lot has at most one accepted offer
  (both enforced by partial unique indexes in schema.sql).

The site only records the agreement. It does not check the item, its value, or the hand-over.

All helpers work inside the caller's transaction and never commit.
"""
import math

import notifications
import wallet

PENDING = "pending"
ACCEPTED = "accepted"
REJECTED = "rejected"
WITHDRAWN = "withdrawn"
EXPIRED = "expired"

MAX_TITLE = 120
MAX_DESCRIPTION = 1000
MAX_VALUE = 1_000_000.00


def parse_offer(title, description, raw_value):
    """Validate the offer form. Returns (title, description, value); value may be None."""
    title = (title or "").strip()
    description = (description or "").strip()
    raw_value = (raw_value or "").strip()
    if not title:
        raise ValueError("Enter the name of the item you offer.")
    if len(title) > MAX_TITLE:
        raise ValueError(f"The item name must be {MAX_TITLE} characters or fewer.")
    if not description:
        raise ValueError("Describe the item you offer.")
    if len(description) > MAX_DESCRIPTION:
        raise ValueError(f"The description must be {MAX_DESCRIPTION} characters or fewer.")
    value = None
    if raw_value:
        try:
            value = round(float(raw_value), 2)
        except ValueError:
            raise ValueError("The estimated value must be a number.") from None
        if not math.isfinite(value) or value <= 0 or value > MAX_VALUE:
            raise ValueError(f"The estimated value must be greater than zero and at most {MAX_VALUE:.2f}.")
    return title, description, value


def get_offer(database, offer_id):
    """An offer together with its lot's seller, title and status."""
    return database.execute(
        "SELECT swap_offers.*, lots.seller_id, lots.title AS lot_title, lots.status AS lot_status, "
        "lots.closes_at AS lot_closes_at, users.email AS offerer_email "
        "FROM swap_offers JOIN lots ON lots.id = swap_offers.lot_id "
        "JOIN users ON users.id = swap_offers.offerer_id WHERE swap_offers.id = ?",
        (offer_id,),
    ).fetchone()


def create_offer(database, lot, offerer_id, title, description, value):
    """Store a pending offer and tell the seller. Returns the new offer id."""
    existing = database.execute(
        "SELECT 1 FROM swap_offers WHERE lot_id = ? AND offerer_id = ? AND status = ?",
        (lot["id"], offerer_id, PENDING),
    ).fetchone()
    if existing:
        raise ValueError("You already have a pending swap offer on this lot. Withdraw it to send a new one.")
    cursor = database.execute(
        "INSERT INTO swap_offers (lot_id, offerer_id, item_title, item_description, estimated_value) "
        "VALUES (?, ?, ?, ?, ?)",
        (lot["id"], offerer_id, title, description, value),
    )
    notifications.create_notification(
        database, lot["seller_id"],
        f"New swap offer on '{lot['title']}': {title}.",
        lot_id=lot["id"],
    )
    return cursor.lastrowid


def accept_offer(database, offer, lot):
    """Accept one offer: close the lot as swapped, reject the rest, return every deposit."""
    database.execute(
        "UPDATE swap_offers SET status = ?, resolved_at = CURRENT_TIMESTAMP WHERE id = ?",
        (ACCEPTED, offer["id"]),
    )
    database.execute("UPDATE lots SET status = 'closed' WHERE id = ?", (lot["id"],))
    notifications.create_notification(
        database, offer["offerer_id"],
        f"Your swap offer on '{lot['title']}' was accepted. Contact the seller ({_email(database, lot['seller_id'])}) "
        "to arrange the exchange.",
        lot_id=lot["id"],
    )
    others = database.execute(
        "SELECT id, offerer_id FROM swap_offers WHERE lot_id = ? AND status = ? AND id <> ?",
        (lot["id"], PENDING, offer["id"]),
    ).fetchall()
    for other in others:
        database.execute(
            "UPDATE swap_offers SET status = ?, resolved_at = CURRENT_TIMESTAMP WHERE id = ?",
            (REJECTED, other["id"]),
        )
        notifications.create_notification(
            database, other["offerer_id"],
            f"Your swap offer on '{lot['title']}' was not chosen: the seller accepted another offer.",
            lot_id=lot["id"],
        )
    # Nobody wins the auction, so every held deposit goes back to its owner.
    depositors = database.execute(
        "SELECT user_id, amount FROM deposits WHERE lot_id = ? AND status = 'held'", (lot["id"],)
    ).fetchall()
    wallet.settle_lot(database, lot, None, "Lot swapped")
    for deposit in depositors:
        notifications.create_notification(
            database, deposit["user_id"],
            f"'{lot['title']}' was swapped for an item, so the auction ended. "
            f"Your deposit of {deposit['amount']:.2f} was returned.",
            lot_id=lot["id"],
        )


def reject_offer(database, offer, lot):
    database.execute(
        "UPDATE swap_offers SET status = ?, resolved_at = CURRENT_TIMESTAMP WHERE id = ?",
        (REJECTED, offer["id"]),
    )
    notifications.create_notification(
        database, offer["offerer_id"],
        f"Your swap offer on '{lot['title']}' was rejected by the seller.",
        lot_id=lot["id"],
    )


def withdraw_offer(database, offer):
    database.execute(
        "UPDATE swap_offers SET status = ?, resolved_at = CURRENT_TIMESTAMP WHERE id = ?",
        (WITHDRAWN, offer["id"]),
    )


def expire_lot_offers(database, lot):
    """Called when a lot closes by time: pending offers can no longer be accepted."""
    pending = database.execute(
        "SELECT id, offerer_id FROM swap_offers WHERE lot_id = ? AND status = ?", (lot["id"], PENDING)
    ).fetchall()
    for offer in pending:
        database.execute(
            "UPDATE swap_offers SET status = ?, resolved_at = CURRENT_TIMESTAMP WHERE id = ?",
            (EXPIRED, offer["id"]),
        )
        notifications.create_notification(
            database, offer["offerer_id"],
            f"The auction for '{lot['title']}' ended before the seller answered your swap offer.",
            lot_id=lot["id"],
        )


def remove_lot_offers(database, lot, reason):
    """Tell pending offerers and delete every offer so the lot row can be deleted."""
    pending = database.execute(
        "SELECT offerer_id FROM swap_offers WHERE lot_id = ? AND status = ?", (lot["id"], PENDING)
    ).fetchall()
    for offer in pending:
        notifications.create_notification(
            database, offer["offerer_id"],
            f"{reason}: '{lot['title']}'. Your swap offer was cancelled.",
        )
    database.execute("DELETE FROM swap_offers WHERE lot_id = ?", (lot["id"],))


def offers_for_lot(database, lot_id):
    """Every offer on a lot with the offerer's email, newest first (the seller's view)."""
    return database.execute(
        "SELECT swap_offers.*, users.email AS offerer_email FROM swap_offers "
        "JOIN users ON users.id = swap_offers.offerer_id WHERE swap_offers.lot_id = ? "
        "ORDER BY swap_offers.id DESC",
        (lot_id,),
    ).fetchall()


def accepted_offer(database, lot_id):
    return database.execute(
        "SELECT swap_offers.*, users.email AS offerer_email FROM swap_offers "
        "JOIN users ON users.id = swap_offers.offerer_id WHERE swap_offers.lot_id = ? AND swap_offers.status = ?",
        (lot_id, ACCEPTED),
    ).fetchone()


def latest_offer_by(database, lot_id, user_id):
    return database.execute(
        "SELECT * FROM swap_offers WHERE lot_id = ? AND offerer_id = ? ORDER BY id DESC LIMIT 1",
        (lot_id, user_id),
    ).fetchone()


def user_offers(database, user_id):
    """The offers a user has made, with the lot they are for, newest first."""
    return database.execute(
        "SELECT swap_offers.*, lots.title AS lot_title FROM swap_offers "
        "JOIN lots ON lots.id = swap_offers.lot_id WHERE swap_offers.offerer_id = ? "
        "ORDER BY swap_offers.id DESC",
        (user_id,),
    ).fetchall()


def _email(database, user_id):
    row = database.execute("SELECT email FROM users WHERE id = ?", (user_id,)).fetchone()
    return row["email"] if row else "the seller"
