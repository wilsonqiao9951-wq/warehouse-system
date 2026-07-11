from sqlalchemy import select

from app.core.config import settings
from app.core.database import Base
from app.core.rbac import TENANT_MODELS
from app.models import Organization, Part, User, UserRole, Warehouse, WorkOrder


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


def test_core_api_isolates_organizations(client):
    settings.rbac_enforce = False
    try:
        first_admin = client.post(
            "/api/users",
            json={"name": "First Admin", "email": "first-admin@example.com", "role": "admin"},
        ).json()
        first_part = client.post(
            "/api/parts",
            json={"part_number": "ORG1-PART", "name": "Organization One Part"},
        ).json()
        first_work_order = client.post(
            "/api/work-orders",
            json={"ticket_number": "ORG1-WO", "assigned_user_id": first_admin["id"]},
        ).json()
        first_customer = client.post(
            "/api/customers", json={"name": "Organization One Customer", "account_number": "ORG1-CUSTOMER"}
        ).json()

        with client.app.state.testing_session_local() as db:
            second_organization = Organization(id=2, name="Second Organization", slug="second")
            second_manager = User(
                organization_id=2,
                name="Second Manager",
                email="second-manager@example.com",
                role=UserRole.MANAGER,
            )
            db.add_all([second_organization, second_manager])
            db.commit()
            second_manager_id = second_manager.id

        settings.rbac_enforce = True
        second_headers = {"X-User-Id": str(second_manager_id)}

        second_part_response = client.post(
            "/api/parts",
            headers=second_headers,
            json={"part_number": "ORG2-PART", "name": "Organization Two Part"},
        )
        assert second_part_response.status_code == 200
        assert second_part_response.json()["organization_id"] == 2

        listed_parts = client.get("/api/parts", headers=second_headers)
        assert listed_parts.status_code == 200
        assert [part["part_number"] for part in listed_parts.json()] == ["ORG2-PART"]
        assert first_part["part_number"] not in {part["part_number"] for part in listed_parts.json()}

        listed_work_orders = client.get("/api/work-orders", headers=second_headers)
        assert listed_work_orders.status_code == 200
        assert listed_work_orders.json() == []

        cross_org_start = client.post(
            f"/api/work-orders/{first_work_order['id']}/start",
            headers=second_headers,
            json={},
        )
        assert cross_org_start.status_code == 404

        cross_org_assignment = client.post(
            "/api/work-orders",
            headers=second_headers,
            json={"ticket_number": "ORG2-BAD-WO", "assigned_user_id": first_admin["id"]},
        )
        assert cross_org_assignment.status_code == 400

        cross_org_customer = client.post(
            "/api/work-orders",
            headers=second_headers,
            json={"ticket_number": "ORG2-BAD-CUSTOMER", "customer_id": first_customer["id"]},
        )
        assert cross_org_customer.status_code == 400

        cross_org_context = client.get(
            f"/api/work-orders/{first_work_order['id']}/service-context", headers=second_headers
        )
        assert cross_org_context.status_code == 404
    finally:
        settings.rbac_enforce = False
def test_all_tenant_models_are_registered_for_automatic_scope():
    missing = [
        mapper.class_.__name__
        for mapper in Base.registry.mappers
        if hasattr(mapper.class_, "organization_id") and mapper.class_ not in TENANT_MODELS
    ]
    assert missing == []
