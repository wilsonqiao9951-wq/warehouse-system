from datetime import datetime, timedelta
import json

from sqlalchemy import select

from app.core.config import settings
from app.core.security import hash_password
from app.models import (
    AuditLog,
    Organization,
    OrganizationDataExport,
    OrganizationDataRestore,
    User,
    UserRole,
)


def _export(organization_id: int, generated_at: datetime, digest: str):
    return OrganizationDataExport(
        organization_id=organization_id,
        requested_by=None,
        sha256=digest * 64,
        size_bytes=128,
        record_count=2,
        file_count=0,
        missing_file_count=0,
        include_files=False,
        table_counts_json='{"parts":2}',
        generated_at=generated_at,
        created_at=generated_at,
        updated_at=generated_at,
    )


def _restore(
    organization_id: int,
    *,
    status: str,
    updated_at: datetime,
    digest: str,
    matched_export_id: int | None = None,
    rollback_payload: str | None = None,
    rollback_expires_at: datetime | None = None,
    file_rollback_size_bytes: int = 0,
):
    return OrganizationDataRestore(
        organization_id=organization_id,
        requested_by=None,
        matched_export_id=matched_export_id,
        status=status,
        archive_sha256=digest * 64,
        archive_size_bytes=128,
        plan_sha256=digest.upper() * 64,
        source_schema_revision="20260807_0052",
        source_exported_at=updated_at,
        record_count=2,
        file_count=1 if file_rollback_size_bytes else 0,
        create_count=0,
        file_create_count=0,
        file_overwrite_count=1 if file_rollback_size_bytes else 0,
        file_unchanged_count=0,
        file_conflict_count=0,
        update_count=1,
        unchanged_count=1,
        conflict_count=0,
        protected_count=0,
        table_summary_json="{}",
        validation_messages_json="[]",
        rollback_payload_json=rollback_payload,
        rollback_sha256=(digest * 64 if rollback_payload else None),
        rollback_size_bytes=(len(rollback_payload.encode("utf-8")) if rollback_payload else 0),
        file_rollback_sha256=(digest * 64 if file_rollback_size_bytes else None),
        file_rollback_size_bytes=file_rollback_size_bytes,
        rollback_expires_at=rollback_expires_at,
        applied_at=updated_at if status == "applied" else None,
        created_at=updated_at,
        updated_at=updated_at,
    )


