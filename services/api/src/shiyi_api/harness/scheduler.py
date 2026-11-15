"""Opt-in local worker; run separately from the API with the same SQLite path."""
import argparse
import json
import sqlite3
import time

from ..storage import get_store
from .proactive import tick


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--once", action="store_true", help="Process one due batch and exit")
    parser.add_argument("--interval", type=int, default=30, choices=range(5, 301),
                        metavar="5..300", help="Scan interval in seconds")
    args = parser.parse_args()
    store = get_store()
    while True:
        try:
            outcomes = tick(store)
            print(json.dumps({"proactive_demo": True, "outcomes": outcomes}), flush=True)
        except sqlite3.OperationalError:
            if args.once:
                raise
            print("Proactive scan deferred: database unavailable", flush=True)
        if args.once:
            return
        time.sleep(args.interval)


if __name__ == "__main__":
    main()
