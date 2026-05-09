"""Forward-return evaluation for parsed AltFINS signals + matched baseline.

For each evaluable signal (category 'directional' or 'target'):
  - Pull Binance hourly OHLCV from posted_at
  - Compute close-to-close return at horizons +1d, +3d, +7d, +14d, +30d
  - direction_correct = (sign of return == sign of side)
  - For target_alerts: target_hit_pathwise = did high (long) / low (short)
    ever cross target_price within horizon?

Baseline:
  For each evaluable signal, pick BASELINE_K random other symbols from the
  AltFINS-signaled universe (excluding the signaled symbol) and compute the
  same forward returns starting at the same posted_at. This gives a like-
  for-like distribution to compare against.
"""
import os
import random
import time
from datetime import timedelta
from typing import Optional

import ccxt  # type: ignore
import pandas as pd  # type: ignore
from dateutil.parser import isoparse  # type: ignore
from dotenv import load_dotenv  # type: ignore

import db

HORIZONS = [4, 8, 12, 24, 72, 168]  # hours: 4h, 8h, 12h, 1d, 3d, 7d
BASELINE_K = 5


def _ccxt_symbol(symbol: str) -> Optional[str]:
    if not symbol:
        return None
    s = symbol.upper()
    # AltFINS uses bare tickers; assume USDT pair on Binance
    return f"{s}/USDT"


def _exchange() -> ccxt.Exchange:
    return ccxt.binance({"enableRateLimit": True})


def fetch_ohlcv_cached(conn, ex, symbol_ccxt: str, since_ms: int,
                        until_ms: int) -> pd.DataFrame:
    """Fetch 1h bars covering [since_ms, until_ms]; cache in ohlcv_cache."""
    cached = conn.execute(
        "SELECT ts_ms, o, h, l, c, v FROM ohlcv_cache "
        "WHERE symbol = ? AND ts_ms >= ? AND ts_ms <= ? ORDER BY ts_ms",
        (symbol_ccxt, since_ms, until_ms),
    ).fetchall()
    have = {r["ts_ms"] for r in cached}
    expected = (until_ms - since_ms) // (60 * 60 * 1000) + 1
    if len(have) >= expected * 0.95:
        df = pd.DataFrame([dict(r) for r in cached])
    else:
        out: list[list[float]] = []
        cursor = since_ms
        while cursor <= until_ms:
            try:
                batch = ex.fetch_ohlcv(symbol_ccxt, timeframe="1h",
                                       since=cursor, limit=1000)
            except ccxt.BadSymbol:
                return pd.DataFrame()
            except Exception as e:
                print(f"  fetch error {symbol_ccxt}: {e!r}")
                time.sleep(2)
                break
            if not batch:
                break
            out.extend(batch)
            cursor = batch[-1][0] + 60 * 60 * 1000
            if len(batch) < 1000:
                break
            time.sleep(ex.rateLimit / 1000)
        if not out:
            return pd.DataFrame()
        # cache
        conn.executemany(
            "INSERT OR IGNORE INTO ohlcv_cache (symbol, ts_ms, o, h, l, c, v) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            [(symbol_ccxt, r[0], r[1], r[2], r[3], r[4], r[5]) for r in out],
        )
        conn.commit()
        df = pd.DataFrame(out, columns=["ts_ms", "o", "h", "l", "c", "v"])

    if df.empty:
        return df
    df = df.drop_duplicates(subset=["ts_ms"]).sort_values("ts_ms").reset_index(drop=True)
    df["dt"] = pd.to_datetime(df["ts_ms"], unit="ms", utc=True)
    return df


def _entry_and_horizons(posted, df: pd.DataFrame) -> tuple:
    """Return (entry_price, dict of horizon_hours->window) anchored at posted timestamp."""
    after = df[df["dt"] >= posted]
    if after.empty:
        return None, {}
    entry_row = after.iloc[0]
    entry_price = float(entry_row["o"])
    out = {}
    for h in HORIZONS:
        deadline = posted + timedelta(hours=h)
        window = df[(df["dt"] >= posted) & (df["dt"] <= deadline)]
        if window.empty:
            continue
        out[h] = window
    return entry_price, out


