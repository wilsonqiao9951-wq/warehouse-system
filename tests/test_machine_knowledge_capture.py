from datetime import datetime
from pathlib import Path

from app.core.config import settings
from app.models import (
    AuditLog,
    MachineKnowledgeEntry,
    Organization,
    Part,
    User,
    UserRole,
    Warehouse,
    WorkOrder,
    WorkOrderPart,
)


PNG = b"\x89PNG\r\n\x1a\n" + b"machine-knowledge-photo"
WEBM = b"\x1aE\xdf\xa3" + b"machine-knowledge-video"


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


def _headers(user: dict | int) -> dict[str, str]:
    user_id = user if isinstance(user, int) else user["id"]
    return {"X-User-Id": str(user_id)}


def _enable_header_rbac():
    original = (settings.rbac_enforce, settings.legacy_header_auth)
    settings.rbac_enforce = True
    settings.legacy_header_auth = True
    return original


def _restore_rbac(original: tuple[bool, bool]) -> None:
    settings.rbac_enforce, settings.legacy_header_auth = original


def test_completed_work_order_generates_idempotent_review_drafts(client):
    manager = _create_user(client, "capture-manager", "manager")
    admin = _create_user(client, "capture-admin", "admin")
    engineer = _create_user(client, "capture-engineer", "engineer")
    warehouse = client.post(
        "/api/warehouses",
        json={"code": "CAPTURE", "name": "Capture Warehouse"},
    ).json()
    part = client.post(
        "/api/parts",
        json={"part_number": "CAP-RELAY", "name": "Control relay"},
    ).json()

    with client.app.state.testing_session_local() as db:
        work_order = WorkOrder(
            organization_id=1,
            ticket_number="CAPTURE-WO-1",
            machine_type="CAPTURE-9000",
            job_type="Electrical repair",
            problem_description="Compressor would not start.",
            fault_type="Control circuit failure",
            error_code="E-42",
            environment_info="High ambient temperature",
            repair_result="Replaced relay and verified three successful starts.",
            final_outcome="repaired",
            first_time_fix=True,
            is_rework=False,
            repair_duration_minutes=48,
            status="completed",
            is_locked=True,
            completed_at=datetime.utcnow(),
        )
        db.add(work_order)
        db.flush()
        db.add(
            WorkOrderPart(
                organization_id=1,
                work_order_id=work_order.id,
                part_id=part["id"],
                warehouse_id=warehouse["id"],
                quantity=2,
                unit_cost=50,
                total_cost=100,
            )
        )
        reference_work_order = WorkOrder(
            organization_id=1,
            ticket_number="CAPTURE-WO-2",
            machine_type="CAPTURE-9000",
            repair_result="Replaced relay during a return visit.",
            final_outcome="repaired",
            first_time_fix=False,
            is_rework=True,
            status="completed",
            is_locked=True,
            completed_at=datetime.utcnow(),
        )
        db.add(reference_work_order)
        db.flush()
        db.add(
            WorkOrderPart(
                organization_id=1,
                work_order_id=reference_work_order.id,
                part_id=part["id"],
                warehouse_id=warehouse["id"],
                quantity=1,
                unit_cost=50,
                total_cost=50,
            )
        )
        db.commit()
        work_order_id = work_order.id
        reference_work_order_id = reference_work_order.id

    original_rbac = _enable_header_rbac()
    try:
        profile_response = client.post(
            "/api/machine-knowledge",
            headers=_headers(manager),
            json={"model": "CAPTURE-9000", "manufacturer": "FieldCo"},
        )
        assert profile_response.status_code == 200, profile_response.text
        profile_id = profile_response.json()["id"]

        generated = client.post(
            f"/api/machine-knowledge/{profile_id}/drafts/from-work-order",
            headers=_headers(manager),
            json={"work_order_id": work_order_id},
        )
        assert generated.status_code == 200, generated.text
        body = generated.json()
        assert body["created_entries"] == 3
        assert body["skipped_entries"] == 0
        entries = body["profile"]["entries"]
        assert {entry["entry_type"] for entry in entries} == {
            "fault",
            "repair_step",
            "note",
        }
        part_entry = next(entry for entry in entries if entry["related_part"])
        assert part_entry["related_part"]["part_number"] == "CAP-RELAY"
        assert part_entry["related_part_role"] == "recommended"
        assert part_entry["source_work_order_id"] == work_order_id
        assert "successful first-time repair" in part_entry["content"]
        assert all(entry["status"] == "draft" for entry in entries)

        repeated = client.post(
            f"/api/machine-knowledge/{profile_id}/drafts/from-work-order",
            headers=_headers(manager),
            json={"work_order_id": work_order_id},
        )
        assert repeated.status_code == 200, repeated.text
        assert repeated.json()["created_entries"] == 0
        assert repeated.json()["skipped_entries"] == 3
        assert len(repeated.json()["profile"]["entries"]) == 3

        reference = client.post(
            f"/api/machine-knowledge/{profile_id}/drafts/from-work-order",
            headers=_headers(manager),
            json={"work_order_id": reference_work_order_id},
        )
        assert reference.status_code == 200, reference.text
        assert reference.json()["created_entries"] == 2
        reference_part = next(
            entry
            for entry in reference.json()["profile"]["entries"]
            if entry["source_work_order_id"] == reference_work_order_id
            and entry["related_part"]
        )
        assert reference_part["related_part_role"] == "reference"
        assert "reference evidence only" in reference_part["content"]

        hidden_from_engineer = client.get(
            f"/api/machine-knowledge/{profile_id}",
            headers=_headers(engineer),
        )
        assert hidden_from_engineer.status_code == 404

        for entry in entries:
            published = client.post(
                f"/api/machine-knowledge/entries/{entry['id']}/actions",
                headers=_headers(admin),
                json={"action": "publish", "expected_version": entry["version"]},
            )
            assert published.status_code == 200, published.text

        field_view = client.get(
            f"/api/machine-knowledge/{profile_id}",
            headers=_headers(engineer),
        )
        assert field_view.status_code == 200, field_view.text
        assert len(field_view.json()["entries"]) == 3
        safe_part = next(
            entry["related_part"]
            for entry in field_view.json()["entries"]
            if entry["related_part"]
        )
        assert "default_cost" not in safe_part

        with client.app.state.testing_session_local() as db:
            generated_entries = (
                db.query(MachineKnowledgeEntry)
                .filter(MachineKnowledgeEntry.source_work_order_id == work_order_id)
                .all()
            )
            assert len(generated_entries) == 3
            assert len({entry.origin_key for entry in generated_entries}) == 3
            audit = (
                db.query(AuditLog)
                .filter(AuditLog.action == "generate_machine_knowledge_drafts")
                .all()
            )
            assert len(audit) == 3
    finally:
        _restore_rbac(original_rbac)


