from sqlalchemy import select

from app.models import Organization, Part, User, Warehouse, WorkOrder


def test_default_organization_owns_new_core_records(client):
    user_response = client.post(
        "/api/users",
        json={"name": "Tenant Admin", "email": "tenant-admin@example.com", "role": "admin"},
    )
    assert user_response.status_code == 200
    user = user_response.json()
    assert user["organization_id"] == 1

    warehouse_response = client.post(
        "/api/warehouses",
        json={"name": "Tenant Warehouse", "assigned_user_id": user["id"]},
    )
    assert warehouse_response.status_code == 200
    assert warehouse_response.json()["organization_id"] == 1

    part_response = client.post(
        "/api/parts",
        json={"part_number": "TENANT-PART-1", "name": "Tenant Part"},
    )
    assert part_response.status_code == 200
    assert part_response.json()["organization_id"] == 1

    work_order_response = client.post(
        "/api/work-orders",
        json={"ticket_number": "TENANT-WO-1", "assigned_user_id": user["id"]},
    )
    assert work_order_response.status_code == 200
    assert work_order_response.json()["organization_id"] == 1


def test_default_organization_is_seeded_in_test_database(client):
    with client.app.state.testing_session_local() as db:
        organization = db.scalar(select(Organization).where(Organization.id == 1))
        assert organization is not None
        assert organization.slug == "test"
        assert db.scalar(select(User).where(User.organization_id == 1)) is None
        assert db.scalar(select(Warehouse).where(Warehouse.organization_id == 1)) is None
        assert db.scalar(select(Part).where(Part.organization_id == 1)) is None
        assert db.scalar(select(WorkOrder).where(WorkOrder.organization_id == 1)) is None
