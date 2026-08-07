from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal
from hashlib import sha256
from pathlib import PurePosixPath
from tempfile import SpooledTemporaryFile
from typing import Any, BinaryIO
import base64
import json
import stat
import zipfile

from sqlalchemy import Date as SqlDate
from sqlalchemy import DateTime as SqlDateTime
from sqlalchemy import Enum as SqlEnum
from sqlalchemy import Float as SqlFloat
from sqlalchemy import LargeBinary, Numeric
from sqlalchemy import UniqueConstraint, and_, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.rbac import TENANT_MODELS
from app.models import Organization
from app.services.data_exports import (
    FORMAT_VERSION,
    _excluded_columns,
    _json_value,
    _schema_revision,
)


MAX_MANIFEST_BYTES = 1024 * 1024
MAX_ARCHIVE_ENTRIES = 20_000
IMMUTABLE_COLUMNS = {"id", "organization_id", "version", "created_at", "updated_at"}

# Initial restore application is deliberately limited to existing master,
# configuration, and reviewed knowledge rows. Transactions, work-order custody,
# authentication, billing, integrations, and audit evidence remain immutable.
RESTORABLE_TABLES = {
    "completion_policies",
    "customers",
    "equipment",
    "machine_knowledge_entries",
    "machine_knowledge_profiles",
    "part_machine_associations",
    "parts",
    "storage_locations",
    "warehouses",
    "work_order_form_fields",
    "work_order_form_templates",
}
CREATE_TABLE_ORDER = (
    "customers",
    "equipment",
    "warehouses",
    "storage_locations",
    "parts",
    "part_machine_associations",
    "completion_policies",
    "work_order_form_templates",
    "work_order_form_fields",
    "machine_knowledge_profiles",
    "machine_knowledge_entries",
)
CREATE_TABLE_RANK = {
    table_name: rank for rank, table_name in enumerate(CREATE_TABLE_ORDER)
}
RESTORE_SCHEMA_COMPATIBILITY = {
    "20260806_0037": {"20260806_0036", "20260806_0037"},
    "20260807_0038": {
        "20260806_0036",
        "20260806_0037",
        "20260807_0038",
    },
}


class DataRestoreInvalid(ValueError):
    pass


class DataRestoreConflict(ValueError):
    pass


@dataclass
class RestoreUpload:
    stream: BinaryIO
    sha256: str
    size_bytes: int


@dataclass
class RestoreAnalysis:
    archive_sha256: str
    archive_size_bytes: int
    source_schema_revision: str | None
    source_exported_at: datetime | None
    record_count: int
    file_count: int
    create_count: int
    update_count: int
    unchanged_count: int
    conflict_count: int
    protected_count: int
    table_summary: dict[str, dict[str, int]]
    validation_messages: list[str]
    plan: list[dict[str, Any]]
    plan_json: str
    plan_sha256: str


def copy_restore_upload(source: BinaryIO) -> RestoreUpload:
    stream = SpooledTemporaryFile(max_size=8 * 1024 * 1024, mode="w+b")
    digest = sha256()
    size = 0
    try:
        while chunk := source.read(1024 * 1024):
            size += len(chunk)
            if size > settings.max_data_restore_archive_bytes:
                raise DataRestoreInvalid("Restore archive exceeds the configured upload limit")
            digest.update(chunk)
            stream.write(chunk)
        if size == 0:
            raise DataRestoreInvalid("Restore archive is empty")
        stream.seek(0)
        return RestoreUpload(stream=stream, sha256=digest.hexdigest(), size_bytes=size)
    except Exception:
        stream.close()
        raise


def _safe_archive_path(name: str) -> bool:
    if not name or "\\" in name or name.startswith("/"):
        return False
    path = PurePosixPath(name)
    return not path.is_absolute() and all(part not in {"", ".", ".."} for part in path.parts)


