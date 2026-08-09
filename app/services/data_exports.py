from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal
from enum import Enum
from hashlib import sha256
from pathlib import Path
from tempfile import SpooledTemporaryFile
from typing import Any, BinaryIO
import base64
import json
import re
import zipfile

from sqlalchemy import inspect, select, text
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.rbac import TENANT_MODELS
from app.models import Organization


FORMAT_VERSION = "opf-portable-v1"
SENSITIVE_COLUMNS: dict[str, set[str]] = {
    "users": {
        "password_hash",
        "mfa_secret_encrypted",
        "mfa_recovery_codes_json",
        "mfa_last_used_step",
        "mfa_enrollment_expires_at",
    },
    "user_devices": {"device_token_hash"},
    "user_invitations": {"token_hash"},
    "auth_security_events": {"principal_fingerprint", "source_fingerprint"},
    "password_reset_tokens": {
        "token_hash",
        "principal_fingerprint",
        "source_fingerprint",
    },
    "external_integrations": {"api_key_hash"},
    "integration_adapter_configurations": {"credential_ciphertext"},
    "organization_domains": {"verification_token", "verification_value"},
}
PUBLIC_FILE_REFERENCE = re.compile(r"/uploads/[A-Za-z0-9._~%+@/-]+")


class DataExportTooLarge(ValueError):
    pass


@dataclass
class DataExportBundle:
    stream: BinaryIO
    generated_at: datetime
    sha256: str
    size_bytes: int
    record_count: int
    file_count: int
    missing_file_count: int
    table_counts: dict[str, int]


def _json_value(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.isoformat(timespec="microseconds") + "Z"
        return value.astimezone(timezone.utc).isoformat(timespec="microseconds").replace(
            "+00:00",
            "Z",
        )
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, bytes):
        return {"encoding": "base64", "data": base64.b64encode(value).decode("ascii")}
    if isinstance(value, dict):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    return str(value)


def _excluded_columns(row: Any) -> set[str]:
    table_name = row.__table__.name
    excluded = set(SENSITIVE_COLUMNS.get(table_name, set()))
    for column in row.__table__.columns:
        name = column.name.lower()
        if "password" in name or name.endswith("_secret") or name.endswith("_hash"):
            excluded.add(column.name)
    return excluded


def _row_payload(row: Any) -> dict[str, Any]:
    excluded = _excluded_columns(row)
    return {
        column.name: _json_value(getattr(row, column.name))
        for column in row.__table__.columns
        if column.name not in excluded
    }


def _find_public_file_references(value: Any) -> set[str]:
    matches: set[str] = set()
    if isinstance(value, str):
        if value.startswith("/uploads/"):
            matches.add(value)
        elif "/uploads/" in value:
            matches.update(PUBLIC_FILE_REFERENCE.findall(value))
            if value.lstrip().startswith(("{", "[")):
                try:
                    matches.update(_find_public_file_references(json.loads(value)))
                except json.JSONDecodeError:
                    pass
    elif isinstance(value, dict):
        for nested in value.values():
            matches.update(_find_public_file_references(nested))
    elif isinstance(value, list):
        for nested in value:
            matches.update(_find_public_file_references(nested))
    return matches


def _find_private_file_references(value: Any) -> set[str]:
    matches: set[str] = set()
    if isinstance(value, str) and value.startswith("private:"):
        matches.add(value.removeprefix("private:"))
    elif isinstance(value, dict):
        for nested in value.values():
            matches.update(_find_private_file_references(nested))
    elif isinstance(value, list):
        for nested in value:
            matches.update(_find_private_file_references(nested))
    return matches


def _safe_file(root: Path, relative: str) -> Path | None:
    root = root.resolve()
    target = (root / relative).resolve()
    if target != root and root not in target.parents:
        return None
    return target if target.is_file() else None


def _write_bytes(archive: zipfile.ZipFile, path: str, content: bytes) -> str:
    archive.writestr(path, content)
    return sha256(content).hexdigest()


def _write_file(
    archive: zipfile.ZipFile,
    source: Path,
    archive_path: str,
    max_bytes: int,
) -> tuple[int, str]:
    digest = sha256()
    size = 0
    with source.open("rb") as source_file, archive.open(archive_path, "w") as target:
        while chunk := source_file.read(1024 * 1024):
            if size + len(chunk) > max_bytes:
                raise DataExportTooLarge("Organization files exceed the configured export limit")
            digest.update(chunk)
            size += len(chunk)
            target.write(chunk)
    return size, digest.hexdigest()


def _schema_revision(db: Session) -> str | None:
    bind = db.get_bind()
    if not inspect(bind).has_table("alembic_version"):
        return None
    return db.scalar(text("SELECT version_num FROM alembic_version LIMIT 1"))


