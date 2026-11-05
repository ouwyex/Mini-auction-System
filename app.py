"""Flask entry point for the student mini-auction demo."""
from datetime import datetime, timezone
from functools import wraps
from pathlib import Path
import secrets
import sqlite3
import math

from flask import Flask, abort, flash, g, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash

from db import DATABASE, init_db

app = Flask(__name__)
app.config["SECRET_KEY"] = "change-this-development-key"
app.config["DATABASE"] = str(DATABASE)


def get_db():
    """Return one SQLite connection per request."""
    if "db" not in g:
        g.db = sqlite3.connect(app.config["DATABASE"], timeout=10)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db


@app.teardown_appcontext
def close_db(_error=None):
    connection = g.pop("db", None)
    if connection is not None:
        connection.close()


def close_expired_lots(database):
    """Close expired lots; the highest bid wins, ties go to the earlier bid."""
    now = datetime.now(timezone.utc).isoformat()
    database.execute(
        "UPDATE lots SET status = CASE WHEN EXISTS "
        "(SELECT 1 FROM bids WHERE bids.lot_id = lots.id) THEN 'closed' ELSE 'unsold' END "
        "WHERE status = 'active' AND closes_at <= ?", (now,),
    )
    database.commit()


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get("user_id"):
            flash("Please log in to continue.", "error")
            return redirect(url_for("login"))
        return view(*args, **kwargs)
    return wrapped


def admin_required(view):
    @wraps(view)
    @login_required
    def wrapped(*args, **kwargs):
        user = get_db().execute("SELECT role FROM users WHERE id = ?", (session["user_id"],)).fetchone()
        if not user or user["role"] != "admin":
            abort(403, description="Administrator access is required.")
        return view(*args, **kwargs)
    return wrapped


def owned_lot_or_403(lot_id):
    """Return the lot only to its owner; otherwise stop with a clear 403."""
    lot = get_db().execute("SELECT * FROM lots WHERE id = ?", (lot_id,)).fetchone()
    if lot is None:
        abort(404)
    if lot["seller_id"] != session["user_id"]:
        abort(403, description="You can only manage your own lots.")
    if get_db().execute("SELECT 1 FROM bids WHERE lot_id = ? LIMIT 1", (lot_id,)).fetchone():
        abort(403, description="A lot with bids cannot be edited or cancelled.")
    return lot


@app.before_request
def prepare_request():
    if not Path(app.config["DATABASE"]).exists():
        init_db()
    # Add profile columns to databases created by earlier versions.
    user_columns = {row["name"] for row in get_db().execute("PRAGMA table_info(users)")}
    for column in ("first_name", "last_name"):
        if column not in user_columns:
            get_db().execute(f"ALTER TABLE users ADD COLUMN {column} TEXT")
    get_db().commit()
    # Expiration is handled during requests, so no background worker is needed.
    close_expired_lots(get_db())
    if session.get("user_id"):
        user = get_db().execute("SELECT is_blocked FROM users WHERE id = ?", (session["user_id"],)).fetchone()
        if user is None:
            session.clear()
        elif user["is_blocked"]:
            session.clear()
            abort(403, description="This account is blocked.")
    if request.method == "POST":
        expected = session.get("csrf_token")
        supplied = request.form.get("csrf_token", "")
        if not expected or not secrets.compare_digest(expected, supplied):
            abort(400, description="The form expired or its security token is missing. Reload and try again.")


@app.context_processor
def common_context():
    if "csrf_token" not in session:
        session["csrf_token"] = secrets.token_urlsafe(32)
    user = None
    if session.get("user_id"):
        user = get_db().execute("SELECT id, email, role FROM users WHERE id = ?", (session["user_id"],)).fetchone()
    return {"current_user": user, "csrf_token": session["csrf_token"]}


@app.errorhandler(403)
def forbidden(error):
    return render_template("error.html", code=403, message=error.description), 403


@app.route("/")
def home():
    lots = get_db().execute(
        "SELECT id, title, current_price, closes_at FROM lots "
        "WHERE status = 'active' ORDER BY closes_at, id"
    ).fetchall()
    now = datetime.now(timezone.utc)
    lot_rows = []
    for lot in lots:
        try:
            seconds = max(0, int((datetime.fromisoformat(lot["closes_at"]) - now).total_seconds()))
            days, remainder = divmod(seconds, 86400)
            hours, remainder = divmod(remainder, 3600)
            remaining = f"{days}d {hours}h" if days else f"{hours}h {remainder // 60}m"
        except ValueError:
            remaining = "time unavailable"
        lot_rows.append({"lot": lot, "remaining": remaining})
    return render_template("home.html", lots=lot_rows)