def test_retention_preview_and_cleanup_preserve_active_evidence(client, tmp_path, monkeypatch):
    rollback_root = tmp_path / "rollback"
    monkeypatch.setattr(settings, "data_restore_rollback_files_root", str(rollback_root))
    now = datetime.utcnow()
    old = now - timedelta(days=400)
    rollback_payload = '{"database":[{"safe":"rollback"}],"files":[]}'
    with client.app.state.testing_session_local() as db:
        stale_export = _export(1, old, "a")
        protected_export = _export(1, old, "b")
        recent_export = _export(1, now, "c")
        db.add_all([stale_export, protected_export, recent_export])
        db.flush()
        stale_restore = _restore(
            1,
            status="rejected",
            updated_at=old,
            digest="d",
            matched_export_id=stale_export.id,
        )
        protected_restore = _restore(
            1,
            status="approved",
            updated_at=old,
            digest="e",
            matched_export_id=protected_export.id,
        )
        expired_rollback = _restore(
            1,
            status="applied",
            updated_at=old,
            digest="f",
            rollback_payload=rollback_payload,
            rollback_expires_at=now - timedelta(days=1),
            file_rollback_size_bytes=5,
        )
        db.add_all([stale_restore, protected_restore, expired_rollback])
        other = Organization(name="Other Retention Tenant", slug="other-retention")
        db.add(other)
        db.flush()
        other_export = _export(other.id, old, "9")
        other_restore = _restore(
            other.id,
            status="rejected",
            updated_at=old,
            digest="8",
        )
        db.add_all([other_export, other_restore])
        db.commit()
        ids = {
            "stale_export": stale_export.id,
            "protected_export": protected_export.id,
            "recent_export": recent_export.id,
            "stale_restore": stale_restore.id,
            "protected_restore": protected_restore.id,
            "expired_rollback": expired_rollback.id,
            "other_export": other_export.id,
            "other_restore": other_restore.id,
        }

    evidence = rollback_root / "organization-1" / f"restore-{ids['expired_rollback']}"
    evidence.mkdir(parents=True)
    (evidence / "evidence.bin").write_bytes(b"12345")

    preview = client.get("/api/organization/data-retention")
    assert preview.status_code == 200, preview.text
    overview = preview.json()
    assert overview["export_evidence_candidates"] == 1
    assert overview["restore_rehearsal_candidates"] == 1
    assert overview["rollback_evidence_candidates"] == 1
    assert overview["rollback_database_bytes"] == len(rollback_payload.encode("utf-8"))
    assert overview["rollback_file_bytes"] == 5

    cleaned = client.post(
        "/api/organization/data-retention/cleanup",
        json={
            "expected_version": overview["settings_version"],
            "reason": "Annual governed recovery evidence cleanup",
            "max_items": 100,
        },
    )
    assert cleaned.status_code == 200, cleaned.text
    result = cleaned.json()
    assert result["export_evidence_deleted"] == 1
    assert result["restore_rehearsals_deleted"] == 1
    assert result["rollback_evidence_purged"] == 1
    assert result["rollback_file_bytes_purged"] == 5
    assert result["file_cleanup_pending"] is False
    assert result["remaining_candidates"] == 0
    assert not evidence.exists()

    with client.app.state.testing_session_local() as db:
        assert db.get(OrganizationDataExport, ids["stale_export"]) is None
        assert db.get(OrganizationDataRestore, ids["stale_restore"]) is None
        assert db.get(OrganizationDataExport, ids["protected_export"]) is not None
        assert db.get(OrganizationDataExport, ids["recent_export"]) is not None
        assert db.get(OrganizationDataRestore, ids["protected_restore"]) is not None
        assert db.get(OrganizationDataExport, ids["other_export"]) is not None
        assert db.get(OrganizationDataRestore, ids["other_restore"]) is not None
        expired = db.get(OrganizationDataRestore, ids["expired_rollback"])
        assert expired.status == "applied"
        assert expired.rollback_payload_json is None
        assert expired.rollback_sha256 is None
        assert expired.rollback_size_bytes == 0
        assert expired.file_rollback_sha256 is None
        assert expired.file_rollback_size_bytes == 0
        assert expired.rollback_evidence_purged_at is not None
        audit = db.scalar(
            select(AuditLog).where(
                AuditLog.action == "organization_data_retention_cleanup"
            )
        )
        metadata = json.loads(audit.metadata_json)
        assert metadata["reason"] == "Annual governed recovery evidence cleanup"
        assert "safe" not in audit.metadata_json
        assert rollback_payload not in audit.metadata_json

    repeated = client.post(
        "/api/organization/data-retention/cleanup",
        json={
            "expected_version": overview["settings_version"],
            "reason": "Confirm cleanup is idempotent",
        },
    )
    assert repeated.status_code == 200
    assert repeated.json()["remaining_candidates"] == 0
    assert repeated.json()["rollback_evidence_purged"] == 0


