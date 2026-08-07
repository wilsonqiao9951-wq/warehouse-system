from __future__ import annotations

from dataclasses import dataclass

from app.models.entities import UserRole


USERS_READ = "users.read"
AUDIT_READ = "audit.read"
AUDIT_EXPORT = "audit.export"
REPORTS_READ = "reports.read"
REPORTS_EXPORT = "reports.export"
INTEGRATIONS_READ = "integrations.read"
INTEGRATIONS_MANAGE = "integrations.manage"


@dataclass(frozen=True)
class PermissionDefinition:
    code: str
    name: str
    description: str
    default_roles: frozenset[UserRole]
    sensitive: bool = False


PERMISSIONS = (
    PermissionDefinition(
        USERS_READ,
        "View employee directory",
        "View tenant users and employee performance identities.",
        frozenset({UserRole.ADMIN, UserRole.MANAGER}),
    ),
    PermissionDefinition(
        AUDIT_READ,
        "View audit evidence",
        "Search and summarize the tenant audit trail.",
        frozenset({UserRole.ADMIN, UserRole.MANAGER}),
        True,
    ),
    PermissionDefinition(
        AUDIT_EXPORT,
        "Export audit evidence",
        "Create password-confirmed audit CSV exports.",
        frozenset({UserRole.ADMIN}),
        True,
    ),
    PermissionDefinition(
        REPORTS_READ,
        "View operational reports",
        "View team performance, warehouse, and abnormal-usage reports.",
        frozenset({UserRole.ADMIN, UserRole.MANAGER}),
    ),
    PermissionDefinition(
        REPORTS_EXPORT,
        "Export operational analytics",
        "Create password-confirmed work-order analytics CSV exports.",
        frozenset({UserRole.ADMIN}),
        True,
    ),
    PermissionDefinition(
        INTEGRATIONS_READ,
        "View integrations",
        "View external-system configuration and delivery logs without secrets.",
        frozenset({UserRole.ADMIN, UserRole.MANAGER}),
        True,
    ),
    PermissionDefinition(
        INTEGRATIONS_MANAGE,
        "Manage integrations",
        "Create, change, rotate, retry, or disable external integrations.",
        frozenset({UserRole.ADMIN}),
        True,
    ),
)

PERMISSION_BY_CODE = {item.code: item for item in PERMISSIONS}
ALL_PERMISSION_CODES = frozenset(PERMISSION_BY_CODE)


def default_permission_codes(role: UserRole) -> set[str]:
    return {item.code for item in PERMISSIONS if role in item.default_roles}


def effective_permission_codes(
    role: UserRole,
    overrides: dict[str, bool] | None = None,
) -> set[str]:
    if role == UserRole.ADMIN:
        return set(ALL_PERMISSION_CODES)
    effective = default_permission_codes(role)
    for code, allowed in (overrides or {}).items():
        if code not in ALL_PERMISSION_CODES:
            continue
        if allowed:
            effective.add(code)
        else:
            effective.discard(code)
    return effective
