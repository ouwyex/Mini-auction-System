-- ONLINE MINI-AUCTION SYSTEM

-- 1. SNIPING PROTECTION

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

      -- The bid must not be after the original closing time.
      AND julianday(closes_at) >= julianday(NEW.created_at)

      -- The bid must be within the final 30 seconds.
      AND julianday(closes_at) - julianday(NEW.created_at)
          <= (30.0 / 86400.0);

END;

-- 2. DATABASE INDEXES

-- Speed up bid history and highest bid queries.
CREATE INDEX IF NOT EXISTS idx_bids_lot_amount
ON bids (lot_id, amount DESC, id ASC);

-- Speed up user bid history.
CREATE INDEX IF NOT EXISTS idx_bids_bidder
ON bids (bidder_id);

-- Speed up recent bid queries.
CREATE INDEX IF NOT EXISTS idx_bids_created_at
ON bids (created_at);

-- Speed up active auction queries.
CREATE INDEX IF NOT EXISTS idx_lots_status_closes
ON lots (status, closes_at);

-- Speed up seller lot queries.
CREATE INDEX IF NOT EXISTS idx_lots_seller
ON lots (seller_id);

-- 3. HIGHEST BID FOR EACH LOT

SELECT
    l.id AS lot_id,
    l.title,
    l.start_price,
    l.current_price,
    COALESCE(MAX(b.amount), l.start_price) AS highest_bid

FROM lots AS l

LEFT JOIN bids AS b
    ON l.id = b.lot_id

GROUP BY
    l.id,
    l.title,
    l.start_price,
    l.current_price

ORDER BY l.id;

-- 4. TOTAL NUMBER OF BIDS FOR EACH LOT

SELECT
    l.id AS lot_id,
    l.title,
    COUNT(b.id) AS total_bids,
    COALESCE(MAX(b.amount), l.start_price) AS highest_bid

FROM lots AS l

LEFT JOIN bids AS b
    ON l.id = b.lot_id

GROUP BY
    l.id,
    l.title,
    l.start_price

ORDER BY total_bids DESC;

-- 5. REGISTERED USERS

SELECT
    id,
    first_name,
    last_name,
    email,
    role,
    balance

FROM users

WHERE role = 'user'

ORDER BY id;

-- 6. SELLERS

SELECT DISTINCT
    u.id,
    u.first_name,
    u.last_name,
    u.email

FROM users AS u

JOIN lots AS l
    ON u.id = l.seller_id

ORDER BY u.id;

-- 7. ADMINISTRATORS

SELECT
    id,
    first_name,
    last_name,
    email,
    role

FROM users

WHERE role = 'admin';

-- 8. COMPLETE BID HISTORY FOR A LOT

SELECT
    b.id AS bid_id,
    l.id AS lot_id,
    l.title AS lot_title,
    u.first_name,
    u.last_name,
    b.amount,
    b.created_at

FROM bids AS b

JOIN lots AS l
    ON b.lot_id = l.id

JOIN users AS u
    ON b.bidder_id = u.id

WHERE b.lot_id = 1

ORDER BY b.amount DESC, b.id ASC;


-- 9. RECENT BIDS
-- Bids placed during the last 5 minutes.
-- This is an activity report, NOT the sniping rule.

SELECT
    b.id AS bid_id,
    l.title AS lot_title,
    u.first_name,
    u.last_name,
    b.amount,
    b.created_at

FROM bids AS b

JOIN lots AS l
    ON b.lot_id = l.id

JOIN users AS u
    ON b.bidder_id = u.id

WHERE datetime(b.created_at)
      >= datetime('now', '-5 minutes')

ORDER BY b.created_at DESC;


-- 10. ACTIVE AUCTIONS

SELECT
    id AS lot_id,
    title,
    start_price,
    current_price,
    bid_step,
    closes_at

FROM lots

WHERE status = 'active'

AND datetime(closes_at) > datetime('now')

ORDER BY closes_at ASC;

-- 11. HIGHEST BID FOR A SPECIFIC LOT

SELECT
    l.id AS lot_id,
    l.title,
    b.bidder_id,
    u.first_name,
    u.last_name,
    b.amount AS highest_bid,
    b.created_at

FROM lots AS l

JOIN bids AS b
    ON b.lot_id = l.id

JOIN users AS u
    ON u.id = b.bidder_id

WHERE l.id = 1

ORDER BY b.amount DESC, b.id ASC

LIMIT 1;

-- 12. AUCTION WINNERS
-- Highest accepted bid wins

SELECT
    l.id AS lot_id,
    l.title,
    u.first_name,
    u.last_name,
    u.email AS winner_email,
    b.amount AS winning_bid,
    b.created_at AS winning_time

FROM lots AS l

JOIN bids AS b
    ON b.lot_id = l.id

JOIN users AS u
    ON u.id = b.bidder_id

WHERE l.status = 'closed'

AND b.id = (
    SELECT b2.id

    FROM bids AS b2

    WHERE b2.lot_id = l.id

    ORDER BY b2.amount DESC, b2.id ASC

    LIMIT 1
)

ORDER BY l.id;

-- 13. DEPOSIT HISTORY


SELECT
    d.id AS deposit_id,
    l.title AS lot_title,
    u.first_name,
    u.last_name,
    d.amount,
    d.status,
    d.created_at

FROM deposits AS d

JOIN lots AS l
    ON d.lot_id = l.id

JOIN users AS u
    ON d.user_id = u.id

ORDER BY d.created_at DESC;
