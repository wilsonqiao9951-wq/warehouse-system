from io import BytesIO
import json
import zipfile

from sqlalchemy import select, update

from app.core.config import settings
from app.core.security import hash_password
from app.services import data_restores
from app.models import (
    AuditLog,
    Customer,
    Equipment,
    Organization,
    OrganizationDataRestore,
    Part,
    User,
    UserRole,
)


def _backup(client) -> bytes:
    response = client.post(
        "/api/organization/data-exports",
        json={"include_files": False},
    )
    assert response.status_code == 200, response.text
    return response.content


def _rehearse(client, archive: bytes, headers: dict[str, str] | None = None, password: str | None = None):
    data = {} if password is None else {"account_password": password}
    return client.post(
        "/api/organization/data-restores/rehearsals",
        headers=headers or {},
        data=data,
        files={"file": ("backup.zip", archive, "application/zip")},
    )


def _apply(client, restore_id: int, version: int, archive: bytes, password: str | None = None):
    data = {"expected_version": str(version)}
    if password is not None:
        data["account_password"] = password
    return client.post(
        f"/api/organization/data-restores/{restore_id}/apply",
        data=data,
        files={"file": ("backup.zip", archive, "application/zip")},
    )


def test_controlled_restore_rehearsal_apply_and_rollback(client):
    part = client.post(
        "/api/parts",
        json={"part_number": "RESTORE-100", "name": "Known good filter", "default_cost": 12.5},
    )
    assert part.status_code == 200, part.text
    part_id = part.json()["id"]
    archive = _backup(client)

    with client.app.state.testing_session_local() as db:
        row = db.get(Part, part_id)
        row.name = "Accidental overwrite"
        row.default_cost = 99.0
        db.commit()

    rehearsal = _rehearse(client, archive)
    assert rehearsal.status_code == 200, rehearsal.text
    result = rehearsal.json()
    assert result["status"] == "validated"
    assert result["matched_export_id"] is not None
    assert result["update_count"] == 1
    assert result["conflict_count"] == 0
    assert result["table_summary"]["parts"]["updates"] == 1
    assert any("protected records" in message for message in result["validation_messages"])

    approved = client.post(
        f"/api/organization/data-restores/{result['id']}/decision",
        json={
            "expected_version": result["version"],
            "decision": "approve",
            "note": "Validated customer recovery request",
        },
    )
    assert approved.status_code == 200, approved.text
    assert approved.json()["status"] == "approved"

    applied = _apply(
        client,
        result["id"],
        approved.json()["version"],
        archive,
    )
    assert applied.status_code == 200, applied.text
    applied_result = applied.json()
    assert applied_result["status"] == "applied"
    assert applied_result["rollback_size_bytes"] > 0
    with client.app.state.testing_session_local() as db:
        restored = db.get(Part, part_id)
        assert restored.name == "Known good filter"
        assert restored.default_cost == 12.5

    with client.app.state.testing_session_local() as db:
        db.get(Part, part_id).name = "Edited after restore"
        db.commit()
    drift_blocked = client.post(
        f"/api/organization/data-restores/{result['id']}/rollback",
        json={"expected_version": applied_result["version"]},
    )
    assert drift_blocked.status_code == 409
    assert "changed after restore review" in drift_blocked.json()["detail"]
    with client.app.state.testing_session_local() as db:
        db.get(Part, part_id).name = "Known good filter"
        db.commit()

    rolled_back = client.post(
        f"/api/organization/data-restores/{result['id']}/rollback",
        json={"expected_version": applied_result["version"]},
    )
    assert rolled_back.status_code == 200, rolled_back.text
    assert rolled_back.json()["status"] == "rolled_back"
    with client.app.state.testing_session_local() as db:
        original_live = db.get(Part, part_id)
        assert original_live.name == "Accidental overwrite"
        assert original_live.default_cost == 99.0
        actions = set(
            db.scalars(
                select(AuditLog.action).where(
                    AuditLog.entity_type == "organization_data_restore"
                )
            ).all()
        )
        assert actions == {
            "organization_data_restore_validated",
            "organization_data_restore_approved",
            "organization_data_restore_applied",
            "organization_data_restore_rolled_back",
        }


def test_restore_rejects_tampered_or_unmanifested_archive(client):
    archive = _backup(client)
    rebuilt = BytesIO()
    with zipfile.ZipFile(BytesIO(archive)) as source, zipfile.ZipFile(rebuilt, "w") as target:
        for info in source.infolist():
            target.writestr(info.filename, source.read(info.filename))
        target.writestr("../outside.txt", b"not allowed")

    response = _rehearse(client, rebuilt.getvalue())
    assert response.status_code == 400
    assert "unsafe path" in response.json()["detail"]
    with client.app.state.testing_session_local() as db:
        assert db.scalar(select(OrganizationDataRestore)) is None

    checksum_tampered = BytesIO()
    with zipfile.ZipFile(BytesIO(archive)) as source, zipfile.ZipFile(checksum_tampered, "w") as target:
        for info in source.infolist():
            content = source.read(info.filename)
            if info.filename == "data/parts.jsonl":
                content += b"{}\n"
            target.writestr(info.filename, content)
    checksum_response = _rehearse(client, checksum_tampered.getvalue())
    assert checksum_response.status_code == 400
    assert "does not match its manifest" in checksum_response.json()["detail"]


