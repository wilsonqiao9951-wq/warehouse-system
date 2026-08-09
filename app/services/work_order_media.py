from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
import re

from fastapi import HTTPException

from app.models import WorkOrderMedia
from app.schemas import WorkOrderMediaRead


MEDIA_CATEGORIES = {
    "arrival",
    "before",
    "during",
    "after",
    "damage",
    "serial_label",
    "other",
}
MAX_MEDIA_PER_WORK_ORDER = 100


def detect_work_order_media(data: bytes) -> tuple[str, str, str] | None:
    if data.startswith(b"\xff\xd8\xff"):
        return "photo", ".jpg", "image/jpeg"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "photo", ".png", "image/png"
    if data.startswith((b"GIF87a", b"GIF89a")):
        return "photo", ".gif", "image/gif"
    if len(data) >= 12 and data.startswith(b"RIFF") and data[8:12] == b"WEBP":
        return "photo", ".webp", "image/webp"
    if len(data) >= 12 and data[4:8] == b"ftyp" and data[8:12] in {
        b"heic",
        b"heix",
        b"hevc",
        b"hevx",
        b"mif1",
    }:
        return "photo", ".heic", "image/heic"
    if data.startswith(b"\x1aE\xdf\xa3"):
        return "video", ".webm", "video/webm"
    if len(data) >= 12 and data[4:8] == b"ftyp":
        brand = data[8:12]
        if brand == b"qt  ":
            return "video", ".mov", "video/quicktime"
        if brand in {
            b"isom",
            b"iso2",
            b"mp41",
            b"mp42",
            b"avc1",
            b"M4V ",
            b"MSNV",
        }:
            return "video", ".mp4", "video/mp4"
    return None


def normalize_media_category(value: str) -> str:
    category = value.strip().lower()
    if category not in MEDIA_CATEGORIES:
        raise HTTPException(status_code=422, detail="Unknown work-order media category")
    return category


def normalize_media_caption(value: str | None) -> str | None:
    caption = (value or "").strip()
    return caption or None


def safe_original_filename(value: str | None) -> str | None:
    leaf = re.split(r"[\\/]", value or "")[-1].strip()
    if not leaf:
        return None
    cleaned = re.sub(r"[^A-Za-z0-9._ ()-]", "_", leaf).strip(" .")
    return cleaned[:255] or None


def media_request_fingerprint(
    *,
    work_order_id: int,
    category: str,
    caption: str | None,
    file_sha256: str,
    size_bytes: int,
    media_type: str,
    mime_type: str,
    original_filename: str | None,
    created_by: int | None,
    created_device_id: int | None,
    claim_version: int,
) -> str:
    payload = {
        "caption": caption,
        "category": category,
        "claim_version": claim_version,
        "created_by": created_by,
        "created_device_id": created_device_id,
        "file_sha256": file_sha256,
        "media_type": media_type,
        "mime_type": mime_type,
        "original_filename": original_filename,
        "size_bytes": size_bytes,
        "work_order_id": work_order_id,
    }
    canonical = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    )
    return sha256(canonical.encode("utf-8")).hexdigest()


def work_order_media_read(
    row: WorkOrderMedia,
    *,
    include_private_attribution: bool = False,
) -> WorkOrderMediaRead:
    return WorkOrderMediaRead(
        id=row.id,
        organization_id=row.organization_id,
        work_order_id=row.work_order_id,
        category=row.category,
        caption=row.caption,
        media_type=row.media_type,
        mime_type=row.mime_type,
        size_bytes=row.size_bytes,
        file_sha256=row.file_sha256,
        original_filename=(
            row.original_filename if include_private_attribution else None
        ),
        client_request_id=row.client_request_id,
        created_by=row.created_by,
        created_device_id=(
            row.created_device_id if include_private_attribution else None
        ),
        claim_version=row.claim_version,
        content_url=f"/api/work-orders/{row.work_order_id}/media/{row.id}/content",
        created_at=row.created_at,
    )


def safe_media_path(private_root: Path, row: WorkOrderMedia) -> Path:
    root = private_root.resolve()
    expected_prefix = f"work-order-media/{row.organization_id}/{row.work_order_id}/"
    key = row.media_storage_key.replace("\\", "/")
    if not key.startswith(expected_prefix):
        raise HTTPException(status_code=409, detail="Work-order media storage reference is invalid")
    target = (root / key).resolve()
    if root not in target.parents:
        raise HTTPException(status_code=409, detail="Work-order media storage reference is invalid")
    return target


def file_sha256(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as source:
        while chunk := source.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()