def test_retention_policy_auth_version_and_interrupted_file_recovery(
    client, tmp_path, monkeypatch
):
    rollback_root = tmp_path / "rollback"
    monkeypatch.setattr(settings, "data_restore_rollback_files_root", str(rollback_root))
    now = datetime.utcnow()
    with client.app.state.testing_session_local() as db:
        active = _restore(
            1,
            status="applied",
            updated_at=now,
            digest="1",
            rollback_payload='{"database":[],"files":[]}',
            rollback_expires_at=now + timedelta(days=30),
            file_rollback_size_bytes=6,
        )
        db.add(active)
        db.commit()
        active_id = active.id
    quarantined = (
        rollback_root
        / ".retention-cleanup"
        / "organization-1"
        / f"restore-{active_id}"
    )
    quarantined.mkdir(parents=True)
    (quarantined / "active.bin").write_bytes(b"active")

    initial = client.get("/api/organization/data-retention").json()
    invalid = client.put(
        "/api/organization/data-retention",
        json={
            "expected_version": initial["settings_version"],
            "data_export_evidence_retention_days": 365,
            "data_restore_rehearsal_retention_days": 90,
            "data_restore_rollback_retention_days": 30,
            "reason": "   ",
        },
    )
    assert invalid.status_code == 422
    updated = client.put(
        "/api/organization/data-retention",
        json={
            "expected_version": initial["settings_version"],
            "data_export_evidence_retention_days": 730,
            "data_restore_rehearsal_retention_days": 120,
            "data_restore_rollback_retention_days": 45,
            "reason": "Updated contractual retention schedule",
        },
    )
    assert updated.status_code == 200, updated.text
    policy = updated.json()
    assert policy["settings_version"] == initial["settings_version"] + 1
    stale = client.put(
        "/api/organization/data-retention",
        json={
            "expected_version": initial["settings_version"],
            "data_export_evidence_retention_days": 365,
            "data_restore_rehearsal_retention_days": 90,
            "data_restore_rollback_retention_days": 30,
            "reason": "Stale update must not overwrite policy",
        },
    )
    assert stale.status_code == 409

    reconciled = client.post(
        "/api/organization/data-retention/cleanup",
        json={
            "expected_version": policy["settings_version"],
            "reason": "Recover interrupted file cleanup boundary",
        },
    )
    assert reconciled.status_code == 200, reconciled.text
    assert reconciled.json()["recovered_interrupted_file_cleanups"] == 1
    restored = rollback_root / "organization-1" / f"restore-{active_id}"
    assert (restored / "active.bin").read_bytes() == b"active"
    with client.app.state.testing_session_local() as db:
        row = db.get(OrganizationDataRestore, active_id)
        assert row.rollback_payload_json is not None
        actions = set(db.scalars(select(AuditLog.action)).all())
        assert "organization_data_retention_policy_updated" in actions
        assert "organization_data_retention_cleanup" in actions


def test_retention_cleanup_requires_administrator_and_current_password(client):
    created = client.post(
        "/api/users",
        json={
            "name": "Retention Warehouse",
            "email": "retention-warehouse@example.com",
            "role": "warehouse",
            "password": "retention-warehouse-password",
        },
    )
    assert created.status_code == 200
    original_rbac = settings.rbac_enforce
    original_legacy = settings.legacy_header_auth
    try:
        settings.rbac_enforce = True
        settings.legacy_header_auth = True
        denied = client.get(
            "/api/organization/data-retention",
            headers={"X-User-Id": str(created.json()["id"])},
        )
        assert denied.status_code == 403

        settings.rbac_enforce = False
        administrator = User(
            organization_id=1,
            name="Retention Administrator",
            email="retention-admin@example.com",
            role=UserRole.ADMIN,
            password_hash=hash_password("retention-administrator-password"),
        )
        with client.app.state.testing_session_local() as db:
            db.add(administrator)
            db.commit()
        settings.rbac_enforce = True
        settings.legacy_header_auth = False
        login = client.post(
            "/api/auth/login",
            data={
                "username": "retention-admin@example.com",
                "password": "retention-administrator-password",
            },
        )
        headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
        overview = client.get(
            "/api/organization/data-retention", headers=headers
        ).json()
        wrong = client.post(
            "/api/organization/data-retention/cleanup",
            headers=headers,
            json={
                "expected_version": overview["settings_version"],
                "reason": "Authenticated cleanup attempt",
                "account_password": "wrong-password-value",
            },
        )
        assert wrong.status_code == 401
        allowed = client.post(
            "/api/organization/data-retention/cleanup",
            headers=headers,
            json={
                "expected_version": overview["settings_version"],
                "reason": "Authenticated cleanup attempt",
                "account_password": "retention-administrator-password",
            },
        )
        assert allowed.status_code == 200
    finally:
        settings.rbac_enforce = original_rbac
        settings.legacy_header_auth = original_legacy
