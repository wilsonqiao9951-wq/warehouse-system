from __future__ import annotations

from contextlib import contextmanager
import json

from sqlalchemy import select

from app.core.config import settings
from app.core.security import hash_password
from app.models import (
    AuditLog,
    InventoryNotification,
    InventoryTransaction,
    Organization,
    Part,
    ReplenishmentRequest,
    User,
    UserDevice,
    UserRole,
    Warehouse,
    WorkOrderPart,
)


ENGINEER_PASSWORD = "engineer-custody-password"
STAFF_PASSWORD = "warehouse-custody-password"
DEVICE_TOKEN_A = "a" * 64
DEVICE_TOKEN_B = "b" * 64
DEVICE_TOKEN_WAREHOUSE = "c" * 64
DEVICE_TOKEN_ADMIN = "d" * 64
DEVICE_TOKEN_MANAGER = "e" * 64


@contextmanager
def _enforced_rbac():
    original_rbac = settings.rbac_enforce
    original_legacy = settings.legacy_header_auth
    settings.rbac_enforce = True
    settings.legacy_header_auth = False
    try:
        yield
    finally:
        settings.rbac_enforce = original_rbac
        settings.legacy_header_auth = original_legacy


def _create_user(client, name: str, role: str, password: str) -> dict:
    response = client.post(
        "/api/users",
        json={
            "name": name,
            "email": f"{name}@custody.test",
            "role": role,
            "password": password,
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def _create_warehouse(
    client,
    code: str,
    *,
    warehouse_type: str = "main",
    assigned_user_id: int | None = None,
) -> dict:
    response = client.post(
        "/api/warehouses",
        json={
            "code": code,
            "name": f"{code} warehouse",
            "warehouse_type": warehouse_type,
            "assigned_user_id": assigned_user_id,
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def _create_part(client, part_number: str = "CUSTODY-PART") -> dict:
    response = client.post(
        "/api/parts",
        json={
            "part_number": part_number,
            "name": f"{part_number} name",
            "default_cost": 7.5,
            "safety_stock": 0,
            "min_stock": 0,
        },
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
) -> dict[str, str]:
    login_headers: dict[str, str] = {}
    if device_id is not None:
        assert device_token is not None
        login_headers = {
            "X-Device-Id": device_id,
            "X-Device-Token": device_token,
            "X-Device-Name": device_id,
        }
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


def _create_notification(client, part_id: int, warehouse_id: int, *, work_order_id: int | None = None) -> int:
    with client.app.state.testing_session_local() as db:
        item = InventoryNotification(
            organization_id=1,
            part_id=part_id,
            warehouse_id=warehouse_id,
            work_order_id=work_order_id,
            message="Van stock needs replenishment",
        )
        db.add(item)
        db.commit()
        db.refresh(item)
        return item.id


def _seed_stock(client, part_id: int, warehouse_id: int, quantity: int) -> dict:
    response = client.post(
        "/api/inventory/transactions",
        json={
            "part_id": part_id,
            "transaction_type": "inbound",
            "quantity": quantity,
            "to_warehouse_id": warehouse_id,
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def _create_request(
    client,
    notification_id: int,
    headers: dict[str, str],
    *,
    quantity: int,
    source_warehouse_id: int | None = None,
) -> dict:
    suffix = f"?quantity={quantity}"
    if source_warehouse_id is not None:
        suffix += f"&source_warehouse_id={source_warehouse_id}"
    response = client.post(
        f"/api/inventory/notifications/{notification_id}/create-request{suffix}",
        headers=headers,
    )
    assert response.status_code == 200, response.text
    return response.json()


def _manual_request(
    client,
    headers: dict[str, str],
    *,
    part_id: int,
    destination_warehouse_id: int,
    quantity: int,
    reason: str,
    client_request_id: str,
    source_warehouse_id: int | None = None,
):
    payload: dict[str, object] = {
        "part_id": part_id,
        "destination_warehouse_id": destination_warehouse_id,
        "quantity": quantity,
        "reason": reason,
        "client_request_id": client_request_id,
    }
    if source_warehouse_id is not None:
        payload["source_warehouse_id"] = source_warehouse_id
    return client.post(
        "/api/inventory/replenishment-requests",
        headers=headers,
        json=payload,
    )


def _action(
    client,
    request_id: int,
    headers: dict[str, str],
    action: str,
    expected_version: int,
    *,
    source_warehouse_id: int | None = None,
    reason: str | None = None,
    account_password: str | None = None,
):
    if action == "start_picking":
        approval_login = client.post(
            "/api/auth/login",
            data={"username": "custody-manager@custody.test", "password": STAFF_PASSWORD},
        )
        if approval_login.status_code == 200:
            approval = client.post(
                f"/api/inventory/replenishment-requests/{request_id}/actions",
                headers={"Authorization": f"Bearer {approval_login.json()['access_token']}"},
                json={"action": "approve", "expected_version": expected_version},
            )
            if approval.status_code != 200:
                return approval
    payload: dict[str, object] = {
        "action": action,
        "expected_version": expected_version,
    }
    if source_warehouse_id is not None:
        payload["source_warehouse_id"] = source_warehouse_id
    if reason is not None:
        payload["reason"] = reason
    if account_password is not None:
        payload["account_password"] = account_password
    return client.post(
        f"/api/inventory/replenishment-requests/{request_id}/actions",
        headers=headers,
        json=payload,
    )


def _balance(client, headers: dict[str, str], part_id: int, warehouse_id: int) -> int:
    response = client.get("/api/inventory/balances?limit=100", headers=headers)
    assert response.status_code == 200, response.text
    return next(
        row["quantity"]
        for row in response.json()
        if row["part_id"] == part_id and row["warehouse_id"] == warehouse_id
    )


def _standard_setup(client, *, source_quantity: int = 10) -> dict:
    admin = _create_user(client, "custody-admin", "admin", STAFF_PASSWORD)
    warehouse_user = _create_user(client, "custody-warehouse", "warehouse", STAFF_PASSWORD)
    manager = _create_user(client, "custody-manager", "manager", STAFF_PASSWORD)
    engineer_a = _create_user(client, "custody-engineer-a", "engineer", ENGINEER_PASSWORD)
    engineer_b = _create_user(client, "custody-engineer-b", "engineer", ENGINEER_PASSWORD)
    source = _create_warehouse(client, "CUSTODY-MAIN")
    van_a = _create_warehouse(
        client,
        "CUSTODY-VAN-A",
        warehouse_type="van",
        assigned_user_id=engineer_a["id"],
    )
    van_b = _create_warehouse(
        client,
        "CUSTODY-VAN-B",
        warehouse_type="van",
        assigned_user_id=engineer_b["id"],
    )
    part = _create_part(client)
    if source_quantity:
        _seed_stock(client, part["id"], source["id"], source_quantity)
    return {
        "admin": admin,
        "warehouse_user": warehouse_user,
        "manager": manager,
        "engineer_a": engineer_a,
        "engineer_b": engineer_b,
        "source": source,
        "van_a": van_a,
        "van_b": van_b,
        "part": part,
    }


def _headers(client, setup: dict) -> dict[str, dict[str, str]]:
    return {
        "admin": _login(
            client,
            setup["admin"],
            STAFF_PASSWORD,
            device_id="custody-admin-device",
            device_token=DEVICE_TOKEN_ADMIN,
        ),
        "warehouse": _login(
            client,
            setup["warehouse_user"],
            STAFF_PASSWORD,
            device_id="custody-warehouse-device",
            device_token=DEVICE_TOKEN_WAREHOUSE,
        ),
        "manager": _login(
            client,
            setup["manager"],
            STAFF_PASSWORD,
            device_id="custody-manager-device",
            device_token=DEVICE_TOKEN_MANAGER,
        ),
        "engineer_a": _login(
            client,
            setup["engineer_a"],
            ENGINEER_PASSWORD,
            device_id="custody-engineer-a-phone",
            device_token=DEVICE_TOKEN_A,
        ),
        "engineer_b": _login(
            client,
            setup["engineer_b"],
            ENGINEER_PASSWORD,
            device_id="custody-engineer-b-phone",
            device_token=DEVICE_TOKEN_B,
        ),
    }


def test_replenishment_full_custody_chain_moves_stock_once_and_audits_every_actor(client):
    setup = _standard_setup(client)
    notification_id = _create_notification(client, setup["part"]["id"], setup["van_a"]["id"])

    with _enforced_rbac():
        headers = _headers(client, setup)
        item = _create_request(
            client,
            notification_id,
            headers["warehouse"],
            quantity=4,
            source_warehouse_id=setup["source"]["id"],
        )
        assert (item["status"], item["version"], item["target_user_id"]) == (
            "requested",
            0,
            setup["engineer_a"]["id"],
        )
        assert _balance(client, headers["warehouse"], setup["part"]["id"], setup["source"]["id"]) == 10
        assert _balance(client, headers["warehouse"], setup["part"]["id"], setup["van_a"]["id"]) == 0

        picked = _action(
            client,
            item["id"],
            headers["warehouse"],
            "start_picking",
            0,
            source_warehouse_id=setup["source"]["id"],
        )
        assert picked.status_code == 200, picked.text
        assert (picked.json()["status"], picked.json()["version"]) == ("picking", 1)
        assert picked.json()["source_available_quantity"] == 6
        assert _balance(client, headers["warehouse"], setup["part"]["id"], setup["source"]["id"]) == 10

        shipped = _action(client, item["id"], headers["warehouse"], "ship", 1)
        assert shipped.status_code == 200, shipped.text
        assert (shipped.json()["status"], shipped.json()["version"]) == ("shipped", 2)
        assert shipped.json()["shipment_transaction_id"] is not None
        assert _balance(client, headers["warehouse"], setup["part"]["id"], setup["source"]["id"]) == 6
        assert _balance(client, headers["warehouse"], setup["part"]["id"], setup["van_a"]["id"]) == 0

        received = _action(
            client,
            item["id"],
            headers["engineer_a"],
            "receive",
            2,
            account_password=ENGINEER_PASSWORD,
        )
        assert received.status_code == 200, received.text
        assert (received.json()["status"], received.json()["version"]) == ("received", 3)
        assert received.json()["received_by"] == setup["engineer_a"]["id"]
        assert received.json()["received_device_id"] is not None
        assert received.json()["receipt_transaction_id"] is not None
        assert _balance(client, headers["warehouse"], setup["part"]["id"], setup["source"]["id"]) == 6
        assert _balance(client, headers["warehouse"], setup["part"]["id"], setup["van_a"]["id"]) == 4

        van_inventory = client.get("/api/inventory/my-van", headers=headers["engineer_a"])
        assert van_inventory.status_code == 200, van_inventory.text
        van_row = next(row for row in van_inventory.json() if row["part_id"] == setup["part"]["id"])
        assert (van_row["warehouse_id"], van_row["quantity"]) == (setup["van_a"]["id"], 4)

        completed = _action(client, item["id"], headers["warehouse"], "complete", 3)
        assert completed.status_code == 200, completed.text
        assert (completed.json()["status"], completed.json()["version"]) == ("completed", 4)
        assert completed.json()["completed_by"] == setup["warehouse_user"]["id"]
        assert _balance(client, headers["warehouse"], setup["part"]["id"], setup["source"]["id"]) == 6
        assert _balance(client, headers["warehouse"], setup["part"]["id"], setup["van_a"]["id"]) == 4

    with client.app.state.testing_session_local() as db:
        transactions = db.scalars(
            select(InventoryTransaction)
            .where(InventoryTransaction.replenishment_request_id == item["id"])
            .order_by(InventoryTransaction.id)
        ).all()
        assert [(row.movement_stage, row.quantity) for row in transactions] == [("ship", 4), ("receive", 4)]
        assert transactions[0].user_id == setup["warehouse_user"]["id"]
        assert transactions[1].user_id == setup["engineer_a"]["id"]

        device = db.scalar(
            select(UserDevice).where(
                UserDevice.user_id == setup["engineer_a"]["id"],
                UserDevice.device_id == "custody-engineer-a-phone",
            )
        )
        stored = db.get(ReplenishmentRequest, item["id"])
        assert stored is not None and device is not None
        assert stored.received_device_id == device.id
        assert db.get(InventoryNotification, notification_id).status == "resolved"

        audits = db.scalars(
            select(AuditLog)
            .where(AuditLog.entity_type == "replenishment_request", AuditLog.entity_id == item["id"])
            .order_by(AuditLog.id)
        ).all()
        assert [row.action for row in audits] == [
            "replenishment_requested",
            "replenishment_approve",
            "replenishment_start_picking",
            "replenishment_ship",
            "replenishment_receive",
            "replenishment_complete",
        ]
        assert [row.user_id for row in audits] == [
            setup["warehouse_user"]["id"],
            setup["manager"]["id"],
            setup["warehouse_user"]["id"],
            setup["warehouse_user"]["id"],
            setup["engineer_a"]["id"],
            setup["warehouse_user"]["id"],
        ]
        receive_metadata = json.loads(audits[4].metadata_json)
        assert receive_metadata["from_status"] == "shipped"
        assert receive_metadata["to_status"] == "received"
        assert receive_metadata["inventory_transaction_id"] == stored.receipt_transaction_id


def test_replenishment_rejects_illegal_transitions_and_stale_versions_without_side_effects(client):
    setup = _standard_setup(client)
    notification_id = _create_notification(client, setup["part"]["id"], setup["van_a"]["id"])

    with _enforced_rbac():
        headers = _headers(client, setup)
        item = _create_request(
            client,
            notification_id,
            headers["warehouse"],
            quantity=3,
            source_warehouse_id=setup["source"]["id"],
        )
        assert _action(client, item["id"], headers["warehouse"], "ship", 0).status_code == 409
        assert _action(
            client,
            item["id"],
            headers["engineer_a"],
            "receive",
            0,
            account_password=ENGINEER_PASSWORD,
        ).status_code == 409
        assert _action(client, item["id"], headers["warehouse"], "complete", 0).status_code == 409
        assert _action(
            client,
            item["id"],
            headers["warehouse"],
            "start_picking",
            99,
            source_warehouse_id=setup["source"]["id"],
        ).status_code == 409

        picked = _action(
            client,
            item["id"],
            headers["warehouse"],
            "start_picking",
            0,
            source_warehouse_id=setup["source"]["id"],
        )
        assert picked.status_code == 200, picked.text
        assert _action(client, item["id"], headers["warehouse"], "ship", 0).status_code == 409
        assert _action(
            client,
            item["id"],
            headers["engineer_a"],
            "receive",
            1,
            account_password=ENGINEER_PASSWORD,
        ).status_code == 409
        assert _action(client, item["id"], headers["warehouse"], "complete", 1).status_code == 409

        shipped = _action(client, item["id"], headers["warehouse"], "ship", 1)
        assert shipped.status_code == 200, shipped.text
        assert _action(
            client,
            item["id"],
            headers["warehouse"],
            "start_picking",
            2,
            source_warehouse_id=setup["source"]["id"],
        ).status_code == 409
        assert _action(
            client,
            item["id"],
            headers["warehouse"],
            "cancel",
            2,
            reason="Too late to cancel",
        ).status_code == 409
        assert _action(client, item["id"], headers["warehouse"], "complete", 2).status_code == 409

        listed = client.get("/api/inventory/replenishment-requests", headers=headers["warehouse"])
        assert listed.status_code == 200, listed.text
        current = next(row for row in listed.json() if row["id"] == item["id"])
        assert (current["status"], current["version"]) == ("shipped", 2)

    with client.app.state.testing_session_local() as db:
        transactions = db.scalars(
            select(InventoryTransaction).where(InventoryTransaction.replenishment_request_id == item["id"])
        ).all()
        assert [(row.movement_stage, row.quantity) for row in transactions] == [("ship", 3)]
        action_audits = db.scalars(
            select(AuditLog).where(
                AuditLog.entity_type == "replenishment_request",
                AuditLog.entity_id == item["id"],
            )
        ).all()
        assert {row.action for row in action_audits} == {
            "replenishment_requested",
            "replenishment_approve",
            "replenishment_start_picking",
            "replenishment_ship",
        }


def test_vehicle_receipt_requires_target_engineer_registered_device_and_password(client):
    setup = _standard_setup(client)
    notification_id = _create_notification(client, setup["part"]["id"], setup["van_a"]["id"])

    with _enforced_rbac():
        headers = _headers(client, setup)
        unbound_engineer_headers = _login(client, setup["engineer_a"], ENGINEER_PASSWORD)
        item = _create_request(
            client,
            notification_id,
            headers["warehouse"],
            quantity=2,
            source_warehouse_id=setup["source"]["id"],
        )

        assert _action(
            client,
            item["id"],
            headers["engineer_a"],
            "start_picking",
            0,
            source_warehouse_id=setup["source"]["id"],
        ).status_code == 403
        assert _action(
            client,
            item["id"],
            headers["manager"],
            "start_picking",
            0,
            source_warehouse_id=setup["source"]["id"],
        ).status_code == 403

        picked = _action(
            client,
            item["id"],
            headers["admin"],
            "start_picking",
            0,
            source_warehouse_id=setup["source"]["id"],
        )
        assert picked.status_code == 200, picked.text
        assert _action(client, item["id"], headers["engineer_a"], "ship", 1).status_code == 403
        assert _action(client, item["id"], headers["manager"], "ship", 1).status_code == 403
        shipped = _action(client, item["id"], headers["warehouse"], "ship", 1)
        assert shipped.status_code == 200, shipped.text

        for forbidden_headers in (
            headers["engineer_b"],
            headers["warehouse"],
            headers["admin"],
            headers["manager"],
        ):
            response = _action(
                client,
                item["id"],
                forbidden_headers,
                "receive",
                2,
                account_password=ENGINEER_PASSWORD,
            )
            assert response.status_code == 403, response.text

        missing_device = _action(
            client,
            item["id"],
            unbound_engineer_headers,
            "receive",
            2,
            account_password=ENGINEER_PASSWORD,
        )
        assert missing_device.status_code == 401, missing_device.text

        wrong_device_secret = _action(
            client,
            item["id"],
            {**headers["engineer_a"], "X-Device-Token": "z" * 64},
            "receive",
            2,
            account_password=ENGINEER_PASSWORD,
        )
        assert wrong_device_secret.status_code == 401, wrong_device_secret.text

        wrong_password = _action(
            client,
            item["id"],
            headers["engineer_a"],
            "receive",
            2,
            account_password="incorrect-password",
        )
        assert wrong_password.status_code == 401, wrong_password.text

        received = _action(
            client,
            item["id"],
            headers["engineer_a"],
            "receive",
            2,
            account_password=ENGINEER_PASSWORD,
        )
        assert received.status_code == 200, received.text
        assert _action(client, item["id"], headers["manager"], "complete", 3).status_code == 403
        assert _action(client, item["id"], headers["engineer_a"], "complete", 3).status_code == 403

        completed = _action(client, item["id"], headers["admin"], "complete", 3)
        assert completed.status_code == 200, completed.text
        assert completed.json()["completed_by"] == setup["admin"]["id"]


def test_replenishment_action_retries_are_idempotent_and_do_not_duplicate_ledger_entries(client):
    setup = _standard_setup(client)
    notification_id = _create_notification(client, setup["part"]["id"], setup["van_a"]["id"])

    with _enforced_rbac():
        headers = _headers(client, setup)
        item = _create_request(
            client,
            notification_id,
            headers["warehouse"],
            quantity=5,
            source_warehouse_id=setup["source"]["id"],
        )
        pick_payload = dict(source_warehouse_id=setup["source"]["id"])
        first_pick = _action(client, item["id"], headers["warehouse"], "start_picking", 0, **pick_payload)
        retry_pick = _action(client, item["id"], headers["warehouse"], "start_picking", 0, **pick_payload)
        assert first_pick.status_code == retry_pick.status_code == 200
        assert first_pick.json()["version"] == retry_pick.json()["version"] == 1

        first_ship = _action(client, item["id"], headers["warehouse"], "ship", 1)
        retry_ship = _action(client, item["id"], headers["warehouse"], "ship", 1)
        assert first_ship.status_code == retry_ship.status_code == 200
        assert first_ship.json()["shipment_transaction_id"] == retry_ship.json()["shipment_transaction_id"]
        assert first_ship.json()["version"] == retry_ship.json()["version"] == 2

        first_receive = _action(
            client,
            item["id"],
            headers["engineer_a"],
            "receive",
            2,
            account_password=ENGINEER_PASSWORD,
        )
        retry_receive = _action(
            client,
            item["id"],
            headers["engineer_a"],
            "receive",
            2,
            account_password=ENGINEER_PASSWORD,
        )
        assert first_receive.status_code == retry_receive.status_code == 200
        assert first_receive.json()["receipt_transaction_id"] == retry_receive.json()["receipt_transaction_id"]
        assert first_receive.json()["version"] == retry_receive.json()["version"] == 3

        first_complete = _action(client, item["id"], headers["warehouse"], "complete", 3)
        retry_complete = _action(client, item["id"], headers["warehouse"], "complete", 3)
        assert first_complete.status_code == retry_complete.status_code == 200
        assert first_complete.json()["version"] == retry_complete.json()["version"] == 4
        assert _balance(client, headers["warehouse"], setup["part"]["id"], setup["source"]["id"]) == 5
        assert _balance(client, headers["warehouse"], setup["part"]["id"], setup["van_a"]["id"]) == 5

    with client.app.state.testing_session_local() as db:
        rows = db.scalars(
            select(InventoryTransaction)
            .where(InventoryTransaction.replenishment_request_id == item["id"])
            .order_by(InventoryTransaction.id)
        ).all()
        assert [row.movement_stage for row in rows] == ["ship", "receive"]
        audits = db.scalars(
            select(AuditLog).where(
                AuditLog.entity_type == "replenishment_request",
                AuditLog.entity_id == item["id"],
            )
        ).all()
        assert len(audits) == 6


def test_replenishment_requires_independent_approval_and_records_rejection(client):
    setup = _standard_setup(client)
    first_notification = _create_notification(client, setup["part"]["id"], setup["van_a"]["id"])
    second_notification = _create_notification(client, setup["part"]["id"], setup["van_b"]["id"])
    with _enforced_rbac():
        headers = _headers(client, setup)
        item = _create_request(client, first_notification, headers["warehouse"], quantity=2,
                               source_warehouse_id=setup["source"]["id"])
        assert item["approval_status"] == "pending"
        direct_pick = client.post(
            f"/api/inventory/replenishment-requests/{item['id']}/actions",
            headers=headers["warehouse"],
            json={"action": "start_picking", "expected_version": 0,
                  "source_warehouse_id": setup["source"]["id"]},
        )
        assert direct_pick.status_code == 409
        assert _action(client, item["id"], headers["warehouse"], "approve", 0).status_code == 403
        approved = _action(client, item["id"], headers["manager"], "approve", 0)
        assert approved.status_code == 200, approved.text
        assert approved.json()["approval_status"] == "approved"
        assert approved.json()["approved_by"] == setup["manager"]["id"]
        assert approved.json()["can_start_picking"] is False
        warehouse_view = client.get("/api/inventory/replenishment-requests", headers=headers["warehouse"]).json()
        assert next(row for row in warehouse_view if row["id"] == item["id"])["can_start_picking"] is True

        rejected_item = _create_request(client, second_notification, headers["warehouse"], quantity=1,
                                        source_warehouse_id=setup["source"]["id"])
        missing_reason = _action(client, rejected_item["id"], headers["admin"], "reject", 0)
        assert missing_reason.status_code == 422
        rejected = _action(client, rejected_item["id"], headers["admin"], "reject", 0,
                           reason="Duplicate replenishment request")
        assert rejected.status_code == 200, rejected.text
        assert rejected.json()["status"] == "rejected"
        assert rejected.json()["approval_status"] == "rejected"
        assert rejected.json()["rejection_reason"] == "Duplicate replenishment request"
        assert rejected.json()["rejected_by"] == setup["admin"]["id"]
        assert _action(client, rejected_item["id"], headers["manager"], "approve", 1).status_code == 409

    with client.app.state.testing_session_local() as db:
        actions = {row.action for row in db.scalars(select(AuditLog).where(
            AuditLog.entity_type == "replenishment_request",
            AuditLog.entity_id == rejected_item["id"],
        )).all()}
        assert actions == {"replenishment_requested", "replenishment_reject"}


def test_same_notification_creates_only_one_replenishment_request(client):
    setup = _standard_setup(client)
    notification_id = _create_notification(client, setup["part"]["id"], setup["van_a"]["id"])

    with _enforced_rbac():
        headers = _headers(client, setup)
        first = _create_request(
            client,
            notification_id,
            headers["warehouse"],
            quantity=3,
            source_warehouse_id=setup["source"]["id"],
        )
        repeated = _create_request(
            client,
            notification_id,
            headers["admin"],
            quantity=8,
            source_warehouse_id=setup["van_b"]["id"],
        )
        assert repeated["id"] == first["id"]
        assert repeated["quantity"] == 3
        assert repeated["source_warehouse_id"] == setup["source"]["id"]

    with client.app.state.testing_session_local() as db:
        requests = db.scalars(
            select(ReplenishmentRequest).where(ReplenishmentRequest.notification_id == notification_id)
        ).all()
        assert len(requests) == 1
        audits = db.scalars(
            select(AuditLog).where(
                AuditLog.action == "replenishment_requested",
                AuditLog.entity_id == first["id"],
            )
        ).all()
        assert len(audits) == 1
        assert db.get(InventoryNotification, notification_id).status == "acknowledged"


def test_cancellation_releases_reserved_stock_for_competing_request(client):
    setup = _standard_setup(client, source_quantity=5)
    first_notification = _create_notification(client, setup["part"]["id"], setup["van_a"]["id"])
    second_notification = _create_notification(client, setup["part"]["id"], setup["van_a"]["id"])

    with _enforced_rbac():
        headers = _headers(client, setup)
        first = _create_request(
            client,
            first_notification,
            headers["warehouse"],
            quantity=4,
            source_warehouse_id=setup["source"]["id"],
        )
        second = _create_request(
            client,
            second_notification,
            headers["warehouse"],
            quantity=4,
            source_warehouse_id=setup["source"]["id"],
        )

        first_pick = _action(
            client,
            first["id"],
            headers["warehouse"],
            "start_picking",
            0,
            source_warehouse_id=setup["source"]["id"],
        )
        assert first_pick.status_code == 200, first_pick.text
        assert first_pick.json()["source_available_quantity"] == 1

        competing_pick = _action(
            client,
            second["id"],
            headers["warehouse"],
            "start_picking",
            0,
            source_warehouse_id=setup["source"]["id"],
        )
        assert competing_pick.status_code == 409, competing_pick.text

        short_reason = _action(
            client,
            first["id"],
            headers["warehouse"],
            "cancel",
            1,
            reason="x",
        )
        assert short_reason.status_code == 422, short_reason.text
        cancelled = _action(
            client,
            first["id"],
            headers["warehouse"],
            "cancel",
            1,
            reason="Reassigned available stock",
        )
        assert cancelled.status_code == 200, cancelled.text
        assert (cancelled.json()["status"], cancelled.json()["version"]) == ("cancelled", 2)
        repeated_cancelled_request = _create_request(
            client,
            first_notification,
            headers["warehouse"],
            quantity=4,
            source_warehouse_id=setup["source"]["id"],
        )
        assert repeated_cancelled_request["id"] == first["id"]
        assert repeated_cancelled_request["status"] == "cancelled"

        second_pick = _action(
            client,
            second["id"],
            headers["warehouse"],
            "start_picking",
            0,
            source_warehouse_id=setup["source"]["id"],
        )
        assert second_pick.status_code == 200, second_pick.text
        assert second_pick.json()["source_available_quantity"] == 1
        assert _balance(client, headers["warehouse"], setup["part"]["id"], setup["source"]["id"]) == 5

    with client.app.state.testing_session_local() as db:
        assert db.get(InventoryNotification, first_notification).status == "resolved"
        assert len(db.scalars(
            select(ReplenishmentRequest).where(ReplenishmentRequest.notification_id == first_notification)
        ).all()) == 1
        transactions = db.scalars(
            select(InventoryTransaction).where(
                InventoryTransaction.replenishment_request_id.in_([first["id"], second["id"]])
            )
        ).all()
        assert transactions == []


def test_manual_vehicle_replenishment_is_validated_and_client_request_id_is_idempotent(client):
    setup = _standard_setup(client)
    alternate_source = _create_warehouse(client, "CUSTODY-ALTERNATE-SOURCE")

    with _enforced_rbac():
        headers = _headers(client, setup)
        created = _manual_request(
            client,
            headers["warehouse"],
            part_id=setup["part"]["id"],
            destination_warehouse_id=setup["van_a"]["id"],
            source_warehouse_id=setup["source"]["id"],
            quantity=3,
            reason="  Initialize engineer van stock  ",
            client_request_id="manual-van-init-001",
        )
        assert created.status_code == 200, created.text
        body = created.json()
        assert body["notification_id"] is None
        assert body["client_request_id"] == "manual-van-init-001"
        assert body["request_reason"] == "Initialize engineer van stock"
        assert body["target_user_id"] == setup["engineer_a"]["id"]
        assert (body["status"], body["version"]) == ("requested", 0)

        repeated = _manual_request(
            client,
            headers["admin"],
            part_id=setup["part"]["id"],
            destination_warehouse_id=setup["van_a"]["id"],
            source_warehouse_id=setup["source"]["id"],
            quantity=3,
            reason="  Initialize engineer van stock  ",
            client_request_id="manual-van-init-001",
        )
        assert repeated.status_code == 200, repeated.text
        assert repeated.json()["id"] == body["id"]

        conflicting_retry = _manual_request(
            client,
            headers["warehouse"],
            part_id=setup["part"]["id"],
            destination_warehouse_id=setup["van_a"]["id"],
            source_warehouse_id=setup["source"]["id"],
            quantity=4,
            reason="Initialize engineer van stock",
            client_request_id="manual-van-init-001",
        )
        assert conflicting_retry.status_code == 409, conflicting_retry.text
        source_replacement = _action(
            client,
            body["id"],
            headers["warehouse"],
            "start_picking",
            0,
            source_warehouse_id=alternate_source["id"],
        )
        assert source_replacement.status_code == 409, source_replacement.text

        main_destination = _manual_request(
            client,
            headers["warehouse"],
            part_id=setup["part"]["id"],
            destination_warehouse_id=setup["source"]["id"],
            quantity=1,
            reason="Invalid main destination",
            client_request_id="manual-main-dest-001",
        )
        assert main_destination.status_code == 422, main_destination.text

        vehicle_source = _manual_request(
            client,
            headers["warehouse"],
            part_id=setup["part"]["id"],
            destination_warehouse_id=setup["van_a"]["id"],
            source_warehouse_id=setup["van_b"]["id"],
            quantity=1,
            reason="Invalid vehicle source",
            client_request_id="manual-van-source-001",
        )
        assert vehicle_source.status_code == 409, vehicle_source.text

        blank_reason = _manual_request(
            client,
            headers["warehouse"],
            part_id=setup["part"]["id"],
            destination_warehouse_id=setup["van_a"]["id"],
            quantity=1,
            reason="   ",
            client_request_id="manual-blank-reason-001",
        )
        assert blank_reason.status_code == 422, blank_reason.text

    with client.app.state.testing_session_local() as db:
        rows = db.scalars(
            select(ReplenishmentRequest).where(
                ReplenishmentRequest.client_request_id == "manual-van-init-001"
            )
        ).all()
        assert len(rows) == 1
        audits = db.scalars(
            select(AuditLog).where(
                AuditLog.action == "replenishment_requested",
                AuditLog.entity_id == body["id"],
            )
        ).all()
        assert len(audits) == 1
        metadata = json.loads(audits[0].metadata_json)
        assert metadata["origin"] == "manual"
        assert metadata["client_request_id"] == "manual-van-init-001"


def test_warehouse_creation_classifies_engineer_ownership_as_van_and_rejects_other_van_owners(client):
    engineer = _create_user(client, "warehouse-class-engineer", "engineer", ENGINEER_PASSWORD)
    warehouse_user = _create_user(client, "warehouse-class-staff", "warehouse", STAFF_PASSWORD)

    auto_classified = client.post(
        "/api/warehouses",
        json={
            "code": "AUTO-VAN",
            "name": "Auto classified van",
            "warehouse_type": "main",
            "assigned_user_id": engineer["id"],
        },
    )
    assert auto_classified.status_code == 200, auto_classified.text
    assert auto_classified.json()["warehouse_type"] == "van"
    assert auto_classified.json()["assigned_user_id"] == engineer["id"]

    invalid_owner = client.post(
        "/api/warehouses",
        json={
            "code": "INVALID-VAN-OWNER",
            "name": "Invalid van owner",
            "warehouse_type": "van",
            "assigned_user_id": warehouse_user["id"],
        },
    )
    missing_owner = client.post(
        "/api/warehouses",
        json={
            "code": "MISSING-VAN-OWNER",
            "name": "Missing van owner",
            "warehouse_type": "van",
        },
    )
    assert invalid_owner.status_code == 422, invalid_owner.text
    assert missing_owner.status_code == 422, missing_owner.text


def test_generic_inventory_endpoints_never_mutate_vehicle_stock_including_legacy_main_type(client):
    setup = _standard_setup(client)
    with client.app.state.testing_session_local() as db:
        legacy_vehicle = Warehouse(
            organization_id=1,
            code="LEGACY-MAIN-TYPE-VAN",
            name="Legacy main type assigned to engineer",
            warehouse_type="main",
            assigned_user_id=setup["engineer_a"]["id"],
        )
        db.add(legacy_vehicle)
        db.commit()
        db.refresh(legacy_vehicle)
        legacy_vehicle_id = legacy_vehicle.id

    vehicle_ids = (setup["van_a"]["id"], legacy_vehicle_id)
    for vehicle_id in vehicle_ids:
        attempts = [
            {
                "transaction_type": "inbound",
                "quantity": 1,
                "to_warehouse_id": vehicle_id,
            },
            {
                "transaction_type": "transfer",
                "quantity": 1,
                "from_warehouse_id": setup["source"]["id"],
                "to_warehouse_id": vehicle_id,
            },
            {
                "transaction_type": "transfer",
                "quantity": 1,
                "from_warehouse_id": vehicle_id,
                "to_warehouse_id": setup["source"]["id"],
            },
            {
                "transaction_type": "outbound",
                "quantity": 1,
                "from_warehouse_id": vehicle_id,
            },
        ]
        for attempt in attempts:
            response = client.post(
                "/api/inventory/transactions",
                json={"part_id": setup["part"]["id"], **attempt},
            )
            assert response.status_code == 409, response.text

    for protected_type in ("return", "work_order_used"):
        response = client.post(
            "/api/inventory/transactions",
            json={
                "part_id": setup["part"]["id"],
                "transaction_type": protected_type,
                "quantity": 1,
                "to_warehouse_id": setup["source"]["id"],
            },
        )
        assert response.status_code == 400, response.text

    with client.app.state.testing_session_local() as db:
        vehicle_movements = db.scalars(
            select(InventoryTransaction).where(
                (InventoryTransaction.from_warehouse_id.in_(vehicle_ids))
                | (InventoryTransaction.to_warehouse_id.in_(vehicle_ids))
            )
        ).all()
        assert vehicle_movements == []


def test_historical_replenishment_requires_admin_password_reason_and_explicit_resolution(client):
    setup = _standard_setup(client)
    notification_id = _create_notification(client, setup["part"]["id"], setup["van_a"]["id"])
    with client.app.state.testing_session_local() as db:
        reopened = ReplenishmentRequest(
            organization_id=1,
            notification_id=notification_id,
            part_id=setup["part"]["id"],
            destination_warehouse_id=setup["van_a"]["id"],
            source_warehouse_id=setup["source"]["id"],
            target_user_id=setup["engineer_a"]["id"],
            quantity=2,
            requested_by=setup["warehouse_user"]["id"],
            status="requested",
            version=0,
            requires_reconciliation=True,
        )
        historical = ReplenishmentRequest(
            organization_id=1,
            part_id=setup["part"]["id"],
            destination_warehouse_id=setup["van_a"]["id"],
            source_warehouse_id=setup["source"]["id"],
            target_user_id=setup["engineer_a"]["id"],
            quantity=1,
            requested_by=setup["warehouse_user"]["id"],
            status="completed",
            version=4,
            requires_reconciliation=True,
        )
        db.add_all([reopened, historical])
        db.commit()
        db.refresh(reopened)
        db.refresh(historical)
        reopened_id = reopened.id
        historical_id = historical.id

    def reconcile(request_id: int, request_headers: dict[str, str], payload: dict):
        return client.post(
            f"/api/inventory/replenishment-requests/{request_id}/reconcile",
            headers=request_headers,
            json=payload,
        )

    reset_payload = {
        "expected_version": 0,
        "resolution": "reset_requested",
        "reason": "Validate migrated historical request",
        "account_password": STAFF_PASSWORD,
    }
    with _enforced_rbac():
        headers = _headers(client, setup)
        assert _action(
            client,
            reopened_id,
            headers["admin"],
            "start_picking",
            0,
            source_warehouse_id=setup["source"]["id"],
        ).status_code == 409
        assert reconcile(reopened_id, headers["warehouse"], reset_payload).status_code == 403
        assert reconcile(reopened_id, headers["manager"], reset_payload).status_code == 403
        assert reconcile(
            reopened_id,
            headers["admin"],
            {**reset_payload, "expected_version": 99},
        ).status_code == 409
        assert reconcile(
            reopened_id,
            headers["admin"],
            {**reset_payload, "account_password": "incorrect-password"},
        ).status_code == 401
        assert reconcile(
            reopened_id,
            headers["admin"],
            {**reset_payload, "reason": "   "},
        ).status_code == 422
        assert reconcile(
            reopened_id,
            headers["admin"],
            {**reset_payload, "resolution": "accept_historical"},
        ).status_code == 409

        reset = reconcile(reopened_id, headers["admin"], reset_payload)
        assert reset.status_code == 200, reset.text
        assert reset.json()["requires_reconciliation"] is False
        assert (reset.json()["status"], reset.json()["version"]) == ("requested", 1)
        resumed = _action(
            client,
            reopened_id,
            headers["warehouse"],
            "start_picking",
            1,
            source_warehouse_id=setup["source"]["id"],
        )
        assert resumed.status_code == 200, resumed.text

        historical_payload = {
            "expected_version": 4,
            "resolution": "accept_historical",
            "reason": "Accept completed legacy record without ledger",
            "account_password": STAFF_PASSWORD,
        }
        assert reconcile(
            historical_id,
            headers["admin"],
            {**historical_payload, "resolution": "reset_requested"},
        ).status_code == 409
        accepted = reconcile(historical_id, headers["admin"], historical_payload)
        assert accepted.status_code == 200, accepted.text
        assert accepted.json()["requires_reconciliation"] is False
        assert (accepted.json()["status"], accepted.json()["version"]) == ("completed", 5)

    with client.app.state.testing_session_local() as db:
        assert db.get(InventoryNotification, notification_id).status == "open"
        audits = db.scalars(
            select(AuditLog)
            .where(
                AuditLog.action == "replenishment_reconciled",
                AuditLog.entity_id.in_([reopened_id, historical_id]),
            )
            .order_by(AuditLog.entity_id)
        ).all()
        assert len(audits) == 2
        assert [json.loads(row.metadata_json)["resolution"] for row in audits] == [
            "reset_requested",
            "accept_historical",
        ]


def test_corrupt_shipment_and_receipt_ledgers_block_receive_and_complete(client):
    setup = _standard_setup(client)
    with _enforced_rbac():
        headers = _headers(client, setup)
        first_response = _manual_request(
            client,
            headers["warehouse"],
            part_id=setup["part"]["id"],
            destination_warehouse_id=setup["van_a"]["id"],
            source_warehouse_id=setup["source"]["id"],
            quantity=2,
            reason="Shipment ledger integrity test",
            client_request_id="ledger-corruption-ship",
        )
        second_response = _manual_request(
            client,
            headers["warehouse"],
            part_id=setup["part"]["id"],
            destination_warehouse_id=setup["van_a"]["id"],
            source_warehouse_id=setup["source"]["id"],
            quantity=2,
            reason="Receipt ledger integrity test",
            client_request_id="ledger-corruption-receive",
        )
        assert first_response.status_code == second_response.status_code == 200
        first = first_response.json()
        second = second_response.json()

        for item in (first, second):
            picked = _action(
                client,
                item["id"],
                headers["warehouse"],
                "start_picking",
                0,
                source_warehouse_id=setup["source"]["id"],
            )
            assert picked.status_code == 200, picked.text
            shipped = _action(client, item["id"], headers["warehouse"], "ship", 1)
            assert shipped.status_code == 200, shipped.text
            item["shipment_transaction_id"] = shipped.json()["shipment_transaction_id"]

        second_received = _action(
            client,
            second["id"],
            headers["engineer_a"],
            "receive",
            2,
            account_password=ENGINEER_PASSWORD,
        )
        assert second_received.status_code == 200, second_received.text
        second_receipt_id = second_received.json()["receipt_transaction_id"]

        with client.app.state.testing_session_local() as db:
            corrupt_shipment = db.get(InventoryTransaction, first["shipment_transaction_id"])
            corrupt_receipt = db.get(InventoryTransaction, second_receipt_id)
            corrupt_shipment.quantity = 3
            corrupt_receipt.quantity = 3
            db.commit()

        blocked_receive = _action(
            client,
            first["id"],
            headers["engineer_a"],
            "receive",
            2,
            account_password=ENGINEER_PASSWORD,
        )
        blocked_complete = _action(client, second["id"], headers["warehouse"], "complete", 3)
        assert blocked_receive.status_code == 409, blocked_receive.text
        assert blocked_complete.status_code == 409, blocked_complete.text

    with client.app.state.testing_session_local() as db:
        first_stored = db.get(ReplenishmentRequest, first["id"])
        second_stored = db.get(ReplenishmentRequest, second["id"])
        assert (first_stored.status, first_stored.version, first_stored.receipt_transaction_id) == (
            "shipped",
            2,
            None,
        )
        assert (second_stored.status, second_stored.version, second_stored.completed_at) == (
            "received",
            3,
            None,
        )


def test_replenishment_requests_and_actions_are_tenant_isolated(client):
    setup = _standard_setup(client)
    notification_one = _create_notification(client, setup["part"]["id"], setup["van_a"]["id"])
    extra_notification_one = _create_notification(client, setup["part"]["id"], setup["van_a"]["id"])

    with client.app.state.testing_session_local() as db:
        organization_two = Organization(name="Custody Tenant Two", slug="custody-tenant-two")
        db.add(organization_two)
        db.flush()
        warehouse_user_two = User(
            organization_id=organization_two.id,
            name="Tenant two warehouse",
            email="tenant-two-warehouse@custody.test",
            role=UserRole.WAREHOUSE,
            password_hash=hash_password(STAFF_PASSWORD),
        )
        engineer_two = User(
            organization_id=organization_two.id,
            name="Tenant two engineer",
            email="tenant-two-engineer@custody.test",
            role=UserRole.ENGINEER,
            password_hash=hash_password(ENGINEER_PASSWORD),
        )
        db.add_all([warehouse_user_two, engineer_two])
        db.flush()
        source_two = Warehouse(
            organization_id=organization_two.id,
            code="TENANT-TWO-SOURCE",
            name="Tenant two source",
            warehouse_type="main",
        )
        destination_two = Warehouse(
            organization_id=organization_two.id,
            code="TENANT-TWO-DEST",
            name="Tenant two destination",
            warehouse_type="van",
            assigned_user_id=engineer_two.id,
        )
        part_two = Part(
            organization_id=organization_two.id,
            part_number="TENANT-TWO-PART",
            name="Tenant two part",
        )
        db.add_all([source_two, destination_two, part_two])
        db.flush()
        notification_two = InventoryNotification(
            organization_id=organization_two.id,
            part_id=part_two.id,
            warehouse_id=destination_two.id,
            message="Tenant two replenishment",
        )
        db.add(notification_two)
        db.commit()
        tenant_two = {
            "user": {"id": warehouse_user_two.id, "email": warehouse_user_two.email},
            "source_id": source_two.id,
            "destination_id": destination_two.id,
            "part_id": part_two.id,
            "notification_id": notification_two.id,
            "organization_id": organization_two.id,
        }

    with _enforced_rbac():
        headers = _headers(client, setup)
        tenant_two_headers = _login(
            client,
            tenant_two["user"],
            STAFF_PASSWORD,
            device_id="tenant-two-warehouse-device",
            device_token="t" * 64,
        )
        request_one = _create_request(
            client,
            notification_one,
            headers["warehouse"],
            quantity=2,
            source_warehouse_id=setup["source"]["id"],
        )
        request_two = _create_request(
            client,
            tenant_two["notification_id"],
            tenant_two_headers,
            quantity=1,
            source_warehouse_id=tenant_two["source_id"],
        )
        manual_one = _manual_request(
            client,
            headers["warehouse"],
            part_id=setup["part"]["id"],
            destination_warehouse_id=setup["van_a"]["id"],
            source_warehouse_id=setup["source"]["id"],
            quantity=1,
            reason="Tenant scoped manual request",
            client_request_id="same-key-across-tenants",
        )
        manual_two = _manual_request(
            client,
            tenant_two_headers,
            part_id=tenant_two["part_id"],
            destination_warehouse_id=tenant_two["destination_id"],
            source_warehouse_id=tenant_two["source_id"],
            quantity=1,
            reason="Tenant scoped manual request",
            client_request_id="same-key-across-tenants",
        )
        assert manual_one.status_code == manual_two.status_code == 200
        assert manual_one.json()["id"] != manual_two.json()["id"]

        list_one = client.get("/api/inventory/replenishment-requests", headers=headers["warehouse"])
        list_two = client.get("/api/inventory/replenishment-requests", headers=tenant_two_headers)
        assert {row["id"] for row in list_one.json()} == {request_one["id"], manual_one.json()["id"]}
        assert {row["id"] for row in list_two.json()} == {request_two["id"], manual_two.json()["id"]}

        cross_action = _action(
            client,
            request_one["id"],
            tenant_two_headers,
            "start_picking",
            0,
            source_warehouse_id=tenant_two["source_id"],
        )
        assert cross_action.status_code == 404, cross_action.text
        cross_notification = client.post(
            f"/api/inventory/notifications/{notification_one}/create-request?quantity=1",
            headers=tenant_two_headers,
        )
        assert cross_notification.status_code == 404, cross_notification.text
        cross_source = client.post(
            f"/api/inventory/notifications/{extra_notification_one}/create-request"
            f"?quantity=1&source_warehouse_id={tenant_two['source_id']}",
            headers=headers["warehouse"],
        )
        assert cross_source.status_code == 404, cross_source.text
        cross_manual_destination = _manual_request(
            client,
            headers["warehouse"],
            part_id=setup["part"]["id"],
            destination_warehouse_id=tenant_two["destination_id"],
            source_warehouse_id=setup["source"]["id"],
            quantity=1,
            reason="Cross tenant destination must fail",
            client_request_id="cross-tenant-destination",
        )
        cross_manual_source = _manual_request(
            client,
            tenant_two_headers,
            part_id=tenant_two["part_id"],
            destination_warehouse_id=tenant_two["destination_id"],
            source_warehouse_id=setup["source"]["id"],
            quantity=1,
            reason="Cross tenant source must fail",
            client_request_id="cross-tenant-source",
        )
        assert cross_manual_destination.status_code == 404, cross_manual_destination.text
        assert cross_manual_source.status_code == 404, cross_manual_source.text

    with client.app.state.testing_session_local() as db:
        audits_one = db.scalars(
            select(AuditLog).where(AuditLog.entity_id == request_one["id"], AuditLog.entity_type == "replenishment_request")
        ).all()
        audits_two = db.scalars(
            select(AuditLog).where(AuditLog.entity_id == request_two["id"], AuditLog.entity_type == "replenishment_request")
        ).all()
        assert audits_one and {row.organization_id for row in audits_one} == {1}
        assert audits_two and {row.organization_id for row in audits_two} == {tenant_two["organization_id"]}


def test_generic_inventory_transaction_persists_and_ignores_spoofed_user_id(client):
    setup = _standard_setup(client, source_quantity=0)

    with _enforced_rbac():
        headers = _headers(client, setup)
        created = client.post(
            "/api/inventory/transactions",
            headers=headers["warehouse"],
            json={
                "part_id": setup["part"]["id"],
                "transaction_type": "inbound",
                "quantity": 7,
                "to_warehouse_id": setup["source"]["id"],
                "user_id": setup["engineer_b"]["id"],
            },
        )
        assert created.status_code == 200, created.text
        assert created.json()["user_id"] == setup["warehouse_user"]["id"]
        transaction_id = created.json()["id"]

        listed = client.get("/api/inventory/transactions?limit=100", headers=headers["warehouse"])
        assert listed.status_code == 200, listed.text
        stored_response = next(row for row in listed.json() if row["id"] == transaction_id)
        assert stored_response["user_id"] == setup["warehouse_user"]["id"]
        assert _balance(client, headers["warehouse"], setup["part"]["id"], setup["source"]["id"]) == 7

    with client.app.state.testing_session_local() as db:
        stored = db.get(InventoryTransaction, transaction_id)
        assert stored is not None
        assert stored.user_id == setup["warehouse_user"]["id"]
        audit = db.scalar(
            select(AuditLog).where(
                AuditLog.action == "inventory_inbound",
                AuditLog.entity_id == transaction_id,
            )
        )
        assert audit is not None and audit.user_id == setup["warehouse_user"]["id"]


def test_engineer_can_only_consume_parts_from_own_van_and_my_van_is_account_scoped(
    client,
    seed_inventory_ledger,
):
    setup = _standard_setup(client)
    transfer_to_a = client.post(
        "/api/inventory/transactions",
        json={
            "part_id": setup["part"]["id"],
            "transaction_type": "transfer",
            "quantity": 2,
            "from_warehouse_id": setup["source"]["id"],
            "to_warehouse_id": setup["van_a"]["id"],
        },
    )
    transfer_to_b = client.post(
        "/api/inventory/transactions",
        json={
            "part_id": setup["part"]["id"],
            "transaction_type": "transfer",
            "quantity": 2,
            "from_warehouse_id": setup["source"]["id"],
            "to_warehouse_id": setup["van_b"]["id"],
        },
    )
    assert transfer_to_a.status_code == transfer_to_b.status_code == 409
    seed_inventory_ledger(
        part_id=setup["part"]["id"],
        transaction_type="transfer",
        quantity=2,
        from_warehouse_id=setup["source"]["id"],
        to_warehouse_id=setup["van_a"]["id"],
    )
    seed_inventory_ledger(
        part_id=setup["part"]["id"],
        transaction_type="transfer",
        quantity=2,
        from_warehouse_id=setup["source"]["id"],
        to_warehouse_id=setup["van_b"]["id"],
    )
    work_order = client.post(
        "/api/work-orders",
        json={"ticket_number": "CUSTODY-OWN-VAN", "status": "open"},
    )
    assert work_order.status_code == 200, work_order.text

    with _enforced_rbac():
        headers = _headers(client, setup)
        claimed = client.post(
            f"/api/work-orders/{work_order.json()['id']}/claim",
            headers=headers["engineer_a"],
        )
        assert claimed.status_code == 200, claimed.text
        execution_headers = {
            **headers["engineer_a"],
            "X-Claim-Version": str(claimed.json()["claim_version"]),
        }
        base_payload = {
            "work_order_id": work_order.json()["id"],
            "part_id": setup["part"]["id"],
            "user_id": setup["engineer_b"]["id"],
            "quantity": 1,
            "unit_cost": 7.5,
        }
        other_van = client.post(
            f"/api/work-orders/{work_order.json()['id']}/use-part",
            headers=execution_headers,
            json={**base_payload, "warehouse_id": setup["van_b"]["id"]},
        )
        main_warehouse = client.post(
            f"/api/work-orders/{work_order.json()['id']}/use-part",
            headers=execution_headers,
            json={**base_payload, "warehouse_id": setup["source"]["id"]},
        )
        assert other_van.status_code == 403, other_van.text
        assert main_warehouse.status_code == 403, main_warehouse.text

        own_van = client.post(
            f"/api/work-orders/{work_order.json()['id']}/use-part",
            headers=execution_headers,
            json={**base_payload, "warehouse_id": setup["van_a"]["id"]},
        )
        assert own_van.status_code == 200, own_van.text
        assert own_van.json()["user_id"] == setup["engineer_a"]["id"]

        engineer_a_van = client.get("/api/inventory/my-van", headers=headers["engineer_a"])
        engineer_b_van = client.get("/api/inventory/my-van", headers=headers["engineer_b"])
        assert engineer_a_van.status_code == engineer_b_van.status_code == 200
        row_a = next(row for row in engineer_a_van.json() if row["part_id"] == setup["part"]["id"])
        row_b = next(row for row in engineer_b_van.json() if row["part_id"] == setup["part"]["id"])
        assert (row_a["warehouse_id"], row_a["quantity"]) == (setup["van_a"]["id"], 1)
        assert (row_b["warehouse_id"], row_b["quantity"]) == (setup["van_b"]["id"], 2)
        assert client.get("/api/inventory/my-van", headers=headers["admin"]).status_code == 403

    with client.app.state.testing_session_local() as db:
        usages = db.scalars(
            select(WorkOrderPart).where(WorkOrderPart.work_order_id == work_order.json()["id"])
        ).all()
        assert len(usages) == 1
        assert usages[0].warehouse_id == setup["van_a"]["id"]
        assert usages[0].user_id == setup["engineer_a"]["id"]


def _return_action(client, request_id: int, headers: dict[str, str], action: str, version: int, **extra):
    return client.post(
        f"/api/inventory/vehicle-returns/{request_id}/actions",
        headers=headers,
        json={"action": action, "expected_version": version, **extra},
    )


def test_vehicle_return_full_chain_requires_owner_handover_and_warehouse_receipt(client, seed_inventory_ledger):
    setup = _standard_setup(client)
    seed_inventory_ledger(
        part_id=setup["part"]["id"],
        quantity=5,
        to_warehouse_id=setup["van_a"]["id"],
        user_id=setup["engineer_a"]["id"],
    )

    with _enforced_rbac():
        headers = _headers(client, setup)
        created = client.post(
            "/api/inventory/vehicle-returns",
            headers=headers["engineer_a"],
            json={
                "part_id": setup["part"]["id"],
                "source_warehouse_id": setup["van_a"]["id"],
                "destination_warehouse_id": setup["source"]["id"],
                "quantity": 3,
                "reason": "Unused service stock",
                "client_request_id": "return-full-chain-001",
            },
        )
        assert created.status_code == 200, created.text
        item = created.json()
        assert (item["status"], item["version"], item["engineer_id"]) == (
            "requested",
            0,
            setup["engineer_a"]["id"],
        )

        approved = _return_action(client, item["id"], headers["warehouse"], "approve", 0)
        assert approved.status_code == 200, approved.text
        assert (approved.json()["status"], approved.json()["version"]) == ("approved", 1)
        assert _return_action(
            client,
            item["id"],
            headers["engineer_b"],
            "ship",
            1,
            account_password=ENGINEER_PASSWORD,
        ).status_code == 403
        assert _return_action(
            client,
            item["id"],
            headers["admin"],
            "ship",
            1,
            account_password=STAFF_PASSWORD,
        ).status_code == 403
        assert _return_action(
            client,
            item["id"],
            headers["engineer_a"],
            "ship",
            1,
            account_password="wrong-password",
        ).status_code == 401

        shipped = _return_action(
            client,
            item["id"],
            headers["engineer_a"],
            "ship",
            1,
            account_password=ENGINEER_PASSWORD,
        )
        assert shipped.status_code == 200, shipped.text
        assert (shipped.json()["status"], shipped.json()["version"]) == ("shipped", 2)
        assert _balance(client, headers["warehouse"], setup["part"]["id"], setup["van_a"]["id"]) == 2
        assert _return_action(client, item["id"], headers["engineer_a"], "receive", 2).status_code == 403

        received = _return_action(client, item["id"], headers["warehouse"], "receive", 2)
        assert received.status_code == 200, received.text
        assert (received.json()["status"], received.json()["version"]) == ("received", 3)
        assert _balance(client, headers["warehouse"], setup["part"]["id"], setup["source"]["id"]) == 13

    with client.app.state.testing_session_local() as db:
        transactions = db.scalars(
            select(InventoryTransaction)
            .where(InventoryTransaction.vehicle_return_request_id == item["id"])
            .order_by(InventoryTransaction.id)
        ).all()
        assert [row.movement_stage for row in transactions] == ["return_ship", "return_receive"]
        assert transactions[0].user_id == setup["engineer_a"]["id"]
        assert transactions[1].user_id == setup["warehouse_user"]["id"]
        audits = db.scalars(
            select(AuditLog)
            .where(AuditLog.entity_type == "vehicle_return_request", AuditLog.entity_id == item["id"])
            .order_by(AuditLog.id)
        ).all()
        assert [row.action for row in audits] == [
            "vehicle_return_requested",
            "vehicle_return_approve",
            "vehicle_return_ship",
            "vehicle_return_receive",
        ]


def test_vehicle_return_approval_reserves_stock_and_cancel_releases_it(client, seed_inventory_ledger):
    setup = _standard_setup(client, source_quantity=0)
    seed_inventory_ledger(
        part_id=setup["part"]["id"],
        quantity=5,
        to_warehouse_id=setup["van_a"]["id"],
    )
    with _enforced_rbac():
        headers = _headers(client, setup)

        def create(key: str):
            response = client.post(
                "/api/inventory/vehicle-returns",
                headers=headers["engineer_a"],
                json={
                    "part_id": setup["part"]["id"],
                    "source_warehouse_id": setup["van_a"]["id"],
                    "destination_warehouse_id": setup["source"]["id"],
                    "quantity": 4,
                    "reason": "Reduce vehicle stock",
                    "client_request_id": key,
                },
            )
            assert response.status_code == 200, response.text
            return response.json()

        first = create("return-reservation-001")
        second = create("return-reservation-002")
        assert _return_action(client, first["id"], headers["warehouse"], "approve", 0).status_code == 200
        competing = _return_action(client, second["id"], headers["warehouse"], "approve", 0)
        assert competing.status_code == 409, competing.text
        cancelled = _return_action(
            client,
            first["id"],
            headers["engineer_a"],
            "cancel",
            1,
            reason="Return no longer needed",
        )
        assert cancelled.status_code == 200, cancelled.text
        assert cancelled.json()["status"] == "cancelled"
        assert _return_action(client, second["id"], headers["warehouse"], "approve", 0).status_code == 200


def test_vehicle_return_creation_is_device_bound_idempotent_and_tenant_safe(client, seed_inventory_ledger):
    setup = _standard_setup(client)
    seed_inventory_ledger(
        part_id=setup["part"]["id"],
        quantity=2,
        to_warehouse_id=setup["van_a"]["id"],
    )
    payload = {
        "part_id": setup["part"]["id"],
        "source_warehouse_id": setup["van_a"]["id"],
        "destination_warehouse_id": setup["source"]["id"],
        "quantity": 1,
        "reason": "Duplicate return test",
        "client_request_id": "return-idempotent-001",
    }
    with _enforced_rbac():
        headers = _headers(client, setup)
        assert client.post("/api/inventory/vehicle-returns", headers=_login(client, setup["engineer_a"], ENGINEER_PASSWORD), json=payload).status_code == 401
        assert client.post("/api/inventory/vehicle-returns", headers=headers["engineer_b"], json=payload).status_code == 403
        first = client.post("/api/inventory/vehicle-returns", headers=headers["engineer_a"], json=payload)
        repeated = client.post("/api/inventory/vehicle-returns", headers=headers["engineer_a"], json=payload)
        assert first.status_code == repeated.status_code == 200
        assert first.json()["id"] == repeated.json()["id"]
        conflict = client.post(
            "/api/inventory/vehicle-returns",
            headers=headers["engineer_a"],
            json={**payload, "quantity": 2},
        )
        assert conflict.status_code == 409
        engineer_list = client.get("/api/inventory/vehicle-returns", headers=headers["engineer_a"])
        other_list = client.get("/api/inventory/vehicle-returns", headers=headers["engineer_b"])
        assert {row["id"] for row in engineer_list.json()} == {first.json()["id"]}
        assert other_list.json() == []


def test_vehicle_return_retries_do_not_duplicate_inventory_movements(client, seed_inventory_ledger):
    setup = _standard_setup(client)
    seed_inventory_ledger(part_id=setup["part"]["id"], quantity=2, to_warehouse_id=setup["van_a"]["id"])
    with _enforced_rbac():
        headers = _headers(client, setup)
        created = client.post(
            "/api/inventory/vehicle-returns",
            headers=headers["engineer_a"],
            json={
                "part_id": setup["part"]["id"],
                "source_warehouse_id": setup["van_a"]["id"],
                "destination_warehouse_id": setup["source"]["id"],
                "quantity": 1,
                "reason": "Retry safety",
                "client_request_id": "return-retry-001",
            },
        ).json()
        assert _return_action(client, created["id"], headers["warehouse"], "approve", 0).status_code == 200
        first_ship = _return_action(
            client, created["id"], headers["engineer_a"], "ship", 1, account_password=ENGINEER_PASSWORD
        )
        retry_ship = _return_action(
            client, created["id"], headers["engineer_a"], "ship", 1, account_password=ENGINEER_PASSWORD
        )
        assert first_ship.status_code == retry_ship.status_code == 200
        first_receive = _return_action(client, created["id"], headers["warehouse"], "receive", 2)
        retry_receive = _return_action(client, created["id"], headers["warehouse"], "receive", 2)
        assert first_receive.status_code == retry_receive.status_code == 200
    with client.app.state.testing_session_local() as db:
        rows = db.scalars(
            select(InventoryTransaction).where(InventoryTransaction.vehicle_return_request_id == created["id"])
        ).all()
        assert sorted(row.movement_stage for row in rows) == ["return_receive", "return_ship"]
