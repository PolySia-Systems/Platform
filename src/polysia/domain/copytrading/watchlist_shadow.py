"""Policy for bounded research from a saved watchlist."""

MIN_DURATION = 15 * 60
MAX_DURATION = 7 * 24 * 60 * 60
MAX_RUN_WALLETS = 6
RUN_PAGE_SIZE = 20
MIN_FREE_BYTES = 32 * 1024 * 1024
MAX_STORE_BYTES = 128 * 1024 * 1024
RUN_WRITE_RESERVE_BYTES = 16 * 1024 * 1024
LEGACY_SHADOW_MODEL = "forward-public-book-v1"
SHADOW_MODEL = "forward-public-book-v2"
STARTING_CASH = "100"
FEE_BPS = "200"
MAX_FILL_NOTIONAL = "5"
MAX_MARK_AGE_SECONDS = 180
FILL_REASON = "current_book_shadow_fill"
