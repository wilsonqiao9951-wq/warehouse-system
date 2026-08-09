from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_db
from app.core.rbac import (
    Actor,
    get_current_actor,
    require_work_order_execution_scope,
    require_work_order_scope,
)
from app.models import AuditLog, WorkOrderMedia
from app.schemas import WorkOrderMediaRead
from app.services.work_order_media import (
    MAX_MEDIA_PER_WORK_ORDER,
    detect_work_order_media,
    file_sha256,
    media_request_fingerprint,
    normalize_media_caption,
    normalize_media_category,
    safe_media_path,
    safe_original_filename,
    work_order_media_read,
)


router = APIRouter(prefix="/work-orders", tags=["work-order-media"])


def _utcnow_naive() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _may_view_private_attribution(actor: Actor, row: WorkOrderMedia) -> bool:
    return actor.role.value in {"admin", "manager"} or row.created_by == actor.user_id


def _audit(
    db: Session,
    actor: Actor,
    action: str,
    media_id: int,
    metadata: dict,
) -> None:
    db.add(
        AuditLog(
            organization_id=actor.organization_id,
            user_id=actor.user_id,
            action=action,
            entity_type="work_order_media",
            entity_id=media_id,
            metadata_json=json.dumps(
                {
                    "actor_role": actor.role.value,
                    "auth_method": actor.auth_method,
                    "device_record_id": actor.device_record_id,
                    **metadata,
                },
                separators=(",", ":"),
                sort_keys=True,
            ),
            timestamp=_utcnow_naive(),
        )
    )


def _media_or_404(
    db: Session,
    organization_id: int,
    work_order_id: int,
    media_id: int,
) -> WorkOrderMedia:
    row = db.scalar(
        select(WorkOrderMedia).where(
            WorkOrderMedia.id == media_id,
            WorkOrderMedia.organization_id == organization_id,
            WorkOrderMedia.work_order_id == work_order_id,
        )
    )
    if not row:
        raise HTTPException(status_code=404, detail="Work-order media not found")
    return row


@router.get("/{work_order_id}/media", response_model=list[WorkOrderMediaRead])
def list_work_order_media(
    work_order_id: int,
    limit: int = Query(default=100, ge=1, le=100),
    db: Session = Depends(get_db),
    actor: Actor = Depends(get_current_actor),
):
    require_work_order_scope(db, actor, work_order_id)
    rows = db.scalars(
        select(WorkOrderMedia)
        .where(
            WorkOrderMedia.organization_id == actor.organization_id,
            WorkOrderMedia.work_order_id == work_order_id,
        )
        .order_by(WorkOrderMedia.created_at.desc(), WorkOrderMedia.id.desc())
        .limit(limit)
    ).all()
    return [
        work_order_media_read(
            row,
            include_private_attribution=_may_view_private_attribution(actor, row),
        )
        for row in rows
    ]