def evaluate_signal(conn, ex, sig) -> None:
    sym_ccxt = _ccxt_symbol(sig["symbol"])
    if not sym_ccxt:
        return
    posted = isoparse(sig["posted_at"])
    since = int(posted.timestamp() * 1000)
    until = since + (max(HORIZONS) + 2) * 24 * 60 * 60 * 1000

    df = fetch_ohlcv_cached(conn, ex, sym_ccxt, since, until)
    if df.empty:
        for h in HORIZONS:
            conn.execute(
                "INSERT OR REPLACE INTO returns (signal_id, horizon_hours, note) "
                "VALUES (?, ?, ?)",
                (sig["signal_id"], h, "no_data"),
            )
        return

    entry, windows = _entry_and_horizons(posted, df)
    if entry is None:
        for h in HORIZONS:
            conn.execute(
                "INSERT OR REPLACE INTO returns (signal_id, horizon_hours, note) "
                "VALUES (?, ?, ?)",
                (sig["signal_id"], h, "no_bar_after_post"),
            )
        return

    side = sig["side"]
    sign = 1 if side == "long" else -1
    target_price = sig["target_price"]

    for h in HORIZONS:
        win = windows.get(h)
        if win is None or win.empty:
            conn.execute(
                "INSERT OR REPLACE INTO returns (signal_id, horizon_hours, note) "
                "VALUES (?, ?, ?)",
                (sig["signal_id"], h, "no_bars_in_horizon"),
            )
            continue
        exit_price = float(win.iloc[-1]["c"])
        fwd = (exit_price - entry) / entry
        direction_correct = 1 if sign * fwd > 0 else 0
        target_hit = None
        if target_price is not None:
            if side == "long":
                target_hit = 1 if (win["h"] >= target_price).any() else 0
            else:
                target_hit = 1 if (win["l"] <= target_price).any() else 0
        conn.execute(
            "INSERT OR REPLACE INTO returns (signal_id, horizon_hours, "
            "entry_price, exit_price, fwd_return, direction_correct, "
            "target_hit_pathwise, note) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (sig["signal_id"], h, entry, exit_price, fwd,
             direction_correct, target_hit, None),
        )


def evaluate_baseline(conn, ex, sig, universe: list[str]) -> None:
    """Pick K random universe symbols, compute same-horizon returns from posted_at."""
    posted = isoparse(sig["posted_at"])
    since = int(posted.timestamp() * 1000)
    until = since + (max(HORIZONS) + 2) * 24 * 60 * 60 * 1000

    candidates = [s for s in universe if s and s != sig["symbol"]]
    random.shuffle(candidates)
    picked = 0
    for s in candidates:
        if picked >= BASELINE_K:
            break
        sym_ccxt = _ccxt_symbol(s)
        if not sym_ccxt:
            continue
        df = fetch_ohlcv_cached(conn, ex, sym_ccxt, since, until)
        if df.empty:
            continue
        entry, windows = _entry_and_horizons(posted, df)
        if entry is None:
            continue
        for h in HORIZONS:
            win = windows.get(h)
            if win is None or win.empty:
                continue
            exit_price = float(win.iloc[-1]["c"])
            fwd = (exit_price - entry) / entry
            conn.execute(
                "INSERT INTO baseline_returns (pair_signal_id, posted_at, "
                "symbol, horizon_hours, fwd_return) VALUES (?, ?, ?, ?, ?)",
                (sig["signal_id"], sig["posted_at"], s, h, fwd),
            )
        picked += 1


def evaluate_all() -> tuple[int, int]:
    load_dotenv()
    conn = db.connect()
    sigs = conn.execute(
        "SELECT * FROM signals WHERE parsed_ok = 1 ORDER BY posted_at"
    ).fetchall()

    universe = [r["symbol"] for r in conn.execute(
        "SELECT DISTINCT symbol FROM signals WHERE parsed_ok = 1 AND symbol IS NOT NULL"
    ).fetchall()]
    print(f"Universe size (distinct signaled symbols): {len(universe)}")

    # if returns already populated, skip; but we DELETE on parse, so fresh start
    ex = _exchange()
    done = 0
    for sig in sigs:
        try:
            evaluate_signal(conn, ex, sig)
            evaluate_baseline(conn, ex, sig, universe)
        except Exception as e:
            print(f"  signal {sig['signal_id']} {sig['symbol']}: {e!r}")
        conn.commit()
        done += 1
        if done % 10 == 0:
            print(f"  evaluated {done}/{len(sigs)}")
    return done, len(sigs)


def main() -> None:
    done, total = evaluate_all()
    print(f"\nevaluated {done}/{total} signals (with {BASELINE_K} baseline picks each)")


if __name__ == "__main__":
    main()
