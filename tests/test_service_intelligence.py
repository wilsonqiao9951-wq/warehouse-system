from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timedelta

from app.core.config import settings
from app.models import (
    MachineKnowledgeEntry,
    MachineKnowledgeProfile,
    Organization,
    Part,
    User,
    UserRole,
    Warehouse,
    WorkOrder,
    WorkOrderPart,
)


def _create_user(client, name: str, role: str = "admin") -> dict:
    response = client.post(
        "/api/users",
        json={
            "name": name,
            "email": f"{name}@service-intelligence.test",
            "role": role,
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


@contextmanager
def _enforced_rbac():
    original_rbac = settings.rbac_enforce
    original_legacy = settings.legacy_header_auth
    settings.rbac_enforce = True
    settings.legacy_header_auth = True
    try:
        yield
    finally:
        settings.rbac_enforce = original_rbac
        settings.legacy_header_auth = original_legacy


def test_service_intelligence_ranks_traceable_history_and_published_guidance(client):
    now = datetime.utcnow()
    with client.app.state.testing_session_local() as db:
        part = Part(
            organization_id=1,
            part_number="INTEL-FILTER-01",
            name="Primary airflow filter",
            default_cost=999.0,
            supplier="Private supplier",
        )
        warehouse = Warehouse(
            organization_id=1,
            code="INTEL-MAIN",
            name="Intelligence main warehouse",
        )
        db.add_all((part, warehouse))
        db.flush()
        target = WorkOrder(
            organization_id=1,
            ticket_number="INTEL-TARGET",
            machine_type="ACME-9000",
            job_type="Cooling repair",
            problem_description="Low airflow and warm cabinet",
            fault_type="Airflow failure",
            error_code="AIR-01",
            status="open",
        )
        strongest = WorkOrder(
            organization_id=1,
            ticket_number="INTEL-HISTORY-STRONG",
            machine_type="acme-9000",
            job_type="Cooling repair",
            problem_description="Warm cabinet caused by low airflow",
            fault_type="Airflow failure",
            error_code="AIR-01",
            repair_result="Replaced filter and verified temperature.",
            final_outcome="repaired",
            first_time_fix=True,
            is_rework=False,
            repair_duration_minutes=40,
            status="completed",
            is_locked=True,
            completed_at=now - timedelta(days=1),
            revenue=5000,
            labor_cost=2500,
        )
        second = WorkOrder(
            organization_id=1,
            ticket_number="INTEL-HISTORY-SECOND",
            machine_type="ACME-9000",
            job_type="Cooling repair",
            problem_description="Restricted air path",
            fault_type="Airflow failure",
            error_code="AIR-02",
            repair_result="Cleaned air path.",
            final_outcome="temporary_fix",
            first_time_fix=False,
            is_rework=True,
            repair_duration_minutes=80,
            status="COMPLETED",
            is_locked=True,
            completed_at=now - timedelta(days=2),
        )
        untrusted = WorkOrder(
            organization_id=1,
            ticket_number="INTEL-UNLOCKED",
            machine_type="ACME-9000",
            job_type="Cooling repair",
            fault_type="Airflow failure",
            error_code="AIR-01",
            first_time_fix=True,
            repair_duration_minutes=5,
            status="completed",
            is_locked=False,
            completed_at=now,
        )
        db.add_all((target, strongest, second, untrusted))
        db.flush()
        db.add(
            WorkOrderPart(
                organization_id=1,
                work_order_id=strongest.id,
                part_id=part.id,
                warehouse_id=warehouse.id,
                quantity=2,
                unit_cost=12,
                total_cost=24,
            )
        )
        profile = MachineKnowledgeProfile(
            organization_id=1,
            model="ACME-9000",
            model_key="acme-9000",
            is_active=True,
        )
        db.add(profile)
        db.flush()
        published = MachineKnowledgeEntry(
            organization_id=1,
            profile_id=profile.id,
            entry_type="fault",
            title="AIR-01 low-airflow recovery",
            content="Inspect the filter and verify the fan path before replacing controls.",
            fault_code="AIR-01",
            related_part_id=part.id,
            related_part_role="recommended",
            installation_location="Upper return-air compartment",
            status="published",
            published_at=now,
        )
        draft = MachineKnowledgeEntry(
            organization_id=1,
            profile_id=profile.id,
            entry_type="caution",
            title="Unreviewed private draft",
            content="This draft must not be exposed.",
            status="draft",
        )
        db.add_all((published, draft))
        db.commit()
        target_id = target.id
        strongest_id = strongest.id
        second_id = second.id
        untrusted_id = untrusted.id
        published_id = published.id
        draft_id = draft.id

    response = client.get(f"/api/work-orders/{target_id}/service-intelligence")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["evidence_scope"] == (
        "organization_completed_work_orders_and_published_exact_model_knowledge"
    )
    analysis = body["fault_analysis"]
    assert analysis["completed_work_orders"] == 2
    assert analysis["labeled_outcomes"] == 2
    assert analysis["first_time_fix_rate"] == 0.5
    assert analysis["rework_rate"] == 0.5
    assert analysis["average_repair_minutes"] == 60.0
    assert analysis["top_fault_types"][0] == {
        "value": "Airflow failure",
        "count": 2,
    }
    assert any("elevated rework" in warning for warning in analysis["warnings"])

    knowledge = body["knowledge_entries"]
    assert [entry["id"] for entry in knowledge] == [published_id]
    assert draft_id not in {entry["id"] for entry in knowledge}
    assert knowledge[0]["confidence"] > 0.5
    assert knowledge[0]["related_part"]["part_number"] == "INTEL-FILTER-01"
    assert "default_cost" not in knowledge[0]["related_part"]
    assert "supplier" not in knowledge[0]["related_part"]
    assert knowledge[0]["installation_location"] == "Upper return-air compartment"

    similar = body["similar_work_orders"]
    assert [item["id"] for item in similar[:2]] == [strongest_id, second_id]
    assert untrusted_id not in {item["id"] for item in similar}
    assert similar[0]["confidence"] > similar[1]["confidence"]
    assert similar[0]["parts_used"] == [
        {
            "part_number": "INTEL-FILTER-01",
            "name": "Primary airflow filter",
            "quantity": 2,
        }
    ]
    assert "revenue" not in similar[0]
    assert "labor_cost" not in similar[0]
    assert "customer_signature_data" not in similar[0]


def test_engineer_can_read_another_engineers_service_intelligence(client):
    owner = _create_user(client, "intelligence-owner", "engineer")
    observer = _create_user(client, "intelligence-observer", "engineer")
    with client.app.state.testing_session_local() as db:
        target = WorkOrder(
            organization_id=1,
            ticket_number="INTEL-SHARED-POOL",
            machine_type="SHARED-100",
            job_type="Inspection",
            status="in_progress",
            claimed_by_id=owner["id"],
            assigned_user_id=owner["id"],
            engineer_id=owner["id"],
            claim_version=1,
        )
        history = WorkOrder(
            organization_id=1,
            ticket_number="INTEL-SHARED-HISTORY",
            machine_type="SHARED-100",
            job_type="Inspection",
            status="completed",
            is_locked=True,
            completed_at=datetime.utcnow(),
            first_time_fix=True,
        )
        db.add_all((target, history))
        db.commit()
        target_id = target.id

    with _enforced_rbac():
        response = client.get(
            f"/api/work-orders/{target_id}/service-intelligence",
            headers={"X-User-Id": str(observer["id"])},
        )
        assert response.status_code == 200, response.text
        assert response.json()["fault_analysis"]["completed_work_orders"] == 1

        forbidden_write = client.patch(
            f"/api/work-orders/{target_id}",
            headers={"X-User-Id": str(observer["id"])},
            json={"problem_description": "Unauthorized change"},
        )
        assert forbidden_write.status_code in {401, 403}


def test_service_intelligence_is_tenant_scoped_and_requires_visible_target(client):
    org_one_admin = _create_user(client, "intelligence-org-one", "admin")
    now = datetime.utcnow()
    with client.app.state.testing_session_local() as db:
        target = WorkOrder(
            organization_id=1,
            ticket_number="INTEL-ORG1-TARGET",
            machine_type="TENANT-MODEL",
            job_type="Repair",
            status="open",
        )
        own_history = WorkOrder(
            organization_id=1,
            ticket_number="INTEL-ORG1-HISTORY",
            machine_type="TENANT-MODEL",
            job_type="Repair",
            status="completed",
            is_locked=True,
            completed_at=now,
            first_time_fix=True,
        )
        other_org = Organization(name="Intelligence Tenant Two", slug="intelligence-tenant-two")
        db.add_all((target, own_history, other_org))
        db.flush()
        other_admin = User(
            organization_id=other_org.id,
            name="intelligence-org-two",
            email="intelligence-org-two@service-intelligence.test",
            role=UserRole.ADMIN,
        )
        other_history = WorkOrder(
            organization_id=other_org.id,
            ticket_number="INTEL-ORG2-HISTORY",
            machine_type="TENANT-MODEL",
            job_type="Repair",
            status="completed",
            is_locked=True,
            completed_at=now,
            first_time_fix=False,
            is_rework=True,
        )
        other_target = WorkOrder(
            organization_id=other_org.id,
            ticket_number="INTEL-ORG2-TARGET",
            machine_type="TENANT-MODEL",
            status="open",
        )
        other_profile = MachineKnowledgeProfile(
            organization_id=other_org.id,
            model="TENANT-MODEL",
            model_key="tenant-model",
            is_active=True,
        )
        db.add_all((other_admin, other_history, other_target, other_profile))
        db.flush()
        db.add(
            MachineKnowledgeEntry(
                organization_id=other_org.id,
                profile_id=other_profile.id,
                entry_type="note",
                title="Other tenant secret",
                content="Must never cross the tenant boundary.",
                status="published",
                published_at=now,
            )
        )
        db.commit()
        target_id = target.id
        other_target_id = other_target.id

    with _enforced_rbac():
        response = client.get(
            f"/api/work-orders/{target_id}/service-intelligence",
            headers={"X-User-Id": str(org_one_admin["id"])},
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["fault_analysis"]["completed_work_orders"] == 1
        assert body["fault_analysis"]["first_time_fix_rate"] == 1.0
        assert body["knowledge_entries"] == []
        assert {item["ticket_number"] for item in body["similar_work_orders"]} == {
            "INTEL-ORG1-HISTORY"
        }

        hidden_target = client.get(
            f"/api/work-orders/{other_target_id}/service-intelligence",
            headers={"X-User-Id": str(org_one_admin["id"])},
        )
        assert hidden_target.status_code == 404