def _read_json(stream: bytes, label: str) -> Any:
    try:
        return json.loads(stream.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise DataRestoreInvalid(f"{label} is not valid UTF-8 JSON") from exc


def _parse_utc(value: Any) -> datetime | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise DataRestoreInvalid("Manifest generation time is invalid")
    try:
        parsed = datetime.fromisoformat(
            value.removesuffix("Z") + ("+00:00" if value.endswith("Z") else "")
        )
        if parsed.tzinfo is not None:
            return parsed.astimezone(timezone.utc).replace(tzinfo=None)
        return parsed
    except ValueError as exc:
        raise DataRestoreInvalid("Manifest generation time is invalid") from exc


def _deserialize(column, value: Any) -> Any:
    if value is None:
        return None
    column_type = column.type
    try:
        if isinstance(column_type, SqlDateTime):
            if not isinstance(value, str):
                raise ValueError
            parsed = datetime.fromisoformat(
                value.removesuffix("Z") + ("+00:00" if value.endswith("Z") else "")
            )
            if parsed.tzinfo is not None:
                return parsed.astimezone(timezone.utc).replace(tzinfo=None)
            return parsed
        if isinstance(column_type, SqlDate):
            if not isinstance(value, str):
                raise ValueError
            return date.fromisoformat(value)
        if isinstance(column_type, SqlEnum) and column_type.enum_class:
            return column_type.enum_class(value)
        if isinstance(column_type, SqlFloat):
            return float(value)
        if isinstance(column_type, Numeric):
            return Decimal(str(value))
        if isinstance(column_type, LargeBinary):
            if not isinstance(value, dict) or value.get("encoding") != "base64":
                raise ValueError
            return base64.b64decode(value.get("data", ""), validate=True)
    except (TypeError, ValueError) as exc:
        raise DataRestoreInvalid(
            f"Invalid value for {column.table.name}.{column.name}"
        ) from exc
    return value


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _table_registry() -> dict[str, Any]:
    models = (Organization, *TENANT_MODELS)
    return {model.__table__.name: model for model in dict.fromkeys(models)}


def _validate_archive_entries(archive: zipfile.ZipFile) -> dict[str, zipfile.ZipInfo]:
    infos = archive.infolist()
    if len(infos) > MAX_ARCHIVE_ENTRIES:
        raise DataRestoreInvalid("Restore archive contains too many entries")
    entries: dict[str, zipfile.ZipInfo] = {}
    uncompressed = 0
    for info in infos:
        if info.is_dir():
            continue
        if not _safe_archive_path(info.filename):
            raise DataRestoreInvalid("Restore archive contains an unsafe path")
        if info.filename in entries:
            raise DataRestoreInvalid("Restore archive contains duplicate paths")
        if info.flag_bits & 0x1:
            raise DataRestoreInvalid("Encrypted ZIP entries are not supported")
        file_mode = (info.external_attr >> 16) & 0o170000
        if file_mode == stat.S_IFLNK:
            raise DataRestoreInvalid("Restore archive contains a symbolic link")
        uncompressed += info.file_size
        if uncompressed > settings.max_data_restore_uncompressed_bytes:
            raise DataRestoreInvalid("Restore archive exceeds the uncompressed-content limit")
        entries[info.filename] = info
    if "manifest.json" not in entries:
        raise DataRestoreInvalid("Restore archive is missing manifest.json")
    if entries["manifest.json"].file_size > MAX_MANIFEST_BYTES:
        raise DataRestoreInvalid("Restore manifest is too large")
    return entries


def _manifest_entries(
    manifest: dict[str, Any],
    registry: dict[str, Any],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], set[str]]:
    tables = manifest.get("tables")
    files = manifest.get("files")
    if not isinstance(tables, list) or not isinstance(files, list):
        raise DataRestoreInvalid("Restore manifest table or file inventory is invalid")
    expected = {"manifest.json"}
    table_names: set[str] = set()
    for item in tables:
        if not isinstance(item, dict):
            raise DataRestoreInvalid("Restore manifest contains an invalid table entry")
        table = item.get("table")
        path = item.get("path")
        if table not in registry or path != f"data/{table}.jsonl" or table in table_names:
            raise DataRestoreInvalid("Restore manifest contains an unknown or duplicate table")
        if not isinstance(item.get("records"), int) or item["records"] < 0:
            raise DataRestoreInvalid("Restore manifest contains an invalid table count")
        if not isinstance(item.get("sha256"), str) or len(item["sha256"]) != 64:
            raise DataRestoreInvalid("Restore manifest contains an invalid table checksum")
        table_names.add(table)
        expected.add(path)
    file_paths: set[str] = set()
    for item in files:
        if not isinstance(item, dict):
            raise DataRestoreInvalid("Restore manifest contains an invalid file entry")
        path = item.get("path")
        if not isinstance(path, str) or not _safe_archive_path(path) or not path.startswith("files/"):
            raise DataRestoreInvalid("Restore manifest contains an unsafe file path")
        if path in file_paths:
            raise DataRestoreInvalid("Restore manifest contains a duplicate file path")
        if not isinstance(item.get("size_bytes"), int) or item["size_bytes"] < 0:
            raise DataRestoreInvalid("Restore manifest contains an invalid file size")
        if not isinstance(item.get("sha256"), str) or len(item["sha256"]) != 64:
            raise DataRestoreInvalid("Restore manifest contains an invalid file checksum")
        file_paths.add(path)
        expected.add(path)
    return tables, files, expected


