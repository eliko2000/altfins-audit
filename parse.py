"""Classify and extract structured fields from AltFINS posts.

AltFINS' free-channel posts split into ~7 categories, only two of which we
can evaluate:
  - directional : has a symbol and a clear bullish/bearish slant + last_price
  - target      : directional + an explicit "+X% target" or target $price

Everything else (news, marketing, conditional analysis, recap, education) is
labelled and ignored by the evaluator.
"""
import os
import re
from dataclasses import dataclass, field
from typing import Optional

from dotenv import load_dotenv  # type: ignore

import db

# --- regex pieces ------------------------------------------------------------

NUM = r"\d{1,3}(?:,\d{3})*(?:\.\d+)?|\d+(?:\.\d+)?"

# Symbol candidates
RE_DOLLAR_TICKER = re.compile(r"\$([A-Z]{2,10})\b")
RE_PAREN_TICKER = re.compile(r"\b([A-Z]{1,10})\s*\(\s*[A-Za-z]")  # "VET (VeChain)" or "M ( emeCore)"
RE_HEAD_TICKER = re.compile(r"^([A-Z]{2,10})\b")  # "AAVE Experiences..." / "XRP ⚠️"

RE_LAST_PRICE = re.compile(rf"Last\s*Price[:\s]+\$?\s*({NUM})", re.IGNORECASE)
RE_MKT_CAP = re.compile(rf"Market\s*Cap[:\s]+\$?\s*({NUM})", re.IGNORECASE)
RE_SIGNAL_TYPE = re.compile(r"Signal\s*Type[:\s]+(.+)", re.IGNORECASE)

# "+15% upside target to $0.009" / "+12.18% potential" / "+25% target"
RE_TARGET_PCT = re.compile(
    rf"\+\s*({NUM})\s*%\s*(?:upside|profit|potential|target|to\b)",
    re.IGNORECASE,
)
RE_TARGET_TO = re.compile(rf"target.{{0,30}}?\$\s*({NUM})", re.IGNORECASE)
RE_STOP = re.compile(rf"Stop\s*Loss[^0-9]{{0,20}}\$?\s*({NUM})", re.IGNORECASE)

# Sides
BULLISH_TOKENS = [
    "bullish", "uptrend", "breakout", "broken out", "broke out", "rally",
    "momentum building", "all-time high", "ath", "local high", "gainer",
    "trend reversal", "buy signal", "buy ", "long signal", "🚀",
    "strong demand", "bullish move", "strong buyers",
]
BEARISH_TOKENS = [
    "bearish", "downtrend", "breakdown", "downturn", "decline", "declined",
    "falling wedge", "sell signal", "short ", "weakness", "fading",
    "pressure mounting", "below support", "broke below", "📉",
    "support broken", "rejection",
]

CONDITIONAL_TOKENS = ["either", " or 1)", " or 2)", "we wait for price"]
RECAP_TOKENS = [
    "captured big winners", "altfins members", "vip community",
    "recent ai-powered", "recent trade setups", "trade setups hitting",
    "+%", "winners!",
]
MARKETING_TOKENS = [
    "coin pick", "vip", "watch tutorial", "altfins mcp", "altfins analytics",
    "join traders", "introducing", "we’re excited to announce",
    "new go-to destination", "50% off", "10k prop", "subscribe",
    "newsletter", "daily trade ideas", "free guide", "free pdf",
    "follow @altfins", "step-by-step", "beginner-friendly", "how to trade",
    "how to profit", "how to identify", "how to spot", "happy easter",
    "happy holidays", "merry christmas", "happy new year",
    "🐣", "🎄", "platform update",
]
NEWS_TOKENS = [
    "co-founder", "warns", "according to", "report", "regulators",
    "etf", "lawsuit", "sec ", "approved", "court ", "ruling",
    "billion", "trillion", "nation", "government",
]


def _f(s: Optional[str]) -> Optional[float]:
    if s is None:
        return None
    try:
        return float(s.replace(",", ""))
    except ValueError:
        return None


@dataclass
class Parsed:
    category: str = "other"
    symbol: Optional[str] = None
    side: Optional[str] = None
    last_price: Optional[float] = None
    target_pct: Optional[float] = None
    target_price: Optional[float] = None
    sl_price: Optional[float] = None
    signal_type: Optional[str] = None
    notes: list = field(default_factory=list)


def _detect_symbol(text: str) -> Optional[str]:
    # priority: $TICKER > "TICKER (Name)" > leading-token
    m = RE_DOLLAR_TICKER.search(text)
    if m:
        return m.group(1)
    m = RE_PAREN_TICKER.search(text)
    if m:
        return m.group(1)
    # leading token must be all caps and >=2 chars to avoid false positives
    first_line = text.lstrip().split("\n", 1)[0]
    m = RE_HEAD_TICKER.match(first_line)
    if m and len(m.group(1)) >= 2:
        return m.group(1)
    return None


def _detect_side(text_lower: str) -> Optional[str]:
    bull = sum(1 for t in BULLISH_TOKENS if t in text_lower)
    bear = sum(1 for t in BEARISH_TOKENS if t in text_lower)
    if bull > bear and bull >= 1:
        return "long"
    if bear > bull and bear >= 1:
        return "short"
    return None


def _is_conditional(text_lower: str) -> bool:
    return any(t in text_lower for t in CONDITIONAL_TOKENS)


def _is_recap(text_lower: str) -> bool:
    # recaps tend to list multiple symbols with +X% next to each
    if any(t in text_lower for t in RECAP_TOKENS):
        return True
    plus_pct = re.findall(r"\+\d+%", text_lower)
    if len(plus_pct) >= 3:
        return True
    return False