@router.post("/{work_order_id}/media", response_model=WorkOrderMediaRead)
async def create_work_order_media(
    work_order_id: int,
    file: UploadFile = File(...),
    category: str = Form(..., min_length=2, max_length=24),
    caption: str | None = Form(default=None, max_length=500),
    client_request_id: str = Form(
        ...,
        min_length=8,
        max_length=100,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]{7,99}$",
    ),
    db: Session = Depends(get_db),
    actor: Actor = Depends(get_current_actor),
):
    work_order = require_work_order_execution_scope(db, actor, work_order_id)
    if work_order.is_locked or work_order.status == "PENDING_APPROVAL":
        raise HTTPException(
            status_code=409,
            detail="Work order cannot accept media in its current state",
        )

    normalized_category = normalize_media_category(category)
    normalized_caption = normalize_media_caption(caption)
    original_filename = safe_original_filename(file.filename)
    data = await file.read(settings.max_knowledge_media_upload_bytes + 1)
    if len(data) > settings.max_knowledge_media_upload_bytes:
        raise HTTPException(status_code=413, detail="Media exceeds the configured upload limit")
    media_signature = detect_work_order_media(data)
    if media_signature is None:
        raise HTTPException(status_code=400, detail="Unsupported or invalid photo/video file")
    media_type, extension, mime_type = media_signature
    digest = sha256(data).hexdigest()
    request_fingerprint = media_request_fingerprint(
        work_order_id=work_order_id,
        category=normalized_category,
        caption=normalized_caption,
        file_sha256=digest,
        size_bytes=len(data),
        media_type=media_type,
        mime_type=mime_type,
        original_filename=original_filename,
        created_by=actor.user_id,
        created_device_id=actor.device_record_id,
        claim_version=work_order.claim_version,
    )
    existing = db.scalar(
        select(WorkOrderMedia).where(
            WorkOrderMedia.organization_id == actor.organization_id,
            WorkOrderMedia.client_request_id == client_request_id,
        )
    )
    if existing:
        if existing.request_fingerprint != request_fingerprint:
            raise HTTPException(
                status_code=409,
                detail="Client request ID was already used for different media evidence",
            )
        return work_order_media_read(existing, include_private_attribution=True)

    media_count = db.scalar(
        select(func.count(WorkOrderMedia.id)).where(
            WorkOrderMedia.organization_id == actor.organization_id,
            WorkOrderMedia.work_order_id == work_order_id,
        )
    ) or 0
    if media_count >= MAX_MEDIA_PER_WORK_ORDER:
        raise HTTPException(status_code=409, detail="Work order media limit reached")

    storage_key = (
        f"work-order-media/{actor.organization_id}/{work_order_id}/"
        f"{uuid4().hex}{extension}"
    )
    target = Path(settings.data_export_private_files_root) / storage_key
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)
    row = WorkOrderMedia(
        organization_id=actor.organization_id,
        work_order_id=work_order_id,
        category=normalized_category,
        caption=normalized_caption,
        media_type=media_type,
        mime_type=mime_type,
        size_bytes=len(data),
        file_sha256=digest,
        request_fingerprint=request_fingerprint,
        media_storage_key=storage_key,
        original_filename=original_filename,
        client_request_id=client_request_id,
        created_by=actor.user_id,
        created_device_id=actor.device_record_id,
        claim_version=work_order.claim_version,
        created_at=_utcnow_naive(),
    )
    try:
        db.add(row)
        db.flush()
        _audit(
            db,
            actor,
            "create_work_order_media",
            row.id,
            {
                "category": row.category,
                "claim_version": row.claim_version,
                "file_sha256": row.file_sha256,
                "media_type": row.media_type,
                "mime_type": row.mime_type,
                "size_bytes": row.size_bytes,
                "work_order_id": row.work_order_id,
            },
        )
        db.commit()
    except IntegrityError:
        db.rollback()
        target.unlink(missing_ok=True)
        concurrent = db.scalar(
            select(WorkOrderMedia).where(
                WorkOrderMedia.organization_id == actor.organization_id,
                WorkOrderMedia.client_request_id == client_request_id,
            )
        )
        if concurrent and concurrent.request_fingerprint == request_fingerprint:
            return work_order_media_read(concurrent, include_private_attribution=True)
        raise HTTPException(
            status_code=409,
            detail="Client request ID was already used for different media evidence",
        )
    except Exception:
        db.rollback()
        target.unlink(missing_ok=True)
        raise
    db.refresh(row)
    return work_order_media_read(row, include_private_attribution=True)


@router.get("/{work_order_id}/media/{media_id}/content")
def get_work_order_media_content(
    work_order_id: int,
    media_id: int,
    db: Session = Depends(get_db),
    actor: Actor = Depends(get_current_actor),
):
    require_work_order_scope(db, actor, work_order_id)
    row = _media_or_404(db, actor.organization_id, work_order_id, media_id)
    target = safe_media_path(Path(settings.data_export_private_files_root), row)
    if not target.is_file():
        raise HTTPException(status_code=404, detail="Work-order media file is unavailable")
    if target.stat().st_size != row.size_bytes or file_sha256(target) != row.file_sha256:
        raise HTTPException(status_code=409, detail="Work-order media integrity check failed")
    return FileResponse(
        target,
        media_type=row.mime_type,
        filename=f"work-order-{work_order_id}-media-{media_id}{target.suffix}",
        content_disposition_type="inline",
        headers={
            "Cache-Control": "private, no-store",
            "Content-Security-Policy": "sandbox; default-src 'none'",
            "X-Content-Type-Options": "nosniff",
        },
    )
