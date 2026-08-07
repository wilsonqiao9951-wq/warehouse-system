from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone

from fastapi import HTTPException
from sqlalchemy import and_, case, func, select
from sqlalchemy.orm import Session

from app.models import User, UserRole, WorkOrder, WorkOrderPart
from app.schemas import (
    AnalyticsFilterOption,
    PerformanceDashboardRead,
    PerformanceScorecardRead,
    PerformanceTeamSummaryRead,
)


@dataclass
class _CompletedMetrics:
    completed: int = 0
    first_time_fix_labeled: int = 0
    first_time_fix_success: int = 0
    rework: int = 0
    repair_duration_labeled: int = 0
    repair_duration_minutes: int = 0
    revenue: float = 0.0
    labor_cost: float = 0.0

    def add(self, row) -> None:
        self.completed += int(row[1] or 0)
        self.first_time_fix_labeled += int(row[2] or 0)
        self.first_time_fix_success += int(row[3] or 0)
        self.rework += int(row[4] or 0)
        self.repair_duration_labeled += int(row[5] or 0)
        self.repair_duration_minutes += int(row[6] or 0)
        self.revenue += float(row[7] or 0.0)
        self.labor_cost += float(row[8] or 0.0)


@dataclass
class _PartsMetrics:
    work_orders: int = 0
    quantity: int = 0
    cost: float = 0.0

    def add(self, row) -> None:
        self.work_orders += int(row[1] or 0)
        self.quantity += int(row[2] or 0)
        self.cost += float(row[3] or 0.0)


def _ratio(numerator: float, denominator: float) -> float | None:
    return numerator / denominator if denominator else None


def _rounded_ratio(numerator: float, denominator: float) -> float | None:
    value = _ratio(numerator, denominator)
    return round(value, 4) if value is not None else None


