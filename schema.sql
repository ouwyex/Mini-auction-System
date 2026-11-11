-- Four tables form the small auction database (users, lots, bids, deposits).
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    first_name TEXT,
    last_name TEXT,
    email TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    role TEXT NOT NULL CHECK (role IN ('user', 'admin')),
    is_blocked INTEGER NOT NULL DEFAULT 0 CHECK (is_blocked IN (0, 1)),
    balance REAL NOT NULL DEFAULT 0,
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

CREATE TABLE IF NOT EXISTS deposits (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    lot_id INTEGER NOT NULL REFERENCES lots(id),
    user_id INTEGER NOT NULL REFERENCES users(id),
    amount REAL NOT NULL CHECK (amount > 0),
    status TEXT NOT NULL DEFAULT 'held' CHECK (status IN ('held', 'returned', 'applied')),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (lot_id, user_id)
);
CREATE INDEX IF NOT EXISTS idx_deposits_user ON deposits (user_id);
