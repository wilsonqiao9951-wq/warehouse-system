from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts import platform_recovery
from scripts.platform_recovery import DatabaseTarget, RecoveryError
from scripts.verify_scale_performance import _percentile, _plan_nodes
from app.services.data_restores import RESTORE_SCHEMA_COMPATIBILITY


def _target(database: str) -> DatabaseTarget:
    return DatabaseTarget(
        host="127.0.0.1",
        port=5432,
        database=database,
        user="owner",
        password="secret",
        options={},
    )


def _source_roots(tmp_path: Path) -> tuple[Path, Path, Path, Path]:
    output = tmp_path / "recovery"
    public = tmp_path / "public"
    private = tmp_path / "private"
    rollback = tmp_path / "rollback"
    for root in (output, public, private, rollback):
        root.mkdir()
    (public / "photo.bin").write_bytes(b"public")
    nested = private / "knowledge"
    nested.mkdir()
    (nested / "guide.bin").write_bytes(b"private")
    (rollback / "before.bin").write_bytes(b"rollback")
    return output, public, private, rollback


def _create(tmp_path: Path, monkeypatch) -> dict:
    output, public, private, rollback = _source_roots(tmp_path)
    monkeypatch.setattr(
        platform_recovery,
        "_database_evidence",
        lambda _target: ("20260808_0067", {"parts": 2, "work_orders": 3}),
    )

    def fake_run(command, _target, *, capture_output=False):
        assert command[0] == "pg_dump"
        Path(command[command.index("--file") + 1]).write_bytes(b"database archive")
        return ""

    monkeypatch.setattr(platform_recovery, "_run_postgres", fake_run)
    return platform_recovery.create_recovery_point(
        database=_target("source"),
        output_root=output,
        public_root=public,
        private_root=private,
        rollback_root=rollback,
        source_version="test-commit",
    )


