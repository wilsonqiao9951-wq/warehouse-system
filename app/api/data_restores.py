from __future__ import annotations

from datetime import datetime, timedelta
from hashlib import sha256
import json
import zipfile

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from sqlalchemy import and_, exists, func, not_, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.rbac import Actor, get_current_actor, require_roles
from app.core.security import verify_password
from app.models import (
    AuditLog,
    Organization,
    OrganizationDataExport,
    OrganizationDataRestore,
    User,
    UserRole,
)
from app.schemas import (
    OrganizationDataRestoreDecision,
    OrganizationDataRetentionCleanup,
    OrganizationDataRetentionCleanupRead,
    OrganizationDataRetentionPolicyUpdate,
    OrganizationDataRetentionRead,
    OrganizationDataRestoreRead,
    OrganizationDataRestoreRollback,
)
from app.services.data_restores import (
    DataRestoreConflict,
    DataRestoreInvalid,
    analyze_restore_archive,
    apply_restore_plan,
    compensate_restore_file_apply,
    compensate_restore_file_rollback,
    copy_restore_upload,
    discard_restore_file_evidence,
    finalize_staged_retention_cleanup,
    list_staged_retention_cleanup_ids,
    prepare_restore_file_rollback,
    prepare_restore_files,
    promote_restore_files,
    reconcile_staged_retention_cleanup,
    rollback_staged_retention_cleanup,
    rollback_restore_files,
    rollback_restore_plan,
    stage_restore_file_evidence_cleanup,
)


router = APIRouter()


def _require_account_reauthentication(
    db: Session,
    actor: Actor,
    password: str | None,
) -> None:
    if actor.auth_method == "test":
        return
    if actor.auth_method not in {"bearer", "cookie"} or actor.user_id is None:
        raise HTTPException(status_code=401, detail="Authenticated session required")
    user = db.get(User, actor.user_id)
    if not password or not user or not verify_password(password, user.password_hash):
        raise HTTPException(status_code=401, detail="Account password verification failed")


def _json_object(value: str) -> dict:
    try:
        parsed = json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _json_list(value: str) -> list[str]:
    try:
        parsed = json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return []
    return [str(item) for item in parsed] if isinstance(parsed, list) else []


def _restore_table_summary(value: str) -> dict:
    summary = _json_object(value)
    for counts in summary.values():
        if isinstance(counts, dict):
            counts.setdefault("creates", 0)
    return summary