def test_restore_rehydrates_deleted_parent_and_child_then_rolls_back(client):
    with client.app.state.testing_session_local() as db:
        customer = Customer(
            organization_id=1,
            name="Recovery Customer",
            account_number="RECOVERY-100",
        )
        db.add(customer)
        db.flush()
        equipment = Equipment(
            organization_id=1,
            customer_id=customer.id,
            asset_tag="RECOVERY-EQ-100",
            model="ACME-9000",
        )
        db.add(equipment)
        db.commit()
        customer_id = customer.id
        equipment_id = equipment.id

    archive = _backup(client)
    with client.app.state.testing_session_local() as db:
        db.delete(db.get(Equipment, equipment_id))
        db.delete(db.get(Customer, customer_id))
        db.commit()

    rehearsal = _rehearse(client, archive)
    assert rehearsal.status_code == 200, rehearsal.text
    result = rehearsal.json()
    assert result["create_count"] == 2
    assert result["update_count"] == 0
    assert result["conflict_count"] == 0
    assert result["table_summary"]["customers"]["creates"] == 1
    assert result["table_summary"]["equipment"]["creates"] == 1

    approved = client.post(
        f"/api/organization/data-restores/{result['id']}/decision",
        json={
            "expected_version": result["version"],
            "decision": "approve",
            "note": "Rehydrate verified customer equipment",
        },
    )
    assert approved.status_code == 200, approved.text
    applied = _apply(
        client,
        result["id"],
        approved.json()["version"],
        archive,
    )
    assert applied.status_code == 200, applied.text
    assert applied.json()["create_count"] == 2
    with client.app.state.testing_session_local() as db:
        restored_customer = db.get(Customer, customer_id)
        restored_equipment = db.get(Equipment, equipment_id)
        assert restored_customer.name == "Recovery Customer"
        assert restored_equipment.customer_id == customer_id
        restored_updated_at = restored_equipment.updated_at

        restored_equipment.model = "Edited after rehydration"
        db.commit()

    drift_blocked = client.post(
        f"/api/organization/data-restores/{result['id']}/rollback",
        json={"expected_version": applied.json()["version"]},
    )
    assert drift_blocked.status_code == 409
    assert "changed after restore review" in drift_blocked.json()["detail"]

    with client.app.state.testing_session_local() as db:
        db.execute(
            update(Equipment)
            .where(Equipment.id == equipment_id)
            .values(model="ACME-9000", updated_at=restored_updated_at)
        )
        db.commit()

    rolled_back = client.post(
        f"/api/organization/data-restores/{result['id']}/rollback",
        json={"expected_version": applied.json()["version"]},
    )
    assert rolled_back.status_code == 200, rolled_back.text
    with client.app.state.testing_session_local() as db:
        assert db.get(Equipment, equipment_id) is None
        assert db.get(Customer, customer_id) is None


def test_restore_accepts_previous_portable_schema_revision(client, monkeypatch):
    archive = _backup(client)
    compatible = BytesIO()
    with zipfile.ZipFile(BytesIO(archive)) as source, zipfile.ZipFile(compatible, "w") as target:
        for info in source.infolist():
            content = source.read(info.filename)
            if info.filename == "manifest.json":
                manifest = json.loads(content)
                manifest["schema_revision"] = "20260806_0036"
                content = (json.dumps(manifest, sort_keys=True) + "\n").encode("utf-8")
            target.writestr(info.filename, content)
    monkeypatch.setattr(data_restores, "_schema_revision", lambda _db: "20260806_0037")
    response = _rehearse(client, compatible.getvalue())
    assert response.status_code == 200, response.text
    assert response.json()["source_schema_revision"] == "20260806_0036"


