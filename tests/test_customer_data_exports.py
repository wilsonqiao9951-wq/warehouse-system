from hashlib import sha256
from io import BytesIO
import json
import zipfile

from sqlalchemy import select

from app.core.config import settings
from app.models import (
    AuditLog,
    MachineKnowledgeEntry,
    MachineKnowledgeProfile,
    Organization,
    OrganizationDataExport,
    Part,
    WorkOrder,
)


def _jsonl(archive: zipfile.ZipFile, path: str) -> list[dict]:
    return [
        json.loads(line)
        for line in archive.read(path).decode("utf-8").splitlines()
        if line
    ]


def test_customer_data_export_is_tenant_scoped_redacted_and_checksummed(
    client,
    monkeypatch,
    tmp_path,
):
    public_root = tmp_path / "uploads"
    evidence_file = public_root / "part-images" / "filter.png"
    evidence_file.parent.mkdir(parents=True)
    evidence_file.write_bytes(b"verified-field-evidence")
    form_file = public_root / "form-photos" / "inspection.png"
    form_file.parent.mkdir(parents=True)
    form_file.write_bytes(b"configured-form-evidence")
    private_root = tmp_path / "private_uploads"
    knowledge_file = private_root / "machine-knowledge" / "1" / "guide.png"
    knowledge_file.parent.mkdir(parents=True)
    knowledge_file.write_bytes(b"private-knowledge-evidence")
    monkeypatch.setattr(settings, "data_export_public_files_root", str(public_root))
    monkeypatch.setattr(
        settings,
        "data_export_private_files_root",
        str(private_root),
    )

    created_user = client.post(
        "/api/users",
        json={
            "name": "Export Administrator",
            "email": "backup-admin@example.com",
            "role": "admin",
            "password": "portable-backup-password",
        },
    )
    assert created_user.status_code == 200, created_user.text
    with client.app.state.testing_session_local() as db:
        second = Organization(name="Other Customer", slug="other-customer")
        db.add(second)
        db.flush()
        profile = MachineKnowledgeProfile(
            organization_id=1,
            model="ACME-9000",
            model_key="acme-9000",
        )
        db.add(profile)
        db.flush()
        db.add_all(
            [
                Part(
                    organization_id=1,
                    part_number="VISIBLE-100",
                    name="Visible filter",
                    image_url="/uploads/part-images/filter.png",
                ),
                Part(
                    organization_id=1,
                    part_number="MISSING-200",
                    name="Missing evidence reference",
                    image_url="/uploads/part-images/missing.png",
                ),
                Part(
                    organization_id=second.id,
                    part_number="HIDDEN-900",
                    name="Other customer secret part",
                ),
                WorkOrder(
                    organization_id=1,
                    ticket_number="BACKUP-FORM-1",
                    form_data_json=json.dumps(
                        {"inspection_photo": "/uploads/form-photos/inspection.png"}
                    ),
                ),
                MachineKnowledgeEntry(
                    organization_id=1,
                    profile_id=profile.id,
                    entry_type="photo",
                    title="Control board location",
                    content="Verified field guide",
                    media_storage_key="machine-knowledge/1/guide.png",
                    media_mime_type="image/png",
                    media_size_bytes=len(b"private-knowledge-evidence"),
                ),
            ]
        )
        db.commit()

    response = client.post(
        "/api/organization/data-exports",
        json={"include_files": True},
    )
    assert response.status_code == 200, response.text
    assert response.headers["content-type"] == "application/zip"
    assert "openpartsflow-backup-test-" in response.headers["content-disposition"]
    assert response.headers["x-openpartsflow-sha256"] == sha256(response.content).hexdigest()

    with zipfile.ZipFile(BytesIO(response.content)) as archive:
        manifest = json.loads(archive.read("manifest.json"))
        parts = _jsonl(archive, "data/parts.jsonl")
        users = _jsonl(archive, "data/users.jsonl")
        organizations = _jsonl(archive, "data/organizations.jsonl")
        assert manifest["format_version"] == "opf-portable-v1"
        assert manifest["organization"]["id"] == 1
        assert manifest["file_count"] == 3
        assert manifest["missing_file_count"] == 1
        assert manifest["security"]["redacted_columns"]["users"] == [
            "mfa_enrollment_expires_at",
            "mfa_last_used_step",
            "mfa_recovery_codes_json",
            "mfa_secret_encrypted",
            "password_hash",
        ]
        assert {row["part_number"] for row in parts} == {"VISIBLE-100", "MISSING-200"}
        assert organizations == [
            next(row for row in organizations if row["id"] == 1)
        ]
        assert all(
            not {
                "password_hash",
                "mfa_secret_encrypted",
                "mfa_recovery_codes_json",
                "mfa_last_used_step",
                "mfa_enrollment_expires_at",
            }.intersection(row)
            for row in users
        )
        assert "files/public/part-images/filter.png" in archive.namelist()
        assert archive.read("files/public/part-images/filter.png") == b"verified-field-evidence"
        assert archive.read("files/public/form-photos/inspection.png") == b"configured-form-evidence"
        assert archive.read("files/private/machine-knowledge/1/guide.png") == b"private-knowledge-evidence"
        assert manifest["missing_files"] == ["/uploads/part-images/missing.png"]

    listed = client.get("/api/organization/data-exports")
    assert listed.status_code == 200, listed.text
    evidence = listed.json()
    assert len(evidence) == 1
    assert evidence[0]["sha256"] == response.headers["x-openpartsflow-sha256"]
    assert evidence[0]["file_count"] == 3
    assert evidence[0]["missing_file_count"] == 1
    assert evidence[0]["table_counts"]["parts"] == 2

    with client.app.state.testing_session_local() as db:
        stored = db.scalar(select(OrganizationDataExport))
        audit = db.scalar(
            select(AuditLog).where(
                AuditLog.action == "organization_data_export_generated"
            )
        )
        assert stored is not None
        assert audit is not None
        assert stored.sha256 == sha256(response.content).hexdigest()
        assert "account_password" not in (audit.metadata_json or "")
        assert "portable-backup-password" not in (audit.metadata_json or "")