def _read_restore(row: OrganizationDataRestore) -> OrganizationDataRestoreRead:
    return OrganizationDataRestoreRead(
        id=row.id,
        organization_id=row.organization_id,
        requested_by=row.requested_by,
        approved_by=row.approved_by,
        rejected_by=row.rejected_by,
        applied_by=row.applied_by,
        rolled_back_by=row.rolled_back_by,
        matched_export_id=row.matched_export_id,
        format_version=row.format_version,
        status=row.status,
        archive_sha256=row.archive_sha256,
        archive_size_bytes=row.archive_size_bytes,
        plan_sha256=row.plan_sha256,
        source_schema_revision=row.source_schema_revision,
        source_exported_at=row.source_exported_at,
        record_count=row.record_count,
        file_count=row.file_count,
        create_count=row.create_count,
        file_create_count=row.file_create_count,
        file_overwrite_count=row.file_overwrite_count,
        file_unchanged_count=row.file_unchanged_count,
        file_conflict_count=row.file_conflict_count,
        update_count=row.update_count,
        unchanged_count=row.unchanged_count,
        conflict_count=row.conflict_count,
        protected_count=row.protected_count,
        table_summary=_restore_table_summary(row.table_summary_json),
        validation_messages=_json_list(row.validation_messages_json),
        approval_note=row.approval_note,
        rollback_size_bytes=row.rollback_size_bytes,
        file_rollback_sha256=row.file_rollback_sha256,
        file_rollback_size_bytes=row.file_rollback_size_bytes,
        rollback_expires_at=row.rollback_expires_at,
        rollback_evidence_purged_at=row.rollback_evidence_purged_at,
        rollback_evidence_purged_by=row.rollback_evidence_purged_by,
        version=row.version,
        approved_at=row.approved_at,
        rejected_at=row.rejected_at,
        applied_at=row.applied_at,
        rolled_back_at=row.rolled_back_at,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _audit(
    db: Session,
    actor: Actor,
    row: OrganizationDataRestore,
    action: str,
    metadata: dict,
) -> None:
    db.add(
        AuditLog(
            organization_id=row.organization_id,
            user_id=actor.user_id,
            action=action,
            entity_type="organization_data_restore",
            entity_id=row.id,
            metadata_json=json.dumps(
                {
                    "actor_role": actor.role.value,
                    "auth_method": actor.auth_method,
                    "archive_sha256": row.archive_sha256,
                    "plan_sha256": row.plan_sha256,
                    "status": row.status,
                    "version": row.version,
                    **metadata,
                },
                sort_keys=True,
                separators=(",", ":"),
            ),
            timestamp=datetime.utcnow(),
        )
    )


def _restore_for_update(
    db: Session,
    actor: Actor,
    restore_id: int,
) -> OrganizationDataRestore:
    row = db.scalar(
        select(OrganizationDataRestore)
        .where(OrganizationDataRestore.id == restore_id)
        .with_for_update()
    )
    if not row or row.organization_id != actor.organization_id:
        raise HTTPException(status_code=404, detail="Restore rehearsal not found")
    return row


def _retention_conditions(
    organization: Organization,
    now: datetime,
):
    export_cutoff = now - timedelta(
        days=organization.data_export_evidence_retention_days
    )
    rehearsal_cutoff = now - timedelta(
        days=organization.data_restore_rehearsal_retention_days
    )
    legacy_rollback_cutoff = now - timedelta(
        days=organization.data_restore_rollback_retention_days
    )
    removable_restore = and_(
        OrganizationDataRestore.organization_id == organization.id,
        OrganizationDataRestore.status.in_(("validated", "rejected", "rolled_back")),
        OrganizationDataRestore.updated_at < rehearsal_cutoff,
    )
    rollback_expired = and_(
        OrganizationDataRestore.organization_id == organization.id,
        OrganizationDataRestore.status == "applied",
        OrganizationDataRestore.rollback_payload_json.is_not(None),
        OrganizationDataRestore.rollback_evidence_purged_at.is_(None),
        or_(
            OrganizationDataRestore.rollback_expires_at <= now,
            and_(
                OrganizationDataRestore.rollback_expires_at.is_(None),
                OrganizationDataRestore.applied_at < legacy_rollback_cutoff,
            ),
        ),
    )
    retained_restore_reference = exists(
        select(OrganizationDataRestore.id).where(
            OrganizationDataRestore.organization_id == organization.id,
            OrganizationDataRestore.matched_export_id == OrganizationDataExport.id,
            not_(
                and_(
                    OrganizationDataRestore.status.in_(
                        ("validated", "rejected", "rolled_back")
                    ),
                    OrganizationDataRestore.updated_at < rehearsal_cutoff,
                )
            ),
        )
    )
    removable_export = and_(
        OrganizationDataExport.organization_id == organization.id,
        OrganizationDataExport.generated_at < export_cutoff,
        not_(retained_restore_reference),
    )
    return (
        export_cutoff,
        rehearsal_cutoff,
        removable_restore,
        rollback_expired,
        removable_export,
    )


def _retention_overview(
    db: Session,
    organization: Organization,
    now: datetime | None = None,
) -> OrganizationDataRetentionRead:
    generated_at = now or datetime.utcnow()
    (
        export_cutoff,
        rehearsal_cutoff,
        removable_restore,
        rollback_expired,
        removable_export,
    ) = _retention_conditions(organization, generated_at)
    return OrganizationDataRetentionRead(
        organization_id=organization.id,
        settings_version=organization.settings_version,
        data_export_evidence_retention_days=(
            organization.data_export_evidence_retention_days
        ),
        data_restore_rehearsal_retention_days=(
            organization.data_restore_rehearsal_retention_days
        ),
        data_restore_rollback_retention_days=(
            organization.data_restore_rollback_retention_days
        ),
        export_cutoff=export_cutoff,
        restore_rehearsal_cutoff=rehearsal_cutoff,
        generated_at=generated_at,
        export_evidence_candidates=db.scalar(
            select(func.count(OrganizationDataExport.id)).where(removable_export)
        )
        or 0,
        restore_rehearsal_candidates=db.scalar(
            select(func.count(OrganizationDataRestore.id)).where(removable_restore)
        )
        or 0,
        rollback_evidence_candidates=db.scalar(
            select(func.count(OrganizationDataRestore.id)).where(rollback_expired)
        )
        or 0,
        rollback_database_bytes=db.scalar(
            select(func.coalesce(func.sum(OrganizationDataRestore.rollback_size_bytes), 0))
            .where(rollback_expired)
        )
        or 0,
        rollback_file_bytes=db.scalar(
            select(
                func.coalesce(
                    func.sum(OrganizationDataRestore.file_rollback_size_bytes), 0
                )
            ).where(rollback_expired)
        )
        or 0,
    )


@router.get(
    "/organization/data-retention",
    response_model=OrganizationDataRetentionRead,
)
def get_organization_data_retention(
    db: Session = Depends(get_db),
    actor: Actor = Depends(get_current_actor),
):
    require_roles(actor, UserRole.ADMIN)
    organization = db.get(Organization, actor.organization_id)
    if not organization:
        raise HTTPException(status_code=404, detail="Organization not found")
    return _retention_overview(db, organization)


@router.put(
    "/organization/data-retention",
    response_model=OrganizationDataRetentionRead,
)
def update_organization_data_retention(
    payload: OrganizationDataRetentionPolicyUpdate,
    db: Session = Depends(get_db),
    actor: Actor = Depends(get_current_actor),
):
    require_roles(actor, UserRole.ADMIN)
    _require_account_reauthentication(db, actor, payload.account_password)
    organization = db.scalar(
        select(Organization)
        .where(Organization.id == actor.organization_id)
        .with_for_update()
    )
    if not organization:
        raise HTTPException(status_code=404, detail="Organization not found")
    if organization.settings_version != payload.expected_version:
        raise HTTPException(status_code=409, detail="Organization settings changed; refresh and retry")
    previous = {
        "data_export_evidence_retention_days": organization.data_export_evidence_retention_days,
        "data_restore_rehearsal_retention_days": organization.data_restore_rehearsal_retention_days,
        "data_restore_rollback_retention_days": organization.data_restore_rollback_retention_days,
    }
    organization.data_export_evidence_retention_days = (
        payload.data_export_evidence_retention_days
    )
    organization.data_restore_rehearsal_retention_days = (
        payload.data_restore_rehearsal_retention_days
    )
    organization.data_restore_rollback_retention_days = (
        payload.data_restore_rollback_retention_days
    )
    organization.settings_version += 1
    db.add(
        AuditLog(
            organization_id=organization.id,
            user_id=actor.user_id,
            action="organization_data_retention_policy_updated",
            entity_type="organization",
            entity_id=organization.id,
            metadata_json=json.dumps(
                {
                    "actor_role": actor.role.value,
                    "auth_method": actor.auth_method,
                    "previous": previous,
                    "current": {
                        "data_export_evidence_retention_days": organization.data_export_evidence_retention_days,
                        "data_restore_rehearsal_retention_days": organization.data_restore_rehearsal_retention_days,
                        "data_restore_rollback_retention_days": organization.data_restore_rollback_retention_days,
                    },
                    "reason": payload.reason,
                    "settings_version": organization.settings_version,
                },
                separators=(",", ":"),
            ),
            timestamp=datetime.utcnow(),
        )
    )
    db.commit()
    db.refresh(organization)
    return _retention_overview(db, organization)


@router.post(
    "/organization/data-retention/cleanup",
    response_model=OrganizationDataRetentionCleanupRead,
)
def cleanup_organization_data_retention(
    payload: OrganizationDataRetentionCleanup,
    db: Session = Depends(get_db),
    actor: Actor = Depends(get_current_actor),
):
    require_roles(actor, UserRole.ADMIN)
    _require_account_reauthentication(db, actor, payload.account_password)
    organization = db.scalar(
        select(Organization)
        .where(Organization.id == actor.organization_id)
        .with_for_update()
    )
    if not organization:
        raise HTTPException(status_code=404, detail="Organization not found")
    if organization.settings_version != payload.expected_version:
        raise HTTPException(status_code=409, detail="Organization settings changed; refresh and retry")

    recovered_interrupted = 0
    try:
        staged_ids = list_staged_retention_cleanup_ids(organization.id)
        if staged_ids:
            staged_rows = db.scalars(
                select(OrganizationDataRestore)
                .where(
                    OrganizationDataRestore.organization_id == organization.id,
                    OrganizationDataRestore.id.in_(staged_ids),
                )
                .with_for_update()
            ).all()
            active_ids = {
                row.id
                for row in staged_rows
                if row.rollback_payload_json is not None
                and row.rollback_evidence_purged_at is None
            }
            recovered_interrupted = reconcile_staged_retention_cleanup(
                organization.id, active_ids
            )
    except (DataRestoreConflict, OSError) as exc:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail="Restore retention file reconciliation failed",
        ) from exc

    executed_at = datetime.utcnow()
    (
        export_cutoff,
        rehearsal_cutoff,
        removable_restore,
        rollback_expired,
        _removable_export,
    ) = _retention_conditions(organization, executed_at)
    remaining = payload.max_items
    rollback_rows = db.scalars(
        select(OrganizationDataRestore)
        .where(rollback_expired)
        .order_by(
            OrganizationDataRestore.rollback_expires_at,
            OrganizationDataRestore.applied_at,
            OrganizationDataRestore.id,
        )
        .limit(remaining)
        .with_for_update(skip_locked=True)
    ).all()
    remaining -= len(rollback_rows)
    restore_rows = []
    if remaining:
        restore_rows = db.scalars(
            select(OrganizationDataRestore)
            .where(removable_restore)
            .order_by(
                OrganizationDataRestore.updated_at,
                OrganizationDataRestore.id,
            )
            .limit(remaining)
            .with_for_update(skip_locked=True)
        ).all()
        remaining -= len(restore_rows)

    prepared_files = None
    file_cleanup_pending = False
    rollback_database_bytes = sum(row.rollback_size_bytes for row in rollback_rows)
    rollback_file_bytes = sum(row.file_rollback_size_bytes for row in rollback_rows)
    try:
        prepared_files = stage_restore_file_evidence_cleanup(
            organization.id,
            [row.id for row in rollback_rows if row.file_rollback_size_bytes > 0],
        )
        for row in rollback_rows:
            row.rollback_payload_json = None
            row.rollback_sha256 = None
            row.rollback_size_bytes = 0
            row.file_rollback_sha256 = None
            row.file_rollback_size_bytes = 0
            row.rollback_evidence_purged_at = executed_at
            row.rollback_evidence_purged_by = actor.user_id
            row.version += 1
        deleted_restore_ids = [row.id for row in restore_rows]
        for row in restore_rows:
            db.delete(row)
        db.flush()

        export_rows = []
        if remaining:
            retained_reference = exists(
                select(OrganizationDataRestore.id).where(
                    OrganizationDataRestore.organization_id == organization.id,
                    OrganizationDataRestore.matched_export_id == OrganizationDataExport.id,
                )
            )
            export_rows = db.scalars(
                select(OrganizationDataExport)
                .where(
                    OrganizationDataExport.organization_id == organization.id,
                    OrganizationDataExport.generated_at < export_cutoff,
                    not_(retained_reference),
                )
                .order_by(
                    OrganizationDataExport.generated_at,
                    OrganizationDataExport.id,
                )
                .limit(remaining)
                .with_for_update(skip_locked=True)
            ).all()
            for row in export_rows:
                db.delete(row)

        db.add(
            AuditLog(
                organization_id=organization.id,
                user_id=actor.user_id,
                action="organization_data_retention_cleanup",
                entity_type="organization",
                entity_id=organization.id,
                metadata_json=json.dumps(
                    {
                        "actor_role": actor.role.value,
                        "auth_method": actor.auth_method,
                        "reason": payload.reason,
                        "settings_version": organization.settings_version,
                        "export_cutoff": export_cutoff.isoformat(),
                        "restore_rehearsal_cutoff": rehearsal_cutoff.isoformat(),
                        "export_evidence_deleted": len(export_rows),
                        "export_ids": [row.id for row in export_rows],
                        "restore_rehearsals_deleted": len(restore_rows),
                        "restore_ids": deleted_restore_ids,
                        "rollback_evidence_purged": len(rollback_rows),
                        "rollback_restore_ids": [row.id for row in rollback_rows],
                        "rollback_database_bytes_purged": rollback_database_bytes,
                        "rollback_file_bytes_purged": rollback_file_bytes,
                        "missing_file_evidence_ids": (
                            prepared_files.missing_restore_ids if prepared_files else []
                        ),
                        "recovered_interrupted_file_cleanups": recovered_interrupted,
                    },
                    separators=(",", ":"),
                ),
                timestamp=executed_at,
            )
        )
        db.commit()
    except (DataRestoreConflict, OSError) as exc:
        db.rollback()
        rollback_staged_retention_cleanup(prepared_files)
        raise HTTPException(
            status_code=409,
            detail="Restore retention file staging failed",
        ) from exc
    except Exception:
        db.rollback()
        rollback_staged_retention_cleanup(prepared_files)
        raise

    try:
        finalize_staged_retention_cleanup(prepared_files)
    except (DataRestoreConflict, OSError):
        file_cleanup_pending = True
        db.add(
            AuditLog(
                organization_id=organization.id,
                user_id=actor.user_id,
                action="organization_data_retention_file_cleanup_pending",
                entity_type="organization",
                entity_id=organization.id,
                metadata_json=json.dumps(
                    {
                        "restore_ids": (
                            prepared_files.moved_restore_ids if prepared_files else []
                        ),
                        "reason": "protected_quarantine_cleanup_failed",
                    },
                    separators=(",", ":"),
                ),
                timestamp=datetime.utcnow(),
            )
        )
        db.commit()

    db.refresh(organization)
    overview = _retention_overview(db, organization)
    return OrganizationDataRetentionCleanupRead(
        organization_id=organization.id,
        executed_at=executed_at,
        export_evidence_deleted=len(export_rows),
        restore_rehearsals_deleted=len(restore_rows),
        rollback_evidence_purged=len(rollback_rows),
        rollback_database_bytes_purged=rollback_database_bytes,
        rollback_file_bytes_purged=rollback_file_bytes,
        recovered_interrupted_file_cleanups=recovered_interrupted,
        file_cleanup_pending=file_cleanup_pending,
        remaining_candidates=(
            overview.export_evidence_candidates
            + overview.restore_rehearsal_candidates
            + overview.rollback_evidence_candidates
        ),
    )


