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

`python migrate.py` safely converts existing `buyer` and `seller` roles to `user`, preserving user IDs, lots, bids, and password hashes. It also adds the wallet balance column, the `wallet_transactions` table, the filter index, the `swap_offers` table, and the `lots.accepts_swaps` column to an older database. Run it once when upgrading an existing database. The migration rebuilds only the users table with foreign key checks temporarily disabled; it does not reset auction data. `python seed.py` is for a demo database and resets all its rows (including wallet history) before loading sample data. Each demo user starts with a 500.00 wallet deposit.

## Roles and permissions

| Visitor/account | Permissions |
| --- | --- |
| Guest | View and filter lots, register, and log in |
| User | Create lots, edit/cancel own unbid lots, bid on other users' lots, view own lots and bids, top up their wallet, pay lot deposits, review wallet history, and offer items for swap (sellers answer the offers on their own lots) |
| Admin | Block/unblock users and delete lots (held deposits are refunded) |

Blocked accounts cannot log in or continue using an existing session. Registration always creates a `user`; create administrator accounts through seed data.

## Auction rules

- A new lot starts at its start price and requires a positive bid step and future closing time.
- The first bid must be at least the start price. Each later bid must be at least the current price plus the bid step.
- Sellers cannot bid on their own lots. Bids are checked and recorded in one `BEGIN IMMEDIATE` SQLite transaction.
- Expired lots are closed during requests. The highest bid wins; if bids tie, the earlier inserted bid wins. A lot without bids becomes unsold.
- Soft close: a bid placed in the last 30 seconds before closing extends the auction by 2 minutes.
- Datetime-local values are interpreted as UTC. There is no background worker, so an expired lot's displayed status updates on the next request.

## Home page filter

The home page (`/`) accepts query-string filters that can be combined:

| Parameter | Meaning |
| --- | --- |
| `status` | `active` (default), `closed`, `unsold`, or `all` |
| `min_price`, `max_price` | Inclusive range on the lot's current price; either may be left empty |
| `q` | Case-insensitive title search; `%` and `_` are matched literally |
| `swaps` | `1` shows only lots that accept item swaps |

Example: `/?status=all&min_price=20&max_price=50&q=lamp`. Invalid numbers, a minimum above the maximum, or an unknown status show a message and that filter is ignored. The index `idx_lots_status_price` on `lots (status, current_price)` supports the status and price conditions.

## Deposits and wallet history

Every user has a demo wallet balance (top-ups are simulated, 0.01 to 10000.00 at a time; there is no payment provider).

**Bid reserve.** Before bidding on a lot, a user pays an entry deposit of 10% of its start price from their balance (`POST /lots/<id>/deposit`). Before each bid is accepted, the held funds are increased to cover that bidder's full current maximum bid. The increase is debited atomically with the bid; if funds are insufficient, neither the bid nor the price changes. When another user outbids the leader, the excess reserve is returned and the entry deposit remains held. A user's own higher bid increases their reserve only by the difference. On lot settlement, the winner's held amount is applied toward the purchase and other held deposits are returned. The `deposits` table has `UNIQUE (lot_id, user_id)`, plus `CHECK (amount > 0)`, a status check (`held`, `returned`, `applied`), and foreign keys to the lot and user. Sellers cannot pay deposits on their own lots, and administrators have no wallet. Insufficient funds only reject the bid; they do not trigger an account sanction or monetary penalty.

- When a lot closes, the winner's deposit is `applied` to the purchase and every other deposit is `returned` to its owner's balance. An unsold lot returns all of its deposits.
- Cancelling a lot or deleting it as an administrator refunds its held deposits. A lot with paid deposits cannot be edited, because the deposit depends on the start price.

**Wallet history.** Every money movement is one row in `wallet_transactions` (`top_up`, `deposit_paid`, `deposit_returned`) and is listed newest first on the Wallet page (`/wallet`) together with the user's deposits and their status.

- A balance can never go below zero: `users.balance` has `CHECK (balance >= 0)` and every change goes through `wallet.record`.
- Each change writes exactly one history row with the running `balance_after`, so a balance always equals the sum of that user's history amounts.
- A winner's applied deposit moves no money at closing, so it has no extra history row.
- Amounts are stored as `REAL` rounded to cents, which is fine for this demo; a real system would use integer cents.
- Deposits created before the history table existed have no `deposit_paid` row, but their refunds are still recorded.

## Notifications

When a bid takes the lead, the previous highest bidder gets an in-app notification (`notifications` table, `notifications.py`). The Notifications link in the menu shows the unread count; the page lists messages and lets the user mark one or all as read (`/notifications`). Raising your own leading bid does not notify you, and a user can only mark their own notifications as read. The notification is stored in the same transaction as the bid, so both succeed or both roll back. There is no email, SMS, or background worker; the user sees it on the next page load.

## Item swaps

Besides money, a lot can accept **an item instead of a bid**. The seller ticks "Accept item swaps" when creating the lot (`lots.accepts_swaps`, 0 or 1, default 0). On such a lot every other user sees a second form, "Offer an item instead of money" (`POST /lots/<id>/swap-offers`), with the item name, a description, and an optional estimated value. No deposit is needed because no money moves.

- The seller sees every offer on the lot page and can **accept** or **reject** each one. The offerer can **withdraw** a pending offer. Offerers follow their offers on the My swaps page (`/my-swaps`), and everyone involved gets an in-app notification.
- **Accepting an offer** closes the lot at once, rejects the other pending offers, and returns every held deposit in full (wallet history shows "Lot swapped"). The lot keeps status `closed`; the accepted row in `swap_offers` marks it as swapped, so it shows as "swapped" with no bidding winner.
- If the lot closes by time first, pending offers become `expired`. Cancelling a lot or deleting it as an administrator cancels its offers.
- The `swap_offers` table has status `pending`, `accepted`, `rejected`, `withdrawn`, or `expired`. Two partial unique indexes enforce the rules in the database: one pending offer per user and lot (a new offer is allowed after a rejection or withdrawal), and at most one accepted offer per lot.
- A lot's swap option cannot be changed once offers exist, and administrators cannot make offers.
- The site only records the agreement. It does not check the item or its value and does not handle the hand-over; the accepted offerer is given the seller's email to arrange it.

## Test

```powershell
python -m pytest
```

## Project structure

- `app.py` — routes, access checks, CSRF checks, the home page filter, wallet pages, and auction actions.
- `notifications.py` — in-app notification helpers (outbid alerts, unread count, mark as read).
- `wallet.py` — wallet helpers: top-ups, deposits, deposit settlement, and wallet history.
- `swaps.py` — item swap offers: validation, accept/reject/withdraw, expiry, and clean-up when a lot is removed.
- `db.py` / `schema.sql` — SQLite connection helper, table and index definitions, and `ensure_schema` for upgrading older databases.
- `migrate.py` — preserves existing data while converting old account roles and adding the wallet tables.
- `seed.py` — creates one admin, four funded users, six demo lots (two accept swaps, one with a pending offer), and bids backed by paid deposits.
- `templates/` — Jinja pages; template autoescaping protects displayed content.
- `tests/` — pytest coverage for roles, permissions, bidding, closing (`test_app.py`), the filter (`test_filter.py`), wallet history (`test_wallet.py`), the deposit rule (`test_deposits.py`), notifications (`test_notifications.py`), the 30-second soft close (`test_soft_close.py`), item swaps (`test_swaps.py`), and the team's QA requirements (`test_qa_requirements.py`).

The Flask development secret key is for local use only; deployment should set a private secret key from the environment.