@app.route("/register", methods=("GET", "POST"))
def register():
    if request.method == "POST":
        first_name = request.form.get("first_name", "").strip()
        last_name = request.form.get("last_name", "").strip()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        if not first_name or not last_name:
            flash("Enter your first and last name.", "error")
        elif len(first_name) > 100 or len(last_name) > 100:
            flash("Name fields must be 100 characters or fewer.", "error")
        elif not email or "@" not in email or len(email) > 254:
            flash("Enter a valid email address.", "error")
        elif len(password) < 8:
            flash("Password must be at least 8 characters.", "error")
        else:
            try:
                get_db().execute(
                    "INSERT INTO users (first_name, last_name, email, password_hash, role) "
                    "VALUES (?, ?, ?, ?, 'user')",
                    (first_name, last_name, email, generate_password_hash(password)),
                )
                get_db().commit()
                flash("Account created. You can now log in.", "success")
                return redirect(url_for("login"))
            except sqlite3.IntegrityError:
                flash("An account with that email already exists.", "error")
    return render_template("register.html")


@app.route("/login", methods=("GET", "POST"))
def login():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        user = get_db().execute(
            "SELECT id, password_hash, is_blocked FROM users WHERE email = ?", (email,)
        ).fetchone()
        if user and not user["is_blocked"] and check_password_hash(user["password_hash"], password):
            session.clear()
            session["user_id"] = user["id"]
            return redirect(url_for("home"))
        flash("Email or password is incorrect.", "error")
    return render_template("login.html")


@app.post("/logout")
@login_required
def logout():
    session.clear()
    flash("You have been logged out.", "success")
    return redirect(url_for("home"))


@app.route("/lots/<int:lot_id>")
def lot_detail(lot_id):
    database = get_db()
    lot = database.execute(
        "SELECT lots.*, users.email AS seller_email FROM lots "
        "JOIN users ON lots.seller_id = users.id WHERE lots.id = ?", (lot_id,)
    ).fetchone()
    if lot is None:
        return render_template("not_found.html"), 404
    bids = database.execute(
        "SELECT bids.id, bids.amount, bids.created_at, users.email AS bidder_email FROM bids "
        "JOIN users ON bids.bidder_id = users.id WHERE bids.lot_id = ? "
        "ORDER BY bids.amount DESC, bids.id ASC", (lot_id,)
    ).fetchall()
    winner = None
    if lot["status"] == "closed" and bids:
        winner = database.execute("SELECT email FROM users WHERE id = ?", (database.execute(
            "SELECT bidder_id FROM bids WHERE lot_id = ? ORDER BY amount DESC, id ASC LIMIT 1", (lot_id,)
        ).fetchone()[0],)).fetchone()["email"]
    return render_template("lot_detail.html", lot=lot, bids=bids, winner=winner)


def parse_closing_time(value):
    """Parse datetime-local input; this demo treats its value as UTC."""
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M").replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None


@app.route("/lots/new", methods=("GET", "POST"))
@login_required
def create_lot():
    if request.method == "POST":
        title = request.form.get("title", "").strip()
        description = request.form.get("description", "").strip()
        closes_at = parse_closing_time(request.form.get("closes_at"))
        try:
            start_price = float(request.form.get("start_price", ""))
            bid_step = float(request.form.get("bid_step", ""))
        except (TypeError, ValueError):
            start_price = bid_step = 0
        if not title:
            flash("Title is required.", "error")
        elif not description:
            flash("Description is required.", "error")
        elif not math.isfinite(start_price) or not math.isfinite(bid_step) or start_price <= 0 or bid_step <= 0:
            flash("Start price and bid step must be valid numbers greater than zero.", "error")
        elif not closes_at:
            flash("Enter a valid closing time.", "error")
        elif closes_at <= datetime.now(timezone.utc):
            flash("Closing time must be in the future.", "error")
        else:
            get_db().execute(
                "INSERT INTO lots (seller_id, title, description, start_price, bid_step, current_price, closes_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (session["user_id"], title, description, start_price, bid_step, start_price, closes_at.isoformat()),
            )
            get_db().commit()
            flash("Lot created.", "success")
            return redirect(url_for("home"))
    return render_template("new_lot.html")


@app.route("/lots/<int:lot_id>/edit", methods=("GET", "POST"))
@login_required
def edit_lot(lot_id):
    lot = owned_lot_or_403(lot_id)
    if lot["status"] != "active":
        abort(403, description="Only active lots can be edited.")
    if request.method == "POST":
        title = request.form.get("title", "").strip()
        description = request.form.get("description", "").strip()
        closing = parse_closing_time(request.form.get("closes_at"))
        if not title or not description:
            flash("Title and description are required.", "error")
        elif not closing or closing <= datetime.now(timezone.utc):
            flash("Closing time must be a valid future time.", "error")
        else:
            try:
                price, step = float(request.form.get("start_price", "")), float(request.form.get("bid_step", ""))
            except (TypeError, ValueError):
                price = step = 0
            if not math.isfinite(price) or not math.isfinite(step) or price <= 0 or step <= 0:
                flash("Start price and bid step must be greater than zero.", "error")
            else:
                get_db().execute(
                    "UPDATE lots SET title = ?, description = ?, start_price = ?, bid_step = ?, "
                    "current_price = ?, closes_at = ? WHERE id = ? AND seller_id = ?",
                    (title, description, price, step, price, closing.isoformat(), lot_id, session["user_id"]),
                )
                get_db().commit()
                return redirect(url_for("my_lots"))
    return render_template("new_lot.html", lot=lot, editing=True)


