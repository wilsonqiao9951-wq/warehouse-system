from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, select

from app.core.database import SessionLocal, set_platform_database_scope
from app.models import OperationsAlertDelivery, OperationsAlertIncident
from app.services.operations_alerts import reconcile_operations_alerts


VERIFY_CODE = "verification_operations_alert"


def _clear() -> None:
    with SessionLocal() as db:
        set_platform_database_scope(db)
        incident_ids = db.scalars(
            select(OperationsAlertIncident.id).where(
                OperationsAlertIncident.alert_code == VERIFY_CODE
            )
        ).all()
        if incident_ids:
            db.execute(
                delete(OperationsAlertDelivery).where(
                    OperationsAlertDelivery.incident_id.in_(incident_ids)
                )
            )
            db.execute(
                delete(OperationsAlertIncident).where(
                    OperationsAlertIncident.id.in_(incident_ids)
                )
            )
        db.commit()


def main() -> int:
    _clear()
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    alert = {
        "code": VERIFY_CODE,
        "severity": "critical",
        "message": "Verification-only aggregate operational risk.",
        "count": 2,
    }
    try:
        with SessionLocal() as db:
            set_platform_database_scope(db)
            assert reconcile_operations_alerts(db, [alert], now=now) == (1, 1)
            db.commit()
            incident = db.scalar(
                select(OperationsAlertIncident).where(
                    OperationsAlertIncident.alert_code == VERIFY_CODE,
                    OperationsAlertIncident.status == "open",
                )
            )
            assert incident is not None
            delivery = db.scalar(
                select(OperationsAlertDelivery).where(
                    OperationsAlertDelivery.incident_id == incident.id
                )
            )
            assert delivery is not None
            assert delivery.event_type == "triggered"
            assert delivery.status == "pending"
            assert len(delivery.idempotency_key) == 64
            assert len(delivery.request_hash) == 64

            transitions, queued = reconcile_operations_alerts(
                db,
                [alert],
                now=now + timedelta(minutes=1),
            )
            db.commit()
            assert (transitions, queued) == (0, 0)
            assert db.query(OperationsAlertIncident).filter_by(
                alert_code=VERIFY_CODE,
                status="open",
            ).count() == 1
            assert db.query(OperationsAlertDelivery).filter_by(
                incident_id=incident.id
            ).count() == 1

            assert reconcile_operations_alerts(
                db,
                [],
                now=now + timedelta(minutes=2),
            ) == (1, 1)
            db.commit()
            db.refresh(incident)
            assert incident.status == "resolved"
            events = db.scalars(
                select(OperationsAlertDelivery.event_type)
                .where(OperationsAlertDelivery.incident_id == incident.id)
                .order_by(OperationsAlertDelivery.id)
            ).all()
            assert events == ["triggered", "resolved"]
        print(
            "Operations alert verification passed: durable trigger, idempotent observation, and resolved delivery."
        )
        return 0
    finally:
        _clear()


if __name__ == "__main__":
    raise SystemExit(main())
