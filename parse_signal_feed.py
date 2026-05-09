"""Parser for the AltFINS dedicated signal feed (@Signal_Feed_altFINS).

Format is structured and bot-generated, very different from the open chat:

    SYMBOL ( Long Name) 🚀                    ← 🚀 = bullish, ⚠️/📉 = bearish
    Short tagline mentioning Bullish/Bearish
    Last Price: $X | Market Cap: $Y
    Signal Type: <pattern>
    Description ...
    Find out more

This parser is FAIRER to altFINS than parse.py: it only marks `directional`
posts whose Signal Type is an *actionable entry trigger*, not an observational
pattern. Doji, Trading in a Range, ATH proximity, Unusual Volume, Overbought/
Oversold are excluded — those are descriptive, not "buy/sell now" calls.
"""
import re
from dataclasses import dataclass, field
from typing import Optional

import db


NUM = r"\d{1,3}(?:,\d{3})*(?:\.\d+)?|\d+(?:\.\d+)?"

RE_LAST_PRICE = re.compile(rf"Last\s*Price[:\s]+\$?\s*({NUM})", re.IGNORECASE)
RE_SIGNAL_TYPE = re.compile(r"Signal\s*Type[:\s]+(.+)", re.IGNORECASE)
# Header symbol: "XTZ Tezos 🚀" or "AERO ( Aerodrome Finance) 🚀" or "BDX ( Beldex) ⚠️"
RE_HEAD_SYMBOL = re.compile(r"^\s*([A-Z0-9]{2,10})\b")

# Actionable entry triggers — what a trader would actually act on.
# Match against the Signal Type line (case-insensitive substring).
ACTIONABLE_PATTERNS = [
    "bullish cross",         # Bullish Cross Price above EMA / SMA
    "bearish cross",         # Bearish Cross Price below ...
    "bullish price cross",
    "bearish price cross",
    "bullish breakout",
    "bearish breakout",
    "breakdown",
    "new local high",
    "new local low",
    "bullish momentum",
    "bearish momentum",
    "momentum inflection",
    "fast bullish momentum",
    "fast bearish momentum",
    "strong uptrend",
    "strong downtrend",
    "uptrend across",
    "downtrend across",
    "short-term trend upgrade",
    "short-term trend downgrade",
    "long-term trend upgrade",
    "long-term trend downgrade",
    "trend reversal",
    "bounced up in downtrend",   # explicit short setup
    "bounced down in uptrend",   # explicit long setup
    "early bullish momentum",
    "early bearish momentum",
    "pullback in uptrend",   # buy-the-dip long
    "pullback in downtrend",
    # Headline-only formats (no "Signal Type:" line, but explicit entry verbs):
    "breakout alert",
    "breakdown alert",
    "reversal spotted",
    "reversal confirmed",
    "bullish reversal",
    "bearish reversal",
    "momentum shift confirmed",
    "momentum shift detected",
]

# Watch-list / commentary phrases — these defang an otherwise actionable
# headline (e.g. "Channel Down Breakout Watch" is not an entry).
WATCHLIST_DEFANG = ["watch for", "watching for", "monitor for", "breakout watch"]

# Patterns that survive the whitelist BUT carry an inverted direction:
# the prose tags them "Bullish" but the trade idea is to sell the bounce.
INVERTED_PATTERNS = {
    "bounced up in downtrend": "short",
    "bounced down in uptrend": "long",
    "pullback in uptrend": "long",       # buy-the-dip
    "pullback in downtrend": "short",
}

# Observational patterns we explicitly exclude (this is where the "fairness"
# kicks in — we drop noise rather than counting it against altFINS).
EXCLUDED_PATTERNS = [
    "doji",
    "trading in a range",
    "within 5% of ath",
    "within 10% of ath",
    "recent ath",
    "unusual volume",
    "very overbought",
    "very oversold",
    "oversbought rsi",  # AltFINS' typo, kept verbatim
    "oversold rsi",
    "overbought rsi",
]


@dataclass
class Parsed:
    category: str = "other"
    symbol: Optional[str] = None
    side: Optional[str] = None
    last_price: Optional[float] = None
    signal_type: Optional[str] = None
    notes: list = field(default_factory=list)


def _f(s: Optional[str]) -> Optional[float]:
    if s is None:
        return None
    try:
        return float(s.replace(",", ""))
    except ValueError:
        return None


def _detect_symbol(text: str) -> Optional[str]:
    first_line = text.lstrip().split("\n", 1)[0]
    m = RE_HEAD_SYMBOL.match(first_line)
    if m:
        sym = m.group(1)
        # Avoid catching "BTC" inside news headlines like "BTC Plummets..."
        # The header with a real ticker has either ( or 🚀 or ⚠️ nearby.
        if any(t in first_line for t in ["🚀", "⚠️", "📉", "(", "🔥", "💪"]):
            return sym
        # Also accept short headers like "ARB (Arbitrum) 🚀" already handled above.
    return None