def test_knowledge_part_roles_alternatives_and_installation_location(client):
    admin = _create_user(client, "part-link-admin", "admin")
    engineer = _create_user(client, "part-link-engineer", "engineer")
    primary = client.post(
        "/api/parts",
        json={"part_number": "PRIMARY-BOARD", "name": "Primary control board"},
    ).json()
    alternative = client.post(
        "/api/parts",
        json={"part_number": "ALT-BOARD", "name": "Alternative control board"},
    ).json()
    with client.app.state.testing_session_local() as db:
        other_org = Organization(name="Private Parts", slug="private-parts")
        db.add(other_org)
        db.flush()
        private_part = Part(
            organization_id=other_org.id,
            part_number="PRIVATE-ALT",
            name="Private tenant alternative",
        )
        db.add(private_part)
        db.commit()
        private_part_id = private_part.id

    original_rbac = _enable_header_rbac()
    try:
        profile = client.post(
            "/api/machine-knowledge",
            headers=_headers(admin),
            json={"model": "ALT-MACHINE"},
        ).json()
        valid = client.post(
            f"/api/machine-knowledge/{profile['id']}/entries",
            headers=_headers(admin),
            json={
                "entry_type": "note",
                "title": "Approved substitute board",
                "content": "Move the configuration jumper before installation.",
                "related_part_id": alternative["id"],
                "related_part_role": "alternative",
                "alternative_for_part_id": primary["id"],
                "installation_location": "Upper electrical cabinet, slot J4",
            },
        )
        assert valid.status_code == 200, valid.text
        entry = valid.json()["entries"][0]
        assert entry["related_part_role"] == "alternative"
        assert entry["alternative_for_part"]["part_number"] == "PRIMARY-BOARD"
        assert entry["installation_location"] == "Upper electrical cabinet, slot J4"

        same_part = client.post(
            f"/api/machine-knowledge/{profile['id']}/entries",
            headers=_headers(admin),
            json={
                "entry_type": "note",
                "title": "Invalid same part",
                "content": "The alternative must be a different part.",
                "related_part_id": primary["id"],
                "related_part_role": "alternative",
                "alternative_for_part_id": primary["id"],
            },
        )
        assert same_part.status_code == 422
        missing_primary = client.post(
            f"/api/machine-knowledge/{profile['id']}/entries",
            headers=_headers(admin),
            json={
                "entry_type": "note",
                "title": "Missing primary",
                "content": "An alternative must identify what it replaces.",
                "related_part_id": alternative["id"],
                "related_part_role": "alternative",
            },
        )
        assert missing_primary.status_code == 422
        cross_tenant = client.post(
            f"/api/machine-knowledge/{profile['id']}/entries",
            headers=_headers(admin),
            json={
                "entry_type": "note",
                "title": "Cross tenant",
                "content": "Private parts cannot be linked.",
                "related_part_id": private_part_id,
                "related_part_role": "recommended",
            },
        )
        assert cross_tenant.status_code == 400

        published = client.post(
            f"/api/machine-knowledge/entries/{entry['id']}/actions",
            headers=_headers(admin),
            json={"action": "publish", "expected_version": entry["version"]},
        )
        assert published.status_code == 200
        field_view = client.get(
            f"/api/machine-knowledge/{profile['id']}",
            headers=_headers(engineer),
        )
        assert field_view.status_code == 200
        field_entry = field_view.json()["entries"][0]
        assert field_entry["related_part"]["part_number"] == "ALT-BOARD"
        assert field_entry["alternative_for_part"]["part_number"] == "PRIMARY-BOARD"
        assert "default_cost" not in field_entry["alternative_for_part"]
    finally:
        _restore_rbac(original_rbac)