@router.get(
    "/organization/data-restores",
    response_model=list[OrganizationDataRestoreRead],
)
def list_organization_data_restores(
    limit: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
    actor: Actor = Depends(get_current_actor),
):
    require_roles(actor, UserRole.ADMIN)
    rows = db.scalars(
        select(OrganizationDataRestore)
        .order_by(
            OrganizationDataRestore.created_at.desc(),
            OrganizationDataRestore.id.desc(),
        )
        .limit(limit)
    ).all()
    return [_read_restore(row) for row in rows]


@router.post(
    "/organization/data-restores/rehearsals",
    response_model=OrganizationDataRestoreRead,
)
def create_restore_rehearsal(
    file: UploadFile = File(...),
    account_password: str | None = Form(default=None, max_length=128),
    db: Session = Depends(get_db),
    actor: Actor = Depends(get_current_actor),
):
    require_roles(actor, UserRole.ADMIN)
    _require_account_reauthentication(db, actor, account_password)
    organization = db.get(Organization, actor.organization_id)
    if not organization:
        raise HTTPException(status_code=404, detail="Organization not found")
    try:
        upload = copy_restore_upload(file.file)
        try:
            analysis = analyze_restore_archive(db, organization, upload)
        finally:
            upload.stream.close()
    except (DataRestoreInvalid, zipfile.BadZipFile) as exc:
        detail = str(exc)
        status_code = 413 if "limit" in detail.lower() else 400
        raise HTTPException(status_code=status_code, detail=detail) from exc

    matched_export = db.scalar(
        select(OrganizationDataExport).where(
            OrganizationDataExport.sha256 == analysis.archive_sha256
        )
    )
    row = OrganizationDataRestore(
        organization_id=organization.id,
        requested_by=actor.user_id,
        matched_export_id=matched_export.id if matched_export else None,
        archive_sha256=analysis.archive_sha256,
        archive_size_bytes=analysis.archive_size_bytes,
        plan_sha256=analysis.plan_sha256,
        source_schema_revision=analysis.source_schema_revision,
        source_exported_at=analysis.source_exported_at,
        record_count=analysis.record_count,
        file_count=analysis.file_count,
        create_count=analysis.create_count,
        file_create_count=analysis.file_create_count,
        file_overwrite_count=analysis.file_overwrite_count,
        file_unchanged_count=analysis.file_unchanged_count,
        file_conflict_count=analysis.file_conflict_count,
        update_count=analysis.update_count,
        unchanged_count=analysis.unchanged_count,
        conflict_count=analysis.conflict_count,
        protected_count=analysis.protected_count,
        table_summary_json=json.dumps(
            analysis.table_summary, sort_keys=True, separators=(",", ":")
        ),
        validation_messages_json=json.dumps(
            analysis.validation_messages, ensure_ascii=False, separators=(",", ":")
        ),
    )
    db.add(row)
    db.flush()
    _audit(
        db,
        actor,
        row,
        "organization_data_restore_validated",
        {
            "archive_size_bytes": row.archive_size_bytes,
            "matched_export_id": row.matched_export_id,
            "record_count": row.record_count,
            "file_count": row.file_count,
            "create_count": row.create_count,
            "file_create_count": row.file_create_count,
            "file_overwrite_count": row.file_overwrite_count,
            "file_unchanged_count": row.file_unchanged_count,
            "file_conflict_count": row.file_conflict_count,
            "update_count": row.update_count,
            "unchanged_count": row.unchanged_count,
            "conflict_count": row.conflict_count,
            "protected_count": row.protected_count,
        },
    )
    db.commit()
    db.refresh(row)
    return _read_restore(row)


