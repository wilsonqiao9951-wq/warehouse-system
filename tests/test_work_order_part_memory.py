from datetime import datetime

from app.models import Organization, Part, Warehouse, WorkOrder, WorkOrderPart


def test_similar_work_orders_receive_part_recommendations(client):
    user = client.post("/api/users", json={"name": "memory-tech", "email": "memory-tech@example.com", "role": "engineer"}).json()
    warehouse = client.post("/api/warehouses", json={"code": "MEM", "name": "Memory Warehouse"}).json()
    part = client.post("/api/parts", json={"part_number": "PUMP-SEAL", "name": "Pump Seal"}).json()
    client.post("/api/inventory/transactions", json={"part_id": part["id"], "transaction_type": "inbound", "quantity": 10, "to_warehouse_id": warehouse["id"]})
    work_order = client.post("/api/work-orders", json={"ticket_number": "MEM-1", "assigned_user_id": user["id"], "engineer_id": user["id"], "machine_type": "Pump-X", "job_type": "seal replacement"}).json()
    used = client.post(f"/api/work-orders/{work_order['id']}/use-part", json={"work_order_id": work_order["id"], "part_id": part["id"], "warehouse_id": warehouse["id"], "user_id": user["id"], "quantity": 2})
    assert used.status_code == 200
    recommendations = client.get(f"/api/work-orders/{work_order['id']}/part-recommendations")
    assert recommendations.status_code == 200
    assert recommendations.json()[0]["part"]["part_number"] == "PUMP-SEAL"
    assert recommendations.json()[0]["recommended_quantity"] == 2
    assert recommendations.json()[0]["success_rate"] is None
    assert 0 < recommendations.json()[0]["confidence"] < 0.7


