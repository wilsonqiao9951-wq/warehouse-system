from contextlib import contextmanager
from datetime import datetime, timedelta

from app.core.config import settings
from app.models import (
    Organization,
    PartUsageReview,
    User,
    UserRole,
    WorkOrder,
    WorkOrderPart,
)


@contextmanager
def _enforced_legacy_auth():
    original_rbac = settings.rbac_enforce
    original_legacy = settings.legacy_header_auth
    settings.rbac_enforce = True
    settings.legacy_header_auth = True
    try:
        yield
    finally:
        settings.rbac_enforce = original_rbac
        settings.legacy_header_auth = original_legacy


def _create_history(
    db,
    *,
    engineer_id: int,
    warehouse_id: int,
    part_id: int,
    quantities: list[int],
    ticket_prefix: str,
    job_type: str = "repair",
    machine_type: str = "ACME-9000",
    store_name: str = "North Store",
) -> None:
    now = datetime.utcnow()
    for index, quantity in enumerate(quantities, start=1):
        completed_at = now - timedelta(days=len(quantities) - index + 2)
        work_order = WorkOrder(
            organization_id=1,
            ticket_number=f"{ticket_prefix}-{index}",
            job_type=job_type,
            machine_type=machine_type,
            store_name=store_name,
            engineer_id=engineer_id,
            completed_by_id=engineer_id,
            status="COMPLETED",
            is_locked=True,
            completed_at=completed_at,
            revenue=300,
        )
        db.add(work_order)
        db.flush()
        db.add(
            WorkOrderPart(
                organization_id=1,
                work_order_id=work_order.id,
                part_id=part_id,
                warehouse_id=warehouse_id,
                user_id=engineer_id,
                quantity=quantity,
                unit_cost=10,
                total_cost=quantity * 10,
                created_at=completed_at - timedelta(hours=1),
                updated_at=completed_at - timedelta(hours=1),
            )
        )
    db.commit()


def _masters(client):
    engineer = client.post(
        "/api/users",
        json={"name": "Usage Engineer", "email": "usage-engineer@example.test", "role": "engineer"},
    ).json()
    warehouse = client.post(
        "/api/warehouses",
        json={"code": "USAGE-WH", "name": "Usage Warehouse"},
    ).json()
    part = client.post(
        "/api/parts",
        json={"part_number": "USAGE-PART", "name": "Usage part", "default_cost": 10},
    ).json()
    return engineer, warehouse, part