def test_knowledge_media_is_private_until_published(client):
    manager = _create_user(client, "media-manager", "manager")
    admin = _create_user(client, "media-admin", "admin")
    engineer = _create_user(client, "media-engineer", "engineer")
    original_rbac = _enable_header_rbac()
    stored_paths: list[Path] = []
    try:
        profile = client.post(
            "/api/machine-knowledge",
            headers=_headers(manager),
            json={"model": "MEDIA-MACHINE"},
        ).json()
        uploaded = client.post(
            f"/api/machine-knowledge/{profile['id']}/media",
            headers=_headers(manager),
            data={
                "title": "Control cabinet photo",
                "description": "Connector positions before replacement.",
            },
            files={"file": ("cabinet.png", PNG, "image/png")},
        )
        assert uploaded.status_code == 200, uploaded.text
        photo_entry = uploaded.json()["entries"][0]
        assert photo_entry["entry_type"] == "photo"
        assert photo_entry["status"] == "draft"
        assert photo_entry["media_mime_type"] == "image/png"
        assert photo_entry["media_size_bytes"] == len(PNG)
        assert photo_entry["media_url"] == (
            f"/api/machine-knowledge/media/{photo_entry['id']}"
        )

        manager_preview = client.get(
            f"/api/machine-knowledge/media/{photo_entry['id']}",
            headers=_headers(manager),
        )
        assert manager_preview.status_code == 200
        assert manager_preview.content == PNG
        assert manager_preview.headers["content-type"].startswith("image/png")
        hidden_preview = client.get(
            f"/api/machine-knowledge/media/{photo_entry['id']}",
            headers=_headers(engineer),
        )
        assert hidden_preview.status_code == 404
        anonymous = client.get(
            f"/api/machine-knowledge/media/{photo_entry['id']}",
        )
        assert anonymous.status_code == 401

        edited = client.patch(
            f"/api/machine-knowledge/entries/{photo_entry['id']}",
            headers=_headers(manager),
            json={
                "expected_version": photo_entry["version"],
                "title": "Control cabinet photo with connector labels",
            },
        )
        assert edited.status_code == 200, edited.text
        photo_entry = next(
            entry
            for entry in edited.json()["entries"]
            if entry["id"] == photo_entry["id"]
        )
        assert photo_entry["media_url"].startswith("/api/machine-knowledge/media/")
        replace_protected_url = client.patch(
            f"/api/machine-knowledge/entries/{photo_entry['id']}",
            headers=_headers(manager),
            json={
                "expected_version": photo_entry["version"],
                "media_url": "https://example.com/replacement.png",
            },
        )
        assert replace_protected_url.status_code == 409

        video = client.post(
            f"/api/machine-knowledge/{profile['id']}/media",
            headers=_headers(manager),
            data={
                "title": "Access panel video",
                "description": "Short removal sequence.",
            },
            files={"file": ("panel.webm", WEBM, "video/webm")},
        )
        assert video.status_code == 200, video.text
        video_entry = next(
            entry for entry in video.json()["entries"] if entry["entry_type"] == "video"
        )
        assert video_entry["media_mime_type"] == "video/webm"

        invalid = client.post(
            f"/api/machine-knowledge/{profile['id']}/media",
            headers=_headers(manager),
            data={"title": "Invalid", "description": "Invalid file header."},
            files={"file": ("fake.mp4", b"not-a-video", "video/mp4")},
        )
        assert invalid.status_code == 400

        old_limit = settings.max_knowledge_media_upload_bytes
        settings.max_knowledge_media_upload_bytes = 8
        try:
            oversized = client.post(
                f"/api/machine-knowledge/{profile['id']}/media",
                headers=_headers(manager),
                data={"title": "Too large", "description": "Limit enforcement."},
                files={"file": ("large.png", PNG, "image/png")},
            )
            assert oversized.status_code == 413
        finally:
            settings.max_knowledge_media_upload_bytes = old_limit

        published = client.post(
            f"/api/machine-knowledge/entries/{photo_entry['id']}/actions",
            headers=_headers(admin),
            json={"action": "publish", "expected_version": photo_entry["version"]},
        )
        assert published.status_code == 200, published.text
        engineer_media = client.get(
            f"/api/machine-knowledge/media/{photo_entry['id']}",
            headers=_headers(engineer),
        )
        assert engineer_media.status_code == 200
        assert engineer_media.content == PNG

        with client.app.state.testing_session_local() as db:
            entries = (
                db.query(MachineKnowledgeEntry)
                .filter(MachineKnowledgeEntry.profile_id == profile["id"])
                .all()
            )
            stored_paths = [
                Path("private_uploads") / entry.media_storage_key
                for entry in entries
                if entry.media_storage_key
            ]
            assert all(path.is_file() for path in stored_paths)
    finally:
        _restore_rbac(original_rbac)
        for path in stored_paths:
            path.unlink(missing_ok=True)
