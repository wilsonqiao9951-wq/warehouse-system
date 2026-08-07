from __future__ import annotations

from datetime import date, datetime
from hashlib import sha256
import json

from sqlalchemy import func, select

from app.core.config import settings
from app.models import (
    AuditLog,
    EnterpriseAgentRun,
    ExternalIntegration,
    ExternalSyncLog,
    InventoryNotification,
    InventoryTransaction,
    Organization,
    OrganizationUsagePeriod,
    ReplenishmentRequest,
    User,
    WorkOrder,
)


PASSWORD = "enterprise-agent-password"


def _create_user(client, name: str, role: str = "engineer", headers=None) -> dict:
    response = client.post(
        "/api/users",
        headers=headers or {},
        json={
            "name": name,
            "email": f"{name.replace(' ', '-').lower()}@agent.test",
            "role": role,
            "password": PASSWORD,
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def _headers(user_id: int) -> dict[str, str]:
    return {"X-User-Id": str(user_id)}


def _set_permission(client, admin_id: int, user_id: int, effect: str):
    return client.put(
        f"/api/users/{user_id}/permissions/agent.use",
        headers=_headers(admin_id),
        json={"effect": effect, "reason": "Enterprise agent test policy"},
    )


def _seed_operational_risks(client) -> dict:
    engineer = _create_user(client, "Agent Engineer")
    warehouse = client.post("/api/warehouses", json={"name": "Agent Main"}).json()
    part = client.post(
        "/api/parts",
        json={
            "part_number": "AGENT-PART",
            "name": "Agent low-stock part",
            "default_cost": 25,
            "safety_stock": 2,
            "min_stock": 2,
        },
    ).json()
    with client.app.state.testing_session_local() as db:
        db.add_all(
            [
                WorkOrder(
                    organization_id=1,
                    ticket_number="AGENT-DONE-1",
                    engineer_id=engineer["id"],
                    completed_by_id=engineer["id"],
                    job_type="Repair",
                    status="COMPLETED",
                    is_locked=True,
                    first_time_fix=False,
                    is_rework=True,
                    repair_duration_minutes=180,
                    revenue=300,
                    labor_cost=100,
                    created_at=datetime(2026, 8, 1, 8),
                    completed_at=datetime(2026, 8, 2, 12),
                ),
                WorkOrder(
                    organization_id=1,
                    ticket_number="AGENT-DONE-2",
                    engineer_id=engineer["id"],
                    completed_by_id=engineer["id"],
                    job_type="Repair",
                    status="COMPLETED",
                    is_locked=True,
                    first_time_fix=True,
                    is_rework=False,
                    repair_duration_minutes=60,
                    revenue=200,
                    labor_cost=50,
                    created_at=datetime(2026, 8, 2, 8),
                    completed_at=datetime(2026, 8, 3, 12),
                ),
                WorkOrder(
                    organization_id=1,
                    ticket_number="AGENT-BACKLOG",
                    engineer_id=engineer["id"],
                    job_type="Repair",
                    status="OPEN",
                    schedule_date=date(2026, 8, 5),
                    created_at=datetime(2026, 7, 1, 8),
                ),
            ]
        )
        db.add(
            InventoryNotification(
                organization_id=1,
                part_id=part["id"],
                warehouse_id=warehouse["id"],
                message="Agent low-stock evidence",
                status="open",
            )
        )
        db.add(
            ReplenishmentRequest(
                organization_id=1,
                part_id=part["id"],
                destination_warehouse_id=warehouse["id"],
                quantity=3,
                requested_by=engineer["id"],
                target_user_id=engineer["id"],
                request_reason="Agent test refill",
                status="requested",
                approval_status="pending",
                requires_reconciliation=True,
            )
        )
        integration = ExternalIntegration(
            organization_id=1,
            name="Agent ERP",
            provider="erp",
            key_prefix="opf_agent_test",
            api_key_hash="a" * 64,
            field_mapping_json="{}",
            is_active=True,
        )
        db.add(integration)
        db.flush()
        db.add(
            ExternalSyncLog(
                organization_id=1,
                integration_id=integration.id,
                direction="outbound",
                event_type="work_order.completed",
                external_id="agent-event-1",
                idempotency_key="agent-event-1",
                request_hash="b" * 64,
                status="failed",
                attempt_count=3,
            )
        )

        tenant_two = Organization(
            name="Agent Hidden Tenant",
            slug="agent-hidden-tenant",
            ai_monthly_limit=100,
        )
        db.add(tenant_two)
        db.flush()
        hidden_integration = ExternalIntegration(
            organization_id=tenant_two.id,
            name="Hidden ERP",
            provider="erp",
            key_prefix="opf_agent_hidden",
            api_key_hash="c" * 64,
            field_mapping_json="{}",
            is_active=True,
        )
        db.add(hidden_integration)
        db.flush()
        db.add(
            ExternalSyncLog(
                organization_id=tenant_two.id,
                integration_id=hidden_integration.id,
                direction="outbound",
                event_type="work_order.completed",
                external_id="hidden-event",
                idempotency_key="hidden-event",
                request_hash="d" * 64,
                status="failed",
                attempt_count=9,
            )
        )
        db.commit()
    return {"engineer": engineer, "warehouse": warehouse, "part": part}


def _evidence_value(payload: dict, finding_code: str, evidence_code: str):
    finding = next(item for item in payload["findings"] if item["code"] == finding_code)
    return next(item["value"] for item in finding["evidence"] if item["code"] == evidence_code)


def test_enterprise_agent_is_grounded_tenant_scoped_read_only_and_audited(client):
    _seed_operational_risks(client)
    question = "Give me the daily operating brief and priority risks."
    with client.app.state.testing_session_local() as db:
        before_work_orders = db.scalar(select(func.count(WorkOrder.id)))
        before_inventory = db.scalar(select(func.count(InventoryTransaction.id)))

    response = client.post(
        "/api/agent/operations",
        json={
            "question": question,
            "intent": "daily_brief",
            "from_date": "2026-08-01",
            "to_date": "2026-08-31",
        },
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["intent"] == "daily_brief"
    assert payload["mode"] == "deterministic_evidence"
    assert payload["priority"] == "critical"
    assert payload["guardrails"] == {
        "read_only": True,
        "mutations_performed": [],
        "raw_question_retained": False,
        "cross_tenant_access": False,
        "external_model_called": False,
    }
    assert {item["code"] for item in payload["findings"]} >= {
        "period_throughput",
        "backlog_exposure",
        "service_outcomes",
        "inventory_readiness",
        "integration_delivery_health",
    }
    assert _evidence_value(
        payload, "integration_delivery_health", "failed_outbound"
    ) == 1
    assert _evidence_value(payload, "backlog_exposure", "period_end_backlog") == 1
    assert _evidence_value(payload, "inventory_readiness", "open_notifications") == 1
    assert response.headers["cache-control"] == "no-store"

    digest = sha256(question.encode("utf-8")).hexdigest()
    with client.app.state.testing_session_local() as db:
        assert db.scalar(select(func.count(WorkOrder.id))) == before_work_orders
        assert db.scalar(select(func.count(InventoryTransaction.id))) == before_inventory
        run = db.scalar(select(EnterpriseAgentRun))
        assert run is not None
        assert run.question_sha256 == digest
        assert question not in run.filters_json
        assert question not in run.tools_json
        audit = db.scalar(
            select(AuditLog).where(AuditLog.action == "enterprise_agent_run_completed")
        )
        assert audit is not None
        assert question not in (audit.metadata_json or "")
        metadata = json.loads(audit.metadata_json)
        assert metadata["question_sha256"] == digest
        assert metadata["read_only"] is True
        usage = db.scalar(select(OrganizationUsagePeriod))
        assert usage is not None and usage.ai_requests == 1

    history = client.get("/api/agent/runs")
    assert history.status_code == 200
    assert history.json()[0]["question_sha256"] == digest
    assert history.json()[0]["tools_used"] == payload["tools_used"]


def test_enterprise_agent_intent_filters_validation_and_ai_limit(client):
    seeded = _seed_operational_risks(client)
    with client.app.state.testing_session_local() as db:
        organization = db.get(Organization, 1)
        organization.ai_monthly_limit = 1
        db.commit()

    missing_date = client.post(
        "/api/agent/operations",
        json={"question": "检查库存和补货风险", "from_date": "2026-08-01"},
    )
    assert missing_date.status_code == 422
    with client.app.state.testing_session_local() as db:
        assert db.scalar(select(OrganizationUsagePeriod)) is None

    first = client.post(
        "/api/agent/operations",
        json={
            "question": "检查库存和补货风险",
            "from_date": "2026-08-01",
            "to_date": "2026-08-31",
            "engineer_id": seeded["engineer"]["id"],
            "job_type": "Repair",
        },
    )
    assert first.status_code == 200, first.text
    assert first.json()["intent"] == "inventory_risk"
    assert [item["code"] for item in first.json()["findings"]] == [
        "inventory_readiness"
    ]
    assert first.json()["filters"]["engineer_id"] == seeded["engineer"]["id"]

    exhausted = client.post(
        "/api/agent/operations",
        json={"question": "What is our service quality?", "intent": "service_quality"},
    )
    assert exhausted.status_code == 429
    assert "AI monthly limit reached (1)" in exhausted.json()["detail"]
    with client.app.state.testing_session_local() as db:
        usage = db.scalar(select(OrganizationUsagePeriod))
        assert usage is not None and usage.ai_requests == 1
        assert db.scalar(select(func.count(EnterpriseAgentRun.id))) == 1


def test_enterprise_agent_permission_defaults_allow_deny_and_delegation(client):
    original_rbac = settings.rbac_enforce
    original_legacy = settings.legacy_header_auth
    try:
        settings.rbac_enforce = False
        admin = _create_user(client, "Agent Admin", "admin")
        settings.rbac_enforce = True
        settings.legacy_header_auth = True
        manager = _create_user(client, "Agent Manager", "manager", _headers(admin["id"]))
        warehouse = _create_user(client, "Agent Warehouse", "warehouse", _headers(admin["id"]))
        request = {"question": "Give me today's operating brief."}

        matrix = client.get("/api/permissions/me", headers=_headers(manager["id"]))
        assert matrix.status_code == 200
        assert "agent.use" in matrix.json()["effective_permissions"]
        assert client.post(
            "/api/agent/operations", headers=_headers(manager["id"]), json=request
        ).status_code == 200

        denied = client.post(
            "/api/agent/operations", headers=_headers(warehouse["id"]), json=request
        )
        assert denied.status_code == 403
        assert denied.json()["detail"] == "Permission required: agent.use"

        granted = _set_permission(client, admin["id"], warehouse["id"], "allow")
        assert granted.status_code == 200, granted.text
        delegated_options = client.get(
            "/api/agent/options", headers=_headers(warehouse["id"])
        )
        assert delegated_options.status_code == 200
        assert delegated_options.json()["engineers"] == []
        assert client.post(
            "/api/agent/operations", headers=_headers(warehouse["id"]), json=request
        ).status_code == 200
        engineer_filter_denied = client.post(
            "/api/agent/operations",
            headers=_headers(warehouse["id"]),
            json={**request, "engineer_id": manager["id"]},
        )
        assert engineer_filter_denied.status_code == 403
        assert engineer_filter_denied.json()["detail"] == "Permission required: users.read"

        removed = _set_permission(client, admin["id"], manager["id"], "deny")
        assert removed.status_code == 200
        assert client.get(
            "/api/agent/runs", headers=_headers(manager["id"])
        ).status_code == 403
    finally:
        settings.rbac_enforce = original_rbac
        settings.legacy_header_auth = original_legacy
