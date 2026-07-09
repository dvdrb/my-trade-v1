from __future__ import annotations

import argparse

from app.data.db import DEFAULT_DB_PATH, init_db


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", default=str(DEFAULT_DB_PATH))
    args = parser.parse_args()
    init_db(args.db)
    print(f"Initialized SQLite database at {args.db}")


if __name__ == "__main__":
    main()
