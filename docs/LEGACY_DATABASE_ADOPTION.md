# Legacy SQLite database adoption

OpenPartsFlow now treats Alembic as the only production schema owner. Older
local databases may contain business tables created by SQLAlchemy at runtime
without an `alembic_version`. Do not use `alembic stamp head` on those files:
stamping records a version without actually adding the missing columns,
constraints, indexes, or tables.

## Read-only rehearsal

From the repository root, with the project virtual environment active:

```powershell
python -m scripts.adopt_legacy_database --database .\openpartsflow.db
```

The rehearsal creates disposable snapshots and candidates only. It verifies:

- SQLite integrity and every foreign key;
- that no source-only table or column would be discarded;
- that each missing required column has a safe default or explicit derivation;
- every table row count and a SHA-256 digest of every shared source value;
- derived legacy values such as `min_stock`, `total_cost`, and work-order aliases;
- the final Alembic head and candidate integrity.

The source file is not changed and all temporary files are removed.

## Apply after stopping the backend

```powershell
python -m scripts.adopt_legacy_database --database .\openpartsflow.db --apply
```

Apply mode requires SQLite `journal_mode=DELETE` and an exclusive database
lock. It refuses to continue when another process is using the file. Once the
lock is held, it:

1. creates a permanent `*.pre-alembic-*.db` backup;
2. migrates an isolated empty candidate through the complete Alembic history;
3. copies and verifies the legacy records while the source remains locked;
4. flushes the candidate and atomically replaces the live database;
5. reopens and validates the result;
6. writes a secret-free `*.adoption-*.json` audit report.

If post-replacement verification fails, the retained backup is copied back
atomically. A failure before replacement leaves the source untouched and keeps
any already-created backup for investigation.

## Automatic local startup

`scripts/start-dev.ps1` runs `python -m scripts.prepare_database` before either
service starts. It automatically adopts only a detected unversioned local
SQLite database using the protected apply flow above; normal versioned
databases receive `alembic upgrade head`. Service startup stops on any database
preparation error.

Unknown tables, unknown columns, broken integrity, foreign-key violations,
non-empty Alembic metadata, active database users, and unsafe journal modes all
fail closed. PostgreSQL and already-versioned databases continue through the
normal Alembic upgrade path.
