from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
import re
import unicodedata

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import (
    MachineKnowledgeEntry,
    MachineKnowledgeProfile,
    Part,
    WorkOrder,
    WorkOrderPart,
)
from app.schemas import (
    MachineKnowledgePartRead,
    ServiceIntelligenceFaultAnalysis,
    ServiceIntelligenceKnowledgeEntry,
    ServiceIntelligencePattern,
    ServiceIntelligenceSimilarWorkOrder,
    ServiceHistoryPart,
    WorkOrderServiceIntelligence,
)


@dataclass(frozen=True)
class _SimilarMatch:
    work_order: WorkOrder
    confidence: float
    factors: tuple[str, ...]


def _normalize(value: str | None) -> str:
    return unicodedata.normalize("NFKC", value or "").strip().casefold()


def _tokens(*values: str | None) -> set[str]:
    normalized = _normalize(" ".join(value for value in values if value))
    return {
        token
        for token in re.findall(r"[^\W_]+", normalized)
        if len(token) > 1
    }


def _jaccard(left: set[str], right: set[str]) -> float:
    if not left or not right:
        return 0.0
    return len(left & right) / len(left | right)


def _similarity(
    target: WorkOrder,
    historical: WorkOrder,
) -> tuple[float, tuple[str, ...]]:
    score = 0.0
    factors: list[str] = []
    comparisons = (
        ("same machine model", target.machine_type, historical.machine_type, 0.40),
        ("same work type", target.job_type, historical.job_type, 0.15),
        ("same fault type", target.fault_type, historical.fault_type, 0.15),
        ("same error code", target.error_code, historical.error_code, 0.15),
    )
    for label, target_value, history_value, weight in comparisons:
        if _normalize(target_value) and _normalize(target_value) == _normalize(history_value):
            score += weight
            factors.append(label)

    symptom_similarity = _jaccard(
        _tokens(target.problem_description, target.description),
        _tokens(historical.problem_description, historical.description),
    )
    if symptom_similarity >= 0.15:
        score += symptom_similarity * 0.15
        factors.append("similar reported symptoms")
    return min(1.0, score), tuple(factors)


def _part_read(part: Part | None) -> MachineKnowledgePartRead | None:
    if not part:
        return None
    return MachineKnowledgePartRead(
        id=part.id,
        part_number=part.part_number,
        name=part.name,
        image_url=part.image_url,
    )


def _parts_by_work_order(
    db: Session,
    organization_id: int,
    work_order_ids: set[int],
) -> dict[int, list[ServiceHistoryPart]]:
    if not work_order_ids:
        return {}
    rows = db.execute(
        select(
            WorkOrderPart.work_order_id,
            Part.part_number,
            Part.name,
            func.sum(WorkOrderPart.quantity),
        )
        .join(Part, Part.id == WorkOrderPart.part_id)
        .where(
            WorkOrderPart.organization_id == organization_id,
            Part.organization_id == organization_id,
            WorkOrderPart.work_order_id.in_(work_order_ids),
        )
        .group_by(WorkOrderPart.work_order_id, Part.part_number, Part.name)
        .order_by(WorkOrderPart.work_order_id, Part.part_number)
    ).all()
    result: dict[int, list[ServiceHistoryPart]] = defaultdict(list)
    for work_order_id, part_number, name, quantity in rows:
        result[work_order_id].append(
            ServiceHistoryPart(
                part_number=part_number,
                name=name,
                quantity=int(quantity or 0),
            )
        )
    return result


