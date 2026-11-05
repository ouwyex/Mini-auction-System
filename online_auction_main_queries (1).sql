-- ONLINE AUCTION SYSTEM



INSERT INTO users (username, email, password_hash, role)
VALUES
    ('Alice', 'alice@gmail.com', 'hash_1', 'buyer'),
    ('Bob', 'bob@gmail.com', 'hash_2', 'seller'),
    ('Admin', 'admin@gmail.com', 'hash_3', 'admin');


INSERT INTO lots (title, starting_price, seller_id)
VALUES
    ('iPhone 15', 200.00, 2),
    ('Laptop', 500.00, 2);


INSERT INTO bids (lot_id, buyer_id, bid_amount)
VALUES
    (1, 1, 220.00),
    (1, 1, 250.00),
    (1, 1, 270.00);


SELECT
    l.lot_id,
    l.title,
    MAX(b.bid_amount) AS highest_bid
FROM lots AS l
LEFT JOIN bids AS b ON l.lot_id = b.lot_id
GROUP BY l.lot_id, l.title
ORDER BY l.lot_id;


SELECT
    l.lot_id,
    l.title,
    COUNT(b.bid_id) AS total_bids,
    MAX(b.bid_amount) AS highest_bid
FROM lots AS l
LEFT JOIN bids AS b ON l.lot_id = b.lot_id
GROUP BY l.lot_id, l.title
ORDER BY l.lot_id;


SELECT *
FROM users
WHERE role = 'buyer';

SELECT *
FROM users
WHERE role = 'seller';

SELECT *
FROM users
WHERE role = 'admin';


SELECT
    b.bid_id,
    l.title,
    u.username AS bidder,
    b.bid_amount,
    b.bid_time
FROM bids AS b
JOIN lots AS l ON l.lot_id = b.lot_id
JOIN users AS u ON u.user_id = b.buyer_id
WHERE b.lot_id = 1
ORDER BY b.bid_amount DESC;


SELECT
    b.bid_id,
    l.title,
    u.username AS bidder,
    b.bid_amount,
    b.bid_time
FROM bids AS b
JOIN lots AS l ON l.lot_id = b.lot_id
JOIN users AS u ON u.user_id = b.buyer_id
WHERE b.bid_time >= CURRENT_TIMESTAMP - INTERVAL '5 minutes'
ORDER BY b.bid_time DESC;


SELECT
    b.bid_id,
    l.title,
    u.username AS bidder,
    b.bid_amount,
    b.bid_time,
    l.end_time
FROM bids AS b
JOIN lots AS l ON l.lot_id = b.lot_id
JOIN users AS u ON u.user_id = b.buyer_id
WHERE b.bid_time >= l.end_time - INTERVAL '5 minutes'
  AND b.bid_time <= l.end_time
ORDER BY b.bid_time DESC;


SELECT
    l.lot_id,
    l.title,
    MAX(b.bid_amount) AS highest_last_minute_bid
FROM lots AS l
JOIN bids AS b ON b.lot_id = l.lot_id
WHERE b.bid_time >= l.end_time - INTERVAL '5 minutes'
  AND b.bid_time <= l.end_time
GROUP BY l.lot_id, l.title
ORDER BY l.lot_id;
