from pathlib import Path

from app.core.config import settings
from app.models import (
    AuditLog,
    InventoryTransaction,
    Organization,
    Part,
    PartMachineAssociation,
    PartRecognitionCandidate,
    PartRecognitionObservation,
    Warehouse,
)


PNG = b"\x89PNG\r\n\x1a\n" + b"controlled-visual-candidate"


def _stored_image_path(client, observation_id: int) -> Path:
    with client.app.state.testing_session_local() as db:
        reference = db.get(PartRecognitionObservation, observation_id).image_url
    if reference.startswith("private:"):
        return Path(settings.data_export_private_files_root) / reference.removeprefix("private:")
    return Path(settings.data_export_public_files_root) / reference.removeprefix("/uploads/")


def _candidate_action(client, candidate: dict, action: str, **extra):
    return client.post(
        f"/api/parts/recognition/candidates/{candidate['id']}/actions",
        json={
            "action": action,
            "expected_version": candidate["version"],
            **extra,
        },
    )


def test_visual_candidate_requires_full_human_and_usage_verification(client):
    engineer = client.post(
        "/api/users",
        json={"name": "visual-tech", "email": "visual-tech@example.com", "role": "engineer"},
    ).json()
    warehouse = client.post(
        "/api/warehouses",
        json={"code": "VIS-MAIN", "name": "Visual Main"},
    ).json()
    target_part = client.post(
        "/api/parts",
        json={
            "part_number": "VISION-RELAY-42",
            "name": "Compressor control relay",
            "machine_type": "ACME-9000",
        },
    ).json()
    client.post(
        "/api/parts",
        json={"part_number": "OTHER-FILTER", "name": "Return air filter"},
    )
    inbound = client.post(
        "/api/inventory/transactions",
        json={
            "part_id": target_part["id"],
            "transaction_type": "inbound",
            "quantity": 10,
            "to_warehouse_id": warehouse["id"],
        },
    )
    assert inbound.status_code == 200, inbound.text
    work_order = client.post(
        "/api/work-orders",
        json={
            "ticket_number": "VISUAL-WO-1",
            "engineer_id": engineer["id"],
            "machine_type": "ACME-9000",
            "job_type": "electrical repair",
        },
    ).json()

    with client.app.state.testing_session_local() as db:
        before_candidates = db.query(InventoryTransaction).count()
    created = client.post(
        "/api/parts/recognition/candidates",
        data={
            "work_order_id": str(work_order["id"]),
            "machine_model": "ACME-9000",
            "label_text": "Relay VISION-RELAY-42",
            "notes": "Label is partly scratched",
        },
        files={"file": ("relay.png", PNG, "image/png")},
    )
    assert created.status_code == 200, created.text
    observation = created.json()
    assert observation["work_order_id"] == work_order["id"]
    assert observation["candidates"][0]["part_id"] == target_part["id"]
    assert observation["candidates"][0]["status"] == "ai_candidate"
    assert observation["candidates"][0]["confidence"] >= 0.92
    candidate = observation["candidates"][0]
    assert observation["image_url"].endswith(f"/{observation['id']}/image")
    protected_image = client.get(observation["image_url"])
    assert protected_image.status_code == 200
    assert protected_image.content == PNG
    assert protected_image.headers["cache-control"].startswith("private")
    stored_image = _stored_image_path(client, observation["id"])
    assert stored_image.read_bytes() == PNG

    with client.app.state.testing_session_local() as db:
        assert db.query(InventoryTransaction).count() == before_candidates
        assert db.query(PartMachineAssociation).count() == 0

    employee = _candidate_action(client, candidate, "employee_confirm")
    assert employee.status_code == 200, employee.text
    candidate = employee.json()["candidates"][0]
    assert candidate["status"] == "employee_confirmed"

    admin = _candidate_action(client, candidate, "admin_confirm")
    assert admin.status_code == 200, admin.text
    candidate = admin.json()["candidates"][0]
    assert candidate["status"] == "admin_confirmed"

    no_usage = _candidate_action(client, candidate, "verify_usage")
    assert no_usage.status_code == 409
    assert "has not recorded use" in no_usage.text

    used = client.post(
        f"/api/work-orders/{work_order['id']}/use-part",
        json={
            "work_order_id": work_order["id"],
            "part_id": target_part["id"],
            "warehouse_id": warehouse["id"],
            "user_id": engineer["id"],
            "quantity": 1,
        },
    )
    assert used.status_code == 200, used.text
    with client.app.state.testing_session_local() as db:
        after_usage = db.query(InventoryTransaction).count()

    verified = _candidate_action(client, candidate, "verify_usage")
    assert verified.status_code == 200, verified.text
    candidate = verified.json()["candidates"][0]
    assert candidate["status"] == "usage_verified"

    trusted = _candidate_action(client, candidate, "promote_trusted")
    assert trusted.status_code == 200, trusted.text
    candidate = trusted.json()["candidates"][0]
    assert candidate["status"] == "trusted"
    assert candidate["version"] == 4

    with client.app.state.testing_session_local() as db:
        assert db.query(InventoryTransaction).count() == after_usage
        memory = db.query(PartMachineAssociation).one()
        assert memory.part_id == target_part["id"]
        assert memory.machine_model == "ACME-9000"
        assert memory.recognition_source == "verified_visual"
        assert memory.confidence == 0.99
        actions = {
            row.action
            for row in db.query(AuditLog)
            .filter(AuditLog.entity_type == "part_recognition_candidate")
            .all()
        }
        assert actions == {
            "part_recognition_employee_confirm",
            "part_recognition_admin_confirm",
            "part_recognition_verify_usage",
            "part_recognition_promote_trusted",
        }

    suggestions = client.get(
        "/api/parts/recognition/suggestions?machine_model=ACME-9000"
    )
    assert suggestions.status_code == 200
    assert suggestions.json()[0]["part_id"] == target_part["id"]
    stored_image.unlink()


