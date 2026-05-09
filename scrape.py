"""Backfill messages from an AltFINS Telegram chat into SQLite.

Captures sender_id, username, and reply-status for every message so we can
later filter to just the official AltFINS poster(s). Run `python main.py
senders` after scraping to see who's actually posting.

First run is interactive: Telethon prompts for phone, login code, and 2FA
if set. Session is cached in store/altfins.session.
"""
import asyncio
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

from dotenv import load_dotenv  # type: ignore
from telethon import TelegramClient

import db

SESSION_PATH = Path(__file__).parent / "store" / "altfins"


def _sender_fields(sender) -> tuple:
    """Pull (id, username, display_name) from a Telethon User/Channel entity."""
    if sender is None:
        return (None, None, None)
    sid = getattr(sender, "id", None)
    username = getattr(sender, "username", None)
    name = " ".join(
        x for x in [getattr(sender, "first_name", None),
                    getattr(sender, "last_name", None),
                    getattr(sender, "title", None)] if x
    ).strip() or None
    return (sid, username, name)


async def backfill(channel: str, days: int) -> int:
    api_id = int(os.environ["TELEGRAM_API_ID"])
    api_hash = os.environ["TELEGRAM_API_HASH"]

    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    conn = db.connect()

    inserted = 0
    async with TelegramClient(str(SESSION_PATH), api_id, api_hash) as client:
        async for msg in client.iter_messages(channel, offset_date=None, reverse=False):
            if msg.date < cutoff:
                break
            text = msg.message or ""
            if not text.strip():
                continue
            sender = await msg.get_sender() if msg.sender_id else None
            sid, uname, sname = _sender_fields(sender)
            cur = conn.execute(
                "INSERT OR IGNORE INTO messages (msg_id, channel, posted_at, text, "
                "sender_id, sender_username, sender_name, is_reply, raw_json) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    msg.id,
                    channel,
                    msg.date.isoformat(),
                    text,
                    sid,
                    uname,
                    sname,
                    1 if msg.reply_to_msg_id else 0,
                    json.dumps({"views": getattr(msg, "views", None),
                                "reply_to": msg.reply_to_msg_id}),
                ),
            )
            if cur.rowcount:
                inserted += 1
    conn.commit()
    return inserted


def main() -> None:
    load_dotenv()
    channel = os.environ.get("ALTFINS_CHANNEL", "altfinsofficialchat")
    days = int(os.environ.get("SCRAPE_DAYS", "180"))
    n = asyncio.run(backfill(channel, days))
    print(f"scraped {n} new messages from @{channel} (last {days} days)")
    print("next: run `python main.py senders` to see who's posting")


if __name__ == "__main__":
    main()