def _detect_side(text: str, signal_type: str) -> Optional[str]:
    """Direction priority:
       1. Inverted patterns (sell the bounce / buy the dip) override prose.
       2. Header emoji on first line (🚀 long, ⚠️/📉 short).
       3. First Bullish/Bearish token in body.
    """
    st_lower = (signal_type or "").lower()
    for pat, side in INVERTED_PATTERNS.items():
        if pat in st_lower:
            return side

    first_line = text.lstrip().split("\n", 1)[0]
    if "🚀" in first_line:
        return "long"
    if "⚠️" in first_line or "📉" in first_line:
        return "short"

    # Fallback to first matching directional adjective in body
    tl = text.lower()
    bull_pos = tl.find("bullish")
    bear_pos = tl.find("bearish")
    if bull_pos >= 0 and (bear_pos < 0 or bull_pos < bear_pos):
        return "long"
    if bear_pos >= 0:
        return "short"
    return None


def _is_actionable(signal_type: Optional[str]) -> bool:
    if not signal_type:
        return False
    st = signal_type.lower()
    if any(ex in st for ex in EXCLUDED_PATTERNS):
        return False
    return any(p in st for p in ACTIONABLE_PATTERNS)


def _recover_actionable_from_body(text: str) -> Optional[str]:
    """For posts that lack a `Signal Type:` line but use a prose-style header
    ("XYZ Bullish Reversal Spotted!"), find the actionable phrase in the first
    ~200 chars. Defang if the post is a watch-list rather than an entry."""
    head = text[:300].lower()
    if any(d in head for d in WATCHLIST_DEFANG):
        return None
    if any(ex in head for ex in EXCLUDED_PATTERNS):
        return None
    for pat in ACTIONABLE_PATTERNS:
        if pat in head:
            return pat
    return None


def parse_message(text: str) -> Parsed:
    p = Parsed()

    last_m = RE_LAST_PRICE.search(text)
    p.last_price = _f(last_m.group(1)) if last_m else None

    sig_m = RE_SIGNAL_TYPE.search(text)
    p.signal_type = sig_m.group(1).strip().split("\n")[0][:80] if sig_m else None

    p.symbol = _detect_symbol(text)
    p.side = _detect_side(text, p.signal_type or "")

    # No Last Price → almost certainly a news/article post. Drop.
    if p.last_price is None:
        p.category = "news"
        if p.signal_type:
            p.notes.append("no_price_but_has_type")
        return p

    if p.symbol is None:
        p.category = "other"
        p.notes.append("no_symbol")
        return p

    if p.side is None:
        p.category = "other"
        p.notes.append("no_side")
        return p

    # Not in actionable whitelist → fall back to body scan for headline-only
    # entries ("Bullish Reversal Spotted", "Channel Down Breakout Alert").
    if not _is_actionable(p.signal_type):
        recovered = _recover_actionable_from_body(text)
        if recovered:
            if not p.signal_type:
                p.signal_type = recovered.title()
            p.notes.append("recovered_from_body")
            p.category = "directional"
            return p
        p.category = "observational"
        return p

    p.category = "directional"
    return p


def parse_all() -> dict:
    conn = db.connect()
    conn.execute("DELETE FROM returns")
    conn.execute("DELETE FROM baseline_returns")
    conn.execute("DELETE FROM signals")

    rows = conn.execute(
        "SELECT msg_id, posted_at, text FROM messages "
        "WHERE is_reply = 0 ORDER BY posted_at"
    ).fetchall()

    counts: dict = {}
    for r in rows:
        p = parse_message(r["text"])
        counts[p.category] = counts.get(p.category, 0) + 1
        evaluable = p.category == "directional"
        conn.execute(
            "INSERT INTO signals (msg_id, posted_at, category, symbol, side, "
            "last_price, target_pct, target_price, sl_price, signal_type, "
            "parsed_ok, parse_notes) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                r["msg_id"], r["posted_at"], p.category, p.symbol, p.side,
                p.last_price, None, None, None,
                p.signal_type, 1 if evaluable else 0,
                ",".join(p.notes) if p.notes else None,
            ),
        )
    conn.commit()
    counts["_total"] = len(rows)
    counts["_evaluable"] = counts.get("directional", 0)
    return counts


def main() -> None:
    counts = parse_all()
    total = counts.pop("_total")
    ev = counts.pop("_evaluable")
    print(f"\nParsed {total} messages from Signal_Feed_altFINS:")
    for cat in ("directional", "observational", "news", "other"):
        print(f"  {cat:<14} {counts.get(cat, 0):>5}")
    print(f"\n  evaluable      {ev:>5}  (directional only — actionable entry triggers)")


if __name__ == "__main__":
    main()
