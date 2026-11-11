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

`python migrate.py` adds the wallet balance and the deposits table to an existing database and safely converts existing `buyer` and `seller` roles to `user`, preserving user IDs, lots, bids, and password hashes. Run it once when upgrading an existing database. The migration rebuilds only the users table with foreign key checks temporarily disabled; it does not reset auction data. `python seed.py` is for a demo database and resets all its rows before loading sample data.

## Roles and permissions

| Visitor/account | Permissions |
| --- | --- |
| Guest | View lots, register, and log in |
| User | Create lots, edit/cancel own unbid lots, add demo money to a wallet, pay a deposit, bid on other users' lots, view own lots, bids and deposits |
| Admin | Block/unblock users and delete lots |

Blocked accounts cannot log in or continue using an existing session. Registration always creates a `user`; create administrator accounts through seed data.

## Auction rules

- A new lot starts at its start price and requires a positive bid step and future closing time.
- The first bid must be at least the start price. Each later bid must be at least the current price plus the bid step.
- **Deposit:** before a user can bid on a lot, they must pay a deposit of 10% of the lot's start price from their wallet (`Pay deposit` on the lot page). Without a held deposit the bid is refused. A user pays one deposit per lot.
- **Wallet:** every user has a demo wallet (play money, no real payment). Money is added on the `Wallet` page, up to 10000 at a time. Seeded users start with 1000.
- **When an auction ends:** the winner's deposit is *applied* to the purchase, all other deposits are *returned* to the wallets. If the lot is unsold, every deposit is returned. If a lot is cancelled or deleted by an admin, all its deposits are refunded.
- A lot with paid deposits cannot be edited (its start price would change the deposit), but it can be cancelled.
- Sellers cannot bid on their own lots. Bids are checked and recorded in one `BEGIN IMMEDIATE` SQLite transaction.
- Expired lots are closed during requests. The highest bid wins; if bids tie, the earlier inserted bid wins. A lot without bids becomes unsold.
- Datetime-local values are interpreted as UTC. There is no background worker, so an expired lot's displayed status updates on the next request.

## Test

```powershell
python -m pytest
```

## Project structure

- `app.py` — routes, access checks, CSRF checks, auction actions, wallet and deposits.
- `db.py` / `schema.sql` — SQLite connection helper and table definitions (users, lots, bids, deposits). An older database is upgraded automatically on the first request.
- `migrate.py` — preserves existing data while converting old account roles.
- `seed.py` — creates one admin, four users, and six demo lots.
- `templates/` — Jinja pages; template autoescaping protects displayed content.
- `tests/` — pytest coverage for roles, permissions, bidding, closing (`test_app.py`) and the deposit rule (`test_deposits.py`).

The Flask development secret key is for local use only; deployment should set a private secret key from the environment.