def _plan_row(
    db: Session,
    model: Any,
    payload: dict[str, Any],
    organization_id: int,
) -> tuple[str, dict[str, Any] | None, str | None]:
    table = model.__table__
    table_name = table.name
    unknown = set(payload) - {column.name for column in table.columns}
    if unknown:
        raise DataRestoreInvalid(f"{table_name} contains unknown columns")
    excluded = _excluded_columns(model)
    if excluded.intersection(payload):
        raise DataRestoreInvalid(f"{table_name} contains prohibited authentication columns")
    row_id = payload.get("id")
    if not isinstance(row_id, int) or isinstance(row_id, bool) or row_id < 1:
        return "conflict", None, f"{table_name} contains a row without a valid integer id"
    if payload.get("organization_id") != organization_id:
        return "conflict", None, f"{table_name} row {row_id} belongs to another organization"
    target = db.get(model, row_id)
    if target is None:
        existing_owner = db.execute(
            select(table.c.organization_id).where(table.c.id == row_id)
        ).scalar_one_or_none()
        if existing_owner is not None:
            return (
                "conflict",
                None,
                f"{table_name} row {row_id} is already owned by another organization",
            )
        missing = {
            column.name
            for column in table.columns
            if column.name not in excluded and column.name not in payload
        }
        if missing:
            raise DataRestoreInvalid(
                f"{table_name} row {row_id} is missing columns required for rehydration"
            )
        columns = {column.name: column for column in table.columns}
        after = {
            name: _json_value(_deserialize(columns[name], value))
            for name, value in payload.items()
            if name not in excluded
        }
        unique_conflict = _unique_conflict(db, table, row_id, after)
        if unique_conflict:
            return (
                "conflict",
                None,
                f"{table_name} row {row_id} conflicts with current unique key {unique_conflict}",
            )
        return (
            "create",
            {
                "action": "create",
                "table": table_name,
                "id": row_id,
                "before": None,
                "after": after,
            },
            None,
        )
    if getattr(target, "organization_id", None) != organization_id:
        return (
            "conflict",
            None,
            f"{table_name} row {row_id} is already owned by another organization",
        )

    before: dict[str, Any] = {}
    after: dict[str, Any] = {}
    columns = {column.name: column for column in table.columns}
    proposed_row: dict[str, Any] = {}
    for name, value in payload.items():
        if name in excluded:
            continue
        converted = _deserialize(columns[name], value)
        current = _json_value(getattr(target, name))
        proposed = _json_value(converted)
        proposed_row[name] = current if name in IMMUTABLE_COLUMNS else proposed
        if name in IMMUTABLE_COLUMNS:
            continue
        if _canonical(current) != _canonical(proposed):
            before[name] = current
            after[name] = proposed
    unique_conflict = _unique_conflict(db, table, row_id, proposed_row)
    if unique_conflict:
        return (
            "conflict",
            None,
            f"{table_name} row {row_id} conflicts with current unique key {unique_conflict}",
        )
    if not after:
        return "unchanged", None, None
    return (
        "update",
        {
            "action": "update",
            "table": table_name,
            "id": row_id,
            "before": before,
            "after": after,
        },
        None,
    )


