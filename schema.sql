-- Five tables form the small auction database.
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    first_name TEXT,
    last_name TEXT,
    email TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    role TEXT NOT NULL CHECK (role IN ('user', 'admin')),
    is_blocked INTEGER NOT NULL DEFAULT 0 CHECK (is_blocked IN (0, 1)),
    balance REAL NOT NULL DEFAULT 0 CHECK (balance >= 0),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS lots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    seller_id INTEGER NOT NULL REFERENCES users(id),
    title TEXT NOT NULL,
    description TEXT NOT NULL,
    start_price REAL NOT NULL CHECK (start_price > 0),
    bid_step REAL NOT NULL CHECK (bid_step > 0),
    current_price REAL NOT NULL,
    closes_at TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'closed', 'unsold')),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS bids (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    lot_id INTEGER NOT NULL REFERENCES lots(id),
    bidder_id INTEGER NOT NULL REFERENCES users(id),
    amount REAL NOT NULL CHECK (amount > 0),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- One deposit (10% of the start price) per user per lot, paid before bidding.
-- status: held while the lot is active; returned (refunded) or applied (kept by the
-- winner as part of the purchase) once it is settled. UNIQUE stops a second deposit
-- for the same user and lot.
CREATE TABLE IF NOT EXISTS deposits (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    lot_id INTEGER NOT NULL REFERENCES lots(id),
    user_id INTEGER NOT NULL REFERENCES users(id),
    amount REAL NOT NULL CHECK (amount > 0),
    status TEXT NOT NULL DEFAULT 'held' CHECK (status IN ('held', 'returned', 'applied')),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (lot_id, user_id)
);

-- Wallet history: one row for every money movement. Positive amounts add to the
-- balance, negative amounts take from it, and balance_after is the running balance.
-- lot_id is a plain reference (no foreign key) so history survives when a lot is deleted.
CREATE TABLE IF NOT EXISTS wallet_transactions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id),
    kind TEXT NOT NULL CHECK (kind IN ('top_up', 'deposit_paid', 'deposit_returned')),
    amount REAL NOT NULL CHECK (amount <> 0),
    balance_after REAL NOT NULL CHECK (balance_after >= 0),
    lot_id INTEGER,
    description TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- Speeds up the home page filter (status + price range), deposit lookups and the Wallet page.
CREATE INDEX IF NOT EXISTS idx_lots_status_price ON lots (status, current_price);
CREATE INDEX IF NOT EXISTS idx_deposits_user ON deposits (user_id);
CREATE INDEX IF NOT EXISTS idx_wallet_user ON wallet_transactions (user_id, id);
