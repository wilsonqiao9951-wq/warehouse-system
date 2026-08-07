from __future__ import annotations

import re


REGION_CODE_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


def normalize_region_code(value: str | None) -> str | None:
    cleaned = (value or "").strip().lower()
    if not cleaned:
        return None
    if not 2 <= len(cleaned) <= 64 or not REGION_CODE_PATTERN.fullmatch(cleaned):
        raise ValueError(
            "Region must be 2-64 lowercase letters, numbers, or single hyphens"
        )
    return cleaned


def residency_status(
    required_region: str | None,
    deployment_region: str,
) -> str:
    if required_region is None:
        return "unrestricted"
    try:
        current_region = normalize_region_code(deployment_region)
    except ValueError:
        return "blocked"
    return "compliant" if required_region == current_region else "blocked"


def residency_block_reason(
    required_region: str | None,
    deployment_region: str,
) -> str | None:
    if residency_status(required_region, deployment_region) != "blocked":
        return None
    return (
        f"Organization data residency requires {required_region}; "
        f"this deployment is {deployment_region}"
    )