def test_public_part_usage_creates_explainable_review_and_versioned_decision(
    client,
    seed_inventory_ledger,
):
    engineer, warehouse, part = _masters(client)
    sessions = client.app.state.testing_session_local
    with sessions() as db:
        _create_history(
            db,
            engineer_id=engineer["id"],
            warehouse_id=warehouse["id"],
            part_id=part["id"],
            quantities=[1, 1, 1],
            ticket_prefix="USAGE-HISTORY",
        )
    target = client.post(
        "/api/work-orders",
        json={
            "ticket_number": "USAGE-TARGET",
            "job_type": "repair",
            "machine_type": "ACME-9000",
            "store_name": "North Store",
            "engineer_id": engineer["id"],
            "assigned_user_id": engineer["id"],
            "revenue": 300,
        },
    ).json()
    seed_inventory_ledger(
        part_id=part["id"],
        quantity=20,
        to_warehouse_id=warehouse["id"],
        unit_cost=10,
    )
    used = client.post(
        f"/api/work-orders/{target['id']}/use-part",
        json={
            "work_order_id": target["id"],
            "part_id": part["id"],
            "warehouse_id": warehouse["id"],
            "quantity": 8,
            "unit_cost": 10,
        },
    )
    assert used.status_code == 200, used.text

    listed = client.get("/api/reports/abnormal-usage")
    assert listed.status_code == 200, listed.text
    assert len(listed.json()) == 1
    review = listed.json()[0]
    assert review["work_order_part_id"] == used.json()["id"]
    assert review["reason_codes"][0] == "quantity_spike"
    assert review["baseline_scope"] == "job_machine_store"
    assert review["baseline_sample_size"] == 3
    assert review["baseline_mean_quantity"] == 1
    assert review["baseline_spike_threshold"] == 1.8
    assert review["source_fingerprint"]
    assert review["parts_cost"] == 80
    assert "exceeds" in review["reason"]
    baselines = client.get(
        f"/api/reports/abnormal-usage/baselines?part_id={part['id']}"
    )
    assert baselines.status_code == 200, baselines.text
    assert {row["scope"] for row in baselines.json()} == {
        "job_machine_store",
        "job_machine",
        "machine",
        "job",
        "organization",
    }

    missing_note = client.post(
        f"/api/reports/abnormal-usage/{review['id']}/actions",
        json={"action": "acknowledge", "expected_version": review["version"]},
    )
    assert missing_note.status_code == 422

    acknowledged = client.post(
        f"/api/reports/abnormal-usage/{review['id']}/actions",
        json={
            "action": "acknowledge",
            "expected_version": review["version"],
            "note": "Manager accepted the evidence review",
        },
    )
    assert acknowledged.status_code == 200, acknowledged.text
    assert acknowledged.json()["status"] == "acknowledged"
    repeated_acknowledgement = client.post(
        f"/api/reports/abnormal-usage/{review['id']}/actions",
        json={
            "action": "acknowledge",
            "expected_version": review["version"],
            "note": "Manager accepted the evidence review",
        },
    )
    assert repeated_acknowledgement.status_code == 200
    assert repeated_acknowledgement.json()["version"] == acknowledged.json()["version"]
    stale = client.post(
        f"/api/reports/abnormal-usage/{review['id']}/actions",
        json={
            "action": "confirm",
            "expected_version": review["version"],
            "reason": "Confirmed against the service notes",
        },
    )
    assert stale.status_code == 409
    confirmed = client.post(
        f"/api/reports/abnormal-usage/{review['id']}/actions",
        json={
            "action": "confirm",
            "expected_version": acknowledged.json()["version"],
            "reason": "Confirmed against the service notes",
        },
    )
    assert confirmed.status_code == 200, confirmed.text
    assert confirmed.json()["status"] == "confirmed"
    repeated_confirmation = client.post(
        f"/api/reports/abnormal-usage/{review['id']}/actions",
        json={
            "action": "confirm",
            "expected_version": acknowledged.json()["version"],
            "reason": "Confirmed against the service notes",
        },
    )
    assert repeated_confirmation.status_code == 200
    assert repeated_confirmation.json()["version"] == confirmed.json()["version"]
    assert client.get("/api/reports/abnormal-usage").json() == []
    assert len(client.get("/api/reports/abnormal-usage?status=confirmed").json()) == 1


def test_rare_part_combination_is_detected_without_quantity_spike(client):
    engineer, warehouse, common_part = _masters(client)
    rare_part = client.post(
        "/api/parts",
        json={"part_number": "RARE-PART", "name": "Rare part", "default_cost": 2},
    ).json()
    target = client.post(
        "/api/work-orders",
        json={
            "ticket_number": "RARE-TARGET",
            "job_type": "repair",
            "machine_type": "ACME-9000",
            "store_name": "North Store",
            "engineer_id": engineer["id"],
        },
    ).json()
    sessions = client.app.state.testing_session_local
    with sessions() as db:
        _create_history(
            db,
            engineer_id=engineer["id"],
            warehouse_id=warehouse["id"],
            part_id=common_part["id"],
            quantities=[1, 1, 1, 1, 1],
            ticket_prefix="RARE-HISTORY",
        )
        target_order = db.get(WorkOrder, target["id"])
        usage = WorkOrderPart(
            organization_id=1,
            work_order_id=target_order.id,
            part_id=rare_part["id"],
            warehouse_id=warehouse["id"],
            user_id=engineer["id"],
            quantity=1,
            unit_cost=2,
            total_cost=2,
            created_at=datetime.utcnow().replace(hour=12, minute=0, second=0, microsecond=0),
        )
        db.add(usage)
        db.flush()
        from app.services.abnormal_usage import evaluate_part_usage

        outcome = evaluate_part_usage(db, 1, usage)
        db.commit()
        assert outcome.created is True
        assert outcome.review is not None
        assert json_load(outcome.review.reason_codes_json) == ["unusual_part_combination"]
        assert outcome.review.combination_support_ratio == 0
        assert outcome.review.segment_work_order_count == 5


def json_load(value: str):
    import json

    return json.loads(value)


