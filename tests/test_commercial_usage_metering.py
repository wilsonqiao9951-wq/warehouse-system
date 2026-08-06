from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from threading import Barrier

from fastapi import HTTPException
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import sessionmaker

from app.core.database import Base, configure_sqlite_connection
from app.models import Organization, OrganizationUsagePeriod
from app.services.commercial import consume_monthly_usage, organization_usage


def _create_work_order(client, ticket: str = "METER-100") -> dict:
    response = client.post(
        "/api/work-orders",
        json={
            "ticket_number": ticket,
            "machine_type": "ACME-9000",
            "job_type": "repair",
            "problem_description": "Compressor alarm",
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def _create_integration(client) -> dict:
    response = client.post(
        "/api/integrations",
        json={
            "name": "Metered external API",
            "provider": "generic",
            "field_mapping": {},
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_starter_blocks_metered_features_without_recording_usage(client):
    work_order = _create_work_order(client)
    secret = _create_integration(client)
    with client.app.state.testing_session_local() as db:
        organization = db.get(Organization, 1)
        assert organization is not None
        organization.plan_code = "starter"
        organization.ai_monthly_limit = 0
        organization.api_monthly_limit = 0
        db.commit()

    ai_response = client.get(
        f"/api/work-orders/{work_order['id']}/part-recommendations"
    )
    assert ai_response.status_code == 403
    assert ai_response.json()["detail"] == "AI capability is not included in this plan."

    api_response = client.get(
        "/api/external/v1/inventory",
        headers={"X-API-Key": secret["api_key"]},
    )
    assert api_response.status_code == 403
    assert api_response.json()["detail"] == "API capability is not included in this plan."

    missing = client.get("/api/work-orders/999999/part-recommendations")
    assert missing.status_code == 404
    usage = client.get("/api/organization/settings")
    assert usage.status_code == 200
    assert usage.json()["ai_monthly_used"] == 0
    assert usage.json()["api_monthly_used"] == 0
    assert usage.json()["usage_period_start"] == datetime.utcnow().date().replace(day=1).isoformat()


def test_ai_limit_is_hard_and_new_utc_month_uses_a_new_period(client):
    work_order = _create_work_order(client)
    with client.app.state.testing_session_local() as db:
        organization = db.get(Organization, 1)
        assert organization is not None
        organization.ai_monthly_limit = 2
        db.commit()

    first = client.get(
        f"/api/work-orders/{work_order['id']}/part-recommendations"
    )
    second = client.get(
        f"/api/work-orders/{work_order['id']}/service-intelligence"
    )
    exhausted = client.get(
        f"/api/work-orders/{work_order['id']}/part-recommendations"
    )
    assert first.status_code == 200, first.text
    assert second.status_code == 200, second.text
    assert exhausted.status_code == 429
    assert "AI monthly limit reached (2)" in exhausted.json()["detail"]

    settings = client.get("/api/organization/settings").json()
    assert settings["ai_monthly_used"] == 2

    current = datetime.utcnow()
    next_month = datetime(
        current.year + (1 if current.month == 12 else 0),
        1 if current.month == 12 else current.month + 1,
        3,
    )
    with client.app.state.testing_session_local() as db:
        consume_monthly_usage(db, 1, ai_requests=1, now=next_month)
        db.commit()
        next_usage = organization_usage(db, 1, now=next_month)
        assert next_usage["ai_monthly_used"] == 1
        assert next_usage["usage_period_start"] == next_month.date().replace(day=1)
        periods = db.scalars(
            select(OrganizationUsagePeriod)
            .where(OrganizationUsagePeriod.organization_id == 1)
            .order_by(OrganizationUsagePeriod.period_start)
        ).all()
        assert [(row.period_start, row.ai_requests) for row in periods] == [
            (current.date().replace(day=1), 2),
            (next_month.date().replace(day=1), 1),
        ]

        unlimited = Organization(
            name="Unlimited Usage Tenant",
            slug="unlimited-usage-tenant",
            plan_code="enterprise",
            ai_monthly_limit=None,
            api_monthly_limit=None,
        )
        db.add(unlimited)
        db.flush()
        unlimited.ai_monthly_limit = None
        unlimited.api_monthly_limit = None
        db.commit()
        db.refresh(unlimited)
        consume_monthly_usage(
            db,
            unlimited.id,
            ai_requests=5_000,
            api_requests=5_000,
            now=next_month,
        )
        db.commit()
        unlimited_usage = organization_usage(db, unlimited.id, now=next_month)
        assert unlimited_usage["ai_monthly_used"] == 5_000
        assert unlimited_usage["api_monthly_used"] == 5_000

        db.info["organization_id"] = 1
        tenant_rows = db.scalars(select(OrganizationUsagePeriod)).all()
        assert tenant_rows
        assert all(row.organization_id == 1 for row in tenant_rows)


def test_external_idempotency_and_combined_ai_api_charging(client):
    secret = _create_integration(client)
    api_key = secret["api_key"]
    with client.app.state.testing_session_local() as db:
        organization = db.get(Organization, 1)
        assert organization is not None
        organization.ai_monthly_limit = 2
        organization.api_monthly_limit = 2
        db.commit()

    payload = {
        "external_id": "metered-row-1",
        "data": {
            "ticket_number": "EXT-METER-1",
            "machine_type": "ACME-9000",
            "job_type": "repair",
        },
    }
    headers = {
        "X-API-Key": api_key,
        "X-Idempotency-Key": "metered-create-1",
    }
    created = client.post("/api/external/v1/work-orders", headers=headers, json=payload)
    replayed = client.post("/api/external/v1/work-orders", headers=headers, json=payload)
    assert created.status_code == 200, created.text
    assert replayed.status_code == 200, replayed.text
    assert replayed.json()["replayed"] is True

    recommendations = client.get(
        "/api/external/v1/work-orders/metered-row-1/recommendations",
        headers={"X-API-Key": api_key},
    )
    assert recommendations.status_code == 200, recommendations.text

    exhausted = client.get(
        "/api/external/v1/inventory",
        headers={"X-API-Key": api_key},
    )
    assert exhausted.status_code == 429
    missing = client.get(
        "/api/external/v1/work-orders/not-linked",
        headers={"X-API-Key": api_key},
    )
    assert missing.status_code == 404

    settings = client.get("/api/organization/settings").json()
    assert settings["api_monthly_used"] == 2
    assert settings["ai_monthly_used"] == 1


def test_file_sqlite_serializes_competing_final_ai_request(tmp_path):
    database_path = (tmp_path / "commercial-usage.db").as_posix()
    engine = create_engine(
        f"sqlite:///{database_path}",
        connect_args={"check_same_thread": False},
        pool_pre_ping=True,
    )
    event.listen(engine, "connect", configure_sqlite_connection)
    Base.metadata.create_all(engine)
    Session = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    with Session() as db:
        db.add(
            Organization(
                id=1,
                name="Usage Concurrency",
                slug="usage-concurrency",
                ai_monthly_limit=1,
            )
        )
        db.commit()

    barrier = Barrier(2)

    def consume(index: int) -> str:
        with Session() as db:
            db.info["organization_id"] = 1
            barrier.wait(timeout=5)
            try:
                consume_monthly_usage(db, 1, ai_requests=1)
                db.commit()
                return f"consumed-{index}"
            except HTTPException as exc:
                db.rollback()
                assert exc.status_code == 429
                return "limit"

    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            outcomes = list(executor.map(consume, (1, 2)))
        assert outcomes.count("limit") == 1
        assert sum(outcome.startswith("consumed-") for outcome in outcomes) == 1
        with Session() as db:
            db.info["organization_id"] = 1
            usage = db.scalar(select(OrganizationUsagePeriod))
            assert usage is not None
            assert usage.ai_requests == 1
    finally:
        engine.dispose()
