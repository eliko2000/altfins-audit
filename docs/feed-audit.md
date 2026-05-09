# Follow-up: @Signal_Feed_altFINS audit

Same harness, same methodology as the [main audit](../README.md), pointed at the
dedicated free signals broadcast channel ([t.me/Signal_Feed_altFINS](https://t.me/Signal_Feed_altFINS))
instead of the open chat.

## Why this audit exists

The main audit covered the open chat, where messages mix curated trade ideas
with member chatter. A natural pushback: "you should be looking at their
dedicated signal feed instead." This addendum does that.

## What's in the channel

`@Signal_Feed_altFINS` is a broadcast channel posted to by `Altfins_signals_bot`.
Posts arrive ~21/day in a structured format:

```
SYMBOL ( Long Name) 🚀
Short tagline mentioning Bullish/Bearish
Last Price: $X | Market Cap: $Y
Signal Type: <pattern>
Description of the pattern
```

Direction is encoded in the header (🚀 = bullish, ⚠️/📉 = bearish). The
`Signal Type:` line names a pattern (e.g. `Bullish Cross Price above EMA 12 and EMA 26`,
`New Local High (15 periods)`, `Bounced Up in Downtrend (sell the bounce)`).

A handful of patterns are inverted: "Bounced Up in Downtrend (sell the bounce)"
is tagged Bearish in the prose but is a *short* setup; "Pullback in Uptrend
(buy the dip)" is a *long* setup. The parser ([`parse_signal_feed.py`](../parse_signal_feed.py))
handles these via an explicit override map.

## The "fairness" filter

Not every post is an actionable trade call. The channel emits a long tail of
**observational** patterns that describe the chart without telling you to enter:

- `Doji` (indecision)
- `Trading in a Range` (sideways)
- `Within 5–10% of ATH` / `Recent ATH` (price-level annotations)
- `Unusual Volume Gainer` / `Decliner` (volume anomaly, no direction)
- `Very Overbought` / `Very Oversold` (contrarian observations, not entries)

The audit excludes those. Only **actionable entry triggers** — Bullish/Bearish
Crosses, Breakouts, New Local High/Low, Momentum Inflections, Strong
Up/Downtrends, Trend Upgrades/Downgrades, the buy-the-dip/sell-the-bounce
patterns, and their headline-format equivalents (e.g. `Channel Down Breakout
Alert`, `Bullish Reversal Spotted`) — are evaluated.

This is *more generous to altFINS* than the main audit: we throw out the noise
and keep only what a trader would actually act on.

## Sample

| Bucket | Count |
|---|---:|
| Total messages scraped (54 days) | 1,237 |
| → directional (actionable entries) | 682 |
| → observational (excluded — Doji / Range / ATH / Volume) | 263 |
| → news (no Last Price / no symbol) | 238 |
| → other | 54 |
| **Evaluable** (had Binance USDT data) | **470** |
| ↳ long calls | 203 |
| ↳ short calls | 267 |

Side balance is far more even than the open chat (314L / 81S).

The window is **2026-03-16 → 2026-05-09**, which is the full posting history
of the channel — it doesn't go further back. The whole sample sits inside one
bull-market regime, which matters for interpretation (see Caveats).

## Findings

### Overall (470 signals, all sides)

| Horizon | n | Direction acc. | Signal mean | Baseline mean | Alpha |
|---|---:|---:|---:|---:|---:|
| +4h | 470 | 49.8% | -0.14% | -0.02% | -0.12% |
| +8h | 470 | 47.4% | -0.14% | +0.01% | -0.15% |
| +12h | 470 | 47.9% | -0.07% | +0.08% | -0.16% |
| +1d | 470 | 45.5% | -0.19% | +0.23% | -0.42% |
| +3d | 470 | 45.3% | -0.49% | +0.48% | -0.98% |
| +7d | 470 | 49.6% | -0.25% | +1.56% | -1.80% |

Direction accuracy hovers near coin flip (45–50%). Alpha negative at every
horizon. The fairness filter didn't save the verdict.

### Long calls only (203 signals)

| Horizon | Dir acc | Signal mean | Baseline mean | Alpha |
|---|---:|---:|---:|---:|
| +4h | 49.8% | -0.18% | -0.02% | -0.16% |
| +8h | 47.8% | -0.01% | +0.01% | -0.02% |
| +12h | 48.3% | +0.30% | +0.08% | +0.21% |
| +1d | 46.8% | +0.22% | +0.23% | -0.01% |
| +3d | 45.3% | +0.33% | +0.48% | -0.15% |
| +7d | 54.7% | +1.62% | +1.56% | +0.07% |

**Roughly at-random.** Alpha within ±0.21% across all horizons — well inside
noise. The longs aren't winners but they're not destroying value either.

### Short calls only (267 signals)

| Horizon | Dir acc | Signal mean | Baseline mean | Alpha |
|---|---:|---:|---:|---:|
| +4h | 49.8% | -0.11% | -0.02% | -0.09% |
| +8h | 47.2% | -0.23% | +0.01% | -0.24% |
| +12h | 47.6% | -0.35% | +0.08% | -0.44% |
| +1d | 44.6% | -0.49% | +0.23% | -0.72% |
| +3d | 45.3% | -1.12% | +0.48% | -1.60% |
| +7d | 45.7% | -1.67% | +1.56% | **-3.23%** |

**Structurally losing in this window.** Alpha gets monotonically worse with
horizon. The "Bounced Up in Downtrend (sell the bounce)" pattern averaged a
+0.93% forward return at 24h — i.e. the bounces the bot told you to fade kept
going up.

## Caveats

All caveats from the main audit apply, plus:

- **Single regime, 54 days.** The whole sample is bull-market — random baseline
  is already +1.56% at +7d. We can't tell from this alone whether shorts are
  *structurally* bad or just regime-mismatched. The main audit had 24 months
  and saw the same pattern across regimes; this one doesn't have the runway.
- **Channel age.** `@Signal_Feed_altFINS` only goes back ~54 days as of the
  scrape date. Re-running this in 6 months will give a much stronger sample.
- **No fees / slippage.** Same as the main audit — alpha is computed at mid-bar
  fills with zero cost.

## Reproducibility

```bash
# After the main quick-start setup:
echo "ALTFINS_CHANNEL=Signal_Feed_altFINS" >> .env  # (replace the existing line)
echo "SCRAPE_DAYS=90"                               >> .env  # (replace the existing line)
mv store/altfins.db store/altfins_chat.db           # back up the open-chat audit

python main.py scrape
python parse_signal_feed.py    # NOT main.py parse — different parser
python main.py evaluate
python main.py report
python render_feed_pngs.py
```
