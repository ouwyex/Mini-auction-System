# Time-based auction categories — integration guide

## Category rules

- Express: more than 0 and up to 24 hours remaining.
- Standard: more than 24 and up to 72 hours remaining.
- Long-term: more than 72 hours remaining.
- Ended: 0 or less (not one of the three active categories).

The default list order is Express → Standard → Long-term. Inside each category,
the auction ending soonest appears first.

## Design

This implementation derives the category from the existing `lots.closes_at`.
It does not add a database column and does not require a SQL migration.
Categories change automatically as time passes: Long-term becomes Standard
at 72 hours remaining, then Express at 24 hours remaining.

This is based on remaining time, not the duration originally chosen by the seller.

## Files to add

- `auction_categories.py`
- `tests/test_auction_categories.py`

Do not replace app.py, schema.sql, or existing templates.

## Backend integration (for the teammate maintaining Flask)

Import near the other imports:

    from auction_categories import annotate_auction_categories

In the route that fetches the auction listing, after retrieving the matching
rows and before rendering the template:

    lots = annotate_auction_categories(lots)

Pass `lots` to the existing template as usual. If the route uses a different
variable name, apply the helper to that variable.

Important: apply the helper to the complete filtered result BEFORE pagination.
Sorting only one SQL page after LIMIT/OFFSET will not guarantee global priority.
Keep existing search, price, status, and other filters unchanged.
Each row must contain the existing `closes_at` field.

## Template integration (for the teammate maintaining HTML)

Inside the existing auction card:

    <span class="{{ lot.auction_category.badge_class }}">
        {{ lot.auction_category.label }}
    </span>

If the template uses dictionary notation:

    {{ lot['auction_category']['label'] }}

Add to the existing stylesheet:

    .auction-category-express { background: #fee2e2; color: #991b1b; }
    .auction-category-standard { background: #dbeafe; color: #1e40af; }
    .auction-category-long-term { background: #ede9fe; color: #5b21b6; }
    .auction-category-expired { background: #e5e7eb; color: #374151; }

## Test

From the repository root:

    python -m unittest discover -s tests -p "test_auction_categories.py"

The tests cover category boundaries, ended auctions, and priority ordering.

## Manual check

Use three active test lots ending in 12 hours, 48 hours, and 5 days.
They should appear Express, Standard, Long-term regardless of creation order.
