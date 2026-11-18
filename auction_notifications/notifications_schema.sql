-- Add this table to schema.sql (do not replace the existing schema).
CREATE TABLE IF NOT EXISTS notifications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    lot_id INTEGER REFERENCES lots(id) ON DELETE SET NULL,
    message TEXT NOT NULL,
    notification_type TEXT NOT NULL DEFAULT 'info'
        CHECK (notification_type IN ('info', 'outbid', 'auction_won', 'auction_closed')),
    is_read INTEGER NOT NULL DEFAULT 0 CHECK (is_read IN (0, 1)),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_notifications_user_unread
    ON notifications(user_id, is_read, created_at DESC);