@router.post(
    "/organization/data-restores/{restore_id}/decision",
    response_model=OrganizationDataRestoreRead,
)
def decide_restore_rehearsal(
    restore_id: int,
    payload: OrganizationDataRestoreDecision,
    db: Session = Depends(get_db),
    actor: Actor = Depends(get_current_actor),
):
    require_roles(actor, UserRole.ADMIN)
    _require_account_reauthentication(db, actor, payload.account_password)
    row = _restore_for_update(db, actor, restore_id)
    if row.status != "validated":
        raise HTTPException(status_code=409, detail="Only a validated rehearsal can be decided")
    if row.version != payload.expected_version:
        raise HTTPException(status_code=409, detail="Restore rehearsal changed; refresh and retry")
    now = datetime.utcnow()
    if payload.decision == "approve":
        if row.conflict_count:
            raise HTTPException(status_code=409, detail="Resolve all rehearsal conflicts before approval")
        if (
            row.create_count == 0
            and row.update_count == 0
            and row.file_create_count == 0
            and row.file_overwrite_count == 0
        ):
            raise HTTPException(status_code=409, detail="Restore rehearsal has no eligible changes")
        row.status = "approved"
        row.approved_by = actor.user_id
        row.approved_at = now
        action = "organization_data_restore_approved"
    else:
        row.status = "rejected"
        row.rejected_by = actor.user_id
        row.rejected_at = now
        action = "organization_data_restore_rejected"
    row.approval_note = payload.note.strip()
    row.version += 1
    _audit(db, actor, row, action, {"decision_note": row.approval_note})
    db.commit()
    db.refresh(row)
    return _read_restore(row)