@app.post("/lots/<int:lot_id>/cancel")
@login_required
def cancel_lot(lot_id):
    lot = owned_lot_or_403(lot_id)
    if lot["status"] != "active":
        abort(403, description="Only active lots can be cancelled.")
    get_db().execute("DELETE FROM lots WHERE id = ? AND seller_id = ?", (lot_id, session["user_id"]))
    get_db().commit()
    flash("Lot cancelled.", "success")
    return redirect(url_for("my_lots"))


@app.post("/lots/<int:lot_id>/bid")
@login_required
def place_bid(lot_id):
    raw_amount = request.form.get("amount", "")
    try:
        amount = float(raw_amount)
        if not math.isfinite(amount) or amount <= 0:
            raise ValueError
    except (TypeError, ValueError):
        flash("Bid amount must be a valid number greater than zero.", "error")
        return redirect(url_for("lot_detail", lot_id=lot_id))
    database = get_db()
    try:
        database.execute("BEGIN IMMEDIATE")
        lot = database.execute("SELECT * FROM lots WHERE id = ?", (lot_id,)).fetchone()
        if not lot:
            raise ValueError("This lot does not exist.")
        if lot["status"] != "active":
            raise ValueError("This lot is not active.")
        if lot["seller_id"] == session["user_id"]:
            raise ValueError("You cannot bid on your own lot.")
        if datetime.fromisoformat(lot["closes_at"]) <= datetime.now(timezone.utc):
            raise ValueError("Bidding has closed for this lot.")
        has_bids = database.execute("SELECT 1 FROM bids WHERE lot_id = ? LIMIT 1", (lot_id,)).fetchone()
        minimum = lot["current_price"] + lot["bid_step"] if has_bids else lot["start_price"]
        if amount < minimum:
            raise ValueError(f"Bid must be at least {minimum:.2f}.")
        database.execute("INSERT INTO bids (lot_id, bidder_id, amount) VALUES (?, ?, ?)",
                         (lot_id, session["user_id"], amount))
        database.execute("UPDATE lots SET current_price = ? WHERE id = ?", (amount, lot_id))
        database.commit()
        flash("Your bid was placed.", "success")
    except ValueError as error:
        database.rollback()
        flash(str(error), "error")
    except sqlite3.Error:
        database.rollback()
        flash("We could not place your bid. Please try again.", "error")
    return redirect(url_for("lot_detail", lot_id=lot_id))


@app.route("/my-lots")
@login_required
def my_lots():
    lots = get_db().execute("SELECT * FROM lots WHERE seller_id = ? ORDER BY id DESC", (session["user_id"],)).fetchall()
    return render_template("my_lots.html", lots=lots)


@app.route("/my-bids")
@login_required
def my_bids():
    rows = get_db().execute(
        "SELECT lots.*, bids.amount AS my_bid, "
        "CASE WHEN lots.status = 'closed' AND bids.bidder_id = "
        "(SELECT bidder_id FROM bids b2 WHERE b2.lot_id = lots.id ORDER BY amount DESC, id ASC LIMIT 1) "
        "THEN 1 ELSE 0 END AS won FROM bids JOIN lots ON lots.id = bids.lot_id "
        "WHERE bids.bidder_id = ? ORDER BY bids.id DESC", (session["user_id"],),
    ).fetchall()
    return render_template("my_bids.html", bids=rows)


@app.route("/admin", methods=("GET", "POST"))
@admin_required
def admin():
    database = get_db()
    if request.method == "POST":
        action = request.form.get("action")
        try:
            if action in ("block", "unblock"):
                user_id = int(request.form.get("user_id", ""))
                if user_id == session["user_id"] and action == "block":
                    abort(403, description="You cannot block your own administrator account.")
                database.execute("UPDATE users SET is_blocked = ? WHERE id = ? AND role = 'user'",
                                 (1 if action == "block" else 0, user_id))
            elif action == "delete_lot":
                lot_id = int(request.form.get("lot_id", ""))
                database.execute("DELETE FROM bids WHERE lot_id = ?", (lot_id,))
                database.execute("DELETE FROM lots WHERE id = ?", (lot_id,))
            else:
                abort(400, description="Unknown admin action.")
        except ValueError:
            abort(400, description="Invalid item ID.")
        database.commit()
        flash("Admin action completed.", "success")
        return redirect(url_for("admin"))
    users = database.execute("SELECT id, email, is_blocked FROM users WHERE role = 'user' ORDER BY id").fetchall()
    lots = database.execute("SELECT id, title, status FROM lots ORDER BY id").fetchall()
    return render_template("admin.html", users=users, lots=lots)


if __name__ == "__main__":
    init_db()
    app.run(debug=True)
