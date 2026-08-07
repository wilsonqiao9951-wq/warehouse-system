from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from app.services.legacy_database_adoption import (
    LegacyDatabaseAdoptionError,
    adopt_legacy_sqlite_database,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Safely validate or adopt an unversioned OpenPartsFlow SQLite "
            "database into the Alembic migration history."
        )
    )
    parser.add_argument(
        "--database",
        type=Path,
        default=Path("openpartsflow.db"),
        help="SQLite database path (default: ./openpartsflow.db)",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help=(
            "Create a permanent backup and atomically replace the source after "
            "all checks pass. Without this flag, the command is read-only."
        ),
    )
    parser.add_argument(
        "--lock-timeout",
        type=float,
        default=2.0,
        help="Seconds to wait for the exclusive apply lock (default: 2)",
    )
    return parser


def main() -> int:
    args = _parser().parse_args()
    try:
        report = adopt_legacy_sqlite_database(
            args.database,
            apply=args.apply,
            lock_timeout_seconds=args.lock_timeout,
        )
    except LegacyDatabaseAdoptionError as exc:
        print(f"Legacy database adoption refused: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:
        print(f"Legacy database adoption failed: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(report.as_dict(), ensure_ascii=False, indent=2))
    if not args.apply:
        print(
            "Dry run passed. Stop the backend and rerun with --apply to perform "
            "the verified replacement.",
            file=sys.stderr,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