@router.post(
    "/organization/data-restores/{restore_id}/apply",
    response_model=OrganizationDataRestoreRead,
)
def apply_approved_restore(
    restore_id: int,
    file: UploadFile = File(...),
    expected_version: int = Form(..., ge=0),
    account_password: str | None = Form(default=None, max_length=128),
    db: Session = Depends(get_db),
    actor: Actor = Depends(get_current_actor),
):
    require_roles(actor, UserRole.ADMIN)
    _require_account_reauthentication(db, actor, account_password)
    row = _restore_for_update(db, actor, restore_id)
    if row.status != "approved":
        raise HTTPException(status_code=409, detail="Only an approved restore can be applied")
    if row.version != expected_version:
        raise HTTPException(status_code=409, detail="Restore approval changed; refresh and retry")
    organization = db.get(Organization, actor.organization_id)
    if not organization:
        raise HTTPException(status_code=404, detail="Organization not found")
    upload = None
    prepared_files = None
    try:
        upload = copy_restore_upload(file.file)
        if upload.sha256 != row.archive_sha256:
            raise DataRestoreConflict("The uploaded archive is not the approved archive")
        analysis = analyze_restore_archive(db, organization, upload)
        if analysis.plan_sha256 != row.plan_sha256:
            raise DataRestoreConflict("Live data changed after approval; run a new rehearsal")
        prepared_files = prepare_restore_files(
            analysis,
            upload.stream,
            organization.id,
            row.id,
        )
        rollback_json, rollback_sha256 = apply_restore_plan(
            db,
            analysis,
            organization.id,
            prepared_files,
        )
        promote_restore_files(prepared_files)

        row.status = "applied"
        row.applied_by = actor.user_id
        row.applied_at = datetime.utcnow()
        row.rollback_expires_at = row.applied_at + timedelta(
            days=organization.data_restore_rollback_retention_days
        )
        row.rollback_payload_json = rollback_json
        row.rollback_sha256 = rollback_sha256
        row.rollback_size_bytes = len(rollback_json.encode("utf-8"))
        row.file_rollback_sha256 = prepared_files.rollback_sha256
        row.file_rollback_size_bytes = prepared_files.rollback_size_bytes
        row.version += 1
        _audit(
            db,
            actor,
            row,
            "organization_data_restore_applied",
            {
                "create_count": row.create_count,
                "update_count": row.update_count,
                "file_create_count": row.file_create_count,
                "file_overwrite_count": row.file_overwrite_count,
                "rollback_sha256": row.rollback_sha256,
                "rollback_size_bytes": row.rollback_size_bytes,
                "file_rollback_sha256": row.file_rollback_sha256,
                "file_rollback_size_bytes": row.file_rollback_size_bytes,
                "rollback_expires_at": row.rollback_expires_at.isoformat(),
            },
        )
        db.commit()
    except (DataRestoreInvalid, zipfile.BadZipFile) as exc:
        db.rollback()
        compensate_restore_file_apply(prepared_files)
        discard_restore_file_evidence(prepared_files)
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except DataRestoreConflict as exc:
        db.rollback()
        compensate_restore_file_apply(prepared_files)
        discard_restore_file_evidence(prepared_files)
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except IntegrityError as exc:
        db.rollback()
        compensate_restore_file_apply(prepared_files)
        discard_restore_file_evidence(prepared_files)
        raise HTTPException(
            status_code=409,
            detail="Restore changes violate a live database constraint; run a new rehearsal",
        ) from exc
    except OSError as exc:
        db.rollback()
        compensate_restore_file_apply(prepared_files)
        discard_restore_file_evidence(prepared_files)
        raise HTTPException(status_code=409, detail="Restore media writeback failed") from exc
    except Exception:
        db.rollback()
        compensate_restore_file_apply(prepared_files)
        discard_restore_file_evidence(prepared_files)
        raise
    finally:
        if upload is not None:
            upload.stream.close()

    db.refresh(row)
    return _read_restore(row)


