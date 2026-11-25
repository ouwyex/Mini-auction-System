"""Time-based auction categories derived from the existing lots.closes_at field."""
from datetime import datetime, timedelta, timezone

EXPRESS_MAX = timedelta(hours=24)
STANDARD_MAX = timedelta(hours=72)

META = {
    "express": ("Express", 0, "auction-category-express"),
    "standard": ("Standard", 1, "auction-category-standard"),
    "long_term": ("Long-term", 2, "auction-category-long-term"),
    "expired": ("Ended", 3, "auction-category-expired"),
}

def _parse(value):
    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, str):
        value = value.strip()
        if value.endswith("Z"):
            value = value[:-1] + "+00:00"
        try:
            dt = datetime.fromisoformat(value)
        except ValueError:
            dt = datetime.strptime(value, "%Y-%m-%d %H:%M:%S")
    else:
        raise TypeError("closes_at must be a datetime or ISO datetime string")
    return dt.astimezone() if dt.tzinfo is None else dt.astimezone(timezone.utc)

def classify_auction(closes_at, now=None):
    closing = _parse(closes_at)
    current = datetime.now(closing.tzinfo) if now is None else _parse(now)
    remaining = closing - current
    if remaining.total_seconds() <= 0:
        key = "expired"
    elif remaining <= EXPRESS_MAX:
        key = "express"
    elif remaining <= STANDARD_MAX:
        key = "standard"
    else:
        key = "long_term"
    label, priority, css_class = META[key]
    return {
        "code": key, "label": label, "priority": priority,
        "badge_class": css_class,
        "remaining_seconds": max(0, int(remaining.total_seconds())),
    }

def annotate_auction_categories(lots, now=None, closes_at_key="closes_at"):
    """Copy rows to dicts, attach category metadata, and sort by priority.

    Sort order: Express, Standard, Long-term, Ended; then earliest closing time.
    Call before pagination for globally correct ordering.
    """
    result = []
    for row in lots:
        item = dict(row)
        category = classify_auction(item[closes_at_key], now)
        item["auction_category"] = category
        item["auction_category_code"] = category["code"]
        item["auction_category_label"] = category["label"]
        result.append(item)
    result.sort(key=lambda item: (
        item["auction_category"]["priority"], _parse(item[closes_at_key])
    ))
    return result