def _similar_work_orders(
    db: Session,
    target: WorkOrder,
    organization_id: int,
) -> list[ServiceIntelligenceSimilarWorkOrder]:
    history = db.scalars(
        select(WorkOrder)
        .where(
            WorkOrder.organization_id == organization_id,
            WorkOrder.id != target.id,
            WorkOrder.is_locked.is_(True),
            WorkOrder.completed_at.is_not(None),
            func.lower(WorkOrder.status) == "completed",
        )
        .order_by(WorkOrder.completed_at.desc(), WorkOrder.id.desc())
        .limit(500)
    ).all()
    matches: list[_SimilarMatch] = []
    for historical in history:
        confidence, factors = _similarity(target, historical)
        if confidence >= 0.15 and factors:
            matches.append(_SimilarMatch(historical, confidence, factors))
    matches.sort(
        key=lambda item: (
            -item.confidence,
            -(item.work_order.completed_at.timestamp() if item.work_order.completed_at else 0),
            -item.work_order.id,
        )
    )
    matches = matches[:5]
    parts = _parts_by_work_order(
        db,
        organization_id,
        {match.work_order.id for match in matches},
    )
    return [
        ServiceIntelligenceSimilarWorkOrder(
            id=match.work_order.id,
            ticket_number=match.work_order.ticket_number,
            completed_at=match.work_order.completed_at,
            job_type=match.work_order.job_type,
            problem_description=match.work_order.problem_description,
            fault_type=match.work_order.fault_type,
            error_code=match.work_order.error_code,
            repair_result=match.work_order.repair_result,
            final_outcome=match.work_order.final_outcome,
            first_time_fix=match.work_order.first_time_fix,
            is_rework=match.work_order.is_rework,
            repair_duration_minutes=match.work_order.repair_duration_minutes,
            parts_used=parts.get(match.work_order.id, []),
            confidence=round(match.confidence, 3),
            reason="Matched by " + ", ".join(match.factors) + ".",
        )
        for match in matches
    ]


def _top_patterns(values: list[str | None]) -> list[ServiceIntelligencePattern]:
    labels: dict[str, str] = {}
    counts: Counter[str] = Counter()
    for value in values:
        key = _normalize(value)
        if not key:
            continue
        labels.setdefault(key, value.strip())
        counts[key] += 1
    return [
        ServiceIntelligencePattern(value=labels[key], count=count)
        for key, count in sorted(counts.items(), key=lambda item: (-item[1], labels[item[0]]))[:5]
    ]


def _fault_analysis(
    db: Session,
    target: WorkOrder,
    organization_id: int,
) -> ServiceIntelligenceFaultAnalysis:
    model_key = _normalize(target.machine_type)
    if not model_key:
        return ServiceIntelligenceFaultAnalysis(
            machine_model=None,
            summary="Add a machine model to enable model-specific fault analysis.",
            warnings=["No machine model is recorded on this work order."],
        )

    evidence = db.scalars(
        select(WorkOrder)
        .where(
            WorkOrder.organization_id == organization_id,
            WorkOrder.id != target.id,
            WorkOrder.is_locked.is_(True),
            WorkOrder.completed_at.is_not(None),
            func.lower(WorkOrder.status) == "completed",
            func.lower(func.trim(WorkOrder.machine_type)) == model_key,
        )
        .order_by(WorkOrder.completed_at.desc(), WorkOrder.id.desc())
        .limit(1000)
    ).all()
    completed_count = len(evidence)
    labeled = [item for item in evidence if item.first_time_fix is not None]
    first_time_fix_count = sum(1 for item in labeled if item.first_time_fix is True)
    rework_count = sum(1 for item in evidence if item.is_rework)
    durations = [
        item.repair_duration_minutes
        for item in evidence
        if item.repair_duration_minutes is not None
    ]
    first_time_fix_rate = (
        round(first_time_fix_count / len(labeled), 3) if labeled else None
    )
    rework_rate = round(rework_count / completed_count, 3) if completed_count else None
    average_repair_minutes = (
        round(sum(durations) / len(durations), 1) if durations else None
    )
    warnings: list[str] = []
    if completed_count == 0:
        summary = f"No completed evidence is available yet for {target.machine_type.strip()}."
        warnings.append("Do not treat the current result as a learned diagnosis.")
    else:
        statements = [f"{completed_count} completed same-model job(s) were reviewed"]
        if first_time_fix_rate is not None:
            statements.append(f"{round(first_time_fix_rate * 100)}% first-time fix")
        if rework_rate is not None:
            statements.append(f"{round(rework_rate * 100)}% marked as rework")
        if average_repair_minutes is not None:
            statements.append(f"{round(average_repair_minutes)} minute average repair")
        summary = "; ".join(statements) + "."
        if len(labeled) < 3:
            warnings.append("Outcome confidence is limited because fewer than three jobs are labeled.")
        if rework_rate is not None and rework_rate >= 0.25:
            warnings.append("Same-model history has an elevated rework rate; verify the repair before closing.")

    return ServiceIntelligenceFaultAnalysis(
        machine_model=target.machine_type.strip(),
        completed_work_orders=completed_count,
        labeled_outcomes=len(labeled),
        first_time_fix_rate=first_time_fix_rate,
        rework_rate=rework_rate,
        average_repair_minutes=average_repair_minutes,
        top_fault_types=_top_patterns([item.fault_type for item in evidence]),
        top_error_codes=_top_patterns([item.error_code for item in evidence]),
        summary=summary,
        warnings=warnings,
    )