def _unique_conflict(
    db: Session,
    table: Any,
    row_id: int,
    proposed: dict[str, Any],
) -> str | None:
    constraints = [
        constraint
        for constraint in table.constraints
        if isinstance(constraint, UniqueConstraint)
    ]
    for constraint in constraints:
        names = [column.name for column in constraint.columns]
        if not names or any(name not in proposed or proposed[name] is None for name in names):
            continue
        found = db.execute(
            select(table.c.id)
            .where(and_(*(table.c[name] == proposed[name] for name in names)))
            .limit(1)
        ).scalar_one_or_none()
        if found is not None and found != row_id:
            return constraint.name or ",".join(names)
    return None


def _dependency_error(
    db: Session,
    item: dict[str, Any],
    registry: dict[str, Any],
    planned_creates: set[tuple[str, int]],
    invalid_creates: set[tuple[str, int]],
    organization_id: int,
) -> str | None:
    model = registry[item["table"]]
    table = model.__table__
    for column in table.columns:
        value = item["after"].get(column.name)
        if value is None:
            continue
        for foreign_key in column.foreign_keys:
            remote_table = foreign_key.column.table
            remote_name = remote_table.name
            if foreign_key.column.name != "id" or not isinstance(value, int):
                return f"{item['table']} row {item['id']} has an unsupported foreign key"
            key = (remote_name, value)
            if key in planned_creates:
                if key in invalid_creates:
                    return (
                        f"{item['table']} row {item['id']} depends on an unresolved "
                        f"{remote_name} row {value}"
                    )
                continue
            if remote_name == "organizations":
                if value != organization_id:
                    return f"{item['table']} row {item['id']} references another organization"
                continue
            remote = db.execute(
                select(remote_table).where(remote_table.c.id == value)
            ).mappings().first()
            if remote is None:
                return (
                    f"{item['table']} row {item['id']} references missing "
                    f"{remote_name} row {value}"
                )
            if "organization_id" in remote_table.c and remote["organization_id"] != organization_id:
                return (
                    f"{item['table']} row {item['id']} references another organization's "
                    f"{remote_name} row {value}"
                )
    return None


def _invalid_plan_dependencies(
    db: Session,
    plan: list[dict[str, Any]],
    registry: dict[str, Any],
    organization_id: int,
) -> dict[int, str]:
    create_indexes = {
        (item["table"], item["id"]): index
        for index, item in enumerate(plan)
        if item.get("action") == "create"
    }
    planned_creates = set(create_indexes)
    invalid: dict[int, str] = {}
    changed = True
    while changed:
        changed = False
        invalid_creates = {
            key for key, index in create_indexes.items() if index in invalid
        }
        for index, item in enumerate(plan):
            if index in invalid:
                continue
            error = _dependency_error(
                db,
                item,
                registry,
                planned_creates,
                invalid_creates,
                organization_id,
            )
            if error:
                invalid[index] = error
                changed = True
    return invalid