@router.post(
    "/organization/data-restores/{restore_id}/rollback",
    response_model=OrganizationDataRestoreRead,
)
def rollback_applied_restore(
    restore_id: int,
    payload: OrganizationDataRestoreRollback,
    db: Session = Depends(get_db),
    actor: Actor = Depends(get_current_actor),
):
    require_roles(actor, UserRole.ADMIN)
    _require_account_reauthentication(db, actor, payload.account_password)
    row = _restore_for_update(db, actor, restore_id)
    if row.status != "applied" or not row.rollback_payload_json:
        raise HTTPException(status_code=409, detail="Only an applied restore can be rolled back")
    if row.rollback_expires_at and row.rollback_expires_at <= datetime.utcnow():
        raise HTTPException(
            status_code=409,
            detail="The governed rollback window has expired; run retention cleanup",
        )
    if row.version != payload.expected_version:
        raise HTTPException(status_code=409, detail="Restore evidence changed; refresh and retry")
    rollback_bytes = row.rollback_payload_json.encode("utf-8")
    if (
        len(rollback_bytes) != row.rollback_size_bytes
        or sha256(rollback_bytes).hexdigest() != row.rollback_sha256
    ):
        raise HTTPException(status_code=409, detail="Rollback evidence integrity check failed")
    prepared_files = None
    try:
        prepared_files = prepare_restore_file_rollback(
            row.rollback_payload_json,
            row.organization_id,
            row.id,
            row.file_rollback_sha256,
            row.file_rollback_size_bytes,
        )
        restored_rows = rollback_restore_plan(
            db, row.rollback_payload_json, row.organization_id
        )
        rollback_restore_files(prepared_files)
        row.status = "rolled_back"
        row.rolled_back_by = actor.user_id
        row.rolled_back_at = datetime.utcnow()
        row.version += 1
        _audit(
            db,
            actor,
            row,
            "organization_data_restore_rolled_back",
            {
                "restored_rows": restored_rows,
                "restored_files": len(prepared_files.file_plan),
                "rollback_sha256": row.rollback_sha256,
                "file_rollback_sha256": row.file_rollback_sha256,
            },
        )
        db.commit()
    except (DataRestoreConflict, DataRestoreInvalid) as exc:
        db.rollback()
        compensate_restore_file_rollback(prepared_files)
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except IntegrityError as exc:
        db.rollback()
        compensate_restore_file_rollback(prepared_files)
        raise HTTPException(
            status_code=409,
            detail="Rollback changes violate a live database constraint",
        ) from exc
    except OSError as exc:
        db.rollback()
        compensate_restore_file_rollback(prepared_files)
        raise HTTPException(status_code=409, detail="Restore media rollback failed") from exc
    except Exception:
        db.rollback()
        compensate_restore_file_rollback(prepared_files)
        raise
    discard_restore_file_evidence(prepared_files)
    db.refresh(row)
    return _read_restore(row)