def build_organization_data_export(
    db: Session,
    organization: Organization,
    *,
    include_files: bool,
) -> DataExportBundle:
    generated_at = datetime.utcnow()
    stream = SpooledTemporaryFile(max_size=8 * 1024 * 1024, mode="w+b")
    table_counts: dict[str, int] = {}
    table_manifest: list[dict[str, Any]] = []
    public_references: set[str] = set()
    private_references: set[str] = set()
    record_count = 0
    raw_size = 0

    export_models = (Organization, *TENANT_MODELS)
    unique_models = tuple(dict.fromkeys(export_models))
    try:
        with zipfile.ZipFile(
            stream,
            mode="w",
            compression=zipfile.ZIP_DEFLATED,
            compresslevel=6,
        ) as archive:
            for model in sorted(unique_models, key=lambda item: item.__table__.name):
                table_name = model.__table__.name
                archive_path = f"data/{table_name}.jsonl"
                content_digest = sha256()
                table_count = 0
                if model is Organization:
                    rows = iter((organization,))
                else:
                    rows = db.scalars(select(model).order_by(model.id)).yield_per(500)
                with archive.open(archive_path, "w") as target:
                    for row in rows:
                        payload = _row_payload(row)
                        public_references.update(_find_public_file_references(payload))
                        private_references.update(_find_private_file_references(payload))
                        media_storage_key = getattr(row, "media_storage_key", None)
                        if isinstance(media_storage_key, str) and media_storage_key:
                            private_references.add(media_storage_key)
                        line = (
                            json.dumps(
                                payload,
                                ensure_ascii=False,
                                separators=(",", ":"),
                            ).encode("utf-8")
                            + b"\n"
                        )
                        raw_size += len(line)
                        if raw_size > settings.max_data_export_bytes:
                            raise DataExportTooLarge(
                                "Organization data exceeds the configured export limit"
                            )
                        content_digest.update(line)
                        target.write(line)
                        table_count += 1
                content_sha256 = content_digest.hexdigest()
                table_counts[table_name] = table_count
                record_count += table_count
                table_manifest.append(
                    {
                        "table": table_name,
                        "path": archive_path,
                        "records": table_count,
                        "sha256": content_sha256,
                        "excluded_columns": sorted(
                            _excluded_columns(model)
                        ),
                    }
                )

            file_manifest: list[dict[str, Any]] = []
            missing_files: list[str] = []
            if include_files:
                public_root = Path(settings.data_export_public_files_root)
                for reference in sorted(public_references):
                    relative = reference.removeprefix("/uploads/")
                    source = _safe_file(public_root, relative)
                    if source is None:
                        missing_files.append(reference)
                        continue
                    source_size = source.stat().st_size
                    if raw_size + source_size > settings.max_data_export_bytes:
                        raise DataExportTooLarge("Organization files exceed the configured export limit")
                    archive_path = f"files/public/{relative.replace('\\', '/')}"
                    size, digest = _write_file(
                        archive,
                        source,
                        archive_path,
                        settings.max_data_export_bytes - raw_size,
                    )
                    raw_size += size
                    file_manifest.append(
                        {
                            "reference": reference,
                            "path": archive_path,
                            "size_bytes": size,
                            "sha256": digest,
                        }
                    )

                private_root = Path(settings.data_export_private_files_root)
                for reference in sorted(private_references):
                    source = _safe_file(private_root, reference)
                    safe_reference = f"private:{reference}"
                    if source is None:
                        missing_files.append(safe_reference)
                        continue
                    source_size = source.stat().st_size
                    if raw_size + source_size > settings.max_data_export_bytes:
                        raise DataExportTooLarge("Organization files exceed the configured export limit")
                    archive_path = f"files/private/{reference.replace('\\', '/')}"
                    size, digest = _write_file(
                        archive,
                        source,
                        archive_path,
                        settings.max_data_export_bytes - raw_size,
                    )
                    raw_size += size
                    file_manifest.append(
                        {
                            "reference": safe_reference,
                            "path": archive_path,
                            "size_bytes": size,
                            "sha256": digest,
                        }
                    )

            manifest = {
                "format_version": FORMAT_VERSION,
                "generated_at_utc": generated_at.isoformat(timespec="microseconds") + "Z",
                "schema_revision": _schema_revision(db),
                "organization": {
                    "id": organization.id,
                    "name": organization.name,
                    "slug": organization.slug,
                },
                "record_count": record_count,
                "file_count": len(file_manifest),
                "missing_file_count": len(missing_files),
                "include_files": include_files,
                "tables": table_manifest,
                "files": file_manifest,
                "missing_files": missing_files,
                "security": {
                    "redacted_columns": {
                        item["table"]: item["excluded_columns"]
                        for item in table_manifest
                        if item["excluded_columns"]
                    },
                    "note": "Authentication secrets are intentionally excluded.",
                },
            }
            _write_bytes(
                archive,
                "manifest.json",
                json.dumps(
                    manifest,
                    ensure_ascii=False,
                    indent=2,
                    sort_keys=True,
                ).encode("utf-8")
                + b"\n",
            )

        size_bytes = stream.tell()
        stream.seek(0)
        digest = sha256()
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
        stream.seek(0)
        return DataExportBundle(
            stream=stream,
            generated_at=generated_at,
            sha256=digest.hexdigest(),
            size_bytes=size_bytes,
            record_count=record_count,
            file_count=len(file_manifest),
            missing_file_count=len(missing_files),
            table_counts=table_counts,
        )
    except Exception:
        stream.close()
        raise