def test_candidate_actions_require_current_version_and_rejection_reason(client):
    part = client.post(
        "/api/parts",
        json={"part_number": "VERSIONED-1", "name": "Versioned candidate"},
    ).json()
    created = client.post(
        "/api/parts/recognition/candidates",
        data={"label_text": "VERSIONED-1"},
        files={"file": ("versioned.png", PNG, "image/png")},
    )
    assert created.status_code == 200, created.text
    candidate = created.json()["candidates"][0]
    assert candidate["part_id"] == part["id"]

    employee = _candidate_action(client, candidate, "employee_confirm")
    assert employee.status_code == 200
    current = employee.json()["candidates"][0]

    stale = _candidate_action(client, candidate, "admin_confirm")
    assert stale.status_code == 409
    assert "changed" in stale.text

    missing_reason = _candidate_action(client, current, "reject")
    assert missing_reason.status_code == 422
    rejected = _candidate_action(
        client,
        current,
        "reject",
        reason="Label does not match the photographed connector",
    )
    assert rejected.status_code == 200, rejected.text
    rejected_candidate = rejected.json()["candidates"][0]
    assert rejected_candidate["status"] == "rejected"
    assert rejected_candidate["rejection_reason"].startswith("Label")

    cannot_promote = _candidate_action(client, rejected_candidate, "promote_trusted")
    assert cannot_promote.status_code == 409
    _stored_image_path(client, created.json()["id"]).unlink()


def test_visual_candidates_are_tenant_scoped(client):
    with client.app.state.testing_session_local() as db:
        other = Organization(name="Other visual tenant", slug="other-visual-tenant")
        db.add(other)
        db.flush()
        part = Part(
            organization_id=other.id,
            part_number="OTHER-VISUAL",
            name="Private visual part",
        )
        warehouse = Warehouse(
            organization_id=other.id,
            code="OTHER-VIS",
            name="Other Visual Warehouse",
        )
        db.add_all((part, warehouse))
        db.flush()
        observation = PartRecognitionObservation(
            organization_id=other.id,
            machine_model="PRIVATE-MACHINE",
            image_url="/uploads/private.png",
        )
        db.add(observation)
        db.flush()
        candidate = PartRecognitionCandidate(
            organization_id=other.id,
            observation_id=observation.id,
            part_id=part.id,
            rank=1,
            confidence=0.9,
            reason="private tenant signal",
        )
        db.add(candidate)
        db.commit()
        candidate_id = candidate.id

    listed = client.get("/api/parts/recognition/candidates")
    assert listed.status_code == 200
    assert listed.json() == []
    hidden = client.post(
        f"/api/parts/recognition/candidates/{candidate_id}/actions",
        json={"action": "employee_confirm", "expected_version": 0},
    )
    assert hidden.status_code == 404