def test_ranked_recommendations_explain_outcomes_duration_and_inventory_location(
    client,
    seed_inventory_ledger,
):
    engineer = client.post(
        "/api/users",
        json={"name": "ranking-tech", "email": "ranking-tech@example.com", "role": "engineer"},
    ).json()
    main = client.post(
        "/api/warehouses",
        json={"code": "RANK-MAIN", "name": "Ranking Main"},
    ).json()
    van = client.post(
        "/api/warehouses",
        json={
            "code": "RANK-VAN",
            "name": "Ranking Van",
            "warehouse_type": "van",
            "assigned_user_id": engineer["id"],
        },
    ).json()
    van_bin = client.post(
        "/api/storage-locations",
        json={"warehouse_id": van["id"], "code": "VAN-A1", "name": "Front shelf"},
    ).json()
    exact_part = client.post(
        "/api/parts",
        json={"part_number": "RANK-EXACT", "name": "Exact match contactor"},
    ).json()
    weak_part = client.post(
        "/api/parts",
        json={"part_number": "RANK-WEAK", "name": "Weak match filter"},
    ).json()
    similar_part = client.post(
        "/api/parts",
        json={"part_number": "RANK-SIMILAR", "name": "Similar symptom relay"},
    ).json()
    for part in (exact_part, weak_part, similar_part):
        inbound = client.post(
            "/api/inventory/transactions",
            json={
                "part_id": part["id"],
                "transaction_type": "inbound",
                "quantity": 20,
                "to_warehouse_id": main["id"],
            },
        )
        assert inbound.status_code == 200, inbound.text
    seed_inventory_ledger(
        part_id=exact_part["id"],
        quantity=7,
        to_warehouse_id=van["id"],
        to_location_id=van_bin["id"],
    )

    exact_history = []
    for number, quantity in (("RANK-H1", 2), ("RANK-H2", 4)):
        row = client.post(
            "/api/work-orders",
            json={
                "ticket_number": number,
                "engineer_id": engineer["id"],
                "machine_type": "RTU-900",
                "job_type": "cooling repair",
                "fault_type": "electrical",
                "error_code": "E42",
                "problem_description": "compressor will not start after control alarm",
            },
        ).json()
        used = client.post(
            f"/api/work-orders/{row['id']}/use-part",
            json={
                "work_order_id": row["id"],
                "part_id": exact_part["id"],
                "warehouse_id": main["id"],
                "user_id": engineer["id"],
                "quantity": quantity,
            },
        )
        assert used.status_code == 200, used.text
        exact_history.append(row["id"])

    weak_history = client.post(
        "/api/work-orders",
        json={
            "ticket_number": "RANK-WEAK-H1",
            "engineer_id": engineer["id"],
            "machine_type": "OTHER-100",
            "job_type": "cooling repair",
            "fault_type": "airflow",
            "problem_description": "dirty return air filter",
        },
    ).json()
    used = client.post(
        f"/api/work-orders/{weak_history['id']}/use-part",
        json={
            "work_order_id": weak_history["id"],
            "part_id": weak_part["id"],
            "warehouse_id": main["id"],
            "user_id": engineer["id"],
            "quantity": 1,
        },
    )
    assert used.status_code == 200, used.text

    similar_history = client.post(
        "/api/work-orders",
        json={
            "ticket_number": "RANK-SIMILAR-H1",
            "engineer_id": engineer["id"],
            "machine_type": "UNRELATED-200",
            "job_type": "diagnostic visit",
            "fault_type": "unknown",
            "problem_description": "control alarm compressor will not start",
        },
    ).json()
    used = client.post(
        f"/api/work-orders/{similar_history['id']}/use-part",
        json={
            "work_order_id": similar_history["id"],
            "part_id": similar_part["id"],
            "warehouse_id": main["id"],
            "user_id": engineer["id"],
            "quantity": 1,
        },
    )
    assert used.status_code == 200, used.text

    with client.app.state.testing_session_local() as db:
        first = db.get(WorkOrder, exact_history[0])
        first.status = "COMPLETED"
        first.completed_at = datetime.utcnow()
        first.final_outcome = "repaired"
        first.first_time_fix = True
        first.is_rework = False
        first.repair_duration_minutes = 60

        second = db.get(WorkOrder, exact_history[1])
        second.status = "COMPLETED"
        second.completed_at = datetime.utcnow()
        second.final_outcome = "temporary_fix"
        second.first_time_fix = False
        second.is_rework = False
        second.repair_duration_minutes = 90

        weak = db.get(WorkOrder, weak_history["id"])
        weak.status = "COMPLETED"
        weak.completed_at = datetime.utcnow()
        weak.final_outcome = "repaired"
        weak.first_time_fix = True
        weak.is_rework = False
        weak.repair_duration_minutes = 30

        similar = db.get(WorkOrder, similar_history["id"])
        similar.status = "COMPLETED"
        similar.completed_at = datetime.utcnow()
        similar.final_outcome = "repaired"
        similar.first_time_fix = True
        similar.is_rework = False
        similar.repair_duration_minutes = 45
        db.commit()

    target = client.post(
        "/api/work-orders",
        json={
            "ticket_number": "RANK-TARGET",
            "assigned_user_id": engineer["id"],
            "engineer_id": engineer["id"],
            "machine_type": "RTU-900",
            "job_type": "cooling repair",
            "fault_type": "electrical",
            "error_code": "E42",
            "problem_description": "control alarm and compressor will not start",
        },
    ).json()
    response = client.get(f"/api/work-orders/{target['id']}/part-recommendations")
    assert response.status_code == 200, response.text
    recommendations = response.json()
    assert [item["part"]["part_number"] for item in recommendations[:3]] == [
        "RANK-EXACT",
        "RANK-SIMILAR",
        "RANK-WEAK",
    ]

    best = recommendations[0]
    assert best["recommended_quantity"] == 3
    assert best["usage_count"] == 2
    assert best["total_quantity"] == 6
    assert best["success_rate"] == 0.5
    assert best["average_repair_minutes"] == 75.0
    assert best["available_quantity"] == 21
    assert best["inventory_location"] == "Ranking Van / VAN-A1"
    assert best["inventory_warehouse_id"] == van["id"]
    assert best["inventory_location_id"] == van_bin["id"]
    assert best["confidence"] > recommendations[1]["confidence"]
    assert "same machine" in best["reason"]
    assert "50% first-time repair success" in best["reason"]


def test_ranked_recommendations_never_learn_from_another_organization(client):
    with client.app.state.testing_session_local() as db:
        other = Organization(name="Other service company", slug="other-service-company")
        db.add(other)
        db.flush()
        warehouse = Warehouse(
            organization_id=other.id,
            code="OTHER-MAIN",
            name="Other Main",
        )
        part = Part(
            organization_id=other.id,
            part_number="OTHER-SECRET",
            name="Other tenant part",
        )
        db.add_all((warehouse, part))
        db.flush()
        history = WorkOrder(
            organization_id=other.id,
            ticket_number="OTHER-HISTORY",
            machine_type="SHARED-MODEL",
            job_type="shared repair",
            status="COMPLETED",
            final_outcome="repaired",
            first_time_fix=True,
            completed_at=datetime.utcnow(),
        )
        db.add(history)
        db.flush()
        db.add(
            WorkOrderPart(
                organization_id=other.id,
                work_order_id=history.id,
                part_id=part.id,
                warehouse_id=warehouse.id,
                quantity=10,
            )
        )
        db.commit()

    target = client.post(
        "/api/work-orders",
        json={
            "ticket_number": "TENANT-TARGET",
            "machine_type": "SHARED-MODEL",
            "job_type": "shared repair",
        },
    ).json()
    response = client.get(f"/api/work-orders/{target['id']}/part-recommendations")
    assert response.status_code == 200
    assert response.json() == []