def test_recovery_point_and_isolated_restore_round_trip(tmp_path, monkeypatch):
    created = _create(tmp_path, monkeypatch)
    recovery_point = Path(created["recovery_point"])
    manifest = json.loads((recovery_point / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["format"] == platform_recovery.RECOVERY_FORMAT
    assert manifest["database"]["row_count"] == 5
    assert manifest["volumes"]["private"]["files"][0]["path"] == "knowledge/guide.bin"

    monkeypatch.setattr(platform_recovery, "_assert_empty_database", lambda _target: None)
    monkeypatch.setattr(platform_recovery, "_run_postgres", lambda *_args, **_kwargs: "")
    monkeypatch.setattr(
        platform_recovery,
        "_database_evidence",
        lambda _target: ("20260808_0067", {"parts": 2, "work_orders": 3}),
    )
    report_path = tmp_path / "report.json"
    report = platform_recovery.restore_recovery_point(
        source_database=_target("source"),
        target_database=_target("isolated"),
        recovery_point=recovery_point,
        target_public_root=tmp_path / "restored-public",
        target_private_root=tmp_path / "restored-private",
        target_rollback_root=tmp_path / "restored-rollback",
        report_path=report_path,
        confirm_isolated=True,
    )
    assert report["status"] == "passed"
    assert report["database_row_count"] == 5
    assert (tmp_path / "restored-public" / "photo.bin").read_bytes() == b"public"
    assert (tmp_path / "restored-private" / "knowledge" / "guide.bin").read_bytes() == b"private"
    assert (tmp_path / "restored-rollback" / "before.bin").read_bytes() == b"rollback"
    verified = platform_recovery.verify_rehearsal_report(
        report_path,
        max_rpo_seconds=60,
        max_rto_seconds=60,
    )
    assert verified["status"] == "verified"


def test_recovery_restore_refuses_same_database_and_tampered_archive(tmp_path, monkeypatch):
    created = _create(tmp_path, monkeypatch)
    recovery_point = Path(created["recovery_point"])
    with pytest.raises(RecoveryError, match="must not be the source"):
        platform_recovery.restore_recovery_point(
            source_database=_target("same"),
            target_database=_target("same"),
            recovery_point=recovery_point,
            target_public_root=tmp_path / "target-public",
            target_private_root=tmp_path / "target-private",
            target_rollback_root=tmp_path / "target-rollback",
            report_path=tmp_path / "report.json",
            confirm_isolated=True,
        )

    with (recovery_point / "public.tar.gz").open("ab") as handle:
        handle.write(b"tampered")
    with pytest.raises(RecoveryError, match="byte count does not match"):
        platform_recovery.restore_recovery_point(
            source_database=_target("source"),
            target_database=_target("isolated"),
            recovery_point=recovery_point,
            target_public_root=tmp_path / "target-public",
            target_private_root=tmp_path / "target-private",
            target_rollback_root=tmp_path / "target-rollback",
            report_path=tmp_path / "report.json",
            confirm_isolated=True,
        )


def test_recovery_restore_rejects_malformed_rehashed_manifest(tmp_path, monkeypatch):
    created = _create(tmp_path, monkeypatch)
    recovery_point = Path(created["recovery_point"])
    manifest_path = recovery_point / platform_recovery.MANIFEST_NAME
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest.pop("database")
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    (recovery_point / platform_recovery.MANIFEST_HASH_NAME).write_text(
        platform_recovery._sha256_bytes(platform_recovery._canonical_json(manifest)),
        encoding="ascii",
    )
    with pytest.raises(RecoveryError, match="manifest sections are invalid"):
        platform_recovery.restore_recovery_point(
            source_database=_target("source"),
            target_database=_target("isolated"),
            recovery_point=recovery_point,
            target_public_root=tmp_path / "target-public",
            target_private_root=tmp_path / "target-private",
            target_rollback_root=tmp_path / "target-rollback",
            report_path=tmp_path / "report.json",
            confirm_isolated=True,
        )


def test_recovery_url_parsing_and_report_budget(monkeypatch, tmp_path):
    monkeypatch.setenv(
        "RECOVERY_DATABASE_URL",
        "postgresql+psycopg://owner:p%40ss@localhost:5544/openpartsflow?sslmode=require",
    )
    target = platform_recovery._database_target_from_environment("RECOVERY_DATABASE_URL")
    assert target.password == "p@ss"
    assert target.port == 5544
    assert target.options == {"PGSSLMODE": "require"}
    environment = target.subprocess_environment()
    assert environment["PGPASSWORD"] == "p@ss"
    assert environment["PGOPTIONS"] == "-c openpartsflow.platform_access=on"

    report_path = tmp_path / "report.json"
    report_path.write_text(
        json.dumps(
            {
                "format": platform_recovery.REPORT_FORMAT,
                "status": "passed",
                "isolation_confirmed": True,
                "recovery_point_id": "test",
                "manifest_sha256": "a" * 64,
                "rpo_seconds": 61,
                "rto_seconds": 1,
                "database_row_count": 1,
                "evidence_file_count": 1,
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(RecoveryError, match="RPO evidence budget"):
        platform_recovery.verify_rehearsal_report(
            report_path,
            max_rpo_seconds=60,
            max_rto_seconds=60,
        )


def test_complete_database_evidence_refuses_tenant_scoped_role(monkeypatch):
    monkeypatch.setattr(platform_recovery, "_query", lambda _target, _sql: "f")
    with pytest.raises(RecoveryError, match="requires a PostgreSQL role with BYPASSRLS"):
        platform_recovery._database_evidence(_target("source"))


def test_scale_percentile_and_plan_flattening():
    assert _percentile([4, 1, 3, 2], 0.5) == 2
    nodes = _plan_nodes(
        {
            "Node Type": "Limit",
            "Plans": [
                {
                    "Node Type": "Index Scan",
                    "Index Name": "ix_work_orders_org_id",
                }
            ],
        }
    )
    assert [node["Node Type"] for node in nodes] == ["Limit", "Index Scan"]


def test_portable_restore_compatibility_continues_through_scale_revision():
    compatible = RESTORE_SCHEMA_COMPATIBILITY["20260808_0067"]
    assert {
        "20260808_0064",
        "20260808_0065",
        "20260808_0066",
        "20260808_0067",
    } <= compatible
