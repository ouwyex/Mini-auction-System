# Integration instructions — notifications

This bundle adds the notification data layer and page template. The existing repository
still needs the small integration edits below; do not overwrite app.py blindly.

## 1. Database

Append the contents of `notifications_schema.sql` to the end of `schema.sql`.
The app's `ensure_schema()` / startup schema upgrade path must execute this CREATE TABLE
statement for existing databases too. If `ensure_schema()` only adds selected tables,
add the same SQL there (or execute this idempotent statement during its upgrade).

## 2. Copy the module and template

Copy `notifications.py` into the repository root and
`templates/notifications.html` into the existing templates directory.

## 3. app.py integration

Add `import notifications` beside `import wallet`.

In `common_context()`, return the unread count:
    unread_notifications = 0
    if user:
        unread_notifications = notifications.unread_count(get_db(), user["id"])
    return {
        "current_user": user,
        "csrf_token": session["csrf_token"],
        "unread_notifications": unread_notifications,
    }

Add these authenticated routes:
    @app.route("/notifications")
    @login_required
    def notification_list():
        database = get_db()
        rows = notifications.get_notifications(database, session["user_id"])
        return render_template("notifications.html", notifications=rows)

    @app.post("/notifications/<int:notification_id>/read")
    @login_required
    def mark_notification_read(notification_id):
        notifications.mark_notification_read(
            get_db(), notification_id, session["user_id"]
        )
        get_db().commit()
        return redirect(url_for("notification_list"))

    @app.post("/notifications/read-all")
    @login_required
    def mark_all_notifications_read():
        notifications.mark_all_read(get_db(), session["user_id"])
        get_db().commit()
        return redirect(url_for("notification_list"))

## 4. Add the notification link in templates/base.html

Inside the `{% if current_user %}` navigation block, add:
    <a href="{{ url_for('notification_list') }}">
      Notifications
      {% if unread_notifications %}<span class="notification-count">{{ unread_notifications }}</span>{% endif %}
    </a>

## 5. Trigger notification when a bid outbids someone

In `place_bid()` in app.py, the code already obtains `previous = winning_bid(database, lot_id)`
before inserting the new bid. Immediately after updating `lots.current_price`, and BEFORE
`database.commit()`, add:
    notifications.notify_outbid(database, previous, session["user_id"], lot)

This intentionally does not notify a user when they raise their own leading bid.
The notification insert is in the same transaction as the bid, so both succeed or roll back.

## 6. CSS (append to static/style.css)

    .notification-count {
      display: inline-grid;
      min-width: 1.35rem;
      height: 1.35rem;
      place-items: center;
      margin-left: .25rem;
      padding: 0 .3rem;
      border-radius: 999px;
      color: white;
      background: var(--orange-deep);
      font-size: .72rem;
      font-weight: 700;
    }
    .notification-unread {
      border-left: 3px solid var(--orange);
      padding-left: 1rem;
    }

## 7. Important

- Do not add email, SMS, push notifications, or a background worker for this task.
- This is an in-app notification: it appears in the notification list and unread count
  when the user next loads a page.
- The existing app closes expired auctions during requests. Auction-won notifications
  would need a separate, carefully idempotent integration in close_expired_lots();
  they are not included in this minimal deliverable because the agreed original scope
  was alerting the previous highest bidder when they are outbid.
