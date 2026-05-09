import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).parent / "store" / "altfins.db"

# messages is the raw scrape; signals / returns / baseline_returns are derived
# and safe to drop+recreate when we change the parser/evaluator.
SCHEMA = """
CREATE TABLE IF NOT EXISTS messages (
    msg_id           INTEGER PRIMARY KEY,
    channel          TEXT    NOT NULL,
    posted_at        TEXT    NOT NULL,
    text             TEXT    NOT NULL,
    sender_id        INTEGER,
    sender_username  TEXT,
    sender_name      TEXT,
    is_reply         INTEGER NOT NULL DEFAULT 0,
    raw_json         TEXT
);
CREATE INDEX IF NOT EXISTS idx_messages_sender ON messages(sender_id);

DROP TABLE IF EXISTS evaluations;

CREATE TABLE IF NOT EXISTS signals (
    signal_id     INTEGER PRIMARY KEY AUTOINCREMENT,
    msg_id        INTEGER NOT NULL UNIQUE REFERENCES messages(msg_id),
    posted_at     TEXT    NOT NULL,
    category      TEXT    NOT NULL,  -- directional, target, conditional, news, marketing, recap, other
    symbol        TEXT,
    side          TEXT CHECK (side IN ('long', 'short')),
    last_price    REAL,
    target_pct    REAL,               -- 0.15 for "+15% target"
    target_price  REAL,
    sl_price      REAL,
    signal_type   TEXT,                -- AltFINS' "Signal Type:" line if present
    parsed_ok     INTEGER NOT NULL,    -- 1 = evaluable (directional or target)
    parse_notes   TEXT
);
CREATE INDEX IF NOT EXISTS idx_signals_symbol ON signals(symbol);
CREATE INDEX IF NOT EXISTS idx_signals_posted ON signals(posted_at);
CREATE INDEX IF NOT EXISTS idx_signals_category ON signals(category);

CREATE TABLE IF NOT EXISTS returns (
    return_id          INTEGER PRIMARY KEY AUTOINCREMENT,
    signal_id          INTEGER NOT NULL REFERENCES signals(signal_id),
    horizon_hours      INTEGER NOT NULL,
    entry_price        REAL,
    exit_price         REAL,
    fwd_return         REAL,
    direction_correct  INTEGER,
    target_hit_pathwise INTEGER,
    note               TEXT,
    UNIQUE (signal_id, horizon_hours)
);

CREATE TABLE IF NOT EXISTS baseline_returns (
    baseline_id   INTEGER PRIMARY KEY AUTOINCREMENT,
    pair_signal_id INTEGER NOT NULL REFERENCES signals(signal_id),
    posted_at     TEXT    NOT NULL,
    symbol        TEXT    NOT NULL,
    horizon_hours INTEGER NOT NULL,
    fwd_return    REAL,
    note          TEXT
);
CREATE INDEX IF NOT EXISTS idx_baseline_horizon ON baseline_returns(horizon_hours);

CREATE TABLE IF NOT EXISTS ohlcv_cache (
    symbol  TEXT NOT NULL,
    ts_ms   INTEGER NOT NULL,
    o REAL, h REAL, l REAL, c REAL, v REAL,
    PRIMARY KEY (symbol, ts_ms)
);
"""


def connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    return conn
