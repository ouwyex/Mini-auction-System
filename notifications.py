"""In-app notifications for Mini Auction System (Flask + SQLite)."""

def create_notification(database, user_id, message, lot_id=None, notification_type="info"):
    """Insert one notification. Caller controls transaction/commit."""
    if not user_id or not message:
        return None
    cursor = database.execute(
        """INSERT INTO notifications (user_id, lot_id, message, notification_type)
           VALUES (?, ?, ?, ?)""",
        (user_id, lot_id, message, notification_type),
    )
    return cursor.lastrowid


def notify_outbid(database, previous_bid, new_bidder_id, lot, new_amount):
    """Notify the previous leader when another user takes the lead."""
    if previous_bid is None or previous_bid["bidder_id"] == new_bidder_id:
        return None
    return create_notification(
        database,
        previous_bid["bidder_id"],
        f"Your bid on '{lot['title']}' has been outbid. The new highest bid is {new_amount:.2f}.",
        lot_id=lot["id"],
        notification_type="outbid",
    )


def unread_count(database, user_id):
    row = database.execute(
        "SELECT COUNT(*) AS total FROM notifications WHERE user_id = ? AND is_read = 0",
        (user_id,),
    ).fetchone()
    return row["total"]


def get_notifications(database, user_id, limit=50):
    return database.execute(
        """SELECT n.*, l.title AS lot_title
           FROM notifications n
           LEFT JOIN lots l ON l.id = n.lot_id
           WHERE n.user_id = ?
           ORDER BY n.created_at DESC, n.id DESC
           LIMIT ?""",
        (user_id, limit),
    ).fetchall()


def mark_notification_read(database, notification_id, user_id):
    """A user can only mark their own notification as read."""
    cursor = database.execute(
        """UPDATE notifications SET is_read = 1
           WHERE id = ? AND user_id = ? AND is_read = 0""",
        (notification_id, user_id),
    )
    return cursor.rowcount


def mark_all_read(database, user_id):
    cursor = database.execute(
        "UPDATE notifications SET is_read = 1 WHERE user_id = ? AND is_read = 0",
        (user_id,),
    )
    return cursor.rowcount
