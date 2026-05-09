"""CLI: scrape -> senders -> parse -> evaluate -> report.

Usage:
    python main.py scrape       # backfill last SCRAPE_DAYS days from Telegram
    python main.py senders      # list top senders so you can pick AltFINS
    python main.py parse        # parse signals (filtered by ALTFINS_SENDER_*)
    python main.py evaluate     # first-touch evaluation against Binance OHLCV
    python main.py report       # print aggregate stats
"""
import sys

import evaluate
import parse as parse_mod
import report
import scrape
import senders


def main() -> None:
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    cmd = sys.argv[1]
    if cmd == "scrape":
        scrape.main()
    elif cmd == "senders":
        senders.main()
    elif cmd == "parse":
        parse_mod.main()
    elif cmd == "evaluate":
        evaluate.main()
    elif cmd == "report":
        report.main()
    else:
        print(f"unknown command: {cmd}")
        print(__doc__)
        sys.exit(1)


if __name__ == "__main__":
    main()