def _is_marketing(text_lower: str) -> bool:
    return sum(1 for t in MARKETING_TOKENS if t in text_lower) >= 1


def _is_news(text_lower: str) -> bool:
    # news headlines often have no Last Price line and are long-form prose
    has_last_price = "last price" in text_lower
    if has_last_price:
        return False
    news_hits = sum(1 for t in NEWS_TOKENS if t in text_lower)
    return news_hits >= 2


def parse_message(text: str) -> Parsed:
    p = Parsed()
    tl = text.lower()

    # Conditional and recap are explicit anti-signal patterns and preempt
    # everything (an AltFINS post saying "either A or B" is not a single call).
    if _is_recap(tl):
        p.category = "recap"
        return p
    if _is_conditional(tl):
        p.category = "conditional"
        return p

    # Try to extract a clean signal first. The "Get Free Hourly Trading
    # Signals →" footer appears on every alert AND on pure marketing posts,
    # so we can't use it to classify; we use structure instead.
    p.symbol = _detect_symbol(text)
    p.side = _detect_side(tl)

    last_m = RE_LAST_PRICE.search(text)
    p.last_price = _f(last_m.group(1)) if last_m else None

    sig_m = RE_SIGNAL_TYPE.search(text)
    p.signal_type = sig_m.group(1).strip()[:80] if sig_m else None

    pct_m = RE_TARGET_PCT.search(text)
    if pct_m:
        v = _f(pct_m.group(1))
        if v is not None:
            p.target_pct = v / 100.0

    tprice_m = RE_TARGET_TO.search(text)
    p.target_price = _f(tprice_m.group(1)) if tprice_m else None

    sl_m = RE_STOP.search(text)
    p.sl_price = _f(sl_m.group(1)) if sl_m else None

    if p.target_pct is not None and p.target_price is None and p.last_price:
        sign = 1 if p.side == "long" else -1 if p.side == "short" else 1
        p.target_price = p.last_price * (1 + sign * p.target_pct)
    elif p.target_price is not None and p.target_pct is None and p.last_price:
        p.target_pct = (p.target_price - p.last_price) / p.last_price
        if p.side == "short":
            p.target_pct = -p.target_pct

    # Filter out short messages / pure-link posts that survived above
    word_count = len(re.findall(r"\w+", text))
    is_link_only = ("https://" in text or "http://" in text) and word_count < 30

    if p.symbol and p.side and not is_link_only:
        # Last Price is no longer required — evaluator anchors at the
        # OHLCV bar at posted_at. We still record it when present.
        if p.target_pct is not None or p.target_price is not None:
            p.category = "target"
        else:
            p.category = "directional"
        if p.last_price is None:
            p.notes.append("implicit_price")
        return p

    # Not a clean signal — classify the non-signal type
    if _is_marketing(tl) or is_link_only:
        p.category = "marketing"
    elif _is_news(tl):
        p.category = "news"
    else:
        if p.symbol is None:
            p.notes.append("no_symbol")
        if p.side is None:
            p.notes.append("no_side")
        p.category = "other"
    return p


def parse_all() -> dict:
    load_dotenv()
    sender_username = os.environ.get("ALTFINS_SENDER_USERNAME") or None
    sender_id_raw = os.environ.get("ALTFINS_SENDER_ID")
    sender_id = int(sender_id_raw) if sender_id_raw else None
    skip_replies = os.environ.get("SKIP_REPLIES", "1") == "1"

    conn = db.connect()
    # nuke old signals so re-runs reflect parser changes
    conn.execute("DELETE FROM returns")
    conn.execute("DELETE FROM baseline_returns")
    conn.execute("DELETE FROM signals")

    where = ["1=1"]
    params: list = []
    if sender_username:
        where.append("m.sender_username = ?")
        params.append(sender_username)
    if sender_id is not None:
        where.append("m.sender_id = ?")
        params.append(sender_id)
    if skip_replies:
        where.append("m.is_reply = 0")
    sql = (
        "SELECT m.msg_id, m.posted_at, m.text FROM messages m "
        f"WHERE {' AND '.join(where)} ORDER BY m.posted_at"
    )
    rows = conn.execute(sql, params).fetchall()

    counts: dict = {}
    for r in rows:
        p = parse_message(r["text"])
        counts[p.category] = counts.get(p.category, 0) + 1
        evaluable = p.category in ("directional", "target")
        conn.execute(
            "INSERT INTO signals (msg_id, posted_at, category, symbol, side, "
            "last_price, target_pct, target_price, sl_price, signal_type, "
            "parsed_ok, parse_notes) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                r["msg_id"], r["posted_at"], p.category, p.symbol, p.side,
                p.last_price, p.target_pct, p.target_price, p.sl_price,
                p.signal_type, 1 if evaluable else 0,
                ",".join(p.notes) if p.notes else None,
            ),
        )
    conn.commit()
    counts["_total"] = len(rows)
    counts["_evaluable"] = counts.get("directional", 0) + counts.get("target", 0)
    return counts


def main() -> None:
    counts = pretty = parse_all()
    print(f"\nParsed {pretty.pop('_total')} messages from AltFINS:")
    ev = pretty.pop("_evaluable")
    for cat in ("directional", "target", "conditional", "news", "marketing",
                "recap", "other"):
        print(f"  {cat:<12} {pretty.get(cat, 0):>4}")
    print(f"\n  evaluable    {ev:>4}  (directional + target)")


if __name__ == "__main__":
    main()