def test_review_queue_roles_and_tenant_isolation(client, seed_inventory_ledger):
    engineer, warehouse, part = _masters(client)
    sessions = client.app.state.testing_session_local
    with sessions() as db:
        _create_history(
            db,
            engineer_id=engineer["id"],
            warehouse_id=warehouse["id"],
            part_id=part["id"],
            quantities=[1, 1, 1],
            ticket_prefix="ROLE-HISTORY",
        )
        manager = User(
            organization_id=1,
            name="Usage Manager",
            email="usage-manager@example.test",
            role=UserRole.MANAGER,
        )
        other_org = Organization(name="Other usage tenant", slug="other-usage-tenant")
        db.add_all([manager, other_org])
        db.flush()
        other_admin = User(
            organization_id=other_org.id,
            name="Other Usage Admin",
            email="other-usage-admin@example.test",
            role=UserRole.ADMIN,
        )
        db.add(other_admin)
        db.commit()
        ids = {"manager": manager.id, "engineer": engineer["id"], "other": other_admin.id}
    target = client.post(
        "/api/work-orders",
        json={
            "ticket_number": "ROLE-TARGET",
            "job_type": "repair",
            "machine_type": "ACME-9000",
            "store_name": "North Store",
            "engineer_id": engineer["id"],
        },
    ).json()
    seed_inventory_ledger(part_id=part["id"], quantity=20, to_warehouse_id=warehouse["id"])
    used = client.post(
        f"/api/work-orders/{target['id']}/use-part",
        json={
            "work_order_id": target["id"],
            "part_id": part["id"],
            "warehouse_id": warehouse["id"],
            "quantity": 8,
        },
    )
    assert used.status_code == 200

    with _enforced_legacy_auth():
        manager_rows = client.get(
            "/api/reports/abnormal-usage",
            headers={"X-User-Id": str(ids["manager"])},
        )
        engineer_rows = client.get(
            "/api/reports/abnormal-usage",
            headers={"X-User-Id": str(ids["engineer"])},
        )
        other_rows = client.get(
            "/api/reports/abnormal-usage",
            headers={"X-User-Id": str(ids["other"])},
        )
        engineer_evaluate = client.post(
            "/api/reports/abnormal-usage/evaluate",
            headers={"X-User-Id": str(ids["engineer"])},
        )

    assert manager_rows.status_code == 200
    assert len(manager_rows.json()) == 1
    assert engineer_rows.status_code == 403
    assert other_rows.status_code == 200
    assert other_rows.json() == []
    assert engineer_evaluate.status_code == 403


def test_history_evaluation_is_bounded_and_idempotent(client):
    engineer, warehouse, part = _masters(client)
    sessions = client.app.state.testing_session_local
    with sessions() as db:
        usage_ids = []
        for index in (1, 2):
            work_order = WorkOrder(
                organization_id=1,
                ticket_number=f"EVALUATE-OFF-HOUR-{index}",
                engineer_id=engineer["id"],
                job_type="repair",
                machine_type="ACME-9000",
                store_name="North Store",
            )
            db.add(work_order)
            db.flush()
            usage = WorkOrderPart(
                organization_id=1,
                work_order_id=work_order.id,
                part_id=part["id"],
                warehouse_id=warehouse["id"],
                user_id=engineer["id"],
                quantity=1,
                unit_cost=1,
                total_cost=1,
                created_at=datetime.utcnow().replace(
                    hour=2, minute=index, second=0, microsecond=0
                ),
            )
            db.add(usage)
            db.flush()
            usage_ids.append(usage.id)
        db.commit()

    first = client.post("/api/reports/abnormal-usage/evaluate?limit=1")
    assert first.status_code == 200, first.text
    assert first.json() == {
        "scanned": 1,
        "created": 1,
        "already_evaluated": 0,
        "no_anomaly": 0,
        "truncated": True,
        "next_after_id": usage_ids[0],
    }
    continued = client.post(
        f"/api/reports/abnormal-usage/evaluate?limit=1&after_id={first.json()['next_after_id']}"
    )
    assert continued.status_code == 200
    assert continued.json()["created"] == 1
    assert continued.json()["truncated"] is False
    assert continued.json()["next_after_id"] is None
    second = client.post("/api/reports/abnormal-usage/evaluate?limit=1")
    assert second.status_code == 200
    assert second.json()["created"] == 0
    assert second.json()["already_evaluated"] == 1
    with sessions() as db:
        assert db.query(PartUsageReview).count() == 2
