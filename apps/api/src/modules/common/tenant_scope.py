from typing import Any, Iterable

from fastapi import HTTPException, status


def is_super_admin(actor: dict[str, Any]) -> bool:
    return actor.get("role") == "super_admin"


def can_access_tenant(actor: dict[str, Any], tenant_id: str | None) -> bool:
    if tenant_id is None:
        return is_super_admin(actor)
    return is_super_admin(actor) or actor.get("tenant_id") == tenant_id


def require_tenant_access(
    actor: dict[str, Any],
    tenant_id: str | None,
    *,
    detail: str,
) -> None:
    if not can_access_tenant(actor, tenant_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=detail,
        )


def filter_records_for_actor(
    actor: dict[str, Any],
    records: Iterable[dict[str, Any]],
) -> list[dict[str, Any]]:
    if is_super_admin(actor):
        return list(records)
    actor_tenant_id = actor.get("tenant_id")
    return [
        record
        for record in records
        if record.get("tenant_id") == actor_tenant_id
    ]
