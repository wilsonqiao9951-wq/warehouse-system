from __future__ import annotations

from contextlib import contextmanager

from sqlalchemy import select

from app.core.config import settings
from app.models import UserDevice, WorkOrder, WorkOrderPart


ENGINEER_PASSWORD = "engineer-password"
MANAGER_PASSWORD = "manager-password-1"
DEVICE_TOKEN_A = "a" * 64
DEVICE_TOKEN_A_SECOND = "b" * 64
DEVICE_TOKEN_B = "c" * 64
DEVICE_TOKEN_WAREHOUSE = "d" * 64


def _create_user(client, name: str, role: str, password: str) -> dict:
    response = client.post(
        "/api/users",
        json={
            "name": name,
            "email": f"{name}@claims.test",
            "role": role,
            "password": password,
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def _create_work_order(client, ticket_number: str) -> dict:
    response = client.post(
        "/api/work-orders",
        json={"ticket_number": ticket_number, "status": "open", "problem_description": "No cooling"},
    )
    assert response.status_code == 200, response.text
    return response.json()


def _login(
    client,
    user: dict,
    password: str,
    *,
    device_id: str | None = None,
    device_token: str | None = None,
    device_name: str | None = None,
) -> dict[str, str]:
    login_headers: dict[str, str] = {}
    if device_id is not None:
        assert device_token is not None
        login_headers.update(
            {
                "X-Device-Id": device_id,
                "X-Device-Token": device_token,
                "X-Device-Name": device_name or device_id,
            }
        )
    response = client.post(
        "/api/auth/login",
        data={"username": user["email"], "password": password},
        headers=login_headers,
    )
    assert response.status_code == 200, response.text
    headers = {"Authorization": f"Bearer {response.json()['access_token']}"}
    if device_token is not None:
        headers["X-Device-Token"] = device_token
    return headers


def _claim(client, work_order_id: int, headers: dict[str, str]):
    return client.post(f"/api/work-orders/{work_order_id}/claim", headers=headers)


def _execution_headers(headers: dict[str, str], claim_version: int) -> dict[str, str]:
    return {**headers, "X-Claim-Version": str(claim_version)}


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


def _standard_accounts(client) -> tuple[dict, dict, dict, dict]:
    admin = _create_user(client, "claims-admin", "admin", MANAGER_PASSWORD)
    engineer_a = _create_user(client, "claims-engineer-a", "engineer", ENGINEER_PASSWORD)
    engineer_b = _create_user(client, "claims-engineer-b", "engineer", ENGINEER_PASSWORD)
    warehouse = _create_user(client, "claims-warehouse", "warehouse", MANAGER_PASSWORD)
    return admin, engineer_a, engineer_b, warehouse


def _standard_device_headers(client, engineer_a: dict, engineer_b: dict, warehouse: dict):
    engineer_a_headers = _login(
        client,
        engineer_a,
        ENGINEER_PASSWORD,
        device_id="claims-engineer-a-phone",
        device_token=DEVICE_TOKEN_A,
        device_name="Engineer A phone",
    )
    engineer_b_headers = _login(
        client,
        engineer_b,
        ENGINEER_PASSWORD,
        device_id="claims-engineer-b-phone",
        device_token=DEVICE_TOKEN_B,
        device_name="Engineer B phone",
    )
    warehouse_headers = _login(
        client,
        warehouse,
        MANAGER_PASSWORD,
        device_id="claims-warehouse-phone",
        device_token=DEVICE_TOKEN_WAREHOUSE,
        device_name="Warehouse phone",
    )
    return engineer_a_headers, engineer_b_headers, warehouse_headers


def test_all_engineers_can_read_job_pool_and_claim_conflict_has_one_winner(client):
    _, engineer_a, engineer_b, warehouse = _standard_accounts(client)
    work_order = _create_work_order(client, "CLAIM-POOL-1")

    with _enforced_rbac():
        bearer_without_device = _login(client, engineer_a, ENGINEER_PASSWORD)
        unbound_claim = _claim(client, work_order["id"], bearer_without_device)
        assert unbound_claim.status_code == 401, unbound_claim.text

        engineer_a_headers, engineer_b_headers, _ = _standard_device_headers(
            client, engineer_a, engineer_b, warehouse
        )

        pool_a = client.get("/api/work-orders?scope=all&limit=100", headers=engineer_a_headers)
        pool_b = client.get("/api/work-orders?scope=all&limit=100", headers=engineer_b_headers)
        assert pool_a.status_code == 200, pool_a.text
        assert pool_b.status_code == 200, pool_b.text
        assert work_order["id"] in {item["id"] for item in pool_a.json()}
        assert work_order["id"] in {item["id"] for item in pool_b.json()}

        winner = _claim(client, work_order["id"], engineer_a_headers)
        assert winner.status_code == 200, winner.text
        assert winner.json()["claimed_by_id"] == engineer_a["id"]
        assert winner.json()["claim_version"] == 1
        assert winner.json()["can_edit"] is True

        loser = _claim(client, work_order["id"], engineer_b_headers)
        assert loser.status_code == 409, loser.text

        with client.app.state.testing_session_local() as db:
            stored = db.get(WorkOrder, work_order["id"])
            assert stored is not None
            assert stored.claimed_by_id == engineer_a["id"]
            assert stored.claim_version == 1


def test_only_claiming_account_and_bound_device_can_write(client):
    _, engineer_a, engineer_b, warehouse = _standard_accounts(client)
    work_order = _create_work_order(client, "CLAIM-GUARD-1")

    with _enforced_rbac():
        engineer_a_headers, engineer_b_headers, warehouse_headers = _standard_device_headers(
            client, engineer_a, engineer_b, warehouse
        )
        second_device_headers = _login(
            client,
            engineer_a,
            ENGINEER_PASSWORD,
            device_id="claims-engineer-a-tablet",
            device_token=DEVICE_TOKEN_A_SECOND,
            device_name="Engineer A tablet",
        )
        claimed = _claim(client, work_order["id"], engineer_a_headers)
        assert claimed.status_code == 200, claimed.text
        version = claimed.json()["claim_version"]

        missing_claim_version = client.post(
            f"/api/work-orders/{work_order['id']}/start",
            headers=engineer_a_headers,
            json={},
        )
        assert missing_claim_version.status_code == 428, missing_claim_version.text

        other_engineer = client.post(
            f"/api/work-orders/{work_order['id']}/start",
            headers=_execution_headers(engineer_b_headers, version),
            json={},
        )
        assert other_engineer.status_code == 403, other_engineer.text

        other_device = client.post(
            f"/api/work-orders/{work_order['id']}/start",
            headers=_execution_headers(second_device_headers, version),
            json={},
        )
        assert other_device.status_code == 403, other_device.text

        wrong_device_secret = client.post(
            f"/api/work-orders/{work_order['id']}/start",
            headers={
                **_execution_headers(engineer_a_headers, version),
                "X-Device-Token": "x" * 64,
            },
            json={},
        )
        assert wrong_device_secret.status_code == 401, wrong_device_secret.text

        legacy_claim = client.post(
            f"/api/work-orders/{work_order['id']}/claim",
            headers={"X-User-Id": str(engineer_a["id"])},
        )
        assert legacy_claim.status_code == 401, legacy_claim.text
        legacy_write = client.post(
            f"/api/work-orders/{work_order['id']}/start",
            headers={"X-User-Id": str(engineer_a["id"]), "X-Claim-Version": str(version)},
            json={},
        )
        assert legacy_write.status_code == 401, legacy_write.text

        warehouse_claim = _claim(client, work_order["id"], warehouse_headers)
        assert warehouse_claim.status_code == 403, warehouse_claim.text
        warehouse_write = client.post(
            f"/api/work-orders/{work_order['id']}/start",
            headers=_execution_headers(warehouse_headers, version),
            json={},
        )
        assert warehouse_write.status_code == 403, warehouse_write.text

        owner_write = client.post(
            f"/api/work-orders/{work_order['id']}/start",
            headers=_execution_headers(engineer_a_headers, version),
            json={},
        )
        assert owner_write.status_code == 200, owner_write.text
        assert owner_write.json()["status"] == "IN_PROGRESS"


def test_admin_can_edit_but_manager_cannot_impersonate_field_owner(client):
    admin, engineer_a, engineer_b, warehouse = _standard_accounts(client)
    manager = _create_user(client, "claims-field-manager", "manager", MANAGER_PASSWORD)
    work_order = _create_work_order(client, "CLAIM-ADMIN-EDIT-1")

    with _enforced_rbac():
        admin_headers = _login(client, admin, MANAGER_PASSWORD)
        manager_headers = _login(client, manager, MANAGER_PASSWORD)

        manager_edit = client.patch(
            f"/api/work-orders/{work_order['id']}",
            headers=manager_headers,
            json={"problem_description": "Manager attempted field edit"},
        )
        assert manager_edit.status_code == 403, manager_edit.text

        admin_edit = client.patch(
            f"/api/work-orders/{work_order['id']}",
            headers=admin_headers,
            json={"problem_description": "Administrator correction"},
        )
        assert admin_edit.status_code == 200, admin_edit.text
        assert admin_edit.json()["problem_description"] == "Administrator correction"
        assert admin_edit.json()["can_edit"] is True
        assert admin_edit.json()["can_complete"] is False

        admin_start = client.post(
            f"/api/work-orders/{work_order['id']}/start",
            headers=admin_headers,
            json={},
        )
        assert admin_start.status_code == 200, admin_start.text
        assert admin_start.json()["status"] == "IN_PROGRESS"

        admin_complete = client.post(
            f"/api/work-orders/{work_order['id']}/complete",
            headers=admin_headers,
            json={"account_password": MANAGER_PASSWORD},
        )
        assert admin_complete.status_code == 403, admin_complete.text


def test_completion_requires_current_account_password_and_records_exact_device(client):
    _, engineer_a, engineer_b, warehouse = _standard_accounts(client)
    work_order = _create_work_order(client, "CLAIM-COMPLETE-1")

    with _enforced_rbac():
        engineer_a_headers, _, _ = _standard_device_headers(client, engineer_a, engineer_b, warehouse)
        claimed = _claim(client, work_order["id"], engineer_a_headers)
        assert claimed.status_code == 200, claimed.text
        version = claimed.json()["claim_version"]
        execution_headers = _execution_headers(engineer_a_headers, version)

        missing_password = client.post(
            f"/api/work-orders/{work_order['id']}/complete",
            headers=execution_headers,
            json={"repair_result": "Compressor reset and verified."},
        )
        assert missing_password.status_code == 401, missing_password.text

        wrong_password = client.post(
            f"/api/work-orders/{work_order['id']}/complete",
            headers=execution_headers,
            json={"repair_result": "Compressor reset and verified.", "account_password": "not-the-password"},
        )
        assert wrong_password.status_code == 401, wrong_password.text

        completed = client.post(
            f"/api/work-orders/{work_order['id']}/complete",
            headers=execution_headers,
            json={"repair_result": "Compressor reset and verified.", "account_password": ENGINEER_PASSWORD},
        )
        assert completed.status_code == 200, completed.text
        body = completed.json()
        assert body["status"] == "COMPLETED"
        assert body["completed_by_id"] == engineer_a["id"]
        assert body["completed_device_name"] == "Engineer A phone"

        with client.app.state.testing_session_local() as db:
            stored = db.get(WorkOrder, work_order["id"])
            device = db.scalar(
                select(UserDevice).where(
                    UserDevice.user_id == engineer_a["id"],
                    UserDevice.device_id == "claims-engineer-a-phone",
                )
            )
            assert stored is not None and device is not None
            assert stored.completed_by_id == engineer_a["id"]
            assert stored.completed_device_id == device.id
            assert stored.completed_at is not None
            assert stored.is_locked is True


def test_manager_approval_does_not_replace_engineer_completion_attribution(client):
    admin, engineer_a, engineer_b, warehouse = _standard_accounts(client)
    manager = _create_user(client, "claims-manager", "manager", MANAGER_PASSWORD)
    work_order = _create_work_order(client, "CLAIM-APPROVAL-1")
    policy = client.post(
        "/api/completion-policies",
        json={"require_repair_result": True, "require_manager_approval": True},
    )
    assert policy.status_code == 200, policy.text

    with _enforced_rbac():
        engineer_a_headers, _, _ = _standard_device_headers(client, engineer_a, engineer_b, warehouse)
        manager_headers = _login(client, manager, MANAGER_PASSWORD)
        claimed = _claim(client, work_order["id"], engineer_a_headers)
        assert claimed.status_code == 200, claimed.text
        version = claimed.json()["claim_version"]

        requested = client.post(
            f"/api/work-orders/{work_order['id']}/complete",
            headers=_execution_headers(engineer_a_headers, version),
            json={"repair_result": "Repair verified.", "account_password": ENGINEER_PASSWORD},
        )
        assert requested.status_code == 200, requested.text
        assert requested.json()["status"] == "PENDING_APPROVAL"

        approved = client.post(
            f"/api/work-orders/{work_order['id']}/approve-completion",
            headers=manager_headers,
            json={},
        )
        assert approved.status_code == 200, approved.text
        assert approved.json()["completed_by_id"] == engineer_a["id"]
        assert approved.json()["completion_approved_by"] == manager["id"]

        with client.app.state.testing_session_local() as db:
            stored = db.get(WorkOrder, work_order["id"])
            assert stored is not None
            assert stored.completed_by_id == engineer_a["id"]
            assert stored.completion_approved_by == manager["id"]
            assert stored.completed_by_id != stored.completion_approved_by


def test_part_usage_ignores_spoofed_user_id(client, seed_inventory_ledger):
    _, engineer_a, engineer_b, warehouse_user = _standard_accounts(client)
    work_order = _create_work_order(client, "CLAIM-PART-1")
    warehouse = client.post(
        "/api/warehouses",
        json={"name": "Engineer A Van", "warehouse_type": "van", "assigned_user_id": engineer_a["id"]},
    ).json()
    part = client.post("/api/parts", json={"part_number": "CLAIM-PART", "name": "Claim Test Part"}).json()
    inbound = client.post(
        "/api/inventory/transactions",
        json={
            "part_id": part["id"],
            "transaction_type": "inbound",
            "quantity": 2,
            "to_warehouse_id": warehouse["id"],
        },
    )
    assert inbound.status_code == 409, inbound.text
    seed_inventory_ledger(
        part_id=part["id"],
        quantity=2,
        to_warehouse_id=warehouse["id"],
    )

    with _enforced_rbac():
        engineer_a_headers, _, _ = _standard_device_headers(client, engineer_a, engineer_b, warehouse_user)
        claimed = _claim(client, work_order["id"], engineer_a_headers)
        assert claimed.status_code == 200, claimed.text
        execution_headers = _execution_headers(engineer_a_headers, claimed.json()["claim_version"])

        used = client.post(
            f"/api/work-orders/{work_order['id']}/use-part",
            headers=execution_headers,
            json={
                "work_order_id": work_order["id"],
                "part_id": part["id"],
                "warehouse_id": warehouse["id"],
                "user_id": engineer_b["id"],
                "quantity": 1,
            },
        )
        assert used.status_code == 200, used.text
        assert used.json()["user_id"] == engineer_a["id"]

        deprecated_used = client.post(
            "/api/work-order-parts",
            headers=execution_headers,
            json={
                "work_order_id": work_order["id"],
                "part_id": part["id"],
                "warehouse_id": warehouse["id"],
                "user_id": engineer_b["id"],
                "quantity": 1,
            },
        )
        assert deprecated_used.status_code == 200, deprecated_used.text
        assert deprecated_used.json()["user_id"] == engineer_a["id"]

        engineer_b_headers = _login(
            client,
            engineer_b,
            ENGINEER_PASSWORD,
            device_id="claims-engineer-b-progress-phone",
            device_token="e" * 64,
        )
        visible_progress = client.get(
            f"/api/work-order-parts?work_order_id={work_order['id']}&limit=100",
            headers=engineer_b_headers,
        )
        assert visible_progress.status_code == 200, visible_progress.text
        assert len(visible_progress.json()) == 2
        assert {row["user_id"] for row in visible_progress.json()} == {engineer_a["id"]}

        with client.app.state.testing_session_local() as db:
            stored = db.scalars(
                select(WorkOrderPart).where(WorkOrderPart.work_order_id == work_order["id"])
            ).all()
            assert len(stored) == 2
            assert {usage.user_id for usage in stored} == {engineer_a["id"]}


def test_release_invalidates_old_account_device_and_claim_version(client, seed_inventory_ledger):
    _, engineer_a, engineer_b, warehouse = _standard_accounts(client)
    manager = _create_user(client, "claims-release-manager", "manager", MANAGER_PASSWORD)
    work_order = _create_work_order(client, "CLAIM-RELEASE-1")
    van_a = client.post(
        "/api/warehouses",
        json={"name": "Release Engineer A Van", "assigned_user_id": engineer_a["id"]},
    ).json()
    van_b = client.post(
        "/api/warehouses",
        json={"name": "Release Engineer B Van", "assigned_user_id": engineer_b["id"]},
    ).json()
    part = client.post(
        "/api/parts",
        json={"part_number": "RELEASE-PART", "name": "Release ownership part"},
    ).json()
    seed_inventory_ledger(part_id=part["id"], quantity=2, to_warehouse_id=van_a["id"])
    seed_inventory_ledger(part_id=part["id"], quantity=2, to_warehouse_id=van_b["id"])

    with _enforced_rbac():
        engineer_a_headers, engineer_b_headers, _ = _standard_device_headers(
            client, engineer_a, engineer_b, warehouse
        )
        manager_headers = _login(client, manager, MANAGER_PASSWORD)
        first_claim = _claim(client, work_order["id"], engineer_a_headers)
        assert first_claim.status_code == 200, first_claim.text
        old_version = first_claim.json()["claim_version"]

        released = client.post(
            f"/api/work-orders/{work_order['id']}/release",
            headers=manager_headers,
            json={"reason": "Dispatch reassignment"},
        )
        assert released.status_code == 200, released.text
        assert released.json()["claimed_by_id"] is None
        assert released.json()["claim_version"] > old_version

        stale_write = client.post(
            f"/api/work-orders/{work_order['id']}/start",
            headers=_execution_headers(engineer_a_headers, old_version),
            json={},
        )
        assert stale_write.status_code in {403, 409}, stale_write.text

        second_claim = _claim(client, work_order["id"], engineer_b_headers)
        assert second_claim.status_code == 200, second_claim.text
        assert second_claim.json()["claimed_by_id"] == engineer_b["id"]
        assert second_claim.json()["claim_version"] > released.json()["claim_version"]

        old_owner_write = client.patch(
            f"/api/work-orders/{work_order['id']}",
            headers=_execution_headers(engineer_a_headers, old_version),
            json={"problem_description": "Unauthorized stale edit"},
        )
        assert old_owner_write.status_code in {403, 409}, old_owner_write.text

        stale_part_use = client.post(
            f"/api/work-orders/{work_order['id']}/use-part",
            headers=_execution_headers(engineer_a_headers, old_version),
            json={
                "work_order_id": work_order["id"],
                "part_id": part["id"],
                "warehouse_id": van_a["id"],
                "quantity": 1,
            },
        )
        assert stale_part_use.status_code in {403, 409}, stale_part_use.text

        current_owner_write = client.patch(
            f"/api/work-orders/{work_order['id']}",
            headers=_execution_headers(engineer_b_headers, second_claim.json()["claim_version"]),
            json={"problem_description": "Authorized edit"},
        )
        assert current_owner_write.status_code == 200, current_owner_write.text
        assert current_owner_write.json()["problem_description"] == "Authorized edit"

        current_part_use = client.post(
            f"/api/work-orders/{work_order['id']}/use-part",
            headers=_execution_headers(engineer_b_headers, second_claim.json()["claim_version"]),
            json={
                "work_order_id": work_order["id"],
                "part_id": part["id"],
                "warehouse_id": van_b["id"],
                "quantity": 1,
            },
        )
        assert current_part_use.status_code == 200, current_part_use.text
        assert current_part_use.json()["user_id"] == engineer_b["id"]
