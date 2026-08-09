from __future__ import annotations

import argparse
import json
import os
import tempfile
from pathlib import Path
from urllib.parse import urlsplit
from uuid import uuid4

import psycopg
from psycopg import sql

from scripts.platform_recovery import (
    DatabaseTarget,
    RecoveryError,
    _database_target_from_environment,
    create_recovery_point,
    restore_recovery_point,
    verify_rehearsal_report,
)


def _assert_local(target: DatabaseTarget) -> None:
    if target.host.lower() not in {"127.0.0.1", "localhost", "::1"}:
        raise RecoveryError("Disaster-recovery verification requires loopback PostgreSQL")


def _admin_connection(target: DatabaseTarget):
    return psycopg.connect(
        host=target.host,
        port=target.port,
        dbname=target.database,
        user=target.user,
        password=target.password,
        autocommit=True,
        **{
            key.removeprefix("PG").lower(): value
            for key, value in target.options.items()
            if key == "PGSSLMODE"
        },
    )


def verify(database_url_environment: str) -> dict:
    source = _database_target_from_environment(database_url_environment)
    _assert_local(source)
    target_name = f"opf_dr_{uuid4().hex[:12]}"
    target = DatabaseTarget(
        host=source.host,
        port=source.port,
        database=target_name,
        user=source.user,
        password=source.password,
        options=source.options,
    )
    with _admin_connection(source) as connection:
        connection.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(target_name)))
    try:
        with tempfile.TemporaryDirectory(prefix="opf-dr-verification-") as temporary:
            root = Path(temporary)
            recovery_root = root / "recovery"
            report_root = root / "reports"
            public_root = root / "source-public"
            private_root = root / "source-private"
            rollback_root = root / "source-rollback"
            for directory in (
                recovery_root,
                report_root,
                public_root,
                private_root,
                rollback_root,
            ):
                directory.mkdir()
            (public_root / "inspection.jpg").write_bytes(b"public-recovery-evidence")
            nested = private_root / "knowledge"
            nested.mkdir()
            (nested / "repair.bin").write_bytes(b"private-recovery-evidence")
            (rollback_root / "rollback.json").write_bytes(b"rollback-recovery-evidence")

            created = create_recovery_point(
                database=source,
                output_root=recovery_root,
                public_root=public_root,
                private_root=private_root,
                rollback_root=rollback_root,
                source_version=os.environ.get("VCS_REF", "ci"),
            )
            report_path = report_root / "rehearsal.json"
            report = restore_recovery_point(
                source_database=source,
                target_database=target,
                recovery_point=Path(created["recovery_point"]),
                target_public_root=root / "restored-public",
                target_private_root=root / "restored-private",
                target_rollback_root=root / "restored-rollback",
                report_path=report_path,
                confirm_isolated=True,
            )
            verified = verify_rehearsal_report(
                report_path,
                max_rpo_seconds=300,
                max_rto_seconds=120,
            )
            if (root / "restored-public" / "inspection.jpg").read_bytes() != b"public-recovery-evidence":
                raise RecoveryError("Public evidence sentinel did not restore")
            if (root / "restored-private" / "knowledge" / "repair.bin").read_bytes() != b"private-recovery-evidence":
                raise RecoveryError("Private evidence sentinel did not restore")
            if (root / "restored-rollback" / "rollback.json").read_bytes() != b"rollback-recovery-evidence":
                raise RecoveryError("Rollback evidence sentinel did not restore")
            return {
                "status": "passed",
                "format": report["format"],
                "schema_revision": report["schema_revision"],
                "manifest_sha256": verified["manifest_sha256"],
                "database_row_count": verified["database_row_count"],
                "evidence_file_count": verified["evidence_file_count"],
                "rpo_seconds": verified["rpo_seconds"],
                "rto_seconds": verified["rto_seconds"],
                "isolated_database_dropped": True,
            }
    finally:
        with _admin_connection(source) as connection:
            connection.execute(
                "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                "WHERE datname = %s AND pid <> pg_backend_pid()",
                (target_name,),
            )
            connection.execute(sql.SQL("DROP DATABASE IF EXISTS {}").format(sql.Identifier(target_name)))


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run an isolated PostgreSQL and evidence-volume recovery rehearsal."
    )
    parser.add_argument("--database-url-env", default="DATABASE_URL")
    parser.add_argument("--confirm-isolated-ci", action="store_true")
    args = parser.parse_args()
    if not args.confirm_isolated_ci:
        print(json.dumps({"status": "failed", "error": "isolated CI confirmation is required"}))
        return 1
    try:
        result = verify(args.database_url_env)
    except (RecoveryError, psycopg.Error, OSError) as exc:
        error = str(exc) if isinstance(exc, RecoveryError) else "isolated recovery infrastructure failed"
        print(json.dumps({"status": "failed", "error": error}, sort_keys=True))
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
