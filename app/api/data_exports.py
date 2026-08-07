from __future__ import annotations

from collections.abc import Iterator
import json

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.rbac import Actor, get_current_actor, require_roles
from app.core.security import verify_password
from app.models import AuditLog, Organization, OrganizationDataExport, User, UserRole
from app.schemas import OrganizationDataExportRead, OrganizationDataExportRequest
from app.services.data_exports import DataExportTooLarge, build_organization_data_export


router = APIRouter()


def _require_account_reauthentication(
    db: Session,
    actor: Actor,
    password: str | None,
) -> None:
    if actor.auth_method == "test":
        return
    if actor.auth_method != "bearer" or actor.user_id is None:
        raise HTTPException(status_code=401, detail="Bearer authentication required")
    user = db.get(User, actor.user_id)
    if not password or not user or not verify_password(password, user.password_hash):
        raise HTTPException(status_code=401, detail="Account password verification failed")


def _read_export(row: OrganizationDataExport) -> OrganizationDataExportRead:
    try:
        table_counts = json.loads(row.table_counts_json)
    except (TypeError, json.JSONDecodeError):
        table_counts = {}
    return OrganizationDataExportRead(
        id=row.id,
        organization_id=row.organization_id,
        requested_by=row.requested_by,
        format_version=row.format_version,
        sha256=row.sha256,
        size_bytes=row.size_bytes,
        record_count=row.record_count,
        file_count=row.file_count,
        missing_file_count=row.missing_file_count,
        include_files=row.include_files,
        table_counts=table_counts,
        generated_at=row.generated_at,
    )


def _stream_and_close(stream) -> Iterator[bytes]:
    try:
        while chunk := stream.read(1024 * 1024):
            yield chunk
    finally:
        stream.close()


@router.get(
    "/organization/data-exports",
    response_model=list[OrganizationDataExportRead],
)
def list_organization_data_exports(
    limit: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
    actor: Actor = Depends(get_current_actor),
):
    require_roles(actor, UserRole.ADMIN)
    rows = db.scalars(
        select(OrganizationDataExport)
        .order_by(
            OrganizationDataExport.generated_at.desc(),
            OrganizationDataExport.id.desc(),
        )
        .limit(limit)
    ).all()
    return [_read_export(row) for row in rows]


@router.post("/organization/data-exports")
def create_organization_data_export(
    payload: OrganizationDataExportRequest,
    db: Session = Depends(get_db),
    actor: Actor = Depends(get_current_actor),
):
    require_roles(actor, UserRole.ADMIN)
    _require_account_reauthentication(db, actor, payload.account_password)
    organization = db.get(Organization, actor.organization_id)
    if not organization:
        raise HTTPException(status_code=404, detail="Organization not found")
    try:
        bundle = build_organization_data_export(
            db,
            organization,
            include_files=payload.include_files,
        )
    except DataExportTooLarge as exc:
        raise HTTPException(status_code=413, detail=str(exc)) from exc

    evidence = OrganizationDataExport(
        organization_id=organization.id,
        requested_by=actor.user_id,
        sha256=bundle.sha256,
        size_bytes=bundle.size_bytes,
        record_count=bundle.record_count,
        file_count=bundle.file_count,
        missing_file_count=bundle.missing_file_count,
        include_files=payload.include_files,
        table_counts_json=json.dumps(
            bundle.table_counts,
            sort_keys=True,
            separators=(",", ":"),
        ),
        generated_at=bundle.generated_at,
    )
    db.add(evidence)
    db.flush()
    db.add(
        AuditLog(
            organization_id=organization.id,
            user_id=actor.user_id,
            action="organization_data_export_generated",
            entity_type="organization_data_export",
            entity_id=evidence.id,
            metadata_json=json.dumps(
                {
                    "actor_role": actor.role.value,
                    "auth_method": actor.auth_method,
                    "format_version": evidence.format_version,
                    "sha256": evidence.sha256,
                    "size_bytes": evidence.size_bytes,
                    "record_count": evidence.record_count,
                    "file_count": evidence.file_count,
                    "missing_file_count": evidence.missing_file_count,
                    "include_files": evidence.include_files,
                },
                separators=(",", ":"),
            ),
            timestamp=bundle.generated_at,
        )
    )
    try:
        db.commit()
    except Exception:
        bundle.stream.close()
        raise

    safe_slug = "".join(
        character
        for character in organization.slug
        if character.isascii() and (character.isalnum() or character in "-_.")
    ) or f"organization-{organization.id}"
    filename = f"openpartsflow-backup-{safe_slug}-{bundle.generated_at:%Y%m%dT%H%M%SZ}.zip"
    return StreamingResponse(
        _stream_and_close(bundle.stream),
        media_type="application/zip",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "X-OpenPartsFlow-Export-Id": str(evidence.id),
            "X-OpenPartsFlow-SHA256": evidence.sha256,
        },
    )
