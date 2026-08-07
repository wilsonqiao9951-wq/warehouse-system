from __future__ import annotations

from dataclasses import dataclass
import re
import unicodedata

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Part, PartMachineAssociation, WorkOrder
from app.services.recommendations import build_part_recommendations


@dataclass(frozen=True)
class VisualCandidateSuggestion:
    part: Part
    confidence: float
    reason: str


def _normalize(value: str | None) -> str:
    return unicodedata.normalize("NFKC", value or "").strip().casefold()


def _tokens(value: str | None) -> set[str]:
    return {
        token
        for token in re.findall(r"[^\W_]+", _normalize(value))
        if len(token) > 1
    }


def generate_visual_part_candidates(
    db: Session,
    *,
    machine_model: str | None,
    label_text: str | None,
    work_order: WorkOrder | None,
    limit: int = 5,
) -> list[VisualCandidateSuggestion]:
    """Rank safe candidates from existing tenant knowledge.

    This foundation intentionally does not claim that the image bytes have been
    classified by a vision model. It combines label text, machine knowledge, and
    completed-work history so later OCR/CV providers can add signals without
    bypassing the same human-controlled candidate lifecycle.
    """

    parts = db.scalars(
        select(Part).where(Part.is_active.is_(True)).order_by(Part.id)
    ).all()
    if not parts:
        return []

    normalized_machine = _normalize(machine_model)
    normalized_label = _normalize(label_text)
    label_tokens = _tokens(label_text)
    signals: dict[int, list[tuple[float, str]]] = {}

    for part in parts:
        part_signals: list[tuple[float, str]] = []
        normalized_number = _normalize(part.part_number)
        normalized_barcode = _normalize(part.barcode)
        if normalized_label and normalized_number and normalized_number in normalized_label:
            part_signals.append((0.92, "part number appears in label text"))
        if normalized_label and normalized_barcode and normalized_barcode in normalized_label:
            part_signals.append((0.95, "barcode appears in label text"))

        name_tokens = _tokens(" ".join(filter(None, (part.name, part.english_name))))
        if label_tokens and name_tokens:
            overlap = len(label_tokens & name_tokens) / len(label_tokens | name_tokens)
            if overlap >= 0.2:
                part_signals.append(
                    (min(0.82, 0.45 + overlap * 0.4), "part name resembles label text")
                )
        if (
            normalized_machine
            and _normalize(part.machine_type)
            and normalized_machine == _normalize(part.machine_type)
        ):
            part_signals.append((0.58, "part catalog lists the same machine"))
        if part_signals:
            signals[part.id] = part_signals

    if normalized_machine:
        associations = db.scalars(
            select(PartMachineAssociation).where(
                PartMachineAssociation.machine_model.ilike(machine_model.strip())
            )
        ).all()
        for association in associations:
            if _normalize(association.machine_model) != normalized_machine:
                continue
            confidence = min(
                0.88,
                max(0.55, association.confidence * 0.7)
                + min(0.20, association.confirmed_count * 0.04),
            )
            signals.setdefault(association.part_id, []).append(
                (confidence, "confirmed photo memory for the same machine")
            )

    if work_order is not None:
        for recommendation in build_part_recommendations(db, work_order):
            signals.setdefault(recommendation.part.id, []).append(
                (
                    min(0.86, 0.42 + recommendation.confidence * 0.44),
                    "completed-job history recommends this part",
                )
            )

    part_by_id = {part.id: part for part in parts}
    ranked: list[tuple[float, Part, str]] = []
    for part_id, part_signals in signals.items():
        part = part_by_id.get(part_id)
        if part is None:
            continue
        strongest = max(value for value, _ in part_signals)
        combined = min(0.95, strongest + min(0.08, (len(part_signals) - 1) * 0.04))
        reasons = list(dict.fromkeys(reason for _, reason in sorted(part_signals, reverse=True)))
        ranked.append((round(combined, 3), part, "; ".join(reasons)))

    ranked.sort(key=lambda item: (-item[0], item[1].part_number))
    return [
        VisualCandidateSuggestion(part=part, confidence=confidence, reason=reason)
        for confidence, part, reason in ranked[:limit]
    ]
