from __future__ import annotations

from contextlib import contextmanager

from app.core.config import settings


PASSWORD = "form-test-password"
PNG_SIGNATURE = "data:image/png;base64,iVBORw0KGgo="


def _field(
    key: str,
    label: str,
    field_type: str = "text",
    **overrides,
) -> dict:
    payload = {
        "field_key": key,
        "label": label,
        "field_type": field_type,
        "options": ["Pass", "Fail"] if field_type == "select" else [],
        "required_at_completion": False,
        "requires_photo": False,
        "requires_signature": False,
        "requires_approval": False,
        "triggers_notification": False,
        "affects_inventory": False,
        "include_in_ai_learning": True,
        "sort_order": 0,
    }
    payload.update(overrides)
    return payload


def _create_template(client, *, name: str = "HVAC field visit", fields: list[dict] | None = None, **overrides) -> dict:
    payload = {
        "name": name,
        "industry": "HVAC",
        "description": "Verified site form",
        "default_work_order_status": "scheduled",
        "fields": fields or [
            _field(
                "condition",
                "Equipment condition",
                "select",
                required_at_completion=True,
                default_value="Pass",
            )
        ],
    }
    payload.update(overrides)
    response = client.post("/api/work-order-form-templates", json=payload)
    assert response.status_code == 200, response.text
    return response.json()


