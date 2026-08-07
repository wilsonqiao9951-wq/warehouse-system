from __future__ import annotations

import re
from datetime import datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import InventoryRegion


REGION_CODE_PATTERN = re.compile(r"^[A-Z0-9]+(?:-[A-Z0-9]+)*$")


def normalize_region_code(value: str) -> str:
    code = re.sub(r"[-_\s]+", "-", value.strip().upper()).strip("-")
    if not code or not REGION_CODE_PATTERN.fullmatch(code):
        raise HTTPException(
            status_code=422,
            detail="Region code must contain only letters, numbers, and hyphens",
        )
    return code


def normalize_region_name(value: str) -> str:
    name = value.strip()
    if not name:
        raise HTTPException(status_code=422, detail="Region name cannot be blank")
    return name


def validate_region_timezone(value: str) -> str:
    timezone_name = value.strip()
    try:
        ZoneInfo(timezone_name)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise HTTPException(status_code=422, detail="Unknown IANA timezone") from exc
    return timezone_name


def ensure_default_region(db: Session, organization_id: int) -> InventoryRegion:
    default_region = db.scalar(
        select(InventoryRegion).where(
            InventoryRegion.organization_id == organization_id,
            InventoryRegion.is_default.is_(True),
        ).limit(1)
    )
    if default_region:
        return default_region

    existing = db.scalar(
        select(InventoryRegion)
        .where(
            InventoryRegion.organization_id == organization_id,
            InventoryRegion.is_active.is_(True),
        )
        .order_by(InventoryRegion.id.asc())
        .limit(1)
    )
    now = datetime.utcnow()
    if existing:
        existing.is_default = True
        existing.version += 1
        existing.updated_at = now
        db.add(existing)
        db.flush()
        return existing

    region = InventoryRegion(
        organization_id=organization_id,
        code="PRIMARY",
        name="Primary region",
        timezone="UTC",
        is_default=True,
        is_active=True,
        created_at=now,
        updated_at=now,
    )
    db.add(region)
    db.flush()
    return region
