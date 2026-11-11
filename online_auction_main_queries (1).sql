-- ONLINE MINI-AUCTION SYSTEM


PRAGMA foreign_keys = ON;

-- 1. Extend auction time when a bid is placed in the last 30 seconds
DROP TRIGGER IF EXISTS extend_auction_on_last_second_bid;

CREATE TRIGGER extend_auction_on_last_second_bid
AFTER INSERT ON bids
FOR EACH ROW
BEGIN
    UPDATE lots
    SET closes_at = strftime(
        '%Y-%m-%dT%H:%M:%f+00:00',
        julianday(closes_at) + (2.0 / 1440.0)
    )
    WHERE id = NEW.lot_id
      AND status = 'active'
      AND julianday(NEW.created_at) <= julianday(closes_at)
      AND julianday(NEW.created_at) >= julianday(closes_at, '-30 seconds');
END;

-- 2. Create indexes
CREATE INDEX IF NOT EXISTS idx_bids_lot_amount_id
ON bids (lot_id, amount DESC, id ASC);

CREATE INDEX IF NOT EXISTS idx_bids_bidder
ON bids (bidder_id);

CREATE INDEX IF NOT EXISTS idx_bids_created_at
ON bids (created_at);

CREATE INDEX IF NOT EXISTS idx_lots_status_closes
ON lots (status, closes_at);

CREATE INDEX IF NOT EXISTS idx_lots_seller
ON lots (seller_id);

-- 3. Get the highest bid for each lot
SELECT
    l.id AS lot_id,
    l.title,
    COALESCE(MAX(b.amount), l.start_price) AS highest_bid
FROM lots l
LEFT JOIN bids b ON b.lot_id = l.id
GROUP BY l.id, l.title, l.start_price
ORDER BY l.id;

-- 4. Count bids for each lot
SELECT
    l.id AS lot_id,
    l.title,
    COUNT(b.id) AS total_bids
FROM lots l
LEFT JOIN bids b ON b.lot_id = l.id
GROUP BY l.id, l.title
ORDER BY total_bids DESC;

-- 5. Get all registered users
SELECT
    id,
    first_name,
    last_name,
    email,
    created_at
FROM users
WHERE role = 'user'
ORDER BY created_at DESC;

-- 6. Get all sellers
SELECT DISTINCT
    u.id,
    u.first_name,
    u.last_name,
    u.email
FROM users u
JOIN lots l ON l.seller_id = u.id
ORDER BY u.id;

-- 7. Get all administrators
SELECT
    id,
    first_name,
    last_name,
    email
FROM users
WHERE role = 'admin'
ORDER BY id;

-- 8. Get complete bid history for a specific lot
SELECT
    b.id AS bid_id,
    b.lot_id,
    b.bidder_id,
    u.first_name,
    u.last_name,
    b.amount,
    b.created_at
FROM bids b
JOIN users u ON u.id = b.bidder_id
WHERE b.lot_id = 1
ORDER BY b.created_at ASC, b.id ASC;

-- 9. Get bids placed during the last five minutes
SELECT
    b.id AS bid_id,
    b.lot_id,
    b.bidder_id,
    b.amount,
    b.created_at
FROM bids b
WHERE datetime(b.created_at) >= datetime('now', '-5 minutes')
ORDER BY b.created_at DESC, b.id DESC;

-- 10. Get active auctions that have not expired
SELECT
    id,
    title,
    start_price,
    current_price,
    bid_step,
    closes_at
FROM lots
WHERE status = 'active'
  AND datetime(closes_at) > datetime('now')
ORDER BY closes_at ASC;

-- 11. Get the highest bid for a specific lot
SELECT
    b.id AS bid_id,
    b.lot_id,
    b.bidder_id,
    u.first_name,
    u.last_name,
    b.amount,
    b.created_at
FROM bids b
JOIN users u ON u.id = b.bidder_id
WHERE b.lot_id = 1
ORDER BY b.amount DESC, b.id ASC
LIMIT 1;

-- 12. Get winners of closed auctions
SELECT
    l.id AS lot_id,
    l.title,
    u.id AS winner_id,
    u.first_name,
    u.last_name,
    b.amount AS winning_bid,
    b.created_at AS winning_bid_time
FROM lots l
JOIN bids b ON b.lot_id = l.id
JOIN users u ON u.id = b.bidder_id
WHERE l.status = 'closed'
  AND NOT EXISTS (
      SELECT 1
      FROM bids b2
      WHERE b2.lot_id = l.id
        AND (
            b2.amount > b.amount
            OR (b2.amount = b.amount AND b2.id < b.id)
        )
  )
ORDER BY l.id;

-- 13. Get deposit history
SELECT
    d.id AS deposit_id,
    d.lot_id,
    l.title,
    d.user_id,
    u.first_name,
    u.last_name,
    d.amount,
    d.status,
    d.created_at
FROM deposits d
JOIN lots l ON l.id = d.lot_id
JOIN users u ON u.id = d.user_id
ORDER BY d.created_at DESC, d.id DESC;