def build_performance_dashboard(
    db: Session,
    organization_id: int,
    *,
    from_date: date,
    to_date: date,
    selected_engineer_id: int | None,
    can_view_team: bool,
    can_view_financials: bool,
) -> PerformanceDashboardRead:
    if to_date < from_date:
        raise HTTPException(status_code=422, detail="to_date must be on or after from_date")
    days = (to_date - from_date).days + 1
    if days > 366:
        raise HTTPException(status_code=422, detail="Performance range cannot exceed 366 days")

    engineers = list(
        db.scalars(
            select(User)
            .where(
                User.organization_id == organization_id,
                User.role == UserRole.ENGINEER,
            )
            .order_by(User.name.asc(), User.id.asc())
        ).all()
    )
    users = {user.id: user for user in engineers}
    if selected_engineer_id is not None and selected_engineer_id not in users:
        raise HTTPException(status_code=404, detail="Engineer not found")

    start_at = datetime.combine(from_date, time.min)
    end_at = datetime.combine(to_date + timedelta(days=1), time.min)
    accountable_engineer = func.coalesce(
        WorkOrder.completed_by_id,
        WorkOrder.claimed_by_id,
        WorkOrder.engineer_id,
        WorkOrder.assigned_user_id,
    )
    assigned_engineer = func.coalesce(
        WorkOrder.engineer_id,
        WorkOrder.assigned_user_id,
    )
    completed_conditions = [
        WorkOrder.organization_id == organization_id,
        func.lower(WorkOrder.status) == "completed",
        WorkOrder.completed_at >= start_at,
        WorkOrder.completed_at < end_at,
    ]
    cohort_conditions = [
        WorkOrder.organization_id == organization_id,
        WorkOrder.created_at >= start_at,
        WorkOrder.created_at < end_at,
    ]
    if selected_engineer_id is not None:
        completed_conditions.append(accountable_engineer == selected_engineer_id)
        cohort_conditions.append(assigned_engineer == selected_engineer_id)

    valid_engineer_ids = set(users)

    def normalized(value: int | None) -> int | None:
        return value if value in valid_engineer_ids else None

    completed: dict[int | None, _CompletedMetrics] = {}
    completed_rows = db.execute(
        select(
            accountable_engineer,
            func.count(WorkOrder.id),
            func.count(WorkOrder.first_time_fix),
            func.coalesce(func.sum(case((WorkOrder.first_time_fix.is_(True), 1), else_=0)), 0),
            func.coalesce(func.sum(case((WorkOrder.is_rework.is_(True), 1), else_=0)), 0),
            func.count(WorkOrder.repair_duration_minutes),
            func.coalesce(func.sum(WorkOrder.repair_duration_minutes), 0),
            func.coalesce(func.sum(WorkOrder.revenue), 0),
            func.coalesce(func.sum(WorkOrder.labor_cost), 0),
        )
        .where(*completed_conditions)
        .group_by(accountable_engineer)
    ).all()
    for row in completed_rows:
        key = normalized(row[0])
        completed.setdefault(key, _CompletedMetrics()).add(row)

    parts: dict[int | None, _PartsMetrics] = {}
    parts_rows = db.execute(
        select(
            accountable_engineer,
            func.count(func.distinct(WorkOrderPart.work_order_id)),
            func.coalesce(func.sum(func.abs(WorkOrderPart.quantity)), 0),
            func.coalesce(func.sum(func.abs(WorkOrderPart.total_cost)), 0),
        )
        .select_from(WorkOrder)
        .join(
            WorkOrderPart,
            and_(
                WorkOrderPart.work_order_id == WorkOrder.id,
                WorkOrderPart.organization_id == organization_id,
            ),
        )
        .where(*completed_conditions)
        .group_by(accountable_engineer)
    ).all()
    for row in parts_rows:
        key = normalized(row[0])
        parts.setdefault(key, _PartsMetrics()).add(row)

    cohort: dict[int | None, tuple[int, int]] = {}
    cohort_rows = db.execute(
        select(
            assigned_engineer,
            func.count(WorkOrder.id),
            func.coalesce(
                func.sum(
                    case(
                        (
                            and_(
                                func.lower(WorkOrder.status) == "completed",
                                WorkOrder.completed_at.is_not(None),
                                WorkOrder.completed_at < end_at,
                            ),
                            1,
                        ),
                        else_=0,
                    )
                ),
                0,
            ),
        )
        .where(*cohort_conditions)
        .group_by(assigned_engineer)
    ).all()
    for row in cohort_rows:
        key = normalized(row[0])
        current_received, current_completed = cohort.get(key, (0, 0))
        cohort[key] = (
            current_received + int(row[1] or 0),
            current_completed + int(row[2] or 0),
        )

    if selected_engineer_id is not None:
        output_ids: list[int | None] = [selected_engineer_id]
    else:
        activity_ids = set(completed) | set(parts) | set(cohort)
        output_ids = sorted(
            {user.id for user in engineers if user.is_active} | (activity_ids - {None}),
            key=lambda value: (users[value].name.lower(), value),
        )
        if None in activity_ids:
            output_ids.append(None)

    scorecards: list[PerformanceScorecardRead] = []
    for engineer_id in output_ids:
        user = users.get(engineer_id) if engineer_id is not None else None
        finished = completed.get(engineer_id, _CompletedMetrics())
        used = parts.get(engineer_id, _PartsMetrics())
        received, cohort_finished = cohort.get(engineer_id, (0, 0))
        completion_rate = _rounded_ratio(cohort_finished, received)
        first_time_fix_rate = _rounded_ratio(
            finished.first_time_fix_success,
            finished.first_time_fix_labeled,
        )
        first_time_fix_coverage = _rounded_ratio(
            finished.first_time_fix_labeled,
            finished.completed,
        ) or 0.0
        rework_rate = _rounded_ratio(finished.rework, finished.completed) or 0.0
        average_duration = _ratio(
            finished.repair_duration_minutes,
            finished.repair_duration_labeled,
        )
        duration_coverage = _rounded_ratio(
            finished.repair_duration_labeled,
            finished.completed,
        ) or 0.0
        parts_usage_coverage = _rounded_ratio(used.work_orders, finished.completed) or 0.0
        parts_quantity_per_completed = _ratio(used.quantity, finished.completed) or 0.0
        parts_cost_per_completed = _ratio(used.cost, finished.completed)
        contribution = finished.revenue - finished.labor_cost - used.cost
        scorecards.append(
            PerformanceScorecardRead(
                engineer_id=engineer_id,
                engineer_name=user.name if user else "Unattributed",
                is_active=bool(user and user.is_active),
                cohort_received=received,
                cohort_completed=cohort_finished,
                completion_rate=completion_rate,
                completed_in_period=finished.completed,
                throughput_per_30_days=round(finished.completed * 30 / days, 2),
                first_time_fix_labeled=finished.first_time_fix_labeled,
                first_time_fix_rate=first_time_fix_rate,
                first_time_fix_coverage=first_time_fix_coverage,
                rework_rate=rework_rate,
                repair_duration_labeled=finished.repair_duration_labeled,
                average_repair_minutes=(round(average_duration, 2) if average_duration is not None else None),
                repair_duration_coverage=duration_coverage,
                parts_usage_work_orders=used.work_orders,
                parts_usage_coverage=parts_usage_coverage,
                parts_quantity=used.quantity,
                parts_quantity_per_completed=round(parts_quantity_per_completed, 2),
                parts_cost=(round(used.cost, 2) if can_view_financials else None),
                parts_cost_per_completed=(
                    round(parts_cost_per_completed, 2)
                    if can_view_financials and parts_cost_per_completed is not None
                    else None
                ),
                parts_cost_to_revenue_rate=(
                    round(used.cost / finished.revenue, 4)
                    if can_view_financials and finished.revenue > 0
                    else None
                ),
                revenue=(round(finished.revenue, 2) if can_view_financials else None),
                labor_cost=(round(finished.labor_cost, 2) if can_view_financials else None),
                contribution=(round(contribution, 2) if can_view_financials else None),
            )
        )

    scorecards.sort(
        key=lambda row: (
            -row.completed_in_period,
            -(row.completion_rate if row.completion_rate is not None else -1),
            row.engineer_name.lower(),
        )
    )
    totals_completed = sum(item.completed for item in completed.values())
    totals_received = sum(value[0] for value in cohort.values())
    totals_cohort_completed = sum(value[1] for value in cohort.values())
    totals_ftf_labeled = sum(item.first_time_fix_labeled for item in completed.values())
    totals_ftf_success = sum(item.first_time_fix_success for item in completed.values())
    totals_rework = sum(item.rework for item in completed.values())
    totals_duration_labeled = sum(item.repair_duration_labeled for item in completed.values())
    totals_duration = sum(item.repair_duration_minutes for item in completed.values())
    totals_parts_quantity = sum(item.quantity for item in parts.values())
    totals_parts_cost = sum(item.cost for item in parts.values())
    team_parts_cost_per_completed = _ratio(totals_parts_cost, totals_completed)

    return PerformanceDashboardRead(
        generated_at=datetime.now(timezone.utc).replace(tzinfo=None),
        viewer_scope="team" if can_view_team else "self",
        can_view_team=can_view_team,
        can_view_financials=can_view_financials,
        from_date=from_date,
        to_date=to_date,
        days=days,
        selected_engineer_id=selected_engineer_id,
        engineer_options=[
            AnalyticsFilterOption(
                value=str(user.id),
                label=f"{user.name}{'' if user.is_active else ' (inactive)'}",
            )
            for user in engineers
        ] if can_view_team else [],
        definitions={
            "completion_rate": "Work orders currently assigned to the engineer and created in the selected UTC period that were completed by period end, divided by that created cohort.",
            "throughput": "Work orders completed by the accountable engineer in the selected UTC period, normalized to 30 days for period comparison.",
            "quality": "First-time-fix excludes unlabeled outcomes; rework uses all completed work orders. Coverage is always shown.",
            "parts_efficiency": "Recorded part quantity and cost on completed work orders. Lower use is not automatically better because job mix and repair complexity differ.",
            "attribution": "Completion uses completed-by, then claim owner, then current engineer/assignee. Non-engineer or missing attribution is disclosed separately to managers.",
        },
        team=PerformanceTeamSummaryRead(
            engineer_count=sum(1 for row in scorecards if row.engineer_id is not None),
            active_engineers=sum(1 for row in scorecards if row.engineer_id is not None and row.is_active),
            cohort_received=totals_received,
            cohort_completed=totals_cohort_completed,
            completion_rate=_rounded_ratio(totals_cohort_completed, totals_received),
            completed_in_period=totals_completed,
            throughput_per_30_days=round(totals_completed * 30 / days, 2),
            first_time_fix_rate=_rounded_ratio(totals_ftf_success, totals_ftf_labeled),
            first_time_fix_coverage=_rounded_ratio(totals_ftf_labeled, totals_completed) or 0.0,
            rework_rate=_rounded_ratio(totals_rework, totals_completed) or 0.0,
            average_repair_minutes=(
                round(totals_duration / totals_duration_labeled, 2)
                if totals_duration_labeled
                else None
            ),
            parts_quantity_per_completed=round(
                _ratio(totals_parts_quantity, totals_completed) or 0.0,
                2,
            ),
            parts_cost_per_completed=(
                round(team_parts_cost_per_completed, 2)
                if can_view_financials and team_parts_cost_per_completed is not None
                else None
            ),
        ),
        scorecards=scorecards,
    )