def _validate_protected_row(
    model: Any,
    payload: dict[str, Any],
    organization_id: int,
) -> None:
    table = model.__table__
    table_name = table.name
    unknown = set(payload) - {column.name for column in table.columns}
    if unknown:
        raise DataRestoreInvalid(f"{table_name} contains unknown columns")
    if _excluded_columns(model).intersection(payload):
        raise DataRestoreInvalid(f"{table_name} contains prohibited authentication columns")
    if model is Organization:
        if payload.get("id") != organization_id:
            raise DataRestoreInvalid("Organization data does not match the restore target")
    elif payload.get("organization_id") != organization_id:
        raise DataRestoreInvalid(f"{table_name} contains cross-organization data")


def analyze_restore_archive(
    db: Session,
    organization: Organization,
    upload: RestoreUpload,
) -> RestoreAnalysis:
    registry = _table_registry()
    upload.stream.seek(0)
    try:
        archive = zipfile.ZipFile(upload.stream)
    except zipfile.BadZipFile as exc:
        raise DataRestoreInvalid("Restore upload is not a valid ZIP archive") from exc
    with archive:
        entries = _validate_archive_entries(archive)
        manifest = _read_json(archive.read("manifest.json"), "Restore manifest")
        if not isinstance(manifest, dict) or manifest.get("format_version") != FORMAT_VERSION:
            raise DataRestoreInvalid("Restore archive format is not supported")
        source_org = manifest.get("organization")
        if not isinstance(source_org, dict) or (
            source_org.get("id") != organization.id
            or source_org.get("slug") != organization.slug
        ):
            raise DataRestoreInvalid("Restore archive does not belong to this organization")
        source_revision = manifest.get("schema_revision")
        current_revision = _schema_revision(db)
        compatible_revisions = RESTORE_SCHEMA_COMPATIBILITY.get(
            current_revision, {current_revision}
        )
        if source_revision not in compatible_revisions:
            raise DataRestoreInvalid(
                "Restore archive schema revision is not compatible with the running database"
            )
        tables, files, expected_entries = _manifest_entries(manifest, registry)
        if set(entries) != expected_entries:
            raise DataRestoreInvalid("Restore archive inventory does not match its manifest")

        plan: list[dict[str, Any]] = []
        messages: list[str] = []
        table_summary: dict[str, dict[str, int]] = {}
        record_count = 0
        create_count = 0
        update_count = 0
        unchanged_count = 0
        conflict_count = 0
        protected_count = 0

        for item in tables:
            table_name = item["table"]
            model = registry[table_name]
            digest = sha256()
            rows_seen = 0
            seen_row_ids: set[int] = set()
            summary = {
                "records": 0,
                "creates": 0,
                "updates": 0,
                "unchanged": 0,
                "conflicts": 0,
                "protected": 0,
            }
            with archive.open(item["path"]) as source:
                for raw_line in source:
                    digest.update(raw_line)
                    if not raw_line.strip():
                        continue
                    payload = _read_json(raw_line, f"{table_name} row")
                    if not isinstance(payload, dict):
                        raise DataRestoreInvalid(f"{table_name} contains a non-object row")
                    rows_seen += 1
                    row_id = payload.get("id")
                    if isinstance(row_id, int) and row_id in seen_row_ids:
                        raise DataRestoreInvalid(
                            f"{table_name} contains duplicate row ids"
                        )
                    if isinstance(row_id, int):
                        seen_row_ids.add(row_id)
                    if table_name not in RESTORABLE_TABLES:
                        _validate_protected_row(model, payload, organization.id)
                        summary["protected"] += 1
                        protected_count += 1
                        continue
                    outcome, change, message = _plan_row(
                        db, model, payload, organization.id
                    )
                    if outcome == "create":
                        summary["creates"] += 1
                        create_count += 1
                        plan.append(change or {})
                    elif outcome == "update":
                        summary["updates"] += 1
                        update_count += 1
                        plan.append(change or {})
                    elif outcome == "unchanged":
                        summary["unchanged"] += 1
                        unchanged_count += 1
                    else:
                        summary["conflicts"] += 1
                        conflict_count += 1
                        if message and len(messages) < 100:
                            messages.append(message)
            if rows_seen != item["records"] or digest.hexdigest() != item["sha256"]:
                raise DataRestoreInvalid(f"{table_name} data does not match its manifest")
            summary["records"] = rows_seen
            table_summary[table_name] = summary
            record_count += rows_seen

        invalid_dependencies = _invalid_plan_dependencies(
            db, plan, registry, organization.id
        )
        if invalid_dependencies:
            filtered_plan: list[dict[str, Any]] = []
            for index, item in enumerate(plan):
                error = invalid_dependencies.get(index)
                if not error:
                    filtered_plan.append(item)
                    continue
                summary = table_summary[item["table"]]
                if item.get("action") == "create":
                    summary["creates"] -= 1
                    create_count -= 1
                else:
                    summary["updates"] -= 1
                    update_count -= 1
                summary["conflicts"] += 1
                conflict_count += 1
                if len(messages) < 100:
                    messages.append(error)
            plan = filtered_plan

        for item in files:
            digest = sha256()
            size = 0
            with archive.open(item["path"]) as source:
                while chunk := source.read(1024 * 1024):
                    digest.update(chunk)
                    size += len(chunk)
            if size != item["size_bytes"] or digest.hexdigest() != item["sha256"]:
                raise DataRestoreInvalid(f"{item['path']} does not match its manifest")

        if record_count != manifest.get("record_count"):
            raise DataRestoreInvalid("Restore manifest total record count is invalid")
        if len(files) != manifest.get("file_count"):
            raise DataRestoreInvalid("Restore manifest total file count is invalid")
        missing_files = manifest.get("missing_files")
        if (
            not isinstance(missing_files, list)
            or manifest.get("missing_file_count") != len(missing_files)
            or any(not isinstance(item, str) for item in missing_files)
        ):
            raise DataRestoreInvalid("Restore manifest missing-file inventory is invalid")
        if protected_count:
            messages.append(
                "Authentication, billing, audit, transaction, custody, and other protected records are validation-only."
            )
        if files:
            messages.append(
                "Media entries were checksum-verified; this restore stage does not write files to storage."
            )
        if create_count:
            messages.append(
                "Missing eligible rows passed global id, unique-key, tenant, and foreign-key checks and can be rehydrated."
            )
        plan.sort(
            key=lambda item: (
                0 if item.get("action") == "create" else 1,
                CREATE_TABLE_RANK.get(item["table"], len(CREATE_TABLE_RANK)),
                item["id"],
            )
        )
        plan_json = _canonical(plan)
        plan_bytes = plan_json.encode("utf-8")
        if len(plan_bytes) > settings.max_data_restore_rollback_bytes:
            raise DataRestoreInvalid("Restore rollback snapshot exceeds the configured limit")
        return RestoreAnalysis(
            archive_sha256=upload.sha256,
            archive_size_bytes=upload.size_bytes,
            source_schema_revision=source_revision,
            source_exported_at=_parse_utc(manifest.get("generated_at_utc")),
            record_count=record_count,
            file_count=len(files),
            create_count=create_count,
            update_count=update_count,
            unchanged_count=unchanged_count,
            conflict_count=conflict_count,
            protected_count=protected_count,
            table_summary=table_summary,
            validation_messages=messages,
            plan=plan,
            plan_json=plan_json,
            plan_sha256=sha256(plan_bytes).hexdigest(),
        )


