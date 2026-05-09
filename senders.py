"""List top senders in the scraped messages, with samples.

Use this to identify which sender_id / username is the official AltFINS
poster. Set ALTFINS_SENDER_USERNAME or ALTFINS_SENDER_ID in .env, and
parse will only consider their messages.
"""
from tabulate import tabulate  # type: ignore

import db


def main() -> None:
    conn = db.connect()
    rows = conn.execute(
        """
        SELECT sender_id, sender_username, sender_name,
               COUNT(*) AS messages,
               SUM(is_reply) AS replies,
               MIN(posted_at) AS first_seen,
               MAX(posted_at) AS last_seen
        FROM messages
        GROUP BY sender_id
        ORDER BY messages DESC
        LIMIT 20
        """
    ).fetchall()

    if not rows:
        print("No messages in DB. Run `python main.py scrape` first.")
        return

    print("\nTop 20 senders:\n")
    print(tabulate(
        [(r["sender_id"], r["sender_username"] or "-",
          (r["sender_name"] or "-")[:30],
          r["messages"], r["replies"],
          r["first_seen"][:10], r["last_seen"][:10]) for r in rows],
        headers=["sender_id", "username", "name", "msgs", "replies",
                 "first", "last"],
    ))

    top = rows[0]
    print(f"\nMost likely AltFINS sender: id={top['sender_id']}, "
          f"username={top['sender_username'] or '(none)'}, "
          f"name={top['sender_name'] or '(none)'}")
    print("\nSet one of these in .env:")
    if top["sender_username"]:
        print(f"  ALTFINS_SENDER_USERNAME={top['sender_username']}")
    print(f"  ALTFINS_SENDER_ID={top['sender_id']}")

    print("\n--- Sample messages from top sender ---")
    samples = conn.execute(
        "SELECT posted_at, substr(text, 1, 400) AS preview "
        "FROM messages WHERE sender_id = ? AND is_reply = 0 "
        "ORDER BY posted_at DESC LIMIT 3",
        (top["sender_id"],),
    ).fetchall()
    for s in samples:
        print(f"\n[{s['posted_at']}]")
        print(s["preview"])


if __name__ == "__main__":
    main()
