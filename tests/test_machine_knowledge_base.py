from datetime import datetime, timedelta

from app.core.config import settings
from app.models import (
    AuditLog,
    MachineKnowledgeEntry,
    MachineKnowledgeProfile,
    Organization,
    Part,
    PartMachineAssociation,
    User,
    UserRole,
    WorkOrder,
)


def _headers(user: dict) -> dict[str, str]:
    return {"X-User-Id": str(user["id"])}


def _create_user(client, name: str, role: str) -> dict:
    response = client.post(
        "/api/users",
        json={
            "name": name,
            "email": f"{name}@example.com",
            "role": role,
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_machine_knowledge_publish_flow_and_field_evidence(client):
    manager = _create_user(client, "knowledge-manager", "manager")
    admin = _create_user(client, "knowledge-admin", "admin")
    engineer = _create_user(client, "knowledge-engineer", "engineer")
    warehouse = _create_user(client, "knowledge-warehouse", "warehouse")
    part = client.post(
        "/api/parts",
        json={
            "part_number": "KB-FILTER-01",
            "name": "Primary filter",
            "default_cost": 123.45,
            "supplier": "Private Supplier",
        },
    ).json()

    now = datetime.utcnow()
    with client.app.state.testing_session_local() as db:
        first = WorkOrder(
            organization_id=1,
            ticket_number="KB-EVIDENCE-1",
            machine_type="ACME-9000",
            status="completed",
            is_locked=True,
            completed_at=now - timedelta(days=2),
            first_time_fix=True,
            repair_duration_minutes=60,
        )
        second = WorkOrder(
            organization_id=1,
            ticket_number="KB-EVIDENCE-2",
            machine_type="acme-9000",
            status="completed",
            is_locked=True,
            completed_at=now - timedelta(days=1),
            first_time_fix=False,
            repair_duration_minutes=90,
        )
        db.add_all((first, second))
        db.flush()
        source_work_order_id = first.id
        db.add(
            PartMachineAssociation(
                organization_id=1,
                machine_model="ACME-9000",
                part_id=part["id"],
                recognition_source="verified_visual",
                confidence=0.99,
                confirmed_count=3,
            )
        )
        db.commit()

    original_rbac = settings.rbac_enforce
    original_legacy = settings.legacy_header_auth
    settings.rbac_enforce = True
    settings.legacy_header_auth = True
    try:
        created = client.post(
            "/api/machine-knowledge",
            headers=_headers(manager),
            json={
                "manufacturer": "ACME",
                "model": " ACME-9000 ",
                "equipment_type": "Cooling unit",
                "summary": "Field guide for the ACME 9000 platform.",
            },
        )
        assert created.status_code == 200, created.text
        profile = created.json()
        assert profile["model"] == "ACME-9000"
        assert profile["can_add_entry"] is True
        assert profile["evidence"]["completed_work_orders"] == 2
        assert profile["evidence"]["first_time_fix_rate"] == 0.5
        assert profile["evidence"]["average_repair_minutes"] == 75.0
        profile_id = profile["id"]

        draft = client.post(
            f"/api/machine-knowledge/{profile_id}/entries",
            headers=_headers(manager),
            json={
                "entry_type": "fault",
                "title": "Low airflow",
                "content": "Inspect the primary filter before opening the fan housing.",
                "fault_code": "AIR-01",
                "related_part_id": part["id"],
                "source_work_order_id": source_work_order_id,
            },
        )
        assert draft.status_code == 200, draft.text
        entry = draft.json()["entries"][0]
        assert entry["status"] == "draft"
        assert entry["can_edit"] is True
        assert entry["can_publish"] is False

        hidden = client.get(
            f"/api/machine-knowledge/{profile_id}",
            headers=_headers(engineer),
        )
        assert hidden.status_code == 404
        manager_cannot_publish = client.post(
            f"/api/machine-knowledge/entries/{entry['id']}/actions",
            headers=_headers(manager),
            json={"action": "publish", "expected_version": entry["version"]},
        )
        assert manager_cannot_publish.status_code == 403
        engineer_cannot_edit = client.post(
            f"/api/machine-knowledge/{profile_id}/entries",
            headers=_headers(engineer),
            json={
                "entry_type": "note",
                "title": "Unauthorized",
                "content": "Engineers cannot publish field guidance directly.",
            },
        )
        assert engineer_cannot_edit.status_code == 403

        published = client.post(
            f"/api/machine-knowledge/entries/{entry['id']}/actions",
            headers=_headers(admin),
            json={"action": "publish", "expected_version": entry["version"]},
        )
        assert published.status_code == 200, published.text
        entry = published.json()["entries"][0]
        assert entry["status"] == "published"
        assert entry["published_by"] == admin["id"]

        engineer_view = client.get(
            "/api/machine-knowledge?model=acme-9000",
            headers=_headers(engineer),
        )
        assert engineer_view.status_code == 200, engineer_view.text
        field_profile = engineer_view.json()[0]
        assert len(field_profile["entries"]) == 1
        assert field_profile["entries"][0]["can_edit"] is False
        assert field_profile["entries"][0]["related_part"]["part_number"] == "KB-FILTER-01"
        assert "default_cost" not in field_profile["entries"][0]["related_part"]
        assert "supplier" not in field_profile["related_parts"][0]

        warehouse_view = client.get(
            f"/api/machine-knowledge/{profile_id}",
            headers=_headers(warehouse),
        )
        assert warehouse_view.status_code == 200
        assert warehouse_view.json()["entries"][0]["status"] == "published"

        immutable = client.patch(
            f"/api/machine-knowledge/entries/{entry['id']}",
            headers=_headers(manager),
            json={
                "expected_version": entry["version"],
                "content": "Silent edits must not replace published guidance.",
            },
        )
        assert immutable.status_code == 409
        assert "immutable" in immutable.text

        archived = client.post(
            f"/api/machine-knowledge/entries/{entry['id']}/actions",
            headers=_headers(admin),
            json={"action": "archive", "expected_version": entry["version"]},
        )
        assert archived.status_code == 200
        assert archived.json()["entries"][0]["status"] == "archived"
        hidden_after_archive = client.get(
            f"/api/machine-knowledge/{profile_id}",
            headers=_headers(engineer),
        )
        assert hidden_after_archive.status_code == 404

        with client.app.state.testing_session_local() as db:
            actions = {
                row.action
                for row in db.query(AuditLog)
                .filter(
                    AuditLog.entity_type.in_(
                        {"machine_knowledge_profile", "machine_knowledge_entry"}
                    )
                )
                .all()
            }
            assert {
                "create_machine_knowledge_profile",
                "create_machine_knowledge_entry",
                "publish_machine_knowledge_entry",
                "archive_machine_knowledge_entry",
            }.issubset(actions)
    finally:
        settings.rbac_enforce = original_rbac
        settings.legacy_header_auth = original_legacy


def test_machine_knowledge_versions_duplicates_and_evidence_validation(client):
    admin = _create_user(client, "knowledge-version-admin", "admin")
    part = client.post(
        "/api/parts",
        json={"part_number": "KB-VERSION-PART", "name": "Version part"},
    ).json()
    with client.app.state.testing_session_local() as db:
        incomplete = WorkOrder(
            organization_id=1,
            ticket_number="KB-INCOMPLETE",
            machine_type="VERSION-MODEL",
            status="in_progress",
            is_locked=False,
        )
        wrong_model = WorkOrder(
            organization_id=1,
            ticket_number="KB-WRONG-MODEL",
            machine_type="OTHER-MODEL",
            status="completed",
            is_locked=True,
            completed_at=datetime.utcnow(),
        )
        db.add_all((incomplete, wrong_model))
        db.commit()
        incomplete_id = incomplete.id
        wrong_model_id = wrong_model.id

    original_rbac = settings.rbac_enforce
    original_legacy = settings.legacy_header_auth
    settings.rbac_enforce = True
    settings.legacy_header_auth = True
    try:
        created = client.post(
            "/api/machine-knowledge",
            headers=_headers(admin),
            json={"model": " Version-Model "},
        )
        assert created.status_code == 200, created.text
        profile = created.json()
        duplicate = client.post(
            "/api/machine-knowledge",
            headers=_headers(admin),
            json={"model": "version-model"},
        )
        assert duplicate.status_code == 409

        updated = client.patch(
            f"/api/machine-knowledge/{profile['id']}",
            headers=_headers(admin),
            json={
                "expected_version": profile["version"],
                "summary": "Versioned summary",
            },
        )
        assert updated.status_code == 200
        stale = client.patch(
            f"/api/machine-knowledge/{profile['id']}",
            headers=_headers(admin),
            json={
                "expected_version": profile["version"],
                "summary": "Stale overwrite",
            },
        )
        assert stale.status_code == 409

        invalid_media = client.post(
            f"/api/machine-knowledge/{profile['id']}/entries",
            headers=_headers(admin),
            json={
                "entry_type": "video",
                "title": "Unsafe media",
                "content": "The URL scheme is rejected.",
                "media_url": "javascript:alert(1)",
            },
        )
        assert invalid_media.status_code == 422
        missing_media = client.post(
            f"/api/machine-knowledge/{profile['id']}/entries",
            headers=_headers(admin),
            json={
                "entry_type": "photo",
                "title": "Missing photo",
                "content": "A photo entry requires a URL.",
            },
        )
        assert missing_media.status_code == 422
        incomplete_evidence = client.post(
            f"/api/machine-knowledge/{profile['id']}/entries",
            headers=_headers(admin),
            json={
                "entry_type": "note",
                "title": "Incomplete evidence",
                "content": "Cannot cite an unfinished job.",
                "source_work_order_id": incomplete_id,
            },
        )
        assert incomplete_evidence.status_code == 409
        wrong_evidence = client.post(
            f"/api/machine-knowledge/{profile['id']}/entries",
            headers=_headers(admin),
            json={
                "entry_type": "note",
                "title": "Wrong model",
                "content": "Cannot cite a different machine model.",
                "source_work_order_id": wrong_model_id,
                "related_part_id": part["id"],
            },
        )
        assert wrong_evidence.status_code == 409
    finally:
        settings.rbac_enforce = original_rbac
        settings.legacy_header_auth = original_legacy


def test_machine_knowledge_is_tenant_scoped(client):
    org_one_admin = _create_user(client, "knowledge-org-one", "admin")
    with client.app.state.testing_session_local() as db:
        other_org = Organization(name="Knowledge Tenant Two", slug="knowledge-tenant-two")
        db.add(other_org)
        db.flush()
        other_admin = User(
            organization_id=other_org.id,
            name="knowledge-org-two",
            email="knowledge-org-two@example.com",
            role=UserRole.ADMIN,
        )
        db.add(other_admin)
        db.flush()
        other_profile = MachineKnowledgeProfile(
            organization_id=other_org.id,
            model="PRIVATE-2000",
            model_key="private-2000",
            created_by=other_admin.id,
            updated_by=other_admin.id,
        )
        db.add(other_profile)
        db.flush()
        db.add(
            MachineKnowledgeEntry(
                organization_id=other_org.id,
                profile_id=other_profile.id,
                entry_type="caution",
                title="Private tenant warning",
                content="This must never appear in another organization.",
                status="published",
                created_by=other_admin.id,
                updated_by=other_admin.id,
                published_by=other_admin.id,
                published_at=datetime.utcnow(),
            )
        )
        db.commit()
        other_admin_id = other_admin.id
        other_profile_id = other_profile.id

    original_rbac = settings.rbac_enforce
    original_legacy = settings.legacy_header_auth
    settings.rbac_enforce = True
    settings.legacy_header_auth = True
    try:
        hidden_list = client.get(
            "/api/machine-knowledge?include_inactive=true",
            headers=_headers(org_one_admin),
        )
        assert hidden_list.status_code == 200
        assert hidden_list.json() == []
        hidden_detail = client.get(
            f"/api/machine-knowledge/{other_profile_id}",
            headers=_headers(org_one_admin),
        )
        assert hidden_detail.status_code == 404

        other_list = client.get(
            "/api/machine-knowledge",
            headers={"X-User-Id": str(other_admin_id)},
        )
        assert other_list.status_code == 200, other_list.text
        assert [row["model"] for row in other_list.json()] == ["PRIVATE-2000"]

        same_model_other_tenant = client.post(
            "/api/machine-knowledge",
            headers=_headers(org_one_admin),
            json={"model": "PRIVATE-2000"},
        )
        assert same_model_other_tenant.status_code == 200
    finally:
        settings.rbac_enforce = original_rbac
        settings.legacy_header_auth = original_legacy