def test_only_claim_owner_or_admin_can_attach_visual_evidence_to_work_order(client):
    password = "visual-security-password"
    original_rbac = settings.rbac_enforce
    original_legacy = settings.legacy_header_auth
    settings.rbac_enforce = False
    try:
        admin = client.post(
            "/api/users",
            json={
                "name": "visual-admin",
                "email": "visual-admin@example.com",
                "role": "admin",
                "password": password,
            },
        ).json()
        owner = client.post(
            "/api/users",
            json={
                "name": "visual-owner",
                "email": "visual-owner@example.com",
                "role": "engineer",
                "password": password,
            },
        ).json()
        other = client.post(
            "/api/users",
            json={
                "name": "visual-other",
                "email": "visual-other@example.com",
                "role": "engineer",
                "password": password,
            },
        ).json()
        manager = client.post(
            "/api/users",
            json={
                "name": "visual-manager",
                "email": "visual-manager@example.com",
                "role": "manager",
                "password": password,
            },
        ).json()
        client.post(
            "/api/parts",
            json={"part_number": "SECURE-VISUAL", "name": "Secure visual part"},
        )
        settings.rbac_enforce = True
        settings.legacy_header_auth = True
        manager_headers = {"X-User-Id": str(manager["id"])}
        work_order = client.post(
            "/api/work-orders",
            headers=manager_headers,
            json={
                "ticket_number": "VISUAL-SECURE-WO",
                "assigned_user_id": owner["id"],
                "engineer_id": owner["id"],
                "machine_type": "SECURE-MACHINE",
            },
        ).json()

        def login(user: dict, device_id: str, device_token: str) -> dict[str, str]:
            response = client.post(
                "/api/auth/login",
                data={"username": user["email"], "password": password},
                headers={
                    "X-Device-Id": device_id,
                    "X-Device-Token": device_token,
                    "X-Device-Name": device_id,
                },
            )
            assert response.status_code == 200, response.text
            return {
                "Authorization": f"Bearer {response.json()['access_token']}",
                "X-Device-Token": device_token,
            }

        owner_headers = login(owner, "visual-owner-phone", "a" * 64)
        other_headers = login(other, "visual-other-phone", "b" * 64)
        claimed = client.post(
            f"/api/work-orders/{work_order['id']}/claim",
            headers=owner_headers,
        )
        assert claimed.status_code == 200, claimed.text
        version = str(claimed.json()["claim_version"])
        form = {
            "work_order_id": str(work_order["id"]),
            "label_text": "SECURE-VISUAL",
        }
        files = {"file": ("secure.png", PNG, "image/png")}

        denied_other = client.post(
            "/api/parts/recognition/candidates",
            headers={**other_headers, "X-Claim-Version": version},
            data=form,
            files=files,
        )
        assert denied_other.status_code == 403
        denied_manager = client.post(
            "/api/parts/recognition/candidates",
            headers=manager_headers,
            data=form,
            files=files,
        )
        assert denied_manager.status_code == 403
        owner_created = client.post(
            "/api/parts/recognition/candidates",
            headers={**owner_headers, "X-Claim-Version": version},
            data=form,
            files=files,
        )
        assert owner_created.status_code == 200, owner_created.text
        assert owner_created.json()["created_by"] == owner["id"]
        other_can_view = client.get(
            owner_created.json()["image_url"],
            headers=other_headers,
        )
        assert other_can_view.status_code == 200
        assert other_can_view.content == PNG
        unauthenticated = client.get(owner_created.json()["image_url"])
        assert unauthenticated.status_code == 401
        owner_candidate = owner_created.json()["candidates"][0]
        owner_confirmed = client.post(
            f"/api/parts/recognition/candidates/{owner_candidate['id']}/actions",
            headers={**owner_headers, "X-Claim-Version": version},
            json={
                "action": "employee_confirm",
                "expected_version": owner_candidate["version"],
                "work_order_id": work_order["id"],
            },
        )
        assert owner_confirmed.status_code == 200, owner_confirmed.text
        owner_candidate = owner_confirmed.json()["candidates"][0]
        independently_confirmed = client.post(
            f"/api/parts/recognition/candidates/{owner_candidate['id']}/actions",
            headers={"X-User-Id": str(admin["id"])},
            json={
                "action": "admin_confirm",
                "expected_version": owner_candidate["version"],
                "work_order_id": work_order["id"],
            },
        )
        assert independently_confirmed.status_code == 200, independently_confirmed.text
        _stored_image_path(client, owner_created.json()["id"]).unlink()

        admin_created = client.post(
            "/api/parts/recognition/candidates",
            headers={"X-User-Id": str(admin["id"])},
            data=form,
            files=files,
        )
        assert admin_created.status_code == 200, admin_created.text
        admin_candidate = admin_created.json()["candidates"][0]
        admin_as_employee = client.post(
            f"/api/parts/recognition/candidates/{admin_candidate['id']}/actions",
            headers={"X-User-Id": str(admin["id"])},
            json={
                "action": "employee_confirm",
                "expected_version": admin_candidate["version"],
                "work_order_id": work_order["id"],
            },
        )
        assert admin_as_employee.status_code == 200, admin_as_employee.text
        same_admin = client.post(
            f"/api/parts/recognition/candidates/{admin_candidate['id']}/actions",
            headers={"X-User-Id": str(admin["id"])},
            json={
                "action": "admin_confirm",
                "expected_version": admin_as_employee.json()["candidates"][0]["version"],
                "work_order_id": work_order["id"],
            },
        )
        assert same_admin.status_code == 409
        assert "different account" in same_admin.text
        _stored_image_path(client, admin_created.json()["id"]).unlink()
    finally:
        settings.rbac_enforce = original_rbac
        settings.legacy_header_auth = original_legacy