def _knowledge_entries(
    db: Session,
    target: WorkOrder,
    organization_id: int,
) -> list[ServiceIntelligenceKnowledgeEntry]:
    model_key = _normalize(target.machine_type)
    if not model_key:
        return []
    rows = db.execute(
        select(MachineKnowledgeEntry, MachineKnowledgeProfile)
        .join(
            MachineKnowledgeProfile,
            MachineKnowledgeProfile.id == MachineKnowledgeEntry.profile_id,
        )
        .where(
            MachineKnowledgeEntry.organization_id == organization_id,
            MachineKnowledgeProfile.organization_id == organization_id,
            MachineKnowledgeProfile.model_key == model_key,
            MachineKnowledgeProfile.is_active.is_(True),
            MachineKnowledgeEntry.status == "published",
        )
        .order_by(
            MachineKnowledgeEntry.sort_order,
            MachineKnowledgeEntry.published_at.desc(),
            MachineKnowledgeEntry.id,
        )
    ).all()
    part_ids = {
        part_id
        for entry, _ in rows
        for part_id in (entry.related_part_id, entry.alternative_for_part_id)
        if part_id is not None
    }
    parts = (
        {
            part.id: part
            for part in db.scalars(
                select(Part).where(
                    Part.organization_id == organization_id,
                    Part.id.in_(part_ids),
                )
            ).all()
        }
        if part_ids
        else {}
    )

    target_fault_tokens = _tokens(target.fault_type, target.error_code)
    target_symptom_tokens = _tokens(target.problem_description, target.description)
    ranked: list[tuple[float, int, ServiceIntelligenceKnowledgeEntry]] = []
    for entry, profile in rows:
        score = 0.20
        factors = ["published guidance for the exact machine model"]
        if _normalize(target.error_code) and _normalize(target.error_code) == _normalize(entry.fault_code):
            score += 0.35
            factors.append("same error code")
        entry_tokens = _tokens(entry.title, entry.content, entry.fault_code)
        fault_overlap = _jaccard(target_fault_tokens, entry_tokens)
        if fault_overlap:
            score += min(0.25, fault_overlap * 0.35)
            factors.append("matching fault terms")
        symptom_overlap = _jaccard(target_symptom_tokens, entry_tokens)
        if symptom_overlap:
            score += min(0.20, symptom_overlap * 0.30)
            factors.append("matching symptom terms")
        ranked.append(
            (
                min(1.0, score),
                entry.sort_order,
                ServiceIntelligenceKnowledgeEntry(
                    id=entry.id,
                    profile_id=profile.id,
                    machine_model=profile.model,
                    entry_type=entry.entry_type,
                    title=entry.title,
                    content=entry.content,
                    fault_code=entry.fault_code,
                    related_part=_part_read(parts.get(entry.related_part_id)),
                    related_part_role=entry.related_part_role,
                    alternative_for_part=_part_read(parts.get(entry.alternative_for_part_id)),
                    installation_location=entry.installation_location,
                    media_url=entry.media_url,
                    media_mime_type=entry.media_mime_type,
                    published_at=entry.published_at,
                    confidence=round(min(1.0, score), 3),
                    reason="Matched by " + ", ".join(factors) + ".",
                ),
            )
        )
    ranked.sort(key=lambda item: (-item[0], item[1], item[2].title.casefold(), item[2].id))
    return [entry for _, _, entry in ranked[:8]]


def build_service_intelligence(
    db: Session,
    target: WorkOrder,
    organization_id: int,
) -> WorkOrderServiceIntelligence:
    return WorkOrderServiceIntelligence(
        work_order_id=target.id,
        evidence_scope="organization_completed_work_orders_and_published_exact_model_knowledge",
        fault_analysis=_fault_analysis(db, target, organization_id),
        knowledge_entries=_knowledge_entries(db, target, organization_id),
        similar_work_orders=_similar_work_orders(db, target, organization_id),
    )