def test_restore_conflicts_block_approval_and_live_drift_blocks_apply(client):
    first = client.post(
        "/api/parts",
        json={"part_number": "RESTORE-200", "name": "Original first"},
    ).json()
    second = client.post(
        "/api/parts",
        json={"part_number": "RESTORE-201", "name": "Original second"},
    ).json()
    archive = _backup(client)
    with client.app.state.testing_session_local() as db:
        db.delete(db.get(Part, first["id"]))
        db.get(Part, second["id"]).name = "Changed before rehearsal"
        other = Organization(name="Conflicting Tenant", slug="conflicting-tenant")
        db.add(other)
        db.flush()
        db.add(
            Part(
                id=first["id"],
                organization_id=other.id,
                part_number="OTHER-RESTORE-200",
                name="Other tenant row using deleted id",
            )
        )
        db.commit()

    conflicted = _rehearse(client, archive)
    assert conflicted.status_code == 200, conflicted.text
    conflict_result = conflicted.json()
    assert conflict_result["conflict_count"] == 1
    blocked = client.post(
        f"/api/organization/data-restores/{conflict_result['id']}/decision",
        json={
            "expected_version": conflict_result["version"],
            "decision": "approve",
            "note": "Attempt conflict approval",
        },
    )
    assert blocked.status_code == 409

    with client.app.state.testing_session_local() as db:
        other_part = db.execute(
            select(Part).where(Part.id == first["id"])
        ).scalar_one()
        db.delete(other_part)
        db.flush()
        unique_collision = Part(
            id=first["id"] + 1000,
            organization_id=1,
            part_number="RESTORE-200",
            name="Current row using archived unique key",
        )
        db.add(unique_collision)
        db.commit()

    unique_conflicted = _rehearse(client, archive)
    assert unique_conflicted.status_code == 200, unique_conflicted.text
    assert unique_conflicted.json()["conflict_count"] == 1
    assert any(
        "unique key" in message
        for message in unique_conflicted.json()["validation_messages"]
    )

    with client.app.state.testing_session_local() as db:
        db.delete(db.get(Part, first["id"] + 1000))
        db.flush()
        db.add(
            Part(
                id=first["id"],
                organization_id=1,
                part_number="RESTORE-200",
                name="Original first",
            )
        )
        db.commit()
    clean = _rehearse(client, archive)
    assert clean.status_code == 200, clean.text
    clean_result = clean.json()
    approved = client.post(
        f"/api/organization/data-restores/{clean_result['id']}/decision",
        json={
            "expected_version": clean_result["version"],
            "decision": "approve",
            "note": "Approve stable rehearsal",
        },
    )
    assert approved.status_code == 200, approved.text
    with client.app.state.testing_session_local() as db:
        db.get(Part, second["id"]).name = "Changed after approval"
        db.commit()
    stale = _apply(
        client,
        clean_result["id"],
        approved.json()["version"],
        archive,
    )
    assert stale.status_code == 409
    assert "changed after approval" in stale.json()["detail"]


def test_restore_requires_admin_and_current_password(client):
    original_rbac = settings.rbac_enforce
    original_legacy = settings.legacy_header_auth
    try:
        settings.rbac_enforce = False
        admin = client.post(
            "/api/users",
            json={
                "name": "Restore Admin",
                "email": "restore-admin@example.com",
                "role": "admin",
                "password": "correct-restore-password",
            },
        ).json()
        manager = client.post(
            "/api/users",
            json={
                "name": "Restore Manager",
                "email": "restore-manager@example.com",
                "role": "manager",
                "password": "manager-restore-password",
            },
        ).json()
        archive = _backup(client)
        with client.app.state.testing_session_local() as db:
            other_org = Organization(name="Other Restore Tenant", slug="other-restore")
            db.add(other_org)
            db.flush()
            other_admin = User(
                organization_id=other_org.id,
                name="Other Restore Admin",
                email="other-restore-admin@example.com",
                role=UserRole.ADMIN,
                password_hash=hash_password("other-restore-password"),
            )
            db.add(other_admin)
            db.commit()
        settings.rbac_enforce = True
        settings.legacy_header_auth = False

        def login(email: str, password: str) -> str:
            response = client.post(
                "/api/auth/login",
                data={"username": email, "password": password},
            )
            assert response.status_code == 200, response.text
            return response.json()["access_token"]

        admin_headers = {
            "Authorization": f"Bearer {login(admin['email'], 'correct-restore-password')}"
        }
        manager_headers = {
            "Authorization": f"Bearer {login(manager['email'], 'manager-restore-password')}"
        }
        other_headers = {
            "Authorization": f"Bearer {login('other-restore-admin@example.com', 'other-restore-password')}"
        }
        assert _rehearse(
            client,
            archive,
            manager_headers,
            "manager-restore-password",
        ).status_code == 403
        assert _rehearse(
            client,
            archive,
            admin_headers,
            "incorrect-restore-password",
        ).status_code == 401
        admin_rehearsal = _rehearse(
            client,
            archive,
            admin_headers,
            "correct-restore-password",
        )
        assert admin_rehearsal.status_code == 200
        rejected = client.post(
            f"/api/organization/data-restores/{admin_rehearsal.json()['id']}/decision",
            headers=admin_headers,
            json={
                "expected_version": admin_rehearsal.json()["version"],
                "decision": "reject",
                "note": "No recovery is required",
                "account_password": "correct-restore-password",
            },
        )
        assert rejected.status_code == 200, rejected.text
        assert rejected.json()["rejected_by"] == admin["id"]
        assert rejected.json()["rejected_at"] is not None
        cross_tenant = _rehearse(
            client,
            archive,
            other_headers,
            "other-restore-password",
        )
        assert cross_tenant.status_code == 400
        assert "does not belong" in cross_tenant.json()["detail"]
        assert client.get(
            "/api/organization/data-restores",
            headers=other_headers,
        ).json() == []
        assert client.get(
            "/api/organization/data-restores",
            headers=manager_headers,
        ).status_code == 403
    finally:
        settings.rbac_enforce = original_rbac
        settings.legacy_header_auth = original_legacy