def _create_user(client, name: str, role: str) -> dict:
    response = client.post(
        "/api/users",
        json={
            "name": name,
            "email": f"{name}@forms.test",
            "role": role,
            "password": PASSWORD,
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def _login(client, user: dict, *, device_id: str | None = None, token: str | None = None) -> dict[str, str]:
    headers = {}
    if device_id:
        headers = {
            "X-Device-Id": device_id,
            "X-Device-Token": token,
            "X-Device-Name": device_id,
        }
    response = client.post(
        "/api/auth/login",
        data={"username": user["email"], "password": PASSWORD},
        headers=headers,
    )
    assert response.status_code == 200, response.text
    result = {"Authorization": f"Bearer {response.json()['access_token']}"}
    if token:
        result["X-Device-Token"] = token
    return result


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


def test_template_versions_create_immutable_work_order_snapshots(client):
    template = _create_template(client)
    created = client.post(
        "/api/work-orders",
        json={
            "ticket_number": "FORM-SNAPSHOT-1",
            "form_template_id": template["id"],
        },
    )
    assert created.status_code == 200, created.text
    assert created.json()["status"] == "scheduled"
    assert created.json()["form_template_version"] == 0

    first_form = client.get(f"/api/work-orders/{created.json()['id']}/form")
    assert first_form.status_code == 200, first_form.text
    assert first_form.json()["values"] == {"condition": "Pass"}
    assert first_form.json()["fields"][0]["label"] == "Equipment condition"

    updated = client.patch(
        f"/api/work-order-form-templates/{template['id']}",
        json={
            "expected_version": template["version"],
            "name": template["name"],
            "fields": [
                _field("condition", "Condition after repair", "select", options=["Pass", "Fail", "Monitor"]),
                _field("meter_reading", "Meter reading", "number"),
            ],
        },
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["version"] == 1

    unchanged = client.get(f"/api/work-orders/{created.json()['id']}/form")
    assert unchanged.status_code == 200
    assert [field["field_key"] for field in unchanged.json()["fields"]] == ["condition"]
    assert unchanged.json()["fields"][0]["label"] == "Equipment condition"

    second = client.post(
        "/api/work-orders",
        json={
            "ticket_number": "FORM-SNAPSHOT-2",
            "form_template_id": template["id"],
            "status": "open",
        },
    )
    assert second.status_code == 200, second.text
    assert second.json()["status"] == "open"
    assert second.json()["form_template_version"] == 1
    second_form = client.get(f"/api/work-orders/{second.json()['id']}/form")
    assert [field["field_key"] for field in second_form.json()["fields"]] == [
        "condition",
        "meter_reading",
    ]


def test_form_values_are_typed_versioned_and_required_for_completion(client):
    template = _create_template(
        client,
        name="Commissioning form",
        fields=[
            _field("result", "Commissioning result", "select", required_at_completion=True),
            _field("pressure", "Pressure", "number", required_at_completion=True, sort_order=1),
            _field(
                "site_photo",
                "Site photo",
                "photo",
                requires_photo=True,
                triggers_notification=True,
                sort_order=2,
            ),
            _field("customer_signoff", "Customer signoff", "signature", sort_order=3),
        ],
    )
    order = client.post(
        "/api/work-orders",
        json={"ticket_number": "FORM-VALIDATE-1", "form_template_id": template["id"]},
    ).json()

    unknown = client.patch(
        f"/api/work-orders/{order['id']}/form",
        json={"expected_version": 0, "values": {"unknown": "x"}},
    )
    assert unknown.status_code == 422, unknown.text
    wrong_choice = client.patch(
        f"/api/work-orders/{order['id']}/form",
        json={"expected_version": 0, "values": {"result": "Maybe"}},
    )
    assert wrong_choice.status_code == 422, wrong_choice.text
    wrong_number = client.patch(
        f"/api/work-orders/{order['id']}/form",
        json={"expected_version": 0, "values": {"pressure": "high"}},
    )
    assert wrong_number.status_code == 422, wrong_number.text
    invalid_signature = client.patch(
        f"/api/work-orders/{order['id']}/form",
        json={"expected_version": 0, "values": {"customer_signoff": "not-a-signature"}},
    )
    assert invalid_signature.status_code == 422, invalid_signature.text

    incomplete = client.post(f"/api/work-orders/{order['id']}/complete", json={})
    assert incomplete.status_code == 422, incomplete.text
    assert "custom_form.result" in incomplete.text
    assert "custom_form.pressure" in incomplete.text
    assert "custom_form.site_photo" in incomplete.text

    saved = client.patch(
        f"/api/work-orders/{order['id']}/form",
        json={
            "expected_version": 0,
            "values": {
                "result": "Pass",
                "pressure": 42.5,
                "site_photo": "https://files.example.test/site.jpg",
            },
        },
    )
    assert saved.status_code == 200, saved.text
    assert saved.json()["form_version"] == 1
    assert saved.json()["missing_required_fields"] == []

    stale = client.patch(
        f"/api/work-orders/{order['id']}/form",
        json={"expected_version": 0, "values": {"pressure": 43}},
    )
    assert stale.status_code == 409, stale.text

    completed = client.post(f"/api/work-orders/{order['id']}/complete", json={})
    assert completed.status_code == 200, completed.text
    frozen = client.patch(
        f"/api/work-orders/{order['id']}/form",
        json={"expected_version": 1, "values": {"pressure": 43}},
    )
    assert frozen.status_code == 409, frozen.text


def test_template_field_can_require_manager_completion_approval(client):
    template = _create_template(
        client,
        name="Approval form",
        fields=[_field("safety_check", "Safety check", "boolean", requires_approval=True)],
    )
    order = client.post(
        "/api/work-orders",
        json={"ticket_number": "FORM-APPROVAL-1", "form_template_id": template["id"]},
    ).json()
    policy = client.get(f"/api/work-orders/{order['id']}/completion-policy")
    assert policy.status_code == 200, policy.text
    assert policy.json()["require_manager_approval"] is True


def test_verified_claim_owner_edits_form_while_other_engineers_only_read(client):
    admin = _create_user(client, "form-admin", "admin")
    engineer_a = _create_user(client, "form-engineer-a", "engineer")
    engineer_b = _create_user(client, "form-engineer-b", "engineer")
    manager = _create_user(client, "form-manager", "manager")
    template = _create_template(
        client,
        name="Ownership form",
        fields=[
            _field("reading", "Reading", "number"),
            _field("customer_signoff", "Customer signoff", "signature", sort_order=1),
        ],
    )
    order = client.post(
        "/api/work-orders",
        json={"ticket_number": "FORM-OWNER-1", "form_template_id": template["id"]},
    ).json()
    seeded = client.patch(
        f"/api/work-orders/{order['id']}/form",
        json={
            "expected_version": 0,
            "values": {"customer_signoff": PNG_SIGNATURE},
        },
    )
    assert seeded.status_code == 200, seeded.text

    with _enforced_rbac():
        owner_headers = _login(
            client,
            engineer_a,
            device_id="form-owner-phone",
            token="a" * 64,
        )
        other_headers = _login(
            client,
            engineer_b,
            device_id="form-other-phone",
            token="b" * 64,
        )
        manager_headers = _login(client, manager)
        admin_headers = _login(client, admin)
        claimed = client.post(
            f"/api/work-orders/{order['id']}/claim",
            headers=owner_headers,
        )
        assert claimed.status_code == 200, claimed.text
        version = claimed.json()["claim_version"]
        owner_write_headers = {**owner_headers, "X-Claim-Version": str(version)}
        other_write_headers = {**other_headers, "X-Claim-Version": str(version)}

        owner_read = client.get(
            f"/api/work-orders/{order['id']}/form",
            headers=owner_headers,
        )
        assert owner_read.status_code == 200, owner_read.text
        assert owner_read.json()["can_edit"] is True
        assert owner_read.json()["values"]["customer_signoff"] == PNG_SIGNATURE

        other_read = client.get(
            f"/api/work-orders/{order['id']}/form",
            headers=other_headers,
        )
        assert other_read.status_code == 200, other_read.text
        assert other_read.json()["can_edit"] is False
        assert other_read.json()["values"]["customer_signoff"] is None

        other_write = client.patch(
            f"/api/work-orders/{order['id']}/form",
            headers=other_write_headers,
            json={"expected_version": 1, "values": {"reading": 99}},
        )
        assert other_write.status_code == 403, other_write.text

        manager_read = client.get(
            f"/api/work-orders/{order['id']}/form",
            headers=manager_headers,
        )
        assert manager_read.status_code == 200
        assert manager_read.json()["can_edit"] is False
        manager_write = client.patch(
            f"/api/work-orders/{order['id']}/form",
            headers=manager_headers,
            json={"expected_version": 1, "values": {"reading": 98}},
        )
        assert manager_write.status_code == 403, manager_write.text

        owner_write = client.patch(
            f"/api/work-orders/{order['id']}/form",
            headers=owner_write_headers,
            json={"expected_version": 1, "values": {"reading": 42}},
        )
        assert owner_write.status_code == 200, owner_write.text
        assert owner_write.json()["values"]["reading"] == 42

        admin_correction = client.patch(
            f"/api/work-orders/{order['id']}/form",
            headers=admin_headers,
            json={"expected_version": 2, "values": {"reading": 43}},
        )
        assert admin_correction.status_code == 200, admin_correction.text
        assert admin_correction.json()["values"]["reading"] == 43


def test_template_configuration_validation_and_applicability(client):
    bad_select = client.post(
        "/api/work-order-form-templates",
        json={
            "name": "Invalid choice form",
            "fields": [_field("choice", "Choice", "select", options=[])],
        },
    )
    assert bad_select.status_code == 422, bad_select.text

    bad_photo_flag = client.post(
        "/api/work-order-form-templates",
        json={
            "name": "Invalid photo form",
            "fields": [_field("evidence", "Evidence", "text", requires_photo=True)],
        },
    )
    assert bad_photo_flag.status_code == 422, bad_photo_flag.text

    template = _create_template(
        client,
        name="Filtered form",
        applicable_machine_type="ACME-9000",
        applicable_job_type="repair",
    )
    wrong_machine = client.post(
        "/api/work-orders",
        json={
            "ticket_number": "FORM-FILTER-1",
            "form_template_id": template["id"],
            "machine_type": "OTHER",
            "job_type": "repair",
        },
    )
    assert wrong_machine.status_code == 409, wrong_machine.text
    applicable = client.post(
        "/api/work-orders",
        json={
            "ticket_number": "FORM-FILTER-2",
            "form_template_id": template["id"],
            "machine_type": "acme-9000",
            "job_type": "REPAIR",
        },
    )
    assert applicable.status_code == 200, applicable.text

    second_template = _create_template(client, name="Second filtered form")
    duplicate_update = client.patch(
        f"/api/work-order-form-templates/{second_template['id']}",
        json={
            "expected_version": second_template["version"],
            "name": template["name"],
            "fields": [_field("replacement", "Replacement field")],
        },
    )
    assert duplicate_update.status_code == 409, duplicate_update.text
