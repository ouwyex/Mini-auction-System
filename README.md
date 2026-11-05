# Online Mini-Auction System

A small Flask and SQLite classroom project for creating lots, bidding, and closing timed auctions.

## Install and run

Requirements: Python 3.11 or newer and pip.

```powershell
py -3.11 -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python migrate.py
python seed.py
python app.py
```

Open http://127.0.0.1:5000. Demo accounts use `admin@example.com` with password `admin-demo`, or `user1@example.com` through `user4@example.com` with password `user-demo`.

`python migrate.py` safely converts existing `buyer` and `seller` roles to `user`, preserving user IDs, lots, bids, and password hashes. Run it once when upgrading an existing database. The migration rebuilds only the users table with foreign key checks temporarily disabled; it does not reset auction data. `python seed.py` is for a demo database and resets all its rows before loading sample data.

## Roles and permissions

| Visitor/account | Permissions |
| --- | --- |
| Guest | View lots, register, and log in |
| User | Create lots, edit/cancel own unbid lots, bid on other users' lots, view own lots and bids |
| Admin | Block/unblock users and delete lots |

Blocked accounts cannot log in or continue using an existing session. Registration always creates a `user`; create administrator accounts through seed data.

## Auction rules

- A new lot starts at its start price and requires a positive bid step and future closing time.
- The first bid must be at least the start price. Each later bid must be at least the current price plus the bid step.
- Sellers cannot bid on their own lots. Bids are checked and recorded in one `BEGIN IMMEDIATE` SQLite transaction.
- Expired lots are closed during requests. The highest bid wins; if bids tie, the earlier inserted bid wins. A lot without bids becomes unsold.
- Datetime-local values are interpreted as UTC. There is no background worker, so an expired lot's displayed status updates on the next request.

## Test

```powershell
python -m pytest
```

## Project structure

- `app.py` — routes, access checks, CSRF checks, and auction actions.
- `db.py` / `schema.sql` — SQLite connection helper and table definitions.
- `migrate.py` — preserves existing data while converting old account roles.
- `seed.py` — creates one admin, four users, and six demo lots.
- `templates/` — Jinja pages; template autoescaping protects displayed content.
- `tests/` — pytest coverage for roles, permissions, bidding, and closing.

The Flask development secret key is for local use only; deployment should set a private secret key from the environment.