def _assert_current_values(row: Any, values: dict[str, Any], label: str) -> None:
    for name, expected in values.items():
        actual = _json_value(getattr(row, name))
        if _canonical(actual) != _canonical(expected):
            raise DataRestoreConflict(f"{label} changed after restore review")


def apply_restore_plan(db: Session, analysis: RestoreAnalysis, organization_id: int) -> tuple[str, str]:
    if analysis.conflict_count:
        raise DataRestoreConflict("Restore plan contains unresolved conflicts")
    registry = _table_registry()
    create_items = sorted(
        (item for item in analysis.plan if item.get("action") == "create"),
        key=lambda item: (
            CREATE_TABLE_RANK.get(item["table"], len(CREATE_TABLE_RANK)),
            item["id"],
        ),
    )
    update_items = [
        item for item in analysis.plan if item.get("action", "update") == "update"
    ]
    for item in create_items:
        model = registry[item["table"]]
        table = model.__table__
        existing = db.execute(
            select(table.c.id).where(table.c.id == item["id"])
        ).scalar_one_or_none()
        if existing is not None:
            raise DataRestoreConflict("A restore record id was claimed after approval")
        columns = {column.name: column for column in table.columns}
        values = {
            name: _deserialize(columns[name], value)
            for name, value in item["after"].items()
        }
        if values.get("organization_id") != organization_id:
            raise DataRestoreConflict("Restore plan contains a cross-organization create")
        db.add(model(**values))
        db.flush()

    for item in update_items:
        model = registry[item["table"]]
        row = db.get(model, item["id"])
        if row is None or getattr(row, "organization_id", None) != organization_id:
            raise DataRestoreConflict("Restore target disappeared after approval")
        _assert_current_values(row, item["before"], f"{item['table']} row {item['id']}")
        columns = {column.name: column for column in model.__table__.columns}
        for name, value in item["after"].items():
            setattr(row, name, _deserialize(columns[name], value))
    db.flush()
    rollback_json = analysis.plan_json
    return rollback_json, sha256(rollback_json.encode("utf-8")).hexdigest()


