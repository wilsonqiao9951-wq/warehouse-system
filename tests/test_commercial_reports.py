from datetime import date, datetime

from sqlalchemy import select

from app.models import AuditLog, Organization, OrganizationUsagePeriod
from app.services.commercial import current_usage_period


def _previous_month(period_start: date) -> date:
    if period_start.month == 1:
        return date(period_start.year - 1, 12, 1)
    return date(period_start.year, period_start.month - 1, 1)


def test_organization_commercial_report_zero_fills_and_exports_safe_csv(client):
    current = current_usage_period()
    previous = _previous_month(current)
    with client.app.state.testing_session_local() as db:
        organization = db.get(Organization, 1)
        assert organization is not None
        organization.name = "=Formula Customer"
        organization.ai_monthly_limit = 100
        organization.api_monthly_limit = 200
        db.add_all([
            OrganizationUsagePeriod(
                organization_id=1,
                period_start=current,
                ai_requests=12,
                api_requests=34,
                last_ai_used_at=datetime.utcnow(),
            ),
            OrganizationUsagePeriod(
                organization_id=1,
                period_start=previous,
                ai_requests=5,
                api_requests=7,
            ),
        ])
        db.commit()

    report = client.get("/api/organization/commercial-report?months=3")
    assert report.status_code == 200, report.text
    payload = report.json()
    assert payload["organization_name"] == "=Formula Customer"
    assert [row["period_start"] for row in payload["periods"][:2]] == [
        current.isoformat(),
        previous.isoformat(),
    ]
    assert payload["periods"][0]["ai_requests"] == 12
    assert payload["periods"][1]["api_requests"] == 7
    assert payload["periods"][2]["ai_requests"] == 0
    assert payload["ai_monthly_limit"] == 100

    exported = client.post(
        "/api/organization/commercial-report/export",
        json={"months": 3},
    )
    assert exported.status_code == 200, exported.text
    assert exported.headers["content-type"].startswith("text/csv")
    assert "openpartsflow-commercial-usage-test.csv" in exported.headers["content-disposition"]
    assert exported.content.startswith(b"\xef\xbb\xbf")
    csv_text = exported.content.decode("utf-8-sig")
    assert "'=Formula Customer" in csv_text
    assert "organization_name" in csv_text
    assert "current_ai_monthly_limit" in csv_text
    with client.app.state.testing_session_local() as db:
        audit = db.scalar(
            select(AuditLog).where(
                AuditLog.action == "organization_commercial_report_exported"
            )
        )
        assert audit is not None
        assert "account_password" not in (audit.metadata_json or "")


def test_platform_commercial_report_is_period_exact_and_export_is_audited(client):
    current = current_usage_period()
    with client.app.state.testing_session_local() as db:
        second = Organization(
            name="Second Report Customer",
            slug="second-report-customer",
            plan_code="starter",
            ai_monthly_limit=0,
            api_monthly_limit=0,
        )
        db.add(second)
        db.flush()
        second_id = second.id
        db.add(
            OrganizationUsagePeriod(
                organization_id=second_id,
                period_start=current,
                ai_requests=0,
                api_requests=9,
            )
        )
        db.commit()

    report = client.get(
        f"/api/platform/commercial-report?period_start={current.isoformat()}"
    )
    assert report.status_code == 200, report.text
    assert {row["organization_id"] for row in report.json()} == {1, second_id}
    second_row = next(row for row in report.json() if row["organization_id"] == second_id)
    assert second_row["api_requests"] == 9
    assert second_row["api_monthly_limit"] == 0

    invalid_period = client.get("/api/platform/commercial-report?period_start=2026-08-02")
    assert invalid_period.status_code == 422
    exported = client.post(
        "/api/platform/commercial-report/export",
        json={"period_start": current.isoformat()},
    )
    assert exported.status_code == 200, exported.text
    csv_text = exported.content.decode("utf-8-sig")
    assert "Second Report Customer" in csv_text
    assert current.isoformat() in csv_text
    with client.app.state.testing_session_local() as db:
        audit = db.scalar(
            select(AuditLog).where(
                AuditLog.action == "platform_commercial_report_exported"
            )
        )
        assert audit is not None
        assert '"organization_count":2' in (audit.metadata_json or "")
