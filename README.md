# altfins-audit

Forward-return audit of the public [@altfinsofficialchat](https://t.me/altfinsofficialchat) Telegram chat. Scrapes posts, classifies them, replays each evaluable signal against Binance hourly OHLCV, and compares forward returns to a same-universe random-pick baseline.

This repo is the methodology and code behind [this thread](#) (replace with your tweet URL once posted). Run it yourself, change the parameters, get your own answer.

> **Follow-up addendum:** [Same audit pointed at the dedicated bot signal feed](docs/feed-audit.md) ([@Signal_Feed_altFINS](https://t.me/Signal_Feed_altFINS)) — 470 actionable entries over 54 days, same verdict (no edge) but with a regime caveat.

## What it does

1. **Scrape** — pulls every post from the AltFINS official poster in the chat for the last N days (default 730).
2. **Classify** — labels each post as `directional`, `target`, `conditional`, `news`, `marketing`, `recap`, or `other`. Only `directional` and `target` are evaluated.
3. **Evaluate** — for each evaluable signal, fetches Binance 1h OHLCV from the post's timestamp, anchors entry at the next-bar open, and computes forward returns at +4h, +8h, +12h, +1d, +3d, +7d.
4. **Baseline** — for each signal, picks 5 random other symbols from the AltFINS-signaled universe and computes the same forward returns starting at the same timestamp. This gives a fair "what if you'd picked from their coverage at random" reference.
5. **Report** — directional accuracy, mean/median signed forward return, alpha vs baseline, broken down by side (long/short) and by half-year regime.

## Findings (2024-05-09 → 2026-05-07)

- 1186 messages from the official poster
- 508 evaluable (`directional` + `target`)
- 395 with Binance USDT data; 113 dropped (non-Binance pairs)

| Horizon | n | Direction acc. | Signal mean | Baseline mean | Alpha |
|---|---:|---:|---:|---:|---:|
| +4h | 395 | 42.5% | -0.28% | -0.17% | -0.11% |
| +8h | 395 | 44.3% | -0.38% | -0.22% | -0.16% |
| +12h | 395 | 45.1% | -0.25% | -0.11% | -0.14% |
| +1d | 395 | 41.3% | -0.28% | +0.01% | -0.29% |
| +3d | 395 | 45.3% | -0.36% | +0.54% | -0.90% |
| +7d | 395 | 45.1% | -0.33% | +0.51% | -0.83% |

Direction accuracy stays in the 41–45% band at every horizon. Alpha is small and negative everywhere.

By half-year (24h horizon, direction accuracy):

| Period | n | Dir. acc | Mean (24h) |
|---|---:|---:|---:|
| 2024-H1 | 23 | 39.1% | -0.63% |
| 2024-H2 | 92 | 47.8% | +0.83% |
| 2025-H1 | 69 | 42.0% | -0.30% |
| 2025-H2 | 77 | 45.5% | -0.25% |
| 2026-H1 | 134 | 34.3% | -0.98% |

## Caveats

- **Free chat ≠ paid product.** AltFINS sells a separate signals product. This audit only covers the free public chat.
- **Binance USDT only.** ~22% of posted alerts are on tokens not listed as USDT pairs on Binance and are excluded.
- **Bullish/bearish detection is heuristic.** The classifier reads the post body for direction tokens; it can mislabel.
- **Single 24-month window.** Crypto regimes change; another window could differ.
- **Replies are excluded.** AltFINS sometimes posts updates ("TP1 hit", "move SL") as replies to the original post. The audit evaluates each signal as originally posted — this is intentional, but it ignores active management.
- **No fees / slippage modeled in the alpha calculation.** Mid-bar entry, mid-bar exit, no costs.

## Quick start

```bash
git clone <your-fork-or-this-repo> altfins-audit
cd altfins-audit
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

Edit `.env`:

- `TELEGRAM_API_ID`, `TELEGRAM_API_HASH` — get these from <https://my.telegram.org/apps>. Treat as secrets.
- `ALTFINS_CHANNEL` — defaults to `altfinsofficialchat`. The public chat handle.
- `ALTFINS_SENDER_USERNAME=altfinsofficial` — restricts parsing to the official poster, ignoring member chatter. Run `python main.py senders` after the first scrape if you want to verify.
- `SCRAPE_DAYS=730` — how far back to backfill.

Then:

```bash
python main.py scrape    # interactive on first run: phone, login code, optional 2FA
python main.py senders   # optional: see top posters in the chat
python main.py parse     # category breakdown
python main.py evaluate  # pulls Binance OHLCV for each signal + 5 baseline picks per signal
python main.py report    # prints the tables shown above
```

Evaluation takes a while on first run (~15 min) because it fetches 1h Binance OHLCV for hundreds of symbols. Bars are cached in SQLite, so re-runs are seconds.

## Project layout

| File | Purpose |
|---|---|
| `db.py` | SQLite schema + `connect()` |
| `scrape.py` | Telethon backfill of messages |
| `senders.py` | Diagnostic: who's posting in the chat |
| `parse.py` | Classifier + field extractor (regex-based) |
| `evaluate.py` | Forward-return computation + baseline |
| `report.py` | Aggregation tables |
| `main.py` | CLI entry: `scrape | senders | parse | evaluate | report` |

All persistent state — SQLite DB, Telethon session — lives in `store/` and is gitignored.

## Re-running on a different signal source

The harness is generic. If you have a CSV of signals from any source with columns `posted_at, symbol, side, target_pct (optional), sl (optional)`, you can skip `scrape`/`parse` and load straight into the `signals` table, then run `evaluate` and `report`. PRs welcome.

## Open invitation

If you run a paid signal service and think your product would score better than this free-chat sample: send a CSV of your signals for any window and I'll publish a like-for-like result.

## License

MIT.