def rollback_restore_plan(db: Session, rollback_json: str, organization_id: int) -> int:
    try:
        plan = json.loads(rollback_json)
    except json.JSONDecodeError as exc:
        raise DataRestoreConflict("Stored rollback snapshot is invalid") from exc
    if not isinstance(plan, list):
        raise DataRestoreConflict("Stored rollback snapshot is invalid")
    registry = _table_registry()
    validated: list[tuple[dict[str, Any], Any, Any]] = []
    for item in plan:
        if not isinstance(item, dict) or item.get("table") not in RESTORABLE_TABLES:
            raise DataRestoreConflict("Stored rollback snapshot contains an invalid target")
        action = item.get("action", "update")
        if action not in {"create", "update"}:
            raise DataRestoreConflict("Stored rollback snapshot contains an invalid action")
        model = registry[item["table"]]
        row = db.get(model, item.get("id"))
        if row is None or getattr(row, "organization_id", None) != organization_id:
            raise DataRestoreConflict("A restored record no longer exists")
        after = item.get("after")
        before = item.get("before")
        if not isinstance(after, dict) or (
            action == "update" and not isinstance(before, dict)
        ) or (action == "create" and before is not None):
            raise DataRestoreConflict("Stored rollback snapshot is invalid")
        _assert_current_values(row, after, f"{item['table']} row {item['id']}")
        validated.append((item, model, row))

    for item, model, row in validated:
        if item.get("action", "update") != "update":
            continue
        before = item["before"]
        columns = {column.name: column for column in model.__table__.columns}
        for name, value in before.items():
            if name not in columns or name in IMMUTABLE_COLUMNS:
                raise DataRestoreConflict("Stored rollback snapshot contains an invalid field")
            setattr(row, name, _deserialize(columns[name], value))
    db.flush()

    create_rows = sorted(
        (
            (item, row)
            for item, _model, row in validated
            if item.get("action") == "create"
        ),
        key=lambda pair: (
            CREATE_TABLE_RANK.get(pair[0]["table"], len(CREATE_TABLE_RANK)),
            pair[0]["id"],
        ),
        reverse=True,
    )
    for _item, row in create_rows:
        db.delete(row)
        db.flush()
    return len(plan)