def test_customer_data_export_requires_admin_and_password_reauthentication(client):
    original_rbac = settings.rbac_enforce
    original_legacy = settings.legacy_header_auth
    try:
        settings.rbac_enforce = False
        admin = client.post(
            "/api/users",
            json={
                "name": "Backup Admin",
                "email": "backup-auth-admin@example.com",
                "role": "admin",
                "password": "correct-backup-password",
            },
        ).json()
        manager = client.post(
            "/api/users",
            json={
                "name": "Backup Manager",
                "email": "backup-manager@example.com",
                "role": "manager",
                "password": "manager-backup-password",
            },
        ).json()
        settings.rbac_enforce = True
        settings.legacy_header_auth = False

        def login(email: str, password: str) -> str:
            response = client.post(
                "/api/auth/login",
                data={"username": email, "password": password},
            )
            assert response.status_code == 200, response.text
            return response.json()["access_token"]

        admin_token = login(admin["email"], "correct-backup-password")
        manager_token = login(manager["email"], "manager-backup-password")
        manager_headers = {"Authorization": f"Bearer {manager_token}"}
        admin_headers = {"Authorization": f"Bearer {admin_token}"}

        assert client.get(
            "/api/organization/data-exports",
            headers=manager_headers,
        ).status_code == 403
        assert client.post(
            "/api/organization/data-exports",
            headers=manager_headers,
            json={"account_password": "manager-backup-password"},
        ).status_code == 403
        wrong_password = client.post(
            "/api/organization/data-exports",
            headers=admin_headers,
            json={"account_password": "incorrect-backup-password"},
        )
        assert wrong_password.status_code == 401
        assert client.get(
            "/api/organization/data-exports",
            headers=admin_headers,
        ).status_code == 200
    finally:
        settings.rbac_enforce = original_rbac
        settings.legacy_header_auth = original_legacy


def test_customer_data_export_size_limit_fails_without_evidence(client, monkeypatch):
    monkeypatch.setattr(settings, "max_data_export_bytes", 1)
    response = client.post(
        "/api/organization/data-exports",
        json={"include_files": False},
    )
    assert response.status_code == 413
    with client.app.state.testing_session_local() as db:
        assert db.scalar(select(OrganizationDataExport)) is None
        assert db.scalar(
            select(AuditLog).where(
                AuditLog.action == "organization_data_export_generated"
            )
        ) is None
